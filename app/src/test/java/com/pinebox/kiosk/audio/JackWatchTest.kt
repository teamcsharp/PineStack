package com.pinebox.kiosk.audio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class JackWatchTest {
    @Test fun repairsStaleAnnouncementAtBoundedCadence() {
        assertTrue(shouldRepairJack(true, true, false, 20_000, 0, 10_000))
        assertFalse(shouldRepairJack(true, true, false, 24_000, 20_000, 10_000))
        assertTrue(shouldRepairJack(true, true, false, 30_000, 20_000, 10_000))
    }

    @Test fun doesNotFightHealthyOrUnknownRoutes() {
        assertFalse(shouldRepairJack(true, true, true, 30_000, 0, 10_000))
        assertFalse(shouldRepairJack(true, true, null, 30_000, 0, 10_000))
        assertFalse(shouldRepairJack(false, true, false, 30_000, 0, 10_000))
        assertFalse(shouldRepairJack(true, false, false, 30_000, 0, 10_000))
    }
}
