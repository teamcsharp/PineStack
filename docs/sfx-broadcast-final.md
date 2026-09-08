# SFX broadcast observation

Read-only observation of the normal deployed station. No model, TTS, playback, route, or volume requests were issued.

Observed 241.436 seconds in 25 snapshots. Completion: complete.

Bank before: `{"total": 24, "ready": 3, "waiting": 21, "suspended": 0, "reserved": 0, "heard": 1, "why": "The SFX speech reserve is ready"}`.

Bank after: `{"total": 24, "ready": 3, "waiting": 21, "suspended": 0, "reserved": 0, "heard": 1, "why": "A bounded writer is busy; the original source remains queued"}`.

Cadence deltas: `{"heard_units": 0, "heard_samples": 0, "sample_due": 0, "sample_omitted": 0, "guy_due": 0, "guy_omitted": 0}`. New durable host receipts: 0; sample receipts: 0; bank heard delta: 0.

Preparation reasons: A bounded writer is busy; the original source remains queued; The SFX speech reserve is ready

[Exact snapshots, saved proof and receipts](sfx-broadcast-final.json).

- Due/omitted counters describe planning in the current process, not audible delivery.
- Heard counters and durable receipts use production playback acknowledgements; no microphone or acoustic measurement was made.
- A sampled chat row can be prepared or held; it is not proof of being heard.
- Bank totals apply to the current voice/profile. A profile change or restart can invalidate simple deltas.
- This short observation cannot establish sustained preparation throughput or station-wide audio quality.

The short-sample pool was populated throughout this capture: 4,289 candidates initially, 4,344 finally, and 4,289 to 5,045 during progressive scans. The separate [restart capture](sfx-warm-final-live.json) saw 3,133 verified candidates while the full scan was still running. This resolves the earlier [roughly six-minute empty-pool delay](sfx-broadcast-observation.md) without increasing the four-second sample cap.

Three distinct current-voice recordings passed the stored Crystal, full-text, voice and media checks. Two were generic responses eligible for immediate selection; the third required a matching topic. The third completed after the restart but before this observation began, so this capture does not demonstrate in-window bank growth. The reserve admission rule now counts only eligible, unreserved generic takes outside the replay cooldown. With two available, ordinary background admission was expected here. Mechanical acceptance is not an editorial quality guarantee: the topical biscuit response contains the ungrounded phrase "the villain just witnessed them."

There were no new durable host, sample or guy receipts in this window. The [air diagnosis](sfx-final-air-diagnosis.json) found that emergency host pairs were being dispatched through a path that omitted cadence additions and counters. It also observed an actual quiet interval, with no active speech or stream, rather than a model or TTS job holding the audio floor. Music was intentionally at zero, so the evidence does not establish uninterrupted DJ audio. The later continuity patch uses the same saved-sample selection and row acknowledgements as ordinary speech; its live verification is recorded separately in [the following capture](sfx-continuity-live.json).

The apparent 31-ready inventory was a count of recorded and tint-ready rows, not of programmes eligible for every current slot. The [stock diagnosis](sfx-ready-stock-diagnosis.json) and [read-only saved-take proof](sfx-ready-take-proof.json) found one 49.59-second news bulletin with all four takes intact that had already used all nine permitted airings. The main planner already excluded it from available supply. The news producer's separate fullness check incorrectly counted exhausted stock; that check now uses the existing repeat-eligibility rule while retaining historical rows, takes, voices and policy. Two isolated regressions verify that a full exhausted shelf permits preparation and that unaired or still-reusable supply continues to satisfy the ceiling. This particular live bulletin was below the current demand, so the bug is not evidence that it caused all recent gaps. Ordinary prepared gallery playback subsequently resumed.

These findings and the earlier captures are retained even though later patches address them. The final continuity and news changes passed the complete 893-test Python suite and 95 Node checks before deployment; this document's unchanged JSON remains evidence from the preceding deployment.
