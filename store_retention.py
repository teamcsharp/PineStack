"""Retention for the stores that had none (2026-09-10).

WHAT WAS MEASURED, on a station that had just gone silent:

  the event loop frozen 153s in every 600 - 25% of the time - 46 stalls,
  worst 18.5s, and the named frames were all reads and writes against
  three databases that had grown to 7.5 GB between them:

    lab_traces.record          2,824 MB   385,632 rows    7.3 KB/row
    review_events.body         1,728 MB    26,930 rows   64.0 KB/row
    station_flow.events.body   1,496 MB 1,648,672 rows    0.9 KB/row
    line_reviews.context       1,000 MB    18,889 rows   53.0 KB/row

  and the oldest row in any of them was THREE DAYS OLD. Nothing in
  rejection_lab.py, line_review.py or station_flow.py has ever deleted
  anything, so the station accumulates about two and a half gigabytes a
  day of prompts, traces and evidence and then reads across it on the
  hot path. That is the cost: not one slow query, a working set that has
  outgrown the machine.

HOW THIS DELETES, and why it matters more than what it deletes. A single
`DELETE FROM lab_traces WHERE at < ?` over three hundred thousand rows
holds the write lock for as long as it takes, and the stall it causes
while running is the exact problem it exists to fix. So every sweep here
works in small batches with a wall-clock budget, commits each batch, and
stops when the budget is spent - it will simply come round again. A sweep
that has to be scheduled for a quiet hour is a sweep that never runs.

WHAT IS NEVER TOUCHED. A line review the operator has not answered yet is
their queue, not history: `review_status='pending'` is excluded from every
rule below, whatever its age. The same instinct as the retirement desk -
finished work can go, work waiting on a person cannot.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

# Hours of evidence kept. Short on purpose: at the measured write rate a
# day of traces is about a gigabyte, so anything generous here is a
# decision to keep the loop starved.
KEEP_TRACE_HOURS = float(os.getenv("PINE_KEEP_TRACE_HOURS", "36"))
KEEP_EVENT_HOURS = float(os.getenv("PINE_KEEP_EVENT_HOURS", "36"))
# The flow journal has no timestamp column at all - the time lives inside
# the JSON body - so it is trimmed by row count instead.
KEEP_FLOW_ROWS = int(os.getenv("PINE_KEEP_FLOW_ROWS", "300000"))
# A resolved review keeps its row (the decision is the record) and loses
# its 53 KB of prompt context, which nothing reads once it is answered.
BLANK_CONTEXT_HOURS = float(os.getenv("PINE_BLANK_CONTEXT_HOURS", "24"))

BATCH = 500                     # rows per transaction
BUDGET = 4.0                    # seconds per table per sweep


def _open(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5.0)
    db.execute("PRAGMA busy_timeout=4000")
    return db


def _spend(db: sqlite3.Connection, sql: str, params: tuple,
           budget: float) -> int:
    """Run one batched statement until it stops matching or time is up."""
    done = 0
    stop = time.monotonic() + max(0.5, budget)
    while time.monotonic() < stop:
        cur = db.execute(sql, params)
        db.commit()
        if not cur.rowcount:
            break
        done += cur.rowcount
    return done


def prune_by_age(path: str, table: str, column: str, hours: float,
                 budget: float = BUDGET, extra: str = "") -> int:
    """Delete rows older than `hours`, in batches, within a budget."""
    if not os.path.exists(path):
        return 0
    cutoff = time.time() - max(1.0, hours) * 3600.0
    where = "%s < ?" % column + ((" AND " + extra) if extra else "")
    sql = ("DELETE FROM %s WHERE rowid IN "
           "(SELECT rowid FROM %s WHERE %s LIMIT %d)"
           % (table, table, where, BATCH))
    try:
        with _open(path) as db:
            return _spend(db, sql, (cutoff,), budget)
    except Exception:                              # noqa: BLE001
        return 0                # maintenance never breaks the station


def prune_keep_newest(path: str, table: str, key: str, keep: int,
                      budget: float = BUDGET) -> int:
    """Keep the newest `keep` rows by `key`; delete the rest in batches."""
    if not os.path.exists(path):
        return 0
    sql = ("DELETE FROM %s WHERE %s IN "
           "(SELECT %s FROM %s ORDER BY %s ASC LIMIT %d)"
           % (table, key, key, table, key, BATCH))
    try:
        with _open(path) as db:
            floor = db.execute(
                "SELECT %s FROM %s ORDER BY %s DESC LIMIT 1 OFFSET ?"
                % (key, table, key), (max(0, keep - 1),)).fetchone()
            if not floor:
                return 0        # fewer rows than the ceiling; nothing to do
            guarded = sql.replace(
                "ORDER BY %s ASC" % key,
                "WHERE %s < %d ORDER BY %s ASC" % (key, int(floor[0]), key))
            return _spend(db, guarded, (), budget)
    except Exception:                              # noqa: BLE001
        return 0


def blank_column(path: str, table: str, column: str, stamp: str,
                 hours: float, extra: str = "",
                 budget: float = BUDGET) -> int:
    """Empty a heavy column on rows that are finished with, keeping the row.

    Used for a resolved review's `context`: the decision is the record and
    is kept forever; the prompt it was made against is 53 KB of evidence
    nobody reads again."""
    if not os.path.exists(path):
        return 0
    cutoff = time.time() - max(1.0, hours) * 3600.0
    where = ("%s < ? AND %s != '' AND %s != '{}'" % (stamp, column, column)
             + ((" AND " + extra) if extra else ""))
    sql = ("UPDATE %s SET %s='{}' WHERE rowid IN "
           "(SELECT rowid FROM %s WHERE %s LIMIT %d)"
           % (table, column, table, where, BATCH))
    try:
        with _open(path) as db:
            return _spend(db, sql, (cutoff,), budget)
    except Exception:                              # noqa: BLE001
        return 0


def retention_sweep(data_dir: str) -> dict[str, Any]:
    """One pass over every store that grows without bound."""
    started = time.monotonic()
    out: dict[str, Any] = {"at": time.time(), "removed": {}}
    join = lambda name: os.path.join(str(data_dir), name)   # noqa: E731

    out["removed"]["lab_traces"] = prune_by_age(
        join("rejection_lab.sqlite3"), "lab_traces", "at", KEEP_TRACE_HOURS)
    out["removed"]["review_events"] = prune_by_age(
        join("line_review.sqlite3"), "review_events", "at", KEEP_EVENT_HOURS)
    # Resolved reviews only. A pending one is the operator's queue.
    out["removed"]["review_context_blanked"] = blank_column(
        join("line_review.sqlite3"), "line_reviews", "context", "last_at",
        BLANK_CONTEXT_HOURS, extra="review_status != 'pending'")
    out["removed"]["flow_events"] = prune_keep_newest(
        join("station_flow.sqlite3"), "events", "id", KEEP_FLOW_ROWS)

    out["seconds"] = round(time.monotonic() - started, 2)
    total = sum(int(v or 0) for v in out["removed"].values())
    out["total"] = total
    out["say"] = ("%d row(s) cleared in %.1fs - traces %d, events %d, "
                  "flow %d, contexts emptied %d"
                  % (total, out["seconds"],
                     out["removed"]["lab_traces"],
                     out["removed"]["review_events"],
                     out["removed"]["flow_events"],
                     out["removed"]["review_context_blanked"])
                  if total else "nothing was old enough to clear")
    return out


def store_sizes(data_dir: str) -> dict[str, float]:
    """Megabytes per store, for the report."""
    out: dict[str, float] = {}
    for name in ("rejection_lab", "line_review", "station_flow",
                 "prompt_learning", "rhyme_assistance", "system2"):
        path = os.path.join(str(data_dir), name + ".sqlite3")
        try:
            out[name] = round(os.path.getsize(path) / 1048576.0, 1)
        except OSError:
            continue
    return out
