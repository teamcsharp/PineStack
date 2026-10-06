package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class ReplayBlobSpaceTest {
    /** Production free-space decision, with packets carrying distinguishable
     * bytes; check retained payloads as well as byte accounting after each write. */
    private class PacketRing(val capacity: Int) {
        data class Packet(val at: Int, val bytes: ByteArray)
        val blob = ByteArray(capacity)
        val held = java.util.ArrayDeque<Packet>()
        var head = 0
        var wrote = 0
        fun add(bytes: ByteArray) {
            while (!ReplayBlobSpace.fits(capacity, head, held.peekFirst()?.at ?: 0, held.size, bytes.size)) {
                wrote -= held.removeFirst().bytes.size
                if (held.isEmpty()) { head = 0; wrote = 0 }
            }
            if (head + bytes.size > capacity) head = 0
            bytes.copyInto(blob, head)
            held.addLast(Packet(head, bytes))
            head += bytes.size
            wrote += bytes.size
        }
        fun assertIntact() {
            assertTrue("held byte accounting exceeded physical capacity", wrote <= capacity)
            assertEquals(wrote, held.sumOf { it.bytes.size })
            for (packet in held) assertArrayEquals("held encoded packet was overwritten",
                packet.bytes, blob.copyOfRange(packet.at, packet.at + packet.bytes.size))
        }
    }
    private fun sample(size: Int, tag: Int): ByteArray = ByteArray(size) { index ->
        ((tag * 29 + index * 17) and 255).toByte()
    }

    @Test fun wrappedFullRingDropsOldestBeforeReusingItsBytes() {
        val ring = PacketRing(100)
        ring.add(sample(20, 1)); ring.add(sample(80, 2)); ring.add(sample(20, 3))
        assertEquals(20, ring.head); assertEquals(20, ring.held.first.at)
        assertEquals(100, ring.wrote); ring.assertIntact()
        ring.add(sample(10, 4))
        ring.assertIntact()
        assertEquals(30, ring.wrote)
        assertEquals(listOf(20, 10), ring.held.map { it.bytes.size })
        assertArrayEquals(sample(20, 3), ring.held.first.bytes)
    }

    @Test fun equalCursorsAreFreeOnlyForAnEmptyRing() {
        assertTrue(ReplayBlobSpace.fits(100, 0, 0, 0, 100))
        assertFalse(ReplayBlobSpace.fits(100, 0, 0, 1, 1))
        assertFalse(ReplayBlobSpace.fits(100, 20, 20, 2, 10))
        assertFalse(ReplayBlobSpace.fits(100, 100, 0, 1, 1))
    }

    @Test fun splitFreeSpaceCannotFitOnePacketAcrossTheBoundary() {
        assertFalse(ReplayBlobSpace.fits(100, 97, 2, 3, 5))
        assertTrue(ReplayBlobSpace.fits(100, 97, 6, 3, 5))
        assertTrue(ReplayBlobSpace.fits(100, 20, 40, 3, 20))
        assertFalse(ReplayBlobSpace.fits(100, 20, 40, 3, 21))
    }

    @Test fun variedRepeatedWrapsPreserveEveryRetainedPacket() {
        val ring = PacketRing(100)
        val random = java.util.Random(1225L)
        repeat(3000) { index ->
            ring.add(sample(1 + random.nextInt(100), index))
            ring.assertIntact()
        }
    }
}
