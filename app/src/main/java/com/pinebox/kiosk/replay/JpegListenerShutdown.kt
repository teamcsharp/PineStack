package com.pinebox.kiosk.replay

/** Closing an Android local listener may leave accept() blocked on its old
 * descriptor. Wake it while its name is still bound. On wake failure retain
 * the listener so a later cleanup attempt can retry, then verify thread exit. */
internal object JpegListenerShutdown {
    fun run(acceptorAlive: Boolean, wake: () -> Unit, close: () -> Unit) {
        if (acceptorAlive) wake()
        close()
    }
}
