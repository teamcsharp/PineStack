---
name: orchestrator-judgment-book
description: "#1150: pause-honest demand clocks (larder bleed fix), the judgment book (operator answers → bounded road factors + lessons), pause workshop, and the 🕸 logic graph"
metadata: 
  node_type: memory
  type: project
  originSessionId: 21948932-a31d-4dd3-9e25-119ba26127d8
  modified: 2026-08-27T20:42:20.490Z
---

**"Falling behind while paused" (diagnosed by 3-agent scan + live probes,
2026-08-27, commit #1150):** three wall clocks ran through the pause —
`slot_read()`'s room/lead (NO pause branch; verdict walked to "at risk"
on time alone), the larder freshness prune (no unaired protection;
**measured ~24s/min of held banter bleeding** while nothing aired), and
the pause-funded retint wiping SHORT roads' finished audio before slow
re-render. `hour_needs` "owed" was never the problem — it is schedule-
derived and frozen; only "held" was being eaten.

**#1150 invariants (do not undo):**
- `slot_read` verdict is `"banking"` while paused (shortfall list stays
  honest; `slot_board().behind` no longer fires on pause time).
- Larder prune keeps `row_unaired` rounds whatever their age while
  paused; `radio_pause_set(False)` steps every `_LARDER[].at` and news
  `prep_news_at` forward by the sleep — freshness counts AIR time.
- `retint_shelf`/`retint_one` never tint a row with finished audio when
  its road is in `hour_short_kinds()` (covered roads polish, short bank).
- `schedule_jammed` returns "" while paused; `schedule_adherence.now.
  through` uses `paused_sched_elapsed` while paused.
- `cupboard_rotate` pops pantry keys only outside `pantry_spoken_for()`.

**The judgment book** (`data/judgment_ledger.json`, pattern-A store):
every `orch_answer` pick (and every #1081 decide-alone, marked
`alone: True` at HALF weight) lands with its situation. Distils to
`coord_judgment_factor(road)` (bounded 0.5–2.0), multiplied beside
`coord_learning_factor` at BOTH sites — `coord_plan` want_seconds+sort
and `prep_plan` rate/need — plus `judgment_lesson(road)` (operator's
words). `orch_apply` verb `judgment:{more|less|ease|drop}:{road}`;
`judgment_move()` is the dial; met hours decay the factor 10% toward
1.0 (`judgment_hour_close`); a disproved judgment (factor>1.15,
attainment<0.6) raises an evidence-carrying re-ask (`judgment_reask`,
topic `judgment_<road>`). **Pause workshop**: coordinator's 120s branch
→ `workshop_tick()` — paused + covered + 30min throttle → regenerate_job
on the oldest owned banter round, `operator_note=judgment_lesson`.

**The graph**: `GET /api/orchestrator/logic` (read-auth; composes
hour_needs+cover, plan tasks, `_HOUR_LEARNING`, judgment roads, slot
verdicts, last `_HOURS` scorecard, book tail). Panel: 🕸 Orchestrator in
the tile registry → `orchLogicPanel()` — three.js lanes per road through
DEMAND→STOCK→JUDGMENT→LEARNING→PLAN→LAST HOUR, raycast → rail with the
dial (POST `/api/orchestrator/judgment` {road, move}). NOTE: the
learning surface (`/api/coordinator/hourly`) previously had NO panel
consumer — gallery was carrying a 2.50× miss premium invisibly.

Verified live: slot verdicts `banking`/behind=False while paused; banter
held FLAT after the fix (was bleeding); dial POST → factor 1.2 →
appears in plan tasks as `judgment_factor`. See
[event-loop-starvation-watchdog](event-loop-starvation-watchdog.md), [hour-contract-two-truths](hour-contract-two-truths.md),
[orchestrator-dead-wiring](orchestrator-dead-wiring.md), [floor-and-paced-air](floor-and-paced-air.md).
