"""[vcrfx] desktop/renderer/pinelive.js: the Picture panel's preview - "the
album art shows your video feed" - comes on when a set arms and goes off when
it ends, through PineVcr; the MJPEG keeps its last frame through the collapse.
TARGET: desktop/renderer/pinelive.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("paint", "vcrHidden(p.parts.prev, !st.art_url);",
         """    setHidden(p.parts.prev, !st.art_url);
""",
         """    vcrHidden(p.parts.prev, !st.art_url);   /* [vcrfx] the picture comes on like the SFX TV */
"""),
    Edit("sync", "vcrfx: the last frame stays through the collapse",
         """    else if (img.__src) { img.__src = ''; img.removeAttribute('src'); }
""",
         """    else if (img.__src) {
      img.__src = '';
      /* [vcrfx: the last frame stays through the collapse] */
      setTimeout(function () { if (!img.__src) img.removeAttribute('src'); },
        root.PineVcr ? root.PineVcr.OUT_MS + 80 : 0);
    }
"""),
    Edit("helper", "function vcrHidden(",
         """  function setHidden(node, hidden) {
    if (node && node.hidden !== !!hidden) node.hidden = !!hidden;
  }
""",
         """  function setHidden(node, hidden) {
    if (node && node.hidden !== !!hidden) node.hidden = !!hidden;
  }
  /* [vcrfx] setHidden for a picture: PineVcr.set is idempotent per state,
     so the four-a-second paint costs nothing once the picture has settled. */
  function vcrHidden(node, hidden) {
    var V = root.PineVcr;
    if (!node || !V || typeof V.set !== 'function') { setHidden(node, hidden); return; }
    V.set(node, !hidden, {
      show: function (el) { el.hidden = false; },
      hide: function (el) { el.hidden = true; }
    });
  }
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
