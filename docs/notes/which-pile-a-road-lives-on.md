---
name: which-pile-a-road-lives-on
description: "Six readers disagreed about what the station holds - banter is the LARDER, ads/station IDs have no dialogue entry; use road_source and check director_why's census first"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-10T22:10:06.547Z
---

2026-09-10 (#1165/#1169). The single most productive question on this
station is **"is this reader looking at the right pile?"** Six separate
readers answered "that road is empty" about roads holding dozens of
finished rounds, and each one changed a real decision.

**TWO SHAPES OF THE SAME MISTAKE.**

1. **Banter is banked in `_LARDER`, everything else in `_SHELF`.**
   `dialogue_stock_items` has always known (`list(_LARDER) if road ==
   "banter" else ...`) and so does `prep_has_assigned_work`. Six others
   read `_SHELF["banter"]`, which is permanently empty. Now one door:
   **`road_source(kind)`**.

2. **An advert read and a station ID are ONE LINE** - words, a voice, a
   pantry key, no cast and no turns - so `dialogue_entry(row)` returns
   None for them. `director_road_stock` opened with `if entry is None:
   continue` and skipped every row on both roads: it reported the advert
   road at **0 rows** while the census counted **37 finished**. Ask it the
   census's way round: is there an entry, and if not, are there words?

**WHAT IT COST.** `cupboard_short` and `hour_needs` are the two numbers
that steer an overnight pause - `hour_needs` is what the offline banking
ask computes "furthest behind the three-hour goal" from. Both said
`banter have 0, short 8` against 69 rounds / 46 ready, so the pause was
spent deepening the deepest road on the station. Fixed, banter drops off
the shortfall list and the aim visibly changes: the lookahead log goes
from wanting banter to *"the running order wants track_talk, ad, caller,
news — recording those first"*.

**THE TOOL.** `/api/director/why/<kind>` now carries a **`census`** naming
the FIRST test each held row fails (`profile`, `off brief`, `expired`,
`phone contract`, `in pool, waiting on the tint`, `aired and out of
innings`, `READY`). Ask it before reading any inventory logic. When
`stock` and `census` disagree, `census` is the one written last and the
one that is right.

**MEASURED PAUSE OUTPUT** after the fixes: +615s of finished segment in
15.2 min = **2,421s of air banked per hour of pause**, 11.8 rounds/hour
(was measured at 3.3/hour). Callers and banter carry it.

**STILL OPEN, both real:**
- **81 recorded phone calls, 1 airable.** The rest are out of innings or
  resting on the 3-hour reuse leash - the largest block of finished work
  on the station, idle.
- **Station IDs: 0 held, floor 8, 3 seconds each.** Never named on the
  running order, so `hour_needs` owes them nothing and the planner ranks
  them last; the rota does reach them ("every road on the board has
  already been tried this pass") and `prep_station_id` returns False
  anyway with `drop_voice` set. Not chased further - they still air,
  written live at 3s.
- News is *correctly* not built ahead: `news_want_seconds()` returns 0
  outside the short horizon because bulletins go stale. Not a bug.

See [running-order-vs-clocks](running-order-vs-clocks.md), [hour-contract-two-truths](hour-contract-two-truths.md),
[pause-banking-and-records-underneath](pause-banking-and-records-underneath.md), [orchestrator-dead-wiring](orchestrator-dead-wiring.md).

## The pause trace, 2026-09-10 evening (#1170/#1171)

**The recording room is NOT throttled while paused — it is deliberately
accelerated.** Every pause branch OPENS a throttle: `pantry_window()`
returns "everything is a window", `prep_room_left()` >= 900s, 5 prep slots
instead of 3, **parallel booths exist only while paused**
(`recording_parallel_sitting`), slice >= 120s, the commitment gate lifted
(`_bank_all`), banter stand-down disabled, piper authorised. Paused != off:
`if not _RADIO.get("on")` is the only thing that stops it. So "is he using
the pause" is answered YES by design — measured 2,421s of finished segment
banked per hour.

**`repeat_safe` blocked 88 of 88 calls; 82 by the word "tonight".** Same
regex, same shape as the `live` bug fixed hours earlier (64 of 64, 58 by
one word). The list conflates three things: deixis inside the recording
(`right now`, `earlier` — true every airing, date nothing), a PART OF THE
DAY (`tonight` — dates it to *a* night, not *that* night), and genuinely
dating tokens (day names, `just played`, clock times — blocked forever).
Day-part words are now checked against the clock: 4 READY -> 80. **Check
the airing histogram before blaming an innings cap** — max was 3 against a
cap of 8.

**`_SHELF["recap"]` was WRITE-ONLY INVENTORY.** System2 wrote a recap every
hour (written, deep-tinted, recorded), `shelf_put` stamped every one
`off_brief` (the brief wants "earlier"/"this hour"/"we played" and the
scripts never contain one), and **no consumer exists** — `_ready_shelf_row`
serves only gallery/news/manager and there is no `shelf_take("recap")`
anywhere. 22 rows, 19 finished, 836s of rhymed audio that could never air,
keep-forever. The bill was one round of the DEEP LANE per hour, the
station's scarcest resource. `CANNOT_PREPARE`, `GAP_LIVE_ONLY`,
`PIPER_NEVER`, `BALLAST_NEVER` and the regenerate/recast endpoints all
already said recap cannot be prepared; **System2 appended it by hand in two
places** and now asks the host instead.

**Known, measured, not fixed:** `entry["chunks"] = len(plan) +
missing_voices` while `_round_chunks` DROPS voiceless rows, so `made` can
never reach `chunks` for a round with a voiceless seat — permanently
`partial`. Affects 1 row on this shelf.
