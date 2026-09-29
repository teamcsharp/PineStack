#!/usr/bin/env python3
"""[tree-heard] A SEGMENT'S DECISION TREE SHOWS THE ROUNDS THAT WENT OUT IN IT.

TARGET: script_decision_tree.py

Measured 09-29 by tools/script_watch.py and a two-hour look back: 303 of 1,019
heard lines (30%) were filed under an hour entry that was NOT on air when they
were heard. System 3's segment register files a block under the segment on air
when the block is WRITTEN (app.py script_ledger_commit -> segment_on_air(at) ->
system3_segment_block), and rounds are written a median 51-85 s (p90 up to
290 s) before they sound. So the decision tree opened from an entry drew the
rounds WRITTEN during it - several of which went out in the next entry - and
left out rounds written before it that went out during it.

The register's write-time stamp is kept (the ledger promises a segment never
reopens walking the script in block order). The tree, whose own contract is
"every round that went out in the segment", now reads WHERE A ROUND WAS HEARD
from the origin ledger (system3_origin.sqlite3, already its source for "aired"):

  - a registered round whose heard lines all fall outside the entry's window
    leaves this entry's tree and is listed under `went_elsewhere` with when;
  - a round heard inside the window that the register filed elsewhere joins
    it, marked `filed_elsewhere`;
  - aired rounds keep the script's order (first block).

An entry with no window (or an origin table without the columns) answers
exactly as before. Read only, like the rest of the route.

    python3 sw_tree_heard_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
    python3 sw_tree_heard_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TARGET = "script_decision_tree.py"
MARKER = "[tree-heard]"

HELPERS = '''def heard_where(origin_path: Path, cids: list[str]) -> dict[str, tuple[float, float]]:
    """[tree-heard] conversation -> (first, last) moment a line of it was HEARD,
    from the origin ledger. Read only; {} when absent or the columns are not there."""
    ids = [str(x) for x in dict.fromkeys(cids or []) if x]
    if not ids or not Path(origin_path).is_file():
        return {}
    out: dict[str, tuple[float, float]] = {}
    db = sqlite3.connect("file:" + Path(origin_path).as_posix() + "?mode=ro", uri=True, timeout=5.0)
    try:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            for cid, lo, hi in db.execute("SELECT conversation_id, MIN(air_at), MAX(air_at) FROM origin "
                                          "WHERE conversation_id IN (%s) GROUP BY conversation_id"
                                          % ",".join("?" * len(chunk)), chunk):
                if lo is not None:
                    out[str(cid)] = (float(lo), float(hi))
    except sqlite3.Error:
        return {}
    finally:
        db.close()
    return out


def heard_in(origin_path: Path, start: float, ends: float) -> list[tuple[str, float, int]]:
    """[tree-heard] (conversation, first hearing, first block) of every conversation
    a line of which was HEARD in [start, ends), in the script's order. Read only."""
    if not (start and ends and ends > start) or not Path(origin_path).is_file():
        return []
    db = sqlite3.connect("file:" + Path(origin_path).as_posix() + "?mode=ro", uri=True, timeout=5.0)
    try:
        rows = db.execute("SELECT conversation_id, MIN(air_at), MIN(block) FROM origin WHERE air_at>=? AND "
                          "air_at<? AND conversation_id IS NOT NULL AND conversation_id!='' "
                          "GROUP BY conversation_id ORDER BY MIN(block), MIN(air_at)",
                          (float(start), float(ends))).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()
    return [(str(c), float(a or 0), int(b or 0)) for c, a, b in rows]


def collect(store: Any, seg_id: str, entry: dict[str, Any] | None, origin_path: Path,'''

WINDOW = '''    # [tree-heard] WENT OUT IN = HEARD IN. The register files a block under the
    # segment on air when it was WRITTEN, a median 51-85 s before it sounds; 30% of
    # heard lines (09-29) went out in the next entry. The entry's window decides.
    body_seg = (rec or {}).get("segment") if isinstance((rec or {}).get("segment"), dict) else {}
    try:
        w0 = float((entry or {}).get("start") or body_seg.get("start") or 0)
        w1 = float((entry or {}).get("deadline") or body_seg.get("ends") or 0)
    except (TypeError, ValueError):
        w0 = w1 = 0.0
    went_elsewhere: list[dict[str, Any]] = []
    if w0 and w1 > w0:
        spans = heard_where(origin_path, [cid for cid, _h in picked])
        keep = []
        for cid, how in picked:
            sp = spans.get(cid)
            if sp and not (sp[0] < w1 and sp[1] >= w0):
                went_elsewhere.append({"conversation_id": cid, "heard_from": sp[0], "heard_until": sp[1],
                                       "why": "written while this entry was on air; it went out %s it"
                                              % ("after" if sp[0] >= w1 else "before")})
                continue
            keep.append((cid, how))
        picked = keep
        for cid, first_at, first_block in heard_in(origin_path, w0, w1):
            if cid not in seen:
                seen.add(cid)
                picked.append((cid, {"source": "aired", "first_block": first_block, "blocks": [],
                                     "filed_elsewhere": True, "first_heard": first_at}))
        picked.sort(key=lambda p: (p[1].get("first_block") or 0))
    scripts = scripts_of(entry)
    unmatched = []'''

EDITS = [
    ("helpers", "def collect(store: Any, seg_id: str, entry: dict[str, Any] | None, origin_path: Path,", HELPERS),
    ("window", "    scripts = scripts_of(entry)\n    unmatched = []", WINDOW),
    ("answer", '            "more": max(0, len(picked) - MAX_ROUNDS)}',
     '            "more": max(0, len(picked) - MAX_ROUNDS),\n'
     '            "went_elsewhere": went_elsewhere,  # [tree-heard]\n'
     '            "window": [w0, w1] if w0 and w1 > w0 else None}'),
]


def load(root: Path) -> tuple[Path, str, bool]:
    path = root / TARGET
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return path, raw.replace("\r\n", "\n"), crlf


def check(root: Path) -> tuple[int, list[str]]:
    try:
        _p, text, _c = load(root)
    except OSError as exc:
        return 1, ["cannot read %s: %s" % (TARGET, exc)]
    if MARKER in text:
        return 2, ["already applied"]
    missing = [name for name, anchor, _new in EDITS if text.count(anchor) != 1]
    return (1, ["anchor %s: found %d" % (n, text.count(a)) for n, a, _ in EDITS if n in missing]) if missing else (0, [])


def apply(root: Path) -> int:
    code, why = check(root)
    if code != 0:
        return code
    path, text, crlf = load(root)
    for _name, anchor, new in EDITS:
        assert text.count(anchor) == 1
        text = text.replace(anchor, new, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tree_heard.")
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__.strip().splitlines()[0])
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
