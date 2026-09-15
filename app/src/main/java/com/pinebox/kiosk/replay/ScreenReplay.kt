package com.pinebox.kiosk.replay

import android.content.Context
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.util.Log
import android.view.Surface
import android.view.WindowManager
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import org.json.JSONObject

/**
 * THE TABLET, ALWAYS BEING RECORDED, HELD IN A RING.
 *
 * "I just want it recording the tablet in general with a rolling history that
 *  I'm able to always extract from the tablet through the Pine Box app."
 *
 * A VirtualDisplay mirrors the real screen into an encoder's input surface,
 * and what comes out goes into ReplayRing. Nothing is written to disk until
 * someone asks for it.
 *
 * NO MEDIAPROJECTION, AND THEREFORE NO DIALOG. The usual road raises a
 * consent prompt every time a projection starts, which on a terminal that
 * must record continuously means a tap after every reboot and every restart -
 * and a rolling buffer that stops whenever nobody is looking at the tablet is
 * not a rolling buffer. CAPTURE_VIDEO_OUTPUT is `prot=signature` on this
 * build with sourcePackage `android`, and this APK carries the platform key,
 * so a VirtualDisplay can be created against the real display directly.
 * Measured after declaring it: granted=true at install, no prompt.
 *
 * THE NUMBERS ARE CHOSEN TO BE CHEAP, because this runs forever:
 *
 *   half size      670x400 rather than 1340x800. A quarter of the pixels, and
 *                  a screen recording is read, not framed - text at half size
 *                  on a 1340px capture is still legible played back at size.
 *   12 fps         a user interface is not motion. Twelve is enough to see a
 *                  menu open and a finger land, and it is 40% of the encoder
 *                  work of thirty.
 *   0.6 Mbit       was 1.6, and 1.6 was already "generous for a mostly-
 *                  static UI at this size". 2026-09-14 the hold went from
 *                  60 s to 1200 s (HOLD_SECONDS below: "anywhere from the
 *                  last five seconds to the last 20 minutes"), and
 *                  1200 s x 1.6 Mbit / 8 = 240 MB is not a ring this heap
 *                  can carry. The screen was measured running at about a
 *                  third of the old ceiling anyway - 200 s held in a ring
 *                  sized for 60 - so the ceiling comes down to where the
 *                  picture actually lives:
 *
 *                      600,000 bit/s / 8      =  75,000 B/s
 *                      x 1200 s               =  90,000,000 B   (90 MB)
 *                      x 5/4 headroom         = 112.5 MB, capped at 100 MB
 *                                               by ReplayRing.size()
 *                      100 MB / 75,000 B/s    = 1,398 s held at the ceiling
 *
 *                  So the twenty minutes fit with a sixth to spare when the
 *                  screen is as busy as the encoder is allowed to make it,
 *                  and a static panel holds far longer. The cost: motion -
 *                  the video wall, a 3D scene - is blockier at 0.6 than it
 *                  was at 1.6. The replay is for reading what the tablet
 *                  did, not for framing; that trade was taken over spilling
 *                  the ring to flash, which would have written it all day.
 *   keyframe 1s    the cut has to start on a sync frame, so the interval is
 *                  the worst-case error on where a clip begins. One second is
 *                  the largest that still feels like "the last thirty".
 *
 * IT STOPS WHEN THE SCREEN DOES. There is nothing on a dark screen worth
 * three percent of a battery, and the ring keeps whatever it held - so the
 * half-minute before the tablet went to sleep is still there when it wakes.
 */
class ScreenReplay(private val context: Context) {

    private val ring = ReplayRing(HOLD_SECONDS)
    private val audioCapture = ReplayAudioCapture(context, ring)
    private var codec: MediaCodec? = null
    private var surface: Surface? = null
    private var display: VirtualDisplay? = null
    private val running = AtomicBoolean(false)
    private var worker: Thread? = null
    @Volatile private var sessionStartedUs = 0L
    @Volatile var lastSavedAudio = JSONObject().put("present", false).put("state", "unavailable")
        private set

