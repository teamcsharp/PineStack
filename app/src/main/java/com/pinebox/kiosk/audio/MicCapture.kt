package com.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.SystemClock
import android.util.Log
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * THE TABLET'S EAR, AND WHY IT IS NATIVE.
 *
 * "It is imperative that I'm able to interface with the system through the
 * microphone just like I am through the Pine Box and through the Nabu
 * device."
 *
 * The obvious road was `getUserMedia` in the WebView, and the talk dot was
 * written that way. It cannot work, and the reason is not a permission -
 * it is the origin. Measured on the device:
 *
 *     origin  : http://10.89.1.246:8096
 *     secure  : false
 *     navigator.mediaDevices : undefined
 *
 * Chromium removes `mediaDevices` ENTIRELY from a page that is not a
 * secure context, and a plain-http LAN address is not one. There is no
 * permission to grant and no flag on the WebView that puts it back; the
 * object the page would call simply does not exist. Granting RECORD_AUDIO
 * to the app - which was also missing, and is now granted - changes
 * nothing about that.
 *
 * The two ways out were (a) move the panel onto a trustworthy origin, by
 * proxying the whole station through a loopback port inside this app, or
 * (b) do the listening in Kotlin and hand the words to JavaScript. This is
 * (b), for four reasons that are about more than avoiding the problem:
 *
 *   - 16 kHz MONO, EXACTLY. Wyoming whisper does not resample. A 24 kHz
 *     clip travels the protocol cleanly, gets logged as "Processing audio
 *     with duration", and comes back EMPTY - measured, twice, before the
 *     station-side bridge learned to resample. AudioRecord can be asked
 *     for 16 kHz directly, so the words are never at the wrong speed.
 *   - THE ECHO CANCELLER. This terminal plays the show out of its own
 *     speaker. The station has already lost time to a microphone hearing
 *     the broadcast and acting on it. AcousticEchoCanceler is a platform
 *     effect attached to the capture session; a WebView stream cannot be
 *     given one selectively.
 *   - IT KEEPS LISTENING WITH THE SCREEN OFF, which is what a wake word
 *     needs and what the Nabu device does.
 *   - NO AUDIO FOCUS FIGHT. The capture session is ours, so it can duck
 *     playback through [MediaFocus] rather than racing it.
 *
 * WHAT THIS CLASS DOES NOT DO: decide what the words mean. It returns PCM
 * and a level. Turning sound into text is the station's job (the whisper
 * bridge), and deciding what a sentence MEANS is the caller's - which is
 * what lets one ear serve a song request, a chat line and a wake word.
 */
