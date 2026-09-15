# Assembly and the cue map

Date: 2026-09-15. Status: implemented, not wired in. Boundary 3 of
[Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md):

> Integrate accepted strips with existing saved-take preparation and mixing.
> Produce the final audio and cue map before readiness is advertised.

New files: `conversation_assembly.py`, `tests/test_conversation_assembly.py`,
and `tools/_cue_map_windows_patch.py` (a patch for the owner of `app.py` to
apply; nothing in this work changed `app.py`, the renderer, or any live
store).

## What the measurement showed

The note orders one specific replacement:

> The current stream path rescales estimated cue windows to fit the finished
> duration (`app.py:83945` onward). Replace that approximation with cue
> positions derived from actual edited sample counts.

Before writing the replacement, the station's own mixer was measured — an
impulse at a known sample through each stage of the filter graph in
`_call_concat_blocking`:

| stage | effect on length | effect on position |
| --- | --- | --- |
| per-input leg (`aresample`, tail trim, `apad`) | exact | none |
| `concat` | exact | none |
| `loudnorm=I=-11:TP=-1.0:LRA=7` | +3 frames | +1 frame |
| `alimiter=limit=0.95` | none | **+119 frames** |

The limiter's 5 ms attack lookahead delays the whole programme by a constant
120 samples at 24 kHz. **A constant delay is not a scale**, so the existing
`scale = _made / _ours` correction cannot be made right by tuning it: it is
too small at the head of a round and too large at the tail. Meanwhile the
error it was actually absorbing — the difference between a clip's length on
disk and its length after the mixer trims its welded `BOX_TAIL_MS` pad — is
not a residual at all. It is a number that can simply be measured.

So `conversation_assembly.py` measures it. Each strip is rendered through
the mixer's own per-input leg and its frame count read off the resulting WAV
header. Cue positions are integer prefix sums of those counts, plus the one
measured latency constant. Nothing is estimated and nothing is rescaled.

## The public surface

```python
from conversation_assembly import (
    assemble_conversation,   # frozen script + masters + cuts -> Assembly
    verify_assembly,         # prove an Assembly before advertising it
    stream_windows,          # the cue map in app.py's rows/clip_* shape
    cue_at,                  # player offset -> the occurrence sounding
    materialize_strips,      # strips on disk, only when something needs them
    cue_map_json,            # the durable form
    frozen_script,           # the adapter, exposed for callers
    concat_beats,            # mirror of app.py's beat draw
    measure_mix_latency,     # the calibration above, cached
    Assembly, AssemblyRefused, Extra, Occurrence, FrozenScript, Master, Cut,
)
```

`assemble_conversation(script, masters, cuts, *, extras=(), beats=None,
crackle=False, mode="sequential", media_root=None, assembly_id="",
keep_strips=False, measure_latency=True, rng=None)` returns an `Assembly`
with `.audio` (WAV bytes), `.cue_map`, `.record`, `.final_audio_hash`,
`.frame_count`, `.seconds`, `.write_audio(path)` and `.close()`. It is a
context manager; leaving the block releases the temporary strips.

Anything that cannot be **proved** raises `AssemblyRefused`, which carries
`.reason`, `.detail` and `.facts`. It is never an invitation to retry the
same inputs — it means "retake, or choose another complete ready candidate".
Reasons in use: `missing_cut`, `duplicate_cut`, `unverified_cut`,
`cut_outside_script`, `ordinal_disagreement`, `cut_out_of_bounds`,
`master_missing`, `master_changed`, `master_frames_mismatch`,
`master_rate_mismatch`, `master_not_supplied`, `unreadable_master`,
`unsupported_sample_width`, `master_empty`, `empty_strip`,
`strip_unmeasurable`, `mix_failed`, `mix_length_unexplained`,
`overlap_requested`, `unsupported_mode`, `no_revision`, `empty_script`,
`no_occurrence_id`, `duplicate_ordinal`, `duplicate_occurrence_id`,
`verification_failed`, `wrong_output_rate`, `nothing_to_mix`,
`segment_missing`, `strips_released`, `bad_field`, `no_master_media`,
`cut_without_occurrence`.

## The cue map, field by field

Top level:

| field | meaning |
| --- | --- |
| `cue_map_revision` | the shape's own version (currently `1`); the admission record pins it |
| `assembly_id` | this finished conversation's identity |
| `script_revision` | the frozen revision this was assembled from |
| `mode` | `"sequential"` — a single active spoken line |
| `sample_rate`, `channels` | `24000`, `1` — the mixer's output format |
| `frame_count` | frames in the finished file, read off its header |
| `seconds` | `frame_count / sample_rate` |
| `final_audio_hash` | sha256 of the finished WAV bytes |
| `derivation` | `"measured"`. Any other value must be treated as an estimate |
| `mix_latency_frames` | the measured constant delay of the join chain |
| `latency_measured` | false means the calibration did not run; the latency is 0 by assumption |
| `mix_residual_frames` | finished frames minus the summed measurements (≈3) |
| `tail_pad_frames` | the `BOX_TAIL_MS` pad glued on at the end |
| `body_frames` | the sum of every cue's span |
| `cues` | the ordered cues, below |
| `sequence` | the line occurrence ids in order — this is what must equal the frozen script sequence |
| `built_at` | unix seconds |
| `verified` | the verification verdict, written in by the assembler itself |

