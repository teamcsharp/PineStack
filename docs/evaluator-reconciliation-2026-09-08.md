# The evaluator reconciliation (2026-09-08)

The #1076 audit found that 17 % of tint refusals were the evaluator's own mistakes and wrote three
patches; applied whole, they broke seventeen tests that pin the operator's fidelity rules, so they
were held back. This is the rule-by-rule pass: every audited false-refusal class was re-implemented
as the narrowest rule that fixes the journaled examples, and every pinned rule still holds. No
version constant moved (`CRYSTAL_GRADER_VERSION` 9, contract `VERSION` 3, `PROMPT_VERSION` 5): the
readings only accept more, so nothing the reserve has already proved is thrown away and the
learner's cohorts are not reset.

## The rap reading (app.py `_rap_*`, `rap_rhyme_evidence`)

| class (audit share) | rule now | pinned rule kept |
|---|---|---|
| landing word in the stop list — "imagine **that**", "way **through** / for **you**", "by and **by**" (31 of 307 refused bars) | a bar's landing is the last word not in `_RAP_END_EXCL` (articles, conjunctions, to/of/as/if/nor); landings compare with `_rap_slant(end=True)` and the dictionary may prove them; internal pairs keep the full stop list | prose does not rhyme on its pronouns (`test_tint_rhyme` PROSE, `test_crystal_whole_resume`) |
| silent e before a plural / past ending counted as a syllable — "seems / schemes" (2) | `_rap_norm` drops the e of -es/-ed when the ending is not a syllable; `_rap_depth` reads -ed like -s | "walking/cooking", "garbage/back", "dramatic/specific" still refused |
| unstressed final -y read as the vowel of "sky" — "plain to see / a century" (11) | `_rap_nuclei_end` reads a final -y/-ey/-ie of a two-nucleus landing as "see"; one-nucleus "fly/sky/why" unchanged | internal pairs stay strict |
| "called / call" as an internal pair | one stem is not a pair | — |
| **new guard** | two fragments of three words or fewer need an exact coda to count as bars ("The red gate / Seven copper plates" is prose; "By the red gate we wait / Seven copper plates" is a pair) | `test_ordinary_short_comma_prose_does_not_gain_invented_bar_boundaries` |

## The contract (crystal_contract.py)

| class (audit share) | rule now | pinned rule kept |
|---|---|---|
| capitalised sentence opener required as a name — "Yeah", "Grab", "Cuz", "Just" (66 of 138 missing-name findings) | `_OPENERS` now carries the ordinary ways a spoken sentence starts (interjections, common adverbs, imperative verbs); anything else capitalised at a sentence start is still a name | "Mara", "Dale", "Ious" at a sentence start still bind (`test_unknown_sentence_opener_and_changed_proper_name_are_not_waved_away`, `test_tint_meaning`); plural common nouns such as "Conversations" are NOT waved (dropped from the patch: no rule tells "Conversations" from "Miles" without a lexicon) |
| speaker label `Name: "quote"` (1) | the label's words are possible names, marked `heuristic`, reported as `possible_names_missing`; the same name spoken inside the quote binds | — |
| em dash gluing a name — "Freshing—animal" (8) | en/em dashes separate words | — |
| bare "one" added for "a single" — "in one breath" (15) | `_bare_one_waived`: an added spoken "one" before a noun the source introduced with a/an/single/one is the same count | "Mara needs one copper plate" → "only copper plates" / "two" / "1 → a" still fail |
| bare "one" dropped — "a deep one" (10) | `_pronominal_one`: article + adjective + "one" at the end of its clause is a pronoun | "one" before a noun keeps its obligation |
| "the only thing" as a count — "the only thing that can rescue me" (part of the 41) | the idiom is tagged `idiom`; as a source fact it binds, as the rewrite's own wording it satisfies a source "one thing" but is never an ADDED count | "The one thing I keep" → "The thing I keep" / "two things" still fail; "only thing" ↔ "one thing" equivalent |
| filler negation added — "no time to waste", "no delay" (57 of 172) | only the idioms in `_FILLER_NEGATIONS` are waived (`_filler_negations_only`) | any other added negation is a claim the source never made: "no need to spin", "No brakes on that route" stay refused (`test_names_numbers_negation_and_unprovided_contrast_still_fail`). Dropped from the patch: "any negation not within three tokens of a source anchor is filler" |
| negation kept as a prefix — "don't know" → "specifics unknown" (15) | `_lexical_negation_kept`: a dropped negation survives as non/dis/un/in/im on a source content word | "Teaming … knows not" → "unaware" still refused (not a source word); "can't lose" → "can lose" still refused |
| transcript question without its "?" (21 + 10) | `_interrogative_cue`: a source with no sentence punctuation at all may be punctuated as a question when it carries a question word or an inverted auxiliary anywhere; a punctuated source only when the cue opens a sentence ("Can't you feel it.") | "You keep the copper plate." → "Can you keep…?" still refused (`test_question_without_final_punctuation_still_requires_question_word_order`); a rhetorical question invented on a punctuated statement stays refused. Dropped from the patch: "a single final full stop is a raw transcript" |
| spoken clock times (10) | already live under #1075 | — |

The report carries `question_basis`, `negation_basis` and `possible_names_missing` so a refusal can be
read for which rule decided it.

## The journal (app.py `crystal_record_refusal`)

112 of 191 batch refusals re-journaled a pair already on file because the digest included the
volatile reports and lived on a row dict rebuilt every pass. The digest is now the parent script,
the turn marker, the words and the grader; a process memo remembers what was journaled and is
honoured only while that review still exists in the store (so a fresh store — the tests, or a
review the operator deleted — starts clean). The first editorial record of a retained candidate is
never silenced (`test_crystal_repair_journal`), and with #1088 these records are the machine's notes
rather than the operator's queue.

## Tests

`tests/test_rap_end_words.py` and `tests/test_crystal_contract_false_refusals.py` carry the exact
journaled bars and pairs; the operator's pinned suites (`test_crystal_contract`, `test_crystal_rhyme`,
`test_tint_contract`, `test_tint_rhyme`, `test_tint_meaning`, `test_rap_only`,
`test_crystal_lexical_false_refusals`, `test_crystal_whole_resume`, `test_crystal_repair_journal` and
the rest of the crystal/tint/rejection suites) run green beside them.