class MicCapture(
    private val context: Context? = null,
    private val attributeToContext: Boolean = false,
) {

    /** What the model wants, so it is what we ask the hardware for. */
    private val rate = 16_000
    private val encoding = AudioFormat.ENCODING_PCM_16BIT

    /**
     * ASK FOR THE BACK MICROPHONE, BECAUSE THAT IS WHERE THE MIC IS.
     *
     * Measured on the device, walking the codec's analogue mux across
     * every pin while one capture was held open, same room, same second:
     *
     *     AIN0  (what the HAL chooses)   -37.6 dBFS
     *     AIN1                           -25.9 dBFS
     *     AIN2                           -14.0 dBFS   <- the microphone
     *
     * Fifteen times the level. The vendor's own files then explain it
     * exactly. `/vendor/etc/audio_device.xml` maps paths to pins:
     *
     *     builtin_Mic_SingleMic   PGA L/R Mux = AIN0     <- asked for
     *     builtin_Mic_BackMic     PGA L/R Mux = AIN2     <- wanted
     *
     * and `/vendor/etc/audio_param/MicInfo_AudioParam.xml` describes two
     * microphones on this board:
     *
     *     amic_proj,main_mic   address "bottom"   BUILTIN_MIC
     *     amic_proj,sub_mic    address "back"     BUILTIN_MIC|BACK_MIC
     *
     * So the microphone the operator speaks into is the one this HAL calls
     * the BACK mic, and a plain capture asks for the other one. Android has
     * a proper API for saying which: AudioRecord.setPreferredDevice with
     * the AudioDeviceInfo whose address is "back".
     *
     * WHAT WAS TRIED AND REJECTED, so it is not tried again:
     *   - Forcing the mux with `tinymix` works and is 15x louder, but
     *     needs root AND must be redone on every capture, because the HAL
     *     rewrites the mux each time a stream opens.
     *   - Asking for STEREO, hoping to be given the DualMic path (which is
     *     L=AIN0, R=AIN2): measured, the HAL still chose AIN0/AIN0 and
     *     both channels read an identical 0.0438. Channel count does not
     *     select the path.
     *   - Every AudioSource constant (MIC, VOICE_RECOGNITION,
     *     VOICE_COMMUNICATION, CAMCORDER, UNPROCESSED, DEFAULT), with and
     *     without effects: all within 20 dB of each other and all quiet,
     *     because all of them landed on AIN0.
     */
    @Volatile var preferBackMic: Boolean = true

    /** What we asked for and what we were actually given - reported rather
     *  than assumed, because setPreferredDevice is a REQUEST. */
    @Volatile var micChosen: String = ""
        private set
    @Volatile var micRouted: String = ""
        private set

        @Volatile var stereo: Boolean = false

    /** Which channel carried the sound, for the readout. */
    @Volatile var leftLevel: Float = 0f
        private set
    @Volatile var rightLevel: Float = 0f
        private set

    private val channel: Int
        get() = if (stereo) AudioFormat.CHANNEL_IN_STEREO else AudioFormat.CHANNEL_IN_MONO

    private val running = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var worker: Thread? = null
    private var sink = ByteArrayOutputStream()

    /**
     * WHICH TAKE THIS IS, AND WHY A COUNTER RATHER THAN A FLAG.
     *
     * The read loop runs on a daemon thread and [stop] gives it 700 ms to
     * notice that `running` has gone false. A blocking AudioRecord.read
     * does not always come back inside that, so the thread can outlive the
     * take it belongs to - and `sink`, `level` and `lastError` are FIELDS.
     * An orphan that wakes up after the next take has started therefore
     * writes ITS samples into the NEW take's buffer, and a `running` flag
     * cannot tell the two apart because by then it is true again.
     *
     * Measured on the device, starting a second take three seconds into a
     * first: the new take reported 2.72 seconds of audio 1.2 seconds after
     * it began - more sound than there had been time for - and carried
     * "the microphone was taken by something else" as its error, which was
     * the DISCARDED thread's dying complaint about having its recorder
     * released. Both readings were about a take that no longer existed.
     * Interleaved samples from two threads are not a long clip either;
     * they are a garbled one, which transcribes into nothing.
     *
     * So every take gets a number, the worker keeps the number it was born
     * with, and it may only touch the shared fields while that is still
     * the current one. An orphan cannot corrupt what came after it.
     */
    private val takeId = AtomicInteger(0)

    /* Effects are held so they can be released with the session. Left
     * attached, they outlive the AudioRecord and leak the session. */
    private var canceller: AcousticEchoCanceler? = null
    private var suppressor: NoiseSuppressor? = null
    private var gain: AutomaticGainControl? = null

    /** 0..1, the loudest thing heard in the last buffer. Read from JS at
     *  animation rate to drive the talk dot's particles, so it must be a
     *  plain field read and never a lock. */
    @Volatile var level: Float = 0f
        private set

    @Volatile private var metricFrame = MicTelemetry.idle()

    /** A cheap, immutable snapshot. All PCM and spectrum work runs in the read loop. */
    internal fun micMetrics(): MicTelemetry.Frame =
        if (running.get()) metricFrame.at(SystemClock.elapsedRealtime()) else MicTelemetry.idle()

    /** RMS over the whole take, so a silent recording can be reported as
     *  silent instead of sent to whisper to come back empty. */
    @Volatile private var sumSquares: Double = 0.0
    @Volatile private var sampleCount: Long = 0

    @Volatile var lastError: String? = null
        private set

    val isRunning: Boolean get() = running.get()

    /** How many seconds are in the buffer right now. */
    val seconds: Float get() = sink.size() / (rate * 2f)

    /** When the take began, by the wall clock, so the samples can be
     *  checked against the time they claim to cover - see [wallSeconds]. */
    @Volatile private var startedAtMs: Long = 0L

    /**
     * How long the take has been open by the CLOCK, not by the sample
     * count. The two should agree; when they do not, the worker thread
     * stopped reading part way through and the clip is missing the
     * difference. That is a silent failure otherwise: a clip of the first
     * two seconds of a ten-second sentence transcribes into a fragment, or
     * into nothing, and looks exactly like a microphone that did not hear.
     */
    val wallSeconds: Float
        get() = if (startedAtMs <= 0L) 0f
        else (System.currentTimeMillis() - startedAtMs) / 1000f

    /** Set when [start] found a take already open and threw it away, so
     *  the caller can say that it did rather than quietly inheriting it. */
    @Volatile var replacedStaleTake: Boolean = false
        private set

    /**
     * Which HAL input to ask for, and whether to attach the effects.
     *
     * Both are overridable ONLY so they can be measured. On a GSI the
     * stock ROM's HAL tuning is not necessarily reachable through every
     * source constant, and "the microphone is silent" and "this particular
     * source is silent" look identical from the app. The first take on
     * this device came back at -73 dBFS with VOICE_RECOGNITION and all
     * three effects on, which is a number that means nothing until the
     * other sources have been tried against the same room.
     */
    /* MIC, NOT VOICE_RECOGNITION - and this is the whole fix.
     *
     * VOICE_RECOGNITION is the "right" constant: it asks the HAL for the
     * speech-tuned path, and it is what a transcriber should want. On this
     * GSI it is DEAD. Measured with real sound in the room, every source
     * back to back inside one minute:
     *
     *     MIC                  peak 0.3545   (0.6271 on the back mic)
     *     CAMCORDER            peak 0.4974
     *     VOICE_COMMUNICATION  peak 0.1004
     *     VOICE_RECOGNITION    peak 0.0004   <- the old default
     *     UNPROCESSED          peak 0.0003
     *
     * A factor of fifteen hundred between MIC and VOICE_RECOGNITION.
     *
     * An earlier sweep of the same sources had them all within 20 dB of
     * each other and all quiet, and I read that as "the microphone is
     * broken below the app". It was measured in a silent room, so all it
     * compared was noise floors - the sources only separate once there is
     * something to hear. That is why this comment carries the numbers and
     * the conditions they were taken under, and not just the verdict.
     */
    @Volatile var source: Int = MediaRecorder.AudioSource.MIC
    @Volatile var withEffects: Boolean = true

    /** Noise suppression and auto gain as well as the echo canceller. Off:
     *  they cost 8 dB and bury a quiet voice. */
    @Volatile var fullEffects: Boolean = false

    /**
     * Open the microphone and start filling the buffer.
     *
     * @return null on success, or a sentence saying what stopped it. The
     *   sentence is shown to the operator, so it says what to DO about it
     *   rather than naming a constant.
     */
    /**
     * A NEW TAKE IS A NEW TAKE.
     *
     * This used to return success the moment it found a capture already
     * running - and then keep filling the SAME sink, because the reset of
     * the buffer sits below that early return. So a take that was never
     * stopped (a torn-down view, a thrown promise, a second press while
     * the first was still settling) was not replaced by the next press; it
     * was extended. The next micStop then handed whisper everything since
     * whenever that orphan began, and the operator got back a sentence
     * from minutes ago, or a fragment of one, or nothing - for words he
     * had just spoken.
     *
     * Measured while proving this out: a take that stayed open 150 seconds
     * longer than intended came back as "So I'm going to make a small hole
     * in the middle of the hole", which was in the room at some point but
     * was not what anybody had just said. A wrong answer is worse than an
     * error message, because it cannot be recognised as a fault.
     *
     * So an open capture is stopped and discarded here, and the fact is
     * recorded: a caller that wanted to know it was inheriting a mess can
     * say so, and nothing silently carries over.
     */
    @Synchronized
    fun start(): String? {
        replacedStaleTake = false
        if (running.get()) {
            stop()
            replacedStaleTake = true
        }
        /* CLAIMED BEFORE ANYTHING ELSE IS TOUCHED. From this line on, a
         * thread still alive from a previous take is holding a number that
         * is no longer current, so it cannot write to lastError, level or
         * the sink - including in the moments between here and the new
         * worker actually starting, which is exactly when the fields are
         * being reset. */
        val mine = takeId.incrementAndGet()
        lastError = null

        val minimum = AudioRecord.getMinBufferSize(rate, channel, encoding)
        if (minimum <= 0) {
            return "this device reports no usable 16 kHz mono capture buffer"
        }
        /* Four times the minimum: the read loop also hashes and measures,
         * and an underrun here is a click in the middle of a word. */
        val size = minimum * 4

        val record = try {
            if (attributeToContext && context != null) {
                AudioRecord.Builder()
                    .setContext(context)
                    .setAudioSource(source)
                    .setAudioFormat(AudioFormat.Builder()
                        .setSampleRate(rate)
                        .setEncoding(encoding)
                        .setChannelMask(channel)
                        .build())
                    .setBufferSizeInBytes(size)
                    .build()
            } else {
                AudioRecord(source, rate, channel, encoding, size)
            }
        } catch (err: Exception) {
            return "the microphone could not be opened: " + (err.message ?: err.javaClass.simpleName)
        }

        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            return "the microphone did not initialise - is RECORD_AUDIO granted?"
        }

        if (withEffects) attachEffects(record.audioSessionId)
        chooseMic(record)

        sink = ByteArrayOutputStream()
        sumSquares = 0.0
        sampleCount = 0
        level = 0f
        metricFrame = MicTelemetry.waiting()
        startedAtMs = System.currentTimeMillis()
        recorder = record
        running.set(true)

        try {
            record.startRecording()
        } catch (err: Exception) {
            stop()
            return "the microphone refused to start: " + (err.message ?: "")
        }
        if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
            stop()
            return "the microphone opened but is not recording - another app may hold it"
        }

        micRouted = try {
            val got = record.routedDevice
            if (got == null) "(the policy named no device)"
            else "routed to id " + got.id + " address '" + got.address + "'"
        } catch (err: Exception) { "(routed device unreadable)" }

        worker = thread(name = "pine-mic", isDaemon = true) {
            val buf = ShortArray(size / 2)
            val telemetry = MicTelemetry(SystemClock.elapsedRealtime())
            while (running.get() && takeId.get() == mine) {
                val got = try {
                    record.read(buf, 0, buf.size)
                } catch (err: Exception) {
                    if (takeId.get() == mine) lastError = err.message
                    break
                }
                /* Checked AGAIN after the read - BOTH of them - because
                 * the read is where the time goes. The loop's own condition
                 * was tested before a blocking call that can sit there for
                 * a whole buffer, and everything below writes to fields
                 * that may by then belong to somebody else.
                 *
                 * Measured: calling micStop with no take open answered with
                 * 0.16 seconds of audio - one buffer - because the previous
                 * take's last read landed after stop() had already emptied
                 * the sink. One buffer is not much sound, but it is a
                 * phantom take where there should be none, and at the start
                 * of a real one it is a sixth of a second of the last
                 * conversation in front of the first word of this one. */
                if (!running.get() || takeId.get() != mine) break
                if (got <= 0) {
                    /* ERROR_INVALID_OPERATION means the session died under
                     * us - usually another app taking the mic. Say so. */
                    if (got == AudioRecord.ERROR_INVALID_OPERATION) {
                        lastError = "the microphone was taken by something else"
                        break
                    }
                    continue
                }
                var peak = 0f
                var square = 0.0
                var lPeak = 0f
                var rPeak = 0f

                /* DE-INTERLEAVE, AND KEEP THE MICROPHONE.
                 *
                 * A stereo frame is L,R,L,R... and on this board only the
                 * right channel has a microphone on it (see the header).
                 * The left is the dead AIN0 pin, so mixing the two would
                 * halve the signal and add nothing but that pin's noise.
                 * It is not a downmix; it is a choice. */
                val frames = if (stereo) got / 2 else got
                if (frames == 0) continue
                val bytes = ByteArray(frames * 2)
                for (f in 0 until frames) {
                    val s: Int
                    if (stereo) {
                        val l = buf[f * 2].toInt()
                        val r = buf[f * 2 + 1].toInt()
                        val lv = abs(l) / 32768f
                        val rv = abs(r) / 32768f
                        if (lv > lPeak) lPeak = lv
                        if (rv > rPeak) rPeak = rv
                        s = r
                    } else {
                        s = buf[f].toInt()
                    }
                    /* Little-endian PCM16, because that is what a WAV
                     * declares and what the station's reader expects. */
                    bytes[f * 2] = (s and 0xFF).toByte()
                    bytes[f * 2 + 1] = ((s shr 8) and 0xFF).toByte()
                    val v = abs(s) / 32768f
                    if (v > peak) peak = v
                    square += (v * v).toDouble()
                }
                if (stereo) {
                    leftLevel = if (lPeak > leftLevel) lPeak else (leftLevel * 0.8f + lPeak * 0.2f)
                    rightLevel = if (rPeak > rightLevel) rPeak else (rightLevel * 0.8f + rPeak * 0.2f)
                }
                synchronized(this) { sink.write(bytes, 0, bytes.size) }
                sumSquares += square
                sampleCount += frames.toLong()
                /* Decay rather than jump: the dot's particles read this
                 * every frame and a raw peak makes them flicker. */
                level = if (peak > level) peak else (level * 0.72f + peak * 0.28f)
                val frame = telemetry.feed(buf, frames, stereo,
                    sqrt(square / frames).toFloat(), peak, SystemClock.elapsedRealtime())
                if (running.get() && takeId.get() == mine) metricFrame = frame
            }
        }
        return null
    }

    /**
     * Stop, and hand back what was heard as a WAV.
     *
     * @return the clip, or null if nothing was captured.
     */
    @Synchronized
    fun stop(): ByteArray? {
        running.set(false)
        worker?.let { try { it.join(700) } catch (ignored: InterruptedException) {} }
        worker = null

        recorder?.let { rec ->
            try { if (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) rec.stop() }
            catch (err: Exception) { Log.w(TAG, "stop", err) }
            try { rec.release() } catch (err: Exception) { Log.w(TAG, "release", err) }
        }
        recorder = null
        releaseEffects()
        level = 0f
        metricFrame = MicTelemetry.idle()

        val pcm = sink.toByteArray()
        sink = ByteArrayOutputStream()
        if (pcm.isEmpty()) return null
        return wav(normalise(pcm))
    }

    /** Throw the take away - the operator cancelled. */
    @Synchronized
    fun cancel() {
        stop()
    }

    /** How loud the whole take was, 0..1. Below about 0.002 it is a silent
     *  room and there is no point sending it anywhere. */
    fun takeLevel(): Float =
        if (sampleCount <= 0) 0f else sqrt(sumSquares / sampleCount).toFloat()

    /* ------------------------------------------------------------------ */

    private fun attachEffects(session: Int) {
        /* Each is optional on purpose. These are HAL-provided effects and a
         * GSI on a tablet whose HAL was written for the stock ROM may offer
         * none of them; that is a quieter microphone, not a broken one. */
        /* THE ECHO CANCELLER STAYS. THE OTHER TWO GO.
         *
         * They are not equivalent. The canceller is what stops this
         * terminal transcribing its own broadcast - the station has
         * already lost hours to a microphone hearing the show and acting
         * on it (#1154), and this tablet plays the show out of a speaker a
         * hand's width from the microphone. It earns its keep.
         *
         * Noise suppression and automatic gain do not. Measured with all
         * three on versus all three off, same room, same minute:
         *
         *     MIC  effects on   -65.8 dBFS
         *     MIC  effects off  -57.2 dBFS
         *
         * Eight decibels, and on a first real take the operator's speech
         * arrived at RMS 0.014 and whisper made nothing of it. A noise
         * suppressor tuned for a phone call treats a quiet, distant voice
         * as the noise, and automatic gain spends its range on the room
         * between words. Level is recovered afterwards instead, where it
         * can be done knowing the whole clip - see [normalise]. */
        if (AcousticEchoCanceler.isAvailable()) {
            canceller = try {
                AcousticEchoCanceler.create(session)?.apply { enabled = true }
            } catch (err: Exception) { null }
        }
        if (fullEffects && NoiseSuppressor.isAvailable()) {
            suppressor = try {
                NoiseSuppressor.create(session)?.apply { enabled = true }
            } catch (err: Exception) { null }
        }
        if (fullEffects && AutomaticGainControl.isAvailable()) {
            gain = try {
                AutomaticGainControl.create(session)?.apply { enabled = true }
            } catch (err: Exception) { null }
        }
    }

    private fun releaseEffects() {
        try { canceller?.release() } catch (err: Exception) {}
        try { suppressor?.release() } catch (err: Exception) {}
        try { gain?.release() } catch (err: Exception) {}
        canceller = null; suppressor = null; gain = null
    }

    /** Which of the three effects the hardware actually gave us. Reported
     *  to the operator rather than assumed, because "the mic hears the
     *  show" is a real failure this station has already paid for. */
    /**
     * Point the capture at the back microphone.
     *
     * setPreferredDevice is a REQUEST, not an instruction - the policy may
     * refuse it - so what was actually granted is read back from
     * getRoutedDevice and reported. A silent refusal here would look
     * exactly like the bug it is meant to fix.
     */
    private fun chooseMic(record: AudioRecord) {
        micChosen = ""
        micRouted = ""
        if (!preferBackMic) return
        val audio = try {
            context?.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        } catch (err: Exception) { null } ?: return

        val inputs = try {
            audio.getDevices(AudioManager.GET_DEVICES_INPUTS)
        } catch (err: Exception) { return }

        /* By ADDRESS first - "back" is what MicInfo_AudioParam.xml calls
         * the sub mic, and it is the only unambiguous handle. Falling back
         * to the second built-in mic covers a build that reports the pair
         * without addresses; falling back to nothing at all is correct
         * when there is genuinely one microphone. */
        val builtins = inputs.filter { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }
        val back = builtins.firstOrNull { it.address == "back" }
            ?: builtins.firstOrNull { it.address.contains("back", ignoreCase = true) }
            ?: if (builtins.size > 1) builtins[1] else null

        if (back == null) {
            micChosen = "no back mic listed (" + builtins.size + " built-in)"
            return
        }
        val took = try { record.setPreferredDevice(back) } catch (err: Exception) { false }
        micChosen = (if (took) "asked for " else "REFUSED ") +
            "built-in mic id " + back.id + " address '" + back.address + "'"
    }

    /** Which channel is carrying sound, for the readout and for proving
     *  the stereo trick is doing what the measurement said it would. */
    fun channelReport(): String =
        if (!stereo) "mono" else
            "L " + String.format("%.4f", leftLevel) + " / R " + String.format("%.4f", rightLevel)

    fun effects(): String {
        val on = mutableListOf<String>()
        if (canceller?.enabled == true) on += "echo cancel"
        if (suppressor?.enabled == true) on += "noise suppress"
        if (gain?.enabled == true) on += "auto gain"
        return if (on.isEmpty()) "none" else on.joinToString(", ")
    }

    /**
     * BRING THE WHOLE CLIP UP TO A LEVEL THE MODEL CAN READ.
     *
     * Done here, at the end, rather than by the platform's automatic gain
     * during the take - because here the whole clip is known. Automatic
     * gain has to guess from what it has heard so far, so it spends its
     * range on the room between words and then clamps down on the first
     * syllable; that is exactly how a real take arrived at RMS 0.014 and
     * came back with no words in it.
     *
     * Peak normalisation, to 0.85 rather than 1.0, so a single transient -
     * a knock on the table - cannot flatten the speech around it, and with
     * a ceiling on the boost: a clip whose loudest moment is the noise
     * floor is a silent room, and multiplying silence by sixty produces a
     * very loud silent room, not words.
     */
    private fun normalise(pcm: ByteArray): ByteArray {
        var peak = 0
        var at = 0
        while (at + 1 < pcm.size) {
            val v = ((pcm[at].toInt() and 0xFF) or (pcm[at + 1].toInt() shl 8)).toShort().toInt()
            val a = if (v < 0) -v else v
            if (a > peak) peak = a
            at += 2
        }
        if (peak <= 0) return pcm
        val want = 0.85f * 32767f
        var factor = want / peak
        if (factor <= 1.05f) return pcm      /* already loud enough */
        if (factor > 24f) factor = 24f       /* 27 dB is the sensible ceiling */

        val out = ByteArray(pcm.size)
        at = 0
        while (at + 1 < pcm.size) {
            val v = ((pcm[at].toInt() and 0xFF) or (pcm[at + 1].toInt() shl 8)).toShort().toInt()
            var scaled = (v * factor).toInt()
            if (scaled > 32767) scaled = 32767
            if (scaled < -32768) scaled = -32768
            out[at] = (scaled and 0xFF).toByte()
            out[at + 1] = ((scaled shr 8) and 0xFF).toByte()
            at += 2
        }
        lift = factor
        return out
    }

    /** How much the clip had to be lifted, for the readout. */
    @Volatile var lift: Float = 1f
        private set

    /** A 44-byte canonical RIFF header in front of the samples.
     *
     *  ALWAYS ONE CHANNEL, whatever the hardware was asked for: the read
     *  loop keeps a single channel, so the file genuinely is mono and must
     *  say so. A stereo header over mono samples would play at half speed
     *  and transcribe as nothing. */
    private fun wav(pcm: ByteArray): ByteArray {
        val out = ByteArray(44 + pcm.size)
        val channels = 1
        val bits = 16
        val byteRate = rate * channels * bits / 8
        val align = channels * bits / 8

        fun ascii(at: Int, s: String) {
            for (i in s.indices) out[at + i] = s[i].code.toByte()
        }
        fun le32(at: Int, v: Int) {
            out[at] = (v and 0xFF).toByte()
            out[at + 1] = ((v shr 8) and 0xFF).toByte()
            out[at + 2] = ((v shr 16) and 0xFF).toByte()
            out[at + 3] = ((v shr 24) and 0xFF).toByte()
        }
        fun le16(at: Int, v: Int) {
            out[at] = (v and 0xFF).toByte()
            out[at + 1] = ((v shr 8) and 0xFF).toByte()
        }

        ascii(0, "RIFF");  le32(4, 36 + pcm.size)
        ascii(8, "WAVE");  ascii(12, "fmt ")
        le32(16, 16);      le16(20, 1)
        le16(22, channels); le32(24, rate)
        le32(28, byteRate); le16(32, align)
        le16(34, bits);    ascii(36, "data"); le32(40, pcm.size)
        System.arraycopy(pcm, 0, out, 44, pcm.size)
        return out
    }

    /** The name of the source in use, for the readout. */
    fun sourceName(): String = when (source) {
        MediaRecorder.AudioSource.MIC -> "MIC"
        MediaRecorder.AudioSource.VOICE_RECOGNITION -> "VOICE_RECOGNITION"
        MediaRecorder.AudioSource.VOICE_COMMUNICATION -> "VOICE_COMMUNICATION"
        MediaRecorder.AudioSource.CAMCORDER -> "CAMCORDER"
        MediaRecorder.AudioSource.UNPROCESSED -> "UNPROCESSED"
        MediaRecorder.AudioSource.DEFAULT -> "DEFAULT"
        else -> "source " + source
    }

    companion object {
        private const val TAG = "PineMic"
        const val RATE = 16_000

        /** By name, so the probe and the settings can say which one. */
        fun sourceByName(name: String): Int = when (name.uppercase()) {
            "MIC" -> MediaRecorder.AudioSource.MIC
            "VOICE_COMMUNICATION" -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
            "CAMCORDER" -> MediaRecorder.AudioSource.CAMCORDER
            "UNPROCESSED" -> MediaRecorder.AudioSource.UNPROCESSED
            "DEFAULT" -> MediaRecorder.AudioSource.DEFAULT
            "VOICE_RECOGNITION" -> MediaRecorder.AudioSource.VOICE_RECOGNITION
            else -> MediaRecorder.AudioSource.MIC
        }
    }
}

