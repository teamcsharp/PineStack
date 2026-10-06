package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class JpegStreamFenceTest {
    @Test fun lateStopForOldStreamCannotCloseANewerDisplayWithTheSameDesktopOwner() {
        val newer = JpegStreamFence("mirror_owner", "jpeg_newer")
        var displayOpen = true
        val stop = { displayOpen = false; true }
        assertNull(newer.stopExact("mirror_owner", "jpeg_older", stop))
        assertTrue(displayOpen)
        assertEquals(true, newer.stopExact("mirror_owner", "jpeg_newer", stop))
        assertFalse(displayOpen)
    }
    @Test fun differentOwnerCannotStopAnIdenticalStreamToken() {
        val held = JpegStreamFence("mirror_owner", "jpeg_stream")
        var releases = 0
        assertNull(held.stopExact("mirror_other", "jpeg_stream") { releases++; true })
        assertEquals(0, releases)
    }
    @Test fun incompleteReleaseRemainsExplicitlyFalseForExactOwnerAndStream() {
        val held = JpegStreamFence("mirror_owner", "jpeg_stream")
        assertEquals(false, held.stopExact("mirror_owner", "jpeg_stream") { false })
        assertTrue(held.exact("mirror_owner", "jpeg_stream"))
    }
    @Test fun onlyAdbAndThisAppCanConsumeSecureScreenFrames() {
        assertTrue(JpegStreamFence.allowedPeer(0, 10212))
        assertTrue(JpegStreamFence.allowedPeer(2000, 10212))
        assertTrue(JpegStreamFence.allowedPeer(10212, 10212))
        assertFalse(JpegStreamFence.allowedPeer(10213, 10212))
        assertFalse(JpegStreamFence.allowedPeer(-1, 10212))
    }
    @Test fun malformedTokensAreRejected() {
        for (token in listOf("", "short", "bad token", "a".repeat(101))) {
            assertFalse(JpegStreamFence.valid(token))
        }
        assertTrue(JpegStreamFence.valid("jpeg_12345678"))
    }
}
