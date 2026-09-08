# RapAssembly — how a thought becomes a rhymed line on the air

Pine Box FM, read from the code on 2026-09-08. One document for the whole assembly line: where a
round's subject comes from, who writes it, what the crystal is and how its material is pulled out of
it, how the tint turns prose into bars, how the grader decides, where the operator's hand enters, how
a round is recorded, stored, scheduled and played, what keeps the air from going silent, and what the
station learns from its own work. Each section names the functions, the stores on disk, the dials
and their defaults, and where to read the live state — enough to make an executive decision about
any stage without opening `app.py` (8.1 MB, one file; the modules beside it are named where they own
a stage).

Every number below is read from the code or a ledger; anything inferred says so.

---

## 1. The line in one picture

```
 IDEATION                WRITING ROOM              THE CRYSTAL                THE TINT
 speakbox docs/minds ─┐  System2 planner ─┐        documents ("minds")        crystal_tint(round)
 wire (news) ────────┼─▶ dj_banter(angle, ├──▶ prose round ──▶ stanzas + vocabulary + world ──▶ whole-round ask
 gallery / memo /    │   seed, material)  │   (script_plain)   (crystal_stanzas,             batched repass
 callers / plot /    │  legacy keepers ───┘                     _crystal_vocab,               per-line asks
 recap / ads / IDs ──┘                                          crystal_world_prompt)          (≤3 under the hold)
                                                                                                    │
                                                              THE GRADER ◀──────────────────────────┘
                                                              tint_evaluate: meaning · rhyme · transformed · copying
                                                                │ pass                     │ refuse
                                                                ▼                          ▼
                                                    script_tinted (the bars)      re-ask with REPAIR EVIDENCE
                                                                │                 ──▶ cut before the studio (a "cut line")
                                                                ▼                        │ operator: allow / keep /
                                                        RECORDING ROOM                   │ Approve as written
                                                        booths → engines (XTTS/F5/piper) │
                                                        takes → PANTRY (clips) ──────────┘ recovery re-records the line
                                                                │
                                                                ▼
                                          STORES: larder (banter) · shelf (kinds) · gold bars · continuity · hold · reel
                                                                │
                                                                ▼
                                        SCHEDULE: hour contract → slot kinds → shelf_take / alt_larder_index
                                                                │
                                                                ▼
                                          THE AIR: the floor → paced turns → box + page → print ledger
                                                                │ silence?
                                                                ▼
                                          COVERS: continuity pair · gold bar · liner · sample · live cover
                                                                │
                                                                ▼
                                          LEARNING: outcomes · fault memo · repair hint · preferences · REFLECTION
```

The whole line is one Python process (`spark-agent`, FastAPI, asyncio) on the host `lilspark`
(10.89.1.246), talking to one Ollama server (the writer and the crystal models), the voice engines,
the Pine Box (the speaker), and the pages. Everything that must survive a restart is a JSON file or a
SQLite store under `data/`.

---

## 2. Ideation — where a round's subject and material come from

