# The continuous take, measured

Date: 2026-09-15. Status: measured on the live station's own material and its
own engines. No live rendering, playback or store behaviour was changed.

[Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md)
ordered this and forbade the shortcut:

> Measure both approaches before claiming that larger requests are faster.
> Record production time, accepted audio duration, retries, missing/repeated
> speech, cut accuracy and listening quality using the same scripts and cast.

So this is numbers, not an argument. Everything below was produced by
`tools/take_bench.py` against XTTS on `127.0.0.1:8770` and the voice lab's new
`/align` endpoint on `:8771`, using six complete conversations read out of
`data/larder.json` — real prepared rounds, with their frozen per-chunk text,
their assigned voices and their reading order. Not one line here was written
for the benchmark.

Reproduce:

```sh
docker exec -d spark-agent sh -c "python -u /app/tools/take_bench.py \
    --round-ids 7,29,4,8,3,22 --keep-audio \
    --out /app/data/bench/take_bench_2026_09_15 > /app/data/bench/bench.log 2>&1"

# and, to re-score a matcher change over the SAME audio rather than paying
# the engine again:
docker exec -d spark-agent sh -c "python -u /app/tools/take_bench.py \
    --realign /app/data/bench/take_bench_2026_09_15 \
    --out /app/data/bench/take_realign_2026_09_15"
```

## The headline

**A true single continuous take is not reachable through the current adapters
above 1,000 characters, and below that ceiling it is neither faster nor
reliably cuttable yet.** Five of eleven performer parts produced accepted
cuts. The other six were refused, and half of those refusals are the engine's
own faults, caught — which is the aligner doing its job, not failing at it.

## 1. The ceiling is real, and it is silent

`reachy-gateway/voice_clone_server.py:371` is `wav = _synthesize(text[:1000],
...)`. A request longer than that is truncated *in the server*, returns HTTP
200 and returns clean audio. Nothing upstream can see it.

Measured with `--probe-only`: render one performer's whole part in a single
request, transcribe what comes back, and align the words against the whole
text and against its first 1,000 characters.

| Round | Asked | Returned audio | Coverage of the WHOLE text | Coverage of the first 1,000 chars |
| --- | --- | --- | --- | --- |
| 2 | 1,531 chars | 86.0 s | **62.6 %** | 95.5 % |
| 0 | 1,663 chars | 75.6 s | **59.7 %** | 98.9 % |
| 42 | 1,602 chars | 87.4 s | **66.1 %** | 96.5 % |

A third to two fifths of every one of those performances was never spoken and
nothing reported an error. That is the whole argument against removing the
station's own `VOICE_MAX_CHARS` cap without touching the host service:
`app.py`'s 800-character cap is currently the only thing standing between the
station and this.

The other two ceilings named in the design note are unchanged and still
apply: `voice_render_any` splits above `VOICE_MAX_CHARS` and rejoins
(`app.py:8373`), and the F5 path splits again near 280 characters
(`app.py:12454`) because past roughly 300 its alignment slides and the tail
garbles.

**So: "one continuous take per performer" is available for a part of up to
1,000 characters, through XTTS only, and only by calling the clone server
directly.** Above that it is segmented synthesis and must be called that.

## 2. Production time — larger requests were NOT faster

