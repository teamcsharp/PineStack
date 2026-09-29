"""[vcrfx] desktop/renderer/ad-viewer.js: the H3 ad viewer's video comes on
with the CRT effect at its first frame and collapses when the viewer closes
(the veil and the media are let go once the collapse is over).
TARGET: desktop/renderer/ad-viewer.js
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("reveal", "vcrfx: an H3 video comes on like the SFX TV",
         """clearTimeout(timer); media.style.visibility = 'visible'; background(false); status.textContent = '';""",
         """clearTimeout(timer); media.style.visibility = 'visible'; background(false); status.textContent = '';
        /* [vcrfx: an H3 video comes on like the SFX TV] once per picture */
        if (isVideo && root.PineVcr && !media.__vcrOn) { media.__vcrOn = true; root.PineVcr.in(media); }"""),
    Edit("close", "vcrfx: the video goes off the way it came on",
         """clearTimeout(exportTimer); disposeMedia(); veil.remove();""",
         """clearTimeout(exportTimer);
      /* [vcrfx: the video goes off the way it came on] */
      var vcrMedia = stage.querySelector('video.pav-media');
      if (root.PineVcr && vcrMedia && vcrMedia.style.visibility === 'visible' && vcrMedia.isConnected) {
        var vcrDispose = disposeMedia;
        disposeMedia = function () {};
        try { vcrMedia.pause(); } catch (e) { /* it stops with the veil */ }
        root.PineVcr.out(vcrMedia).then(function () { vcrDispose(); veil.remove(); });
      } else { disposeMedia(); veil.remove(); }"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
