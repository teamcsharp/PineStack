# Crystal prompt and repair audit — 7 September 2026

The original rewrite path had inconsistent instructions between whole-round, numbered repair, single-turn and caller-fidelity attempts. Retained wire traces show the inconsistency reached the model. Some failures also changed facts; improving the prompt does not justify accepting those candidates or weakening the grade.

This audit read production source and retained SQLite evidence without making model requests, decisions, playback changes or database writes. New pure builders are in `crystal_prompts.py`; root owns their `app.py` integration and subsequent model comparisons. The fourteen tests in `tests/test_crystal_prompts.py` passed with isolated data/cache. They verify construction and budgeting, not a measured model success rate.

## Confirmed defects in the original path

| Location by function | Evidence and effect | Required behavior |
| --- | --- | --- |
| `_crystal_round_first_pass` | Original allowance was source length plus 400 characters, while a strong single-turn rewrite was allowed about 2–3.4 times its source length. Expanding a long conversation into short rhyming bars therefore had much less room in the whole pass. The whole pass was skipped when that small estimate exceeded the operator cap. | Plan ordered output batches with estimated expansion room under the actual cap. Keep oversized originals for a bounded individual attempt. An estimate is not proof that shorter valid wording is impossible. |
| `_crystal_round_repass` | Reused `armed` requested the same speaker-marker format; appended repair instructions requested original numbers and no speaker labels. Retained wire sequence 657 contains both rules. | Exactly one output format per request: markers for a full round, original numeric IDs for a subset. Preserve IDs and source order. |
| Whole-round prompt / `crystal_turn` / caller retry | Whole prompt said to keep every word; single-turn and caller prompts asked for at least half the concrete words; batch repair asked for a fifth. `call_tint_report` used its own 35% anchor floor. | Extract one shared source contract, pass the same configured obligations to prompt and grader, and state facts before style. Do not introduce arbitrary competing percentages in prompts. |
| `crystal_turn` meta and caller-fidelity retries | Shorter retries dropped the original slash-bar/end-rhyme requirements, full style world and operator refinement. Meta retry asked merely for a rewrite; caller retry emphasized one bar/internal rhyme and then mandatory lexical anchors. | Reuse the same builder for first attempt and every repair. Preserve source, full supplied style context, rhyme shape and operator instruction. |
| Single and batch repair prompts | Repairs usually contained originals and generic fault summaries, but omitted the actual candidate being repaired. | Include the exact failed candidate and its full compact evaluation, including missing names, quantities, anchors and question/negation results. Feedback is diagnostic evidence, not a new source. |
| `ask_model` postprocessing | The generic path flattened whitespace and sliced to a character limit before later sentence/fragment handling. That can destroy marker/numbered line structure or cut a final bar even when the model completed normally. | Preserve structured tint output until its own parser; reject incomplete shape explicitly. Do not silently manufacture a shorter accepted rewrite. Root owns this integration. |
| `crystal_turn` return / outer `crystal_tint` retry | Several failed attempts return the unchanged source. The outer loop can then grade that source and replace specific failed-candidate feedback with “unchanged” or “no rhyme.” Batch progress likewise needs to retain the latest rejected attempt separately from selected text. | Keep accepted output separate from latest attempted wording and evaluation. A later repair must see the actual attempt, not a substituted original. Preserve the original as recovery evidence. |

The original single-turn prose also used “ONE bar,” “two or more short bars,” and “do not add a second” in the same task. The last clause meant another turn, but its wording was ambiguous. The builder now explicitly distinguishes one physical output line, multiple slash-separated bars, and no added dialogue turn.

## Retained wire evidence

Source: read-only `/app/data/rejection_lab.sqlite3`, trace `b2931164113f40e19d479fb0c1268b41`. The following fixed sequence numbers identify evidence even while later production traces continue to arrive. No style lyrics are reproduced here.

| Trace sequence | Observed evidence |
| --- | --- |
| 599 | Whole-round wire request: 7,438 user-prompt characters and 1,248 system-prompt characters. Model `gemma4:31b`; `num_predict=2400`, `num_ctx=65536`. |
| 657 | Numbered repair: 7,769 user characters plus the same 1,248-character system guidance. Both “same marker format” and “SAME NUMBER” are present. It supplies original lines and generic faults/missing anchors, rather than actual failed candidate text. |
| 906 → 911 | Caller fidelity retry requests one bar/internal rhyme but omits explicit slash-separated end-rhyme shape. The result is almost ordinary source prose. It completed with `done_reason=stop`, 25 generated tokens. |
| 918 → 923 | Next retry mandates 13 anchor words, without the previous candidate and full fault report. The result repeats property/trying and introduces an unsupported claim about where someone was trying to keep the property. It completed normally in 35 tokens. |