/** Worker-thread PCM measurements. Speech probability is an energy estimate,
 * not a recognizer or ML model; the bands are windowed Goertzel magnitudes. */
internal class MicTelemetry(private val startedAtMs: Long) {
    data class Frame(
        val rms: Float,
        val peak: Float,
        val speechProbability: Float,
        val vadState: String,
        val silenceElapsedMs: Long,
        val endpointTimeoutMs: Long,
        val remainingMs: Long,
        val threshold: Float,
        val bands: List<Float>,
        private val lastSpeechAtMs: Long = 0L,
    ) {
        fun at(nowMs: Long): Frame {
            if (vadState != "silence") return this
            val elapsed = (nowMs - lastSpeechAtMs).coerceAtLeast(0L)
            return copy(
                vadState = if (elapsed >= endpointTimeoutMs) "endpoint" else "silence",
                silenceElapsedMs = elapsed,
                remainingMs = (endpointTimeoutMs - elapsed).coerceAtLeast(0L),
            )
        }
    }

    companion object {
        const val ENDPOINT_MS = 4200L
        private const val WINDOW = 512
        private const val BAND_COUNT = 24
        private val EMPTY_BANDS = List(BAND_COUNT) { 0f }

        fun idle() = Frame(0f, 0f, 0f, "idle", 0L, ENDPOINT_MS, 0L, 0f, EMPTY_BANDS)
        fun waiting() = Frame(0f, 0f, 0f, "waiting", 0L, ENDPOINT_MS,
            ENDPOINT_MS, 0.01f, EMPTY_BANDS)
    }

