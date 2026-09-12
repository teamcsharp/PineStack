---
name: the-memo-gets-through
description: "#1261/#1262 - entry_own_aired credited calls and stings to the manager; and a banked round has no turn boundary left to cut, so nothing can interrupt the floor here - the memo must CLAIM THE NEXT ROUND instead"
metadata:
  node_type: memory
  type: project
---

2026-09-12 (#1261/#1262). The operator: *"it's imperative that the
segments that we have play out... I want him capable of interrupting the
banter to say the messages"*, and *"the orchestrator is supposed to be
learning from each broadcast, each schedule, how to better schedule
things... it would be one thing if this was the first broadcast."*

## 1. The counter credited foreign content to the road

`entry_own_aired` asked `kind in (row["round"], row["kind"])`. **`round`
is the entry a line aired under; `kind` is what the line IS.** Measured
over six hours, under `round=manager`: 93 lines / 990 seconds, of which
only **42 lines / 539 seconds were the manager** — the rest were calls
(23), stings (18), the SFX Guy (9) and an advert.

**One sting inside his four minutes made the entry read as served**, so
#1189 never noted the debt and #1192 never asked for the floor. Cure:
`road_own_kinds(road)` — banter keeps `interject`, caller keeps `call`,
manager keeps only `manager`. This is the trap
[[running-order-measured-2026-09-12]] already records (*"`round` is only
ever the dispatching road. Never a classifier"*) sitting inside a counter
nobody had re-read. **When a reading says a road was served, check which
field it believed.**

## 2. NOTHING CAN INTERRUPT THE FLOOR HERE — don't try

Fixing (1) made the interrupt fire, and it still did not work. Watched
live across a whole manager entry:

    due='his own entry is 80s old with none of him in it'  why='waiting for the floor'
    ... 129s ... 175s ... 220s ...
    due=''   ← the entry closed. He never got on.
    box.floor = "a booth round", held 192 UNBROKEN seconds

`_TALK_CUT` ends a round at its next **turn boundary**, and **a fully
banked round has none left**: #1146 appends every line to the page in one
go and then holds the floor for its own measured airtime
(`_paged_settle`) so the page cannot run ahead of the air. There is
nothing to cut. A 20-second poller waiting for a gap between rounds will
not see one either ([[cupboard-must-be-heard]]).

**The working shape: claim the NEXT round, don't fight for this one.**
`manager_break_claim()` is read in the torrent at the point the station
chooses what to say next — the same point `gap_kind_policy`'s #1022
substitution already overrules the sheet — and it outranks that. It only
claims when a memo is finished, tinted and recorded, so the announce line
(`MANAGER_BREAK_LINES`) can never introduce a memo that fails to arrive.

My own bug worth remembering: the "ask once per entry" token contained
the entry's **age**, which changes every pass, so it asked ten times in
three minutes. **Never build a dedup token out of a value that ticks.**

## 3. Why the orchestrator could not learn

Every reading it had — `slot_supply`, `hour_shortfall`, the System2
binding view — answers *"is there enough material"*. **Nothing recorded
whether an entry on the sheet actually became the thing it says.**

`entry_close_note()` files one row per entry as it closes: what was due,
seconds of its own road inside it, what ate the rest, whether it had
stock at the time. `schedule_lessons()` reaches the distinction that
matters — **starved** (missed with nothing ready → `drive:`) vs **talked
over** (missed with stock ready → the cure is the FLOOR) — which have
identical adherence and opposite cures. Its first live row:

    manager  1 entry  adherence 0%  own_share 0%
    ate = {call: 92s, sfx: 82s, interject: 24s}
    "TALKED OVER ... the cure is the floor, not the cupboard"

`/api/orchestrator/lessons`; a `sheet_adherence` ask fires under 40%.

## 4. A claim I got wrong, so it is not repeated

I concluded from ONE `readable:false` sample that `entry_window_now()`
could not read a System2 hour and that five rungs were dead. **False** —
that sample landed in a gap between System2 plans just after a restart;
sampled repeatedly it reads fine. The robustness change (read the
occurrence's own `start`/`deadline` rather than requiring `minutes`,
which System2 slots do not carry) is worth keeping, but it fixed nothing
that was broken. **One sample of an intermittent reader is not a
diagnosis.**
