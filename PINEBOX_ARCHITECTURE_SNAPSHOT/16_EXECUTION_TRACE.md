# Real Execution Trace

## Scope and Integrity

**OBSERVED:** This trace was captured from the live station on 2026-09-26 between 16:28 and 16:31 CDT using `/api/playout`, `/api/dj/flow`, `/api/dj/state`, `/api/director/trace`, `/api/screenplay`, and live JSONL stores. No mutation endpoint was called.

**UNKNOWN:** Current instrumentation did not provide one exact foreign key joining schedule slot -> prompt/model call -> all round lines -> assembly -> delivery. Screenplay provenance can label a model call `matched: recent`; the sample even associated a nearby gallery/transcript-repair call with a banter round. The trace below therefore separates exact observations from reconstructed control flow.

## Exact Audible Micro-Segment

The observed delivery `1c232a7c5e5f42d2` was an interjection clip, followed by a queued delivery `914e4f3c9dbc4bd6`.

| Timestamp (CDT) | Event/action | Source/function | Input | Output/state mutation | Decision/result | Next consumer |
|---|---|---|---|---|---|---|
| 16:28:13.647 | source selected for concurrent writing | `speakbox_quote`/road writer | current writing request | flow: `speakerbox`, subject from `css15.md` | source draw observed; exact RNG draw absent | prompt assembly |
| 16:28:13.752 | model write admitted | `ask_model`/`call_ollama` | 5,200-char budget, `gemma4:e2b`, temp 1.35 | flow: `draft`; model job active | temperature/seed chosen; seed not in flow row | parser/road writer |
| 16:28:19.401 and later | delivery already playing | page playback ACK -> `LinearSequencer.heard`/flow | delivery `1c232...`, listener IDs | `playing` events and corrected position | listener established audibility | health/sequence clock |
| 16:28:20.477 | one listener ended first delivery | playback ACK | delivery `1c232...` | flow `ended` | route advances independently per listener | next delivery |
| 16:28:20.498 | next clip can play | playback ACK | delivery `914e...` | flow `canplay` from `received` | browser decoder ready | playback |
| 16:28:20.502 | next clip playing | playback ACK | delivery `914e...` | flow `playing` | page listener starts media | air/flow evidence |
| 16:28:27.273 | second listener ended first delivery | playback ACK | delivery `1c232...` | final observed `ended` | sequencer can reconcile actual end | sequence/health |

At 16:28:21, `/api/playout?lean=true` described `1c232...` as route `page`, lane `interject`, producer `_dj_speak_floorless:34241`, 27.775 seconds, three lines, listener-based position, and seven ACKs. `/api/broadcast/health` reported three listeners and last heard 0 seconds ago.

## Representative Multi-Line Round Evidence

**OBSERVED:** `screenplay_rounds.jsonl` recorded a banter bundle from 16:35:00.009 to 16:36:14.472, source `ias2.md`, banked 0.033 seconds before the round stamp, nine line/action IDs, two retrieved chunks, no crystal/tint data, and no exact `takes` rows. Air evidence showed:

- Host question rendered with XTTS voice `vl_a5cc23e4`, 10.66 s; published then listener-acknowledged as stream at 16:36:02.012.
- Cohost response rendered with XTTS voice `vl_62f8434c`, 2.68 s; acknowledged at 16:36:14.596.
- A four-second board SFX and a 5.89-second SFX-guy line shared assembled media and were acknowledged at 16:36:17.051 and 16:36:21.133.
- Several later planned lines were explicitly recorded as `withdrawn`, proving script membership did not imply audibility.

## Reconstructed Control Path

1. **INFERRED:** The schedule/show loop requested a banter/caller-adjacent road. Exact slot ID was not exposed.
2. **OBSERVED:** Speakbox chunks were attached and a round record was stamped.
3. **INFERRED:** A model or previously prepared script supplied the turns. The exact call link is unavailable; nearest-call matching is not accepted as proof.
4. **OBSERVED:** Actor voices, media filenames, and durations were recorded in air rows.
5. **OBSERVED:** SFX/SFX-guy entries were positioned between spoken lines and shared the assembled media file.
6. **OBSERVED:** Page playback ACKs changed `published` evidence to listener-heard `stream` rows; unplayed tail lines became `withdrawn`.
7. **OBSERVED:** Flow, air, script, and screenplay stores retained different facets of the same period.

## Instrumentation Gaps Exposed

- No exact schedule occurrence/slot ID in the observed air rows (`sid` was empty for several interjections).
- No durable decision event for each RNG draw.
- No exact prompt-call ID on every screenplay line; nearest-call fallback can mismatch purpose.
- SFX selection score/candidate set was not joined to the final cue in the read API.
- Published and stream/heard rows can duplicate a line ID by design and require state-aware interpretation.

