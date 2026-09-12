---
name: running-order-vs-clocks
description: "Why scheduled segments don't air - the plot term in the viability signature, the 25s quiet hatch, the 3-road rescue door, and banter living in the larder"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-10T20:55:38.978Z
---

2026-09-10 (#1160-#1165). "The station isn't taking place according to the
scheduled segments" turned out to be five separate faults, each of which
alone empties an entry. Measured, not guessed — `/api/director/why/<kind>`
now carries a **`census`** naming the FIRST test each held row fails, which
is the tool to reach for before reading any of this logic again.

**1. A storyline orphaned the whole cupboard.** `_larder_profile_signature`
carries `plot: [id, ACT NUMBER]`. `profile_compatible` compared it, so
switching a plot on made every banked round on every road non-viable at
once (167 across manager/gallery/caller → pool of 0), and a three-act hour
did it again every 20 minutes. This is the "doing well then suddenly
panicking". Fixed: `plot` now joins `turns` as written-down-but-not-
disqualifying; the preference lives in `_ready_shelf_row`, which takes an
in-plot round first. **Never put a churning value in that signature.**

**2. Quiet air outranked the sheet.** `clock_may_air`'s hatch —
`if time.time() - heard > CLOCK_QUIET_FLOOR (25s): return "the air is quiet"`
— sat ABOVE the running-order test, so on a station that is quiet this
often every clock was almost always exempt and whichever timer ticked
first took the entry. Now: while the entry on air has something finished
standing by (`entry_road_ready`), other clocks wait. `CLOCK_HOLD_MOST`
(15 min) release untouched.

**3. The cupboard was never tried before the emergency host.**
`torrent_force_banter` had two rungs — banter larder, then `continuity_air`
— so an empty larder reached the filler in ONE step past 74 finished
rounds. `dead_air_watch` never reached `dead_air_rescue` either, because
its early-return guard includes "anything rendered in the last 45s" and
the thing rendering is the emergency host itself. Both fixed; a render
still blocks a STRIKE and the needle-drop, not the cupboard.

**4. `_ready_shelf_row` serves only `("gallery","news","manager")`.**
Everything else returns None, so **caller / banter / recap rounds can never
be rescued** however many are ready. `RESCUE_ROADS_OPEN` now names the
openable roads and the count/attempt/endpoint all read it. Giving calls a
rescue transport is real work (a call is intro + conversation + sign-off,
not one round for `_banter_air`) — still open.

**5. Banter lives in `_LARDER`, not `_SHELF`.** `dialogue_stock_items`
always knew; `director_road_stock` and `dead_air_stock` both guessed
`_SHELF` and reported "nothing has been written for this road at all"
against 69 rows / 64 recorded. One door now: **`road_source(kind)`**.

Still open after all five: the manager had still not aired by 15:52. The
`/api/director` view attributes aired lines to entries **by timestamp
window**, not by what the engine believed was on — so a call filed under a
manager entry may mean the engine thought a caller entry was current.
Instrument that attribution before concluding anything else.

See [dead-air-and-staleness-measurement](dead-air-and-staleness-measurement.md), [orchestrator-dead-wiring](orchestrator-dead-wiring.md),
[hour-contract-two-truths](hour-contract-two-truths.md), [parallel-session-commitment-ledger](parallel-session-commitment-ledger.md).
