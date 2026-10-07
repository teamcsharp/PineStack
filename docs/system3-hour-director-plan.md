# Moving System 2 under System 3: the Hour Director plan (draft, 2026-10-06)

The operator: "We need to migrate all System 2 systems over to System 3. The whole point of System 3 was to
remove all the systems from the rigidness of System 2 and put it under the roulette node system of System 3."

This is the inventory of what System 2 still owns on the air, what it is costing today (measured), and a
phased plan with gates. Decisions the operator must make are marked DECIDE.

## 1. What System 2 owns today (engine: system2, legacy_keepers: true, fallback: true)

| System 2 piece | Where | What it decides |
| --- | --- | --- |
| The clock | `system2_runtime.current_clock / _publish_clock`, `schedule_take()` | which entry of the hour is on the air now, published into `_RADIO.sched_*` |
| The hour plans | `system2.plan_hour`, `templates()` from the sheet | the slots of each hour for 6 hours ahead, each with a prep road (`kind`), minutes, a deadline, a brief |
| The inventory | `inventory()` -> `alt_candidates(kind)` | which banked rows are candidates (237 today, 108 ready) |
| Allocation (the binding) | the planner inside `plan_hour`, `/api/system2/binding` | which candidate is booked to which slot; today most talk entries carry 0 allocations (News, Gazette, Banter, Book Time), the fallback chain serves them |
| Dispatch | `system2_runtime.dispatch()` | resolves the booked candidate's takes, the fit test, the reservation, publication; refusals |
| Reservations and events | `system2.store` (sqlite), events `call_in` / `music_request` | leases on candidates, event slots with their own plans |
| Preparation jobs | `jobs` (100 pending today), 1 lane, `larder_prepare` calls | which round is written and voiced next, with a deadline; "already has its admitted station writers; this job remains owed" is this lane saturating |
| The dynamic segments bridge | `dynamic_segments_system2.py` (773 lines) | Book Time / supercut windows as System 2 slots and prepare jobs |
| The fallback | `fallback_due()` -> the legacy torrent chain | when System 2 has nothing staged, the old chain serves the entry read off System 2's clock |

Size: 5,159 lines across five modules, 23 call sites in app.py.

## 2. What it costs the broadcast (measured 2026-10-06)

- Book Time windows never reached their own door: System 2 publishes a window under its prep road (`kind:
  banter`, `dynamic_kind: book_time`) with 0 allocations; the fallback served banter and the segment's door
  ledger read 0 asks all afternoon. Patched at the fallback ([book-nodes-8]); the planner still cannot book
  a window's own parts.
- Two schedulers drive one voice engine: the kitchen's board (#855/#872/#1082) and System 2's prepare jobs
  both call `larder_prepare`; a part sat at 3 of 10 takes for an hour while the board recorded "recap,
  news, gallery, ad" first and System 2's one lane was owed.
- The binding is thin: 9 of 14 entries this hour carry no allocation, so the old chain still decides most
  of the hour - the sheet is nominally System 2's but the air is the legacy draw's.
- Rigid kinds: a slot's `kind` is a prep road, not a node; quotas, "stock before prose" and the jam rule
  argue with the sheet in code paths, not on a wheel.
- Churn: "Preparation job ownership changed" when a plan's revision moved (#1408), reservation conflicts
  (`System2Conflict`), an hour rebuilt per refresh.

## 3. What System 3 already has to take this over

- Roads, legs, tables and structures: every round's running order is a graph of nodes with dice
  (`system3_tables.DEFAULT_ROAD_STRUCTURES`, the register); per-ENTRY structures and micro-exchanges
  ([hour-flow] today: `road@slot_id`).
