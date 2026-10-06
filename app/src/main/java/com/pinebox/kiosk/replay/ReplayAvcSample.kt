package com.pinebox.kiosk.replay

import java.nio.ByteBuffer

/** Check framing before handing a video packet to the native MP4 writer.
 * This does not decode H.264. It rejects impossible bounds, empty NAL units,
 * invalid NAL headers and incomplete length fields. Every accepted packet is
 * emitted with FOUR-byte start codes; Android's writer assumes that width.
 * Walks the borrowed slice without keeping a NAL list or cloning the clip. */
internal object ReplayAvcSample {
    fun requiredCapacity(data: ByteArray, offset: Int, size: Int): Int =
        walk(data, offset, size) { _, _ -> }

    fun toAnnexB(data: ByteArray, offset: Int, size: Int, scratch: ByteBuffer): ByteBuffer {
        val needed = requiredCapacity(data, offset, size)
        require(scratch.capacity() >= needed) { "Replay AVC scratch is too small" }
        scratch.clear()
        walk(data, offset, size) { at, length ->
            scratch.put(0.toByte()).put(0.toByte()).put(0.toByte()).put(1.toByte())
            scratch.put(data, at, length)
        }
        scratch.flip()
        return scratch
    }

    private inline fun walk(data: ByteArray, offset: Int, size: Int, nal: (Int, Int) -> Unit): Int {
        require(offset >= 0 && size > 0 && offset <= data.size - size) { "Invalid replay AVC slice" }
        val end = offset + size
        var leading = offset
        while (leading < end && data[leading] == 0.toByte()) leading++
        val annexB = leading < end && data[leading] == 1.toByte() && leading - offset >= 2 &&
            !isLengthPrefixed(data, offset, end)
        var total = 0L
        if (annexB) {
            var at = leading + 1
            while (true) {
                var next = at
                var prefix = 0
                while (next < end) {
                    prefix = prefixAt(data, next, end)
                    if (prefix != 0) break
                    next++
                }
                val length = next - at
                checkNal(data, at, length)
                total += 4L + length
                require(total <= Int.MAX_VALUE) { "Replay AVC packet is too large" }
                nal(at, length)
                if (next == end) break
                at = next + prefix
            }
        } else {
            var cursor = offset
            while (cursor < end) {
                require(end - cursor >= 4) { "Truncated replay AVC length field" }
                val length = ((data[cursor].toLong() and 255) shl 24) or
                    ((data[cursor + 1].toLong() and 255) shl 16) or
                    ((data[cursor + 2].toLong() and 255) shl 8) or
                    (data[cursor + 3].toLong() and 255)
                cursor += 4
                require(length > 0 && length <= end - cursor) { "Invalid replay AVC NAL length" }
                val bytes = length.toInt()
                checkNal(data, cursor, bytes)
                total += 4L + bytes
                require(total <= Int.MAX_VALUE) { "Replay AVC packet is too large" }
                nal(cursor, bytes)
                cursor += bytes
            }
        }
        return total.toInt()
    }

    private fun prefixAt(data: ByteArray, at: Int, end: Int): Int {
        if (end - at < 3 || data[at] != 0.toByte() || data[at + 1] != 0.toByte()) return 0
        if (data[at + 2] == 1.toByte()) return 3
        return if (end - at >= 4 && data[at + 2] == 0.toByte() && data[at + 3] == 1.toByte()) 4 else 0
    }

    // A length of one is indistinguishable from a four-byte start code.
    // Prefer a COMPLETE length-prefixed parse; otherwise use Annex B.
    private fun isLengthPrefixed(data: ByteArray, offset: Int, end: Int): Boolean {
        var cursor = offset
        while (cursor < end) {
            if (end - cursor < 4) return false
            val length = ((data[cursor].toLong() and 255) shl 24) or
                ((data[cursor + 1].toLong() and 255) shl 16) or
                ((data[cursor + 2].toLong() and 255) shl 8) or
                (data[cursor + 3].toLong() and 255)
            cursor += 4
            if (length <= 0 || length > end - cursor) return false
            val header = data[cursor].toInt() and 255
            if ((header and 128) != 0 || (header and 31) !in 1..23) return false
            cursor += length.toInt()
        }
        return true
    }

    private fun checkNal(data: ByteArray, at: Int, length: Int) {
        require(length > 0) { "Empty replay AVC NAL unit" }
        val header = data[at].toInt() and 255
        require((header and 128) == 0 && (header and 31) in 1..23) { "Invalid replay AVC NAL header" }
        var cursor = at + 1
        val end = at + length
        while (cursor < end) {
            require(prefixAt(data, cursor, end) == 0) { "Unescaped start code inside replay AVC NAL" }
            cursor++
        }
    }
}
