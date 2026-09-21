# The measured cue map reaches the air, and the gate can be enforced

Date: 2026-09-21. Status: built, tested, deployed. The production switch is
`on`; the admission gate is still `observe` and the last step is named at
the bottom.

This finishes [Recording speakers and assembling
conversations](speaker-recording-and-script-assembly.md). The five
boundaries were built on 2026-09-15 and have been running since; three gaps
were left between what was built and what the station actually does, and
this is those three closed.

## What was already true on the morning of the 21st

| Boundary | State |
| --- | --- |
| 1 manifests + durable recovery | live, writing `data/manifests/rev-*` |
| 2 sessions + alignment | live; the continuous take benched and rejected |
| 3 assembly + cue map | producing in **shadow** — 969 rounds, 917 complete |
| 4 admission gate | **observe** — 14,394 dispatches would have been refused |
| 5 the Script view | wired to `state.admission`, in the desk and the APK |

Shadow mode had been measuring for six days and nobody had read it. What it
said is the reason everything below is shaped the way it is.

## 1. The rescale could not be right, and the ledger proved it

Section 4 of the note asks for one thing:

> The current stream path rescales estimated cue windows to fit the finished
> duration. Replace that approximation with cue positions derived from actual
> edited sample counts.

The approximation is `scale = _made / _ours` in `_speak_turns_floorless`: the
sum of the estimated per-turn spans is stretched to fit the duration the
mixer actually produced. Over 915 comparable shadow rounds:

| | |
| --- | --- |
| `mix_latency_frames` | **120 in every single round**, `latency_measured: true` |
| `mix_residual_frames` | 0 in 343 of them; within ±3 in 887 of 915 |
| measured vs estimated | 16 ms in the median round, 41 ms at p95, **1.20 s** worst |

120 frames at 24 kHz is 5 ms: the limiter's lookahead, a **constant** delay.
A constant multiplied by a scale factor is wrong at the head and wrong at the
tail, and no tuning of the factor fixes it. The 3-frame residual is the
loudness pass, and it is not a scale either.

`tools/_cue_map_windows_patch.py` (#1337) replaces it — and it is a rewrite
of the version written on 2026-09-15 and never applied, which could not have
worked: it joined cues to rows by `row["id"]`, the script ledger's
per-airing line id, and the frozen occurrence ids in a cue map are not those.
Rows carry the frozen identity at `row["production"]["occurrence_id"]`, and
that is the join. It also compared the map's whole-file duration against the
finished burst; a call opens with a ring and closes with a hang-up that are
in the file and not in the map, so the comparison is against `body_frames`.

Three helpers, and the guards are the whole of it:

- `production_cue_map` — a map only if it says `derivation: measured`.
- `production_cue_beats` — the assembler's own seam beats, laid onto `seg`
  **by `seg_ix`**, so a ring, a hang-up or a sting keeps the beat it was
  drawn. #778's rule one step earlier: the mixer and the timeline must be
  built out of the same numbers, or the file that airs is not the file that
  was measured.
- `production_cue_windows` — the windows, or `(None, why)`. Every guard has
  to hold: every turn carries a frozen occurrence id; **the burst's
  occurrence ids ARE the map's `sequence`, in order** (the note's own
  acceptance line, and #1330's lesson that two lists of the same shape
  wrongly paired is a silent fault); and the body the map describes is the
  body the mixer just produced, inside the loudness pass's own residual.

A map that does not prove out is not half-used. The round falls back whole
to today's rescale and the log says which guard refused it.

## 2. The gate could not name most of the audio it was gating

147 hours of observe mode, `data/broadcast_admission/ledger.jsonl`, 58,676
rows. 4,991 admissions were refused with "the final audio is not available",
and they sort into three kinds:

| | | |
| --- | --- | --- |
| 4,512 | a 16-hex sfx key | `/sfx/{key}` names a **sample by its id** |
| 398 | an mp3 | `/ads-audio/` — a produced spot |
| 82 | `test.wav` | a recovery fixture that genuinely does not exist |