- The dice and the pools (`s3_choice`, `s3_weighted`, `s3_pool`, `s3_chance`), the rolodex, the flow ledger
  (`s3_flow`, `/api/flow-ledger`), the conversation director (#1386).
- The cupboard with the lifecycle (mode "air"), bank-first transports (`_ready_shelf_air` with a pick, the
  larder transport), readiness (`dialogue_row_ready`), the segment runtime's door with its ledger.
- The deferred writer and the kitchen (the board with its costs and windows).

## 4. The plan: the Hour Director as System 3 nodes

Phase 0 - make the ledger honest (small, now)
- Every door writes why: the segment door does ([book-nodes-7]); add the same ledger to the chain's round
  decision (sheet kind -> policy -> served kind -> why) on the hour's record, readable after the fact.
- Gate: an hour can be read back entry by entry: what was named, what aired, why.

Phase 1 - the hour as a System 3 road
- An hour is a structure: legs = the sheet's entries in order, each leg's act = the entry's standing
  instruction, its seat = the road (news, gallery, caller, book_time, ...), its minutes = the leg's room.
  The existing sheet editor and [hour-flow] edit it; the dynamic windows are legs like any other.
- The "which entry next when the sheet is silent" and the quota pressure become DRAWS on the hour road
  (a QUOTA family: behind-pace roads weighted up), not overrides in the chain. The jam rule becomes a
  chance roll with a dial. Every exception is a roll (the operator's standing rule).
- Gate: the hour road plans the same hour the sheet names today (parity test on 24 recorded hours).

Phase 2 - allocation as a draw over the cupboard
- Replace the planner's booking with System 3 picks: for each leg, the candidates are the cupboard's ready
  rows compatible with the entry (the lifecycle's own rule, with a segment's parts fitting their own
  window); the pick is a weighted draw (age, deadline, no-repeat, bank.reair) through `s3_weighted`, noted
  on the rolodex; nothing is reserved ahead - the door takes the pick when the leg comes round
  (`_ready_shelf_air` with the pick, the transport that exists). Refusals go to the flow ledger.
- Gate: no entry with a ready compatible row airs cover; adherence (#937) rises above today's figure.

Phase 3 - one kitchen, one queue, driven by the hour road
- System 2's prepare jobs retire. The kitchen's board reads the hour road's upcoming legs (the needs, with
  deadlines) and the dynamic segments' own requests; one writer queue with System 3's deferred writer,
  priorities = time to the leg; the voice engine's room is the board's (prep_should_stop) only.
  `legacy_keepers` becomes the only keepers.
- DECIDE: writer lanes - one Ollama slot today; a second lane for banked work changes the box's heat
  (#1285) and the request book; keep one lane with priorities first?
- Gate: a Book Time part written 20 min before its window is voiced before it; the "remains owed" line
  disappears from the ring at normal load.

Phase 4 - events as interject nodes
- Call-ins and music requests (System 2 events with reservations) become interject nodes on the hour road
  (the design in [interject-road-design]: cut-ins are graph nodes, holding lines -> rolled banter). The
  reservation becomes a lease on the cupboard row (the lifecycle already has leases).
- Gate: a listener's call-in airs inside its deadline through the interject node, with its ledger row.

Phase 5 - the switch
- `engine: system3` beside `legacy` and `system2`, with the same `fallback` to the legacy chain; a per-hour
  canary first (odd hours on System 3, even on System 2) with the ledgers compared: adherence, dead air
  (gap_log), repeats (airings), Book Time windows aired, cover rounds.
- DECIDE: when the canary holds for a day, flip the default and leave System 2 readable (its store stays as
  history) for a week before its modules are retired.

## 5. What stays as it is

The cupboard, the lifecycle, the kitchen's board, the tint room (already a System 3 rewrite pass), the
dynamic segments runtime (its door, its parts, its roads), the register and the flow ledger, the desk's
windows (System 3, hour-flow, the blocked book) - they are the unified system; System 2 is what is left
beside it.

## 6. Questions for the operator (DECIDE)

1. Order: the clock and allocation first (phases 1-2, the biggest effect on what airs), or the kitchen
   first (phase 3, the biggest effect on what gets made in time)?
2. The hour road's editor: the sheet editor stays the place the hour is written, with [hour-flow] for a leg's
   inner shape - or does the hour move into the System 3 window entirely?
3. Writer lanes: one lane with priorities, or a second lane for banked work?
4. The canary: odd/even hours, or a whole day on System 3 with the fallback armed?

## 7. The operator's decisions (2026-10-06, 18:20 CST)

1. **Both as one build**: the clock, the booking and the kitchen move together and switch at once.
2. **The hour moves into the System 3 window entirely**: the sheet editor becomes a System 3 system (the hour as a
   road of legs, the leg's inner shape through the hour-flow editor, the hour's own dice as tables).
3. **Writer lanes are dynamic**: one lane most of the time; a second lane when no H3 task is processing and it helps
   the broadcast stay ahead and keep its spontaneity.
4. **The canary is a whole day on System 3 with the fallback armed.**

## 8. The build (three waves in parallel, one switch)

- **Wave G - the Hour Director (station):** `system3_hour.py`; `engine: system3` in the same config file (System 2
  stands down, the fallback stays); the legacy clock keeps the time (`schedule_take()`'s own branch publishes
  `_RADIO.sched_*` with the sheet's kinds, so a Book Time window is `book_time`); the hour's own dice as System 3
  tables (family HOUR: the draw when the sheet is silent, the quota pressure, the jam chance); the booking as a
  draw over the cupboard's ready compatible rows (`s3_weighted("hour.book")`), taken by the doors that exist
  (`_ready_shelf_air` with a pick, the segment door, the produced-ad door, the record pin); the round ledger
  (`GET /api/system3/hour`: named, policy, booked, served, why); the chain asks the director where it asks
  System 2 today.
- **Wave H - one kitchen:** System 2's prepare jobs stand down under `system3`; the board's needs are the hour's
  upcoming legs AND the dynamic windows' unvoiced parts (cost = the chunks left, deadline = the window); the
  deferred writer's priority is time to the leg; the writer lanes dial: a second lane only while no H3 render is in
  flight and the pantry is short.
- **Wave I - the System 3 window's Hour tab (desk + tablet):** the hour as a road of legs (add, remove, move,
  minutes, the instruction), the leg's inner shape through PineHourFlow, the HOUR tables, the ledger view, the engine
  switch and fallback; the sheet's store stays the store (the schedule APIs), so the old sheet view keeps reading it.
- **The switch:** `engine: system3` for a whole day with the fallback armed; the ledgers compared (adherence, dead
  air, repeats, Book Time windows aired, cover rounds) before the default flips.
