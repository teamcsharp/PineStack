#!/usr/bin/env python3
"""[pip-rec-fit] The album recorder's parts follow its size. 2026-10-06.

"When I resize the album recorder dynamically resize the elements inside appropriately to keep it
 sane." The widget is a size container: its art, track number, buttons, bar, meter and readouts
 are measured in its own width (container query units), so a wide recorder grows them and a
 narrow one keeps them in proportion instead of overlapping. Both copies of pine-pip.css.

Usage:  pip_rec_fit_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_rec_fit_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

CSS_NEW = r'''
/* [pip-rec-fit] the recorder is a size container: every part is measured in its own width */
#pinePipWidgets .pip-rec { container-type: inline-size; grid-template-columns: clamp(64px, 26cqw, 220px) minmax(0, 1fr); grid-template-rows: auto minmax(0, auto) auto auto; min-width: 200px; min-height: 0; overflow: hidden; }
#pinePipWidgets .pip-rec .pip-rec-art { width: clamp(64px, 26cqw, 220px); height: clamp(64px, 26cqw, 220px); }
#pinePipWidgets .pip-rec .pip-rec-total { font-size: clamp(8px, 2.8cqw, 14px); }
#pinePipWidgets .pip-rec .pip-rec-main { grid-template-columns: clamp(28px, 11cqw, 64px) minmax(0, 1fr) clamp(24px, 9cqw, 52px) clamp(40px, 17cqw, 120px); column-gap: clamp(4px, 2cqw, 12px); row-gap: clamp(3px, 1.6cqw, 10px); }
#pinePipWidgets .pip-rec .pip-rec-record { width: clamp(28px, 11cqw, 64px); height: clamp(28px, 11cqw, 64px); }
#pinePipWidgets .pip-rec .pip-rec-record i { width: clamp(12px, 5cqw, 30px); height: clamp(12px, 5cqw, 30px); }
#pinePipWidgets .pip-rec .pip-rec-next { width: clamp(24px, 9cqw, 52px); height: clamp(24px, 9cqw, 52px); }
#pinePipWidgets .pip-rec .pip-rec-next svg { width: clamp(10px, 4.4cqw, 24px); height: clamp(10px, 4.4cqw, 24px); }
#pinePipWidgets .pip-rec .pip-rec-meter { width: clamp(28px, 11cqw, 64px); height: clamp(12px, 5cqw, 28px); }
#pinePipWidgets .pip-rec .pip-rec-bar { height: clamp(10px, 4.4cqw, 24px); }
#pinePipWidgets .pip-rec .pip-rec-bar .pip-rec-range { font-size: clamp(7px, 2.5cqw, 12px); line-height: clamp(8px, 3.6cqw, 20px); }
#pinePipWidgets .pip-rec .pip-rec-readout { font-size: clamp(8px, 3.3cqw, 18px); gap: clamp(3px, 2cqw, 10px); }
#pinePipWidgets .pip-rec .pip-rec-readout output { padding: clamp(1px, .5cqw, 3px) clamp(3px, 1.6cqw, 8px); }
#pinePipWidgets .pip-rec .pip-rec-track { font-size: clamp(28px, 19cqw, 120px); }
#pinePipWidgets .pip-rec .pip-rec-status { font-size: clamp(8px, 3cqw, 14px); }
#pinePipWidgets .pip-rec .pip-rec-tools { width: clamp(18px, 6.5cqw, 30px); height: clamp(18px, 6.5cqw, 30px); }
#pinePipWidgets .pip-rec .pip-rec-notch { width: clamp(36px, 15cqw, 90px); }
#pinePipWidgets .pip-rec.mini { grid-template-columns: minmax(0, 1fr); min-width: 0; width: 132px; }
#pinePipWidgets .pip-rec.mini .pip-rec-art { width: 100%; height: auto; aspect-ratio: 1; }
#pinePipWidgets .pip-rec.mini .pip-rec-main { grid-template-columns: clamp(24px, 26cqw, 48px) minmax(0, 1fr) clamp(20px, 22cqw, 40px); }
'''
EDITS = {
    "desktop/renderer/pine-pip.css": [("the recorder's parts follow its size", None, CSS_NEW, "/* [pip-rec-fit] the recorder is a size container", 1)],
    "app/src/main/assets/pine-views/pine-pip.css": [("the recorder's parts follow its size", None, CSS_NEW, "/* [pip-rec-fit] the recorder is a size container", 1)],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


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
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            have = text.count(probe)
            state = "applied" if have == count else "ready" if not have else "missing (probe %d)" % have
            if state == "ready":
                text = text.rstrip("\n") + "\n" + new
                changed = True
            print("%-46s %-40s %s" % (name[-46:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".recfit.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
