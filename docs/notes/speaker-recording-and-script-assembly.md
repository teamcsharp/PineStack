# Recording speakers and assembling conversations

Date: 2026-09-14. Status: proposed architecture following source inspection;
this note does not change recording or playback behavior.

## Operator intent

Write the conversation first. Each performer records their complete part in
one session. Cut those performances into their scripted lines, then assemble
the conversation in its original reading order. The broadcast and Pine Box
Script view must follow that same order.

The operator selected one complete conversation or segment per session.
Several frozen segments could later share a performer session as a separate
optimization, without combining their readiness or broadcast order.

The previously selected fallback policy still applies:

> Choose a ready replacement before it enters the committed script, then play it in order.

## What already exists

Source references describe the code inspected on this date; line numbers can
move. Existing comments sometimes call grouped per-line rendering a
continuous session. That does not mean one continuous generated performance.

| Existing component | Actual behavior |
| --- | --- |
| `recording_sitting`, `app.py:18837` | Pools up to six scripts and schedules work by performer. A time budget can interrupt the sitting; separate engine booths can run concurrently while paused. |
| `_round_chunks`, `app.py:30953` | Produces the spoken chunks in conversation order, including text normalization and performance additions. |
| `larder_prepare`, `app.py:32214` | Groups those chunks by voice, but calls `voice_render_any` for each chunk separately. |
| `reconcile_round_takes`, `app.py:32190` | Reconstructs takes in their original script order, including repeated wording. |
| `_ready_round_takes`, `app.py:71657` | Requires a complete contiguous sequence and matching saved audio, speaker and text. |
| `_call_concat_blocking`, `app.py:81956` | Joins ordered clips, applies explicitly chosen gaps and audio processing. |
| `System2Media`, `system2_media.py` | Verifies media bytes and duration and rechecks a staged recording before delivery. |

These are useful foundations. The missing production contract is an explicit,
durable relationship between a frozen script, each speaker's performance,
its exact cuts, and the final conversation file.

## A session and a continuous take are separate capabilities

The operator's literal model is a continuous speaker take followed by cutting.
Do not declare that implemented merely by regrouping independent TTS calls.

Current local adapters do not provide the boundaries needed for that model:

- `voice_render_any` splits inputs above `VOICE_MAX_CHARS` (default 800) and
  rejoins the resulting audio (`app.py:8373` onward).
- The F5 path additionally splits longer text into roughly 280-character
  pieces (`app.py:12454` onward).
- Current voice adapters return audio without an utterance timestamp map.
- A code note at `app.py:32685` records a previous unsuccessful experiment:
  changing silence thresholds produced different cuts, including a trailing
  tail incorrectly counted as a separator.

For a true continuous performance, add a renderer contract that supplies
reliable line boundaries, or an alignment stage that matches the known script
to the recording. Silence alone cannot establish which line was spoken.
Alignment must reject missing, repeated or mismatched speech; a timestamp
assigned to every input word does not itself prove the audio contains it.

A session implemented with bounded engine segments is an alternative:
retain boundaries at synthesis time and save a speaker master with its cut
map. This avoids guessing cuts, but is still segmented synthesis and must be
described that way. It does not establish the prosody or speed benefits of a
single continuous performance.

The inspected host services impose additional limits. The XTTS adapter in
`reachy-gateway/voice_clone_server.py` truncates requests to 1,000 characters
and enables internal text splitting. It already caches speaker conditioning
by reference and settings; a read-only health request reported five cached
references. The voice director also chunks long readings. Removing the
station's input cap alone would therefore be insufficient and could lose
words silently.

The existing voice lab has a useful starting point: its ingestion path calls
faster-whisper with word timestamps (`voice-lab/app.py:931` onward). Its
verification route returns transcript and quality metrics without timestamps.
No inspected endpoint accepts an authoritative script plus recording and
returns validated line cuts. Word recognition timing is evidence for an
alignment implementation, not proof that one is already available.

Measure both approaches before claiming that larger requests are faster.
Record production time, accepted audio duration, retries, missing/repeated
speech, cut accuracy and listening quality using the same scripts and cast.

## Proposed production flow

```text
Finalized conversation and cast
              |
Frozen production script with ordered line identities
              |
One recording session per performer
              |
Speaker masters + verified line cuts
              |
Assembly in original script order
              |
Finished audio + exact line cue sheet
              |
Ready candidate selection / replacement
              |
Atomic commitment to the broadcast sequence
              |
One playback controller -> actual player position -> Script highlight
```

Freezing a production script authorizes recording; committing a broadcast
sequence authorizes playback. They are distinct boundaries. A candidate can
be abandoned or replaced before broadcast commitment without moving any
line already admitted to the reader.

### 1. Freeze the performance contract

Assign a revision and an ordered occurrence ID to every utterance, including
two occurrences with identical words. Freeze the actual spoken text, cast,
pronunciation changes and performance instructions before recording.
Retain the relationship between a displayed line and any internal render
chunks. Provide surrounding dialogue as context where the renderer supports
it while identifying exactly which actor's words are to be spoken.

