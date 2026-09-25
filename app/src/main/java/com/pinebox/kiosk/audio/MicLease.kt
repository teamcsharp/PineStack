package com.pinebox.kiosk.audio

/** The bridge and Android's recognizer must never record over each other. */
object MicLease {
    private var owner: Any? = null

    @Synchronized fun acquire(who: Any): Boolean {
        if (owner != null && owner !== who) return false
        owner = who
        return true
    }

    @Synchronized fun release(who: Any) {
        if (owner === who) owner = null
    }
}
