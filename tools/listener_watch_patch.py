"""[listener-watch] a new submission joins the library within minutes, not hours.

The library rescans every MUSIC_INDEX_TTL (six hours); a listener who drops a
track into samples_grabbed/user should not wait that long. The submissions
folder is small, so each listener-lane look lists it (at most every
LISTENER_WATCH_S) and asks for one rescan when it holds an audio file the
library does not know. The rescan reuses every unchanged file's cached tags.

Usage (ON THE HOST): python3 tools/listener_watch_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[listener-watch]"

OLD = '''def listener_tracks() -> list[dict[str, Any]]:
    """[listener-lane] the library records under USER_MUSIC_ROOT."""
    root = str(USER_MUSIC_ROOT).rstrip("/") + "/"
    try:
        return [t for t in music_index() if str(t.get("path") or "").startswith(root)]
    except Exception:  # noqa: BLE001
        return []
'''
NEW = '''LISTENER_WATCH_S = 300.0
_LISTENER_WATCH = {"at": 0.0}


def _listener_watch(known: list[dict[str, Any]]) -> None:
    """[listener-watch] a submission the library does not know yet asks for one
    rescan (tags of unchanged files come from the cache)."""
    now = time.time()
    if now - _LISTENER_WATCH["at"] < LISTENER_WATCH_S or _MUSIC.get("scanning"):
        return
    _LISTENER_WATCH["at"] = now
    have = {str(t.get("path") or "") for t in known}
    try:
        for p in _music_walk(USER_MUSIC_ROOT):
            if p.suffix.lower() in MUSIC_TYPES and str(p) not in have:
                pipeline_log("air", "listener lane: %s arrived in the submissions - the library "
                             "reads it in [listener-watch]" % p.name)
                music_index(force=True)
                return
    except Exception:  # noqa: BLE001
        return


def listener_tracks() -> list[dict[str, Any]]:
    """[listener-lane] the library records under USER_MUSIC_ROOT."""
    root = str(USER_MUSIC_ROOT).rstrip("/") + "/"
    try:
        got = [t for t in music_index() if str(t.get("path") or "").startswith(root)]
    except Exception:  # noqa: BLE001
        return []
    _listener_watch(got)                                                   # [listener-watch]
    return got
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor"
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-listener-watch")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
