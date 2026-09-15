# The admission gate, the one playout controller, and the Script view

Date: 2026-09-15. Status: built and tested; **not applied to the live
`app.py` and not deployed**. The station was broadcasting throughout.

This implements boundaries 4 and 5 of
[Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md)
against the "Proposed architecture", "Admission", "Playback", "Display" and
"Recovery" sections of the
[sequential script and playout audit](../sequential-script-playout-audit-2026-09-14.md):

> 4. Implement the admission gate and sole playback controller described in
>    the sequential-playout audit; migrate every producer and recovery route.
> 5. Drive the Script view from the admitted cue map and actual playback
>    occurrence/position. Extend incident references at these same boundaries.

## The boundary, in one sentence

> Choose a ready replacement before it enters the committed script, then
> play it in order.

Planning may change its mind as often as it likes. The admitted reading
order may not change at all. Everything below is the line between the two.

## What was built

| Thing | Where | What it is |
| --- | --- | --- |
| The admission store and sequencer | `broadcast_admission.py` (new, 1614 lines) | The only thing in the station allowed to say a broadcast occurrence exists |
| The app.py integration | `patch_admission.py`, outside the repository | An anchored, idempotent, observe-only patch the **caller** applies |
| The Script view | `desktop/renderer/script-page.js`, `script-page.css` | Reads the committed sequence and the player's actual file/offset |
| Tests | `tests/test_broadcast_admission_2026_09_15.py` (66), `tests/test_admission_transport_patch_2026_09_15.py` (25), `tests/test_script_admission_view_2026_09_15.cjs` (28) | |

Nothing in `broadcast_admission.py` imports `app.py`, opens a socket,
renders audio or touches a live store. It is given a directory and a clock
and it is told things.

## The controller's public surface

```python
controller = PlayoutController.open(root, resolve_audio=..., mode="observe")
```

**Producers submit; they never start broadcast audio.**

| Call | What it does |
| --- | --- |
| `submit(candidate)` | Offers material. Nothing is committed. |
| `verify(candidate)` | Is the final audio available and are its ordered cue offsets known? |
| `admit(candidate, alternatives=..., reservation=..., origin=...)` | **Commits, atomically**: occurrence id, ordered positions, exact audio identity, cue sheet. Chooses a ready replacement from `alternatives` here, and records why. |
| `admit_interruption(candidate)` | Admits at a future safe boundary; never rewrites a committed position. |
| `reserve_position(lane=, reason=)` / `release_reservation(id, why)` | Decides a random SFX's slot **before** the affected material is admitted. The reader will not advance past an unfilled slot. |
| `withdraw(occurrence_id, why)` | Pulls an admitted occurrence before dispatch. Its **position stands** — the script keeps the marked hole. |

**One controller owns dispatch and advancement.**

| Call | What it does |
| --- | --- |
| `gate(lane=, path=, sig=, producer=, reply=, ...) -> Verdict` | The question both transports ask. |
| `begin(occurrence_id, generation=)` | Explicit dispatch of an occurrence the caller holds. |
| `record_delivery(oid, outcome, evidence=, generation=)` | `delivered` / `accepted` / `blocked` / `interrupted` / `uncertain` / `failed`. |
| `acknowledge(oid, listener=, event=, position_s=, generation=)` | A player receipt. Bounded to 24, and never a verdict on its own. |
| `next_occurrence()` / `advance(generation=)` / `ready_buffer(n)` | The reading order, and the buffer ahead of the reader. |
| `reconcile(media=, position_s=, generation=)` | What the player says it is actually sounding, mapped to an occurrence and a cue. |
| `cue_at(oid, position_s)` | An actual offset through the committed cue sheet. |

**Ownership.** `generation` (property) and
`bump_generation(reason)`. A route change or a restart bumps it; anything
still in flight becomes `uncertain`, never `delivered`; a message carrying
an older generation is refused by name (`stale_generation`) and counted.

