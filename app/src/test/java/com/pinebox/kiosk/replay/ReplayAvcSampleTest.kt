package com.pinebox.kiosk.replay

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class ReplayAvcSampleTest {
    private fun bytes(vararg values: Int) = ByteArray(values.size) { values[it].toByte() }
    private fun canonical(data: ByteArray, offset: Int = 0, size: Int = data.size): ByteArray {
        val scratch = ByteBuffer.allocateDirect(ReplayAvcSample.requiredCapacity(data, offset, size))
        val out = ReplayAvcSample.toAnnexB(data, offset, size, scratch)
        assertSame(scratch, out)
        assertTrue(out.isDirect)
        assertEquals(0, out.position())
        return ByteArray(out.remaining()).also { out.get(it) }
    }
    private fun bad(data: ByteArray, offset: Int = 0, size: Int = data.size) {
        try { ReplayAvcSample.requiredCapacity(data, offset, size); fail("Unsafe AVC packet accepted") }
        catch (_: IllegalArgumentException) { }
    }

    @Test fun validFourByteAnnexBHardwarePacketIsPreserved() {
        val packet = bytes(0,0,0,1,0x65,0x88,0x80,0,0,0,1,0x06,0x80)
        assertArrayEquals(packet, canonical(packet))
    }

    @Test fun everyThreeBytePrefixIsExpandedForTheNativeWriter() {
        val packet = bytes(0,0,1,0x67,0x42,0x80,0,0,0,1,0x68,0x80,0,0,1,0x65,0x80)
        val expected = bytes(0,0,0,1,0x67,0x42,0x80,0,0,0,1,0x68,0x80,0,0,0,1,0x65,0x80)
        assertEquals(packet.size + 2, ReplayAvcSample.requiredCapacity(packet, 0, packet.size))
        assertArrayEquals(expected, canonical(packet))
    }

    @Test fun lengthPrefixedPacketIsConvertedWithoutChangingNalPayloads() {
        val packet = bytes(0,0,0,3,0x65,0x88,0x80,0,0,0,2,0x06,0x80)
        val expected = bytes(0,0,0,1,0x65,0x88,0x80,0,0,0,1,0x06,0x80)
        assertArrayEquals(expected, canonical(packet))
    }

    @Test fun singleByteNalLengthDoesNotHideLaterLengthPrefixedNals() {
        val packet = bytes(0,0,0,1,0x0a,0,0,0,2,0x06,0x80)
        val expected = bytes(0,0,0,1,0x0a,0,0,0,1,0x06,0x80)
        assertArrayEquals(expected, canonical(packet))
    }

    @Test fun unescapedStartCodeInsideLengthPrefixedNalIsRejected() {
        bad(bytes(0,0,0,6,0x65,0,0,1,0x41,0x80))
        bad(bytes(0,0,0,7,0x65,0,0,0,1,0x41,0x80))
    }

    @Test fun slicedBorrowedBlobIgnoresBytesOutsideSelectedPacket() {
        val packet = bytes(255,255,0,0,0,1,0x41,0x80,255,255)
        assertArrayEquals(bytes(0,0,0,1,0x41,0x80), canonical(packet, 2, 6))
        assertEquals(255.toByte(), packet[0])
        assertEquals(255.toByte(), packet.last())
    }

    @Test fun emulationPreventionAndLeadingZerosAreSupported() {
        val packet = bytes(0,0,0,0,1,0x65,0,0,3,1,0x80)
        assertArrayEquals(bytes(0,0,0,1,0x65,0,0,3,1,0x80), canonical(packet))
    }

    @Test fun emptyNalAndTrailingStartCodeAreRejected() {
        bad(bytes(0,0,0,1))
        bad(bytes(0,0,0,1,0,0,0,1,0x65,0x80))
        bad(bytes(0,0,0,1,0x65,0x80,0,0,1))
        bad(bytes(0,0,0,0))
    }

    @Test fun truncatedAndUnsignedHugeLengthFieldsAreRejected() {
        bad(bytes(0,0,0))
        bad(bytes(0,0,0,8,0x65,0x80))
        bad(bytes(255,255,255,255,0x65,0x80))
        bad(bytes(128,0,0,1,0x65,0x80))
        bad(bytes(0,0,0,2,0x65,0x80,0))
    }

    @Test fun invalidHeadersAndRawUnframedPayloadAreRejected() {
        bad(bytes(0,0,0,1,0x80,0x80))
        bad(bytes(0,0,0,1,0,0x80))
        bad(bytes(0,0,0,1,0x7f,0x80))
        bad(bytes(0x65,0x88,0x80))
        bad(bytes(0,0,0,2,0x80,0x80))
    }

    @Test fun invalidSliceBoundsCannotOverflowOrReachArrayAccess() {
        val packet = bytes(0,0,0,1,0x65,0x80)
        bad(packet, -1, 6); bad(packet, 0, 0); bad(packet, 0, -1)
        bad(packet, 1, 6); bad(packet, Int.MAX_VALUE, 6); bad(packet, 2, Int.MAX_VALUE)
    }

    @Test fun oneDirectScratchCanBeReusedWithExactOutputRanges() {
        val scratch = ByteBuffer.allocateDirect(32)
        val first = bytes(0,0,1,0x65,0x80)
        val second = bytes(0,0,0,1,0x0a)
        ReplayAvcSample.toAnnexB(first, 0, first.size, scratch)
        val out = ReplayAvcSample.toAnnexB(second, 0, second.size, scratch)
        assertEquals(0, out.position()); assertEquals(5, out.limit())
        assertArrayEquals(second, ByteArray(out.remaining()).also { out.get(it) })
    }

    @Test fun failedValidationOrSmallScratchDoesNotWritePartialNativeInput() {
        val scratch = ByteBuffer.allocateDirect(5)
        scratch.put(42.toByte()); val originalPosition = scratch.position()
        val invalid = bytes(0,0,0,1,0x65,0x80,0,0,1)
        try { ReplayAvcSample.toAnnexB(invalid, 0, invalid.size, scratch); fail("Unsafe input accepted") }
        catch (_: IllegalArgumentException) { }
        assertEquals(originalPosition, scratch.position()); assertEquals(42.toByte(), scratch.get(0))
        val good = bytes(0,0,1,0x65,0x80)
        try { ReplayAvcSample.toAnnexB(good, 0, good.size, scratch); fail("Small scratch accepted") }
        catch (_: IllegalArgumentException) { }
        assertEquals(originalPosition, scratch.position())
    }
}