Script changes create a new revision. Completed audio is reusable only when
its full performance contract remains compatible. New work must never
overwrite a take pinned by an admitted broadcast occurrence.

### 2. Own and persist performer sessions

Each session records its actor, script revision, ordered assignments, renderer
configuration, current state and accepted takes. Resume from verified work
after interruption. An engine capacity limit can constrain execution without
losing session identity or treating an incomplete performance as ready.

A whole-conversation job should finish useful conversations rather than
leave every candidate partly recorded. Scheduling across several scripts is
an optimization after completeness and recovery are correct.

### 3. Save exact cut manifests

Use integer sample positions and an explicit sample rate for source cuts:

| Record | Required identity and evidence |
| --- | --- |
| Frozen script | Revision, ordered line occurrence IDs, speaker and exact spoken text |
| Performer session | Session ID, revision, actor/voice, engine configuration, assignments and state |
| Master recording | Take ID, immutable audio hash, sample rate, frame count and media reference |
| Line cut | Occurrence ID, original ordinal, master hash, start/end sample, boundary method and verification result |
| Finished conversation | Assembly ID, revision, ordered cut references, mix settings, final audio hash and final cue map |
| Broadcast admission | Playback occurrence ID, sequence positions, assembly ID, final audio hash and cue map revision |

Validate source bounds, text coverage, actor identity and exactly one accepted
cut for each required occurrence. Reject ambiguous boundaries. A failed cut
requires a retake or another complete ready candidate before commitment.

The existing pantry key hashes engine, voice and text (`app.py:13618`). It
cannot distinguish two differently performed occurrences of the same words.
Keep content caching as optional reuse; manifest identity must distinguish
performances. Adapt reconciliation and ready-take validation to consume
verified occurrence-specific cuts rather than infer them from text hashes.

### 4. Assemble and validate before admitting

The assembler consumes original script ordinals, never recording completion
order or filesystem order. In a four-line exchange, actor A can record lines
1 and 3, and actor B lines 2 and 4; assembly must produce 1, 2, 3, 4.

Retain the existing mixer where practical. Compute the final cue map from
the actual cuts and processing, including resampling, inserted pauses,
trimming and effect tails. A source master offset is not a final mix offset.
Duration-changing effects require updated cue positions. Make overlap an
explicit script decision; the initial strict sequential mode should have a
single active spoken line.

The current stream path rescales estimated cue windows to fit the finished
duration (`app.py:83945` onward). Replace that approximation with cue positions
derived from actual edited sample counts. Retain separate speech-end and
cue-end positions so an inserted pause does not falsely start the next line.

Verify the complete final artifact before admission. Playback must not write,
record, choose a replacement, or reconstruct the line sequence as it airs.
The sequencer and renderer changes in the earlier audit are still required;
speaker sessions alone do not fix the observed display bugs.

### 5. Keep diagnostics small and traceable

Extend the existing incident capture with references to the relevant script
revision, performer session, accepted cut, assembly and playback occurrence.
Record transitions and refusals, including the reason for any pre-admission
replacement, and keep a bounded window around the incident.

Include the expected next occurrence, actual player file/position and selected
display line. Resolve exact text and source cuts through their manifests.
Save repeated text once. Link retained audio instead of embedding waveform
data in reports. An unavailable reference must be reported explicitly.

Store the master plus cut offsets; materialize individual strip files only
when an adapter or editor needs them. Pin artifacts needed by current
playback and retained incidents, with an explicit retention policy, so a
compact report does not become a collection of broken evidence links.

## Implementation boundaries and acceptance

1. Add pure script/session/cut-manifest validation and durable recovery,
   isolated from live runtime stores.
2. Validate a continuous-take renderer and alignment path on a bounded set of
   complete conversations. Compare against the current segmented approach;
   retain explicit mode identity and reject uncertain cuts.
3. Integrate accepted strips with existing saved-take preparation and mixing.
   Produce the final audio and cue map before readiness is advertised.
4. Implement the admission gate and sole playback controller described in the
   sequential-playout audit; migrate every producer and recovery route.
5. Drive the Script view from the admitted cue map and actual playback
   occurrence/position. Extend incident references at these same boundaries.

Acceptance includes actors finishing out of order; duplicate wording;
missing, repeated or dropped words; corrupt or changed masters; revision
changes; interrupted sessions; retries; duration-changing effects; and
stale player receipts. No incomplete conversation may be admitted. The final
cue sequence must equal the frozen script sequence, and actual dispatch must
follow the committed order across conversations as well as within one file.

This investigation was read-only apart from documentation. No long-take
benchmark, alignment quality test or new playback enforcement was performed.

Related: [Sequential script and playout audit](../sequential-script-playout-audit-2026-09-14.md)
and [implemented incident diagnostics](script-report-diagnostics.md).
