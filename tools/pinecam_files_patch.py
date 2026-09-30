"""[cam-files] File management learns the Pine Cam's videos.

2026-09-30, the operator: "Make sure the file management tab also talks about
the ... videos that are captured by the Pinecam and it offers a tab allowing
me to view and export those to my recordings folder and to delete those and
clear the cache of'em."

Viewing and exporting already had roads (/api/pinecam/recordings, /thumb,
/export, the clip/cut/file routes the Pine Cam's own Recordings tab plays).
What was missing: a measure of what the camera's files hold on the Spark, a
delete, and a cache clear. The cache is only what can be made again from the
footage: thumbnails, re-encoded copies (pinecam_encode) and window cuts
(pinelink_cut_span, named by their span, so a repeat is simply re-cut).
Never the footage or the kept clips, never an album cut, and never a pinned
H3 reference (h3_*) a queued stinger still waits on.

Usage (ON THE HOST): python3 tools/pinecam_files_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[cam-files]"

AT = '''@app.get("/api/pinecam/file/{name}")
'''
NEW = '''# [cam-files] File management's Pine Cam videos: what they hold on the Spark,
# a delete, and a cache clear. The cache is only what the footage can make
# again - thumbnails, re-encoded copies, window cuts - never the footage, the
# kept clips, an album cut, or a pinned H3 reference (h3_*).
def pinecam_cache_files() -> list[Path]:
    out: list[Path] = []
    for folder, keep in ((PINECAM_THUMBS, lambda n: True),
                         (PINECAM_EXPORTS, lambda n: not n.startswith("h3_")),
                         (PINELINK_CUTS, lambda n: n.startswith(("cut_", "list_")))):
        try:
            out.extend(p for p in folder.iterdir() if p.is_file() and keep(p.name))
        except OSError:
            pass
    return out


def pinecam_storage() -> dict[str, Any]:
    def tally(paths: list[Path]) -> dict[str, int]:
        n = size = 0
        for p in paths:
            try:
                size += p.stat().st_size
                n += 1
            except OSError:
                pass
        return {"files": n, "bytes": size}

    try:
        clips = [p for p in pinelink_clips_dir().glob("*.mp4") if p.is_file()]
    except OSError:
        clips = []
    try:
        albums = [p for p in PINELINK_CUTS.glob("album_*.mp4") if p.is_file()]
    except OSError:
        albums = []
    rows = {"footage": tally([p for p in clips if _PINECAM_SEGMENT.match(p.name)]),
            "kept": tally([p for p in clips if not _PINECAM_SEGMENT.match(p.name)]),
            "album": tally(albums),
            "cache": tally(pinecam_cache_files())}
    return {"ok": True, **rows,
            "files": sum(r["files"] for r in rows.values()),
            "bytes": sum(r["bytes"] for r in rows.values()),
            "dest": pinecam_export_dest(), "clips_host": share_path_of(pinelink_clips_dir())}


def pinecam_delete(names: list[str]) -> dict[str, Any]:
    clips = pinelink_clips_dir()
    try:
        newest = max((p for p in clips.glob("*.mp4") if _PINECAM_SEGMENT.match(p.name)),
                     key=_pinecam_at, default=None)
    except OSError:
        newest = None
    gone: list[str] = []
    refused: list[dict[str, str]] = []
    freed = 0
    for name in names[:500]:
        p = pinecam_path_of(name)
        if p is None:
            refused.append({"name": name, "why": "no longer kept"})
            continue
        if newest is not None and p == newest and time.time() - p.stat().st_mtime < 30:
            refused.append({"name": name, "why": "still being recorded"})
            continue
        try:
            size = p.stat().st_size
            p.unlink()
        except OSError as exc:
            refused.append({"name": name, "why": str(exc)[:120]})
            continue
        freed += size
        gone.append(name)
        try:
            (PINECAM_THUMBS / (p.stem + ".jpg")).unlink()
        except OSError:
            pass
    _PINELINK_CENSUS["at"] = 0.0
    say = "deleted %d video%s (%.1f MB)" % (len(gone), "" if len(gone) == 1 else "s", freed / 1e6)
    if refused:
        say += "; kept %d: %s" % (len(refused), refused[0]["why"])
    if gone:
        note_action("Pine Cam: " + say + " [cam-files]")
    return {"ok": bool(gone) or not refused, "deleted": gone, "refused": refused,
            "bytes": freed, "say": say}


def pinecam_clear_cache() -> dict[str, Any]:
    n = freed = 0
    for p in pinecam_cache_files():
        try:
            size = p.stat().st_size
            p.unlink()
        except OSError:
            continue
        n += 1
        freed += size
    say = "cleared the Pine Cam cache: %d file%s, %.1f MB" % (n, "" if n == 1 else "s", freed / 1e6)
    note_action(say + " [cam-files]")
    return {"ok": True, "files": n, "bytes": freed, "say": say}


@app.get("/api/pinecam/storage")
async def pinecam_storage_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(pinecam_storage)


@app.post("/api/pinecam/delete")
async def pinecam_delete_api(request: Request,
                             authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    names = [str(n) for n in ((body or {}).get("names") or []) if n]
    if not names:
        return {"ok": False, "say": "name the videos to delete"}
    return await asyncio.to_thread(pinecam_delete, names)


@app.post("/api/pinecam/clear-cache")
async def pinecam_clear_cache_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    return await asyncio.to_thread(pinecam_clear_cache)


'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    n = src.count(AT)
    assert n == 1, "routes: anchor found %d times" % n
    out = src.replace(AT, NEW + AT)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-cam-files")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
