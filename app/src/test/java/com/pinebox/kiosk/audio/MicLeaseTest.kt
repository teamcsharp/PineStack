package com.pinebox.kiosk.audio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MicLeaseTest {
    @Test fun microphoneHasOneOwner() {
        val bridge = Any()
        val recognizer = Any()
        try {
            assertTrue(MicLease.acquire(bridge))
            assertTrue(MicLease.acquire(bridge))
            assertFalse(MicLease.acquire(recognizer))
            MicLease.release(recognizer)
            assertFalse(MicLease.acquire(recognizer))
            MicLease.release(bridge)
            assertTrue(MicLease.acquire(recognizer))
        } finally {
            MicLease.release(bridge)
            MicLease.release(recognizer)
        }
    }
}
