"""[h3-anyfootage] any footage or recording -> H3, as a stinger's reference video,
through the ONE stinger window the station already has.

"For any footage or recording, I want an option to send it to H3 and have it used
as a reference for a stinger." (operator; "Always reference video".)

The SFX TV's parody window (sfx-tv.js parodyOpen, exported as
PineSfxTv.openParody) is the station's stinger road: dictation, an In/Out trim over
the reference video, the parody_stinger queue and its history. Every footage
surface now opens THAT window with its own clip as the seed:
  - the Pine Cam Recordings tab (footage, kept, cuts, album cuts) and the screen
    exports (the PineTab / Pine Box app screen recordings, data/exports), which the
    tab now lists too - pinned first (POST /api/pinecam/h3-ref) so the reference
    cannot roll off while the stinger waits in the queue;
  - every video bubble in the Message view (its SFX clip, source_type "clip");
  - the SFX TV itself, as before.

  app.py        screen exports in pinecam_path_of / pinecam_recordings,
                GET /api/pinecam/file/{name}, POST /api/pinecam/h3-ref
Usage (ON THE HOST): python3 tools/h3_anyfootage_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[h3-anyfootage]"

APP = [
    ('''PINECAM_RADIO = DATA_DIR / "pinelink_radio.json"
''', '''PINECAM_RADIO = DATA_DIR / "pinelink_radio.json"
PINECAM_SCREENS = data_path("exports")   # [h3-anyfootage] the screen exports (PineTab / Pine Box app)
''', 1),
    ('''    for folder in (pinelink_clips_dir(), PINELINK_CUTS, PINECAM_EXPORTS):
''', '''    for folder in (pinelink_clips_dir(), PINELINK_CUTS, PINECAM_EXPORTS, PINECAM_SCREENS):
''', 1),
    ('''    items.sort(key=lambda r: r["at"], reverse=True)
    return {"items": items, "count": len(items), "dest": pinecam_export_dest(),
''', '''    # [h3-anyfootage] the screen recordings are footage too
    try:
        screens = sorted((p for p in PINECAM_SCREENS.glob("*") if p.is_file()
                          and p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv")),
                         key=lambda q: q.stat().st_mtime, reverse=True)[:200]
    except Exception:  # noqa: BLE001
        screens = []
    for p in screens:
        if not PINELINK_NAME.match(p.name):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({"name": p.name, "kind": "screen", "at": st.st_mtime, "bytes": st.st_size,
                      "url": "/api/pinecam/file/" + p.name, "writing": now - st.st_mtime < 5,
                      "host_path": share_path_of(p), "broken": False})
    items.sort(key=lambda r: r["at"], reverse=True)
    return {"items": items, "count": len(items), "dest": pinecam_export_dest(),
''', 1),
    ('''@app.post("/api/pinecam/h3")
''', '''@app.get("/api/pinecam/file/{name}")
async def pinecam_file_api(name: str, authorization: str | None = Header(default=None)) -> Response:
    """[h3-anyfootage] any recording by name (kept, cut, export, screen), seekable."""
    require_read_auth(authorization)
    path = pinecam_path_of(name)
    if path is None:
        raise HTTPException(status_code=404, detail="no such recording")
    kind = "video/webm" if path.suffix.lower() == ".webm" else "video/mp4"
    return FileResponse(path, media_type=kind, headers={"Accept-Ranges": "bytes"})


def pinecam_pin(src: Path) -> Path:
    """A reference copy that is not rolled off with the two days of footage (or
    tidied out of data/exports) while its stinger waits in the queue."""
    PINECAM_EXPORTS.mkdir(parents=True, exist_ok=True)
    pinned = PINECAM_EXPORTS / (src.name if src.name.startswith("h3_") else ("h3_" + src.name)[:64])
    if not pinned.is_file():
        shutil.copy2(src, pinned)
    return pinned


@app.post("/api/pinecam/h3-ref")
async def pinecam_h3_ref_api(
    request: Request, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[h3-anyfootage] pin a recording as an H3 reference and hand back the seed
    the stinger window takes (PineSfxTv.openParody): id, url, seconds, source_type."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    src = pinecam_path_of(str((body or {}).get("name") or ""))
    if src is None:
        return {"ok": False, "say": "that recording is no longer kept"}
    try:
        pinned = await asyncio.to_thread(pinecam_pin, src)
        seconds = await asyncio.to_thread(_media_duration_probe, pinned)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "say": "could not keep the reference: %s" % str(exc)[:160]}
    return {"ok": True, "id": pinned.name, "source_type": "pinecam", "video": True,
            "url": "/api/pinecam/file/" + pinned.name, "seconds": round(float(seconds or 0), 2),
            "sting": src.name, "say": "pinned as %s" % pinned.name}


@app.post("/api/pinecam/h3")
''', 1),
    # the plain route pins through the same helper
    ('''    def _pin() -> str:
        # the reference is pinned: a copy that is not rolled off with the
        # two days of footage while the stinger waits its turn in the queue
        PINECAM_EXPORTS.mkdir(parents=True, exist_ok=True)
        pinned = PINECAM_EXPORTS / ("h3_" + src.name if not src.name.startswith("h3_") else src.name)
        if not pinned.is_file():
            shutil.copy2(src, pinned)
        return pinned.name
''', '''    def _pin() -> str:
        return pinecam_pin(src).name                  # [h3-anyfootage] one pinning road
''', 1),
]


def patch(path, edits, mode):
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-h3-anyfootage" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    patch(ROOT + "/app.py", APP, sys.argv[1])
