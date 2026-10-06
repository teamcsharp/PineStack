package com.pinebox.kiosk.replay

import java.nio.ByteBuffer

/** A frozen video's location; borrowing retains no second clip-sized array.
 * ScreenReplay keeps all video mutation behind its cache writer barrier. */
internal data class ReplayMuxSample(
    val timeUs: Long, val data: ByteArray, val offset: Int, val size: Int, val flags: Int
) {
    init { require(offset >= 0 && size > 0 && offset <= data.size - size) }
    companion object {
        fun snapshot(timeUs: Long, data: ByteArray, offset: Int, size: Int, flags: Int, frozen: Boolean): ReplayMuxSample =
            if (frozen) ReplayMuxSample(timeUs, data, offset, size, flags)
            else ReplayMuxSample(timeUs, data.copyOfRange(offset, offset + size), 0, size, flags)
    }
}

/** JNI receives a direct buffer containing ONLY this sample, with offset zero.
 * One largest-packet allocation replaces clip-sized clone/pin/copy pressure. */
internal class ReplayMuxBuffer(val capacity: Int) {
    private val buffer = ByteBuffer.allocateDirect(capacity.also { require(it > 0) })
    fun video(data: ByteArray, offset: Int, size: Int): ByteBuffer =
        ReplayAvcSample.toAnnexB(data, offset, size, buffer)

    fun sample(data: ByteArray, offset: Int, size: Int): ByteBuffer {
        require(offset >= 0 && size > 0 && size <= capacity && offset <= data.size - size)
        buffer.clear()
        buffer.put(data, offset, size)
        buffer.flip()
        return buffer
    }
}
