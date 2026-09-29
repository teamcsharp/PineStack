#!/usr/bin/env python3
"""closex_shell - the helper file, the desktop shell's script tag, and
pine-dismiss.js made closex-aware (Escape and BACK reach every popup that
carries a corner X, the topmost first).

    python closex_shell.py --check <repo-root>
    python closex_shell.py --apply <repo-root>

pine-dismiss.js is patched in desktop/renderer (canonical) AND in the kiosk
mirror app/src/main/assets/pine-views, so the two stay identical.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from closex_patchlib import Insert, NewFile, Replace, main  # noqa: E402

HELPER = str(HERE.parent / "src" / "pine-closex.js")
DISMISS = ["desktop/renderer/pine-dismiss.js", "app/src/main/assets/pine-views/pine-dismiss.js"]

ONKEY_OLD = """  function onKey(event) {
    if (event.key !== 'Escape' && event.key !== 'Esc') return;
    for (var i = watched.length - 1; i >= 0; i -= 1) {
      if (showing(watched[i])) { fire(watched[i]); event.stopPropagation(); return; }
    }
  }
"""
ONKEY_NEW = """  function onKey(event) {
    if (event.key !== 'Escape' && event.key !== 'Esc') return;
    var w = null;
    for (var i = watched.length - 1; i >= 0; i -= 1) {
      if (showing(watched[i])) { w = watched[i]; break; }
    }
    /* [closex:esc] a popup with a corner X (pine-closex.js) answers Escape
     * too; the higher of the two on screen goes first. An editor inside it
     * (a textarea, contenteditable) keeps its own Escape. */
    var cx = closexTop(event);
    if (cx && (!w || cx.node === w.node || zOf(cx.node) > zOf(w.node))) {
      try { cx.close(); } catch (err) { /* its own road threw */ }
      event.stopPropagation();
      return;
    }
    if (w) { fire(w); event.stopPropagation(); }
  }

  function closexTop(event) {
    var cx = root.pineCloseX;
    if (!cx || typeof cx.top !== 'function') return null;
    if (event && typeof cx.editing === 'function' && cx.editing(event.target)) return null;
    try { return cx.top(); } catch (err) { return null; }
  }
"""

BACK_TEXT = """    /* [closex:back] every popup with a corner X is a BACK candidate too */
    var cxs = [];
    try { cxs = root.pineCloseX && typeof root.pineCloseX.open === 'function' ? root.pineCloseX.open() : []; } catch (err) { cxs = []; }
    for (i = 0; i < cxs.length; i += 1) {
      var seen = false;
      for (var s = 0; s < out.length; s += 1) { if (out[s].node === cxs[i].node) { seen = true; break; } }
      if (!seen) add(cxs[i].node, cxs[i].close);
    }"""

PATCHES = [NewFile("desktop/renderer/pine-closex.js", "EVERY POP-UP HAS AN X IN ITS CORNER", HELPER)]
for f in DISMISS:
    PATCHES += [
        Replace(f, "closex:esc", ONKEY_OLD, ONKEY_NEW),
        Insert(f, "closex:back", "    for (i = 0; i < backs.length; i += 1) {", BACK_TEXT, where="before"),
        Replace(f, "closex:aware", "    onBack: onBack, back: back};",
                "    onBack: onBack, back: back,\n"
                "    /* [closex:aware] Escape for pineCloseX popups is answered here - once\n"
                "       its key listener is wired (the first watch() wires it) */\n"
                "    closexAware: true, keyWired: function () { return wired; }};"),
    ]
PATCHES.append(Insert("desktop/renderer/index.html", "closex:shell",
                      '  <script src="./pine-dismiss.js"></script>',
                      '  <script src="./pine-closex.js"></script>  <!-- [closex:shell] every popup\'s corner X -->'))

if __name__ == "__main__":
    sys.exit(main(PATCHES))
