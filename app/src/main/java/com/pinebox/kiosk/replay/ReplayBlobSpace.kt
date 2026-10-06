package com.pinebox.kiosk.replay

/** Free contiguous space in a packet ring. Equal cursors with held packets
 * mean full, including after a packet exactly fills the wrapped free prefix. */
internal object ReplayBlobSpace {
    fun fits(capacity: Int, head: Int, oldest: Int, count: Int, size: Int): Boolean {
        if (count == 0) return size <= capacity
        if (head == oldest) return false
        return if (head > oldest) capacity - head >= size || oldest >= size
        else oldest - head >= size
    }
}
