---
name: hour-contract-two-truths
description: "The scheduler panel's red \"short\" is fresh-stock famine, not holes — the commitment desk covers entries with repeats; #1134 shows both and reconciles the ladder"
metadata: 
  node_type: memory
  type: project
  originSessionId: f40c3481-2fd4-4f66-bcbb-4da52e02f40a
  modified: 2026-08-25T18:55:29.031Z
---

Deep orchestrator analysis, 2026-08-25 (#1134). The station's demand side has
**two truths that answer different questions**, and most "the hours are short"
alarms are the wrong one being read:

- `hour_needs()` (the scheduler panel's red numbers, `hour_short_kinds()`)
  counts each ready clip's seconds ONCE against owed = entry-minutes × 4h
  horizon. It is the FRESH-stock gauge.
- `commitment_inventory_plan()` (the desk, `/api/commitments`) binds concrete
  FIFO stock to exact entries and models repeats (`remaining_airings`,
  `repeats_hard`). It is the WILL-ANYTHING-GO-OUT-EMPTY gauge.

The running order is **~2.35× oversubscribed** (`/api/coordinator/capacity`:
~140 min of render room wanted per 60-min hour), so fresh famine is
structural and repeats are the design. The panel crying famine while the desk
says "all 10 segments can be written in time" is NOT a fault. #1134 added
`uncovered` (desk short_seconds) to `flow.hour_needs` via
`_hour_needs_with_cover()`; the panel now says "Xs short of fresh · every
entry bound (repeats)" vs "Ys has NO stock", and only uncovered reads orange.

**Why:** every prior "investigate the orchestrator" pass burned hours on this
disagreement; #1132 was the same class (two inventories).

**How to apply:**
- Judge "is the hour resolved" from the desk / `/api/coordinator/hourly`
  (the #1131 closed-loop hour contract: targets, aired, attainment,
  learning_factor), never from panel red alone.
- `prep_one` gate: writes are refused when the desk says "assigned" — #1134
  added the paused-hour bypass (paused + road in `hour_short_kinds()` may
  write), mirroring #1131's prep_plan gate. Both sides must stay in step.
- **Policy self-contradiction is real**: unanswered orchestrator asks
  self-answer with option 1, and separate asks set `drive_road:gallery` AND
  `postpone_first:gallery` simultaneously → gallery closed its hour at 21%
  while news hit 145%. #1134: `coord_hour_close` now retargets
  `postpone_first` to the biggest-surplus road when the postponed road
  missed its contract. Check `/api/orchestrator/asks` policy block for
  conflicts when a road starves on air.
- Ad road wasted 6/8 writes on "product never named and sold" — the crystal
  tint stripped the sale and the audit runs on TINTED words. #1134:
  `ad_write_fresh` rides the product through the tint on the `verbatim`
  rail, audits before shelving, retries with the lesson in `direct`.
- `coord_schedule_note`/`coord_task_note` look uncalled by grep but are
  wired DYNAMICALLY via `globals().get(...)` in `sched_result`/`task_note` —
  grep for the bare name before declaring dead wiring.
- pyflakes on app.py: the one pre-existing "undefined name 'socket'" hit
  (quoted annotation, ~48994) is harmless noise.

**PAUSE DECREE (#1138, 2026-08-25): a paused radio is SILENT.** The rule
has moved twice — #1115 silent → #1127 "silenced booth, not silenced
station" (records kept spinning) → #1138 operator's words: "I pause the
radio. Playback needs to stop immediately." radio_pause_set stops the
box stream + music_play_on_box gates on radio_paused() +
/api/radio/clock reports playing=false/paused=true (all page players
obey). Resume drops a FRESH record (fast_skip + dj_skip). Do not
"fix" a paused-silent box back to spinning. Spoken pause phrases:
verb-first AND subject-first both work (#1137), questions excluded.
Spoken OFF exists too (#1139): "turn/shut/power off|down the radio",
"stop/kill/end the radio" (adjacent-only), "radio service off" →
dj_stop; "turn on the radio" → start (which also releases a leftover
pause — station_repair_now no longer awaits the sync dj_start).
"take the radio off the air" deliberately stays a PAUSE.

**#1141 (2026-08-25, stacking scan): the cupboard was FORBIDDEN from
being full.** `coord_retire` deleted every row the 4h plan didn't
select ("whether heard or unheard", ~15s cadence) — the keeper's
surplus was shredded within the minute; now keeps unaired rows (#1075
rule). `pantry_burn`'s clip sweep killed ALL audio at render+24h even
under protected rows; spoken-for keys exempt now. Caller banking: the
swath draw avoided shelf FILES while the final contract refuses on
TEXT vs shelf+240-log — 6 refusals/0 banks in 40 min; the draw now
validates with `call_speakerbox_novelty` before writing. Levers wired:
paused keeper auto-authorizes piper for short roads; the #1121 paused
tint bonus (0.90) stands down while any road is short; road_empty
ask's first option is stock:8 (was 2 — decide-alone SHRANK the
cupboard). Dials: prepare_hours 3→6 (was below the 4h floor, doing
nothing), stock_depth 2→8. Coordinator "clear" line now names the 4h
desk's remainder. Caller is the structurally dear road (~273s room /
96s air, cannot repeat) — expect it last to fill.

**#1136 addendum (2026-08-25, full deck audit):** all 34 deck controls
traced; 31 clean. Fixed: `/api/dj/sfx` 500 (relative_to vs
SFX_LOCAL_ROOT), `/api/radio-cache/staging` hang (sfx_by_id CIFS walk
per sting row → one id→name map), voiceDeskOpen silent no-op (opens
first, reports). Ads: `ad_studio_clock` retries in 60s when blocked
(AD_STUDIO_RETRY); `dj_ad_break` gives the produced cupboard
AD_PRODUCED_BREAK_SHARE=0.5 of breaks before the dry shelf read;
`_air_produced_ad` now credits coord_air_note (was invisible to the
hour scorecard). ~15 silent `catch{}` sites in the panel render
failures as empty lists (cache/calendar/topics/plot/guest lists) — not
fixed, known pattern.

See [orchestrator-dead-wiring](orchestrator-dead-wiring.md), [parallel-session-commitment-ledger](parallel-session-commitment-ledger.md).
