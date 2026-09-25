package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class ReplayAudioWindowTest {
    private fun packet(time: Long, duration: Long = 20_000, bytes: Int = 2) =
        ReplayAudioPacket(time, ByteArray(bytes), durationUs = duration)

    @Test fun sampleClockUsesHardwareOriginAndFrameCount() {
        val clock = PcmCaptureClock(48_000)
        val origin = 5_000_000_000L
        assertEquals(origin, clock.stamp(0, 480, (origin + 10_000) * 1000))
        assertEquals(origin + 20_000, clock.stamp(960, 1_920, (origin + 40_000) * 1000))
    }

    @Test fun callbackDelayDoesNotCompressAudioTime() {
        val clock = PcmCaptureClock(48_000)
        val origin = 9_000_000L
        clock.stamp(0, 960, (origin + 20_000) * 1000)
        // Hardware timestamp progressed much farther than this queued read.
        assertEquals(origin + 20_000, clock.stamp(960, 9_600, (origin + 200_000) * 1000))
    }

    @Test fun hardwareClockResetFailsInsteadOfInventingContinuity() {
        val clock = PcmCaptureClock(48_000)
        clock.stamp(0, 480, 10_010_000_000)
        assertThrows(IllegalArgumentException::class.java) {
            clock.stamp(480, 960, 11_020_000_000)
        }
    }

    @Test fun repeatedReadPositionFails() {
        val clock = PcmCaptureClock(48_000)
        clock.stamp(0, 480, 10_010_000_000)
        assertThrows(IllegalArgumentException::class.java) {
            clock.stamp(0, 960, 10_020_000_000)
        }
    }

    @Test fun byteAndPacketBoundsEvictWholeOldPackets() {
        val bytes = ReplayAudioWindow(5, 100)
        bytes.add(packet(0)); bytes.add(packet(20_000)); bytes.add(packet(40_000))
        assertEquals(listOf(20_000L, 40_000L), bytes.select(0, 100_000).map { it.timeUs })
        assertEquals(4, bytes.bytes())
        val count = ReplayAudioWindow(100, 2)
        count.add(packet(0)); count.add(packet(20_000)); count.add(packet(40_000))
        assertEquals(2, count.select(0, 100_000).size)
    }

    @Test fun stalePacketCannotRewriteHistory() {
        val ring = ReplayAudioWindow(100, 10)
        ring.add(packet(40_000)); ring.add(packet(20_000)); ring.add(packet(40_000))
        assertEquals(listOf(40_000L), ring.select(0, 100_000).map { it.timeUs })
    }

    @Test fun selectionPreservesSharedClockOffset() {
        val ring = ReplayAudioWindow(100, 10)
        ring.add(packet(9_000_000)); ring.add(packet(9_020_000)); ring.add(packet(9_040_000))
        val start = 9_010_000L // chosen video keyframe precedes next whole AAC packet
        assertEquals(listOf(10_000L, 30_000L), ring.select(start, 9_050_000).map { it.timeUs - start })
    }

    @Test fun continuousSamplesCoverSelectedWindow() {
        val samples = (0 until 50).map { packet(it * 20_000L) }
        val coverage = ReplayAudioCoverage.measure(samples, 0, 1_000_000)
        assertTrue(coverage.complete)
        assertEquals(1.0, coverage.ratio, 0.00001)
        assertEquals(0L, coverage.maxGapUs)
    }

    @Test fun missingAudioAtEitherBoundaryIsIncomplete() {
        val samples = (10 until 40).map { packet(it * 20_000L) }
        val coverage = ReplayAudioCoverage.measure(samples, 0, 1_000_000)
        assertFalse(coverage.complete)
        assertEquals(200_000L, coverage.leadingUs)
        assertEquals(200_000L, coverage.trailingUs)
        assertEquals(0.6, coverage.ratio, 0.00001)
    }

    @Test fun repeatedShortGapsDoNotPassAsCompleteAudio() {
        val samples = (0 until 25).map { packet(it * 40_000L) }
        val coverage = ReplayAudioCoverage.measure(samples, 0, 1_000_000)
        assertFalse(coverage.complete)
        assertEquals(0.5, coverage.ratio, 0.00001)
    }

    @Test fun signalEvidenceDistinguishesSilenceFromUnavailable() {
        val evidence = ReplayPcmSignal()
        evidence.add(20_000, 40_000, false)
        evidence.add(40_000, 60_000, true)
        assertNull(evidence.at(0, 20_000))
        assertEquals(false, evidence.at(20_000, 40_000))
        assertEquals(true, evidence.at(30_000, 50_000))
        assertNull(evidence.at(60_000, 80_000))
    }

    @Test fun retryDelayIsBoundedAndResetAfterHealthyCapture() {
        val backoff = ReplayRetryBackoff()
        assertEquals(listOf(1000L, 2000L, 4000L, 8000L, 16000L, 30000L, 30000L),
            (0 until 7).map { backoff.nextDelayMs() })
        backoff.reset()
        assertEquals(1000L, backoff.nextDelayMs())
    }

    @Test fun restartedCaptureRetainsGapOnCommonClock() {
        val ring = ReplayAudioWindow(1000, 100)
        (0 until 10).forEach { ring.add(packet(it * 20_000L)) }
        // Capture restarts after a second; missing time must remain missing.
        (60 until 70).forEach { ring.add(packet(it * 20_000L)) }
        val coverage = ReplayAudioCoverage.measure(ring.select(0, 1_400_000), 0, 1_400_000)
        assertFalse(coverage.complete)
        assertEquals(1_000_000L, coverage.maxGapUs)
        assertEquals(1, coverage.gaps)
    }
}
