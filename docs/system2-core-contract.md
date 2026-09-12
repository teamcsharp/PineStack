# System2 core and host contract

`system2.py` is independent of station imports. It never writes prompts, renders audio, starts playback, or changes station settings. SQLite transactions own planning, reservations, event jobs and actual receipt history. The host remains responsible for authenticated controls, current media/proof checks and real transport evidence.

## Plans and stock

`System2Store(path, now=time.time)` accepts an injectable clock. `plan_hour(hour_start, templates, candidates=(), config_revision='', expected_revision=None, plan_id=None)` retains every enabled configured occurrence, including explicit over-capacity debt. The default ID is `hour-<epoch milliseconds>`; independent interrupt plans use an explicit `event-<event ID>` identity. Returned hours use `start`, not `hour_start`. A changed configuration or start increments the revision; an in-flight performance cannot silently move to a different plan.

Templates require `id`, `kind`, `seconds`; optional fields include `offset`, `target_seconds`, `prompt`, `prep_cost_per_second`, and exact `candidate_ids`. `require_slot_binding=True` restricts event plans to their own explicitly bound recordings, so an unrelated ready caller cannot impersonate a requested caller or guest. Full metadata survives into job templates. Overlapping or reordered offsets are rejected. Host configuration chooses horizon and engine mode.

`coverage_mode='one_performance'` makes a short record-linked announcement an explicit one-performance obligation. Its `target_seconds` is a preparation budget; one verified 12-second link supplies one performance, never 180 seconds of speech. Actual ready/heard seconds stay measured, and completion still requires a full audible receipt. `allocate_current(slot_id, candidate_id, expected_revision=None)` binds the actual currently playing record's eligible side without changing the plan revision. It refuses active/completed ownership and another current/future allocation. `get_candidate(id)` exposes the retained evidence for historical trace lookup.

Candidates require `id`, `kind`, exact boolean `ready` and `eligible`, actual `seconds`, full `script`, ordered `lines` and measured SHA256 `audio_hashes` or per-line `audio_hash`. Lines retain text, speaker/voice, duration and all supplied trace/provenance fields. Missing audio, duration or spoken text remains debt. Optional `slot_id`, `template_id` and `hour_id` prevent work prepared for one occurrence being taken by another. Readiness is checked again at reservation and dispatch; full evidence signatures detect changed words, voices, order, media and duration.

The host refreshes the complete inventory with `sync_candidates(rows, replace=True)` before replanning. An absent current row becomes ineligible; immutable historical scripts are preserved. One whole fitting performance is allocated per segment before earlier segments receive additional material. No candidate or normalized text/audio alias is allocated twice within the same hour. Other plans and heard history constrain subsequent reuse.

Counters have distinct meanings:

| Field | Meaning |
| --- | --- |
| `allocated_seconds` | Full recorded performances retained in the plan, including completed ones |
| `ready_seconds` | Unconsumed, currently eligible recorded stock, including valid prepublication reservations |
| `coverage_seconds` | Valid staged or owned/completed performance coverage |
| `in_flight_seconds` | Remaining measured duration of dispatched/suspended work; elapsed time is not audible proof |
| `heard_seconds` | Verified audible line/full-performance receipts only |
| `delivered_seconds` | Verified completed delivery; deliberate mute can be delivered without being heard |
| `debt_seconds` | Target minus committed coverage; never total global library size |

`get_hour`, `hours`, and `scripts` expose full retained plans/scripts. `jobs`, `events`, `reservations` accept optional `states` and bounded `limit`; `get_job`, `get_event`, `get_reservation` return one complete record.

## Preparation

`claim_job(owner, kinds=None, lease_seconds=300, lookahead_seconds=3600)` selects missing-segment work ahead of topups, then deadline and measured preparation cost. Expired slots receive no generation claim. Unknown cost stays null. Target work is the slot deficit, not the entire pantry or hour. Existing live ownership and failed `retry_at` survive replanning; previous ownership/results remain in `last_attempt`.

`renew_job(id, owner, token)` extends current ownership. `complete_job(id, owner, token, candidates=(), success=True, retry_after=30, result=None)` validates plan ownership and candidate kind/binding, saves actual results, and requests replanning. Successful writing without ready eligible media is `progress`, with `ready_output=False` and the same bounded retry delay; later missing segments can advance while its partial work remains retained. A ready candidate clears that wait. It cannot manufacture readiness or airtime.

