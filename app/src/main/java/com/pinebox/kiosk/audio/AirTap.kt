package com.pinebox.kiosk.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

/**
 * THE MIX, CAPTURED OFF THE PAGE.
 *
 * "The capture audio has static and noise in it. I need a Pure Mixed
 *  Broadcast." ... "I don't know why the audio stutters. It's unusual."
 *
 * WHY THE OLD ONE STUTTERED, MEASURED RATHER THAN GUESSED. The capture lived
 * in the page, fed by a ScriptProcessorNode, and a ScriptProcessor runs on
 * the MAIN thread. A blocked main thread does not delay a buffer, it LOSES
 * it - 85 ms at a time - and the ring writes the next buffer hard against the
 * last, so the waveform steps. Twenty seconds on this tablet:
 *
 *     29 gaps, 3.429 seconds lost      and later 42 gaps, 4.68 seconds
 *
 * Seventeen to twenty-three per cent of the sound absent. Nothing was ever
 * added to the signal; silence was cut out of it, hundreds of times a minute,
 * on a tablet at load average 22.
 *
 * AN AUDIOWORKLET WOULD HAVE FIXED IT AND IS NOT AVAILABLE: the panel is
 * served over plain http, isSecureContext is false, and Chromium gates
 * BaseAudioContext.audioWorklet behind a secure context. That road is closed
 * until the station speaks https.
 *
 * SO THE CAPTURE COMES OFF THE PAGE ENTIRELY. An AudioRecord on its own
 * thread cannot be starved by a WebView, eleven canvases, a screen encoder or
 * anything else the main thread is doing - the same reasoning that made the
 * screen recorder a service, and it has never dropped a frame.
 *
 * REMOTE_SUBMIX IS A SHARP TOOL AND IS TREATED AS ONE. On some builds
 * opening it reroutes the device's output into the submix and the speaker
 * goes quiet - which on a radio station is the worst thing this file could
 * possibly do. So it is OFF unless asked for and releases the moment it is
 * told to. Measured on THIS tablet: the submix appears ALONGSIDE headset(4)
 * and speaker(2) rather than replacing them, so output is duplicated, not
 * stolen. That is the good case and it is not to be assumed on another build.
 *
 * AND IT DOES NOT CARRY THE MIX HERE, WHICH IS THE FINDING THAT MATTERS.
 * Measured over the same ten seconds as the page's own capture:
 *
 *     native (submix)   rms    72.7   peak    615   hard steps  0
 *     page (script)     rms  6913.4   peak  32440   hard steps 19
 *
 * So the thread was never the only problem. This road is CLEAN - zero
 * discontinuities against nineteen, which confirms both the diagnosis and the
 * cure - but what arrives is a leakage-level signal about fifty times too
 * quiet, and raising STREAM_MUSIC barely moved it (peak 197 -> 210), so it is
 * not simply post-fader. Something on this build does not route the WebView's
 * playback into the submix.
 *
 * It is left here, working and off, because it costs nothing and is the right
 * shape the day that changes. The real unlock for the page's capture is a
 * SECURE CONTEXT, which would give it an AudioWorklet and take it off the
 * main thread where it belongs.
 */
class AirTap(private val context: Context) {

    private var record: AudioRecord? = null
    private var ring: ShortArray? = null
    private var write = 0
    private var filled = 0
    private val lock = Object()

    @Volatile var running = false
        private set
    @Volatile var lastError: String? = null
        private set
    @Volatile var rate = 48000
        private set

    /** Seconds held, which is what the operator is offered. */
    fun seconds(): Double = synchronized(lock) {
        val have = ring ?: return 0.0
        return filled.toDouble() / rate
    }

