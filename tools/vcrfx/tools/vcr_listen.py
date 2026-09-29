"""[vcrfx] desktop/renderer/listen.js: a gallery clip on the Listen backdrop
comes on with the CRT effect when its first frame is in.
TARGET: desktop/renderer/listen.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("reveal", "vcrfx: the backdrop clip comes on like the SFX TV",
         """        if (endlessBackdrop) return;
        vid.hidden = false;
        showPlexus(false);""",
         """        if (endlessBackdrop) return;
        vid.hidden = false;
        if (root.PineVcr) root.PineVcr.in(vid);   /* [vcrfx: the backdrop clip comes on like the SFX TV] */
        showPlexus(false);"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