A round has an **angle** (what it is about) and a **seed** (what it is built out of); the two are
not alternatives (#1078). Where each comes from:

| road | the angle | the material |
|---|---|---|
| **booth banter** (the larder) | the angle stock and the approach wheel (`DIALOGUE_APPROACHES`, 16 treatments — interrogate it, refuse the premise… — drawn by weight with cooldowns, never the same twice running), or a bombshell (`drop_bombshell`, the least-aired line of the operator's bank) or a surplus topic when the reserve is deep | the **speakbox**: `speakbox_quote()` reads the document folders every call (`data/speakbox`, `data/minds/<id>/docs`), unused lines first, one random swath of one random document; who steals the draw, in order — the operator's theme (strength as probability), the storyline (45%), the crystals that supply words (strength as probability). Best of two 700-character swaths at `speakbox_rate` (0.82); a semantic comeback from another document via the vector index (`speakbox_search`, `nomic-embed-text`, up to 40,000 vectors, one chunk per document); a verbatim swath prepended (0.6) or appended (0.85) or a full 2,600-character reading (0.35) placed after the model has written |
| **news** | the wire: `drudge_headlines` (24, cached 600 s), `news_draw` under three gates (this segment's list, the desk's 3-hour topic ledger, the repeat check); the hourly bulletin takes the whole front page, a break takes three with two full stories dug out (`_news_once`) | `own_material` — the wire is the material; no seed, no aside, no swath (since 14:33 today) |
| **gallery** | the paintings on the wall (`gallery_pending_set`), described and sold | own material |
| **manager** | a memo from upstairs (`UPSTAIRS_GRIPES` and a semantic seed) | own material |
| **callers** | a request, a story call, a scheduled theme; the **call contract** (a ringing line answered, a brief self-introduction, the greeting by name, two natural questions answered, speakbox words in both mouths, novelty against the call log, balance, sign-off, resolution) | the caller's own speakbox seed |
| **recap / ads / station IDs** | the hour's log / the ad book / the drop voice's liners | own material |
| **the plot** | `plot_owns_air()` — the plotline colouring this half hour, its act; part of the writing contract | — |

Every line of every round also gets the speakbox's **flavour** (`speakbox_flavor`: a stray
220-character swath and the mind's blurb — "tonight you are in the … head") when `speakbox_system`
is on. It colours vocabulary; it is never the subject.

**The writer.** `ask_model(prompt, limit, …)` — the station's fast model (`load_settings()["model"]`,
`gemma4:e2b`) at a temperature capped at 1.35, a fresh random seed each call, repeat penalty 1.12,
`max_tokens = limit/2 + 40`, the limit clamped to `reply_max_chars` (6,500). Its answer is cut back
to whole sentences; a reply with no finished sentence is a **fragment** and the caller's fallback
speaks instead (transcript repairs of 400+ characters and JSON-shaped replies excepted). The
round's line count is drawn between `banter_min_lines` and `banter_max_lines`, a caller forces at
least 11, a banked round gets four more than it is judged on.

---

## 3. The writing rooms — who writes the prose

Two rooms write, and the model lane admits them both.

**System2** (`system2_runtime.py`, the default engine since #1070) is the planner: it reads the
operator's schedule into templates (a slot's minutes become seconds; a track talk is one
performance of ≤ 15 s), plans every 15 s and prepares every 3 s, and runs **one sitting per lane**
(`_prepare_lock` = `OLLAMA_LANES`, 1..4). A sitting claims a job on a road that is not already busy
— ad, manager, caller, gallery, news, banter, track_talk, recap, deep — with a 900-second lease, and
hands it to `dj_banter` under a WORK context that fixes the budget: seconds 15..90, turns (11 for a
caller, else 4..12 from `generation_turns`), a word budget at 170 words a minute with 25% headroom,
and `source_chars` (80..220) — the one whole sentence of the seed the scene is built around
(`system2_writing.source_thought`). A scene is complete when it has at least `expected − 1` turns,
markers A–E, six words or more, terminal punctuation (`scene_complete`).

**The legacy keepers** stand down when System2 owns preparation and otherwise fill the same
stores: `larder_keeper` every 3 s (the reserve target `dialogue_reserve_target` = 4 rounds, 6 under
an ad, scaled by `prepare_hours`; paused, it writes until the unaired rounds reach the target under
`larder_cap()`), and `pantry_keeper` every 6 s → `prep_one(kind)` per shelf road (one producer per
road; it diverts to recording when three rows of a road are unvoiced; it refuses a new script while
a selected round is unready — "finish first", #1155 — and while `commitment_write_needed` says the
road is covered). `_LARDER_WRITING` is the one-at-a-time flag every other clock respects.

**Admission to the lane** (`call_ollama`): every purpose maps to a category — interactive (no
cap), the response bank and the SFX reserve (one each), anything tint-shaped (`tint`), the rest
(`station`) — with caps `station = lanes + 1`, `tint = lanes + 3` (+ 1 when a System2 slot starts
within 20 minutes). Over the cap a call is **deferred** without spending compute: a writer rests, a
tint raises `WritingDeferred` and its round waits 30 s. Inside the cap the lane semaphore
(`OLLAMA_LANES`, one per model) serialises the runner; a single-line tint ask yields up to 180 s to
a whole-round ask. The gate as a whole is `_OLLAMA_GATE` (2 × lanes).

**The models.** The writer: `gemma4:e2b`. The tint: `gemma4:31b` on the deep roads and under the
hold, `gemma4:e2b` as the fast fallback. The embedder: `nomic-embed-text`. One Ollama server on
`OLLAMA_URL` (127.0.0.1:11434) with one decode slot (`OLLAMA_NUM_PARALLEL` = 1).

---

## 4. The crystal — what it is and how its data is extracted

**What it is.** A crystal is *a portable vector database distilled from a catalogue — one or more
minds fused under a name, with a tint*. It lives in `data/crystals.json` as
`{name, minds, tint, strength (0–100, default 50), on, source, built}`. A **mind** is one indexed
document set of the speakbox (`data/minds/<id>`: the chunks and their vectors; the DOOM crystal's
minds hold 36,628 chunks). `source` decides what the crystal supplies: `speakbox` (the default —
the crystal colours the prompt, the speakbox still supplies the passages) or `crystal` (its own
minds supply the words too). The operator builds and steers it from the 🔮 view
(`/api/crystals`: upsert, toggle, extract lyrics, rescan, influence, seed, export, and `/rhymes`,
the Rhyme Cloud). `crystal_active()` is every crystal switched on; `crystal_force()` is the
highest active strength as 0..1 — the one number the tint calls *strength*.

**What is pulled out of it, and when.**

| extract | function | how |
|---|---|---|
| **stanzas** | `crystal_stanzas(most, lines)` | per file of each mind, contiguous runs of chunks in document order (text > 20 chars, not noise); windows of `CRYSTAL_STANZA_LINES` = 10 stepped a third apart, ≤ 24 per file, shuffled, then ordered by how long each chunk has rested; the run index is rebuilt every 300 s; the **served window is held for 20 minutes** (`CRYSTAL_MATERIAL_WINDOW` = 1200 s) so the runner's prompt cache sees one prefix |
| **material** (the fallback when no file is long enough) | `crystal_material(most, cap, ceiling, stable)` → `_crystal_material_sample` | a random draw (not similarity-matched) of chunks from the minds' stores, 64+ candidates per mind, texts ≥ 40 chars, deduplicated on the first 80 chars, capped 120–4000 chars each; `stable=True` memoises for the same window |
| **the world** | `crystal_world_prompt()` | `"{name} ({strength}%): {tint}"` for each active crystal — the operator's own description of the world |
| **the prompt-side tint** | `crystal_clause()` | the writer's prompt line *THE {NAME} CRYSTAL IS ON ({strength}%)…* with the style note; at strength ≥ 75 the "tint is total" paragraph; **empty when the two-pass tint is on** (`crystal_tint_pass`), so a round is not tinted twice |
| **the vocabulary** | `_crystal_vocab_build()` → `_crystal_vocab()` | every content word of every chunk of every mind of every active crystal, built once per crystal key in a thread (`crystal_vocab_warm`), unioned with the sampled pool's words; read by the lexicon check, the rhyme options and the rhyme assistance's *style words* |
| **the style pool** | `_CRYSTAL_POOL` | 240 material rows refreshed every 300 s, `CRYSTAL_STYLE_MOST` = 3 passages of ≤ 420 chars for the single-line roads |

A round's tint asks for `2 + round(surplus × 2)` stanzas of ten lines (two normally, up to four
when the station has room), falling back to `crystal_tint_chunks` = 5 passages of
`crystal_tint_chars` = 900. The stanzas, the world and the rules form the **cacheable prefix**
(`frame_prefix`), identical for every road and every ask inside the window; the road, the register
and the per-line evidence follow it.