**Reading.** `cue_map(limit=)` (the Script view's payload),
`occurrence(oid)`, `references(oid="")` (the incident reference set),
`refusals(limit=)`, `stats()`, `checkpoint()`, `resume()`.

### The verdicts it can return

`admitted`, `route`, `exempt`, and six refusals: `unadmitted`,
`out_of_order`, `stale_generation`, `duplicate_dispatch`, `slot_pending`,
`withdrawn`. In observe mode every refusal returns `allow=True` **and**
`would_refuse=True`; a refusal that was computed but not enforced still
reaches the caller, so the census and the live answer can never disagree.

### What it refuses to confuse

- **A content id is not a playback occurrence id.** Playing the same sting
  twice is two occurrences with two positions. The gate claims the
  *earliest* admitted occurrence for an audio identity, so the first
  dispatch takes the first and the second takes the second.
- **A command acknowledgment is not sound at a speaker.** `_play_on_box`
  returning a player name is recorded as `accepted`, with
  `audible_confirmed` carried straight from `_LAST_PLAYOUT` — including
  `None` when the shared meter held another clip's key (#807).
- **Publication is not air.** `page_feed_append` succeeding is `accepted`
  with `"publication is not audible playback"` in its evidence.
- **Speech end is not cue end.** Every cue carries `speech_end_s` apart
  from `end_s`, so an inserted pause does not falsely start the next line.

### Durability

One append-only `ledger.jsonl` (flushed and `fsync`ed before the caller is
told an admission happened) plus an atomically-replaced `state.json`
snapshot. A torn final line is **dropped**, so a crash mid-admission means
the admission never happened rather than half-happened. `resume()` replays
the ledger after the snapshot, bumps the generation, and marks whatever was
in flight `uncertain`.

### The audio identity

`audio_identity()` is a full sha256 up to 8 MiB and a size + first/last
mebibyte digest above it — and **it always records which method it used**.
A hash whose method is not recorded is not evidence, and a hash that
silently changes method between two records is worse than no hash.

## The app.py integration

`patch_admission.py` (in the agent's scratchpad; give it to the caller).
It reads and writes bytes, refuses a file containing CRLF, refuses to write
unless the result compiles, keeps a timestamped backup, is idempotent, and
has a `--revert` that restores the file **byte for byte** (proven against a
real 9.7 MB copy).

```sh
python3 patch_admission.py /app/app.py --check    # dry run
python3 patch_admission.py /app/app.py            # apply
python3 patch_admission.py /app/app.py --revert   # undo
```

### Its seven anchors

Each was verified present exactly once in `app.py` at 9,714,755 bytes on
2026-09-15. If any is no longer unique the script names the edit and stops;
it never falls back to a looser match.

| # | Anchor | Placement | What goes in |
| --- | --- | --- | --- |
| 1 | `_NABU_SPEECH_ACTIVE: dict[str, Any] = {}` … `_NABU_SPEECH_EPOCH = {...}` | before | The controller bootstrap and every helper |
| 2 | `async def _nabu_played_since(t0: float) -> bool:` | before | The `_play_on_box` wrapper |
| 3 | `def page_picture_append(clip: dict[str, Any], at_ms: int = 0) -> ...` | before | The `page_feed_append` wrapper |
| 4 | `except Exception:  # noqa: BLE001` / `pass  # a download never costs the air a beat` | after | `admission_admit_round(one, rows, length, ...)` in the burst path |
| 5 | `} if _STREAM_NOW else None),` | after | `"admission": admission_state(12),` in the `/api/dj` payload |
| 6 | `"omitted_stalls": max(0, len(stalls) - 12)}` / `return out` | inside | `out["admission"]` in `script_diagnostic_context` |
| 7 | `def _view_num(view: dict[str, Any], *keys: str) -> float:` | before | `GET /api/admission` |

Anchor 1 sits deliberately **above** `_play_on_box` and **below**
`data_path`, `VOICE_MEDIA_DIR` and `MEDIA_KEY_SHAPE`: nothing below it may
start broadcast audio without asking first, and nothing above it has the
paths the resolver needs.

### How the producers were migrated

`_play_on_box` and `page_feed_append` are **rebound**, not edited. Python
resolves a global by name at call time, so all 54 direct call sites go
through the gate from the moment the module finishes importing, with no
edit at any of them.

That is what "migrate every producer and recovery route" has to mean when
the producers number thirty inside a 9.7 MB file that is on air: move the
door, not thirty thresholds. Each producer is still identified by name and
line from its own stack frame, so the observe-mode census names every one
of them without a single hand-edited call site.

The one producer given an **early submit** is the burst road: anchor 4
calls `admission_admit_round(one, rows, length)` at the first moment the
audit's precondition can be met at all — the file is finished, `rows` is
its cue sheet *after* the loudness-pass correction, and `length` is what
the mixer produced. That is also the "ready buffer ahead of the reader" for
the road that carries most of the show.

### Every producer and recovery route found

Line numbers are from `app.py` at 9,714,755 bytes, 2026-09-15. The file
moved three times during this work (9,709,745 → 9,713,346 → 9,714,755); a
second session is editing it, so re-run `--check` before applying.

| Producer (top-level def) | def @ | `_play_on_box` | `page_feed_append` | Lane / note |
| --- | --- | --- | --- | --- |
| `render_backlog_drain` | 8685 | — | 8729 | **recovery** — the render backlog |
| `_say_via_clip` | 11898 | 11910 | — | speech / reply (carries `reply=`) |
| `_box_nudge` | 21592 | 21599 | — | station |
| `speak` | 22425 | 22486 | — | speech / reply |
| `page_recovery_start` | 23887 | — | 23904 | **recovery** — preserved FIFO after a deploy |
| `pine_speak_ack` | 25575 | 25626 | 25609 | **reply — exempt** |
| `_dj_speak_floorless` | 26664 | 27162, 27201 | 26934, 27100, 27274, 27320, 27493, 27539 | speech (incl. `_speak_why`) |
| `_replay_held` | 29871 | 29905 | — | **recovery** — hold-shelf drain (`replay=True`) |
| `reel_open` | 39333 | 39369 | 39356 | speech |
| `dj_police_outside` | 57037 | 57082 | 57084 | speech |
| `dj_upstairs_page` | 57567 | 57604 | 57606 | speech |
| `dj_music_ad` | 58237 | 58315 | 58317 | advert |
| `_air_produced_ad` | 58616 | 58663 | 58654 | advert |
| `dj_sting` | 68809 | 68947 | 68927, 68961 | sfx |
| `continuity_air` | 73033 | 73156 | 73175 | **recovery** — continuity / dead-air rescue |
| `call_rerun_take` | 79062 | 79159 | 79146 | **recovery** — call rerun |
| `play_phone_ring` | 82142 | 82160 | 82153 | sfx |
| `_speak_turns_floorless` | 82730 | 84202 | 84144 | speech — **the burst road; early submit at anchor 4** |
| `pinebox_initialize` | 104783 | 104887 | — | **recovery** — box initialise |
| `response_bank_play_api` | 117059 | — | 117118 | speech |
| `_button_ack` | 117583 | 117593 | — | station |
| `_pinebox_probe` | 125241 | 125269, 125275 | — | diagnostic |
| `dj_sfx_play` | 126042 | 126060 | 126054 | sfx |
| `_broadcast_replay` | 126781 | — | 126808 | **recovery** — broadcast replay |
| `sfx_video_cue_api` | 129523 | — | 129637 | sfx |

**Not routed — a third transport.** `music_play_on_box` (def 23630) is a
separate door that hands the box a URL rather than a station-rendered clip,
and it carries no cue sheet at all. Its seven call sites are listed here
because the audit asks for the full census, and they are named in *What
remains* below:

| Producer | def @ | `music_play_on_box` |
| --- | --- | --- |
| `_radio_loop` | 25413 | 25436 |
| `play_music_request` | 25504 | 25525 |
| `_dj_loop` | 29149 | 29182, 29262, 29484 |
| `music_play_api` | 101943 | 101965, 101973 |
| `dj_output_api` | 102478 | 102722 |

30 producers, 54 call sites across the two routed transports.

### The page and the box are two routes onto one occurrence

A burst airs on the page **and** on the box; a sting is appended to the
feed and handed to the speaker. Those are two deliveries of one committed
line, and counting them twice would put a phantom position in the script
for every line the station broadcasts.

The box carrying the *same sting twice*, however, is two plays — and the
audit is explicit that those are two occurrences with two positions. The
only thing that separates the two cases is whether **this transport** has
already carried this occurrence, so the patch keeps a bounded
`{occurrence_id: {routes}}` map and asks exactly that question. A harness
test pins both halves.

## Observe → enforce

**The patch changes no behaviour when applied.** Every verdict is computed
and written down; every verdict is then allowed.

Nothing needs a restart to change mode. The controller re-reads
`<data>/broadcast_admission/mode` at most once every three seconds. Its
contents are one to three whitespace-separated words:

```
observe                    the default; nothing is ever refused
enforce                    refuse in every non-exempt lane
enforce sfx                refuse only in the sfx lane
enforce sfx,advert order   ...and refuse an out-of-order dispatch
off                        unhook the controller entirely
```

`SPARK_AGENT_ADMISSION`, `SPARK_AGENT_ADMISSION_LANES` and
`SPARK_AGENT_ADMISSION_ORDER` set the same three things at start-up; the
file wins wherever it exists and is non-empty.

### The procedure

1. **Apply and restart.** `--check`, then apply, then restart the
   container. The mode file does not exist yet, so the station comes up in
   `observe`. Confirm with `GET /api/admission`: `"mode": "observe"`.

2. **Measure for a full day, across an hour rollover.** Read the census:

   ```sh
   curl -sH "Authorization: Bearer $SPARK_AGENT_API_KEY" \
     http://10.89.1.246:8096/api/admission | jq '.counts, .stats.states'
   ```

   `counts` carries one key per refusal reason and a `would_refuse:` twin
   for each. `refusals[].detail.producer` names the producer by function
   and line. **What you are looking for:** which producers would have been
   refused, how often, and whether any of them is a road the show cannot
   do without. `would_refuse:unadmitted` counts every producer that has not
   yet been given an early submit — expect this to be most of them.

3. **Turn on the cheapest lane first.**

   ```sh
   echo 'enforce sfx' > /app/data/broadcast_admission/mode
   ```

   An sfx refusal costs a sting, not a conversation. Watch
   `counts["refusal:unadmitted"]` climb and listen. Give it an hour.

4. **Widen one lane at a time**: `enforce sfx,advert`, then
   `enforce sfx,advert,rescue`, then `enforce` for everything non-exempt.
   The `reply` lane is exempt in every mode — #647 draws that boundary and
   the pause is deliberately narrower than the FM switch.

5. **Ordering last.** `enforce sfx,advert,rescue,speech order` adds
   `out_of_order` refusal. Do this only once step 2's
   `would_refuse:out_of_order` count has been near zero for a day.

6. **Backing out is one word**: `echo observe > .../mode`, effective within
   three seconds, with no restart. `echo off` unhooks the controller
   entirely. `--revert` removes the patch byte for byte.

**Do not skip step 2.** In observe mode the controller *does* record
unadmitted dispatches as occurrences (marked `origin: observed_dispatch`)
so the Script view keeps a complete sequence — but that labelling is the
census, not a second gate. Enforcing before reading it would silence
whichever producer happens to be first.

## The Script view

`desktop/renderer/script-page.js` now reads the committed sequence from
`state.admission` on the existing `/api/dj` poll — no new request; the
audit's traffic rule stands ("38 concurrent requests were measured starving
this tablet's audio for 46 seconds").

The cue arithmetic lives in one pure module, exported as
`PineScriptPage.cues`, so the Node test holds the real code rather than a
copy of it. `activeRow()` consults it **first**; every older road — the
estimate, the feed search, the burst table, `speaking_now` — runs only
after it declines, and says so.

### What it reads, and from where

| It needs | It reads | Not |
| --- | --- | --- |
| The committed sequence | `state.admission.occurrences`, ordered by `position` | feed rows sorted by `air_at` |
| Which file is sounding | `pinePlayhead().file`, else the live `<audio>`'s `currentSrc` | the server's idea of what is playing |
| Where in it | `pinePlayhead().t`, else `currentTime` | `(Date.now() + skew)/1000 - stream_now.at` |
| Which line that is | the occurrence's own cue sheet | a window search across every row on the page |
| Which of several plays | the occurrence the controller says is in flight, else the most recently dispatched | the last row with a matching filename |

A buffered output therefore has its own playback position by construction:
the only two sources that can produce a `read` state are the bridge
playhead and a sounding `<audio>` element, both of which report *that
output's* offset. The wall clock can only ever produce `estimated`.

### The eight synchronization states

Exposed on a strip under the heading — `#spSync`, with `data-sync` and a
sentence — because the audit is explicit that hiding this would be the
wrong cure: *"Merely preventing a backward visual movement would hide an
audio fault; it would not enforce playback order."*

| State | Meaning | Trustworthy |
| --- | --- | --- |
| `read` | Read off the sound and mapped to a committed cue | **yes** |
| `read-gap` | Read, inside the file, between two committed lines — a declared pause | **yes** |
| `read-unmapped` | Read, but nothing admitted names this file | no |
| `read-outside` | Read, admitted file, offset past the end of its cue sheet | no |
| `stalled` | Read and mapped, and the playhead has not moved for 8 s | no |
| `estimated` | The station clock, not a playhead | no |
| `held` | No playback evidence at all | no |
| `paused` | The air is paused | no |

When the state is untrustworthy the view **preserves the last trustworthy
position** and says it is doing so: the strip reads `· held` with the age
in seconds, and the marked line carries a dashed outline. It is never drawn
identically to a mark the sound is standing behind.

An unpatched station (no `admission` in the payload) reports `estimated`
with *"the station is not sending an admitted cue map"* and does **not**
dash every line — a readout that says the same worried thing all day
teaches the operator to ignore it.

### One scroll controller

There were four movers of the script pane and only one declared itself.
The follow scroll stamped `selfScrollUntil`; the stick-to-end after a
repaint, the reader's-place restore and the tap-to-line jump all moved the
box silently — and each of those fires the pane's own scroll handler, which
reads "the operator scrolled by hand" and switches following **off**. The
page cancelling its own following is the precise fault #1282 was fixed for
once already.

All four now go through `moveScript(reason, apply)`, which owns the
backstop, the `scrollend` early clear and the box that actually scrolls,
records the last twelve movements with their reasons for the incident
report, and refuses to let a `follow` overrule a `restore` in the same
frame — the operator's place beats an automatic move.

### A bug the view tests found

`Number(null)` is `0` and `isFinite(0)` is `true`, so an absent playhead
arrived in the mapper as an offset of exactly zero seconds — which lands
inside the *first cue of whatever file was named* and lights its first line
with no evidence whatever behind it. A cue whose window the assembler could
not supply did the same in reverse: it became the window `0..0`, a line
that can never be reached. Fixed at the one `num()` that both go through.

### Incident references

Extended at the same boundaries, per section 5 of the recording note.

**In the view** (`sampleMotion`'s snapshot, which the caution report, the
motion ring and the window capture all carry):

- `admission` — `playback_occurrence_id`, `position`, `media`, `origin`,
  `script_revision`, `performer_session`, `assembly_id`,
  `cue_map_revision`, `take_id`, `audio_hash`, `accepted_cuts`,
  `generation`, `reader_position`, `mode`.
- `sync` — the state, its reason, when it changed, the last 60 entries of a
  bounded `{at, sync, line, occurrence, position, carried}` ring, and the
  last trustworthy position.
- `scroll` — who last moved the pane, when, and the last twelve movements
  with their reasons.

**On the server** (`script_diagnostic_context`, anchor 6): `out["admission"]`
carries `controller.references()` plus the mode, reader position, counts
and recent refusals.

A reference the server does not carry is reported **absent** — `null`, with
`available: false` and a reason — never filled in with something plausible.

### References the server does not carry yet

The other four modules landed while this was being written, so the picture
changed twice. What follows is what is true of the code as it stands.

**A conversation admitted from `conversation_assembly.py` carries almost
everything.** Its cue map supplies `assembly_id`, `script_revision`,
`cue_map_revision`, `final_audio_hash`, `sample_rate`, `frame_count`,
`seconds`, and per cue `occurrence_id`, `ordinal`, `cut_id`, `speaker`,
`text` and separate speech/cue ends. A `script_manifest.finished_conversation`
record supplies the same things under its own spellings. Both admit, and a
test pins each shape.

**A welded round admitted from the burst path carries almost none of it** —
and that is the road most of the show still takes. Named rather than
invented:

| Reference | Why it is absent on the burst road | Where it comes from |
| --- | --- | --- |
| `script_revision` | The burst has `_round_sid`, but no frozen production-script revision, and reading `_round_sid` at anchor 4 would need scope analysis I could not do safely against a live 9.7 MB file | `script_manifest.freeze` → pass to `welded_round_candidate(script_revision=)` |
| `performer_session` | No assembly record carries one: `conversation_assembly`'s `record` has `cuts[].take_id` but no session | `speaker_session.py` (its records key on `session_id`) — `Contracts.SESSION_ID` already reads it |
| `take_id` | Available per cue on a real assembly at `cue["source"]["take_id"]`, not at the top level this reads; absent entirely on a welded round | flatten it in the adapter once the assembly road is the normal one |
| `accepted_cuts` | Burst rows have no cut identity | already populated from `cue["cut_id"]` on a real assembly |
| a declared `final_audio_hash` to check against | The burst never declares one; the file is hashed at admission but nothing pins it | `conversation_assembly` declares it and `verify()` already refuses a mismatch |

Everything above is read through the adapter at the top of
`broadcast_admission.py` (`class Contracts`). When the burst road is
replaced by the assembly road, the only change needed is to stop passing
`""`.

## The adapter, checked against the landed modules

`script_manifest.py`, `manifest_store.py`, `speaker_session.py`,
`line_alignment.py` and `conversation_assembly.py` did not exist when this
module was compiled. They landed during the work, and the adapter was then
read against their actual source rather than left on the note's table.

**Four things were wrong and are fixed:**

1. `conversation_assembly` spells the cue window `start_seconds`,
   `speech_end_seconds` and `cue_end_seconds`. The adapter was reading
   `start_s` / `end_s` and would have found no usable window in a real
   assembly — it would have refused every one of them.
2. `script_manifest.cue_entry` spells the sample window
   `cue_start_sample` / `cue_end_sample`, and
   `finished_conversation` uses `final_sha256`, `final_sample_rate` and
   `final_frame_count`.
3. **`script_manifest` writes a PREFIXED digest** — `sha256:<64 hex>` —
   while `conversation_assembly` writes bare hex. Comparing the two
   literally would have refused a perfectly good assembly over a colon.
   `Contracts.bare_digest` is now the one place that difference matters.
4. A hash comparison could refuse a long conversation for being long: above
   the 8 MiB cap this module identifies a file by size plus its first and
   last mebibyte, and comparing that span digest to the assembler's full
   digest would never match. A hash that cannot be checked is now reported
   as **unchecked**, never as wrong.

**What is still assumed** (aliases kept in `Contracts`, so both the real
shapes and these survive):

1. A cue map is ordered and non-overlapping in the initial strict
   sequential mode, as the note requires: "the initial strict sequential
   mode should have a single active spoken line".
2. Occurrence ids are unique within one assembly.
3. Sample positions without a declared rate are refused rather than
   guessed at.
4. The durable store is this module's own directory. It does **not** assume
   `manifest_store.py` will own admission records; if it should,
   `AdmissionStore` is the only class to replace.

When the dust settles: delete the aliases that turned out to be wrong. Do
not scatter `.get("or_this")` through the controller.

## Test results

| Suite | Result |
| --- | --- |
| `tests/test_broadcast_admission_2026_09_15.py` | **66 / 66** |
| `tests/test_admission_transport_patch_2026_09_15.py` | **25 / 25** |
| `tests/test_script_admission_view_2026_09_15.cjs` | **28 / 28** |
| `tests/test_script_view_2026_09_11.cjs` (must still pass) | **33 / 33** |
| `tests/test_script_diagnostics_2026_09_14.cjs` | 15 / 15 |
| `tests/test_playhead_bridge_2026_09_13.cjs` | 7 / 7 |
| `tests/test_script_diagnostics.py`, `test_script_report_routes.py` | 27 / 27 |

Every Python test builds its own store under `tempfile.TemporaryDirectory`.
`LiveStoreIsolationTests` asserts the isolation rather than trusting it —
the audit found fixtures that "could append fixture rows to the live
ledger", so one test reads its own source and the module's source and fails
if either names a live runtime store.

The patch harness executes the exact source text the patch inserts, in a
namespace holding stand-ins for the dozen `app.py` globals it touches. It
found three real bugs before anything reached a file:

1. `admission_controller()` could raise out of `admission_ticket`'s
   pre-`try` call — a gate that could take the station off air.
2. A sting played twice ten milliseconds apart was collapsed into one
   occurrence, because freshness alone cannot tell a second route from a
   second play. Route identity now does.
3. Consequently, enforcement could be defeated by a recent observed
   occurrence for the same file.

## What remains

- **Nothing is applied to the live `app.py` and nothing is deployed.** The
  caller applies the patch, restarts, and runs the observe-to-enforce
  procedure above.
- **The APK is not built.** `script-page.js` and `script-page.css` were
  copied to `C:\_tools\pinebox-android\PineBoxKiosk\app\src\main\assets\pine-views\`;
  the caller ships it (`deploy.sh`, never a plain `assembleDebug`).
- **`music_play_on_box` is not routed.** Music has no cue sheet and the
  seven sites above hand the box a URL rather than a station-rendered clip.
  A `music` lane exists in the controller and is never enforced. Routing it
  means deciding what a music occurrence's cue sheet *is* — probably one
  cue for the whole track — and that is a decision, not an omission.
- **Per-sample playback occurrence in the motion ring.** The recorder in
  `script-diagnostics.js` builds each event from a fixed key set, so an
  occurrence id added to `rec.observe()` is dropped. That file belongs to
  another boundary, so the view keeps its own `sync` ring instead and the
  snapshot carries the references. Adding `playback_occurrence_id` to
  `script-diagnostics.js`'s event shape would close the audit's exact
  complaint ("Motion records moving DOM indices and shortened IDs without
  document revision or playback occurrence" — the revision is already
  there).
- **Early submit for the other 29 producers.** They are all *gated*, and
  the census names them; only the burst road *submits ahead*. Each one
  that gets an early submit moves from `would_refuse:unadmitted` to
  `admitted`, and step 2 of the procedure is what says which ones matter.
- **`advance()` has no caller in `app.py`.** The controller owns
  advancement and the transports drive it implicitly through `gate()`;
  nothing yet reads `next_occurrence()` to *decide what to play next*. That
  is the far side of this boundary — the scheduler submitting into a ready
  buffer rather than producers racing for the floor.
- **Acoustic delivery is still unproven.** Deterministic dispatch is
  enforceable; "acoustic exactly-once delivery during a disconnected or
  failed device requires telemetry that some outputs may not provide". The
  controller records `accepted` and says why, and never upgrades that to
  `delivered` on its own.

Related: [Sequential script and playout audit](../sequential-script-playout-audit-2026-09-14.md),
[Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md),
[Script incident diagnostics, version 2](script-report-diagnostics.md),
[The script is the pillar](script-is-the-pillar.md).