Each cue:

| field | meaning |
| --- | --- |
| `occurrence_id` | the identity. Not the text — two occurrences of identical words are different cues |
| `ordinal` | the frozen script ordinal (`-1` for an extra) |
| `kind` | `"line"` for a scripted utterance, otherwise the extra's kind (`"sfx"`) |
| `speaker`, `text` | for display |
| `start_sample` | where this line's audio begins in the **final** file |
| `speech_end_sample` | where the speech stops |
| `cue_end_sample` | where the next line begins |
| `pause_frames` | `cue_end - speech_end`: the inserted pause or seam beat |
| `start_seconds`, `speech_end_seconds`, `cue_end_seconds`, `pause_seconds` | the same four numbers in seconds |
| `exact` | true when derived from measured sample counts |
| `source` | provenance only — `take_id`, `master_hash`, `master_sample_rate`, `start_sample`, `end_sample`, `boundary_method`, `resampled`, `effects` |

**`speech_end_sample` and `cue_end_sample` are separate on purpose.** The
note requires it: "an inserted pause does not falsely start the next line".
A pause belongs to the line before it. The highlight keeps it — so the panel
does not blink into nothing between lines — and a per-line download leaves
it off, because it is the run-up to the next speaker, not this line.

**`source.start_sample` is not a mix position.** It is an offset into the
speaker's master at the master's own rate. Nothing downstream may seek in
the finished file with it. The resampling tests exist to make that concrete:
a 48 kHz master's cut offsets and its final cue positions are different
numbers for the same audio.

The `record` returned beside the cue map is the "Finished conversation" row
of the note's table — assembly id, revision, ordered cut references (master
hash plus integer offsets, **not** strip files), mix settings including the
exact beats drawn, final audio hash and frame count — and is what
`manifest_store.py` should persist.

## What was mirrored from app.py, and where

`_mix_blocking` mirrors `_call_concat_blocking` (`app.py:81956`) filter for
filter: the per-input `aresample=24000` and `aformat`, the
`areverse -> silenceremove(start_silence=CONCAT_KEEP, -50dB) -> areverse`
tail trim from #769, the varied `apad` beat at every seam but the last, the
`concat`, `loudnorm=I=-11:TP=-1.0:LRA=7`, the optional brown-noise vinyl
crackle bed, `alimiter=limit=0.95`, the write to a real seekable file rather
than a pipe (a piped WAV carries a placeholder RIFF size and every later
duration read is then wrong), the `len(blob) <= 4000` refusal from #1147,
and the closing `_wav_tail_pad(blob, BOX_TAIL_MS)` from #493/#712.
`concat_beats` mirrors `app.py:81841`; `box_tail_ms` mirrors
`box_tail_seconds`; `_wav_tail_pad` mirrors `app.py:65845`.

It is a mirror rather than an import because `app.py` is a 200k-line server
module owned by another agent and importing it starts a radio station and
writes to `data/`. `MirrorTests` in the suite keeps the mirror honest by
reading `app.py` **as text** and asserting the constants, the filter
fragments, the 4000-byte threshold and the generated leg string. Drift fails
a test rather than a broadcast.

Two deliberate divergences, both documented in the source:

- app.py returns `None` on any mixer failure so its caller can fall back to
  the turn-by-turn road. There is no such road in an assembler — "No
  incomplete conversation may be admitted" — so a failure raises.
- app.py hands a single-segment round over as it sits on disk, skipping the
  mixer entirely. A one-line conversation still goes through the whole graph
  here, so its cue map is derived and verified exactly like every other one.

## How an integrator wires it in

### Producing

```python
from conversation_assembly import assemble_conversation, AssemblyRefused

try:
    with assemble_conversation(frozen, masters, accepted_cuts) as made:
        media = made.write_audio(VOICE_MEDIA_DIR / f"{made.assembly_id}.wav")
        store.save_assembly(made.record, made.cue_map)
except AssemblyRefused as refused:
    choose_a_replacement(refused.reason, refused.facts)
```

Readiness is advertised **after** that block, never before. The assembler
has already run `verify_assembly` internally and refuses rather than
returning an unproved artifact; `cue_map["verified"]` carries the verdict.

### Admitting

`broadcast_admission.py` needs "Playback occurrence ID, sequence positions,
assembly ID, final audio hash and cue map revision". Everything but the
playback occurrence id is on the cue map: `assembly_id`,
`final_audio_hash`, `cue_map_revision`, and `sequence` for the ordered
positions. Re-run `verify_assembly(assembly, frozen_script)` at the gate if
the artifact has been round-tripped through storage — it is cheap and it is
the last place a swapped file can be caught.

### Playing out and displaying

`stream_windows(cue_map)` returns one row per cue in the shape
`_speak_turns_floorless` already builds:

