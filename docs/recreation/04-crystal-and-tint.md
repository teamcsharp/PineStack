# 04 — The crystal and the tint

## The idea

Everything the station says is written plain first (stage 3), then **rewritten through a crystal**
— a world with its own writing — and only a rewrite that keeps the meaning and proves its rhyme
goes to the recording room. The operator's rule since #1063/#1064: the hold is ON; while it is on the
whole station raps; a line that will not rap is cut before the studio, never aired plain.

## Crystals, minds, the speakbox

- **The speakbox** (`speakbox/`, bind-mounted to `data/speakbox`) is the operator's own documents:
  transcripts, notes, books. `speakbox_reindex` chunks and embeds every mind's folder into
  `data/speakbox_vectors.json` (nomic-embed-text); the studio's grounding draws a **swath** of one
  document per round (`speakbox_rate`, `speakbox_prepend_rate`, `speakbox_full_swath_rate`,
  `speakbox_full_swath_chars`), the document lock (#674) pins it to one document for an hour of study.
- **Minds** (`data/minds/<id>/docs`, registered in `settings.dj.speakbox_minds`) are more folders
  the same machinery indexes: the studio (`main`), topical minds, and the **album minds** a crystal
  extraction creates (#832: one mind per album, `alleninterface-*`, `doom`).
- **Crystals** (`data/crystals.json`): `name`, `tint` (the world description), `strength`, `minds`,
  `on`. `crystal_active()` is the list of crystals switched on; only THEIR minds supply passages to
  the tint. A crystal that is off contributes nothing — its album minds stay registered for
  re-indexing and re-extraction but are never the mind in play (#1085: the studio's own folder was
  clean; the Allen Interface mentions were record announcements from the music rotation).
- `crystal_material()` (random passages from the active crystals' chunks) and `crystal_stanzas()`
  (contiguous runs of `CRYSTAL_STANZA_LINES` lines out of one file — what shows how a bar is BUILT)
  supply the style passages; both hold one sample for `CRYSTAL_MATERIAL_WINDOW` (20 min, #1081) so
  the runner's prompt cache sees one prefix.

## The two passes (`/api/tint` → `stages`)

1. the foundation: the station's system prompt + the segment's standing instruction;
2. the speakbox injection: passages of the operator's documents as material;
3. the conversation: the writer model (`gemma4:e2b`) writes the round UNTINTED; the reserve keeps it
   as the original;
4. the tinting pass: the finished round goes back through the model (`gemma4:31b` deep; the fast
   model when the budget runs low, `tint_model_now`) with the crystal's world and passages, told to
   move it into that world without changing the structure or the facts (`crystal_tint`,
   `_crystal_round_first_pass` → `_crystal_round_repass` over the refused turns → per-line
   `crystal_turn` with up to three asks under the hold → cut);
5. evaluation and readiness: both versions are kept; selected lines must pass; unmet coverage holds
   the recording (`crystal_coverage_target` 100, `tint_coverage_ready`).

## Prompts (`crystal_prompts.py`)

`_frame(world, chunks, force, kind, operator_instruction)` — the priorities (1 meaning, 2 format,
3 bars and rhyme with the landing words decided first, 4 the writer's cadence and lexicon, no
six-word copy), the strength (`_demand`), the shared source-contract rules, THE STYLE WORLD, HOW THAT
WRITER WRITES (the passages), then the road (`Road:`) and the print register for the Gazette
(`_register`, #1075). `turn_prompt` adds the output format, the ORIGINAL SOURCE, the SOURCE
CONTRACT, the WORD OPTIONS (rhyme assistance), the previous turn, the REPAIR EVIDENCE (rejected
candidate + compact evaluation) and the lesson; `round_prompt` does the same per requested turn with
speaker markers or numeric IDs. `PROMPT_VERSION` 5. The stable material comes first so the prefix is
identical across roads and asks (`frame_prefix`, #1081).

## Contracts (`crystal_contract.py`, `crystal_source.py`)

`extract_contract(source)` → names, numbers (incl. spoken clock times, #1075), questions (tense and
scope), negation and what it binds, content anchors; `compare_contract(source, candidate)` → faults.
VERSION 3. The operator's fidelity rules pinned by tests: a changed name is refused, a question keeps
its word order, an unknown opener is not waved away, "one thing" keeps its count.

## The evaluator (`tint_evaluate`, `crystal_rhyme.py`, `crystal_acceptance.py`)

Deterministic: semantic preservation (the contract), internal/multisyllabic/chained rhyme evidence
(CMUdict pronunciations, `rap_rhyme_evidence`, `CRYSTAL_GRADER_VERSION` 9), rhetorical
transformation (unchanged = refused), no copied six-word phrase from the passages, no meta talk
(`_looks_meta`). The grade is "meaning" (the spelling-level proofs are reported beside it unless
`crystal_grade_rhyme` makes them block). Every refusal is a **line review** with its faults.

## Hold, coverage, cut, strike

- `crystal_tint_holds()` (settings `crystal_tint_hold`, on): unproved dialogue is HELD off the air.
- `crystal_coverage_target()` 100: every eligible line must pass or be cut.
- A line refused after its asks is cut before the studio (`disposition="cut"`, #1064); a whole call
  that fails the phone contract is struck and the graded plain call stands back up
  (`_call_tint_strike`, #1146).
- The retry budget (`_tint_retry_note`, `tint_retry_status`): four stagnant answers → a cooldown
  ladder (300/600/1200/1800 s); twelve → **struck out** (#1082), released only by the operator's own
  recovery; a struck-out row is no longer viable and the scheduler writes its replacement.
- The fault memo (`_TINT_FAULT_MEMO`, `tint_prior_lesson`): the first ask of a line seen before
  carries its earlier faults and refused wording (#1082).

## Review and learning

- `line_review.py` — every cut or refusal with its source, candidate, reasons, context and
  evaluation (SQLite `line_reviews`, 655 MB after a day and a half); the operator's decisions
  (allow / keep / replace) bind one exact candidate; preference examples ride the prompt.
- `prompt_learning.py` — the learner: refusals classified into fault families per road, recipes as
  bounded prompt reminders, outcomes measured per attempt with a baseline pooled across versions, a
  10 % trigger, promotion on relative improvement (#1078). Revision history at
  `/api/orchestrator/learning`.
- `rhyme_assistance.py` — CMUdict + WordNet in SQLite (`counts`: 132,962 phones, 117,659 senses),
  hashed lexical vectors, optional nomic embeddings (8 rows embedded; the warm loop waits for lane
  room); `crystal_rhyme_assistance` (memoised 10 min) supplies the WORD OPTIONS; the Rhyme Cloud
  (🎤) draws the crystal's landing words per chunk.

## Throughput

One deep runner slot was the station's ceiling (`docs/system2-capacity-1080.md`); since #1080 two
slots per model (`OLLAMA_NUM_PARALLEL=2`, `OLLAMA_LANES=2`), admission caps `lanes + 1`, a third
permit for due System2 work, and the cacheable prefix (#1081). `/api/tint` reports `coverage`,
`rhyme_assistance`, `fault_memo`, `material`, `stanzas`, `lanes_per_model`, `strikes_most`.