The resolver only knew how to turn a path into a file. So the entire SFX
lane — every sting the station played — was unnameable, and `enforce sfx`
would have silenced all of it while reporting that the audio did not exist.

`tools/_admission_reach_patch.py` (#1338) teaches it `/sfx/`, `/ads-audio/`
and `/upstairs-audio/`. Two things about the SFX road matter:

- **Only the free way back.** `sfx_by_id`'s other roads end in a walk of the
  CIFS share, and the resolver runs on the event loop. #1307 already keeps
  id → path as a dict written at the moment an id is minted, and an id
  cannot be asked for before something has hashed its path.
- **What the box is actually handed.** `/sfx/{key}` serves the *levelled*
  copy when there is one, so that is the file whose bytes are named.
  Cache-only — making one here would put a wave decode on the event loop for
  every sting. `sfx_levelled_name` is split out of `sfx_levelled` for this,
  because #1420's lesson is that the levels must not live in two places.

The 82 stay refused. An occurrence that cannot name its audio is not an
occurrence.

## 3. Seven producers dispatched audio nobody had committed

The census named them exactly:

| lane | producer | unadmitted dispatches |
| --- | --- | --- |
| speech | `_dj_speak_floorless` | 9,192 (+209 on the station lane) |
| sfx | `dj_sting` | 4,505 |
| speech | `_air_produced_ad` | 353 |
| speech | `page_recovery_start` | 79 |
| speech | `dj_upstairs_page` | 45 |
| sfx | `sfx_video_cue_api` | 11 |
| sfx | `dj_sfx_play` | 1 |

Only the burst road submitted ahead. Everything else reached the gate as a
dispatch of audio the controller had never been told about, was admitted by
the census after the fact, and would have been **refused** the moment any
lane was enforced. A census of what happened is not a committed sequence,
and that difference is the whole reason the gate could not be turned on.

`admission_admit_line` (#1338) and `tools/_admission_early_submit_patch.py`
(#1339) give each of them a commitment immediately before its first
transport call, once every veto above it has passed. A line with a sting
welded into it already **has** a cue sheet — the stream's own rows, the
numbers the booth marker is driven off — and it is used as it stands; a
plain line is one cue covering the whole file, which is the honest shape.

Writing the test first found a dispatch the reading had missed:
`_dj_speak_floorless` has **two** doors out, and the second one — the box was
busy, the clip goes to the hold shelf, and in `both` mode the page carries it
live anyway — is a broadcast like any other. `tests/test_early_submit_2026_09_21.py`
asks of each producer, as text, whether the commitment comes before the
transport, so an ordering quietly reversed by a later edit fails there
rather than on air.

## 4. 674 commitments were standing in front of everything

With the producers committing, one number was left: 2,584 `out_of_order`
refusals. Their cause was a single shape.

**674 occurrences stood `admitted` and never dispatched.** Every one of them
from `_speak_turns_floorless`. The oldest at position 16, four days old.

`_burst_withdraw` exists because of exactly this failure one layer up — its
own docstring is "A ROUND THE STATION REFUSED IS NOT ON THE AIR" — and it
withdraws the round's rows from the **feed**. The admission gate, which had
been told about the round a few lines earlier, was never told it had been
refused. Five separate refusal paths, and none of them said so.

Two fixes, because there are two ways to strand a commitment:

- `tools/_burst_withdraw_admission_patch.py` (#1340) — the admit call site
  keeps what it committed and stamps it on every row of the round, and
  `_burst_withdraw` takes it back. (That id on the feed row is also the
  reference the script report was missing: the audit's complaint that
  "Motion records moving DOM indices and shortened IDs without document
  revision or playback occurrence".)
- `broadcast_admission.resume` — an occurrence still `admitted` when the
  process died was never dispatched and never will be. It is withdrawn with
  `STRANDED_WHY`, exactly as an in-flight one is finished as `uncertain`.
  The **position stands**; the script keeps the hole, marked.

**This reversed a contract**, and the reversal is deliberate.
`test_a_crash_between_admission_and_handoff_replays_the_admission` asserted
that a commitment survives a restart and is claimed by the dispatch that
follows it. On this station that never happened once — a burst's mix is
content-addressed and the re-mix after a restart is drawn with fresh seam
beats, so the claim had nothing to match. Nothing is lost by taking the
stranded one back now that every producer brings its own commitment. The
test now asserts the new contract and carries the measurement as its reason.

On the restart that deployed this, all 674 were withdrawn at once:
`{"withdrawn": 674, "finished": 11982}`, `withdrawn:stranded: 674`, and not
one occurrence left standing.

## What it looks like now

A sting, through the live gate, before and after:

```text
before   refusal unadmitted → admission_refused
                             "the final audio is not available at 65d26c4e1827c8d7"
after    admitted pos 37941 sfx origin=producer producer=dj_sfx_play
         dispatched → delivery accepted
```

and the audio it names is exact: `sha256-full`, 233,774 bytes, 5.3 s — the
levelled copy, which is the file the box is handed.

The first round produced with the switch at `on`:

```text
conversation   round-7a3a399d8b62fb73f35b
revision       rev-057d290cef58776413b2
assembly       asm-8f273fcb81cbac327751
playback       play-57f2db644326454e
12 lines, 64.118s, sessions [cohost, dj], 59.5s to produce
latency 120 frames, residual 2 frames
the estimate would have been 12.5ms out on average, 31ms at worst
```

Frozen script → performer sessions → masters and verified cuts → assembly in
script order → finished audio and an exact cue sheet → an admission record.
The whole flow of the note, on a live station.

## Tests

| suite | |
| --- | --- |
| `tests/test_cue_map_windows_2026_09_21.py` | 19 — the three helpers executed, every guard |
| `tests/test_admission_reach_2026_09_21.py` | 28 — the resolver and `admission_admit_line` against a real controller |
| `tests/test_early_submit_2026_09_21.py` | 10 — commitment before transport, as an invariant over `app.py` |
| the five boundary suites | 362, unchanged and green |

Every app.py change is an idempotent, anchored, revertible patch under
`tools/`, compiled before it is written. The station was paused for the
whole deployment, which is why four restarts cost no air.

## 5. Two more, which only enforcing found

The station was taken off pause and the SFX lane enforced with somebody
watching. Two commitments that nothing could ever consume showed up within
minutes of each other, and both were mine.

**A reply is not broadcast, so it must not be committed.** #647 draws that
boundary and `gate` keeps it there: the reply lane returns `exempt` without
ever beginning or finishing the occurrence. `admission_admit_line` was
committing every line `_dj_speak_floorless` produced, replies included — so
a reply stood `admitted` for ever. Three minutes after the first deploy:
one reply at position 37949, and every single dispatch after it refused as
`out_of_order`. The helper now refuses any lane the controller exempts, and
the census and the gate agree again, which is the whole point of a census.

**A LIVE burst that neither road carried gave nothing back.** The end of
each burst reads:

```python
if ready_takes is not None and not (page_delivery or (to_box and played_ok)):
    _burst_withdraw(_entries, "neither the page nor the box took the clip")
```

The `ready_takes is not None` is deliberate and it is a rule about the
FEED — a live round's rows are handled elsewhere. The gate does not care
which kind of round it was. Measured ten minutes into enforcement: one live
burst, 20 lines, 137 s of audio, all twenty of its feed rows still reading
`prepared`, standing `admitted` for thirteen minutes — and all 24
out-of-order refusals in that window named it. #1341 takes the commitment
back regardless of the kind, and changes nothing about the feed.

Both are the same shape as #1340 and both were invisible in observe mode,
because in observe mode a commitment nothing consumes costs nothing. That
is the argument for enforcing a lane rather than reading the census: the
census counts refusals, and only enforcement makes a stuck commitment
expensive enough to find.

## Where it stands

```text
mode: enforce   lanes: ['sfx']   order: False
```

The SFX lane has been enforced on a live, on-air station since this was
written. A sting through it, end to end, with nothing between the operator's
thumb and the picture:

```text
admitted pos 38031 sfx origin=producer dj_sfx_play
dispatched
delivery accepted
```

and the audio it names is exact — `sha256-full`, 233,774 bytes, 5.3 s: the
levelled copy, which is the file the box is handed.

Across the watched windows — 25 minutes of live air — 59 admissions, every
one `origin: producer`, across the speech, sfx, advert and station lanes;
54 deliveries, all `accepted`; five withdrawals, each with its reason named
(two stranded by a restart, two rounds that would not fit their entry, one
hand-off the caller's own check refused); and **no enforced refusal of any
kind**. In the two minutes after the last deploy: 19 admissions, 18
deliveries, and not one refusal of any sort.

### What is NOT ready, and why

**`order`.** Do not add it yet. The burst road commits a whole round and
then the paced page road (#1146) waits for the air it has already sold to
play out before it appends, so a committed round can legitimately sit
unaired for as long as the feed is sold ahead — and with ordering enforced,
every line that airs during that wait is refused. That is a design
decision, not an omission: either the commitment moves below the pacing
wait, or the reader learns that a round waiting on its own slot is not a
blocker. Neither is a one-word change, and the evidence for choosing
between them is not in yet.

**The speech lane** is the next word, and it is ready. Everything that
produces speech commits first, the watched windows are clean, and the last
thing that would have been refused on it is gone: `page_recovery_start`
restores the page's FIFO after a deploy and never asked whether the audio
was still there. `/media` is pruned, so it often is not — and this
station's FIFO held exactly one row, `/media/test.wav`, "The host's full
opening.", a fixture whose file has never existed, replayed on every
restart for as long as the ledger goes back. 82 of the gate's 4,991
historical "the final audio is not available" refusals are that one row.
`page_recovery_read` now uses the gate's own resolver (#1342), so what can
be replayed and what the gate can name cannot disagree, and a dead row is
dropped quietly at startup instead of becoming a refused dispatch and a
404 in somebody's browser.

Even so: `enforce sfx,speech` is the whole of the show's audio, and the two
faults above say this class of bug only shows itself under enforcement. Add
it while somebody is watching, and read the census afterwards.

**An exception between the admit and the transports** still leaves an
occurrence standing until the next restart, where
`broadcast_admission.resume` withdraws it with `STRANDED_WHY`. Wrapping the
whole delivery of the busiest function in the file in a try/finally is a
bigger change than the evidence justifies today.

## Turning it up, or off

The mode file is re-read within three seconds; no restart, ever. It lives
inside the container and is owned by root, so it is written through it:

```sh
docker exec spark-agent sh -c "echo enforce sfx > /app/data/broadcast_admission/mode"
docker exec spark-agent sh -c "echo enforce sfx,speech > /app/data/broadcast_admission/mode"
docker exec spark-agent sh -c "echo observe > /app/data/broadcast_admission/mode"   # back out
```

Read `/api/admission` after each word. What "good" looks like: every
`admitted` row carrying `origin: producer`, `counts` showing
`refusal:unadmitted` and `admission_refused` flat, no enforced refusal, and
nothing in `states` standing `admitted` for longer than a round takes to
air. A single stuck `admitted` row is the tell for every fault in this
note, and `/api/admission` prints its producer.

Related: [Recording speakers and assembling
conversations](speaker-recording-and-script-assembly.md), [The admission
gate, the one playout controller, and the Script
view](admission-and-playout-2026-09-15.md), [Assembly and the cue
map](assembly-and-cue-map-2026-09-15.md), [The continuous take,
measured](continuous-take-bench-2026-09-15.md).