    @Volatile var lastError: String? = null
        private set

    val isRunning: Boolean get() = running.get()

    fun seconds(): Double = ring.seconds()
    fun bytes(): Int = ring.bytes()

    fun audioStatus(): JSONObject = audioCapture.status().apply {
        put("held_seconds", ring.audioSeconds())
        ring.audioClockError?.let { put("available", false); put("state", "unavailable"); put("error", it); put("detail", it) }
    }

    @Synchronized
    fun start(): String? {
        if (running.get()) { audioCapture.start(); return null }
        try {
            val window = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val real = android.graphics.Point()
            @Suppress("DEPRECATION")
            window.defaultDisplay.getRealSize(real)
            /* Even dimensions: the encoder will refuse an odd width, and it
             * says so with a generic configure failure rather than naming it.
             * The same trap the desktop's ffmpeg pass met. */
            val w = ((real.x * SCALE).toInt() / 2) * 2
            val h = ((real.y * SCALE).toInt() / 2) * 2

            val format = MediaFormat.createVideoFormat(MIME, w, h).apply {
                setInteger(MediaFormat.KEY_COLOR_FORMAT,
                    MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
                setInteger(MediaFormat.KEY_FRAME_RATE, FPS)
                // KEY_FRAME_RATE alone is a rate-control hint: the mirror
                // otherwise feeds 30–60 fps while the tablet is animating.
                setFloat(MediaFormat.KEY_MAX_FPS_TO_ENCODER, FPS.toFloat())
                setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                setInteger(MediaFormat.KEY_CAPTURE_RATE, FPS)
                setInteger(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 1_000_000 / FPS)
            }
            ring.size(BITRATE)
            /* THE CACHE FROM BEFORE THE RESTART, taken in once. The ring is
             * only empty on a genuinely fresh start - a screen waking up
             * still holds everything from before it slept, and loading over
             * that would duplicate it. */
            if (ring.seconds() <= 0.0) restore()
            // Capture the device playback mix beside the video encoder. It
            // copies media playback while leaving speaker/headphone routing
            // intact; no microphone and no replacement server stream.
            audioCapture.start()
            sessionStartedUs = System.nanoTime() / 1000

            val encoder = MediaCodec.createEncoderByType(MIME)
            encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            val input = encoder.createInputSurface()
            encoder.start()
            codec = encoder
            surface = input

            val manager = context.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
            /* AUTO_MIRROR against the real display: this is what
             * CAPTURE_VIDEO_OUTPUT buys, and what a MediaProjection token
             * would otherwise be needed for. */
            /* SECURE, OR THE MIRROR IS BLANK.
             *
             * The built-in display on this tablet is FLAG_SECURE, and
             * mirroring a secure display into a virtual one that is not
             * marked secure does not fail - it silently hands over a blanked
             * surface. That is the worst possible shape for a bug: every
             * byte count, frame count, duration and resolution checks out,
             * and the picture is flat grey.
             *
             * Measured before the flag: 10 seconds encoded to 3,834 bytes
             * with six distinct colours, 267,576 of 268,000 pixels being
             * RGB(47,47,47). VIRTUAL_DISPLAY_FLAG_SECURE needs
             * CAPTURE_SECURE_VIDEO_OUTPUT, which is signature-level from
             * `android` and granted by the platform key. */
            /* NOT PUBLIC. A PUBLIC virtual display is a display in its own
             * right - the system may treat it as an extension and put
             * nothing on it, which is exactly what was happening: the
             * encoder was faithfully recording an EMPTY DISPLAY's
             * background, #2F2F2F, at 670x400 and 12 fps.
             *
             * AUTO_MIRROR alone is the mirror. */
            display = manager.createVirtualDisplay(
                "pine-replay", w, h, 1, input,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR
                    or DisplayManager.VIRTUAL_DISPLAY_FLAG_SECURE)

            running.set(true)
            lastError = null
            drain(encoder)
            Log.i(TAG, "replay running at " + w + "x" + h + " " + FPS + "fps, holding "
                + HOLD_SECONDS + "s")
            return null
        } catch (err: Exception) {
            lastError = err.message ?: err.toString()
            Log.w(TAG, "replay would not start: " + lastError)
            stop()
            return lastError
        }
    }

    private fun drain(encoder: MediaCodec) {
        worker = thread(name = "pine-replay", isDaemon = true) {
            val info = MediaCodec.BufferInfo()
            var clockChecked = false
            try {
                while (running.get()) {
                    val index = encoder.dequeueOutputBuffer(info, 250_000)
                    if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        ring.remember(encoder.outputFormat)
                        continue
                    }
                    if (index < 0) continue
                    val out = encoder.getOutputBuffer(index)
                    if (!clockChecked && info.size > 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                        clockChecked = true
                        // VirtualDisplay surface timestamps and AudioRecord's
                        // TIMEBASE_MONOTONIC must share the same clock. Refuse
                        // the audio claim on a vendor codec that uses another
                        // origin; do not align streams by callback arrival.
                        if (info.presentationTimeUs < sessionStartedUs - 2_000_000 ||
                            info.presentationTimeUs > System.nanoTime() / 1000 + 250_000) {
                            ring.invalidateAudioClock("This screen encoder does not expose the monotonic capture clock; synchronized playback audio is unavailable.")
                        }
                    }
                    if (out != null && info.size > 0) ring.add(out, info)
                    encoder.releaseOutputBuffer(index, false)
                }
            } catch (err: Exception) {
                if (running.get()) {
                    lastError = err.message
                    Log.w(TAG, "replay drain stopped: " + err.message)
                }
            }
        }
    }

