#!/usr/bin/env python3
"""[plcover] [pip-rec] The live set's cover can be chosen; the PiP's album recorder widget is a shared setting. 2026-10-05.

"Album art - should show the album art of the current recording. If I click it, allow me to
 select a recent render from ComfyUI / H3 or a supercut recording or SFX clip."

The set's cover (/music/<live id>/art, the MJPEG every player shows) was always a random
picture from PLART_DIR, re-rolled per track. POST /api/pinelive/cover now sets it:
  {"clip_id": <16 hex>}        the clip's own first picture (a video clip's poster)
  {"generation": <filename>}   a finished render from the gallery (an image, or a video's poster)
  {"clear": true}              back to the rolled covers
It is kept for the running set (or the next one when none runs), named in the state as
`cover_override`. The widget's visibility (`widgets.rec`) joins the PiP settings the station shares.

Usage:  pinelive_cover_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pinelive_cover_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PL_VARS_OLD = '''_PLART_LAST: list[Any] = [None]          # [pltrack] the cover just shown
'''
PL_VARS_NEW = '''_PLART_LAST: list[Any] = [None]          # [pltrack] the cover just shown
# [plcover] the operator's chosen cover: {event, kind, data, name}; empty = the rolled covers
_PLART_OVERRIDE: dict[str, Any] = {}
'''

PL_COVER_OLD = '''def _plart_cover(event_key: str) -> tuple[str, bytes] | None:
    """(media type, bytes) of this event's cover, or None (then the camera)."""
    got = _PLART_MEMO.get(event_key)
'''
PL_COVER_NEW = '''def plart_override_set(kind: str, data: bytes, name: str, event: str) -> dict[str, Any]:
    """[plcover] The chosen cover, for this set (or the next one when none runs)."""
    _PLART_OVERRIDE.clear()
    if data:
        _PLART_OVERRIDE.update({"event": event, "kind": kind, "data": data, "name": name, "at": time.time()})
    _PLART_MEMO.clear()
    return {"name": name, "bytes": len(data), "event": event}


def plart_override_view() -> dict[str, Any]:
    ov = _PLART_OVERRIDE
    return {"name": str(ov.get("name") or ""), "set": bool(ov.get("data")), "event": str(ov.get("event") or "")}


def _plart_cover(event_key: str) -> tuple[str, bytes] | None:
    """(media type, bytes) of this event's cover, or None (then the camera)."""
    ov = _PLART_OVERRIDE                                   # [plcover] the operator's choice first
    if ov.get("data") and ov.get("event") in ("", event_key):
        if ov.get("event") == "":
            ov["event"] = event_key                        # the next set took it
        return (str(ov.get("kind") or "image/jpeg"), ov["data"])
    got = _PLART_MEMO.get(event_key)
'''

PL_STATE_OLD = '''            "art_url": art,
            "ingest_url": ingest,
'''
PL_STATE_NEW = '''            "art_url": art,
            "cover_override": plart_override_view(),           # [plcover]
            "ingest_url": ingest,
