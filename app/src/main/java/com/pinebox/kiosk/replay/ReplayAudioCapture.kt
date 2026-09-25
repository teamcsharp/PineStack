package com.pinebox.kiosk.replay

import android.content.Context
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Process
import android.util.Log
import com.pinebox.kiosk.audio.PlaybackLoopback
import org.json.JSONObject
import org.json.JSONArray
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** AAC encoding runs beside the screen encoder, independent of WebView work. */
internal class ReplayAudioCapture(private val context: Context, private val ring: ReplayRing) {
    private val running = AtomicBoolean(false)
    private var worker: Thread? = null
    @Volatile private var input: AudioRecord? = null
    @Volatile private var state = "stopped"
    @Volatile private var error: String? = null
    @Volatile private var frames = 0L
    @Volatile private var signalFrames = 0L
    @Volatile private var lastPacketNs = 0L
    @Volatile private var retries = 0
    @Volatile private var nextRetryNs = 0L
    @Volatile private var bufferFrames = 0
    @Volatile private var backlogFrames = 0L
    @Volatile private var clockDriftUs = 0L
    private val failures = java.util.ArrayDeque<JSONObject>()

    @Synchronized fun start() {
        if (worker?.isAlive == true) return
        running.set(true)
        state = "starting"; error = null; frames = 0; signalFrames = 0; lastPacketNs = 0
        retries = 0; nextRetryNs = 0
        worker = thread(name = "pine-replay-audio", isDaemon = true) {
            val backoff = ReplayRetryBackoff()
            try {
                while (running.get()) {
                    val before = frames
                    nextRetryNs = 0
                    capture()
                    if (!running.get()) break
                    // Recover ordinary device/codec interruptions while the
                    // service remains awake. Gaps retain real capture time.
                    if (frames - before >= RATE * 10L) backoff.reset()
                    val delay = backoff.nextDelayMs()
                    retries++
                    nextRetryNs = System.nanoTime() + delay * 1_000_000
                    Thread.sleep(delay)
                }
            } catch (_: InterruptedException) {
                // stop() cancels a pending retry immediately.
            } finally {
                running.set(false)
                nextRetryNs = 0
                if (state != "unavailable") state = "stopped"
            }
        }
    }

