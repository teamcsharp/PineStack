# Script, session and cut manifests, implemented

Implemented 2026-09-15. Boundary 1 of
[Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md):
"add pure script/session/cut-manifest validation and durable recovery,
isolated from live runtime stores."

Two new modules and one test file. Nothing existing was edited; no route, no
renderer, no runtime store. Nothing here runs on the station yet: these are
the records and the refusals the recording, alignment, assembly and admission
work will be built on.

- `script_manifest.py` - the six record types, their identities, and pure
  validators. No disk, no clock the caller cannot pass in, no `app`.
- `manifest_store.py` - the same records on disk under `data/manifests`, with
  atomic writes, an append-only event log and recovery. Imports
  `script_manifest` and the standard library, nothing else.
- `tests/test_script_manifest.py` - the note's acceptance list, 57 tests,
  writing only to a temporary directory.

Run them the way the repo runs Python tests, from the repository root:

    python -m pytest tests/test_script_manifest.py -q

## What the records are

| Record | Constructor | Identity it carries |
| --- | --- | --- |
| Frozen script | `frozen_script` | content-derived `revision`, ordered `occurrence_id` per utterance, speaker, exact spoken text, pronunciations, instructions, context, render chunks, `performance_digest` |
| Performer session | `performer_session` | session id, revision, actor, voice, engine, engine config, ordered assignments, state, accepted takes |
| Master recording | `master_recording` | take id, immutable `sha256:` audio hash, sample rate, frame count, channels, media reference, explicit `continuous`/`segmented` mode |
| Line cut | `line_cut` | occurrence id, original ordinal, take id, master hash, sample rate, integer start/end sample, boundary method, verification, state |
| Finished conversation | `finished_conversation` | assembly id, revision, ordered cut ids, mix settings, final hash, final rate and frame count, cue map, `cue_map_revision` |
| Broadcast admission | `broadcast_admission` | admission id, unique playback occurrence id, sequence positions, assembly id, final hash, cue map revision |

Three identities do the work the note asked for:

- `occurrence_id(revision, ordinal, actor, text)` includes the ordinal, so
  two occurrences of identical words are different records. The station's
  pantry key (`app.py:13618`) is reproduced as `content_cache_key` and
  documented as optional content reuse only: a test asserts the two
  occurrences collide under that key and never under this one.
- `performance_digest(line, cast_entry)` is the whole performance contract
  without the line's position: text, actor, voice, engine, engine config,
  pronunciations, instructions, context and chunks. `carry_over` reuses
  completed audio across a revision only where this digest is unchanged, and
  matches repeated wording in reading order rather than by text hash.
- `script_revision` is derived from the content, so any change to the
  contract is a new revision and an in-place edit of a stored script fails
  validation.

A cue entry keeps `cue_start`, `speech_start`, `speech_end` and `cue_end`
separately, plus the cut's own `source_frames`, so an inserted pause does not
start the next line and a duration-changing effect is visible rather than
assumed. An assembly must declare `cue_source: "measured"`; `"estimated"` or
`"rescaled"` - the approximation at `app.py:83945` - is refused.

## Storage layout

    data/manifests/events.jsonl                     every event, in order
    data/manifests/<revision>/script.json
    data/manifests/<revision>/events.jsonl
    data/manifests/<revision>/sessions/<session_id>.json
    data/manifests/<revision>/masters/<take_id>.json
    data/manifests/<revision>/cuts/<cut_id>.json
    data/manifests/<revision>/assemblies/<assembly_id>.json
    data/manifests/<revision>/admissions/<admission_id>.json

Each record file is written to a unique temporary name in its own directory
and replaced into place, the pattern `courier_write` and
`ScriptReportStore._write` already use. Event lines are appended, flushed and
fsynced, never rewritten. An event is `{seq, at_ms, kind, revision, subject,
state_from, state_to, ok, reasons, detail}`; refused writes are recorded too,
so the reason a take was not acceptable survives the decision to retake it.

`ManifestStore(root="data/manifests")` takes its root as a constructor
argument and every test passes a temporary directory. The store never touches
`data/` outside that root and never touches the script ledger.

`rebuild()` reads the whole tree back and returns the view plus a `damaged`
list: an unreadable record, a record whose id disagrees with its file name, a
revision directory with no frozen script, a stored script that no longer
validates, a torn final line in an event log. Undamaged records are still
recovered; damage is named, never dropped.

`resume_session(session_id, revision, read_audio=None, commit=True)` rebuilds
an interrupted session from the takes that still verify - each accepted cut
must exist, match its occurrence, be accepted, validate against its master
and the frozen script, and, when `read_audio` is supplied, its master must
still hash to its recorded audio. Everything else is returned as dropped work
with a reason, and the resumed session is written with only the verified
takes.

## Refusals

Every refusal is `{"code", "reason", "where"}` inside a result
`{"ok", "refusals", "reasons", "reason", ...extras}`. No validator returns a
bare `False`, and every reason is a sentence.

Frozen script: `script_malformed`, `script_empty`, `script_no_cast`,
`script_empty_line`, `script_unknown_actor`, `script_ordinal_gap`,
`script_duplicate_occurrence`, `script_occurrence_mismatch`,
`script_revision_mismatch`, `script_sequence_mismatch`,
`script_revision_frozen` (store: a second, different script for one
revision). Malformed input to a constructor raises `ManifestError` with the
same kind of sentence.

