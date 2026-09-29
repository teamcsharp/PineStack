"""[pinestream] pinelive.js + pinelive.css: the header's PineStream switch
(beside PineCam to live) with its PineTab / Pine app picker, and a PineStream
panel in the body (source, rate, width, quality, status, a live preview).

    python edit_pinestream_panel.py --check|--apply <root>

<root> is a directory holding pinelive.js and pinelive.css: run it on every
copy, and they stay identical -
    <spark-agent>/desktop/renderer                       (canonical)
    <spark-agent>/app/src/main/assets/pine-views         (the repo's mirror)
    <PineBoxKiosk>/app/src/main/assets/pine-views        (the kiosk)
--apply runs `node --check` on pinelive.js.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Edit, Insert, main  # noqa: E402

J = "pinelive.js"
C = "pinelive.css"
PAY = HERE.parent / "payload"
JS_FUNCS = (PAY / "panel_funcs.js").read_text(encoding="utf-8").replace("\r\n", "\n")
JS_PANEL = (PAY / "panel_stream.js").read_text(encoding="utf-8").replace("\r\n", "\n")
CSS = (PAY / "panel.css").read_text(encoding="utf-8").replace("\r\n", "\n")

EDITS = [
    Edit(J, "'picture', 'stream', 'recording'",
         "  var PANEL_ORDER = ['scope', 'event', 'input', 'picture', 'recording', 'system3', 'troubleshoot'];\n",
         "  var PANEL_ORDER = ['scope', 'event', 'input', 'picture', 'stream', 'recording', 'system3', 'troubleshoot'];   /* [pinestream] */\n"),
    Edit(J, "picture: false, stream: false,",
         "  var DEFAULT_OPEN = {scope: true, event: true, input: false, picture: false,\n",
         "  var DEFAULT_OPEN = {scope: true, event: true, input: false, picture: false, stream: false,\n"),
    Insert(J, "function flipStream(next, node)",
           "  function headSwitch(parent, cls, labelText, onFlip) {\n",
           JS_FUNCS, where="before"),
    Insert(J, "stream: headSwitch(hswRow, 'pl-hsw-stream'",
           "      cam: headSwitch(hswRow, 'pl-hsw-cam', 'PineCam to live', function (next, node) { flipTailscale(next, node); }),\n",
           "      /* [pinestream] beside PineCam to live: the switch, then which screen */\n"
           "      stream: headSwitch(hswRow, 'pl-hsw-stream', 'PineStream', function (next, node) { flipStream(next, node); }),\n"
           "      streamSrc: streamSourcePicker(hswRow),\n"),
    Edit(J, "[h.cam, h.stream, h.live, h.album]",
         "    [h.cam, h.live, h.album].forEach(function (x) {\n",
         "    try { paintStreamSwitch(h); }                                   /* [pinestream] */\n"
         "    catch (err) { if (root.console) root.console.error('[pinelive] PineStream switch paint failed:', err); }\n"
         "    [h.cam, h.stream, h.live, h.album].forEach(function (x) {\n"),
    Insert(J, "stream: {title: 'PineStream'",
           "    picture: {title: 'Picture', icon: 'c:image', build: buildPicture, paint: paintPicture, summary: summaryPicture},\n",
           "    stream: {title: 'PineStream', icon: 'c:screen', build: buildStream, paint: paintStream, summary: summaryStream},   /* [pinestream] */\n"),
    Insert(J, "function buildStream(p)",
           "  /* ------------------------------------------------------------ recording */\n",
           JS_PANEL, where="before"),
    Edit(J, "try { syncStreamPreview(); }",
         "  function syncPreview() {\n    var img = ui.previewImg;\n",
         "  function syncPreview() {\n"
         "    try { syncStreamPreview(); } catch (err) { /* [pinestream] never breaks the art preview */ }\n"
         "    var img = ui.previewImg;\n"),
    Insert(C, "[pinestream] the header's PineStream",
           "/* [plcount] the failover countdown over the Script view's player */\n",
           CSS, where="before"),
]


def verify(root: Path):
    got = subprocess.run(["node", "--check", str(root / J)], capture_output=True, text=True)
    if got.returncode != 0:
        return False, "node --check pinelive.js: " + got.stderr[-600:]
    return True, "node --check pinelive.js ok"


if __name__ == "__main__":
    sys.exit(main(EDITS, after_apply=verify))
