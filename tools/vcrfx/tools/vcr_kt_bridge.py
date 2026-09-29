"""[vcrfx] PineDesktopBridge.kt: videoWall / pineCam on, off, hide, show play the
CRT natively by default; {vcr: false} in the second argument skips it; a `vcr`
verb replays the on (a proof on the glass from a console).
TARGET: app/src/main/java/com/pinebox/kiosk/bridge/PineDesktopBridge.kt
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("wall-verbs", "val vcr = args.optJSONObject(1)?.optBoolean(\"vcr\", true) ?: true   // [vcrfx] the CRT, natively",
         """                    "on" -> { wall.veil(false); wall.start() }
                    "off" -> wall.stop()
                    /* #1434: veiling is not stopping - the playlist keeps
                     * running and only the surface leaves the screen. */
                    "hide" -> wall.veil(true)
                    "show" -> wall.veil(false)
""",
         """                    "on" -> {
                        val vcr = args.optJSONObject(1)?.optBoolean("vcr", true) ?: true   // [vcrfx] the CRT, natively
                        wall.veil(false, vcr); wall.start(vcr)
                    }
                    "off" -> wall.stop(args.optJSONObject(1)?.optBoolean("vcr", true) ?: true)
                    /* #1434: veiling is not stopping - the playlist keeps
                     * running and only the surface leaves the screen. */
                    "hide" -> wall.veil(true, args.optJSONObject(1)?.optBoolean("vcr", true) ?: true)
                    "show" -> wall.veil(false, args.optJSONObject(1)?.optBoolean("vcr", true) ?: true)
                    "vcr" -> wall.vcrReplay()                                   // [vcrfx]
"""),
    Edit("cam-verbs", "cam.play(url, arg?.optBoolean(\"vcr\", true) ?: true)",
         """                        cam.play(url)
                    }
                    "box" -> boxOf(arg)
                    "off" -> cam.stop()
                    "hide" -> cam.hide()
                    "show" -> cam.show()
""",
         """                        cam.play(url, arg?.optBoolean("vcr", true) ?: true)   // [vcrfx] pops in
                    }
                    "box" -> boxOf(arg)
                    "off" -> cam.stop(arg?.optBoolean("vcr", true) ?: true)
                    "hide" -> cam.hide(arg?.optBoolean("vcr", true) ?: true)
                    "show" -> cam.show(arg?.optBoolean("vcr", true) ?: true)
                    "vcr" -> cam.vcrReplay()                                    // [vcrfx]
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
