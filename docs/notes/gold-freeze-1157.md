---
name: gold-freeze-1157
description: "#1157 (2026-09-09) the freeze — the retirement desk had NEVER recorded a row because resort_may_drop returned above retire_may; six roads deleted rhymed work unasked; the keep is now forever, not 96h"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T06:44:46.884Z
---

**The station's guarantee that "the desk sees every deletion" was false, and the
desk's own silence was the proof — read the wrong way round.**

`data/retire_ledger.json` had never existed and `/api/retire?summary=1` read all
zeros, while the caller shelf fell 16 → 13 → 10 → 9 over one night. That is not
"nothing is being deleted". It is **the desk never being asked**: `resort_may_drop`
returned `False` for a rhymed row on the `tinted_kept` line *above* its own call to
`retire_may`, and `resort_may_drop` was the only shelf-side road to the desk. The
shield hid the desk from exactly the work the desk exists to protect.

**Diagnostic rule this teaches:** an audit trail that is EMPTY is not evidence the
guarded thing is not happening. Ask what would have to run for a row to be written,
and check that path executes — the same shape as [orchestrator-dead-wiring](orchestrator-dead-wiring.md)
("called / runs / changes anything").

Six roads destroyed rhymed work without consulting `retire_may` or `row_is_rhymed`;
all now call `gold_locked(kind, row)` (rhymed AND the ledger does not say "remove";
a fault returns True). The one that mattered most: **`shelf_take`'s caller
burn-on-take** — every rhymed call the station ever aired left by that line, which is
also why the #1033 re-air queue was dead code (no caller row could ever carry
`aired_at`). Rhymed calls are now stamped and sent to the back instead.

**A keep expressed in HOURS is a date on which every shield fails at once.** The
96-hour default would have released four days of backlog in one minute on
2026-09-12. `RETIRE_KEEP_FOREVER = -1.0` / `KEEP_FOREVER_AT = 4102444800.0` is now
the default for every kind but news, and it overrides an hours-stamp already written
on a row — but NOT one the operator set by hand (`retire_kept`), which is a decision
about that item. Both clamps (`retire_rule`, `retire_rules_set`) had `max(0.0, ...)`
and had to learn the sentinel; so did `retire_decide`, `repertoire_status` and the
panel.

**Nothing rhymed is lost when a container is:** `gold_harvest_entry` now runs before
every ceiling-forced removal, larder trim and coordinator sweep. The gold bank's
bound spends the **take**, never the line — most-fired first, so an unheard bar keeps
its audio.

**Two rules deliberately survive the freeze.** A *plain* row is still swept (the
writer needs stocking slots), and a round that has **never aired** is still
untouchable (`row_unaired`, #1075).

**Live sizes that bound the design (measured, not guessed):** a larder round costs
**69 kB of JSON**, and `_larder_save` writes the whole file on the event loop — so
`TINTED_KEEP_ROWS` is 160, not the 400 the repertoire would like. The bars are what
is kept for good, in the gold bank, at ~250 kB a thousand. See
[pulse-library-and-firmware-down](pulse-library-and-firmware-down.md) — json holds the GIL.

Verified live after deploy: 94 rows carry the forever stamp, **zero** carry an hours
stamp; news correctly carries none. Related: [repertoire-dead-air-lcd](repertoire-dead-air-lcd.md),
[rhyme-variety-flow-calls](rhyme-variety-flow-calls.md), [render-is-slower-than-speech](render-is-slower-than-speech.md).
