package com.pinebox.kiosk.replay

/** Image notifications are not replayed when a listener is installed. Attach
 * before a producer can publish, then drain any image queued without an event.
 * A creation failure propagates to the caller's resource cleanup barrier. */
internal object JpegCaptureStartup {
    fun run(attach: () -> Unit, create: () -> Unit, queueDrain: () -> Unit) {
        attach()
        create()
        queueDrain()
    }
}
