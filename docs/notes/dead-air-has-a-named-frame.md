---
name: dead-air-has-a-named-frame
description: "data/gap_log.jsonl carries cause + stall_top - a per-FRAME attribution of who blocked the event loop. Baseline 858 s/h of stall-attributed dead air; sfx_all() walked the CIFS sample library per pick"
metadata:
  node_type: memory
  type: project
---

2026-09-12 (#1265). The operator: *"I don't know what it's doing sitting
on this blank moment here."* **`data/gap_log.jsonl` answers that question
directly and I did not know it.** Every gap row carries:

* `seconds` — how long the hole was
* `cause` — `event-loop stall` / `mid-round hole` / `page join` /
  `pantry miss on a banked round` / `round turnover` / `page render (live)`
* `stall_s` — how much of it was the loop actually blocked
* **`stall_top` — the FRAMES that were running while it was blocked**

Measured baseline, six hours:

    131 gaps >=8s attributed to `event-loop stall` = 5,394s
    an hour and a half of blank in six hours
    stall_s median 18.1s, p90 35.7s, worst 67.8s
    == 858 s/h ==   <- the number to beat

Ranked by `stall_top`, top was **`sfx_id` — 38 stacks, 900s**. `sfx_id`
is a sha1 of a string; it is not slow. **It was the innermost frame while
a caller walked the whole sample library hashing every path** —
`sfx_all()`, over CIFS, 3,588 files, on the air path. Its own docstring
had said so since it was written: *"globbed per pick, no index... add a
cache when someone points this at a library."* #1199 built exactly that
cache (`sfx_pool_cached`) for the SFX desk and the air path never used
it — [[which-pile-a-road-lives-on]]'s shape again: the fix exists and is
bypassed.

## The part I got wrong

I reported a 42% cut from a **25-minute window that contained a
restart**. Over a clean 30 minutes it was 804 s/h against 858 — barely
moved. **Never quote a rate from a window that contains a restart, and
never from one shorter than the thing being measured.**

And two of the remaining walks were MINE: a guard with a 2-second memo
read from the round chooser and both SFX roads, and a census with a
3-second memo riding in `dj_state()` which every panel polls. Up to
thirty shelf walks a minute. `/api/cupboard/unheard` timed out past 25s.
**A memo TTL must be set by how fast the answer can change, not by how
fresh it would be nice to have** — an entry lasts minutes, unheard stock
has waited days.

    /api/manager/breakin        9.42s  ->  0.33s
    /api/cupboard/unheard      >25s    ->  0.01s
    /api/orchestrator/lessons  >120s   ->  0.04s

## How to apply

1. Read `gap_log.jsonl`, group `>=8s` rows by `cause`, then rank
   `stall_top` frames by count and summed `stall_s`. That is the whole
   diagnosis — no py-spy needed ([[event-loop-starvation-watchdog]]).
2. The innermost frame is usually cheap. **Ask who is CALLING it in a
   loop**, and over what store.
3. Fix by indexing at the shared function, not per call site — it covers
   the callers the stacks could not name.
4. Re-measure hour-to-hour, restart-free.

Known remaining frames after the cuts: `prompt_learning_observe`,
`pantry_get`, `_read_gpu_temp`, `crystal_force`,
`_system2_acknowledge_row`, `schedule_read`, `crystal_learning_note` —
10-35s each, all the same shape.
