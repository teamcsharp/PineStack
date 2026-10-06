package com.pinebox.kiosk.replay

/** A reused desktop owner cannot stop a later capture with an old request. */
internal class JpegStreamFence(val owner: String, val streamId: String) {
    init { require(valid(owner) && valid(streamId)) }
    fun exact(who: String, stream: String) = owner == who && streamId == stream
    fun stopExact(who: String, stream: String, stop: () -> Boolean): Boolean? =
        if (exact(who, stream)) stop() else null
    companion object {
        fun allowedPeer(uid: Int, appUid: Int) = uid == 0 || uid == 2000 || uid == appUid
        fun valid(value: String) = Regex("[A-Za-z0-9_-]{8,100}").matches(value)
    }
}
