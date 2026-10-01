"""[sfx-library] the SFX Guy's database as a searchable, editable table.

Installs sfx_library.py's routes (search, suggestions, one entry, edits,
export) after the vector section they read from.

Usage (ON THE HOST): python3 tools/sfx_library_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[sfx-library]"

OLD = '''except Exception as _sfxv_exc:  # noqa: BLE001
    _SFX_VECTORS_RUNTIME = None
    print("sfx vectors did not install: %s: %s" % (type(_sfxv_exc).__name__, _sfxv_exc))
'''
NEW = OLD + '''# [sfx-library] his database as a table: search with suggestions, one entry,
# edits (words, operator tags), export - sfx_library.py
try:
    from sfx_library import install as install_sfx_library
    install_sfx_library(app, globals())
except Exception as _sfxl_exc:  # noqa: BLE001
    print("sfx library did not install: %s: %s" % (type(_sfxl_exc).__name__, _sfxl_exc))
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-sfx-library")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
