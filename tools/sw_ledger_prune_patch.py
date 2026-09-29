#!/usr/bin/env python3
"""[ledger-prune-atomic] THE SCRIPT LEDGER IS NEVER SEEN HALF WRITTEN.

TARGET: app.py

Found 09-29 by tools/script_watch.py, which lost nine rows of one block (38813)
while tailing data/script_ledger.jsonl. The ledger crossed
SCRIPT_LEDGER_MAX_BYTES (8 MB) and _script_ledger_prune ran: it re-wrote the
WHOLE file in place with Path.write_text - truncate to zero, then write 8.5 MB -
while keeping every row, because the keep is two days and the file held six
hours. Every hour from now on it would do the same, under the ledger lock, in
the writer's path. Any reader in that window (script_ledger_rows on a cold
memo, the screenplay's catch-up, a watcher) sees an empty or truncated script.

Now: nothing to drop means nothing is rewritten, and a real prune writes a
sibling file and os.replace()s it, so a reader sees the old ledger or the new
one, never a half. The memo refresh is unchanged.

    python3 sw_ledger_prune_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
    python3 sw_ledger_prune_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TARGET = "app.py"
MARKER = "[ledger-prune-atomic]"

EDITS = [
    ("read",
     '        for line in SCRIPT_LEDGER_PATH.read_text().splitlines():\n'
     '            try:\n'
     '                row = json.loads(line)\n'
     '                if float(row.get("at") or 0) >= floor:\n',
     '        _lines = [x for x in SCRIPT_LEDGER_PATH.read_text().splitlines() if x.strip()]  # [ledger-prune-atomic]\n'
     '        for line in _lines:\n'
     '            try:\n'
     '                row = json.loads(line)\n'
     '                if float(row.get("at") or 0) >= floor:\n'),
    ("write",
     '        SCRIPT_LEDGER_PATH.write_text("\\n".join(keep) + "\\n")\n',
     '        # [ledger-prune-atomic] nothing to drop is nothing to rewrite; a real prune\n'
     '        # replaces the file whole, so no reader ever sees it truncated mid-write\n'
     '        if len(keep) < len(_lines):\n'
     '            _tmp = SCRIPT_LEDGER_PATH.with_name(SCRIPT_LEDGER_PATH.name + ".prune.tmp")\n'
     '            _tmp.write_text("\\n".join(keep) + "\\n")\n'
     '            os.replace(_tmp, SCRIPT_LEDGER_PATH)\n'),
]


def load(root: Path):
    path = root / TARGET
    raw = path.read_bytes().decode("utf-8")
    return path, raw.replace("\r\n", "\n"), "\r\n" in raw


def check(root: Path):
    try:
        _p, text, _c = load(root)
    except OSError as exc:
        return 1, ["cannot read %s: %s" % (TARGET, exc)]
    if MARKER in text:
        return 2, ["already applied"]
    bad = ["anchor %s: found %d" % (n, text.count(a)) for n, a, _ in EDITS if text.count(a) != 1]
    return (1, bad) if bad else (0, [])


def apply(root: Path) -> int:
    code, _why = check(root)
    if code != 0:
        return code
    path, text, crlf = load(root)
    for _n, anchor, new in EDITS:
        text = text.replace(anchor, new, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ledger_prune.")
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply [ROOT]" % argv[0])
        return 1
    root = Path(argv[2] if len(argv) > 2 else ".").resolve()
    if argv[1] == "--check":
        code, why = check(root)
        print({0: "READY", 2: "APPLIED", 1: "MISSING"}[code], "; ".join(why))
        return code
    code = apply(root)
    print({0: "APPLIED", 2: "ALREADY APPLIED"}.get(code, "NOT APPLIED: " + "; ".join(check(root)[1])))
    return 0 if code in (0, 2) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
