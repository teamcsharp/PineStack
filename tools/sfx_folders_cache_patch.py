#!/usr/bin/env python3
"""[sfx-folders-cache] The folder list answers at once. 2026-10-06.

"I want to be able to select any folder from the SFX catalog from the drop down menu." The
menu's Video entry asks /api/sfx/folders, which walked every playable clip of the book (360,000
rows, the database on the share) on every request: over a minute, so the menu listed nothing.
The walk is kept for fifteen minutes and renewed in the background once it is older than five,
so after the first walk the list is immediate; the pin is read fresh every time.

Usage:  sfx_folders_cache_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_folders_cache_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OLD = '''def sfx_folders_view() -> dict[str, Any]:
    """Every folder the book knows, with counts and a few samples to
    preview - one read of the book, grouped here."""
    out: dict[str, dict[str, Any]] = {}
'''
NEW = '''_SFX_FOLDERS_MEMO: dict[str, Any] = {"at": 0.0, "folders": None, "busy": False}   # [sfx-folders-cache]
SFX_FOLDERS_KEEP_S = 900.0
SFX_FOLDERS_RENEW_S = 300.0


def sfx_folders_view() -> dict[str, Any]:
    """[sfx-folders-cache] The folder list, kept: the first call walks the book (slow, the database
    is on the share); later calls answer from the kept list and renew it in the background once it
    is five minutes old. The pin is read fresh every time."""
    now = time.time()
    memo = _SFX_FOLDERS_MEMO
    folders = memo.get("folders")
    if folders is None or now - float(memo.get("at") or 0) > SFX_FOLDERS_KEEP_S:
        folders = _sfx_folders_scan()
        memo.update(at=time.time(), folders=folders)
    elif now - float(memo.get("at") or 0) > SFX_FOLDERS_RENEW_S and not memo.get("busy"):
        memo["busy"] = True

        def _renew() -> None:
            try:
                memo.update(at=time.time(), folders=_sfx_folders_scan())
            except Exception:  # noqa: BLE001
                pass
            finally:
                memo["busy"] = False

        import threading as _threading                  # app.py keeps no module-level threading name
        _threading.Thread(target=_renew, name="sfx-folders-renew", daemon=True).start()
    pin = sfx_pin_view()
    return {"ok": True, "folders": folders, "pin": pin, "kept_s": round(time.time() - float(memo.get("at") or 0), 1),
            "say": ("all clips come from %s for another %d min" % (pin["name"], pin["minutes_left"]))
                   if pin else "every folder - no pin"}


def _sfx_folders_scan() -> list[dict[str, Any]]:
    """Every folder the book knows, with counts and a few samples to
    preview - one read of the book, grouped here."""
    out: dict[str, dict[str, Any]] = {}
'''
TAIL_OLD = '''    folders = sorted(out.values(), key=lambda f: f["path"])[:300]
    pin = sfx_pin_view()
    return {"ok": True, "folders": folders, "pin": pin,
            "say": ("all clips come from %s for another %d min" % (pin["name"], pin["minutes_left"]))
                   if pin else "every folder - no pin"}
'''
TAIL_NEW = '''    return sorted(out.values(), key=lambda f: f["path"])[:300]
'''
EDITS = {"app.py": [
    ("the list is kept", OLD, NEW, "def _sfx_folders_scan() -> list[dict[str, Any]]:", 1),
    ("the scan returns the list", TAIL_OLD, TAIL_NEW, '    return sorted(out.values(), key=lambda f: f["path"])[:300]\n', 1),
]}


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
            print("%-20s (not in this tree - skipped)" % name)
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-20s %-36s %s" % (name, label, state))
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
        tmp = path.with_name(path.name + ".sfxfolders.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
