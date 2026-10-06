package com.pinebox.kiosk.replay

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class ReplayRgbaRowsTest {
    @Test fun rowPaddingAndMissingFinalPaddingDoNotLeakIntoPixels() {
        val buffer = ByteBuffer.wrap(byteArrayOf(1,2,3,4,5,6,7,8,99,99,99,99,9,10,11,12,13,14,15,16))
        val out = ByteArray(16)
        ReplayRgbaRows.copy(buffer, 2, 2, 4, 12, out)
        assertArrayEquals(ByteArray(16) { (it + 1).toByte() }, out)
        assertEquals(0, buffer.position())
    }
    @Test fun originalBufferPositionAndPixelGapsAreRespected() {
        val buffer = ByteBuffer.wrap(byteArrayOf(99,99,1,2,3,4,88,88,5,6,7,8))
        buffer.position(2)
        val out = ByteArray(8)
        ReplayRgbaRows.copy(buffer, 2, 1, 6, 10, out)
        assertArrayEquals(ByteArray(8) { (it + 1).toByte() }, out)
        assertEquals(2, buffer.position())
    }
    @Test fun outputCanBeReusedAndOnlyVisiblePixelsAreWritten() {
        val out = ByteArray(12) { 42 }
        ReplayRgbaRows.copy(ByteBuffer.wrap(byteArrayOf(1,2,3,4)), 1, 1, 4, 4, out)
        ReplayRgbaRows.copy(ByteBuffer.wrap(byteArrayOf(5,6,7,8)), 1, 1, 4, 4, out)
        assertArrayEquals(byteArrayOf(5,6,7,8,42,42,42,42,42,42,42,42), out)
    }
    private fun rejected(work: () -> Unit) {
        try { work(); fail("Unsafe mirror plane accepted") } catch (_: IllegalArgumentException) { }
    }
    @Test fun invalidAndOverflowingDimensionsAreRejected() {
        rejected { ReplayRgbaRows.byteCount(0, 2) }
        rejected { ReplayRgbaRows.byteCount(-1, 2) }
        rejected { ReplayRgbaRows.byteCount(Int.MAX_VALUE, Int.MAX_VALUE) }
        rejected { ReplayRgbaRows.byteCount(4096, 4096) }
    }
    @Test fun truncatedPlaneOrInvalidStridesCannotReachBufferAccess() {
        rejected { ReplayRgbaRows.copy(ByteBuffer.allocate(7), 2, 1, 4, 8, ByteArray(8)) }
        rejected { ReplayRgbaRows.copy(ByteBuffer.allocate(8), 2, 1, 3, 8, ByteArray(8)) }
        rejected { ReplayRgbaRows.copy(ByteBuffer.allocate(8), 2, 1, 4, 7, ByteArray(8)) }
        rejected { ReplayRgbaRows.copy(ByteBuffer.allocate(8), 2, 1, Int.MAX_VALUE, Int.MAX_VALUE, ByteArray(8)) }
        rejected { ReplayRgbaRows.copy(ByteBuffer.allocate(8), 2, 1, 4, 8, ByteArray(7)) }
    }
}
