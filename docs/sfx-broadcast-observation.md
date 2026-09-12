# SFX broadcast observation

Read-only observation of the normal deployed station. No model, TTS, playback, route, or volume requests were issued.

Observed 240.088 seconds in 25 snapshots. Completion: complete.

Bank before: `{"total": 24, "ready": 1, "waiting": 23, "suspended": 0, "reserved": 1, "heard": 0, "why": "A bounded writer is busy; the original source remains queued"}`.

Bank after: `{"total": 24, "ready": 1, "waiting": 23, "suspended": 0, "reserved": 1, "heard": 0, "why": "A bounded writer is busy; the original source remains queued"}`.

Cadence deltas: `{"heard_units": 9, "heard_samples": 0, "sample_due": 6, "sample_omitted": 6, "guy_due": 2, "guy_omitted": 2}`. New durable host receipts: 9; sample receipts: 0; bank heard delta: 0.

Preparation reasons: A bounded writer is busy; the original source remains queued

[Exact snapshots, saved proof and receipts](sfx-broadcast-observation.json).

- Due/omitted counters describe planning in the current process, not audible delivery.
- Heard counters and durable receipts use production playback acknowledgements; no microphone or acoustic measurement was made.
- A sampled chat row can be prepared or held; it is not proof of being heard.
- Bank totals apply to the current voice/profile. A profile change or restart can invalidate simple deltas.
- This short observation cannot establish sustained preparation throughput or station-wide audio quality.

The first observation ran from 1788811613.056 to 1788811853.144 (240.088 seconds). The deployed station stayed on and unpaused, routed to Nabu, with no API errors. Nine new durable host-unit receipts were recorded. No sample or SFX-speaker audible receipt arrived during this window.

One real SFX-speaker take was already prepared by normal background work: "I heard what you said. Go ahead." became "Heard what you said, loud and clear, Go ahead, let it appear." The exact voice is `vl_31d384e6`, engine XTTS. Its WAV is 4.8313 seconds, 231,948 bytes, SHA-256 `521809a361a654690a45f2fa9f43d52d7b280286f57e550eaa688f10f9e8abb0`. Stored grade version 6 passes raw and effective acceptance, coverage is 100%, and required rap rhyme passes. Full recorded wording, voice and tint hashes agree. "Clear/appear" provides an evident rhyme, although "let it appear" is generic padding; these checks do not certify overall artistic quality.

The bank stayed at 1 ready, 1 reserved, 23 waiting, 0 suspended and 0 heard. The waiting reason was bounded writer admission, with original sources retained. The sole ready take was reserved into a complete retained programme, so it was unavailable for two later opportunities. Its row and reservation remain matched in the [queue proof](sfx-bank-queue-proof.json); reservation and a prepared chat timestamp do not prove it aired.

The sample pool was empty through 1788811793 and first appeared as 4,864 clips at the 1788811803 snapshot, approximately 356-366 seconds after the reported backend restart at 1788811437. All nine process-wide sample opportunities had already been omitted; no further opportunity occurred in the last fifty seconds. This was a cold-scan publication delay, not a shortage of suitably short material: the [read-only duration diagnosis](sfx-pool-diagnosis.json) found 3,458 cached grabbed clips at most four seconds long, with correct mounted folders. No length limit was increased and no excerpt was fabricated. The pool owner is addressing warm publication separately.

The normal preparation inventory remained 29 ready, 67 awaiting tint, 1 rewriting, 1 awaiting recording, 1 recording and 47 needing replacement. This exposes continuing tint and writer pressure; one prepared interjection is not evidence of a sustainable larger reserve.

A later [read-only FIFO check](sfx-held-queue-followup.json) at 1788811971 showed the held queue decreasing from five to four rows. The earlier 56.732-second head had left; the 94.335-second next head was actively on Nabu, and the SFX-speaker programme moved from index three to two. No failed-attempt/retry fields appeared on those rows. A separate long intro occupied the floor during the first observation, so a temporarily flat queue count did not establish a stuck head.

Observer validation: Python syntax passed; four isolated receipt/media/summary assertions passed after explicitly closing read-only SQLite connections. No live database, media or control writes were made. The first JSON capture is preserved unchanged.

Follow-up source correction (not deployed in this first capture): below two actually eligible generic responses, a task-local SFX reserve writer has one admission slot in the existing model FIFO. Shared bank eligibility excludes reservations, the 180-second same-word heard cooldown, wrong profile/voice, missing media and failed current proof; no take is consumed during the count. Above that usable floor, ordinary tint admission applies. Six targeted tests plus fourteen bank and three admission regressions pass. This improves queue access, not a promise that a model will produce a passing rhyme or that a recording engine is immediately free.