## Publication and heard receipts

`reserve(slot_id, candidate_id, owner, expected_revision=None, lease_seconds=120, request_id=None)` converts one allocation to active ownership. Only one performance owns a slot at once. Request IDs identify one intent: reusing an ID returns the original record, including a released record. A genuinely new dispatch attempt needs a new ID.

`validate_reservation(id, owner, token=None, seconds=None)` repeats current proof, repeat and actual remaining-time checks. `mark_dispatched(...)` must run at actual handoff, with assembled duration where available. It records publication only. A dispatched reservation with no receipt stays uncertain after its lease; timeout cannot make it automatically replayable.

`ack(id, owner, receipt_id, token=None, line_id=None, completed=False, audible=True, at=None)` accepts an exact recorded line or a separate verified full completion. Repeated line/full callbacks across browser and box credit once. Deliberate mute does not enter heard history; an independently audible route may subsequently provide its own evidence. Unexpected actual repeat receipts are preserved and flagged, never erased.

`record_external(text, audio_hash='', receipt_id=..., at=None, seconds=0, reservation_id='')` accepts only actual external audible evidence. `can_play(texts=(), audio_hashes=(), reservation_id='')` checks the durable one-hour text/audio guard. Passing the exact owned reservation prevents its own earlier line receipt from blocking its remaining performance. Historical publication logs and render/cache counters are not proof and must not be seeded as heard.

`suspend(..., position_seconds, reason, event_id=None)` preserves an owned exact position. `resume(...)` checks remaining duration/current proof and returns `seek_seconds`; it never rewinds. Explicit `release` cancels ownership; the host must not use it merely because a dispatched receipt is late.

## Ingress

`enqueue_event(kind, payload, request_id, deadline=None, due_at=None, priority=0)` preserves exact payload and stable idempotent intent, including omitted deadline defaults. `claim_event(owner, event_id=None, lease_seconds=120)` expires stale jobs, waits until due time, and can claim one exact event. `release_event(id, owner, token, reason=..., retry_after=0)` relinquishes an unpublished attempt without extending its original deadline. `finish_event(id, owner, token, result=...)` records the handler's actual result. Queue acceptance is not a heard receipt. The host chooses scene-boundary interruption and explicitly reports missed wall-clock coverage; no elapsed slot is replayed merely to hide debt.

Validation at core/runtime freeze: 66 isolated `test_system2*.py` tests in 13.296 seconds: 31 core tests, 17 runtime tests and 18 media tests. Coverage includes concurrent ownership, missing-segment priority, partial-progress fairness, retry retention, candidate binding, exact media changes, actual duration after waiting, durable repeat history, independent mute/audible receipts, expiry, event microplan isolation, real local WAV proof, actual provider coroutine/trace association, publication versus hearing, authenticated reads and a cold import of the full application. No tests call a live model, change station settings or start live playback.

The subsequent one-performance/current-record additions pass all 34 core tests in 3.271 seconds. Their new cases cover exact short-link accounting, preservation through replanning, current allocation replacement, and refusal to steal another occurrence's owned or future work. Final combined application and UI validation is recorded separately by the integration owner.

The pre-integration live inventory is retained in [system2-legacy-inventory-audit.json](system2-legacy-inventory-audit.json). At 2026-09-08 05:28:36 UTC it had 57 ready entries but zero ready callers, despite 14,722 aggregate pantry seconds. This is evidence for occurrence-level planning; it is not a post-deployment performance claim.

A later [configured-slot audit](system2-configured-slot-audit.json) records the actual canonical hour: 20 enabled occurrences spanning exactly 60 minutes. The legacy endpoint reported caller `ready=0` while a future caller occurrence claimed 153.7 held seconds; track talk had 82.9 total seconds but claimed 180 held seconds; recap claimed coverage with no written or ready recording because it was exempted until the end. These are inconsistent legacy readiness/accounting fields, not proof that the audio aired. The adapter therefore uses exact current ordered takes and decoded files instead of importing those coverage estimates.
