---
name: orchestrator-dead-wiring
description: "The Pine Box orchestrator's desks were sound but unreachable — the recurring fault class is a gate wired to nothing, not bad reasoning"
metadata: 
  node_type: memory
  type: project
  originSessionId: 972203c0-385f-4018-891c-5d597c362de3
  modified: 2026-08-23T01:12:50.247Z
---

Across 2026-08-21/22 the Pine Box orchestrator was diagnosed end to end. The
finding that matters is a **class**, not a list: the decision-making is
largely correct and largely *unreachable*. Nearly every "the orchestrator is
falling behind" symptom traced to a gate wired to nothing, never to bad
reasoning.

The recurring shapes, all confirmed live:

- **Unit mismatch between two same-named variables.** `_banter_wait` compared
  `len(_LARDER)` (max 14) to `target` — which is a ROW COUNT in
  `larder_keeper` but `prepare_target_seconds()` (7200) in `pantry_keeper`.
  Never true, so banter spent every window and `prep_plan()` — which holds
  the commitment board, deadline picker and slot desk — ran 4× in 24 min.
- **A decision fired from a browser poll.** `cover_now` was called inside
  `glyphy_state()`, whose only caller is `GET /api/glyphy` (5 s poll). Fired
  12–24×/min with a tab open, never without one.
- **A guarantee inside `except Exception:`.** `resort_may_drop` protected the
  crash path of `alt_shelf_trim`, never the two paths that run.
- **A gate counting things that cannot be used.** `hour_needs`/`shelf_full`
  summed shelf rows without `pantry_get()` — 24 rows with pruned audio read
  as "full" against a 24-row ceiling.
- **Policy keys written and read by nothing** — `ballast_minutes`,
  `when_empty`, `thin_road` (and `tint_share`, read with no writer).
- **A "protect X" answer that protected something else.** `prefer:banter`
  removed `order[-1]` from the stand-down ladder, which is `caller`.

**Why:** every one of these reads as working code and produces plausible
output. Three separate readers disagreed about repeat readiness without
anything erroring. This is why "investigate the orchestrator" kept returning
"looks fine".

**How to apply:** when a Pine Box mechanism "isn't working", first ask
*is it called, does it run, does it change anything* — in that order — before
reading its logic. Verify the claim on the live station before patching; I
have twice "corrected" something on reasoning that measurement then refuted
(the innings-vs-pantry hypothesis in #1095). Beware any counter or budget
placed in a function the panel polls — `schedule_take()` and `glyphy_state()`
are both read by the browser. See [spark-agent-environment](spark-agent-environment.md),
[dialogue-pipeline-diagnostics](dialogue-pipeline-diagnostics.md), [pinebox-broadcast-debugging](pinebox-broadcast-debugging.md).

**Restart frequency is a measurement artefact, not a fault.** An audit
reported 85 starts/24 h and concluded the station "cannot learn past 17
minutes". Gap analysis: 55 of 83 gaps under 12 min (deploy bursts), longest
quiet stretch **243 minutes**, exit code 0, no OOM. In normal operation the
process is stable — do not build persistence for in-memory ledgers on the
strength of that number.
