"""[vcrfx] desktop/renderer/sfx-tv.js: the CRT set comes on and goes off through
PineVcr - the same table the stylesheet held, now shared with every picture.
Without PineVcr on the page (an old bundle) the classes run exactly as before.
TARGET: desktop/renderer/sfx-tv.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("helpers", "function vcrTubeOn(",
         """  var OFF_MS = 520;
""",
         """  var OFF_MS = 520;
  /* [vcrfx] THE SET'S ON AND OFF ARE PineVcr's - pine-vcr.js holds the one
   * table (the numbers sfx-tv.css kept as sfxTvOn/sfxTvOff) that every
   * picture in the app, the tablet and the broadcast now shares. The
   * classes stay as the road for a page that has not loaded pine-vcr.js. */
  function vcrTubeOn(tube, flash) {
    var V = root.PineVcr;
    if (V && typeof V.in === 'function') { V.in(tube, {flash: flash || false}); return; }
    tube.classList.add('on');
    if (flash) flash.classList.add('pop');
  }
  function vcrTubeOff(tube) {
    var V = root.PineVcr;
    if (V && typeof V.out === 'function') { V.out(tube); return; }
    tube.classList.remove('on');
    void tube.offsetWidth;            // restart the animation, never resume it
    tube.classList.add('off');
  }
"""),
    Edit("reveal", "vcrTubeOn(glass, parts.flash);",
         """          glass.classList.add('on');   // dot -> line -> picture
          parts.flash.classList.add('pop');
""",
         """          vcrTubeOn(glass, parts.flash);   /* [vcrfx] dot -> line -> picture */
"""),
    Edit("finish", "vcrTubeOff(glass);",
         """      try {
        glass.classList.remove('on');
        void glass.offsetWidth;      // restart the animation, never resume it
        glass.classList.add('off');
      } catch (err) {}
      setTimeout(function () { teardown(screen); }, OFF_MS);
""",
         """      try {
        vcrTubeOff(glass);           /* [vcrfx] picture -> line -> dot */
      } catch (err) {}
      setTimeout(function () { teardown(screen); }, OFF_MS);
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