**Rhyme assistance (the Rhyme Cloud).** `rhyme_assistance.py` keeps its own store
(`data/rhyme_assistance.sqlite3`): CMUdict pronunciations keyed by the tail from the final stressed
vowel, WordNet 3.0 senses and usage counts, and sense embeddings made by `nomic-embed-text` (the
embedding queue waits for model room — `waiting_for_model_room` — behind the writer and the tint;
a 30-second clock warms ≤ 8 senses at a time). For a source line it returns **WORD OPTIONS**: up to
three endings with three sound options each (in the source, in the crystal's style words, with
their usage), and three senses with alternatives — attached to the line's *source contract*
(`crystal_prompt_contract`, memoised 600 s) and emitted in the prompt as *WORD OPTIONS RETRIEVED
BEFORE WRITING*, never for another turn's line. This is the "decide the landing words first"
rule's raw material.

**The versions that stamp a verdict.** grader `CRYSTAL_GRADER_VERSION` = 9 · contract
`crystal_contract.VERSION` = 3 · prompt `PROMPT_VERSION` = 5 · acceptance
`crystal_acceptance.VERSION` = 2 · CMUdict `74790861…`. A stored proof (`tint_output_ready`) is
trusted only at version ≥ 4, at today's strength, and for 900 s.

---

## 5. The tint — prose into bars

The tint is the second pass over a finished round. `crystal_tint(script, kind, ...)` takes the
plain script (`script_plain`, speaker-marked turns `A:`/`B:`/`C:`…) and returns the same structure —
same markers, same number of turns, same order — with each eligible turn rewritten as bars, plus the
paperwork (the prompt armed, the passages injected, what came back, what it cost, the coverage
report). The structure is preserved on purpose so the two versions are comparable and the operator
can choose between them (#1016).

**Which turns.** Every turn of at least `TINT_TURN_FLOOR` characters with a word in it is eligible;
the coverage target (`crystal_coverage_target`, 100 by default) says what share must be tinted — at
100 every eligible line. The phone road's formula lines (the spoken line number, the greeting by
name, the sign-off; `_tint_formula_turn`) are read plain since this evening: a string of digits
cannot be rhymed while every number is kept.

