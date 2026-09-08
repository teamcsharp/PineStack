# The evening's rejections, and what the orchestrator now does about them

Read off the review store at 17:45 CST on 2026-09-08 (197 pending cuts, 600 recent
notes), after the day's three deploys.

## What the queue was

| | |
|---|---|
| pending cuts | 197: tint 188, segment_brief 5, call_contract 4 |
| by road | banter 106, gallery 36, caller 32, news 21 |
| graded before 14:33 (the first road change of the day) | 180 of 188 |
| graded since 16:27 (the last) | 0 |
| meaning cuts | 108 — the negation check on 62, the name check on 46, the question check on 22, anchors below the floor on 26 (mostly the same rows) |
| rhyme cuts | 80 — the last candidate of every one is a couplet on a semicolon that lands no rhyme by the rap reading |
| raw transcript sources (40+ words, under two sentence ends per hundred) | 10, each holding 25–70 anchors nobody could keep |

**The queue is the backlog.** Grader v9 was already current before the afternoon, so the
triage of #1088/v4 (`version < 9`) left these rows in the queue although the roads under them
changed three times since. Live, since 16:27, the machine has re-asked 404 refused rewrites
and cut two lines; 309 of the 404 are the Gazette's paragraphs (fast model, its own lane).

**What the meaning cuts actually were.** Not lost meaning — the contract's three form checks:

- *negation dropped* where the negation was rhetorical: "not just structural", the opener
  "No, it should have been called…", the tag "isn't it?", "can't shake the feeling",
  "the blues aren't tranquil; they are the crushing weight…" — the rewrite kept the claim
  and folded the frame.
- *missing name* where the "name" was the station's own name written in by the prompt
  ("…right here at Chicken Tendo Little Pine Box FM Station": 54 of 71 findings) or a
  description that happened to open the sentence ("Taut wire is too mechanical",
  "Shimmering light", "Suspended moment?").
- *question dropped* where the question was a beat inside the turn ("You think so? I mean,
  look at the colors…") and the turn ended on a statement.

## What changed

1. **Rhetorical negations fold under the meaning grade** (`crystal_contract._rhetorical_negations_only`,
   reported as `negation_rhetorical`, basis *rhetorical negation dropped*). The frames: *not
   just/only/merely/simply/even*, the discourse opener *No,*, a tag question, *can't shake /
   help / even…*, *not X but Y*, *not X; it is Y*. A negation on a fact — "he did not win",
   "your son is not safe" — sits in no frame and stays refused. The strict grade refuses all of them.
2. **Inner questions fold under the meaning grade** (`_question_is_inner`, basis *inner question
   folded*): the source has two or more sentences and does not end on its question. A turn that
   ends on a question — the hand-off — still binds.
3. **The station's name is boilerplate** (`compare_contract(..., boilerplate=)` fed by
   `_tint_boilerplate()` from the `station_name` dial): reported as a possible name, never bound.
4. **A descriptive opener is reported, not bound**: a capitalised opener that WordNet lists as an
   adjective or adverb (vendor/wordnet/index.adj, index.adv) or an -ed/-ing participle, followed by a
   lowercase word that is not a finite verb. "Dale woulda", "Ious.", "Reading is fun" and
   "Dreamscape" still bind.
5. **Raw transcript swaths are bounded** (`_verbatim_turn_text`, 240 characters at a word
   boundary, a full stop added) at the three verbatim insertion points of the writing room — the
   opening passage, the closing passage and the #844 put-back. Punctuated passages are untouched.
6. **The queue is re-read against today's grader** (`line_review_regrade_pending`, ninety seconds
   after boot and on `POST /api/orchestrator/rejections/regrade`): a pending tint cut whose stored
   wording passes now leaves the queue as a note *stale_grader* that says so; a phone-road formula
   line the crystal reads plain since this afternoon leaves as *read_plain*; anything today's
   grader still refuses stays for the operator.

All four contract changes only accept more; `crystal_contract.VERSION` stays 3 and the grader
stays v9, so no stored proof or ready round is invalidated. Every rule pinned in
`tests/test_crystal_contract.py` and `tests/test_crystal_contract_false_refusals.py` still holds;
the new ones are pinned in `tests/test_rejections_adjust_2026_09_08.py`.

## What it does not change

- The 80 rhyme cuts are the model's: a couplet that lands no rhyme after three asks is still
  cut. The reflection (§11 of RapAssembly) and the repair hint are the levers there.
- The Gazette's 309 refusals an hour are its own rule (#1075/#1077): the press holds an edition
  up to 45 minutes and cuts what never passes. It runs on the fast model's lane.
- The call contract (4) and the segment brief (5) are untouched.
