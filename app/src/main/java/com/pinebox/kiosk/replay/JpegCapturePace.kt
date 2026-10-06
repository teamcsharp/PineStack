package com.pinebox.kiosk.replay

/** Rate-limit work after an image exists, without restricting which display
 * vsync phases are allowed to produce the first or a sparse later image. */
internal object JpegCapturePace {
    fun allows(nowNs: Long, lastCaptureNs: Long, fps: Int): Boolean {
        require(fps in 1..12)
        return lastCaptureNs == 0L || nowNs - lastCaptureNs >= 1_000_000_000L / fps
    }
}
