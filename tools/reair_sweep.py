"""[s3-banks-roll] THE ONE-TIME SWEEP: every stored round the re-air gate retires.

    python3 tools/reair_sweep.py              # dry run: list them, write nothing
    python3 tools/reair_sweep.py --apply      # ...and mark them ineligible
    python3 tools/reair_sweep.py --json       # the list as JSON (dry run unless --apply)
        [--data DIR]  the station's data dir (default: data/ beside tools/)

The re-air gate (reair_gate.py) is asked before the re-air roulette ever
rolls: a round with copied turns (> 0.9 like an earlier turn of the same
round), an echo loop, a non_compliant verdict or turns the turnchain gate
flagged ([s3-turnchain], LIVE) never goes out again. The station asks it of
each round as a replay comes up; this asks it of every round stored NOW - the
larder, the prep shelf and the finished-call log - and, where the round names
its System 3 conversation, of that conversation as System 3 recorded it too
(its planned turns, its validation's verdict and echo loop, its own turn_gate
record, any observation of family GATE on it).

--apply writes ONE file, data/reair_ineligible.json - {mark key: why} - which
the station's gate reads within half a minute (its mtime). It never writes the
larder, the shelf, the call log or System 3's record: the running station owns
those and would write over any change. Marks are only ever added; to let a
round go out again, delete its key from that file.

Read-only everywhere else; System 3's record is opened read-only
(sqlite mode=ro). Run it on the host or in the container, niced.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import reair_gate  # noqa: E402

MARKS_NAME = "reair_ineligible.json"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _unpack(blob):
    if isinstance(blob, bytes):
        try:
            blob = zlib.decompress(blob)
        except Exception:  # noqa: BLE001
            pass
        blob = blob.decode("utf-8", "replace")
    return json.loads(blob or "{}")


def stored_rounds(data):
    """(kind, where, row) for every round the station keeps: the larder's
    banter, each prep-shelf road's rows, and the finished calls."""
    out = []
    larder = _load(os.path.join(data, "larder.json"), [])
    if isinstance(larder, dict):
        larder = larder.get("larder") or larder.get("rows") or []
    for i, e in enumerate(larder if isinstance(larder, list) else []):
        if isinstance(e, dict):
            out.append(("banter", "larder[%d]" % i, e))
    shelf = _load(os.path.join(data, "prep_shelf.json"), {})
    book = shelf.get("shelf") if isinstance(shelf, dict) and isinstance(shelf.get("shelf"), dict) else shelf
    for kind, rows in (book.items() if isinstance(book, dict) else []):
        for i, r in enumerate(rows if isinstance(rows, list) else []):
            if isinstance(r, dict):
                out.append((str(kind), "shelf:%s[%d]" % (kind, i), r))
    calls = _load(os.path.join(data, "call_log.json"), [])
    if isinstance(calls, dict):
        calls = calls.get("calls") or calls.get("rows") or []
    for r in calls if isinstance(calls, list) else []:
        if isinstance(r, dict) and isinstance(r.get("transcript"), list) and r.get("transcript"):
            out.append(("call", "call_log:%s" % str(r.get("id") or "?")[:24], r))
    return out