**The passes.** A fresh round is asked for **whole** first (`_crystal_round_first_pass`: the round
prompt, every requested turn numbered, one model ask per output budget group of
`CRYSTAL_GROUP_OUTPUT_CHARS` = 1800), graded bar by bar, and only the refused bars are re-asked
**together** (`_crystal_round_repass`, batched). What is still refused goes to the **per-line** ask,
at most three asks a line under the hold (#1064), each carrying the prior candidate and its
evaluation as REPAIR EVIDENCE, the repair hint, the per-line fault memo and the road's lesson. A
line that runs out of asks is **cut before the studio**: the round keeps its accepted bars (a
caller round does not — a call carries no cuts, #1146 — so a caller round with one cut goes to
replacement; its accepted bars are now harvested as gold, see §9).

**Strikes and rest.** A line refused twelve times across passes is *exhausted*
(`TINT_STRIKES_MOST` = 12, `tint_exhausted`): the row stops holding a stocking slot and the scheduler
writes its replacement. A round refused admission to the lane rests `TINT_DEFERRED_REST` = 30 s
before the recovery clock asks again.

**Progress that survives.** Every pass writes `entry["tint_progress"]` — per turn, the candidate,
its evaluation, `selected`, `cut` — so a restart or a later pass resumes from what passed
(`_tint_retry_accepted`), and the cupboard shows *rapping k/N*.

**The models.** `tint_model_for(kind)` names the road's model: under the hold `tint_model_now()`
— the operator's `crystal_tint_model` (the deep one, `gemma4:31b`) while more than half the tint's
time budget is left (`TINT_SHARE` = 50% of the writing time, `TINT_SHARE_MOST` = 75%), else
`tint_fast_model()` (`gemma4:e2b`); off the hold, the deep model on the deep roads
(`TINT_DEEP_ROADS`: banter, callers, the deep round) and the fast model elsewhere. Under the hold the
deep model runs on every line; measured today, one ask every 25–30 s on the one lane, so an
eight-turn round costs five to eight asks — the physical ceiling of "the deep model on every line"
is about a dozen rounds an hour for the whole station.

**The room a bar gets.** A line's output budget is `1.5 + 0.5×strength` to `2.5 + 0.9×strength`
times its source length, never below 90 characters; a round's batches are planned by `budget_plan`
(`1.6 + 0.8×strength` per source character plus 64 overhead, at least 160 per turn) so no source
is ever truncated to fit.

**Admission.** Every model call goes through `call_ollama` under a category cap
(`_ollama_category_cap`: tint = `OLLAMA_LANES` + 3 waiting, station = lanes + 1, one each for
repertoire and the SFX reserve) and the lane semaphore (`OLLAMA_LANES` = 1 since this morning — two
decode slots measured 0.96× the throughput of one). A refused admission is a *deferral*
(`WritingDeferred`), not a failure: the caller rests and returns.

**What rides the prompt** (in `crystal_operator_refinement`, one funnel for every rewrite): the
operator's crystal instruction (the rejection lab's *future crystal instruction*), the learner's
observed-lesson bullets (≤ 4 per road, ≤ 1,000 characters), and since this evening **THE
ORCHESTRATOR'S REFLECTION** for the road with two accepted bars as exemplars (§11). On every model
call, as a system message: the operator's wording preferences (`line_review_guidance`) — allow/keep
decisions and, now, the wordings approved as written.

---

## 6. The grader — how a bar is judged

`tint_evaluate(original, candidate, chunks, answering, force, kind)` is deterministic — no model —
and runs the same checks whether the bar came from the first pass, a repair, a workbench trial, a
recovery, or the operator's own hand. In order:

