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

    /* The M9 vendor encoder panics with replay and adb screenrecord together.
     * This gate applies to every start road, including SCREEN_ON/onResume.
     * The ring and playback-audio capture remain intact while video is held. */
    private val mirrorEncoderLease = MirrorEncoderLease()
    private var mirrorLeaseTimer: java.util.Timer? = null
    private var videoReleaseError: String? = null
    private var deferredVideoStart = false
    private var mirrorHistoryPending = false
    private val historyWriter = ReplayCacheWriter({ keepHistory() })
    private val mirrorProofWorkers = java.util.concurrent.Executors.newFixedThreadPool(3) { task ->
        Thread(task, "mirror-encoder-proof").apply { isDaemon = true }
    }
    private var externalReplayTimer: java.util.Timer? = null
    private val mirrorLeasePrefs = context.getSharedPreferences("mirror-encoder-lease", Context.MODE_PRIVATE)

    init {
        JpegMirrorCapture.initialize(context)
        val owner = mirrorLeasePrefs.getString("owner", "").orEmpty()
        val left = (mirrorLeasePrefs.getLong("until_wall_ms", 0L) - System.currentTimeMillis())
            .coerceIn(0L, MirrorEncoderLease.MAX_TTL_MS)
        if (mirrorEncoderLease.restore(owner, android.os.SystemClock.elapsedRealtime() + left,
                mirrorLeasePrefs.getBoolean("restore_video", false))) armMirrorLeaseExpiry()
    }

    /** Commit before acknowledging acquisition so an app restart cannot
     * forget the guard while adb's recorder is allocating its hardware codec. */
    private fun persistMirrorLease(): Boolean = mirrorLeasePrefs.edit()
        .putString("owner", mirrorEncoderLease.owner)
        .putLong("until_wall_ms", System.currentTimeMillis() +
            (mirrorEncoderLease.untilMs - android.os.SystemClock.elapsedRealtime()).coerceAtLeast(0L))
        .putBoolean("restore_video", mirrorEncoderLease.resumeWanted).commit()

    @Synchronized
    fun mirrorLease(operation: String, owner: String, ttlMs: Long,
                    jpegWidth: Int = 0, jpegHeight: Int = 0,
                    jpegQuality: Int = 50, jpegFps: Int = 12, jpegStreamId: String = ""): JSONObject {
        val now = android.os.SystemClock.elapsedRealtime()
        var accepted = true
        var detail: String? = null
        when (operation) {
            "acquire" -> {
                accepted = mirrorEncoderLease.acquire(owner, now, ttlMs, running.get() || deferredVideoStart)
                if (accepted) {
                    val saved = persistMirrorLease()
                    stop(keepAudio = true, deferHistory = true)
                    val jpegReleased = stopOwnedJpegCapture(owner)
                    accepted = saved && replayVideoReleased() && jpegReleased
                    detail = if (!saved) "the encoder hold could not be saved for app restart"
                        else if (!jpegReleased) "the previous JPEG capture resources have not released" else videoReleaseError
                    if (accepted && externalScreenRecorderActive() != false) {
                        accepted = false
                        detail = "an external screen recorder is still active or could not be checked"
                    }
                    armMirrorLeaseExpiry()
                } else detail = "the mirror encoder is held by another owner or the owner is invalid"
            }
            "renew" -> {
                accepted = mirrorEncoderLease.renew(owner, now, ttlMs)
                if (accepted) {
                    accepted = persistMirrorLease()
                    armMirrorLeaseExpiry()
                    if (!accepted) detail = "the renewed encoder hold could not be saved"
                } else detail = "this mirror no longer owns the encoder hold"
            }
            "jpeg_start" -> {
                if (!mirrorEncoderLease.ownsCurrent(owner, now)) {
                    accepted = false
                    detail = "JPEG capture requires the current exact encoder-hold owner"
                } else if (!persistMirrorLease()) {
                    accepted = false
                    detail = "the JPEG capture hold could not be saved for app restart"
                } else if (!replayVideoReleased()) {
                    accepted = false
                    detail = "the replay video resources have not released"
                } else if (!JpegMirrorCapture.isReleased()) {
                    accepted = false
                    detail = "the previous JPEG capture has not released; stop it before restarting"
                } else if (externalScreenRecorderActive() != false) {
                    accepted = false
                    detail = "an external capture is still active or could not be checked"
                } else if (!mirrorEncoderLease.ownsCurrent(owner, android.os.SystemClock.elapsedRealtime())) {
                    accepted = false
                    detail = "the JPEG capture owner expired during the capture-ownership proof"
                } else {
                    val result = JpegMirrorCapture.start(owner, jpegStreamId, jpegWidth, jpegHeight, jpegQuality, jpegFps)
                    accepted = result.optBoolean("ok")
                    if (!accepted) detail = result.optString("detail", "JPEG capture did not start")
                }
                if (mirrorEncoderLease.held) armMirrorLeaseExpiry()
            }
            "jpeg_stop" -> {
                if (!mirrorEncoderLease.held || owner != mirrorEncoderLease.owner) {
                    accepted = false
                    detail = "JPEG capture stop requires the exact encoder-hold owner"
                } else {
                    val result = JpegMirrorCapture.stopExactOwner(owner, jpegStreamId)
                    accepted = result.optBoolean("ok") && result.optBoolean("jpeg_released")
                    if (!accepted) detail = result.optString("detail", "JPEG capture resources have not released")
                }
            }
            "release" -> {
                if (mirrorEncoderLease.held) {
                    if (owner != mirrorEncoderLease.owner) {
                        accepted = false
                        detail = "this mirror does not own the encoder hold"
                    } else {
                        val jpegReleased = stopOwnedJpegCapture(owner)
                        val restore = if (jpegReleased) mirrorEncoderLease.release(owner,
                            externalScreenRecorderActive(), JpegMirrorCapture.isReleased()) else null
                        if (restore == null) {
                            accepted = false
                            detail = if (!jpegReleased) "JPEG capture resources have not released" else
                                "the external screen recorder has not been confirmed stopped"
                            armMirrorLeaseExpiry()
                        } else restoreMirrorReplay(restore)
                    }
                }
            }
            "status" -> Unit
            "probe" -> return mirrorEncoderProof().put("ok", true)
                .put("held", mirrorEncoderLease.held).put("owner", mirrorEncoderLease.owner)
                .put("video_running", running.get()).put("audio", audioStatus())
            else -> { accepted = false; detail = "unknown mirror lease operation" }
        }
        val answer = JSONObject().put("ok", accepted)
            .put("held", mirrorEncoderLease.held)
            .put("owner", mirrorEncoderLease.owner)
            .put("expires_in_ms", (mirrorEncoderLease.untilMs - android.os.SystemClock.elapsedRealtime()).coerceAtLeast(0L))
            .put("video_running", running.get())
            .put("video_released", replayVideoReleased())
            .put("restore_replay", mirrorEncoderLease.resumeWanted)
            .put("seconds", ring.seconds())
            .put("audio", audioStatus())
            .put("detail", detail ?: JSONObject.NULL)
        val jpeg = JpegMirrorCapture.status()
        for (key in listOf("jpeg_running", "jpeg_released", "jpeg_owner", "jpeg_stream_id", "jpeg_socket", "width", "height", "fps", "jpeg_quality", "jpeg_frames", "jpeg_since_frame_ms", "jpeg_compress_ms", "jpeg_resources", "jpeg_image_callbacks", "jpeg_drain_attempts", "jpeg_acquired_images", "jpeg_empty_reads", "jpeg_error")) {
            if (jpeg.has(key)) answer.put(key, jpeg.opt(key))
        }
        return answer
    }

    private fun replayVideoReleased(): Boolean = !running.get() && codec == null &&
        display == null && surface == null && videoReleaseError == null && worker?.isAlive != true

    private fun stopOwnedJpegCapture(owner: String): Boolean {
        if (JpegMirrorCapture.isReleased()) return true
        val answer = JpegMirrorCapture.stopOwned(owner)
        return answer.optBoolean("jpeg_released") && JpegMirrorCapture.isReleased()
    }

    private fun armMirrorLeaseExpiry() {
        mirrorLeaseTimer?.cancel()
        mirrorLeaseTimer = null
        if (!mirrorEncoderLease.held) return
        val delay = (mirrorEncoderLease.untilMs - android.os.SystemClock.elapsedRealtime())
            .coerceAtLeast(2_000L)
        val timer = java.util.Timer("mirror-encoder-expiry", true)
        timer.schedule(object : java.util.TimerTask() {
            override fun run() = expireMirrorLease()
        }, delay)
        mirrorLeaseTimer = timer
    }

    @Synchronized
    private fun expireMirrorLease() {
        if (!mirrorEncoderLease.held) return
        val now = android.os.SystemClock.elapsedRealtime()
        // A renewed deadline must not let an old timer stop the current JPEG.
        if (now < mirrorEncoderLease.untilMs) { armMirrorLeaseExpiry(); return }
        if (!stopOwnedJpegCapture(mirrorEncoderLease.owner)) { armMirrorLeaseExpiry(); return }
        val restore = mirrorEncoderLease.expire(now, externalScreenRecorderActive(),
            JpegMirrorCapture.isReleased())
        if (restore == null) armMirrorLeaseExpiry()
        else restoreMirrorReplay(restore)
    }

    private fun restoreMirrorReplay(restore: Boolean) {
        if (!persistMirrorLease()) Log.w(TAG, "the cleared mirror hold could not be saved; stale disk hold stays conservative")
        mirrorLeaseTimer?.cancel()
        mirrorLeaseTimer = null
        val power = context.getSystemService(Context.POWER_SERVICE) as? android.os.PowerManager
        if (restore && power?.isInteractive == true && !com.pinebox.kiosk.kiosk.Standby.active) {
            // Acknowledging release must not wait for codec allocation or
            // a second ownership probe. Retry performs all the same guards.
            deferredVideoStart = true
            armExternalReplayRetry()
        }
    }

    private fun armExternalReplayRetry() {
        externalReplayTimer?.cancel()
        val timer = java.util.Timer("replay-external-encoder", true)
        timer.schedule(object : java.util.TimerTask() {
            override fun run() = retryExternalReplay()
        }, 2_000L)
        externalReplayTimer = timer
    }

    @Synchronized
    private fun retryExternalReplay() {
        externalReplayTimer = null
        if (!deferredVideoStart || mirrorEncoderLease.held) return
        val power = context.getSystemService(Context.POWER_SERVICE) as? android.os.PowerManager
        if (power?.isInteractive != true || com.pinebox.kiosk.kiosk.Standby.active) return
        start()
    }

    /** Use the platform-granted DUMP permission, not an optimistic pidof from
     * an app UID whose /proc visibility can hide root's screenrecord. Keep the
     * hold on timeout, permission refusal, or an unrecognised vendor dump. */
    private fun mirrorEncoderProof(): JSONObject {
        // Independent read-only dumps run together so a stalled vendor service
        // cannot consume the ordered broadcast deadline three times over.
        val checks = listOf(
            java.util.concurrent.Callable<Boolean?> { nativeDump("SurfaceFlinger")?.let { MirrorEncoderLease.parseExternalRecorder(it) } },
            java.util.concurrent.Callable<Boolean?> { nativeDump("meminfo", "screenrecord")?.let { MirrorEncoderLease.parseRecorderProcess(it) } },
            java.util.concurrent.Callable<Boolean?> { nativeDump("media.resource_manager")?.let { MirrorEncoderLease.parseVideoEncoders(it) } }
        )
        val values = try {
            mirrorProofWorkers.invokeAll(checks, 3500, java.util.concurrent.TimeUnit.MILLISECONDS).map { result ->
                try { if (result.isCancelled) null else result.get() } catch (_: Exception) { null }
            }
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            listOf<Boolean?>(null, null, null)
        }
        return JSONObject().put("compositor", values[0] ?: JSONObject.NULL)
            .put("recorder_process", values[1] ?: JSONObject.NULL)
            .put("video_encoder", values[2] ?: JSONObject.NULL)
    }

    private fun externalScreenRecorderActive(): Boolean? {
        val proof = mirrorEncoderProof()
        val keys = listOf("compositor", "recorder_process", "video_encoder")
        if (keys.any { proof.opt(it) == true }) return true
        return if (keys.all { proof.opt(it) == false }) false else null
    }

    private fun nativeDump(vararg args: String): String? {
        val output = try { File.createTempFile("mirror-encoder-", ".txt", context.cacheDir) }
        catch (error: Exception) { return null }
        var process: Process? = null
        return try {
            process = ProcessBuilder(listOf("/system/bin/dumpsys") + args.toList())
                .redirectErrorStream(true).redirectOutput(output).start()
            if (!process.waitFor(3, java.util.concurrent.TimeUnit.SECONDS) ||
                process.exitValue() != 0 || output.length() > 2_000_000L) null
            else output.readText()
        } catch (error: Exception) { null }
        finally {
            process?.destroy()
            output.delete()
        }
    }

    fun seconds(): Double = ring.seconds()
    fun bytes(): Int = ring.bytes()

    fun audioStatus(): JSONObject = audioCapture.status().apply {
        put("held_seconds", ring.audioSeconds())
        ring.audioClockError?.let { put("available", false); put("state", "unavailable"); put("error", it); put("detail", it) }
        /* [#1225] ONE WORD FOR "IS THE TABLET CAPTURING". The operator
         * asked for audio capture to be a background service that is
         * always running, and the honest answer to "is it" was spread
         * across `running`, `available`, `state`, `last_packet_age_ms`
         * and a sentence. It is spread across them still - this is the
         * summary, and it is what the desk's window and the tablet's own
         * readout now print. */
        put("always_on", true)
        put("capture_phase", when {
            ring.audioClockError != null -> "stopped"
            !optBoolean("running", false) -> "not_started"
            optLong("captured_frames", 0L) <= 0L -> "starting"
            optLong("signal_frames", 0L) <= 0L -> "silent"
            ring.audioSeconds() < 5.0 -> "filling"
            else -> "ready"
        })
    }

    /** [smart-reinit] Re-register the playback capture's policy (see
     *  ReplayAudioCapture.reopen). The picture is not touched. */
    fun reopenAudio(): String = audioCapture.reopen()

    /** [smart-reinit] Let the playback capture go entirely: its policy is
     *  unregistered, so nothing can hold the tablet's sound on the remote
     *  submix. prime() - every onResume - starts it again. */
    fun releaseAudio(): String {
        audioCapture.stop()
        return "released until the app next resumes"
    }

    @Synchronized
    fun start(): String? {
        if (mirrorEncoderLease.held) {
            // Service startup/screen-on may request video after a cold hold
            // was acquired. Remember that request without allocating a codec.
            mirrorEncoderLease.requestResume()
            return if (persistMirrorLease()) null else "the deferred replay start could not be saved"
        }
        if (!JpegMirrorCapture.isReleased()) {
            deferredVideoStart = true
            armExternalReplayRetry()
            return null
        }
        if ((codec != null || display != null || surface != null || worker?.isAlive == true) && !running.get()) return "the previous replay encoder has not released"
        if (running.get()) { audioCapture.start(); return null }
        if (mirrorHistoryPending || historyWriter.hasPending) {
            deferredVideoStart = true
            armExternalReplayRetry()
            return "waiting for the frozen replay history cache to finish"
        }
        /* A kiosk process can restart while root's adb recorder survives.
         * Reconstruct exclusion from the compositor before allocating ANY
         * encoder, even when the in-memory lease died with the old process. */
        if (externalScreenRecorderActive() != false) {
            deferredVideoStart = true
            armExternalReplayRetry()
            return "waiting for the external screen recorder to release the encoder"
        }
        deferredVideoStart = false
        externalReplayTimer?.cancel()
        externalReplayTimer = null
        try {
            val window = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val real = android.graphics.Point()
            @Suppress("DEPRECATION")
            window.defaultDisplay.getRealSize(real)
            /* Even dimensions: the encoder will refuse an odd width, and it
             * says so with a generic configure failure rather than naming it.
             * The same trap the desktop's ffmpeg pass met. */
            val at = q                                  // [rec-quality] the level in force
            val w = ((real.x * at.scale).toInt() / 2) * 2
            val h = ((real.y * at.scale).toInt() / 2) * 2
            /* [rec-quality-pct] read before the format: the bitrate is the
             * level's, scaled by the operator's quality share. */
            try { ReplayPrefs.load(context) } catch (e: Exception) { /* [memprefs] keep the default */ }

            val format = MediaFormat.createVideoFormat(MIME, w, h).apply {
                setInteger(MediaFormat.KEY_COLOR_FORMAT,
                    MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                setInteger(MediaFormat.KEY_BIT_RATE, bitrateFor(at))
                setInteger(MediaFormat.KEY_FRAME_RATE, at.fps)
                // KEY_FRAME_RATE alone is a rate-control hint: the mirror
                // otherwise feeds 30–60 fps while the tablet is animating.
                setFloat(MediaFormat.KEY_MAX_FPS_TO_ENCODER, at.fps.toFloat())
                setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0)
                setInteger(MediaFormat.KEY_CAPTURE_RATE, at.fps)
                setInteger(MediaFormat.KEY_REPEAT_PREVIOUS_FRAME_AFTER, 1_000_000 / at.fps)
            }
            /* Sized from the level's design bitrate, not the scaled one: the
             * slider then never reshapes (and empties) the ring at the next
             * screen wake. A lower quality simply holds longer. */
            ring.size(at.bitrate)
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
            codec = encoder
            encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            val input = encoder.createInputSurface()
            surface = input
            encoder.start()

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
            Log.i(TAG, "replay running at " + w + "x" + h + " " + at.fps + "fps (" + at.label + ", "
                + ReplayPrefs.qualityPct + "% = " + bitrateFor(at) + " bit/s), holding "
                + HOLD_SECONDS + "s")
            return null
        } catch (err: Exception) {
            lastError = err.message ?: err.toString()
            Log.w(TAG, "replay would not start: " + lastError)
            stop(keepAudio = true)
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
        if (mirrorHistoryPending || historyWriter.hasPending) { audioCapture.start(); return }
        if (mirrorEncoderLease.held) {
            // Software-only cold history restore: ByteArray/MediaExtractor.
            // The held branch returns before any video encoder start road;
            // start() independently retains lease + external ownership guards.
            ring.size(q.bitrate)
            if (ring.seconds() <= 0.0) restore()
            audioCapture.start()
            return
        }
        ring.size(q.bitrate)
        if (ring.seconds() <= 0.0) restore()
        /* [#1225] AND THE SOUND STARTS HERE, not when the screen lights
         * up. prime() is what PineAppRecorder calls in onCreate - at
         * BOOT_COMPLETED, and again on every MainActivity.onResume - so
         * this is the earliest honest moment in the process's life. It
         * is idempotent; start() calls it again and gets nothing. */
        audioCapture.start()
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
    private fun keep() = historyWriter.flush()

    private fun keepHistory() {
        /* [rec-quality] only Standard is cached: a cache is restored into a
         * Standard ring after a restart, and two frame sizes in one ring cut
         * files a player cannot open. */
        if (level != 0) return
        val held = ring.seconds()
        if (held < 1.0) return
        val real = cacheFile()
        val part = File(real.parentFile, "history.part")
        try {
            part.delete()
            ring.save(part, held + 1.0, allowVideoOnly = true,
                frozenVideo = !running.get() && worker?.isAlive != true)
            if (part.length() > 0L) {
                // Atomic same-directory replacement preserves the old cache on failure.
                android.system.Os.rename(part.absolutePath, real.absolutePath)
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

    /**
     * [#1225] STOP THE PICTURE, LEAVE THE SOUND.
     *
     * The screen going off is not a reason to stop capturing audio - it
     * is the reason the operator asked for this, because a tablet face
     * down on the desk is still playing the station. This is the road
     * the recorder service and standby take; the full stop() is kept for
     * a service being destroyed, which really must release the loopback
     * policy and its retry thread.
     */
    fun stopVideo() = stop(keepAudio = true)

    @Synchronized
    fun stop(keepAudio: Boolean = false, deferHistory: Boolean = false) {
        val was = running.get()
        running.set(false)
        if (!keepAudio) {
            if (mirrorEncoderLease.held) stopOwnedJpegCapture(mirrorEncoderLease.owner)
            mirrorEncoderLease.cancelResume()
            persistMirrorLease()
            deferredVideoStart = false
            externalReplayTimer?.cancel()
            externalReplayTimer = null
            audioCapture.stop()                               // [#1225]
        }
        videoReleaseError = null
        try { display?.release(); display = null }
        catch (err: Exception) { videoReleaseError = "the replay display did not release: " + err.message }
        try { worker?.join(1500) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        try { codec?.stop() } catch (err: Exception) { /* gone */ }
        try { codec?.release(); codec = null }
        catch (err: Exception) { videoReleaseError = "the replay encoder did not release: " + err.message }
        try { surface?.release(); surface = null }
        catch (err: Exception) { videoReleaseError = "the replay surface did not release: " + err.message }
        try { worker?.join(250) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        if (worker?.isAlive == true) videoReleaseError = "the replay drain is still closing"
        else worker = null
        /* THE RING IS NOT CLEARED. Stopping happens when the screen goes off,
         * and the half-minute before that is exactly what somebody will want
         * when they pick the tablet up again.
         *
         * IT IS ALSO WRITTEN TO DISK HERE, which is what makes it a cache
         * rather than a buffer: the app goes away on every deploy, every
         * crash and whenever Android reclaims it, and "pull from it at any
         * time" has to survive all three. */
        if (deferHistory) {
            if (was) mirrorHistoryPending = true
        } else if (was || mirrorHistoryPending || historyWriter.hasPending) {
            mirrorHistoryPending = false
            keep() // Flush even though mirror acquire already stopped video.
        }
    }

    /** Called after the ordered ACK has been delivered. The same atomic
     * history cache is retained without holding the encoder control lock. */
    fun cacheMirrorHistoryAsync() {
        synchronized(this) {
            if (!mirrorHistoryPending) return
            historyWriter.enqueue()
            mirrorHistoryPending = false
        }
    }

    /** Write the history now, without stopping - for a deliberate shutdown. */
    @Synchronized
    fun flush() = keep()

    /**
     * #1182T: STAND DOWN COMPLETELY, AND GIVE THE MEMORY BACK.
     *
     * stop() releases the encoder and the VirtualDisplay and writes the
     * history to disk, and that is right for the screen going dark - the ring
     * is deliberately KEPT in memory there, because "the last minutes before
     * the tablet was put down" is exactly what somebody picking it up wants.
     *
     * Standby is the other case. Another app is in the foreground on a 4 GB
     * tablet, and the ring is the largest single thing this process holds:
     * sized from the constants at 600 kbps x 1200 s with a quarter of
     * headroom, capped at 100 MB, as one ByteArray on the Dalvik heap. The
     * AutoBrowse port measured this terminal at 777 MB RSS and worth about
     * 1.2 GB of MemAvailable; this is the biggest single piece of that which
     * can be handed back without going anywhere near the radio.
     *
     * NOTHING IS LOST. stop() has already put the history on disk - that is
     * what makes it a cache rather than a buffer - so letGo() drops a copy and
     * not the record, and prime() reads it back in on the way out. It is
     * exactly the round trip this class already makes across a process death,
     * which is the strongest evidence there is that it works: the app goes
     * away on every deploy and the history survives it.
     */
    @Synchronized
    fun release() {
        /* [#1225] The ninety megabytes of VIDEO blob is what #1182T came
         * to give back; the audio window is a separate fixed 24 MB and
         * the capture thread costs nothing to leave running. Standby
         * used to take the sound down with the picture, so the tablet
         * stopped capturing every time another app came forward. */
        stop(keepAudio = true)
        historyWriter.invalidate { ring.letGo() }
        Log.i(TAG, "#1182T standing down: the ring is on disk and its memory is "
            + "back with the heap")
    }

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
    /**
     * @param back #1155: seconds before the newest frame held where the
     *   written clip ENDS. 0 - the default - is the tail, exactly as
     *   before. See ReplayRing.save; [lastSavedEndBack] says where the cut
     *   actually landed afterwards.
     */
    @Synchronized
    fun save(want: Double, allowVideoOnly: Boolean = false, back: Double = 0.0): Pair<File, Double> {
        val dir = File(context.cacheDir, "replay").apply { mkdirs() }
        val out = File(dir, "replay-" + System.currentTimeMillis() + ".mp4")
        /* A second of slack so "everything" does not fall a frame short of
         * the oldest keyframe and quietly drop the start. */
        val all = (ring.seconds() + 1.0).coerceAtLeast(1.0)
        val from = back.coerceIn(0.0, (all - 1.0).coerceAtLeast(0.0))
        val got = try { ring.save(out, want.coerceIn(1.0, all - from), allowVideoOnly, from) }
        finally { lastSavedAudio = JSONObject(ring.lastSavedAudio.toString()).put("capture", audioStatus()) }
        return Pair(out, got)
    }

    /** #1155: how far the last [save] ended behind the newest frame held. */
    fun lastSavedEndBack(): Double = ring.lastSavedEndBack

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

        /* [rec-quality] THE LEVELS. Standard is the ring as it always was -
         * half size, twelve frames, 0.6 Mbit, see the note at the top - and
         * the one it always comes back to. The others are opted into from
         * the export sheet for a while and pay for their detail in time
         * held: the ring's memory ceiling does not move, so at three or
         * four times the bitrate it holds a third or a quarter as long. */
        class Quality(val id: Int, val label: String, val scale: Double, val fps: Int, val bitrate: Int)

        val QUALITIES = listOf(
            Quality(0, "Standard", 0.5, 12, 600_000),
            Quality(1, "Sharp", 0.75, 15, 1_400_000),
            Quality(2, "Full detail", 1.0, 15, 2_500_000),
        )

        /* "I might want to do it for moments and then go back to the
         * current settings ... a time period that turns off after 2 hours
         * or resets on rebroadcast" (the operator, 2026-09-30). Held in
         * memory only, so any restart of the recorder is Standard again. */
        const val OPT_IN_MS = 2L * 60 * 60 * 1000
    }

    /* [rec-quality] the level in force, and when an opt-in runs out */
    @Volatile private var level = 0
    @Volatile private var levelUntil = 0L
    private var revert: java.util.Timer? = null
    private val q: Quality get() = QUALITIES[level.coerceIn(0, QUALITIES.size - 1)]

    /** [rec-quality] What the export sheet shows: every level, how long the
     *  ring holds at it (the design floor - a still screen holds more), the
     *  level in force and when it lapses. */
    fun qualityState(): JSONObject {
        try { ReplayPrefs.load(context) } catch (e: Exception) { /* keep what is loaded */ }
        val cap = ReplayPrefs.capBytes.toDouble()
        val levels = org.json.JSONArray()
        for (it in QUALITIES) {
            /* [rec-quality-pct] what it actually encodes at, and so how long
             * the ring's ceiling holds - no longer capped at the design
             * twenty minutes, since a halved bitrate really does hold more. */
            levels.put(JSONObject().put("id", it.id).put("label", it.label)
                .put("width_share", it.scale).put("fps", it.fps).put("bitrate", bitrateFor(it))
                .put("holds_seconds", (cap / (bitrateFor(it) / 8.0) / 1.25).toInt()))
        }
        return JSONObject().put("level", level).put("label", q.label).put("levels", levels)
            .put("quality_pct", ReplayPrefs.qualityPct)
            .put("bitrate_now", bitrateFor(q))
            .put("until_ms", levelUntil)
            .put("left_seconds", if (levelUntil > 0) ((levelUntil - System.currentTimeMillis()) / 1000).coerceAtLeast(0) else 0)
            .put("running", running.get())
    }

    /**
     * [rec-quality] Move the ring to another level.
     *
     * An encoder cannot change its frame size in flight, and a ring that
     * held two sizes would cut files a player cannot open - so the ring
     * starts fresh at the new level (the held picture AND sound go; the
     * export sheet says so before the switch), through the same clean stop
     * the screen going dark uses ([venc-safe]: the encoder is given back,
     * never torn down mid-frame). Anything above Standard lapses after
     * OPT_IN_MS; asking for the level already in force restarts its clock.
     */
    @Synchronized
    fun setQuality(want: Int, why: String = "the export sheet"): String? {
        val l = want.coerceIn(0, QUALITIES.size - 1)
        revert?.cancel()
        revert = null
        if (l == level) {
            levelUntil = if (l > 0) System.currentTimeMillis() + OPT_IN_MS else 0L
            armRevert()
            return null
        }
        val was = running.get()
        level = 0                                   // keep() writes nothing above Standard
        stop(keepAudio = true)
        historyWriter.invalidate {
            try { cacheFile().delete() } catch (err: Exception) { /* nothing cached */ }
            ring.reset()
            level = l
        }
        levelUntil = if (l > 0) System.currentTimeMillis() + OPT_IN_MS else 0L
        Log.i(TAG, "[rec-quality] " + q.label + " (" + why + ")")
        armRevert()
        return if (was) start() else null
    }

    /** [rec-quality-pct] The level's bitrate at the operator's share. */
    private fun bitrateFor(at: Quality): Int =
        (at.bitrate.toLong() * ReplayPrefs.qualityPct / 100).toInt().coerceAtLeast(100_000)

    /**
     * [rec-quality-pct] Set the quality share, kept across restarts.
     *
     * Unlike setQuality() this does NOT start the ring fresh: the frame size
     * is unchanged, so the running encoder is simply told its new bitrate
     * (MediaCodec.PARAMETER_KEY_VIDEO_BITRATE) and everything held stays.
     * A sleeping recorder picks it up at its next start().
     */
    @Synchronized
    fun setQualityPct(pct: Int): String? {
        ReplayPrefs.saveQuality(context, pct)
        val c = codec
        if (!running.get() || c == null) return null
        return try {
            c.setParameters(android.os.Bundle().apply {
                putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, bitrateFor(q))
            })
            Log.i(TAG, "[rec-quality-pct] " + ReplayPrefs.qualityPct + "% = " + bitrateFor(q) + " bit/s")
            null
        } catch (err: Exception) {
            err.message ?: err.toString()
        }
    }

    private fun armRevert() {
        if (level == 0 || levelUntil <= 0L) return
        val t = java.util.Timer("rec-quality", true)
        t.schedule(object : java.util.TimerTask() {
            override fun run() {
                try { setQuality(0, "two hours are up") } catch (err: Exception) { /* next start is Standard */ }
            }
        }, (levelUntil - System.currentTimeMillis()).coerceAtLeast(1000L))
        revert = t
    }
}
