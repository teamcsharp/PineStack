package com.pinebox.kiosk.video

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * [vcrfx] The native CRT plays pine-vcr.js's table number for number. The
 * expected values are PineVcr.sample() from desktop/renderer/pine-vcr.js
 * (node, 2026-09-29), so a drift on either side fails here.
 */
class VcrFxTest {
    private fun near(want: Double, got: Float, what: String) =
        assertEquals(what, want, got.toDouble(), 1e-3)

    private fun check(into: Boolean, t: Float, sx: Double, sy: Double, a: Double) {
        val f = VcrFx.sample(into, t)
        val tag = (if (into) "in" else "out") + "@" + t
        near(sx, f.sx, "$tag sx")
        near(sy, f.sy, "$tag sy")
        near(a, f.alpha, "$tag alpha")
    }

    @Test
    fun onMatchesThePage() {
        check(true, 0f, 0.004, 0.004, 1.0)          // the dot
        check(true, 0.1f, 0.82714, 0.00565, 1.0)
        check(true, 0.2f, 0.97332, 0.00595, 1.0)
        check(true, 0.34f, 1.0, 0.006, 1.0)         // the line
        check(true, 0.5f, 1.0, 0.05920, 1.0)
        check(true, 0.7f, 1.0, 0.82835, 1.0)
        check(true, 0.9f, 1.0, 0.99422, 1.0)
        check(true, 1f, 1.0, 1.0, 1.0)              // the picture
    }

    @Test
    fun offMatchesThePage() {
        check(false, 0f, 1.0, 1.0, 1.0)
        check(false, 0.1f, 1.0, 0.98238, 1.0)
        check(false, 0.2f, 1.0, 0.91082, 1.0)
        check(false, 0.34f, 1.0, 0.55830, 1.0)
        check(false, 0.5f, 1.0, 0.01343, 1.0)       // the line
        check(false, 0.7f, 0.98777, 0.00598, 0.98773)
        check(false, 0.9f, 0.73116, 0.00546, 0.73008)
        check(false, 1f, 0.004, 0.004, 0.0)         // the dot, gone
    }

    @Test
    fun timingIsTheStylesheets() {
        assertEquals(420L, VcrFx.IN_MS)
        assertEquals(460L, VcrFx.OUT_MS)
    }

    @Test
    fun outOfRangeIsClamped() {
        check(true, -1f, 0.004, 0.004, 1.0)
        check(false, 2f, 0.004, 0.004, 0.0)
    }
}
