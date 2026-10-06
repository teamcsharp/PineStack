package com.pinebox.kiosk.replay

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class JpegFrameBufferTest {
    @Test fun bulkWriteCannotGrowBeyondTheFrameLimit() {
        val output = JpegFrameBuffer(8)
        output.write(byteArrayOf(1,2,3,4,5,6), 0, 6)
        try { output.write(byteArrayOf(7,8,9), 0, 3); fail("Limit exceeded") } catch (_: IOException) { }
        assertEquals(6, output.size())
        output.write(7); output.write(8)
        try { output.write(9); fail("Limit exceeded") } catch (_: IOException) { }
        assertEquals(8, output.size())
    }
    @Test fun outputResetReusesCapacityWithoutRetainingPreviousFrameContents() {
        val output = JpegFrameBuffer(8)
        output.write(byteArrayOf(1,2,3,4), 0, 4); val frozen = output.toByteArray()
        output.reset(); output.write(byteArrayOf(9,8), 0, 2)
        assertArrayEquals(byteArrayOf(9,8), output.toByteArray())
        assertArrayEquals(byteArrayOf(1,2,3,4), frozen)
    }
    @Test fun headerEncodesTheWholeFrameAsUnsignedBigEndianLength() {
        assertArrayEquals(byteArrayOf(0,0,1,2), JpegFrameBuffer.header(258))
        assertArrayEquals(byteArrayOf(0,32,0,0), JpegFrameBuffer.header(JpegFrameBuffer.MAX_FRAME_BYTES))
    }
    @Test fun invalidFrameSizesAndSlicesAreRejected() {
        for (size in listOf(0, -1, Int.MAX_VALUE)) {
            try { JpegFrameBuffer.header(size); fail("Bad size accepted") } catch (_: IllegalArgumentException) { }
        }
        val output = JpegFrameBuffer(8)
        try { output.write(byteArrayOf(1), Int.MAX_VALUE, 1); fail("Bad bounds accepted") } catch (_: IllegalArgumentException) { }
    }
}