    /**
     * Start capturing.
     *
     * @return null when it started, or why it did not.
     */
    @Synchronized
    fun start(): String? {
        if (running) return null
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            lastError = "RECORD_AUDIO has not been granted"
            return lastError
        }
        try {
            val least = AudioRecord.getMinBufferSize(rate,
                AudioFormat.CHANNEL_IN_STEREO, AudioFormat.ENCODING_PCM_16BIT)
            if (least <= 0) {
                lastError = "this build reports no buffer size for the submix"
                return lastError
            }
            /* A generous buffer: the READ side is a thread of our own, but a
             * scheduler that leaves it out for a moment must not cost audio,
             * and that is the entire point of moving off the main thread. */
            val size = least * 8

            @Suppress("MissingPermission")
            val tap = AudioRecord(MediaRecorder.AudioSource.REMOTE_SUBMIX,
                rate, AudioFormat.CHANNEL_IN_STEREO,
                AudioFormat.ENCODING_PCM_16BIT, size)
            if (tap.state != AudioRecord.STATE_INITIALIZED) {
                tap.release()
                lastError = "the submix would not initialise - " +
                    "CAPTURE_AUDIO_OUTPUT may not be granted"
                return lastError
            }

            synchronized(lock) {
                ring = ShortArray(rate * HOLD_SECONDS)
                write = 0
                filled = 0
            }
            record = tap
            running = true
            lastError = null
            tap.startRecording()
            drain(tap, size)
            Log.i(TAG, "air tap running at " + rate + " Hz, holding "
                + HOLD_SECONDS + "s")
            return null
        } catch (err: Exception) {
            lastError = err.message ?: err.toString()
            Log.w(TAG, "air tap would not start: " + lastError)
            stop()
            return lastError
        }
    }

    private fun drain(tap: AudioRecord, size: Int) {
        thread(name = "pine-air-tap", isDaemon = true) {
            val block = ShortArray(size / 2)
            while (running) {
                val got = try {
                    tap.read(block, 0, block.size)
                } catch (err: Exception) {
                    if (running) lastError = err.message
                    break
                }
                if (got <= 0) continue
                synchronized(lock) {
                    val room = ring ?: return@synchronized
                    /* STEREO IN, MONO OUT - the same fold the page's capture
                     * did, so a clip cut from here sounds like a clip cut
                     * from there and nothing downstream has to care which
                     * road it came by. */
                    var i = 0
                    while (i + 1 < got) {
                        val mixed = ((block[i].toInt() + block[i + 1].toInt()) / 2)
                        room[write] = mixed.toShort()
                        write = if (write + 1 == room.size) 0 else write + 1
                        if (filled < room.size) filled += 1
                        i += 2
                    }
                }
            }
        }
    }

    @Synchronized
    fun stop() {
        running = false
        try { record?.stop() } catch (err: Exception) { /* gone */ }
        try { record?.release() } catch (err: Exception) { /* gone */ }
        record = null
        /* THE RING IS KEPT, like the screen recorder's: the last two minutes
         * before somebody switched the tap off are exactly what they are
         * about to ask for. */
    }

    /**
     * The window from [fromAgo] seconds ago to [toAgo] seconds ago, as a
     * mono 16-bit WAV.
     *
     * The same shape PineAir.sliceWav answers with, so the desktop's export
     * does not need to know which capture produced it.
     */
    fun sliceWav(fromAgo: Double, toAgo: Double): ByteArray {
        synchronized(lock) {
            val room = ring ?: return wav(ShortArray(0))
            val from = maxOf(fromAgo, toAgo)
            val to = minOf(fromAgo, toAgo)
            val span = ((from - to) * rate).toInt()
            if (span <= 0) return wav(ShortArray(0))
            val back = (from * rate).toInt()
            if (back > filled) {
                /* Never claim more than was captured. Asking for thirty
                 * seconds of a tap that has been open for eleven must give
                 * eleven, not thirty with nineteen of silence in front. */
                val have = minOf(span, filled)
                return wav(read(room, have, minOf(back, filled)))
            }
            return wav(read(room, span, back))
        }
    }

    /** [want] samples ending [back] samples ago. */
    private fun read(room: ShortArray, want: Int, back: Int): ShortArray {
        val out = ShortArray(want)
        var at = write - back
        while (at < 0) at += room.size
        for (i in 0 until want) {
            out[i] = room[at]
            at = if (at + 1 == room.size) 0 else at + 1
        }
        return out
    }

    private fun wav(samples: ShortArray): ByteArray {
        val body = samples.size * 2
        val out = ByteArrayOutputStream(44 + body)
        fun str(s: String) = out.write(s.toByteArray(Charsets.US_ASCII))
        fun int(v: Int) {
            out.write(v and 0xff); out.write((v ushr 8) and 0xff)
            out.write((v ushr 16) and 0xff); out.write((v ushr 24) and 0xff)
        }
        fun short(v: Int) { out.write(v and 0xff); out.write((v ushr 8) and 0xff) }

        str("RIFF"); int(36 + body); str("WAVE")
        str("fmt "); int(16); short(1); short(1)
        int(rate); int(rate * 2); short(2); short(16)
        str("data"); int(body)
        for (s in samples) short(s.toInt())
        return out.toByteArray()
    }

    companion object {
        private const val TAG = "PineAirTap"
        /** Two minutes, matching the page ring this replaces. */
        const val HOLD_SECONDS = 120
    }
}
