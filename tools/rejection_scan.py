"""2026-09-10: what is actually sitting in the review queue, and why.

The panel says "N cut lines wait for your decision" and that is all it says.
Deciding on them needs to know what they have in common - a queue of 300 that
is really two faults repeated 150 times each is a settings problem, not 300
editorial judgements.

Run it inside the container so the read is consistent with the live writer:

    docker exec spark-agent python /app/tools/rejection_scan.py [--pending]
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
import time

DB = "/app/data/line_review.sqlite3"


def reasons_of(raw):
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        got = [str(raw or "")]
    return [str(x) for x in (got or ["(none given)"])]


def main():
    only_pending = "--pending" in sys.argv or len(sys.argv) == 1
    db = sqlite3.connect(DB)
    where = "where review_status = 'pending'" if only_pending else ""
    rows = db.execute(
        "select gate, reasons, technical, disposition, occurrences, "
        "first_at, last_at, candidate from line_reviews " + where).fetchall()
    print(f"{len(rows)} rows" + (" awaiting a decision" if only_pending else ""))
    if not rows:
        return
    gates = collections.Counter()
    faults = collections.Counter()
    tech = 0
    occ = 0
    ages = []
    now = time.time()
    for gate, reasons, technical, _disp, occurrences, first_at, last_at, _cand in rows:
        gates[str(gate)] += 1
        tech += int(technical or 0)
        occ += int(occurrences or 1)
        if last_at:
            ages.append(now - float(last_at))
        for one in reasons_of(reasons):
            faults[one[:64]] += 1
    print(f"  technical (a budget or parse failure, not an editorial call): {tech}")
    print(f"  total occurrences behind them: {occ}")
    if ages:
        ages.sort()
        print(f"  age of the newest: {ages[0] / 3600:.1f} h · "
              f"median {ages[len(ages) // 2] / 3600:.1f} h · "
              f"oldest {ages[-1] / 3600:.1f} h")
    print("  by gate: " + ", ".join(f"{k} {v}" for k, v in gates.most_common(8)))
    print("  what they failed:")
    for fault, n in faults.most_common(12):
        print(f"    {n:5d}  {fault}")
    # The question the operator actually has: is this a queue of judgements,
    # or one setting repeated?
    top = faults.most_common(1)
    if top and top[0][1] >= len(rows) * 0.4:
        print(f"\n  {top[0][1]} of {len(rows)} share ONE fault - this is a "
              "settings decision, not a queue of editorial calls.")


if __name__ == "__main__":
    main()