```python
{"id", "ordinal", "kind", "who", "from", "until", "speech_until", "tail", "exact"}
```

`from`/`until` map to `clip_from`/`clip_until` and `tail` to `clip_tail`.
Match rows to cues **by id**, never by position — #1330's lesson is that two
lists of the same shape, wrongly paired, is a silent fault that puts the
highlight on one line and the audio of another. If any row lacks a cue, fall
back to the estimate for the **whole round**; never mix two timelines.

`cue_at(cue_map, seconds)` answers "which occurrence is sounding at this
player offset", which is what the Script view needs for boundary 5: "Use the
selected player's actual file and offset, mapped through its cue sheet, to
identify the active occurrence."

### The patch for app.py

`tools/_cue_map_windows_patch.py` is written for the owner of `app.py`; it
was never run against the share. It makes three edits inside the coalesced
burst branch of `_speak_turns_floorless`:

1. the seam beats are taken from `ready_meta["cue_map"]["mix"]["beats"]`
   when one is supplied, so the re-mix reproduces the file the assembler
   measured (#778's rule one step earlier);
2. before the rescale, the supplied cue map is adopted — but only if it
   names every row by id **and** its own duration agrees with the finished
   clip to within 30 ms. `_cue_exact` records the outcome, `air_at` is set
   from the measured windows, and both outcomes are written to the pipeline
   log. The rescale itself is then guarded by `not _cue_exact`;
3. `clip_tail` — the point a per-line download cuts at — comes from the cue
   map's own pause, unscaled, because nothing was scaled.

With no cue map, or a cue map that does not prove out, today's behaviour is
byte-for-byte unchanged. Run `--check` first; `--revert` undoes it;
applying twice is a no-op. The script refuses to write if any anchor is
missing or duplicated, and compiles the result before it touches the disk
that serves the station.

## Tests

`python -m pytest tests/test_conversation_assembly.py` — 46 tests, all
passing. Fixtures are pure tones, one frequency per occurrence, synthesised
into a fresh temp directory and removed; cue positions are checked
**acoustically** by reading the tone back out of the finished mix at the
position the cue map claims, so a cue map that is internally consistent but
describes the wrong audio fails. Nothing writes to `data/`, and no test
imports `app.py` or any module that appends to the script ledger — the
2026-09-14 audit records that existing fixtures have appended rows to the
live document.

## Reconciliation with the other boundary-3 modules

The four modules were written in parallel, so `conversation_assembly.py`
reads every foreign record through an alias adapter at the top of the file
rather than naming fields directly. `script_manifest.py`,
`line_alignment.py` and `broadcast_admission.py` landed while this was being
written and the adapter has been reconciled against them as they are
actually spelled. Five differences were real and are now handled:

| what differed | how it is handled |
| --- | --- |
| `script_manifest` hashes are `sha256:<64 hex>`; this module hashes bytes to bare hex | `bare_hash()` reduces both to the hex before anything is compared; `finished_conversation_kwargs` emits the prefixed form back |
| `master_recording` spells them `audio_sha256`, `frame_count`, `media_ref` | all three aliased |
| `line_cut` spells it `master_sha256` and carries `cut_id` | both aliased; `cut_id` is carried through to the cue and the record |
| acceptance is `state` in `("pending", "accepted", "rejected")` for `script_manifest`, but `line_alignment.LineCut.verification` is a mapping of **evidence** with no `ok` key | `state` is authoritative when present; otherwise an explicit verdict; otherwise a cut carrying evidence is accepted, because `line_alignment` returns refused cuts in `.refusals` rather than in `.cuts` |
| `script_manifest.cue_entry` keeps `cue_start_sample` and `speech_start_sample` apart | both are emitted (equal in strict sequential mode, since a strip is trimmed at its tail and never at its head), along with `source_frames` |

Two emitters hand the output on without the caller rewriting it:

```python
record = script_manifest.finished_conversation(
    **conversation_assembly.finished_conversation_kwargs(made))
```

and `manifest_cue_entries(cue_map)` for the cue rows alone. A test drives
the whole chain — `script_manifest.frozen_script` / `master_recording` /
`line_cut` into `assemble_conversation`, out through
`finished_conversation`, past `validate_assembly`, into
`broadcast_admission` — and asserts the admitted sequence positions equal
the frozen sequence and the admitted `final_sha256` is this audio's hash.

Two things callers should know about `script_manifest`'s own gates, learned
from that test: a cast entry needs an `engine`, and a cut whose
`boundary_method` is not one of `("renderer_boundary", "alignment",
"manual")` is refused outright with `cut_boundary_ambiguous`. Silence and
estimates are not evidence of which line was spoken.

`manifest_store.py` was not inspected; the durable form offered here is
`cue_map_json()` plus the `record` dict.

## What is not done here

Overlap. `mode` accepts only `"sequential"`; anything else, and any
negative pause, is refused by name rather than quietly flattened. The note
makes overlap an explicit script decision, and there is no script vocabulary
for it yet.

Nothing is wired in. No producer calls `assemble_conversation` yet, and the
`app.py` patch has not been applied.
