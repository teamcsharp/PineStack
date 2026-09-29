"""[vcrfx] PineCamWall.kt: the Pine Cam's native surface pops in with the CRT
when the page opens the camera (`on`) and collapses when it closes (`off`) or
is covered (`hide`/`show`); `menu` stays instant and can never strand it.
CRLF file: matched as LF, written back CRLF.
TARGET: app/src/main/java/com/pinebox/kiosk/video/PineCamWall.kt
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("play-sig", "fun play(streamUrl: String, vcr: Boolean = true) {",
         """    fun play(streamUrl: String) {
""",
         """    fun play(streamUrl: String, vcr: Boolean = true) {
"""),
    Edit("play-show", "if (vcr) vcrShow() else refreshVisibility()   // [vcrfx] the cam pops in",
         """            build()
            hidden = false
            refreshVisibility()
            if (same) return@onMain
""",
         """            build()
            hidden = false
            if (vcr) vcrShow() else refreshVisibility()   // [vcrfx] the cam pops in
            if (same) return@onMain
"""),
    Edit("stop-sig", "fun stop(vcr: Boolean = true) {",
         """    fun stop() {
        if (!running.compareAndSet(true, false)) return
""",
         """    fun stop(vcr: Boolean = true) {
        if (!running.compareAndSet(true, false)) return
"""),
    Edit("stop-gone", "if (vcr) vcrGone() else { VcrFx.cancel(this); visibility = View.GONE }",
         """            menuHidden = false
            visibility = View.GONE
        }
    }
""",
         """            menuHidden = false
            if (vcr) vcrGone() else { VcrFx.cancel(this); visibility = View.GONE }   // [vcrfx]
        }
    }
"""),
    Edit("hide-show", "fun hide(vcr: Boolean = true)",
         """    fun hide() { hidden = true; onMain { refreshVisibility() } }

    fun show() {
        hidden = false
        onMain {
            refreshVisibility()
""",
         """    fun hide(vcr: Boolean = true) { hidden = true; onMain { if (vcr) vcrGone() else refreshVisibility() } }   // [vcrfx]

    fun show(vcr: Boolean = true) {
        hidden = false
        onMain {
            if (vcr) vcrShow() else refreshVisibility()   // [vcrfx]
"""),
    Edit("refresh", "private fun vcrShow()",
         """    private fun refreshVisibility() {
        visibility = if (running.get() && !hidden && !menuHidden) View.VISIBLE else View.GONE
    }
""",
         """    private fun refreshVisibility() {
        visibility = if (running.get() && !hidden && !menuHidden) View.VISIBLE else View.GONE
        if (visibility == View.VISIBLE) VcrFx.settle(this) else VcrFx.cancel(this)   // [vcrfx] never left collapsed
    }

    /* [vcrfx] THE CRT, ON THE CAM'S OWN FRAME - the table the page's PineVcr
     * plays on the JPEG box (VcrFx). "if I enable the Pine recording and I
     * activate the Pine Cam, then I want the cam to pop in with the V CR
     * effect." Main thread only. */
    private fun vcrWanted(): Boolean = running.get() && !hidden && !menuHidden

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
         """        .put("hidden", hidden)
        .put("menu_hidden", menuHidden)
        .put("lag_ms", lagMs)
""",
         """        .put("hidden", hidden)
        .put("vcr", VcrFx.phase(this))                      // [vcrfx] "in", "out" or ""
        .put("menu_hidden", menuHidden)
        .put("lag_ms", lagMs)
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
