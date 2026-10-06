package com.pinebox.kiosk.replay

import java.nio.ByteBuffer

/** Copy only visible RGBA pixels. The final image row need not have padding. */
internal object ReplayRgbaRows {
    fun byteCount(width: Int, height: Int): Int {
        require(width > 0 && height > 0 && width.toLong() * height <= 4_194_304L) { "Invalid mirror dimensions" }
        return width * height * 4
    }
    fun copy(source: ByteBuffer, width: Int, height: Int, pixelStride: Int, rowStride: Int, destination: ByteArray) {
        val bytes = byteCount(width, height)
        require(pixelStride >= 4 && rowStride > 0 && destination.size >= bytes) { "Invalid mirror RGBA storage" }
        val rowBytes = (width - 1L) * pixelStride + 4L
        val needed = (height - 1L) * rowStride + rowBytes
        require(rowBytes <= rowStride && needed <= source.remaining()) { "Truncated mirror RGBA plane" }
        val input = source.duplicate()
        val base = input.position()
        var out = 0
        for (row in 0 until height) {
            val start = base + row * rowStride
            if (pixelStride == 4) {
                input.position(start)
                input.get(destination, out, width * 4)
                out += width * 4
            } else {
                for (column in 0 until width) {
                    val pixel = start + column * pixelStride
                    for (channel in 0 until 4) destination[out++] = input.get(pixel + channel)
                }
            }
        }
    }
}
