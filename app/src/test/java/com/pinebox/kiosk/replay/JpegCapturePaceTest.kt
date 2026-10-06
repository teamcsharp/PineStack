package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class JpegCapturePaceTest {
    @Test fun theFirstImageIsEligibleAtAnyDisplayVsyncPhase() {
        for (phase in 1L..5L) {
            assertTrue(JpegCapturePace.allows(phase * 16_666_667L, 0L, 12))
        }
    }

    @Test fun denseSixtyHzInputIsStillCappedAtTwelveJpegsPerSecond() {
        var last = 0L
        var captured = 0
        repeat(60) { tick ->
            val now = 1L + tick * 16_666_667L
            if (JpegCapturePace.allows(now, last, 12)) {
                captured++
                last = now
            }
        }
        assertEquals(12, captured)
    }

    @Test fun sparsePeriodicUiFramesDoNotNeedToMatchADisplayPhaseDivisor() {
        var last = 0L
        var captured = 0
        // Android's compositor phase divisor is separate from software pacing.
        // Every sequence here has remainder 1 modulo 5, even a second apart.
        for (sequence in listOf(101L, 161L, 221L, 281L)) {
            val now = sequence * 16_666_667L
            if (JpegCapturePace.allows(now, last, 12)) {
                captured++
                last = now
            }
        }
        assertEquals(4, captured)
    }

    @Test fun elapsedTimeRatherThanInputSequenceControlsTheWorkCap() {
        val last = 900_000_000L
        val period = 1_000_000_000L / 12
        assertFalse(JpegCapturePace.allows(last + period - 1L, last, 12))
        assertTrue(JpegCapturePace.allows(last + period, last, 12))
        assertFalse(JpegCapturePace.allows(last, last, 12))
    }
}
