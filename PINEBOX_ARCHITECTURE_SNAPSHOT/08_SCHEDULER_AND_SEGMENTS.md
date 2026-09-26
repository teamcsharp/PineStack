# Scheduler and Segments

## Time Representation

**OBSERVED:** `schedule.json`/settings contain named schedule presets, an active schedule, day mapping, and ordered slot definitions. `schedule_read` normalizes defaults; `schedule_take` advances occurrence state and is designed not to raise on the air path. Hour-specific overrides and horizon APIs supplement the canonical schedule (`app.py:schedule_defaults`, `schedule_read`, `schedule_take`, routes at `63591-64834`).

**OBSERVED:** System 2 materializes templates into durable hourly slots with start, deadline/hard deadline, target/debt seconds, kind, ordinal, status, and allocations (`system2.py:System2Store`; `system2_runtime.py:refresh`). Preparation jobs are prioritized by deadline and protected by leases.

## Segment Kinds and Behavior

| Family | Representation/owner | Duration and recurrence | Preparation/playout behavior |
|---|---|---|---|
| Record/music | music index + show queue | measured tags or estimate; continuous rotation | `_dj_loop`, request queue, played avoidance |
| Banter | schedule/record talk/larder | line-range and budget; recurring between/over records | banked or live multi-turn script |
| Caller | scheduled road/cupboard | slot target, call turn/hangup rules | prebuilt/graded call or live fallback |
| News | scheduled road/news shelf | freshness lifetime and slot duration | fetch/select/dossier/write/render |
| Advert | scheduled road/ad shelf | fixed spot/read length or measured audio | produced spot/single read |
| Manager/upstairs | scheduled road/shelf | prompt-defined | prepared message/dialogue |
| Gallery | scheduled road/ComfyUI | generation + talk budget | image then description/sales round |
| Track talk | bound to current/coming record | must fit record phase | notes/lyrics lookahead, binding checked before write/render |
| Recap/paper | hour boundary | actual prior-hour evidence | press composes and may air summary |
| IDs/interjections/continuity/SFX guy | cadence/continuity triggers | short measured clips | floor/admission/sequencer lane |

Source constants: `app.py:SCHEDULE_KINDS`, `SCHEDULE_PROMPT_SEED`, `SCHED_PREP_KIND`, `SEGMENT_BRIEF`, `CANNOT_PREPARE`, `SHELF_CAPS`, `SHELF_REUSABLE`.

## Timing, Priority, and Gaps

- **OBSERVED:** Fixed target seconds coexist with dynamic measured audio. Fit is checked before reservation and delivery; debt records what a slot failed to receive.
- **OBSERVED:** Priorities come from deadlines, explicit System 2 event priority, operator interject/priority APIs, road policy, and continuity emergencies.
- **OBSERVED:** Randomization affects prompt alternatives, topic/source, and some road choice details, not the underlying clock order.
- **OBSERVED:** Fillers include records, prepared reserve roads, station IDs, continuity pairs, emergency Piper speech, and stings. Live observation found 498 finished reserve rounds (`/api/director/deadair`).
- **OBSERVED:** Overruns are constrained by fit/deadline/binding checks and linear sequence timing. Underruns become debt or admit filler. Listener ACKs correct estimated end times.
- **OBSERVED:** Bumps/IDs are independent short roads and can be committed at hearing time if not pre-scripted (`script_ledger_catch_up`).

## Real Scheduled Segment Path

The observed current schedule was `canonical hour (fits the engine)` with 18 slots. A representative caller path is:

1. `schedule_read` supplies a `caller` occurrence and `schedule_prompt_for` its standing instruction.
2. `System2Runtime.refresh` materializes the hour/slot in `system2.sqlite3`.
3. `prepare` claims the job and first searches viable cupboard/shelf candidates; otherwise it invokes `dj_call_generated`.
4. Caller/topic/voice are selected; the model writes a labeled transcript; `call_entry_contract` grades it.
5. Accepted turns are rendered by actor, stored, and exposed as a ready candidate.
6. `dispatch` reserves the allocation when the slot is in play, publishes the schedule clock, and delivers it.
7. `speak_turns`/assembly commits line order, playout publishes the media, and listener ACKs create audible evidence.
8. System 2 acknowledges the reservation/line and subsequent planning computes heard/debt from receipts.

**UNKNOWN:** The exact slot ID for the captured caller example could not be joined from the read-only endpoints; its screenplay record did preserve kind, caller, bank/air times, model neighborhood, voice render, and withdrawn/published state.

