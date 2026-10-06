package com.pinebox.kiosk.replay

/** One immutable latest frame; a slow socket never queues old pictures. */
internal class JpegLatestFrame {
    data class Frame(val sequence: Long, val jpeg: ByteArray, val header: ByteArray)
    private val gate = Object()
    private var latest: Frame? = null
    private var sequence = 0L
    private var closed = false
    fun publish(jpeg: ByteArray): Boolean = synchronized(gate) {
        require(jpeg.size in 1..JpegFrameBuffer.MAX_FRAME_BYTES)
        if (closed) return false
        latest = Frame(++sequence, jpeg, JpegFrameBuffer.header(jpeg.size))
        gate.notifyAll()
        true
    }
    fun next(after: Long): Frame? = synchronized(gate) {
        while (!closed && (latest?.sequence ?: 0L) <= after) gate.wait()
        if (closed) null else latest
    }
    fun close() = synchronized(gate) { closed = true; latest = null; gate.notifyAll() }
}
