"""[pinestream] the operator's answers, the shared views half (desk + tablet):

  [pinestream-veil]   pinelive.js's "Go LIVE - the public listen link" sheet
                      carries data-pine-private: PineStream shows "Private
                      screen" while a tune-in link is on the glass.
  [camgrey]           "PineCam to live" (header) and "Video to Tailscale
                      listeners" (Picture panel) render greyed while the Pine
                      Cam link is not live - still clickable, with a tooltip
                      naming why (pinelink's own `why`, last seen). The reading
                      is the popup's existing /api/pinelive/state poll.
  [pinestream-choose] PineStream OFF: both source buttons (header and panel)
                      are inert, the last-used one marked faintly. Flipping
                      it ON opens a chooser anchored to the switch (Pine app /
                      PineTab, last-used preselected and focused, a screen
                      that has not checked in says so); a tap streams it; X,
                      Escape, BACK or a tap beside it cancel and leave it OFF.
  pinestream.js       its state poll says which screen it is and whether it is
                      awake (?from=&awake=), which is what the chooser reads.

    python edit_pinestream_bd_views.py --check|--apply <dir>

<dir> holds pinelive.js, pinelive.css and pinestream.js. Run it on every
copy, which stay identical:
    <spark-agent>/desktop/renderer                  (canonical)
    <spark-agent>/app/src/main/assets/pine-views    (the repo's mirror)
    <PineBoxKiosk>/app/src/main/assets/pine-views   (the kiosk)
--apply runs `node --check` on pinelive.js and pinestream.js.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Edit, Insert, main  # noqa: E402

J = "pinelive.js"
PAY = HERE.parent / "payload"
FUNCS = (PAY / "bd_views_funcs.js").read_text(encoding="utf-8").replace("\r\n", "\n")
CSS = (PAY / "bd_views.css").read_text(encoding="utf-8").replace("\r\n", "\n")

EDITS = [
    # [pinestream-veil]
    Insert(J, "s.back.setAttribute('data-pine-private'",
           "    var s = traySheet('Go LIVE - the public listen link');\n",
           "    /* [pinestream-veil] a tune-in link on the glass: PineStream shows \"Private screen\" */\n"
           "    s.back.setAttribute('data-pine-private', 'a tune-in link is on the screen');\n"),
    # the helpers: camgrey + the chooser
    Insert(J, "function openChooser(anchor)", "  function headSwitch(parent, cls, labelText, onFlip) {\n",
           FUNCS, where="before"),
    # ON asks which screen first
    Edit(J, "if (next) { openChooser(node);",
         "  function flipStream(next, node) {\n    if (!model.settings) model.settings = {};\n    model.settings.stream_on = next;\n",
         "  function flipStream(next, node) {\n"
         "    /* [pinestream-choose] ON asks which screen first: nothing streams without a choice */\n"
         "    if (next) { openChooser(node); return Promise.resolve({ok: true, say: ''}); }\n"
         "    closeChooser();\n"
         "    if (!model.settings) model.settings = {};\n"
         "    model.settings.stream_on = next;\n"),
    # the header's source buttons: inert while off
    Edit(J, "if (h.streamSrc) paintStreamPicker(h.streamSrc, src, on);",
         "    if (h.streamSrc) {\n      h.streamSrc.set(src);\n"
         "      h.streamSrc.buttons.forEach(function (b) { b.disabled = !model.state; });\n    }\n",
         "    if (h.streamSrc) paintStreamPicker(h.streamSrc, src, on);   /* [pinestream-choose] inert while off */\n"),
    # [camgrey] the header switch
    Insert(J, "paintCamGrey(h.cam.root, h.cam.root, h.cam.root.title)",
           "    var rehearse = !!(st && st.armed && st.event && st.event.rehearse);\n",
           "    try { paintCamGrey(h.cam.root, h.cam.root, h.cam.root.title); }   /* [camgrey] */\n"
           "    catch (err) { if (root.console) root.console.error('[pinelive] camgrey paint failed:', err); }\n",
           where="before"),
    # [camgrey] the Picture panel's twin
    Insert(J, "paintCamGrey(p.parts.ts.root, p.parts.ts.sw,",
           "    p.parts.ts.sw.disabled = !model.state;\n",
           "    paintCamGrey(p.parts.ts.root, p.parts.ts.sw, '');   /* [camgrey] */\n"),
    # the panel's source picker: inert while off
    Insert(J, "inertButtons(p.parts.src.buttons, on);",
           "    p.parts.src.set(src);\n",
           "    inertButtons(p.parts.src.buttons, on);   /* [pinestream-choose] */\n"),
    # BACK peels the chooser first
    Edit(J, "if (ui.chooser) closeChooser();",
         "        if (ui.lightbox && !ui.lightbox.root.hidden) closeLightbox();\n",
         "        if (ui.chooser) closeChooser();   /* [pinestream-choose] the chooser first */\n"
         "        else if (ui.lightbox && !ui.lightbox.root.hidden) closeLightbox();\n"),
    # closing the popup cancels the chooser (PineStream stays off)
    Insert(J, "closeChooser();                 /* [pinestream-choose]",
           "    closeDetect();            /* [pldetect] no timer may outlive the popup */\n",
           "    closeChooser();                 /* [pinestream-choose] cancelled: PineStream stays off */\n"),
    Insert("pinelive.css", "[camgrey] PineCam to live while the camera is offline",
           "/* [plcount] the failover countdown over the Script view's player */\n",
           CSS, where="before"),
    # pinestream.js: the check-in rides the state poll it already makes
    Edit("pinestream.js", "'/api/pinestream/state?from='",
         "    Promise.resolve(b.get('/api/pinestream/state')).then(function (info) {\n",
         "    /* [pinestream-choose] which screen asks, and whether it is awake: the\n"
         "     * station's chooser says so when one is asleep or closed */\n"
         "    var awake = true;\n"
         "    try { awake = !doc.hidden; } catch (err) { awake = true; }\n"
         "    Promise.resolve(b.get('/api/pinestream/state?from=' + state.surface + '&awake=' + (awake ? 1 : 0))).then(function (info) {\n"),
]


def verify(root: Path):
    for rel in (J, "pinestream.js"):
        got = subprocess.run(["node", "--check", str(root / rel)], capture_output=True, text=True)
        if got.returncode != 0:
            return False, "node --check %s: %s" % (rel, got.stderr[-600:])
    return True, "node --check pinelive.js, pinestream.js ok"


if __name__ == "__main__":
    sys.exit(main(EDITS, after_apply=verify))
