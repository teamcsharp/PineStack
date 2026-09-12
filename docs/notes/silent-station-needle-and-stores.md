---
name: silent-station-needle-and-stores
description: "2026-09-10: why the station went silent (unbounded await _record_talk pinned the needle 21 min) and why the loop was frozen 25% of the time (7.5 GB of store with no retention + a lock-taking hot read)"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-10T15:50:33.102Z
---

**THE SILENCE, and how to recognise it again.** The needle was pinned on a
218.9-second track with `elapsed 1414` / `remaining 0.0` for twenty-one
minutes. Everything reported healthy: `/api/dj` said `playing: true`,
`/api/pinebox/diagnose` passed all nine checks, 35,755 tracks were queued.
Dialogue still aired in sparse bursts because dialogue rounds are their own
tasks; the MUSIC did not, so every gap between rounds became dead air and the
listener heard a dead station.

**Cause: `await _record_talk(...)` in the radio loop was UNBOUNDED**, and it
runs before the next record goes on air. `_record_talk` swallows
`WritingDeferred` (#1082) - the yield it was written for - but cannot swallow a
SLOW one: measured the same hour, xtts took **63,458 ms for a 275-character
clip**, and the model lane was 74% tint with 70% of all call time WAITING. A
render queued behind that never returns and never raises. Fixed:
`RECORD_TALK_BUDGET` (40s, `PINE_RECORD_TALK_BUDGET`), talk runs as a shielded
task, the needle drops when the budget is spent, and the talk is NOT cancelled -
it finishes into the shelf behind the music (`_talk_late` retrieves the
exception). **Signature to look for: `elapsed` far past the track length with
`remaining 0.0` and `playing: true`.** `/api/dj/next` does NOT unstick it.

**THE LOOP WAS FROZEN 153s IN EVERY 600 (25%)** - 46 stalls, worst 18.5s.
Two causes, both fixed:

1. **7.5 GB of store with NO RETENTION ANYWHERE.** Nothing in
   `rejection_lab.py`, `line_review.py` or `station_flow.py` had ever deleted a
   row, and the oldest row in any of them was THREE DAYS OLD - about 2.5 GB/day
   of prompts and traces, read across on the hot path.
   ```
   lab_traces.record          2,824 MB   385,632 rows    7.3 KB/row
   review_events.body         1,728 MB    26,930 rows   64.0 KB/row
   station_flow.events.body   1,496 MB 1,648,672 rows    0.9 KB/row
   line_reviews.context       1,000 MB    18,889 rows   53.0 KB/row
   ```
   New `store_retention.py` + `retention_clock()` (every 60s) + 
   `/api/maintenance/stores`, `/api/maintenance/retention`. Batches of 500 with
   a 4s budget per table - **a single big DELETE would hold the write lock and
   cause the very stall it fixes**. `station_flow.events` has NO timestamp
   column (time is inside the JSON body), so it is trimmed by row id from the
   old end. **NEVER deleted: any `line_reviews` ROW, and anything
   `review_status='pending'`** - that is the operator's queue. A resolved
   review keeps its row and loses only its context blob.

2. **The 18.5s frame was a LOCK, not a query.** `preference_examples` reads an
   IN-MEMORY list and took the store lock to do it, which a worker holds while
   writing to a 2.9 GB database - and it is on the writing hot path
   (`line_review_guidance` builds it into every round's prompt). Now lock-free,
   the `policy()` argument from #1070. `_refresh_preferences` had to stop
   appending in place and rebind the finished list once, or a lock-free reader
   could see a half-built list.

Also: `banned_words` was memoized against a `stat()` it still made on EVERY
call (#1156 fixed the read, not the stat), and `strip_banned` runs per line -
`dj_pending` scrubs every pending row per panel poll. `BANNED_WORDS_TTL = 2.0`.

**Measured after:** stalls 46 → 20, stalled 153.0s → 59.2s, worst 18.5s → 8.4s,
`line_review_preferences` gone from the top frames. Retention converging live
with the show on air: lab_traces 385,632 → 185,719, review_events 26,930 →
10,434, flow 1,648,672 → 849,464, **line_reviews 18,889 → 18,911 with all 326
pending intact**. Air: 163 lines/30 min, longest gap 1.9 min (was 5.9).

**File sizes do NOT fall** - SQLite frees pages for reuse, not to disk. The
working set shrinks, which is what the loop feels. Reclaiming disk needs
`VACUUM`, which locks the whole database and belongs in a deploy window.

**THE ORCHESTRATOR STOPS DEAD IF A RESERVATION IS STRANDED (2026-09-10, later).**
Second silence report the same day. `/api/system2/status` was answering **HTTP
500**: every `refresh()` raised out of `plan_hour` with
`System2Conflict('An active performance must finish or remain on its original
plan.')`, so there was NO PLAN, so no allocations, so nothing dispatched. The
director's room read all twenty entries "unplanned" while the shelf held
hundreds of finished rounds. **Symptom to recognise: status 500 + every entry
"unplanned" + music playing fine.**

`plan_hour` (system2.py ~312) refuses to re-plan an hour holding a reservation
in `playing`/`suspended` - right - but never checked whether the LEASE was
alive. A round airing when the process dies leaves its reservation `playing`
under a lease nobody renews, and that hour can never be planned again.
Measured: **13 reservations in `playing`, every one past its lease, oldest two
days old**, one on the hour that was on air. It only surfaced because changing
the schedule changed the hour's config hash, which is what makes `plan_hour`
try to re-plan at all. #1074 fixed this exact shape for JOBS and left
reservations with the same wound. Fixed: the occupied test now requires a live
lease, plus `reclaim_reservations()` at startup beside `reclaim_jobs()`.
After: playing 13 → 0, status 200, 2 hours planned, **13 of 20 entries planned
with scripts bound** (two 11-turn calls, two manager memos).

**A 4,799-SECOND TRACK CAN OWN THE HOUR.** `track_may_cut` (#840) refuses any
automatic cut while a record has time left. Found an 80-minute ambient piece on
air with 63 min to run, holding the whole running order behind it. Library
measured over 348 records/24h: median 232s, p90 392s, only FIVE over 600s. So
`RECORD_AIR_MOST` (600s, `PINE_RECORD_AIR_MOST`) lets ~99% finish untouched and
reaches only the occupier.

**THE CUPBOARD CAN BE ORPHANED BY A DIAL.** `_larder_profile_signature()`
included the TURN RANGE (`banter_min/max_lines`). Thinning the running order
moved those dials → moved the signature → **57 of 72 finished, tinted, recorded
calls became non-viable in one step**; five signatures were live on the shelf at
once ([8,11], [16,22], [11,11], [6,6]). Fixed with `profile_compatible()`, which
ignores the turn range and nothing else. **Do NOT fix this by removing `turns`
from the signature** - I tried; stored rows all carry it, so the computed value
then matches nothing and the pool goes to ZERO. The stored strings are the fixed
point; the comparison is what can be taught.

**Calls now repeat** (`caller` added to `SHELF_REUSABLE`, `CALLER_AIRINGS = 2`,
shortest leash of any road) - the single-use rule was buying a silent phone: 63
of 72 spent, 86% of fresh attempts failing. And `repeat_safe` blocked ALL 64
aired calls, 58 on the bare word `live`, because the stock greeting is "Pine Box
FM, you're live; go ahead" - now only `live from|at|outside|on the scene`.

**`/api/director/why/{road}` is the tool to reach for.** It joins what the road
holds, the call sheet's verdict, and - the part that ends the guesswork - THE
BINDER'S OWN POOL (`dialogue_stock_items`). Chasing why a road with 64 finished
recordings bound nothing cost an hour of reading `_viable`/`_tinted`/`_audio`/
profile/innings one at a time and guessing. **Ask the binder; do not re-derive
it.**

Related: [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md), [pulse-library-and-firmware-down](pulse-library-and-firmware-down.md),
[render-is-slower-than-speech](render-is-slower-than-speech.md), [director-room-and-seeded-conversation](director-room-and-seeded-conversation.md).
