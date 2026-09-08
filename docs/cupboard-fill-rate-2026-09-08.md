# Why the cupboard fills at the rate it does (2026-09-08)

The cupboard is the operator's view of prepared rounds (`cupboard_state`, the 🗄 view and the LCD's
paused page): every stored round with its lines, marked *ready*, *rapping k/N* (written, the crystal
still owed), *tinting*, or *tinted, waiting to record*. Two scans were run while the station was
paused between 09:09 and 09:36 CST: one over the station's own ledgers (the pipeline diary, the tint
counters, the recording room, System2, the review store), one over the code that bounds each stage.
Every number below is marked **[V]** (read from a ledger or the code) or **[I]** (inferred). The
snapshots and the classifier are in the session's `live-cupboard2/` folder.

## 1. The rate, measured (26.6 minutes, station paused)

| stage | count | per 10 min |
|---|---|---|
| rounds written (whole e2b answers) | 15 | 5.6 **[V]** |
| deep-model (31b) tint asks attempted | 148 | 55.6 **[V]** |
| … refused admission ("already has its admitted tint writers; this job remains owed") | 70 (47 %) | 26.3 **[V]** |
| … admitted and answered | 74 | 27.8 **[V]** |
| lines accepted by the evaluator | 181 | 81 **[V]** |
| lines refused | 25 (12.1 % of judged) | 11.2 **[V]** |
| whole rounds fully tinted | 3 | 1.3 **[V]** |
| renders (XTTS, 11.3 s each) | 79 | 29.7 **[V]** |
| rounds READY (pipeline) | 8–9 | 3.4–3.6 **[V]** |
| rounds READY as the cupboard view counts them | 1 | 0.4 **[V]** |