    /**
     * READY THE RING WITHOUT RECORDING.
     *
     * The cache used to be taken in by start(), which only runs when the
     * panel is on - so a terminal that booted with its screen dark held
     * nothing, and a pull would have come back empty while a perfectly good
     * history sat on disk beside it.
     *
     * Sizing the ring and restoring into it is not recording, costs no
     * encoder, and is exactly what "pull from it at any time" requires.
     */
    @Synchronized
    fun prime() {
        if (running.get()) return
        ring.size(BITRATE)
        if (ring.seconds() <= 0.0) restore()
    }

    /** Where the history lives between runs. One file, replaced whole. */
    private fun cacheFile(): File =
        File(File(context.cacheDir, "replay").apply { mkdirs() }, "history.mp4")

    /**
     * Put the history on disk.
     *
     * Called when recording stops, which is when the screen goes dark - the
     * moment the history stops growing and starts being worth keeping. NOT
     * called on a timer: at the design bitrate a continuous rolling write is
     * 6.5 GB a day (it was 17 at the old 1.6 Mbit), and this terminal's
     * flash has to last. One write of up to 90 MB at screen-off is not
     * that; /data had 38 GB free when this was sized.
     *
     * Written beside the real file and moved into place, so a kill partway
     * through leaves the previous cache intact rather than a half file that
     * reads as corruption.
     */
    @Synchronized
    private fun keep() {
        val held = ring.seconds()
        if (held < 1.0) return
        val real = cacheFile()
        val part = File(real.parentFile, "history.part")
        try {
            part.delete()
            ring.save(part, held + 1.0, allowVideoOnly = true)
            if (part.length() > 0L) {
                real.delete()
                if (!part.renameTo(real)) part.delete()
                Log.i(TAG, "history cached: " + held.toInt() + "s, "
                    + (real.length() / 1024) + " kB")
            }
        } catch (err: Exception) {
            Log.w(TAG, "history could not be cached: " + err.message)
            try { part.delete() } catch (gone: Exception) { /* fine */ }
        }
    }