The last two examples do not show token exhaustion. The wire had a generous token cap, and both responses ended normally. Their wording supports fixing the repair contract rather than simply increasing tokens.

`ask_model` adds prior operator wording preferences as system evidence. In this trace the system text explicitly labels those examples as prior decisions, not the current source, and says they do not waive checks. Some prior accepted examples are unchanged or unrhymed. The prompt must preserve that feedback while making the current transformation requirement explicit. `call_ollama` passes the provided messages and decoding options; the audited path did not reveal an additional hidden generic “no poetry” system rule.

## Actual fidelity failures must remain failures

These retained records illustrate why a prompt repair must preserve meaning rather than merely reduce rejection counts:

- Record `cb80137d1b14423b9f891ee8845a5bc1`: the source addresses Salem and says things are about to shift. The candidate begins “Salem here” and says things shift. This can change the addressee into the speaker's identity and a prospective event into a present event.
- Record `0771833bbfca4a0b94015ce00751c3bd`: stolen belongings from a storage unit become a raid “for a shopping spree.” That motive is not supplied by the original.
- Record `a35888eeac8442429662cacfab2712e9`: the source's conversational question/tag disappears while new wing/string imagery dominates. Question-role preservation and decorative imagery need separate inspection.
- Record `1ba18888f587429c8bd39d5574b1d361`: the candidate preserves the topic about plans and angles, but has no slash-separated end-rhyme structure. A meaning pass alone does not demonstrate the requested style pass.

These are diagnostic examples, not a complete rejection-rate sample. The audit does not claim every lexical mismatch is meaningful: normalized names, possessives, quantities, negation and source anchors are being centralized separately in `crystal_contract.py`.

## Builder contract and integration checks

`turn_prompt(source, world, chunks, force, kind, answering='', contract=None, operator_instruction='', candidate='', evaluation=None, lesson='')` returns one consistent first-attempt/repair prompt. `round_prompt` accepts original `(marker, source)` turns, optional zero-based `selected_indices`, and indexed candidates, evaluations and contracts. No new model-output JSON schema is introduced; JSON labels input evidence only.

`budget_plan(turns, reply_cap, force=1.0, selected_indices=None)` returns ordered capped batches and explicit oversized indices. Full-strength estimates use 2.4 times source characters plus minimum short-bar room and formatting overhead. Duplicate text and speaker positions remain distinct. `fits` means every selected position fits the batch plan; `single_batch` states whether one request is enough. Neither is a semantic judgment.

Root integration should verify:

1. Every repair branch uses the same builder, including meta, caller fidelity and anchor repair; it passes the actual latest candidate and full evaluation.
2. Grader-specific stopwords/vocabulary are reflected in the precomputed contract supplied to builders. Default extraction is available, but should not silently differ from a configured production grader.
3. The marker parser receives physical lines; numbered subset repair keeps original IDs even across batches and never changes caller/host ownership.
4. Character caps limit requests without slicing original sources or silently accepting partial outputs. Oversized individual lines remain visible for bounded repair.
5. Raw machine reports remain raw. Operator approval, recovery and style proof are not synthesized by prompt construction.

Focused verification completed: **14 tests passed**, covering exact source retention; full world/style retention; identical rhyme requirements across repairs; actual candidate and detailed fault feedback; operator instruction scope; marker/numbered separation; original IDs/order; cap-safe batching; duplicate positions; oversized retention; and invalid inputs. No live model benchmark or deployment is claimed by this artifact.

After root's wrapper integration, **33 focused tests passed in 0.665 seconds** with fresh data/cache: the fourteen pure tests, twelve `test_crystal_prompt_integration.py` cases and seven existing audit/instruction cases. The integration tests execute actual wrapper control flow with fake model responses. They cover meta/unchanged/caller/evaluator repair, safe-source return with separate latest failure evidence, outer retry propagation, ordered first-pass batches, completed-plus-pending progress on admission deferral, resume without repeating accepted positions, and an eleven-turn caller with one cut remaining incomplete. Spoken slash-to-comma cleanup is intentionally retained; the fixtures distinguish the requested bar format from the normalized text received by the grader. These deterministic checks do not measure live model quality.
