"""[pin-any-folder] "Where the clips come from" refused the generated ads.

2026-09-30, the operator ticked sfx_ads for the next hour and got "the
station did not answer: that is not a folder in the SFX collection". The
sheet lists every folder the clip book holds (sfx_folders_view reads the
book), but the pin route only accepted paths under SFX_ROOT and
SFX_MADE_DIR - and the generated ads live in COMFY_OUTPUT/sfx_ads, a third
root the book indexes and the gate never learned.

Every road that honours the pin filters the BOOK by the pinned prefix, so
the true test of "a folder in the SFX collection" is the book itself: a
path with at least one playable clip under it. The old roots still pass
(an empty folder there may still be pinned, as before).

Usage (ON THE HOST): python3 tools/pin_any_folder_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[pin-any-folder]"

EDITS = [
    ("gate",
     '''    if not root_ok or ".." in path:
        raise HTTPException(status_code=400, detail="that is not a folder in the SFX collection")
''',
     '''    if not root_ok and ".." not in path:                   # [pin-any-folder]
        root_ok = await asyncio.to_thread(sfx_pin_folder_known, path)
    if not root_ok or ".." in path:
        raise HTTPException(status_code=400, detail="that is not a folder in the SFX collection")
'''),
    ("helper",
     '''def sfx_pin_set(path: str, hours: float) -> dict[str, Any]:
''',
     '''def sfx_pin_folder_known(path: str) -> bool:
    """[pin-any-folder] a folder is in the SFX collection when the clip book
    holds a playable clip under it - the same book the folder sheet lists
    and every pinned road filters (sfx_ads under COMFY_OUTPUT was listed and
    refused). substr, not LIKE: folder names carry '_' and '%'."""
    prefix = str(path).rstrip("/") + "/"
    try:
        con = sfx_db_reader()
        return con.execute("SELECT 1 FROM clips WHERE playable = 1 AND substr(path, 1, ?) = ? LIMIT 1",
                           (len(prefix), prefix)).fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def sfx_pin_set(path: str, hours: float) -> dict[str, Any]:
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-pin-any-folder")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
