# System2 saved-media adapters — 2026-09-08

`system2_media.py` adds verified saved-recording adapters for whole dialogue,
single-line ads/manager reads/station IDs, produced ads, and individual
record-bound introductions/send-offs. No adapter calls a writer or voice engine.

Inventory reads actual bytes for SHA-256 and measures the recording duration;
advertised metadata durations are not accepted as proof. Proof caches include
file identity, size, mtime and ctime, with a second stat after hashing/decoding.
Only owned `/media/` and `/ads-audio/` files are served, with fresh signatures.
Every saved take position survives, including repeated positions sharing one file.

Pantry singles require exact original text/voice/key identity, including full-text
hash verification when the pantry's text preview is truncated. Produced ads need
an exact retained ad-book transcript and voice. Source readiness remains the
application's existing quality contract; the adapter does not manufacture grades.
Track sides additionally preserve the original parent/side identity and require
the matching record and actual intro/outro position at delivery.

Playback rechecks source/media identity after inventory and after waiting for the
floor. Pantry takes use the existing strict saved-stream path. Produced ads use
one exact media object, with the reservation carried into its page/box receipt.
A device submission reserves ownership before awaiting transport: some transports
return only when playback finishes. A known failed submission returns false for
runtime release; cancellation after submission remains ambiguous and owned.
Publication/submission is never a heard receipt. Muted, interrupted or unrelated
device meters receive no audible credit. Browser completion uses the existing
audible acknowledgement path. Saved audio files remain unchanged.

Validation: 18 adapter tests plus the current 30 planner tests passed together
in 3.178 seconds using fresh data and import-cache directories. All media was
temporary fixture audio. No live playback, model request, volume write or deploy
was performed for this work.

## Integration findings passed to the runtime owner

- Whole-entry-only readiness excluded all raw single-line stock. Runtime now
  consumes the common adapter result.
- Candidate slot identity must use the store's singular `slot_id`, not `slot_ids`.
- Full duration must be charged before submission, not again after a blocking
  device playback call. The runtime releases known failed submissions separately.
- Produced-ad source obligations belong at complete audible `_ready_round_ack`,
  never page publication or a successful deliberately muted transport return.
- A queued guest needs an immutable third-seat name/persona/voice and D turns.
  The old `set_guest` mutates global settings. Runtime owner implemented task-local
  work context, persisted guest voice and a preparer override instead.

## One-hour repetition ingress

Existing legacy gates alone do not enforce the new exact one-hour rule:
`_dj_speak_floorless` exempts checked/manual and ad/station-ID/reply/call paths;
`rerun_check` can stand down; `_banter_air` explicitly permits recorded repeats;
the strict saved playlist precedes old per-turn checks. A System2 reservation
check must guard the final complete playlist before publication independently of
editorial acceptance. Only the same validated reservation may exclude its own
in-flight/ACK evidence. Page and device receipts must both register exact spoken
text, with explicit ownership, and may not credit zero-gain audio. These app/store
integration hooks remain owned by the runtime agent, not this adapter module.

Limits: no new audio archive/join endpoint is supplied here. Signed line URLs are
available from proof. Device receipts are the existing transport evidence, not an
independent acoustic measurement. Uncaptured legacy transcript-to-recording
relationships are refused rather than inferred.
