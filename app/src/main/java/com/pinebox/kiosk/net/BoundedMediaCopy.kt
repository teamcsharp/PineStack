package com.pinebox.kiosk.net

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/** Media size never determines heap allocation, including chunked responses. */
object BoundedMediaCopy {
    fun copy(input: InputStream, output: OutputStream, limit: Long, expected: Long = -1): Long {
        require(limit > 0)
        if (expected > limit) throw IOException("media exceeds cache limit")
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            if (total + count > limit) throw IOException("media exceeds cache limit")
            output.write(buffer, 0, count)
            total += count
        }
        if (expected >= 0 && total != expected) throw IOException("incomplete media download")
        return total
    }
}
