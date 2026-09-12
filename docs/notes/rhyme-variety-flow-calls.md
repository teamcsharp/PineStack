---
name: rhyme-variety-flow-calls
description: "2026-09-08 night: the rhyme dictionary (pine_rhyme), why the writer landed on furniture (the anchor floor, not the prompt), why 8 lines aired 100+ times (continuity tried before gold), and why 29% of calls vaporized (the 2/4/8 page ladder)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T04:38:34.990Z
---

**The operator's asks (2026-09-08 night):** varied rhymes out of the DOOM crystal's own lexicon, not
"must" over and over; hosts and callers competing for the dopest bars; off-the-wall sentences in the
crystal's register; phone calls that COMPLETE ("I dont like hearing the customers just vaporized")
with an adjustable scenario + RNG path + randomly generated conclusions; a complex rhyming
dictionary; and **at longest a 10-second intermission** with a deep repertoire filling all dead air.

**FOUR ROOT CAUSES, all measured, none of them the writer's vocabulary:**
1. **THE REPETITION IS THE COVER BANK, NOT THE WRITER.** 17 lines carried 1,085 of 6,000 airings in
   four days; all 8 lines that aired 100+ times are `CONTINUITY_PAIRS` lines (a bank of 28 tried
   BEFORE the bank of 400 gold bars). Fresh bars are varied: 2,629 distinct landings, 63% used once.
   The ripe/tight, motion/notion and reside/ride couplets are ONE RECORDING EACH, announced 100+ times.
2. **THE WRITER LANDED ON FURNITURE BECAUSE THE GRADER MADE IT.** Crystal-register bars fail the real
   grader 4 of 6 and EVERY failure is the meaning contract's anchor floor, not one a rhyme fault -
   the writer spent the style on the source's own nouns and had nothing left to keep. Accepted turns
   sit at a median anchor_recall of 0.75. THE RULE (never stated in the prompt until now): the
   crystal does NOT replace the source's words, it FURNISHES WHAT THE SOURCE DID NOT SAY - keep the
   nouns/names/numbers in the BODY, spend the crystal on the LANDINGS and the turns. Written that
   way the same sources pass 3 of 4. Only 13.2% of landings were distinctive crystal words; a proven
   multisyllabic pair appeared in 0.0% of accepted turns. DO NOT lower the anchor floor.
3. **`rhyme_options_for` WAS ALPHABETICAL**: it walked `sorted(vocab)` and broke at 40 hits, so 70%
   of every suggestion began with a/b/c ("rhymes with 'be' - ability, adhd, albee, anarchy"). And the
   fluid-acceptance block literally said "do not add an unusual style word" - the ask reversed.
4. **29% OF CALLS VAPORIZED VIA THE 2/4/8 PAGE LADDER.** `_speak_turns_floorless._batches` pages a
   round 2/4/8; the air STOPS at each boundary awaiting TTS. 18 of 62 aired calls never said goodbye
   and every one has a >=36 s hole INSIDE it (121 s once); the clean ones are all <20 s. The escape
   was `_all_hit and _est_secs <= 150` (one page). MILAN aired 6 of 11 = pages 1+2 exactly.

**SHIPPED (commit e616ed8, deploy 2026-09-08 ~22:36 CST, 380 tests green):**
- `work/pine_rhyme.py` + `data/rhyme_families.json`: the crystal's RHYME FAMILIES (live on the host:
  6,721 families / 16,698 words / 5,936 multisyllabic), ranked by DISTINCTIVENESS (crystal frequency
  saturating, WordNet tagged counts as drag, syllables past the stress as reach, function words and
  a DERIVED furniture list penalised). Built in ~10 s inside `crystal_vocab_warm`'s worker thread via
  `_crystal_vocab_counts()`; 2.6 MB; a warm ask 0.01 ms vs 442 ms. `vocab=_crystal_vocab()` is the
  AUTHORITY on membership (the pinned RepairHintTests patches it to 16 words - that is why the
  parameter exists). `_rhyme_options_scan` is the mandatory fallback.
  Live answers: must -> bust lust trust cussed rust crust; station -> domination intoxication
  inspiration meditation reincarnation; it -> shit lit spit bullshit wit quit.
- `crystal_landing_pairs()` -> `crystal_prompts.crystal_landings()`: ANCHORED pairs (a word the source
  already said + the crystal's answer) reach the FIRST ask, after the `Road:` cache cut.
- The prompt's static rules (inside the cacheable prefix, zero per-ask cost): the furnish rule, "the
  landing is where this station is heard", and rule 5 "off the wall, inside the facts" (a flourish
  like "not one"/"never" is a DENIAL the source did not make; "vapour" is not in CMUdict).
- Flow: `cover_the_gap` spends `sfx_fill_gap` (gold-first) BEFORE `continuity_air`; `gold_fill_gap
  (floorless=True)` uses `_dj_speak_floorless` so a finished bar can fill a gap UNDER THE FLOOR (that
  silence was 20% of all on-air time); GOLD_MAX 400->2000; TALK_INCESSANT_QUIET_MOST 12->8, cover
  rest 4->3, SFX_GAP_REST 9->6, GAP_STOCK_FIRST_AFTER 40->12.
- Calls: `elif caller_name: spans = [(0, len(playlist))]` - A PHONE CALL IS NEVER PAGED; `_cut_closing`
  (the last two turns of a caller round may never be cut - the sign-off is a HOST line, which
  `_cut_caller` never protected); the start-of-round checks guarded with `not played_any`; and the
  station going off mid-round now marks `missed` so it cannot forge a completion.

**STILL TO BUILD - the scenario engine, specified in full in `rhyme/calls/report.md`:**
data/call_scenarios.json (premise/want/stance/register/boundary/heat/system_prompt/conclusion_pool),
`call_path_draw` over six weighted beats (~11,250 paths per scenario against 512 total today) rendered
into ONE prompt (~700 chars; a model ask per beat would cost 18-24/hour = 2-3 rounds of tint), and
`call_conclusion_report` verifying the drawn conclusion is STATED in the last three turns - SHIP THAT
SOFT for a day first (the `soft_quality` mechanism), because it is lexical and the DOOM tint states
endings obliquely. THE KEY FINDING: `_fallback_call_script` is a fixed 11-turn skeleton with three
draws = 512 calls with IDENTICAL connective tissue ("moved closer, checked it twice" x44 airings),
so `call_novelty` correctly refuses every new call once a handful exist -> the caller shelf empties ->
the live road -> the page ladder. THE TRUNCATION AND THE SAMENESS ARE ONE FAULT.

**Why:** every refusal that is the reader's fault costs three deep asks on the one lane that gates the
whole stack, and every road that reaches for the shallowest bank is what the listener hears twice.
**How to apply:** before blaming the model's vocabulary, measure WHICH READER refused and whether the
ear agrees; before blaming the writer for repetition, separate repeated LINES from repeated WORDS.
See [rejection-deep-scan-and-stack](rejection-deep-scan-and-stack.md), [repertoire-dead-air-lcd](repertoire-dead-air-lcd.md), [tint-yields-to-air](tint-yields-to-air.md).
