"""[vcrfx] desktop/renderer/script-page.js: the Message view bubble's clip
[msgthumb] comes on over its thumbnail with the CRT effect once its first frame
is in, and collapses back onto the thumbnail when it is released. The thumbnail
is hidden only once the picture is fully on.
Two one-block anchors, both inside [msgthumb] code, so a parallel edit to the
roll player (the same file) cannot land inside them.
TARGET: desktop/renderer/script-page.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("reveal", "vcrfx: the clip comes on over its thumbnail",
         """      v.style.visibility = 'visible';
      if (m.img) m.img.style.visibility = 'hidden';
    }, function () {""",
         """      v.style.visibility = 'visible';
      /* [vcrfx: the clip comes on over its thumbnail] */
      var V = root.PineVcr;
      if (V && typeof V.in === 'function') {
        V.in(v).then(function (ok) {
          if (ok && m.video === v && m.img && v.style.visibility === 'visible') m.img.style.visibility = 'hidden';
        });
      } else if (m.img) m.img.style.visibility = 'hidden';
    }, function () {"""),
    Edit("release", "vcrfx: it collapses back onto the thumbnail",
         """    try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) { /* already gone */ }
    if (v.parentNode) v.parentNode.removeChild(v);
    if (m.img) m.img.style.visibility = '';""",
         """    /* [vcrfx: it collapses back onto the thumbnail] - paused at once, its
       source let go when the collapse is over (a 460 ms overlap with the
       next clip's element, never two playing). Off-screen: at once. */
    var V = root.PineVcr;
    if (V && typeof V.out === 'function' && v.isConnected && v.style.visibility === 'visible') {
      try { v.pause(); } catch (e) { /* already gone */ }
      if (m.img) m.img.style.visibility = '';
      V.out(v).then(function () {
        try { v.removeAttribute('src'); v.load(); } catch (e) { /* already gone */ }
        if (v.parentNode) v.parentNode.removeChild(v);
      });
      return;
    }
    try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) { /* already gone */ }
    if (v.parentNode) v.parentNode.removeChild(v);
    if (m.img) m.img.style.visibility = '';"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