class Record:
    """System 3's record, read-only: a stored round's conversation as System
    3 kept it."""

    def __init__(self, path):
        self.db = None
        if os.path.exists(path):
            try:
                self.db = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
            except Exception:  # noqa: BLE001
                self.db = None

    def close(self):
        if self.db is not None:
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                pass
            self.db = None

    def why(self, cid):
        if not self.db or not cid:
            return ""
        try:
            got = self.db.execute("SELECT verdict, body FROM conversations WHERE id=?", (cid,)).fetchone()
        except Exception:  # noqa: BLE001
            return ""
        if not got:
            return ""
        verdict, blob = got
        if str(verdict or "") == "non_compliant":
            return "System 3's record: verdict non_compliant"
        try:
            body = _unpack(blob)
        except Exception:  # noqa: BLE001
            body = {}
        val = body.get("validation") or {}
        if str(val.get("verdict") or "") == "non_compliant":
            return "System 3's record: verdict non_compliant"
        echo = val.get("echo") or {}
        if echo.get("loop"):
            return "System 3's record: an echo loop (%d turns)" % len(echo.get("turns") or [])
        turns = [(str(t.get("speaker") or ""), str(t.get("text") or ""))
                 for t in (body.get("turns") or []) if isinstance(t, dict) and str(t.get("text") or "").strip()]
        copies = reair_gate.copied_turns(turns)
        if copies:
            return "System 3's record: copied turns - %d of its %d planned turns (%s)" % (
                len(copies), len(turns), ", ".join("t%02d = t%02d" % (i, j) for i, j in copies[:4]))
        got = reair_gate.turnchain_refusal(body.get("turn_gate"))
        if got:
            return "System 3's record: " + got
        # the turnchain gate's observations ([s3-turnchain], LIVE): every
        # catch, re-write, drop and trim is an event of family GATE on its node
        try:
            rows = self.db.execute("SELECT turn_id, body FROM events WHERE conversation_id=? "
                                   "AND family=?", (cid, "GATE")).fetchall()
        except Exception:  # noqa: BLE001
            rows = []
        stages = collections.Counter()
        for _turn_id, blob in rows:
            try:
                ev = _unpack(blob)
            except Exception:  # noqa: BLE001
                ev = {}
            stages[str(ev.get("stage") or "flagged").split(" ")[0] or "flagged"] += 1
        if stages:
            return "System 3's record: the turnchain gate flagged its turns - %d event(s) (%s)" % (
                sum(stages.values()), ", ".join("%s %d" % (k, n) for k, n in stages.most_common(4)))
        return ""


def sweep(data, marks=None):
    """[(kind, where, key, aired, why)] for every stored round the gate retires."""
    marks = marks or {}
    record = Record(os.path.join(data, "system3.sqlite3"))
    out = []
    try:
        for kind, where, row in stored_rounds(data):
            entry = reair_gate.entry_of(row)
            cid = str(reair_gate.stamp_of(row).get("conversation_id") or "")
            why = reair_gate.refusal(row, marks) or record.why(cid)
            if not why:
                continue
            keys = reair_gate.mark_keys(row, cid)
            aired = int(row.get("aired") or entry.get("aired") or 0) if kind != "call" else 1
            out.append({"kind": kind, "where": where, "key": keys[0] if keys else "", "keys": keys,
                        "conversation_id": cid, "aired": aired,
                        "age_h": round((time.time() - float(row.get("at") or row.get("ts")
                                                            or entry.get("at") or 0)) / 3600.0, 1),
                        "why": why})
    finally:
        record.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="mark them ineligible (data/%s)" % MARKS_NAME)
    ap.add_argument("--json", action="store_true", help="print the list as JSON")
    ap.add_argument("--data", default=os.path.join(ROOT, "data"), help="the station's data dir")
    args = ap.parse_args(argv)
    path = os.path.join(args.data, MARKS_NAME)
    marks = reair_gate.load_marks(path)
    found = sweep(args.data, {})
    if args.json:
        print(json.dumps(found, indent=1))
    else:
        by = collections.Counter((f["kind"], f["why"].split(" - ")[0].split(" (")[0][:60]) for f in found)
        print("%d stored round(s) the re-air gate retires (%d aired at least once):"
              % (len(found), sum(1 for f in found if f["aired"])))
        for (kind, reason), n in sorted(by.items(), key=lambda kv: (-kv[1], kv[0])):
            print("  %4d  %-8s %s" % (n, kind, reason))
        print("")
        for f in sorted(found, key=lambda f: (-f["aired"], f["kind"], f["where"]))[:200]:
            print("  %-8s aired %-2d %6.1fh  %-22s %s  %s"
                  % (f["kind"], f["aired"], f["age_h"], f["where"][:22], f["key"][:24], f["why"][:120]))
    if not args.apply:
        print("\ndry run - nothing written (--apply marks them in %s)" % path, file=sys.stderr)
        return 0
    added = 0
    now = round(time.time(), 3)
    for f in found:
        key = f["key"]
        if not key or key in marks:
            continue
        marks[key] = {"why": f["why"][:300], "kind": f["kind"], "aired": f["aired"], "at": now,
                      "conversation_id": f["conversation_id"] or None, "where": f["where"]}
        added += 1
    reair_gate.save_marks(path, marks)
    print("\nmarked %d round(s) ineligible (%d marks in %s)" % (added, len(marks), path), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
