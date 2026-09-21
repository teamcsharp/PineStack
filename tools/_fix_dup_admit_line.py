"""Remove the stale first copy of the admission_admit_line block.

`--revert` on `_admission_reach_patch.py` could not take the old block out
because the tool's own text had already been edited, so `--apply` inserted
the new one above it and app.py briefly held both. The later definition is
the one Python binds, so the station was never wrong - but a dead duplicate
of a function this size is exactly the sort of thing a later reader trusts.

Idempotent: it does nothing when there is only one of each.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path("app.py")
TOOL = "tools/_admission_reach_patch.py"
OLD_COMMIT = "417be30"


def load_old_tool():
    raw = subprocess.run(["git", "show", f"{OLD_COMMIT}:{TOOL}"],
                         capture_output=True, check=True).stdout
    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as fh:
        fh.write(raw)
        name = fh.name
    spec = importlib.util.spec_from_file_location("_old_reach", name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    text = APP.read_bytes().decode("utf-8")
    have = text.count("def admission_admit_line(")
    if have == 1:
        print("one definition; nothing to do")
        return 0
    if have != 2:
        print(f"{have} definitions - refusing to guess", file=sys.stderr)
        return 1

    old = load_old_tool().ADMIT_LINE_NEW
    block = old[:old.index("def admission_state(")]
    found = text.count(block)
    print(f"the old block appears {found} time(s)")
    if found != 1:
        print("refusing to cut: the old block is not there exactly once",
              file=sys.stderr)
        return 1

    out = text.replace(block, "", 1)
    if out.count("def admission_admit_line(") != 1 \
            or out.count("def admission_withdraw(") != 1 \
            or out.count("def admission_state(") != 1:
        print("the cut did not leave exactly one of each", file=sys.stderr)
        return 1
    if "WHAT THE GATE EXEMPTS" not in out:
        print("the cut removed the NEW block, not the old one",
              file=sys.stderr)
        return 1
    compile(out, "app.py", "exec")
    APP.write_bytes(out.encode("utf-8"))
    print("removed the stale copy; app.py parses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