    @Synchronized fun stop() {
        running.set(false)
        try { input?.stop() } catch (_: Exception) { }
        worker?.interrupt()
        try { worker?.join(2000) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        if (worker?.isAlive != true) worker = null
        if (state != "unavailable") state = "stopped"
    }

    fun status(): JSONObject = JSONObject().put("source", "android-playback-mix")
        .put("source_scope", "eligible-device-media").put("device_volume_applied", false)
        .put("state", if (state == "capturing" && signalFrames == 0L) "captured_silence" else state)
        .put("running", running.get()).put("available", running.get() && state == "capturing" && lastPacketNs > 0 && error == null && System.nanoTime() - lastPacketNs < 2_000_000_000L)
        .put("retry_count", retries).put("retry_in_ms", if (nextRetryNs > 0) ((nextRetryNs - System.nanoTime()) / 1_000_000).coerceAtLeast(0) else JSONObject.NULL)
        .put("recent_failures", synchronized(failures) { JSONArray(failures.map { JSONObject(it.toString()) }) })
        .put("buffer_frames", bufferFrames).put("capture_backlog_frames", backlogFrames).put("clock_drift_us", clockDriftUs)
        .put("sample_rate", RATE).put("channels", CHANNELS).put("clock", "monotonic")
        .put("captured_frames", frames).put("signal_frames", signalFrames)
        .put("last_packet_age_ms", if (lastPacketNs > 0) (System.nanoTime() - lastPacketNs) / 1_000_000 else JSONObject.NULL)
        .put("error", error ?: JSONObject.NULL)
        .put("detail", error ?: when {
            !running.get() -> "Playback capture is stopped; previously recorded samples remain in the replay history."
            lastPacketNs == 0L -> "Starting Android playback capture and waiting for timestamped audio samples."
            System.nanoTime() - lastPacketNs >= 2_000_000_000L -> "No recent encoded playback audio has arrived; current capture is unavailable."
            signalFrames == 0L -> "Capturing device media playback; no nonzero audio signal has been observed. Silence or capture policy restrictions may be responsible."
            else -> "Device media playback copied through Android's render-and-loopback mix; no microphone or server audio."
        })

    private fun capture() {
        var loopback: PlaybackLoopback? = null
        var codec: MediaCodec? = null
        try {
            Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
            loopback = PlaybackLoopback.open(context, RATE, CHANNELS)
            val record = loopback.record
            input = record
            bufferFrames = record.bufferSizeInFrames
            codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
            val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, RATE, CHANNELS).apply {
                setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
                setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096)
            }
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()
            record.startRecording()
            check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING) { "Playback capture did not start" }
            val pcm = ShortArray(1024 * CHANNELS)
            val timestamp = AudioTimestamp()
            val clock = PcmCaptureClock(RATE)
            var readFrames = 0L
            var endPts = 0L
            val signalEvidence = ReplayPcmSignal()
            val began = System.nanoTime()
            while (running.get()) {
                val got = record.read(pcm, 0, pcm.size, AudioRecord.READ_BLOCKING)
                if (got < 0) kotlin.error("Playback capture read failed ($got)")
                if (got == 0) continue
                check(got % CHANNELS == 0) { "Playback capture returned an incomplete audio frame" }
                val firstFrame = readFrames
                readFrames += got / CHANNELS
                if (record.getTimestamp(timestamp, AudioTimestamp.TIMEBASE_MONOTONIC) != AudioRecord.SUCCESS) {
                    check(System.nanoTime() - began < 2_000_000_000L) { "Playback capture has no monotonic audio timestamp" }
                    continue // Do not invent a clock for startup samples.
                }
                backlogFrames = timestamp.framePosition - readFrames
                check(backlogFrames <= bufferFrames.toLong()) {
                    "Playback capture overran its audio buffer ($backlogFrames frames ahead, capacity $bufferFrames); sample continuity is unavailable"
                }
                val pts = try { clock.stamp(firstFrame, timestamp.framePosition, timestamp.nanoTime) }
                    finally { clockDriftUs = clock.observedDriftUs }
                val inputDeadline = System.nanoTime() + 1_000_000_000L
                var slot = codec.dequeueInputBuffer(10_000)
                while (slot < 0 && running.get()) {
                    check(System.nanoTime() < inputDeadline) { "Playback audio encoder stopped accepting samples" }
                    drain(codec, signalEvidence)
                    slot = codec.dequeueInputBuffer(10_000)
                }
                if (slot < 0) break
                val buffer = codec.getInputBuffer(slot) ?: kotlin.error("AAC input buffer unavailable")
                buffer.clear(); buffer.order(ByteOrder.nativeOrder())
                check(buffer.remaining() >= got * 2) { "AAC input buffer cannot hold a capture block" }
                for (i in 0 until got) buffer.putShort(pcm[i])
                var signal = false
                for (i in 0 until got) if (pcm[i].toInt() != 0) { signal = true; break }
                endPts = pts + (got / CHANNELS) * 1_000_000L / RATE
                signalEvidence.add(pts, endPts, signal)
                codec.queueInputBuffer(slot, 0, got * 2, pts, 0)
                frames += got / CHANNELS
                if (signal) signalFrames += got / CHANNELS
                drain(codec, signalEvidence)
            }
            // Flush the final AAC packet without manufacturing a timestamp.
            val slot = codec.dequeueInputBuffer(10_000)
            if (slot >= 0) {
                codec.queueInputBuffer(slot, 0, 0, endPts, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                drain(codec, signalEvidence, finishing = true)
            }
        } catch (failure: Throwable) {
            if (running.get()) {
                error = (failure.cause?.message ?: failure.message ?: failure.javaClass.simpleName).take(300)
                state = "unavailable"
                synchronized(failures) {
                    if (failures.size >= 8) failures.removeFirst()
                    failures.addLast(JSONObject().put("observed_at_ms", System.currentTimeMillis())
                        .put("error", error).put("attempt", retries + 1))
                }
                Log.w("PineReplayAudio", "Playback capture attempt ${retries + 1} stopped: $error")
            }
        } finally {
            input = null
            try { codec?.stop() } catch (_: Exception) { }
            try { codec?.release() } catch (_: Exception) { }
            loopback?.close()
            if (!running.get() && state != "unavailable") state = "stopped"
        }
    }

    private fun drain(codec: MediaCodec, signalEvidence: ReplayPcmSignal, finishing: Boolean = false) {
        val info = MediaCodec.BufferInfo()
        var attempts = 0
        while (attempts++ < (if (finishing) 30 else 16)) {
            val index = codec.dequeueOutputBuffer(info, if (finishing) 10_000 else 0)
            if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) { ring.rememberAudio(codec.outputFormat); continue }
            if (index < 0) { if (finishing) continue else break }
            val output = codec.getOutputBuffer(index)
            if (output != null && info.size > 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                ring.addAudio(output, info, signalEvidence.at(info.presentationTimeUs,
                    info.presentationTimeUs + 1_024_000_000L / RATE))
                lastPacketNs = System.nanoTime()
                error = null
                state = "capturing"
            }
            codec.releaseOutputBuffer(index, false)
            if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
        }
    }

    companion object { const val RATE = 48000; const val CHANNELS = 2; const val BITRATE = 128000 }
}