Session: `session_malformed`, `session_revision_mismatch`,
`session_unknown_actor`, `session_contract_mismatch` (voice/engine is not the
frozen cast's), `session_unknown_state`, `session_no_assignments`,
`session_unknown_occurrence`, `session_wrong_actor`,
`session_duplicate_assignment`, `session_assignments_unordered`,
`session_accepted_unassigned`, `session_accepted_missing_cut`,
`session_accepted_wrong_cut`, `session_accepted_unaccepted_cut`,
`session_incomplete`, `session_abandoned` (store: resuming abandoned work).

Master: `master_malformed`, `master_no_sample_rate`, `master_no_frames`,
`master_no_hash`, `master_no_media`, `master_unknown_mode`,
`master_wrong_session`, `master_actor_mismatch`, `master_revision_mismatch`,
`master_unknown_actor`, `master_hash_mismatch`, `master_unreadable`.

Line cut: `cut_malformed`, `cut_unknown_occurrence`, `cut_ordinal_mismatch`,
`cut_unknown_state`, `cut_wrong_master`, `cut_master_mismatch`,
`cut_master_missing`, `cut_sample_rate_mismatch`, `cut_not_integer_samples`,
`cut_empty_span`, `cut_out_of_bounds`, `cut_boundary_ambiguous` (silence,
thresholds, estimates, or a boundary reported ambiguous),
`cut_no_text_evidence`, `cut_actor_mismatch`, `cut_words_missing`,
`cut_words_repeated`, `cut_words_extra`, `cut_text_coverage`,
`cut_duplicate_id`, `cut_duplicate_accepted`, `cut_missing_for_occurrence`,
`cut_overlap_ambiguous`.

Assembly and cues: `assembly_malformed`, `assembly_revision_mismatch`,
`assembly_no_hash`, `assembly_sequence_mismatch`,
`assembly_cut_list_mismatch`, `assembly_cut_missing`, `assembly_incomplete`,
`mix_sample_rate_mismatch`, `cue_map_estimated`,
`cue_map_stale_for_effects`, `cue_not_integer_samples`, `cue_span_invalid`,
`cue_out_of_range`, `cue_overlap`, `cue_position_invalid`,
`cue_position_out_of_range`, `cue_position_unmapped`.

Admission and receipts: `admission_malformed`, `admission_wrong_assembly`,
`admission_audio_mismatch`, `admission_cue_revision_mismatch`,
`admission_no_occurrence`, `admission_occurrence_reused`,
`admission_unverifiable`, `admission_incomplete_assembly`,
`admission_sequence_incomplete`, `admission_sequence_order`,
`admission_sequence_invalid`, `admission_sequence_gap`,
`admission_assembly_missing` (store), `receipt_wrong_occurrence`,
`receipt_wrong_assembly`, `receipt_wrong_audio`, `receipt_stale_cue_map`,
`receipt_undated`, `receipt_expired`.

Reuse and pinning: `contract_changed` (per line, naming what changed),
`pinned_take_overwrite` ("new work must never overwrite a take pinned by an
admitted broadcast occurrence").

Store and recovery: `unknown_revision`, `unknown_session`,
`record_wrong_kind`, `record_no_id`, `record_no_revision`,
`take_unverified`, and the damage codes `script_missing`,
`script_unreadable`, `script_invalid`, `record_unreadable`,
`record_id_mismatch`, `event_unreadable`, `log_unreadable`.

## What a future integrator calls

Recording a conversation, in order:

1. `sm.frozen_script(conversation_id, cast, lines)` then
   `store.put_script(script)`. That freeze authorizes recording and nothing
   else.
2. `sm.performer_session(session_id, script, actor)` then
   `store.put_session(session)`. One session per performer per revision.
3. `sm.master_recording(...)` with the real hash, sample rate and frame count
   of the saved audio, then `store.put_master(master)`. Say `continuous` only
   for one continuous performance; regrouped per-chunk renders are
   `segmented`.
4. `sm.line_cut(...)` per scripted line, then `store.put_cut(cut)`. An
   accepted cut must validate; a pending or rejected cut is stored with the
   reason it failed, which is the retake trail.
5. Update the session with `accepted` and state `complete`, and store it
   again. After an interruption call `store.resume_session(...)` instead.
6. `sm.finished_conversation(...)` with a cue map measured from the actual
   edited sample counts, then `store.put_assembly(assembly)`.
7. `sm.broadcast_admission(admission_id, assembly=assembly,
   start_position=n)` then `store.put_admission(admission)`. That commit
   authorizes playback.

Playback and display call `sm.validate_playback_receipt(admission, receipt,
assembly=assembly, max_age_ms=...)`, which refuses a receipt from a previous
airing, a different file or an older cue map, and otherwise returns the
occurrence and ordinal the playhead is actually inside. `sm.cue_lookup` maps
a sample position on its own.

Before replacing any recorded work, take `store.pins()` and call
`sm.check_overwrite(kind, identifier, existing, replacement, pins)`. The
store already does this on every write; a producer that builds candidates
should check before it spends the time.

`sm.carry_over(old_script, new_script, {occurrence_id: cut_id})` answers
"what survives this revision" and names every line that must be re-recorded.

## Limits

- Text coverage is word-level evidence computed by `difflib` against a
  transcript the caller supplies. It refuses missing, repeated and foreign
  words, but it is not an aligner: nothing here produces cuts, and boundary
  method `alignment` is only accepted with a transcript attached.
- The modules never read audio. `verify_master_bytes` and the `read_audio`
  hook in `resume_session` are the only places bytes enter, and the caller
  supplies them.
- The pantry cache, `reconcile_round_takes` and `_ready_round_takes` are
  untouched; adapting them to consume verified occurrence-specific cuts is
  boundary 3.
- Strict sequential assembly only: overlapping cues are refused rather than
  described. Deliberate overlap remains an explicit script decision for later.
- Retention and pinning of media files is not implemented; `pin_index` says
  which takes an admission holds, but nothing deletes or keeps files yet.

Related: [Sequential script and playout audit](../sequential-script-playout-audit-2026-09-14.md).
