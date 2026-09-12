---
name: the-cupboard-must-be-heard
description: "#1260 - 55 finished rounds aged up to 103h unheard while the same roads were written live 90 times a day; both doors from the cupboard to the air were shut, and the gap-based cure could not run because the floor is held for minutes"
metadata:
  node_type: memory
  type: project
---

2026-09-12 (#1260). The retirement desk showed rows reading **0/18
airings** with ages of a day, two days, four days. The measurement behind
that photograph:

| road | rows | never heard | of those, airable | oldest |
|---|---|---|---|---|
| gallery | 42 | 35 | 25 | 103h |
| manager | 34 | 28 | 19 | 103h |
| ad | 49 | 12 | 11 | 39h |
| news | 12 | 9 | 9 | 5h |
| recap | 10 | 10 | 0 | 104h |

In the **same 24 hours** the station aired 36 distinct manager rounds and
54 distinct gallery rounds. Cross-referenced by sid against the shelf:
**zero overlap**. Every one was written and rendered live.

**THE CUPBOARD WAS NOT BROKEN AND THE DOOR WAS NOT BROKEN.**
`/api/director/why-not/manager` answered *"34 row(s) on the manager pile;
25 carry recorded audio; the air's own door would take one right now"*.
Nobody was knocking.

## The two doors, and why both were shut

**IN TURN.** `_ready_slot_window(kind)` returns a deadline of **0.0**
unless the running order is standing on that exact road's slot, and
`_ready_round_fits` refuses on it. When the slot *is* live it then demands
the round fit what is LEFT of it: the live hour's two manager slots
offered **0.0s and 15.5s** of room against shelf rounds of 26-119s, and
`/api/system2/binding` reported `would_fit: 0` on **all eighteen slots**.
Sheet adherence was measured at 4% the same day. This door opens about
never.

**OUT OF TURN.** `_ready_shelf_air(rescue=True)` - whose only callers were
DEAD AIR and the two entry-debt rungs. The SFX Guy now fills dead air
before the rescue is reached, so that door stopped opening too.

Meanwhile the preparer kept writing: *"the hour is short of caller, news,
gallery - those go first"*. The supply counters are about slot fit, not
about stock, so a full shelf reads as a shortage.

## The trap in the first cure

The first patch put a standing sweep in the dead-air watchdog, behind
`if not (_SPEAKING[0] or _floor_busy())`. It **never ran once** in ten
minutes. `/api/dj` said why: `box.floor = "a booth round"`, held **248
seconds**, and `FLOOR_STALE_SECONDS` is 1500. The pair talk all but
continuously, so the gap that rung waits for does not come. *This is the
same reason #1186 recorded that its rescue "had never fired".*

**On this station, a cure that waits for a gap is a cure that never
runs.** It only showed up because `_UNHEARD_SWEEP` records WHICH gate
shut it - four bare `return ""`s would have looked identical to a working
rung with nothing to do.

## The cure that works

`unheard_free(kind, row)` - **a round that has NEVER BEEN HEARD and has
waited longer than the dial allows is not held by the running order.**
The exemption is read where the ROAD ASKS (`dj_gallery_round` and
`dj_manager_note` both call `_ready_shelf_air` before writing anything),
so the cupboard answers instead of the writing room. Everything else is
unchanged: a repeat still waits its turn and its rest, an unfinished round
is still refused, and `can_handoff` still proves the takes are intact.

Three things ride with it:

* **`cupboard_why_row(kind, row)`** - every reason ONE item is not on the
  air, asked in the order the air asks them, by the functions that decide
  it. On the desk each row expands to it, with Play now / Send to the
  front / Ask the orchestrator to judge it / Remove.
* **`unheard_state()`** - the census, on `/api/cupboard/unheard`, in
  `dj_state()`, and behind the orchestrator's new `cupboard_unheard` ask
  (`unheard:`, `unheardafter:`, `unheardevery:`).
* **`unheard_replace_sweep()`** - the operator's other half, *"if it's not
  used for days and days then we need to replace it"*. Rows unheard past
  four days **that cannot air** go to the retirement desk. It never
  reaches for one the air could still take: #1075 stands.

## What to check first, next time

1. `/api/cupboard/unheard` - `say` names the backlog AND whether anything
   is spending it (`sweep.why`).
2. `/api/cupboard/why?id=...` - the per-row reasons.
3. `/api/director/why-not/<road>` - the air's own door.
4. `/api/dj` -> `box.floor` and `box.floor_for` - **before** writing any
   rung that waits for a free floor.

Known gap, visible on the desk: `RESCUE_ROADS_OPEN` is `manager, gallery,
news, caller`. **recap and ad cannot air out of turn at all**, so their
unheard stock has only the slot door. All ten recap rows are `off_brief`,
so opening the road would not have helped them; the ad road spends itself
through `shelf_take("ad")` at the record slot.