| check | what it measures | refusal (blocking) |
|---|---|---|
| **meaning** (`crystal_compare_contract`, crystal_contract.py, contract VERSION 3) | content anchors recalled above a floor that falls with strength (0.5 below 0.45, 0.35 from 0.45, 0.2 from 0.75 — the harder the tint, the more paraphrase is allowed), names kept (heuristic names advisory), numbers kept and none added (idioms and pronominal "one" waived), a question stays a question, a negation stays where it was, no unsupported positive contrast | *semantic preservation failed* |
| **caller contract** (callers only, `call_tint_report`) | the call's structure survives the rewrite: the line answered, the introduction, the greeting, the sign-off | *caller structure did not pass* |
| **rhyme** (`rap_rhyme_evidence`) | end pairs across bars (the spelling reading `_rap_slant` on landings, plus the pronunciation dictionary `terminal_rhymes`, CMUdict, matching every phone from the final stressed vowel), a chain with the previous bar's end, internal pairs, multisyllabic pairs; a long transcript needs two end pairs | *no rhyme evidence — the bar does not land a rhyme* (required at strength ≥ 0.45) |
| **transformation** | lexical distance ≥ 0.18, no five-word run of the source kept verbatim, cadence or lexicon or length changed — **or**, since this evening, a proved end rhyme the source did not have (`rhyme_added`) | *rhetoric was not materially transformed* |
| **copying** | no six-word phrase lifted from the style passages | *copied a prohibited six-word source phrase* |
| **lexicon** (strength ≥ 0.75) | a word borrowed from the crystal's vocabulary | strict grade only; advisory under meaning |