The view caps itself at 24 rounds and moved 11→12 "ready" while the pipeline's ready count moved
17→25: the cupboard **under-reports** by design of its cap **[V]**. A fresh round on the inline path
(the writer's own thread tints as it writes) goes write → ready in **4–6 minutes** **[V]**. A round
banked plain and left to the recovery loop waited **≥ 24 minutes untouched**: seven of the ten
"rapping 0/N" rounds were the same seven at 09:11 and at 09:35 **[V]**.

## 2. Where the time goes

**The tint admission gate (the visible jam).** Six things ask the deep lane for a tint — the
writers' inline tint, the recovery clock (every 6 s), the coordinator's re-tint (every 15 s), the two
System2 sittings, the recording room's own pre-render tint, the SFX reserve — against a cap of three
admitted asks per model (`_ollama_category_cap`, lanes + 1). The fourth caller was **refused at once**
and told to come back in six seconds; the whole-round shelf requests were refused **nine times in
ten** while single-line re-asks (51 % of admitted asks) slipped through in front of them; every
refusal re-ran the stanzas, the contracts and the regrade and asked for two whole-file saves
(`_pantry_save(True)`, `_larder_save()`) **[V]**. The lane itself ran at 1.35 of 2 slots busy: it was
never packed, it was thrashed **[V]**. The "rounds first on the lane" yield that would have let a
whole round go ahead of single lines (`_tint_turn_yields`) has no caller — it is dead code **[V]**.

**The second decode slot did not produce.** With `OLLAMA_NUM_PARALLEL=2` (set this morning under
#1080) a 31b ask took 15.6 s of working time when alone on the GPU and **32.4 s when it overlapped
another** — 2.08× slower, i.e. the two slots delivered **0.96×** the throughput of one, doubled every
ask's latency, split the prompt cache between two slots, and left the embedding model with no GPU
room (the rhyme assistant reports "waiting_for_model_room", 64 queries pending) **[V for the two
means, I for the ratio]**. The slot bought queue fairness, not output.

**A quarter of the lane is the prompt.** Working time fits 7.6 s fixed + 80 ms per output character;
mean output 276 characters per ask (about two lines) **[I from 48 pairs]**. The fixed cost — the
crystal's five 900-character passages and the rules, read for a 220-character re-ask — is ~26 % of
the deep lane; and the "whole-round first pass" was four to eight group asks, because a group held
1,800 characters of output and a turn runs 60–100 words (`CRYSTAL_GROUP_OUTPUT_CHARS`) **[V]**.

**Paid-for work thrown away.** Six strike-outs, each "refused after 1 asks" (a line that already
had two batched passes gets one per-line ask under the hold, by the #1064 design) **[V]**; a 21-line
caller went from 20 of 21 bars accepted to 1 of 21 when one bar was cut — callers may not carry a cut,
so the round went to replacement and the twenty bars with it (~10 minutes of lane) **[V]**; the
"(#1068) later pass stood down: the next 30 minutes still need schedule-critical tinted audio" fired
25 times during a pause in which nothing could air **[V]**; the caller writer's contract loop ran 8
rewrites, 5 "still thin", 2 binned; track-talk bookends failed 6 of 6 **[V]**.

**The writers.** New banter writes were near zero: `_LARDER_WRITING` is held through the inline tint
(one banter write at a time, tint included) and `prep_has_assigned_work` refuses a new write while any
desk-selected round is still unready — the #1155 pause bypass sits below that check and does not
lift it **[V]**. The keepers' "finish first" rule is doing what it says while the tint is the thing
they are waiting to finish.

**The recorder.** 56 % busy; six idle gaps over a minute totalling 688 s; one XTTS booth
(`same_engine_limit` 1, every presenter on XTTS under the cast lock, `avoid_piper` on, F5 down); the
one booth's occupant was itself "waiting for tint" at 09:11 and 09:21 **[V]**. Render time is not the
ceiling today — the tint is.

**The cupboard view cost the loop.** Each poll ran the review-store lookup for every cut line on the
event loop (`cupboard_cut_review` → `find_occurrence` / `occurrence_reference`); the state memo lasted
two seconds and the LCD polls every second while paused: 12 stalls and 92 s in ten minutes, worst
10.6 s — past the host watchdog's 8 s probe, the thing that restarts the station **[V]**.

## 3. What changed today (no operator rule touched)

| change | where | what it does |
|---|---|---|
| the tint cap is a **waiting depth**: lanes + 3 | `_ollama_category_cap` | the fourth, fifth and sixth callers queue in the lane's FIFO instead of being refused and retried; the runner stays packed; whole-round requests are no longer bounced nine times in ten |
| a refused round **rests 30 s**, not 6 | `TINT_DEFERRED_REST` | the refusal loop and its re-runs stop |
| a deferral **does not force a save** | `ensure_entry_tinted`, `ensure_shelf_row_tinted` | the throttled flusher writes; no two whole-file writes per bounce |
| **one decode slot** on the host again | `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_LANES=1` | per-ask latency halves, one prompt cache, GPU room for the embedder; throughput unchanged by measurement |
| group output **1800 → 3000** characters | `CRYSTAL_GROUP_OUTPUT_CHARS` | an eight-turn first pass is two to four asks, not four to eight; fewer 7.6 s prompt costs |
| the later pass **runs while paused** | `retint_one` | the "cupboard polish waits" stand-down is pause-honest (#1150): nothing is due while the clock is stopped |
| the cupboard view **remembers** a cut's review for five minutes and its state for five seconds | `cupboard_cut_review`, `CUPBOARD_MEMO_SECONDS` | no review-store scans on the loop per poll; the 8–10 s stalls go |

## 4. What would raise the rate further, and what it touches

1. **Keep a caller's accepted bars when one bar is cut** — re-ask the cut line later (the strike cap
   retires it at twelve answers) instead of sending the whole call to replacement. Touches the
   #1146 phone rule that a call carries no cuts; the twenty accepted bars are the argument. **[I]**
2. **Let a new round be written while a selected one is stuck**, when paused and the unaired count
   is below the want (`prep_has_assigned_work` at the larder and shelf keepers). Touches #1155's
   "finish first". **[I]**
3. **Single-line roads on the fast model's lane** (ads, memos, IDs, gallery reads): the fast model
   overlaps the deep runner for free and its bars pass less often but five times faster. Touches
   #1064's "deep model on every road". **[I]**
4. **A second recording engine for non-presenter seats** (kokoro/piper for callers and memos while
   paused) so the booth policy's "parallel independent engines" has a second engine. Touches
   `avoid_piper`. **[I]**
5. Wire in or delete `_tint_turn_yields` and `TINT_TURNS_MOST` (dead); raise the cupboard view's cap
   or show the pipeline's stage counts beside it. **[V]**

## 5. The first reading after the change (10:49–10:58, station still paused)

| measure | before (09:09–09:36, per 10 min) | after (9 min) |
|---|---|---|
| lane occupancy | 1.35 of 2 slots, thrashed | 1 active + 3 waiting, packed **[V]** |
| tint admissions refused | 26.3 | 20 in 9 min — the fifth and sixth drivers still bounce, now resting 30 s **[V]** |
| lines accepted / refused | 81 / 11 | 46 / 7 (13 %) **[V]** |
| whole rounds fully tinted | 1.3 | 2 in 9 min **[V]** |
| pipeline ready | +8 in 22 min | +1 in 9 min **[V]** |
| cupboard stalls on the loop | 12 in 10 min, worst 10.6 s | none; worst stall 1.8 s **[V]** |

The gate no longer thrashes and the loop no longer stalls, but the visible fill did not jump: with one
slot the deep lane answers about one ask every 25–30 s, an eight-turn round costs five to eight of
them, and every round still goes through it. That is the physical ceiling of "the deep model on every
line" — roughly a dozen rounds an hour for the whole station — and the seven rounds that sat at
"rapping 0/N" are now moving through the recovery loop one at a time, several minutes each. Raising
the rate further is one of the rule-touching levers in §4, not another gate.

## 6. How to see whether it worked

`/api/orchestrator/logic` → `pipeline.writers.deferred_by_category` (the refusal count; it was 94 in
30 minutes and 70 in 26), `pipeline.stages` (awaiting_tint vs ready), `/api/tint` →
`coverage.rounds` per 10 minutes, `/api/pulse` (cupboard stalls should be gone), and the cupboard
itself: the seven "rapping 0/N" rounds should turn into bars within the hour instead of sitting.
