# SFX broadcast observation

Read-only observation of the normal deployed station. No model, TTS, playback, route, or volume requests were issued.

Observed 180.08 seconds in 19 snapshots. Completion: complete.

Bank before: `{"total": 24, "ready": 6, "waiting": 18, "suspended": 0, "reserved": 0, "heard": 4, "why": "The SFX speech reserve is ready"}`.

Bank after: `{"total": 24, "ready": 7, "waiting": 17, "suspended": 0, "reserved": 0, "heard": 5, "why": "A bounded writer is busy; the original source remains queued"}`.

Cadence deltas: `{"heard_units": 6, "heard_samples": 3, "sample_due": 3, "sample_omitted": 0, "guy_due": 1, "guy_omitted": 0}`. New durable host receipts: 6; sample receipts: 3; bank heard delta: 1.

Preparation reasons: A bounded writer is busy; the original source remains queued; The SFX speech reserve is ready

[Exact snapshots, saved proof and receipts](sfx-continuity-live.json).

- Due/omitted counters describe planning in the current process, not audible delivery.
- Heard counters and durable receipts use production playback acknowledgements; no microphone or acoustic measurement was made.
- A sampled chat row can be prepared or held; it is not proof of being heard.
- Bank totals apply to the current voice/profile. A profile change or restart can invalidate simple deltas.
- This short observation cannot establish sustained preparation throughput or station-wide audio quality.

The final deployment restarted at 1788813695.43023 after a quiet interval. This capture covers 1788813773.107334 to 1788813953.187, with 19 snapshots over 180.080 seconds and no API errors. The complete 893-test Python suite and 95 Node checks passed before deployment. Earlier negative observations remain intact in [the initial pool-delay report](sfx-broadcast-observation.md) and [the continuity-bypass report](sfx-broadcast-final.md).

Ten new durable row receipts comprise six original host units, three samples and one SFX-guy line. All six host rows have kind `emergency_host`; matching row IDs and audio offsets link the additions to those same three continuity programmes. Samples followed each pair of host units, and the guy followed the fourth unit. No sample or guy opportunity was omitted in this capture. This confirms the previously missing continuity path now participates in the same cadence as ordinary speech.

| Programme timestamp | Original host audio | Sample audio | Guy audio | Receipt sequence |
| --- | ---: | ---: | ---: | --- |
| 1788813778 | 18.138 s | 0.280 s | None due | 96-98 |
| 1788813842 | 13.954 s | 1.380 s | 5.060 s | 99-102 |
| 1788813903 | 13.004 s | 1.920 s | None due | 103-105 |

The guy receipt `618aa2f6fd5641c9b76d5095b4fef79b` carries the configured voice `vl_31d384e6` and the complete stored line: "I'm listening, keep the flow, Let the talking continue, let it grow." Its exact five-second WAV, text hash, voice binding and stored Crystal coverage are in the JSON. The reservation cleared when the receipt arrived; cumulative bank plays increased from four to five. These are production playback acknowledgements, not acoustic measurements.

The current-voice bank grew from six to seven recorded takes during this window, including four generic and three topical takes at the end. All seven have distinct nonempty WAV hashes, matching full recorded text and voice, and stored 100% tint coverage. A snapshot at 1788813873 captured an actual `sfx_tint_reserve` job active on `gemma4:31b` alongside ordinary waiting tint jobs. The newly completed generic take is "You have my attention, the focus is caught, Now finish the thought." This is normal background preparation, without a diagnostic generation or TTS request. Readiness totals include takes in replay cooldown; seven recorded takes do not imply seven immediately selectable generic responses.

The verified short-sample pool was never empty: 5,059 initially, 4,410 finally, and between 4,383 and 5,069 during progressive refreshes. All three acknowledged samples were below the unchanged four-second cap. Station output stayed on, unpaused and routed to Nabu; the held queue remained empty. Stored programme readiness increased from 29 to 30 while one gallery recording completed. Sixty-six stored items still needed tint approval, and one accepted item remained awaiting recording in the final pipeline snapshot.

The evidence establishes cadence participation and background stock growth in this window, not uninterrupted audio or sustained throughput. These emergency pairs remain separated by quiet intervals and do not erase ordinary programme debt. Editorial quality is also distinct from machine acceptance: unused topical stock includes the awkward "A mood that's truly then" and the ungrounded "the villain just witnessed them." The heard generic line supplies a clear flow/grow rhyme, but this report does not certify all bank wording as polished.
