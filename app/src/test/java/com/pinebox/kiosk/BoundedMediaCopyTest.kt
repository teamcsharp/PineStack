package com.pinebox.kiosk

import com.pinebox.kiosk.net.BoundedMediaCopy
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import org.junit.Assert.*
import org.junit.Test

class BoundedMediaCopyTest {
    @Test fun largeStreamUsesSmallReads() {
        var remaining = 32L * 1024 * 1024
        var largest = 0
        val input = object : InputStream() {
            override fun read(): Int = error("bulk reads required")
            override fun read(buffer: ByteArray, offset: Int, count: Int): Int {
                largest = maxOf(largest, buffer.size)
                if (remaining == 0L) return -1
                val size = minOf(count.toLong(), remaining).toInt()
                remaining -= size
                return size
            }
        }
        val sink = object : OutputStream() {
            override fun write(value: Int) {}
            override fun write(buffer: ByteArray, offset: Int, count: Int) {}
        }
        assertEquals(32L * 1024 * 1024, BoundedMediaCopy.copy(input, sink, 40L * 1024 * 1024))
        assertTrue(largest <= 64 * 1024)
    }

    @Test fun preservesBytes() {
        val bytes = ByteArray(140000) { (it % 251).toByte() }
        val out = ByteArrayOutputStream()
        assertEquals(bytes.size.toLong(), BoundedMediaCopy.copy(ByteArrayInputStream(bytes), out, 200000, bytes.size.toLong()))
        assertArrayEquals(bytes, out.toByteArray())
    }

    @Test(expected = IOException::class) fun rejectsOversizeChunkedResponse() {
        BoundedMediaCopy.copy(ByteArrayInputStream(ByteArray(100)), ByteArrayOutputStream(), 99)
    }

    @Test(expected = IOException::class) fun rejectsOversizeDeclaredResponse() {
        BoundedMediaCopy.copy(ByteArrayInputStream(byteArrayOf()), ByteArrayOutputStream(), 99, 100)
    }

    @Test(expected = IOException::class) fun rejectsTruncatedResponse() {
        BoundedMediaCopy.copy(ByteArrayInputStream(byteArrayOf(1, 2)), ByteArrayOutputStream(), 100, 3)
    }
}