    /** Take last run's history back in. See ReplayRing.load. */
    @Synchronized
    private fun restore() {
        val real = cacheFile()
        if (!real.exists()) return
        try {
            val taken = ring.load(real)
            Log.i(TAG, "history restored: " + taken + " packets, "
                + ring.seconds().toInt() + "s")
        } catch (err: Exception) {
            Log.w(TAG, "history would not restore: " + err.message)
        }
    }

    @Synchronized
    fun stop() {
        val was = running.get()
        running.set(false)
        audioCapture.stop()
        try { display?.release() } catch (err: Exception) { /* gone */ }
        try { worker?.join(1500) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        worker = null
        try { codec?.stop() } catch (err: Exception) { /* gone */ }
        try { codec?.release() } catch (err: Exception) { /* gone */ }
        try { surface?.release() } catch (err: Exception) { /* gone */ }
        display = null
        codec = null
        surface = null
        /* THE RING IS NOT CLEARED. Stopping happens when the screen goes off,
         * and the half-minute before that is exactly what somebody will want
         * when they pick the tablet up again.
         *
         * IT IS ALSO WRITTEN TO DISK HERE, which is what makes it a cache
         * rather than a buffer: the app goes away on every deploy, every
         * crash and whenever Android reclaims it, and "pull from it at any
         * time" has to survive all three. */
        if (was) keep()
    }

    /** Write the history now, without stopping - for a deliberate shutdown. */
    fun flush() = keep()

    /**
     * Write the last [want] seconds. Returns the file and what it holds.
     *
     * BOUNDED BY WHAT IS HELD, NOT BY HOLD_SECONDS. The ring is bounded by
     * BYTES - the blob - and a screen cheaper than the design bitrate
     * assumed leaves minutes of history in it. Measured at 200 seconds held
     * against a 60-second design figure, all of which used to be
     * unreachable because this clamped the ask to 60.
     *
     * The blob is the real ceiling, so whatever it turns out to hold is
     * exactly what can be offered, and a pull can never exceed it however
     * long the history reads.
     */
    @Synchronized
    fun save(want: Double, allowVideoOnly: Boolean = false): Pair<File, Double> {
        val dir = File(context.cacheDir, "replay").apply { mkdirs() }
        val out = File(dir, "replay-" + System.currentTimeMillis() + ".mp4")
        /* A second of slack so "everything" does not fall a frame short of
         * the oldest keyframe and quietly drop the start. */
        val all = (ring.seconds() + 1.0).coerceAtLeast(1.0)
        val got = try { ring.save(out, want.coerceIn(1.0, all), allowVideoOnly) }
        finally { lastSavedAudio = JSONObject(ring.lastSavedAudio.toString()).put("capture", audioStatus()) }
        return Pair(out, got)
    }

    companion object {
        private const val TAG = "PineReplay"
        private const val MIME = MediaFormat.MIMETYPE_VIDEO_AVC

        /**
         * THE DESIGN FLOOR, NOT A CAP.
         *
         * It sizes the ring so that at the design bitrate AT LEAST this much
         * always fits. A screen cheaper than that assumption - which a
         * mostly-static terminal always is - leaves far more in the blob,
         * and all of it is offered: see save(), and `seconds` in the state
         * report, which is the only honest figure for how much is there.
         *
         * TWENTY MINUTES, since 2026-09-14: "I want to save anywhere from
         * the last five seconds to the last 20 minutes. So the tablet
         * should always be recording." Paid for by the bitrate, not by the
         * heap - the arithmetic is at the top of this file. The page's
         * export sheet reads this through hotCorners().ring.
         */
        const val HOLD_SECONDS = 1200

        /* Half size, twelve frames, 0.6 Mbit - see the note at the top. */
        private const val SCALE = 0.5
        private const val FPS = 12
        private const val BITRATE = 600_000
    }
}
