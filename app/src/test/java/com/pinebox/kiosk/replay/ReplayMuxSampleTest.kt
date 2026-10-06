package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class ReplayMuxSampleTest {
    @Test fun frozenVideoKeepsOnlyOffsetsIntoOriginalBlob() {
        val blob = ByteArray(2 * 1024 * 1024)
        val sample = ReplayMuxSample.snapshot(42, blob, 1234, 20, 7, true)
        assertSame(blob, sample.data)
        assertEquals(1234, sample.offset)
        assertEquals(20, sample.size)
        assertEquals(42L, sample.timeUs)
        assertEquals(7, sample.flags)
    }
    @Test fun liveExportRetainsImmutableCopiedBytes() {
        val blob = byteArrayOf(1, 2, 3, 4, 5)
        val sample = ReplayMuxSample.snapshot(10, blob, 1, 3, 0, false)
        blob.fill(0)
        assertArrayEquals(byteArrayOf(2, 3, 4), sample.data)
        assertEquals(0, sample.offset)
    }
    @Test fun scratchCopiesExactSliceAndReusesBoundedDirectAllocation() {
        val scratch = ReplayMuxBuffer(4)
        val first = scratch.sample(byteArrayOf(99, 1, 2, 3, 88), 1, 3)
        assertTrue(first.isDirect)
        assertEquals(0, first.position())
        assertEquals(3, first.limit())
        val bytes = ByteArray(first.remaining()); first.get(bytes)
        assertArrayEquals(byteArrayOf(1, 2, 3), bytes)
        val next = scratch.sample(byteArrayOf(8, 9), 0, 2)
        assertSame(first, next)
        assertEquals(4, next.capacity())
        assertEquals(2, next.limit())
        assertEquals(8.toByte(), next.get())
        assertEquals(9.toByte(), next.get())
    }
    @Test fun badPacketBoundsFailBeforeNativeMux() {
        for (bad in listOf(-1 to 1, 0 to 0, 2 to 4)) {
            try { ReplayMuxSample(0, ByteArray(4), bad.first, bad.second, 0); fail("unsafe bounds") }
            catch (_: IllegalArgumentException) { }
        }
        try { ReplayMuxBuffer(2).sample(ByteArray(4), 0, 3); fail("over capacity") }
        catch (_: IllegalArgumentException) { }
    }
}
