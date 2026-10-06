#!/usr/bin/env python3
"""[pip-free] [pip-art] [pip-find] The station's side of the second PiP wave. 2026-10-05.

[pip-free]  Every PiP widget carries a layout entry on the desk ({x,y,w,h,s,t,o}); the shared
            PiP settings carry it too, normalised like every other field. A posted layout is
            the complete map (the desk posts its whole state), so it replaces.
[pip-art]   musicArtOnly - the mini player reduced to its artwork - travels with the settings.
[pip-find]  "show suggestive search results as i type. So I can click on the item that's the
            nearest" - the desk lists /api/music/search hits and asks for the clicked one by
            its id as well as its words; /api/dj/request now takes that id, so the very record
            that was clicked is the one queued, not the search's first guess.

Usage:  pip_station_layout_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_station_layout_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULTS_OLD = '''    "musicPosition": {"x": .03, "y": .6}, "musicExpanded": False,
    "widgets": {"dialogue": True, "task": False, "audit": False, "production": False,
'''
DEFAULTS_NEW = '''    "musicPosition": {"x": .03, "y": .6}, "musicExpanded": False,
    "musicArtOnly": False,   # [pip-art] the player reduced to its artwork
    "layout": {},            # [pip-free] one entry per widget: {x,y,w,h,s,t,o}
    "widgets": {"dialogue": True, "task": False, "audit": False, "production": False,
'''

LAYOUT_FN_OLD = '''def normalize_pip_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    out = dict(PIP_DEFAULTS)
'''
LAYOUT_FN_NEW = '''PIP_LAYOUT_NAMES = ("dialogue", "task", "audit", "production", "music", "chat", "messages", "cast", "voices", "roulette", "camera")
PIP_LAYOUT_FIELDS = {"x": (0.0, 1.0), "y": (0.0, 1.0), "w": (0.0, 1.0), "h": (0.0, 1.0), "s": (.4, 3.0), "o": (.1, 1.0)}


def normalize_pip_layout(raw: Any) -> dict[str, dict[str, Any]]:
    """[pip-free] One entry per widget: its place and size as shares of the window, a scale,
    four trims (% of the widget, top right bottom left) and an opacity. Anything else is dropped;
    an entry with nothing usable is no entry."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for name in PIP_LAYOUT_NAMES:
        entry = raw.get(name)
        if not isinstance(entry, dict):
            continue
        kept: dict[str, Any] = {}
        for field, (low, high) in PIP_LAYOUT_FIELDS.items():
            try:
                number = float(entry.get(field))
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(number):
                kept[field] = round(max(low, min(high, number)), 4)
        trims = entry.get("t")
        if isinstance(trims, list) and len(trims) == 4:
            try:
                sides = [float(v) for v in trims]
            except (TypeError, ValueError, OverflowError):
                sides = []
            if len(sides) == 4 and all(math.isfinite(v) for v in sides):
                sides = [round(max(0.0, min(45.0, v)), 1) for v in sides]
                if any(sides):
                    kept["t"] = sides
        if kept:
            out[name] = kept
    return out


def normalize_pip_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    out = dict(PIP_DEFAULTS)
'''

NORMALIZE_OLD = '''    out["musicExpanded"] = raw.get("musicExpanded") is True   # [pip-music]
'''
NORMALIZE_NEW = '''    out["musicExpanded"] = raw.get("musicExpanded") is True   # [pip-music]
    out["musicArtOnly"] = raw.get("musicArtOnly") is True     # [pip-art]
    out["layout"] = normalize_pip_layout(raw.get("layout"))   # [pip-free]
'''

MERGE_OLD = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds", "messageTile", "roulettePosition", "musicPosition"):
        if isinstance(payload.get(key), dict): merged[key] = {**current[key], **payload[key]}
    normalized = normalize_pip_settings(merged)
'''
MERGE_NEW = '''    for key in ("widgets", "docks", "order", "voiceStyles", "cameraBounds", "messageBounds", "messageTile", "roulettePosition", "musicPosition"):
        if isinstance(payload.get(key), dict): merged[key] = {**current[key], **payload[key]}
    # [pip-free] the desk posts its whole layout, so a posted layout is the complete map:
    # it replaces (a widget it no longer names has been reset); null clears every entry
    if "layout" in payload:
        merged["layout"] = payload["layout"] if isinstance(payload["layout"], dict) else {}
    normalized = normalize_pip_settings(merged)
'''

REQUEST_API_OLD = '''    query = str(payload.get("q") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Name a song")
    result = await dj_request(query, now=bool(payload.get("now")))
'''
REQUEST_API_NEW = '''    query = str(payload.get("q") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Name a song")
    # [pip-find] a record chosen from the suggestions is asked for by its id: that very record is queued
    result = await dj_request(query, now=bool(payload.get("now")), track_id=str(payload.get("id") or "").strip())
'''

REQUEST_FN_OLD = '''async def dj_request(query: str, now: bool = False) -> dict[str, Any]:
    """Queue it or cut to it, and have the DJ acknowledge either way."""
    hits = music_search(query, limit=1)
'''
REQUEST_FN_NEW = '''async def dj_request(query: str, now: bool = False, track_id: str = "") -> dict[str, Any]:
    """Queue it or cut to it, and have the DJ acknowledge either way.
    [pip-find] With a track_id (a record clicked in the desk's suggestions) that record is the
    one queued; the words are kept for the DJ's acknowledgement and the request memory."""
    chosen = music_track(track_id) if track_id else None
    hits = [chosen] if chosen else music_search(query, limit=1)
'''

EDITS = {
    "app.py": [
        ("the defaults carry the two new keys", DEFAULTS_OLD, DEFAULTS_NEW, '"layout": {},            # [pip-free]', 1),
        ("normalize_pip_layout()", LAYOUT_FN_OLD, LAYOUT_FN_NEW, "def normalize_pip_layout(raw: Any) -> dict[str, dict[str, Any]]:", 1),
        ("the settings are normalised", NORMALIZE_OLD, NORMALIZE_NEW, 'out["layout"] = normalize_pip_layout(raw.get("layout"))', 1),
        ("a posted layout replaces", MERGE_OLD, MERGE_NEW, 'merged["layout"] = payload["layout"] if isinstance(payload["layout"], dict) else {}', 1),
        ("a request may name the record", REQUEST_API_OLD, REQUEST_API_NEW, 'track_id=str(payload.get("id") or "").strip())', 1),
        ("dj_request takes the record", REQUEST_FN_OLD, REQUEST_FN_NEW, "chosen = music_track(track_id) if track_id else None", 1),
    ],
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
            print("%-20s %-44s %s" % (name, label, state))
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
        tmp = path.with_name(path.name + ".piplayout.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