    private val ring = ShortArray(WINDOW)
    private var ringAt = 0
    private var ringFilled = 0
    private val window = DoubleArray(WINDOW) { i ->
        0.5 - 0.5 * cos(2.0 * Math.PI * i / (WINDOW - 1))
    }
    private val coefficients = DoubleArray(BAND_COUNT) { i ->
        val hz = 80.0 * (7200.0 / 80.0).pow(i / (BAND_COUNT - 1.0))
        2.0 * cos(2.0 * Math.PI * hz / 16_000.0)
    }
    private var roomMin = Float.POSITIVE_INFINITY
    private var threshold = 0.01f
    private var heardSpeech = false
    private var lastSpeechAtMs = 0L

    fun feed(pcm: ShortArray, frames: Int, stereo: Boolean,
             rms: Float, peak: Float, nowMs: Long): Frame {
        for (i in 0 until frames) {
            ring[ringAt] = pcm[if (stereo) i * 2 + 1 else i]
            ringAt = (ringAt + 1) % WINDOW
            if (ringFilled < WINDOW) ringFilled++
        }

        if (!heardSpeech && nowMs - startedAtMs < 400L) {
            roomMin = minOf(roomMin, rms)
        } else if (!heardSpeech && roomMin.isFinite()) {
            threshold = (roomMin * 3.5f + 0.002f).coerceIn(0.003f, 0.12f)
        }

        val probability = (rms / threshold - 0.5f).coerceIn(0f, 1f)
        val speaking = rms > threshold
        if (speaking) {
            heardSpeech = true
            lastSpeechAtMs = nowMs
        }
        val state = when {
            speaking -> "speech"
            !heardSpeech -> "waiting"
            nowMs - lastSpeechAtMs >= ENDPOINT_MS -> "endpoint"
            else -> "silence"
        }
        val elapsed = if (heardSpeech && !speaking)
            (nowMs - lastSpeechAtMs).coerceAtLeast(0L) else 0L
        return Frame(rms, peak, probability, state, elapsed, ENDPOINT_MS,
            if (state == "endpoint") 0L else (ENDPOINT_MS - elapsed).coerceAtLeast(0L),
            threshold, spectrum(), lastSpeechAtMs)
    }

    private fun spectrum(): List<Float> {
        val start = if (ringFilled == WINDOW) ringAt else 0
        val offset = WINDOW - ringFilled
        return List(BAND_COUNT) { band ->
            var previous = 0.0
            var beforePrevious = 0.0
            val coefficient = coefficients[band]
            for (i in 0 until WINDOW) {
                val sample = if (i < offset) 0.0 else
                    ring[(start + i - offset) % WINDOW].toDouble() / 32768.0
                val current = sample * window[i] + coefficient * previous - beforePrevious
                beforePrevious = previous
                previous = current
            }
            val power = (previous * previous + beforePrevious * beforePrevious -
                coefficient * previous * beforePrevious).coerceAtLeast(0.0)
            (sqrt(sqrt(power) / (WINDOW / 4.0) / 0.12)).toFloat().coerceIn(0f, 1f)
        }
    }
}
