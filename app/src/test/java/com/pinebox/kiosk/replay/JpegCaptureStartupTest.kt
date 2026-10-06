package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class JpegCaptureStartupTest {
    // Mirrors ImageReader: a queued image survives a missed notification,
    // but attaching a listener does not replay a notification already dropped.
    private class QuietReader {
        var pending = 0
        var captured = 0
        var listener: (() -> Unit)? = null
        val work = ArrayDeque<() -> Unit>()
        fun publish() { pending++; listener?.let { work.add(it) } }
        fun capture() { if (pending > 0) { pending = 0; captured++ } }
        fun finishWork() { while (work.isNotEmpty()) work.removeFirst()() }
    }

    @Test fun theOnlyStaticFramePublishedInsideDisplayCreationIsCaptured() {
        val reader = QuietReader()
        JpegCaptureStartup.run(
            { reader.listener = { reader.capture() } },
            { reader.publish() },
            { reader.work.add { reader.capture() } })
        reader.finishWork()
        assertEquals(1, reader.captured)
        assertEquals(0, reader.pending)
    }

    @Test fun anImageWithAnEarlierDroppedNotificationIsDrainedWithoutMotion() {
        val reader = QuietReader()
        reader.publish() // No listener; notification is lost, image is queued.
        JpegCaptureStartup.run(
            { reader.listener = { reader.capture() } },
            { /* Producer stays quiet; registering never emits another event. */ },
            { reader.work.add { reader.capture() } })
        assertEquals(0, reader.captured)
        reader.finishWork()
        assertEquals(1, reader.captured)
    }

    @Test fun aLaterImageStillUsesTheListenerAfterTheEmptyInitialDrain() {
        val reader = QuietReader()
        JpegCaptureStartup.run(
            { reader.listener = { reader.capture() } },
            { },
            { reader.work.add { reader.capture() } })
        reader.finishWork()
        assertEquals(0, reader.captured)
        reader.publish()
        reader.finishWork()
        assertEquals(1, reader.captured)
    }

    @Test fun aFailedDisplayCreationNeverQueuesAReadAndReachesCleanup() {
        var attached = false
        var queued = false
        var cleaned = false
        try {
            JpegCaptureStartup.run({ attached = true },
                { throw IllegalStateException("display refused") }, { queued = true })
            fail("Creation failure swallowed")
        } catch (_: IllegalStateException) {
            // Session.start's caller retains handles and runs its stop barrier.
            cleaned = true
        }
        assertTrue(attached)
        assertFalse(queued)
        assertTrue(cleaned)
    }
}
