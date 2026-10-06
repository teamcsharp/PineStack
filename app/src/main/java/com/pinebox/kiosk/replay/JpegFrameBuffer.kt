package com.pinebox.kiosk.replay

import java.io.ByteArrayOutputStream
import java.io.IOException

/** JPEG work storage is reused, with an enforced ceiling BEFORE growth. */
internal class JpegFrameBuffer(private val ceiling: Int = MAX_FRAME_BYTES) : ByteArrayOutputStream(minOf(128 * 1024, ceiling)) {
    init { require(ceiling > 0 && ceiling <= MAX_FRAME_BYTES) }
    override fun write(value: Int) {
        if (count >= ceiling) throw IOException("Mirror JPEG exceeds frame limit")
        super.write(value)
    }
    override fun write(data: ByteArray, offset: Int, length: Int) {
        require(offset >= 0 && length >= 0 && offset <= data.size - length)
        if (length > ceiling - count) throw IOException("Mirror JPEG exceeds frame limit")
        super.write(data, offset, length)
    }
    companion object {
        const val MAX_FRAME_BYTES = 2 * 1024 * 1024
        fun header(length: Int): ByteArray {
            require(length in 1..MAX_FRAME_BYTES)
            return byteArrayOf((length ushr 24).toByte(), (length ushr 16).toByte(), (length ushr 8).toByte(), length.toByte())
        }
    }
}
