"""[vcrfx] PineVideoWall.kt: the endless set's native surface comes on and goes
off with the CRT (VcrFx) on start/stop/veil; `menu` and every other road stay
instant and can never leave it collapsed (refreshVisibility settles it).
TARGET: app/src/main/java/com/pinebox/kiosk/video/PineVideoWall.kt
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("start", "fun start(vcr: Boolean = true) {",
         """    fun start() {
        if (!running.compareAndSet(false, true)) return
        onMain {
            refreshVisibility()
            build()
        }
""",
         """    fun start(vcr: Boolean = true) {
        if (!running.compareAndSet(false, true)) return
        onMain {
            if (vcr) vcrShow() else refreshVisibility()   // [vcrfx] dot -> line -> picture
            build()
        }
"""),
    Edit("stop-sig", "fun stop(vcr: Boolean = true) {",
         """    fun stop() {
        if (!running.compareAndSet(true, false)) return
        pump?.cancel()
""",
         """    fun stop(vcr: Boolean = true) {
        if (!running.compareAndSet(true, false)) return
        pump?.cancel()
"""),
    Edit("stop-gone", "if (vcr) vcrGone() else { VcrFx.cancel(this); visibility = View.GONE }",
         """            atIndex = -1; atCount = 0; atPos = -1L; atDuration = -1L
            visibility = View.GONE
""",
         """            atIndex = -1; atCount = 0; atPos = -1L; atDuration = -1L
            if (vcr) vcrGone() else { VcrFx.cancel(this); visibility = View.GONE }   // [vcrfx]
"""),
    Edit("veil", "fun veil(on: Boolean, vcr: Boolean = true) {",
         """    fun veil(on: Boolean) {
        veiled = on
        onMain { refreshVisibility() }
    }
""",
         """    fun veil(on: Boolean, vcr: Boolean = true) {
        veiled = on
        onMain { if (!vcr) refreshVisibility() else if (on) vcrGone() else vcrShow() }   // [vcrfx]
    }
"""),
    Edit("refresh", "private fun vcrShow()",
         """    private fun refreshVisibility() {
        visibility = if (running.get() && !veiled && !menuHidden) View.VISIBLE else View.GONE
    }
""",
         """    private fun refreshVisibility() {
        visibility = if (running.get() && !veiled && !menuHidden) View.VISIBLE else View.GONE
        if (visibility == View.VISIBLE) VcrFx.settle(this) else VcrFx.cancel(this)   // [vcrfx] never left collapsed
    }

    /* [vcrfx] THE CRT, ON THE WALL'S OWN FRAME - the same table the page's
     * PineVcr plays (VcrFx). An on starts from the dot; an off hides the wall
     * only if nobody wanted it back meanwhile. Main thread only. */
    private fun vcrWanted(): Boolean = running.get() && !veiled && !menuHidden

    private fun vcrShow() {
        if (!vcrWanted()) { refreshVisibility(); return }
        val lit = visibility == View.VISIBLE && !VcrFx.isGoingOff(this)
        visibility = View.VISIBLE
        if (!lit) VcrFx.play(this, true)
    }

    private fun vcrGone() {
        if (visibility != View.VISIBLE) { refreshVisibility(); return }
        if (VcrFx.isGoingOff(this)) return
        VcrFx.play(this, false) { if (!vcrWanted()) visibility = View.GONE }
    }

    /** [vcrfx] the bridge's `vcr` verb: play the on again (a proof on the glass). */
    fun vcrReplay() { onMain { if (visibility == View.VISIBLE) VcrFx.play(this, true) } }
"""),
    Edit("state", ".put(\"vcr\", VcrFx.phase(this))",
         """        .put("veiled", veiled)
        .put("queued", aheadCount())
""",
         """        .put("veiled", veiled)
        .put("vcr", VcrFx.phase(this))                      // [vcrfx] "in", "out" or ""
        .put("queued", aheadCount())
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
