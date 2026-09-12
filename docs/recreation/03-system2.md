# 03 — System2, the planning engine

System2 is the scheduler that drives the station since #1070 (2026-09-08). It replaced "the desks
decide what to write next" with "the hour is planned, every slot is a job, every job is claimed,
prepared, verified and dispatched, and every airing is receipted". The legacy keepers still write
beside it (`legacy_keepers: true`), and the legacy chain still serves an occurrence when System2 has
nothing ready (`fallback: true`); both are dials.

## Files

- `system2.py` — the store (SQLite, `data/system2*.sqlite`): tables `s2_hours`, `s2_slots`,
  `s2_candidates`, `s2_jobs` (state, deadline, lease), `s2_reservations`, receipts, events. Pure
  functions with validation (`_name`, `_number`), no asyncio, no host imports.
- `system2_runtime.py` — the engine: `System2Runtime(host)`; `refresh()` (sync candidates from the
  common inventory, plan the next `horizon_hours`), `prepare()` (claim a job, write/tint/record for
  its slot), `dispatch()` (serve the occurrence the loop is at), `fallback_due()`, `include_drafts`,
  `candidates_by_slot`, `status()`, the FastAPI routes under `/api/system2/*`, and the loops
  (`plan_loop` 15 s, `prepare_loop` 3 s, `event_loop` 1 s) installed by `install(app, namespace)`;
  the host is the `app` module, reached as `self.host` (the code reads `h.dialogue_row_viable`,
  `h.alt_candidates`, `h.dj_speak`… — the engine reuses the station's writers and rooms).
- `system2_media.py` — the delivery: renders and hand-offs, `deliver(resolved, handoff, validate)`,
  the transport refusal reasons.
- `system2_writing.py` — the writer budget for a job (`system2_budget`: reserved seconds, turns).
- `frontend/system2.js` — the panel section (hours, slots, jobs, orchestrator reasons per slot
  card, the fallback/keepers toggles); mirrored in the desktop Scheduler rail.
- `data/system2-config.json` — the live config: `engine` (`system2`|`legacy`), `horizon_hours` 2,
  `repeat_seconds` 3600, `generation_turns` 6, `legacy_keepers`, `fallback`. The CODE default is
  `legacy` on purpose (test fixtures); the live default is the saved file, set through
  `POST /api/system2/settings`.

## The plan

`plan_hour(hour_start, templates, candidates)` turns the running order into slots: each slot has
`kind`, `start` (= hour start + template offset), `deadline`, `hard_deadline`, `seconds`,
`target_seconds`, `debt_seconds`, `ordinal`, `status` (`needs_preparation`, `complete`,
`outside_hour_capacity`…) and `allocations` (candidates booked to it with a `planned_start`). A
candidate is a piece of the common inventory (a shelf row, a larder round, a cupboard call) with
`kind`, `seconds`, `ready`, `expires`; `candidates_by_slot` decodes one hour of slots at a time (the
GIL lesson, #1070). The one-hour repeat ledger (`can_play`, `repeat_seconds`) refuses a candidate
heard within the hour.

## Jobs and leases

`claim_job(owner, kinds, lease_seconds)` hands the preparer the most urgent slot needing
preparation (ordered by deadline). The lease (900 s, renewed every 300 s by `renew()`) bounds how
long a slot stays unclaimable when a sitting dies; `reclaim_jobs` at startup returns jobs the last
run left working (#1074). `complete_job(success, retry_after, result)` closes it; a job with no
usable outcome rests (`retry_after` 120 s when nothing changed) instead of retrying twice a minute.

## A sitting (`prepare()`)

1. Take a lane (`_prepare_lock`, a semaphore of `OLLAMA_LANES` since #1084 — two sittings on
   different roads at once; the brief and the prep context are task-local).
2. Claim a job; set `WORK` (the contextvar every model call reads: `system2_current_work()` stamps
   entries with `system2_slot/job/trace_id`, and the tint admission gives due work a third permit,
   #1080).
3. Set the road's brief (`alt_brief_set`: the segment's prompt plus the SYSTEM2 PRODUCTION note —
   one complete compact scene, concrete details, no padding) and the prep context.
4. Fit check: the remaining slot time must fit a minimum scene; otherwise the job rests with the
   reason recorded (#1074, `self._refused`).
5. Reuse first: viable, not-ready rows of the road already in the inventory that are not bound to
   another slot and are not struck out (`tint_retry_due`) are finished rather than rewritten.
6. Otherwise write: the road's own writer (`dj_banter`, the call writer with the caller's cloned
   voice, the ad/memo/gallery writers) with `generation_turns`; then the crystal tint; then the
   recording room. Every model call is captured into the trace (`data/system2-traces/<trace>.json`).
7. `complete_job`; the candidate becomes `ready` when its audio and its tint verdict are both in.

## Dispatch and receipts

When the loop reaches an occurrence, `dispatch()` finds the slot in play (`slot['start'] <= now <
deadline`), reserves its best allocation (`reserve`, with the fit re-checked and a refusal reason
recorded when it cannot fit), publishes the occurrence (`_publish_clock` → `sched_pos`), and hands
the candidate to `system2_media.deliver`. A delivery that airs writes an **audible receipt**
(`receipt`, `external_audible_receipt`); a transport refusal releases the reservation with the reason
and the slot tries the next allocation. The receipts are what the hour's `heard` and the debt
accounting are built from — "ready" is not "aired".

## Status and the UI

`GET /api/system2/status` (serialised in a thread; `copy_plans=False`) → `config`, `hours[]`
(`slots[]` with `status`, `target`, `ready`, `debt`, `heard`, `allocations`), `jobs[]` (state,
attempts, last_attempt), `work` (the latest sitting) and `works[]` (every sitting in progress,
#1084), `lanes`, `errors`, `inventory`, `events`. `GET /api/system2/hours|hour|script|line` read the
plan and the traces; `POST /api/system2/settings` changes the dials; the events API takes operator
events (a requested call, a guest interview) into the plan.

## What was learned building it (the audit of #1074)

Candidates must be validated per row and synced off the loop; jobs need leases AND renewal; a
"ready" candidate past its expiry must say so and be refused by the planner; the fit must be checked
before reserving, not after; the status must never deep-copy the plans for a poll. And: the engine
does not change how much the box can write — it changes what gets written first. The capacity
arithmetic is in `docs/system2-capacity-1080.md`.
