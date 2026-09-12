---
name: parallel-session-commitment-ledger
description: A second session edits app.py in parallel — dialogue_stock_items is now the ONE inventory; check for uncommitted growth before every edit
metadata: 
  node_type: memory
  type: project
  originSessionId: 972203c0-385f-4018-891c-5d597c362de3
  modified: 2026-09-10T13:28:37.578Z
---

As of 2026-08-24, `spark-agent/app.py` is edited by **two sessions at once**.
The other session built the four-hour FIFO commitment ledger:
`schedule_demand_entries` → `commitment_inventory_plan` →
`commitment_write_needed` / `committed_stock_ids`, with
**`dialogue_stock_items(road)` as the single common inventory** — its
docstring: *"none of those systems may count or work a different pile any
more."* It holds ad/gallery/news/track_talk stock in shapes the old raw
`_SHELF` walks don't recognise (track_talk pairs live per-record with
`intro`/`outro` side dicts; audio is summed per side).

**Why:** the file grew ~4,000 uncommitted lines between my commits (123k →
127k). Anchored patches failed or landed inside rewritten blocks; one of my
`hour_needs` branches was rewritten by them (better) while I was diagnosing
it. `git add -A` commits sweep their uncommitted work into my commits —
unavoidable in one file; say so in the commit body.

**2026-09-10, worse than "patches fail":** the other session **wrote back a
stale whole-file copy of app.py mid-session and silently REVERTED two of my
already-applied, already-compiled patch stages** (the file went 8,177,898 →
8,210,718 bytes and my `from html import escape` line was simply gone). It
also `docker restart`s the container out from under you (`exit=0`, not the
watchdog). Nothing errored; the routes were just missing from
`/openapi.json`. It changed size again between two reads seconds apart.

**How to apply:**
- `cp` the deployed file fresh **immediately before** every patch; anchor by
  symbol, verify counts, and treat a 0-match FAIL as "the other session
  rewrote it" — re-read before retrying.
- **Re-grep your own markers AFTER every restart and before every verify.**
  Keep a one-liner that counts each edit's anchor (`for m in ...; do grep -c`)
  and run it whenever something you know you built is not there. Write patch
  stages as idempotent, assert-guarded scripts kept on disk so any stage can
  simply be re-run — that is what made recovery cheap.
- Any reader of per-road stock (`hour_needs`, panels, ordering) must consult
  `dialogue_stock_items` (I wired a fallback in #1132); don't add new raw
  `_SHELF`/`_TRACK_TALK` walks.
- `commitment_write_needed` gates writes off the schedule clock — frozen
  while paused; #1131 bypasses it for `hour_short_kinds()` roads off air.
  Don't re-tighten without checking the pause case.
- `schedule_horizon_hours()` floors the operator's `prepare_hours` at **4h**
  ("the station guarantee") — owed/cap arithmetic uses 4 even when the dial
  says 3. Not a bug. See [orchestrator-dead-wiring](orchestrator-dead-wiring.md).
