#!/usr/bin/env python3
"""[report-paste] Images can be pasted into the report pad. 2026-10-05, #1575.

"In the report window in the pop-up, allow me to paste images in the report
window." The pad (talk-dot.js, PineReport) already sent one image, the
screenshot it may be opened with. An image on the clipboard is now attached
too: up to six, each shown as a thumbnail with its own remove, all sent with
the report. Text still pastes into the box as it always did.

Both copies are patched (the desktop renderer's and the tablet's); the tablet
takes it at its next kiosk build.

Usage:  report_paste_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        report_paste_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HINT_OLD = r'''    hint.textContent = 'Dictate it, fix it on the keyboard, then Send it to the inbox - or Cancel.';
'''
HINT_NEW = r'''    hint.textContent = 'Dictate it, fix it on the keyboard, paste any images, then Send it to the inbox - or Cancel.';   /* [report-paste] */
'''

SEND_OLD = r'''{text: text, debug: !!debug.checked, images: padImage ? [padImage] : []}))'''
SEND_NEW = r'''{text: text, debug: !!debug.checked, images: (padImage ? [padImage] : []).concat(pasted)}))'''

PASTE_OLD = r'''    pad.appendChild(area);
    pad.appendChild(debugRow);
'''
PASTE_NEW = r'''    /* [report-paste] #1575: "In the report window in the pop-up, allow me to
       paste images in the report window." An image on the clipboard is
       attached - up to six - shown as a thumbnail with its own remove, and
       sent with the report beside the screenshot the pad may already carry.
       Text still pastes into the box as it always did. */
    var pasted = [];
    var reading = 0;
    var strip = document.createElement('div');
    strip.id = 'pineReportPasted';
    strip.setAttribute('style', 'display:flex;gap:8px;flex-wrap:wrap');
    function paintPasted() {
      strip.textContent = '';
      pasted.forEach(function (src, i) {
        var cell = document.createElement('div');
        cell.setAttribute('style', 'position:relative;width:96px;height:70px;border:1px solid #2a3a44;'
          + 'border-radius:6px;overflow:hidden;background:#000');
        var im = document.createElement('img');
        im.src = src;
        im.alt = 'pasted image ' + (i + 1);
        im.setAttribute('style', 'width:100%;height:100%;object-fit:cover');
        var gone = document.createElement('button');
        gone.type = 'button';
        gone.textContent = '✕';
        gone.title = 'Remove this image';
        gone.setAttribute('aria-label', 'Remove pasted image ' + (i + 1));
        gone.setAttribute('style', 'position:absolute;top:2px;right:2px;width:22px;height:22px;padding:0;'
          + 'border-radius:11px;border:1px solid #2a3a44;background:#0b1116;color:#dfe7ee;font-size:12px;line-height:1');
        gone.addEventListener('click', function (ev) {
          ev.stopPropagation();
          pasted.splice(i, 1);
          paintPasted();
          note.textContent = pasted.length ? pasted.length + ' image(s) attached' : 'the image was removed';
        });
        cell.appendChild(im);
        cell.appendChild(gone);
        strip.appendChild(cell);
      });
    }
    pad.addEventListener('paste', function (ev) {
      var items = (ev.clipboardData && ev.clipboardData.items) || [];
      var files = [];
      Array.prototype.forEach.call(items, function (item) {
        if (item && item.kind === 'file' && /^image\//.test(String(item.type || ''))) {
          var file = item.getAsFile();
          if (file) files.push(file);
        }
      });
      if (!files.length) return;                 /* text goes into the box as before */
      ev.preventDefault();
      files.forEach(function (file) {
        if (pasted.length + reading >= 6) { note.textContent = 'six images is the most one report carries'; return; }
        reading += 1;
        var reader = new FileReader();
        reader.onload = function () {
          reading -= 1;
          var src = String(reader.result || '');
          if (/^data:image\//.test(src)) pasted.push(src);
          paintPasted();
          note.textContent = pasted.length + ' image(s) attached - paste more, or Send';
        };
        reader.onerror = function () { reading -= 1; note.textContent = 'that image could not be read'; };
        reader.readAsDataURL(file);
      });
    });
    pad.appendChild(area);
    pad.appendChild(strip);
    pad.appendChild(debugRow);
'''

JS = [
    ("the hint says so", HINT_OLD, HINT_NEW, "/* [report-paste] */", 1),
    ("pasted images are sent", SEND_OLD, SEND_NEW, "images: (padImage ? [padImage] : []).concat(pasted)", 1),
    ("the pad takes a pasted image", PASTE_OLD, PASTE_NEW, "pad.addEventListener('paste', function (ev) {", 1),
]
EDITS = {"desktop/renderer/talk-dot.js": JS, "app/src/main/assets/pine-views/talk-dot.js": JS}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name)
            continue
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-46s %-30s %s" % (name[-46:], edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _n)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _n, "probe")
        if todo:
            tmp = path.with_name(path.name + ".paste.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