**Two grades.** The *meaning* grade (the default, #1064) enforces meaning, rhyme, transformation and
copying and reports the rest as advisory; the *strict* grade (`crystal_grade_strict`) enforces the
spelling proof and the lexicon too. **Fluid acceptance** (the learner's mode, crystal_acceptance.py,
VERSION 2) waives exactly two style faults — *not transformed* and *no lexicon word* — and only when
the meaning block, the caller contract, the copying check and the rap reading all hold on their own;
it still blocks a candidate that turns an attempt into an accomplished action or leaves an orphaned
source tail. The *editorial* block of the report says which faults blocked and which were advisory.

**Order of the checks** inside `tint_evaluate`: normalise → meaning contract → caller contract →
rhyme (spelling reading, then the rap reading, then `rhyme_added`) → lexicon → transformation →
copying → grade → repair hint → editorial acceptance → operator approvals → the judge ring.

**The operator outranks the grader.** `line_review_permits` asks the review store whether this
source/candidate pair was allowed (a standing allow, an instance grant for a recovery, or a wording
approved as written); if so the report is stamped `operator_accepted` and passes. Every verdict also
lands in `_TINT_JUDGE_RING` (the last 40, for the LCD and the reflection) and in the learner's
outcome table.

**The repair hint** (`tint_repair_hint`, on every refused report): the two landing words and crystal
words that would rhyme with them (`rhyme_options_for`, chosen by the grader's own reading), the
names, numbers and source words to put back, the question/negation to keep, and — for an echo — that
the source was handed back unchanged and the shape to write instead.

---

## 7. Cut lines, the review store and the desks

A line cut before the studio is recorded in the **line review store** (`line_review.py`,
`data/line_review.sqlite3`): gate (`tint`, `segment_brief`, `call_contract`, …), source, candidate,
reasons, the full evaluation, the round's context. Rows the machine handled itself — a rewrite
refused and re-asked, a trimmed draft, a fragment, the recording room's hold, a cut graded by a
superseded grader — are **notes**; only a line that actually left the work is **pending** and waits
for the operator (the Pine Box card *N cut lines wait for your decision*, the panel's Rejected
lines drawer, the LCD review popup).

**Decisions.** *Allow* (the wording may air; a standing approval of the pair) or *keep* (the cut was
right), each with a note that becomes a wording preference the writer sees. The **rejection lab**
(rejection_workbench.py, rejection_lab.py): *Discuss* (the orchestrator explains the cut with the
captured prompt trace), *Trace* (every request and reply of the rewrite pass), *Try wording* (a
candidate graded by the real gate, receipts kept), *Apply* (a passed trial recorded), and since this
evening **Approve as written** — the operator's own wording applied with the operator's authority,
the machine report recorded and never a gate, the instruction kept as a standing lesson for that
kind of line.

**Recovery.** `line_review_recovery_loop` picks allowed rows and instance grants, `build_recovery`
puts the approved wording into the round's turn, and the recording room records that wording;
`line_review_recorded` confirms it aired. A later bar for the same source that passes on its own
supersedes the pending cut (`line_review_supersede`).

**The retirement desk** (`/cupboard/retire`): every road that would delete a cupboard item asks
`retire_may(kind, row, why)` first; a rhymed item (by default) waits for the operator — *remove* or
*keep* (life and airings extended) — with rules per type (ask: rhymed only / everything / never;
keep hours; airings) and a live life timer on every item. Hard ceilings still bound each store.

---

## 8. The recording room — bars into takes

A tinted round is voiced one turn at a time into **takes**, each a clip in the pantry keyed by
(text, voice, engine). The room:

- **Booths.** `ENGINE_BUDGET` = 3 renders at once; on air two of them are reserved for live lines
  (`prep_limit = capacity − 2`), paused all three prepare; one preparation render per engine at a
  time (`same_engine_limit` 1), parallel only across independent engines.
- **Engines.** `voice_render_any` walks a ladder — the asked clone engine, the other clone engine,
  piper, then a floor — and splits anything over 800 characters. XTTS v2 (the clone server on
  :8770, CUDA on the GB10), F5-TTS (:8772), Voxtral (:8000), IndexTTS (:8774), piper (Wyoming
  :10200). The cast lock keeps the presenters on their engine; `avoid_piper` (on) keeps the fast
  engine off the cast seats. `render_cost_note` measures render time against audio time and turns
  **relief** on past 7× real time, off below 3.4×.
- **The hold before the microphone.** A conversation is voiced only after
  `ensure_entry_tinted` / `ensure_shelf_row_tinted` pass; a line that fails the crystal here is
  held with the reason *recording held* (a note, not a decision) and goes back to the tint.
- **Ready.** `dialogue_audio_ready`: `chunks` > 0, `made ≥ chunks`, not partial, every key in
  `entry["keys"]` and `entry["takes"]` present on the shelf and on disk. With the tint complete and
  the contract current, the row is `dialogue_row_ready` — zero work to air.
- **The pantry beneath.** Clips live `pantry_life()` (90 min floor, up to 24 h with the
  build-ahead dial) unless something viable or waiting on the desk holds them; the row ceiling
  (600–4,000, raised above the held set) and the 6 GiB allowance shed loose clips first. A line
  that is asked for again with the same words, voice and engine is served from the pantry with no
  render (#842).

---

## 9. The stores and their clocks

| store | what | file | life |
|---|---|---|---|
| **larder** `_LARDER` | banked booth rounds (banter), each an entry with `script_plain`, `script`/`script_tinted`, `tint`, `tint_progress`, `keys`/`takes`, `at`, `aired`, `profile` | `data/larder.json` | plain: 90 min unaired (`larder_fresh`), 72 h as an aired repeat; **rhymed: 96 h** (`keep_until`); cap `larder_cap()` (14 × hours dial) for stock **plus** up to 80 rhymed rows of repertoire (`larder_trim`) |
| **shelf** `_SHELF[kind]` | prepared rows per kind: ad, station_id, manager, caller, gallery, news, track_talk, recap… (`SHELF_CAPS`) | `data/prep_shelf.json` | unheard 72 h, aired repeat 72 h, news 3 h (`stock_expires_at`); rhymed 96 h; reusable kinds rest 3 h between airings (`SHELF_REUSE_REST`, floor 1 h) with 3 innings, 12 for evergreen kinds and for any rhymed row |
| **pantry** `_PANTRY` | rendered clips keyed by (text, voice, engine) — `pantry_key` | `data/pantry.json` + `media/` | `pantry_life()` = 90 min floor to 24 h, unless something viable or waiting on the desk holds the clip; 600–4,000 rows, 6 GiB |
| **gold bars** `_GOLD` | a rhymed line that aired, with its exact take | `data/gold_bars.json` | 400 rows, each rests 20 min (5 min on the dead-air road); the audio is protected from the media sweep |
| **continuity reserve** | 14 fixed two-host pairs, rapped through the crystal | `data/continuity.json` | each line rests an hour |
| **hold shelf** `_BOX_HOLD` | clips waiting for the box | `data/box_hold.json` | drained six at a time |
| **resume reel** `_REEL` | one welded clip for the unpause | — | rebuilt when consumed |
| **responses / SFX Guy bank** | pre-rendered listening reactions and liners | `data/sfxguy_speech.json` … | 64 per voice / 512 |

**Zero-work-to-air** is one predicate: `dialogue_row_ready(kind, row)` = the writing contract holds
(`_larder_current`; a rhymed round inside its keep is current by definition), the caller contract
holds, the tint is complete (`dialogue_tint_ready`: `script == script_tinted`, `use == tinted`, the
coverage stamp met at today's target and strength), and every planned take is on disk
(`dialogue_audio_ready`). `dialogue_row_viable` is the weaker "can still become ready without a
rewrite" that counts against stocking caps and holds clips.

**Why things used to vanish.** Every expiry rule was written for a ninety-minute cache and none knew a
round was rhymed; the writing contract carries the plot's act, and an act rolling over rebound the
larder to viable rows — 22 rhymed rounds went in one tick at 13:54 today. Both are closed: the
96-hour keep, the desk on every deletion road, the contract yielding to the keep.

---

## 10. The schedule and the air

**The hour contract.** `coord_hour_start` opens an immutable contract of 3,600 active seconds
with a target per road; `coord_hour_close` scores it — 85% delivery, 10% adherence to the running
order, 5% brief quality — and feeds the per-road learning factor that orders production. Five
clocks run independently (the phone, the ads, the bulletin, the memos, the sponsor): `quota_due`
says when a kind is owed (spacing 3600/target, collapsing to a third when the hour is behind, never
below the kind's floor — 240 s for a memo, 180 s otherwise) and `clock_may_air` lets a clock take
the air when the sheet allows or the air has been quiet more than 25 s. Nothing is owed while
paused: a pause banks.

**The running order.** The operator's schedule names the entries; `schedule_adherence` keeps the
kept/missed ledger; `gap_kind_policy` swaps a live-only kind for a banked one after a measured
silence or in the resume runway ("stock before prose"). `hour_shortfall` says which entries have
material behind them — the number the 🎛 view's SCHEDULE station shows.

**Pulling a round.** A plain booth round shops the larder (`alt_larder_index`: the first ready,
current, rested row; unaired first); a shelf kind takes from its shelf (`shelf_take`: unaired first
in strict FIFO for callers, then repeats that have rested and have innings left; burnt rows and
rows the desk holds are skipped). `_banter_air` is the single door onto the air; `speak_turns`
takes the **floor** (`_FLOOR_LOCK`) for the round — one round at a time, the hold named by stage
(*render*, *play*), lent out during a tint ask, and declared stale after 1,500 s so a wedged round
cannot blind the watchdogs.

**Delivery.** Each turn is rendered (or served from the pantry), announced to the Pine Box
(`_play_on_box`; a busy or down box queues it on the hold shelf, drained six at a time by
`box_hold_watch`) and appended to the page feed (`page_feed_append`, the one door: every clip
carries a broadcast instant no earlier than the page's own air clock, which each clip extends by
its measured length — the page-gap law). Every aired line is written to the **print ledger**
(`print_remember`, 8,000 rows kept 24 h, each row flagged *gold* when the line rhymes) so
`rerun_check` refuses a word-for-word repeat: a whole sentence at any distance, a catchphrase under
24 characters for 24 h, a gold bar until half the repeat window has passed. The fuzzy leg (4-word
shingles) stands down while more than 35% of recent candidates are being blocked
(`BLOCK_RATE_CAP`), so the anti-repeat engine can never silence the station.

**Silence, and what fills it.** Two watchdogs: `dead_air_watch` (nothing playing, nobody
speaking, nothing rendering for longer than the dead-air dial → kick the next record; a third
strike restarts the show) and `talk_watch` (no cast line for `talk_quiet_limit()` → `cover_the_gap`).
The cover order since this evening: the continuity reserve (a rapped two-host pair) → **a gold
bar** (a rhymed line's own take, no render) → the SFX Guy's prepared liner → a sample → a live
cover line rendered on the spot. Every silent tick past 12 s is punctuated with a clip that exists
(`sfx_fill_gap`), even under a floor held for a render (samples only there).

---

## 11. What the station learns from its own work

| loop | records | derives | applied where | live? |
|---|---|---|---|---|
| prompt learner (prompt_learning.py) | every graded attempt (`prompt_outcomes`, 4,000 window), every non-technical refusal, every operator decision | up to 4 hints per road from a catalogue; recipes escalate v1→v3 when a fault family keeps failing; revisions journaled | OPERATOR CRYSTAL REFINEMENT slot of every rewrite | yes |
| operator wording preferences (line_review.py) | allow/keep decisions with notes; wordings approved as written | the last 24 as literal examples | a system message on every crystal call (`line_review_guidance`) | yes |
| the fault memo (`_TINT_FAULT_MEMO`) | the faults of every refused line, keyed on the source | "this exact line was refused N times before for…" | the first ask of that line (EARLIER REVIEW FEEDBACK) | yes, in RAM |
| the repair hint | computed at grade time | landing words, rhyme options, facts to put back, the echo | the re-ask | yes |
| **the reflection** (`reflection_clock`) | the hour's accepted and refused bars per road, the learner's counts | three writing rules and two exemplar bars from the road's own model, versioned per road, retired when the road gets worse | THE ORCHESTRATOR'S REFLECTION in every rewrite prompt of the road | yes, hourly per road |
| the judgment book (#1150) | operator moves per road | a production factor and a lesson | ordering only — the lesson never reaches a rewrite | factor yes, lesson dead |
| the rejection lab's trials | every trial and trace (180k traces) | nothing | nothing — by design (a preview never trains) | recorded only |
| the grader's thresholds | — | — | pure operator dials; nothing adapts them | no |

---

## 12. The dials that decide

| dial | default | what it moves | where |
|---|---|---|---|
| crystal on / minds / strength | per crystal | which world tints, how densely | 🔮 panel, `data/crystals.json` |
| `crystal_coverage_target` | 100 | share of eligible turns that must be tinted | settings |
| `crystal_tint_holds` (the hold) | on | a round waits for its tint instead of airing plain | settings |
| `crystal_grade_strict` | meaning | strict adds the spelling proof and the lexicon demand | settings |
| learner mode | fluid / strict | fluid waives style faults when meaning and rhyme hold | rejection lab |
| `TINT_STRIKES_MOST` | 12 | asks a line may cost before it is retired | code |
| per-line asks under the hold | 3 | asks per line per pass | code (#1064) |
| `OLLAMA_LANES` / `OLLAMA_NUM_PARALLEL` | 1 / 1 | decode slots; the tint cap is lanes + 3 waiting | compose / systemd |
| `SHELF_REUSE_REST` | 3 h (floor 1 h) | rest between airings of a repeat | settings |
| `TINTED_KEEP_SECONDS` / `TINTED_KEEP_ROWS` | 96 h / 80 | the rhymed keep and the repertoire's room | env, retirement desk rules |
| retirement rules per kind | ask rhymed / 96 h / 12 airings; news never | who is asked before a deletion | `/cupboard/retire` |
| `GOLD_REST` / `GOLD_GAP_REST` / `GOLD_MAX` | 20 min / 5 min / 400 | how often a bar comes back, how many are kept | code |
| `SFX_GAP_REST`, `sfx_gap` | 9 s / dial | rest between gap clips | env / settings |
| `REFLECTION_EVERY` | 1 h per road | how often the orchestrator reflects | env |
| `dead_air_seconds`, `talk_quiet_limit` | dial / 95 s (12 s at full talk) | when silence becomes a fault | settings |

---

## 13. Where to look

| surface | what it shows |
|---|---|
| **🎛 RapAssembly** (the 3js rail, `/api/rapassembly`) | this whole line as ten lit stations with packets travelling the hand-offs off the pipeline diary — asks, verdicts, renders, lines, covers, reflections — and a rail with every number below |
| `/api/tint` | coverage this hour, the fault memo, strikes, lanes, the material window |
| `/api/dj` → `dialogue_flow` | ready/target, blockers, `repertoire`, `gap_filler`, `retire` |
| `/api/orchestrator/logic` | the pipeline stages (ready / awaiting tint / rewriting / recording / needs replacement), writers, deferrals |
| `/api/orchestrator/rejections`, the Rejected lines drawer, `/cupboard/retire` | cut lines and their evidence; the retirement desk |
| `/api/orchestrator/reflection?kind=` | the road's rules, their measured effect, the hour as the reflection read it |
| `/api/cupboard`, the LCD paused page, the 🗄 view | every stored round with its bars, stage, life timer and airings |
| `/api/pulse`, `/api/pine-journal`, `/journal` | event-loop stalls; the request book |
| the pipeline diary (`pipeline_log`) | *crystal*, *model*, *lookahead*, *air* lines — every ask, refusal, deferral, cover |

---

## 14. Decisions this document is meant to support

- **Depth versus speed.** The deep model on every line is the ceiling (~a dozen rounds an hour). The
  levers are the fast model on single-line roads (ads, memos, IDs), a second recording engine for
  non-presenter seats, and coverage below 100 on roads that need not rhyme.
- **What counts as a rhyme.** The dictionary now proves perfect pairs; slant pairs (calm/harm,
  next/test) are still refused. Accepting slant as advisory would rescue more bars at the cost of
  looser rhymes.
- **The meaning gate's strictness.** A dropped negation or an added question is refused outright;
  the census counted 60 and 20 such cuts. Relaxing either is a taste decision, not a technical one.
- **The repertoire's share of the air.** Rhymed rounds keep 96 h with 12 airings at a 3-hour rest;
  raising airings or shortening the rest makes the station repeat itself more and write less.
- **Who is asked before a deletion.** The desk asks about rhymed items by default; "everything" makes
  every cupboard deletion an operator decision, "never" restores the old sweeps per type.