'''

PL_ROUTE_OLD = '''    @app.get("/api/pinelive/state")
'''
PL_ROUTE_NEW = '''    @app.post("/api/pinelive/cover")
    async def pinelive_cover_api(request: Request,
                                 authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[plcover] The set's cover, chosen: a clip's picture, a render from the gallery, or cleared."""
        auth(authorization)
        body = await body_of(request)
        if body.get("clear"):
            plart_override_set("", b"", "", "")
            PL.note("cover", "the cover goes back to the rolled pictures")
            return {"ok": True, "say": "the covers roll again", "cover": plart_override_view()}

        def picture() -> tuple[str, bytes, str]:
            clip = str(body.get("clip_id") or "").strip()
            gen = str(body.get("generation") or "").strip()
            render = _app("_render_poster")
            poster_dir = _app("SFX_POSTER_DIR")
            if clip:
                if not re.fullmatch(r"[a-f0-9]{16}", clip):
                    raise ValueError("that is not a clip identity")
                by_id = _app("sfx_by_id")
                sample = by_id(clip) if callable(by_id) else None
                if sample is None:
                    raise ValueError("the station has no such clip")
                is_video = _app("sfx_is_video")
                if not (callable(is_video) and is_video(sample)):
                    raise ValueError("that clip has no picture (it is sound only)")
                if not callable(render) or poster_dir is None:
                    raise ValueError("the station cannot draw a clip's picture here")
                out = Path(poster_dir) / f"{clip}.jpg"
                if not out.exists():
                    Path(poster_dir).mkdir(parents=True, exist_ok=True)
                    if not render(sample, out):
                        raise ValueError("the clip's picture could not be drawn")
                return "image/jpeg", out.read_bytes(), Path(str(sample)).name
            if gen:
                if "/" in gen or ".." in gen or not re.fullmatch(r"[\w.\- ()\[\]]{1,200}", gen):
                    raise ValueError("that is not a render's filename")
                find = _app("comfy_output_find")
                path = find(gen) if callable(find) else None
                if path is None or not Path(path).is_file():
                    raise ValueError("that render is not in the gallery any more")
                is_video = _app("sfx_is_video")
                if callable(is_video) and is_video(Path(path)):
                    if not callable(render) or poster_dir is None:
                        raise ValueError("the station cannot draw a render's picture here")
                    sid = _app("sfx_id")(Path(path))
                    out = Path(poster_dir) / f"{sid}.jpg"
                    if not out.exists():
                        Path(poster_dir).mkdir(parents=True, exist_ok=True)
                        if not render(Path(path), out):
                            raise ValueError("the render's picture could not be drawn")
                    return "image/jpeg", out.read_bytes(), Path(path).name
                suffix = Path(path).suffix.lower()
                kind = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
                data = Path(path).read_bytes()
                if len(data) > 24 * 1024 * 1024:
                    raise ValueError("that picture is too large for a cover")
                return kind, data, Path(path).name
            raise ValueError("name a clip_id or a generation, or clear")

        try:
            kind, data, name = await asyncio.to_thread(picture)
        except ValueError as exc:
            return {"ok": False, "code": "cover", "say": str(exc), "cover": plart_override_view()}
        event = PL.event_id() if PL.event is not None else ""
        got = plart_override_set(kind, data, name, event)
        PL.note("cover", "the cover is %s%s" % (name, " for the running set" if event else " for the next set"))
        return {"ok": True, "say": "the cover is %s" % name, "cover": plart_override_view(), "bytes": got["bytes"]}

    @app.get("/api/pinelive/state")
'''

APP_WIDGETS_OLD = '''    "widgets": {"dialogue": True, "task": False, "audit": False, "production": False,
                "music": False, "chat": False, "messages": False, "cast": False,
                "voices": False, "roulette": False},
'''
APP_WIDGETS_NEW = '''    "widgets": {"dialogue": True, "task": False, "audit": False, "production": False,
                "music": False, "chat": False, "messages": False, "cast": False,
                "voices": False, "roulette": False, "rec": False},   # [pip-rec] the album recorder
'''

EDITS = {
    "pinelive.py": [
        ("the chosen cover's place", PL_VARS_OLD, PL_VARS_NEW, "_PLART_OVERRIDE: dict[str, Any] = {}", 1),
        ("the choice comes first", PL_COVER_OLD, PL_COVER_NEW, "def plart_override_set(kind: str, data: bytes, name: str, event: str) -> dict[str, Any]:", 1),
        ("the state names it", PL_STATE_OLD, PL_STATE_NEW, '"cover_override": plart_override_view(),', 1),
        ("POST /api/pinelive/cover", PL_ROUTE_OLD, PL_ROUTE_NEW, '@app.post("/api/pinelive/cover")', 1),
    ],
    "app.py": [
        ("the recorder widget is a shared setting", APP_WIDGETS_OLD, APP_WIDGETS_NEW, '"voices": False, "roulette": False, "rec": False},', 1),
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
        tmp = path.with_name(path.name + ".plcover.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
