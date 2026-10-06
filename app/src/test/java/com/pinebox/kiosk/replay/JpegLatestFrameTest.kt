package com.pinebox.kiosk.replay

import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class JpegLatestFrameTest {
    @Test fun aSlowConsumerReceivesOnlyTheNewestPublishedPicture() {
        val frames = JpegLatestFrame()
        frames.publish(byteArrayOf(1)); val first = frames.next(0)!!
        repeat(1000) { frames.publish(byteArrayOf((it and 255).toByte())) }
        val latest = frames.next(first.sequence)!!
        assertEquals(1001L, latest.sequence)
        assertEquals((999 and 255).toByte(), latest.jpeg[0])
        assertArrayEquals(byteArrayOf(1), first.jpeg)
        frames.close()
    }
    @Test fun aStaticInitialFrameIsRetainedForALaterSocketConnection() {
        val frames = JpegLatestFrame()
        frames.publish(byteArrayOf(1,2,3))
        assertArrayEquals(byteArrayOf(1,2,3), frames.next(0)!!.jpeg)
        frames.close()
    }
    @Test fun closingWakesAWaitingSocketAndStopsFuturePublication() {
        val frames = JpegLatestFrame(); val worker = Executors.newSingleThreadExecutor()
        try {
            val waiting = worker.submit<JpegLatestFrame.Frame?> { frames.next(0) }
            frames.close()
            assertNull(waiting.get(1, TimeUnit.SECONDS))
            assertFalse(frames.publish(byteArrayOf(1)))
            assertNull(frames.next(0))
        } finally { worker.shutdownNow() }
    }
    @Test fun oversizedFramesAreRejectedBeforeTheyCanBeRetained() {
        val frames = JpegLatestFrame()
        try { frames.publish(ByteArray(JpegFrameBuffer.MAX_FRAME_BYTES + 1)); fail("Oversized frame accepted") }
        catch (_: IllegalArgumentException) { }
        frames.close()
    }
}
