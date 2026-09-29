"""[vcrfx] desktop/renderer/pine-cam.js: the Pine Cam box comes on and goes off
with the CRT effect (PineVcr.set - last wish wins, so a fast open/close/open
never strands it collapsed). On the tablet the native surface does the same
thing in Kotlin (PineCamWall -> VcrFx) when `on` / `off` reach it.
TARGET: desktop/renderer/pine-cam.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("open", "vcrBox(true);",
         """    shown = true;
    box.hidden = false;
    setBare(BARE_DEFAULT);                 /* just the window, until asked */
""",
         """    shown = true;
    box.hidden = false;
    vcrBox(true);                          /* [vcrfx] dot -> line -> picture */
    setBare(BARE_DEFAULT);                 /* just the window, until asked */
"""),
    Edit("close", "vcrBox(false);",
         """    shown = false;
    if (box) box.hidden = true;
""",
         """    shown = false;
    if (box) vcrBox(false);                /* [vcrfx] picture -> line -> dot, then hidden */
"""),
    Edit("helper", "function vcrBox(on)",
         """  function toggle() { if (shown) { close(); } else { open(); } }
""",
         """  function toggle() { if (shown) { close(); } else { open(); } }

  /* [vcrfx] THE BOX COMES ON LIKE THE SFX TV. PineVcr.set is a state
   * machine - the newest wish wins and an open during a close starts from
   * the dot again - so the box is only ever hidden by an out that nobody
   * overtook. Without pine-vcr.js on the page it is hidden at once. */
  function vcrBox(on) {
    if (!box) return;
    var V = root.PineVcr;
    if (!V || typeof V.set !== 'function') { box.hidden = !on; return; }
    V.set(box, on, {
      show: function (el) { el.hidden = false; },
      hide: function (el) { if (!shown) el.hidden = true; }
    });
  }
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
