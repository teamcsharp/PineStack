package com.pinebox.kiosk.replay

import java.util.ArrayDeque
import kotlin.math.abs

/** Encoded audio keeps capture time. Missing samples are never packed together. */
internal data class ReplayAudioPacket(
    val timeUs: Long,
    val data: ByteArray,
    val flags: Int = 0,
    val durationUs: Long = 1_024_000_000L / 48000,
    val signal: Boolean? = null,
)

internal class ReplayAudioWindow(private val maxBytes: Int, private val maxPackets: Int) {
    private val packets = ArrayDeque<ReplayAudioPacket>()
    private var bytes = 0

    @Synchronized fun clear() { packets.clear(); bytes = 0 }

    @Synchronized fun add(packet: ReplayAudioPacket) {
        if (packet.data.isEmpty() || packet.data.size > maxBytes) return
        // A stale encoder callback cannot rewrite or append behind newer audio.
        if (packets.peekLast()?.let { packet.timeUs <= it.timeUs } == true) return
        while (packets.isNotEmpty() && (bytes + packet.data.size > maxBytes || packets.size >= maxPackets)) {
            bytes -= packets.removeFirst().data.size
        }
        packets.addLast(packet)
        bytes += packet.data.size
    }

    @Synchronized fun select(fromUs: Long, untilUs: Long): List<ReplayAudioPacket> =
        packets.filter { it.timeUs >= fromUs && it.timeUs <= untilUs }

    @Synchronized fun seconds(): Double = if (packets.size < 2) 0.0 else
        (packets.last.timeUs - packets.first.timeUs) / 1_000_000.0

    @Synchronized fun bytes(): Int = bytes
}

internal class ReplayRetryBackoff {
    private var failures = 0
    fun nextDelayMs(): Long = (1_000L shl failures.coerceAtMost(5)).coerceAtMost(30_000L).also { failures++ }
    fun reset() { failures = 0 }
}

internal data class ReplayAudioCoverage(
    val present: Boolean, val ratio: Double, val gaps: Int,
    val leadingUs: Long, val trailingUs: Long, val maxGapUs: Long,
) {
    // AAC has a 21 ms frame at 48 kHz. Tolerate a frame boundary and the
    // deliberate 100 ms screen-off join, not seconds of uncaptured sound.
    val complete: Boolean get() = present && ratio >= 0.97 && leadingUs <= 150_000 && trailingUs <= 150_000 && maxGapUs <= 150_000

    companion object {
        fun measure(packets: List<ReplayAudioPacket>, fromUs: Long, untilUs: Long): ReplayAudioCoverage {
            if (packets.isEmpty() || untilUs <= fromUs) return ReplayAudioCoverage(false, 0.0, 0,
                (untilUs - fromUs).coerceAtLeast(0), 0, 0)
            val leading = (packets.first().timeUs - fromUs).coerceAtLeast(0)
            var cursor = fromUs
            var covered = 0L
            var gaps = 0
            var maxGap = 0L
            for (packet in packets) {
                val start = packet.timeUs.coerceAtLeast(fromUs)
                val end = (packet.timeUs + packet.durationUs).coerceAtMost(untilUs)
                if (start - cursor > 30_000) {
                    gaps++
                    maxGap = maxOf(maxGap, start - cursor)
                }
                covered += (end - maxOf(cursor, start)).coerceAtLeast(0)
                cursor = maxOf(cursor, end)
            }
            val trailing = (untilUs - cursor).coerceAtLeast(0)
            return ReplayAudioCoverage(true, (covered.toDouble() / (untilUs - fromUs)).coerceIn(0.0, 1.0),
                gaps, leading, trailing, maxOf(maxGap, trailing))
        }
    }
}

/** Small PCM evidence queue; AAC priming without corresponding input stays unknown. */
internal class ReplayPcmSignal {
    private data class Span(val from: Long, val until: Long, val signal: Boolean)
    private val spans = ArrayDeque<Span>()

    fun add(from: Long, until: Long, signal: Boolean) {
        spans.addLast(Span(from, until, signal))
        while (spans.size > 256) spans.removeFirst()
    }

    fun at(from: Long, until: Long): Boolean? {
        while (spans.peekFirst()?.let { it.until <= from } == true) spans.removeFirst()
        val found = spans.filter { it.from < until && it.until > from }
        return if (found.isEmpty()) null else found.any { it.signal }
    }
}

/** AudioRecord TIMEBASE_MONOTONIC frame positions, not wall-clock polling. */
internal class PcmCaptureClock(private val rate: Int) {
    private var originUs: Long? = null
    private var lastUs: Long? = null
    var observedDriftUs = 0L
        private set

    fun stamp(frame: Long, timestampFrame: Long, timestampNano: Long): Long {
        require(frame >= 0 && timestampFrame >= 0 && timestampNano > 0) { "invalid audio timestamp" }
        val candidate = timestampNano / 1000 - timestampFrame * 1_000_000L / rate
        val origin = originUs
        observedDriftUs = candidate - (origin ?: candidate)
        // A reset or discontinuous hardware clock requires a fresh capture,
        // rather than quietly pretending dropped audio was contiguous.
        require(origin == null || abs(observedDriftUs) <= 100_000) { "playback capture clock discontinuity ($observedDriftUs us)" }
        if (origin == null) originUs = candidate
        val value = originUs!! + frame * 1_000_000L / rate
        require(lastUs == null || value > lastUs!!) { "playback capture timestamp went backwards" }
        lastUs = value
        return value
    }
}
