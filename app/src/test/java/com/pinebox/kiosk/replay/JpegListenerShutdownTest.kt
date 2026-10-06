package com.pinebox.kiosk.replay

import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class JpegListenerShutdownTest {
    @Test fun aBlockedAcceptIsWokenBeforeListenerCloseAndActuallyExits() {
        val accepted = CountDownLatch(1)
        val worker = Executors.newSingleThreadExecutor()
        val steps = mutableListOf<String>()
        try {
            val accepting = worker.submit<Boolean> { accepted.await(); true }
            // The fake listener deliberately models close() NOT waking accept().
            JpegListenerShutdown.run(true,
                { steps.add("wake"); accepted.countDown() },
                { steps.add("close") })
            assertEquals(listOf("wake", "close"), steps)
            assertTrue(accepting.get(1, TimeUnit.SECONDS))
        } finally { worker.shutdownNow() }
    }
    @Test fun aFailedWakeKeepsTheListenerAvailableForASecondCleanupAttempt() {
        var closed = false
        try {
            JpegListenerShutdown.run(true, { throw IOException("temporary failure") }, { closed = true })
            fail("Wake failure swallowed")
        } catch (_: IOException) { }
        assertFalse(closed)
        var woke = false
        JpegListenerShutdown.run(true, { woke = true }, { closed = true })
        assertTrue(woke); assertTrue(closed)
    }
    @Test fun alreadyEndedAcceptorsNeedNoLoopbackConnection() {
        var closed = false
        JpegListenerShutdown.run(false, { fail("Unnecessary connection") }, { closed = true })
        assertTrue(closed)
    }
}
