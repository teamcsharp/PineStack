# System Three pantry lifecycle

Activated 2026-10-02 under the operator's instruction to execute the full policy.

## Why the pantry stalled

The panel counted every cached audio clip as stuck work. Unheard shelf rows had no
freshness clock and were protected from retirement; rhymed material could retain
another indefinite shield. Existing multi-voice admission refused missing original
System Three turns, including native one-turn ads and IDs that were mistakenly
sent through that multi-voice requirement. Publishing was sometimes credited as
hearing. A replay gate could then refuse an item that had only been published.
The coordinator could report no recording debt while a render was active and
hundreds of other rows were waiting.

The lifecycle keeps rendered clip cache, pending work and reusable repertoire
separate. Its independent startup clock runs even when the show is paused or off,
so a slow preparation pass cannot stop expiration. It yields between backlog
items and preserves in-flight producers and transport-owned media files.

## Active policy

- Ordinary work: immutable 24-hour lifetime from original creation, including
  unheard, incomplete and rhymed work. News uses the shorter existing news
  freshness window; replies expire after 15 minutes.
- Repair: at most two bounded attempts against the original System Three plan;
  each attempt times out after 180 seconds. Repair never lowers the original
  planned turn count or clears editorial rejection. Invalid binding is refused
  before recording. A verified original one-turn ad/ID remains a one-turn item.
- Scheduling: System Three draws age- and missed-opportunity-weighted stock that
  fits the current road, segment deadline and actual playback runway. In the
  last hour the earliest deadline takes priority among compatible items. No
  compatible slot means retirement by the deadline, rather than forced irrelevant
  speech. Dispatch is paced at 20 seconds and rechecks the normal air contract.
- Delivery: reservation and publication are distinct from consumption. Only a
  complete native playback receipt credits delivery. Failed or timed-out handoffs
  retry within a three-failure budget. Ordinary delivered work leaves the shelf.
  Historical playback evidence also consumes ordinary stock; publication alone
  is not playback evidence.
- Reactions: standalone listening acknowledgments, catchphrases, funny or rhyming
  reactions and high-impact punchlines with real System Three source and a fitting
  take. At most 200 clips and 30 minutes. Unused material gets seven days of
  probation; previously used material expires after 30 days without reuse.
  Re-recording does not reset probation. Context-dependent facts and news are
  rejected. Existing short source-backed material enters a bounded background
  classification queue (200 candidates, ten per batch, two attempts, 24 hours).
- Evergreen segments: explicit operator nomination, at most 20 segments and one
  hour of audio; four-hour rest after delivery and retirement after 30 days without
  use. Caller, news, reply and recap material cannot enter this library.
- Speculative production: a road with eight blocked ordinary items gets
  backpressure while actual imminent coverage debt can still request work.

The pantry popup reports cached clips separately from ready, blocked, reserved,
queued, repairing and expired work. The coordinator reports lifecycle debt and
original-plan repair instead of treating cached audio as broadcast-ready stock.

## Operations and evidence

`GET /api/pantry/lifecycle` exposes state, reason counts, recent decisions, oldest
work, policy and maintenance heartbeat/error. Authentication follows existing
read authorization. `POST /api/pantry/lifecycle/policy` changes validated bounded
policy fields with operator authorization. Modes are `air` (enforce), `trace`
(observe) and `off` (legacy behavior). `POST /api/pantry/lifecycle/nominate` accepts
an item `id` and `kind` (`evergreen`, `reaction`, `catchphrase`, `punchline`).

Policy, counters, candidates and the latest 200 decisions live in
`data/pantry_lifecycle.json`. Per-item metadata lives with the existing shelf and
larder stores. Source-linked decisions are also observed in System Three.
Physical audio deletion remains the responsibility of the existing transport-aware
media pruner; retiring work releases cache ownership, not a file currently playing.

Before activation, the existing pantry, shelf, gold and larder were archived in
`artifacts/pantry-lifecycle/backlog-before-20261002T224953Z` with a manifest.
Original modified source files are preserved under
`artifacts/pantry-lifecycle/source-before`. These artifacts contain no credentials.
Live observations are saved as `activation.json` and `live-latest.json` in the same
artifact folder. Run `python tools/pantry-lifecycle-live.py` inside the station
container to refresh evidence. `--trace` suspends enforcement; `--activate`
requires the recoverable archive and enables enforcement. Neither prints keys.
Restoration of shelf data must happen with the station stopped to avoid a running
flusher overwriting it. Trace mode does not restore already retired material.

Validation: lifecycle unit and real-app integration tests cover deadlines,
source ownership, original one-turn contracts, receipt deduplication, repair and
handoff budgets, library caps, off-air maintenance, runtime getter integration,
probation and census accuracy. Existing scheduling, bootstrap and coordinator
regressions and desktop/Android renderer checks are run alongside these tests.
Two broader-suite failures were reproduced against the saved pre-change app:
`test_pantry_record_readiness.test_bound_profile_uses_the_bank_compatibility_rule`
and `test_gold_freeze.TheAirIsPumped.test_a_held_floor_is_not_a_talking_mouth`.
They remain separate existing issues.

Live verification drained the expired legacy backlog and observed active sounding
receivers. A snapshot cannot establish long-term broadcast continuity; the
persisted decision trail and playback receipts provide the ongoing evidence.

## Startup recovery during verification

The final restart exposed an invalid System Two database signature. A stopped
station copy was archived under
`artifacts/pantry-lifecycle/system2-recovery-20261002T230741Z`. Restoring only the
16-byte SQLite signature (12 bytes were damaged) on a separate copy returned
`PRAGMA integrity_check = ok` across the whole database, with all eight tables
retained. That verified copy was restored atomically; original database and
sidecars remain in the archive. The underlying cause of the signature damage is
not established by this pantry investigation.
