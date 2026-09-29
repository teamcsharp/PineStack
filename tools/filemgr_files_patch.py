#!/usr/bin/env python3
"""[filemgr] place the NEW files: the module, the shipped wipe manifest, the
tests, and the view (canonical desktop/renderer + the repo's pine-views mirror).

    python3 filemgr_files_patch.py --check <repo root>   # 0 ready, 2 applied, 1 collision/missing payload
    python3 filemgr_files_patch.py --apply <repo root>

Sources are ./payload/ beside this script. A destination that exists with
DIFFERENT bytes is a collision (1) - nothing is overwritten. The kiosk
(C:\\_tools\\pinebox-android\\PineBoxKiosk\\app\\src\\main\\assets\\pine-views)
needs the two view files copied by hand plus the ViewAssets.kt entry.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "filemgr.py": "filemgr.py",
    "tools/filemgr_groups.json": "filemgr_groups.json",
    "tests/test_filemgr.py": "test_filemgr.py",
    "desktop/renderer/filemgr.js": "filemgr.js",
    "desktop/renderer/filemgr.css": "filemgr.css",
    "app/src/main/assets/pine-views/filemgr.js": "filemgr.js",
    "app/src/main/assets/pine-views/filemgr.css": "filemgr.css",
}


def blob(p: str) -> bytes | None:
    try:
        return open(p, "rb").read()
    except OSError:
        return None


def state(root: str) -> tuple[int, str]:
    same, absent, clash, nosrc = [], [], [], []
    for dest, src in FILES.items():
        want = blob(os.path.join(HERE, "payload", src))
        if want is None:
            nosrc.append(src)
            continue
        have = blob(os.path.join(root, dest))
        (absent if have is None else same if have == want else clash).append(dest)
    if nosrc:
        return 1, "payload missing: %s" % nosrc
    if clash:
        return 1, "exists with different bytes: %s" % clash
    if not absent:
        return 2, "applied"
    if same:
        return 0, "ready (partly placed: %d of %d)" % (len(same), len(FILES))
    return 0, "ready"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = argv[2]
    code, why = state(root)
    if argv[1] == "--check" or code != 0:
        print("%s: %s" % (root, why))
        return code
    for dest, src in FILES.items():
        path = os.path.join(root, dest)
        if os.path.exists(path):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".filemgr-tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob(os.path.join(HERE, "payload", src)) or b"")
        os.replace(tmp, path)
    code, why = state(root)
    print("%s: %s" % (root, why))
    return 2 if code == 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