Every part was rendered twice with the same voice, the same reference and the
same text: once as one engine request per frozen line (SEGMENTED, the
station's road today) and once as a single request for the whole part
(CONTINUOUS).

`x RT` is wall-clock over produced audio seconds; lower is faster.

| Round | Voice | Lines | Chars | Seg wall | Seg audio | Seg x RT | Con wall | Con audio | Con x RT |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | Caine | 4 | 390 | 36.9 s | 26.4 s | 1.40 | 29.2 s | 32.1 s | 0.91 |
| 29 | Caine | 3 | 230 | 51.8 s | 20.7 s | 2.50 | 18.6 s | 16.5 s | 1.13 |
| 29 | Avasarala | 3 | 284 | 35.4 s | 21.3 s | 1.66 | 43.0 s | 19.4 s | 2.22 |
| 4 | Caine | 3 | 298 | 29.2 s | 20.2 s | 1.45 | 31.6 s | 23.8 s | 1.33 |
| 4 | Avasarala | 3 | 286 | 24.9 s | 19.7 s | 1.27 | 9.1 s | 22.1 s | 0.41 |
| 8 | Caine | 3 | 293 | 10.4 s | 23.4 s | 0.45 | 8.0 s | 18.3 s | 0.44 |
| 8 | Avasarala | 3 | 354 | 11.0 s | 25.1 s | 0.44 | 27.0 s | 26.4 s | 1.02 |
| 3 | Caine | 6 | 655 | 20.3 s | 45.3 s | 0.45 | 37.4 s | 45.7 s | 0.82 |
| 3 | Avasarala | 3 | 326 | 10.2 s | 22.2 s | 0.46 | 11.3 s | 25.9 s | 0.44 |
| 22 | Caine | 7 | 876 | 26.8 s | 61.7 s | 0.43 | 25.4 s | 64.0 s | 0.40 |
| 22 | Avasarala | 6 | 641 | 28.0 s | 36.0 s | 0.78 | 19.5 s | 40.7 s | 0.48 |

Totals, and the reason there are two of them:

| Set | Seg wall | Seg audio | Seg x RT | Con wall | Con audio | Con x RT | Continuous / segmented wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All 11 parts | 284.9 s | 322.0 s | 0.885 | 260.1 s | 334.8 s | 0.777 | **0.91** |
| Rounds 8, 3, 22 only | 106.7 s | 213.7 s | 0.499 | 128.6 s | 220.9 s | 0.582 | **1.21** |

Rounds 7, 29 and 4 were rendered while the GB10 was at 94 % utilisation for
somebody else — the same segmented request shape costs 2.50 x RT there and
0.44 x RT twenty minutes later. **The second row is the one to quote**: on an
uncontended box the continuous take was 21 % SLOWER in wall clock than the
same words rendered line by line. Neither row supports "larger requests are
faster". The claim the note told us not to make would have been false.

Retries: **zero**, on both roads, across 44 segmented requests and 11
continuous ones. Neither road is flaky; they are just not different in the
direction that was assumed.

## 3. Cut accuracy, and what the aligner refused

`line_alignment.py` matched the recognised word sequence against the frozen
script for each continuous master. Five of eleven parts produced cuts.

| Round | Voice | Lines | Cuts | Coverage | Per-cut CER (mean / worst) | Cuts over 0.15 CER | Boundary methods used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 29 | Avasarala | 3 | 3 | 1.000 | 0.020 / 0.051 | 0 | word_span, +gap_split, +edge_pad |
| 8 | Caine | 3 | 3 | 1.000 | 0.060 / 0.129 | 0 | word_span, +gap_split, +edge_pad |
| 8 | Avasarala | 3 | 3 | 1.000 | 0.007 / 0.013 | 0 | word_span, +gap_split, +edge_pad |
| 3 | Caine | 6 | 6 | 1.000 | 0.019 / 0.050 | 0 | word_span, +gap_split, +edge_pad |
| 22 | Avasarala | 6 | 6 | 0.982 | 0.031 / 0.086 | 0 | word_span, +gap_split, +edge_pad |

21 cuts, 148.1 s of accepted audio. Cut accuracy was measured by cutting each
strip at its integer sample positions and sending it back through voice-lab
`/verify` against that line's exact text: **mean character error rate 0.027,
worst single cut 0.129, and not one cut over the 0.15 threshold the lab
already uses to say "it said something else".** Where the aligner accepts, the
strip contains the line.

Boundary error against the segmented render of the same line averaged 1.01 s
(worst 2.94 s). That number is **not** an error: the two roads are different
performances and the continuous one paces differently, so it measures
prosody difference, not mis-cutting. The CER above is the cut-accuracy figure;
this one is only here because the note asked for it.

### The six refusals, each traced to its cause

| Occurrence | Refusal | What is actually in the audio |
| --- | --- | --- |
| r7-001 | `extra_speech` — 6 unscripted words in a row | **Engine fault.** XTTS re-read a clause: "till i put on the mask **if i put on the mask** if i pulled that off". |
| r3-006 | `extra_speech` — "thorn soar in mow the" | **Engine fault.** Garble inserted between "right now" and "the whole situation". |
| r22-001 | `missing_speech` + `repeated_speech` | **Engine fault, both ways at once.** The script says "is this your king is this your king" — the engine said it **once**. Then it read "the whole structure must fit somehow when reality starts to ring" **twice**. The duplicate-occurrence case and the repeat case in one take. |
| r4-001 | `mismatched_speech` — 3 of 20 words | **Recogniser.** "a heavy way to view the scene" heard as "a heavy weight of you the scene"; "flux krea" heard as "flux create a". |
| r29-000 | `coverage_low` + `mismatched_speech` | **Recogniser.** "line seven five six three eight" read back as "line seventy five thousand six hundred thirty eight"; "pretense" as "pretends". |
| r4-000 | `coverage_low` + `mismatched_speech` — 15 of 19 | **Recogniser**, same shape. |

Three genuine engine faults caught; three false refusals from the
recogniser. Both halves matter:

* The three real ones are exactly what the design note demanded be rejected,
  and two of them would be invisible to any silence-based splitter. r22-001
  in particular is the case the whole occurrence-ID scheme exists for: a line
  that appears twice in the script and once in the audio.
* The three false ones are **not** matcher strictness. They are
  `WHISPER_MODEL=base`, which is the voice lab's own documented floor, chosen
  for CPU cost rather than accuracy. Proper nouns ("krea"), digit strings
  read as numbers, and near-homophones are where it loses. Raising the lab to
  `small` is the single named lever on the acceptance rate, and it is a
  compose env change plus a container recreate — not done here, because this
  investigation was not allowed to change how the station runs.

## 4. Listening quality

Both roads' full masters through voice-lab `/verify` against their own text:

| | Segmented | Continuous |
| --- | --- | --- |
| Read-back CER, median over 11 parts | 0.034 | 0.034 |
| Speaker identity (wespeaker cosine), range | 0.655 – 0.790 | 0.652 – 0.799 |
| `overrun` (audio per character vs baseline), range | 0.92 – 1.48 | 1.03 – 1.35 |
| `/verify` verdict `pass` | 3 of 11 | 1 of 11 |

The `/verify` failures are almost all the same fault on both roads —
`looping (compression 1.51–1.96)` — and it fires on the *segmented* renders
too, so it is a property of this material (dense internal rhyme, repeated
phrases) tripping the compression-ratio heuristic, not a difference between
the two approaches. On the numbers that do separate them, they are level:
identical median CER, overlapping identity, and the continuous road slightly
*tighter* on overrun.

**There is no measured prosody or speed benefit to the continuous take here.**
The design note anticipated that the segmented alternative "does not establish
the prosody or speed benefits of a single continuous performance"; measured,
neither does the continuous one, at the lengths the adapters allow.

## 5. Verdict

1. **A continuous take is achievable only up to 1,000 characters**, via XTTS,
   by calling the clone server directly. Past that the server truncates in
   silence and the result must never be described as a continuous
   performance. `tools/take_bench.py --probe-only` is the standing check.
2. **It is not faster.** 1.21x slower than per-line rendering on an
   uncontended box; the apparent 0.91x over the full set is GPU contention,
   not the method.
3. **The alignment path works and refuses correctly.** 21 of 21 accepted cuts
   land under the lab's own accuracy threshold, and every refusal names its
   occurrence and its fault. Where the audio was wrong, it was caught; where
   the recogniser was wrong, the refusal was conservative rather than a bad
   cut on air — which is the correct direction to be wrong in.
4. **Acceptance is recogniser-bound, not matcher-bound.** Half the refusals
   trace to `WHISPER_MODEL=base`. That is the next lever, and it is cheap.
5. Until then, the honest production configuration is
   **`segmented_synthesis` with retained boundaries**: render per line, keep
   each request's boundary as the cut (no guessing, no alignment), and save
   the speaker master plus its cut map. `speaker_session.RendererConfig`
   carries `mode` for exactly this reason, and every take and cut records
   which mode made it. It is segmented synthesis. It is not to be called a
   continuous performance in a manifest, in a log line, or in a comment.

Related: [Recording speakers and assembling conversations](speaker-recording-and-script-assembly.md).
