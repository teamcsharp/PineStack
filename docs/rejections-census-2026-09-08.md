# The rejections census (2026-09-08)

The panel said *763 cut lines wait for your decision* and the rejected-lines drawer *944*; the review
store held **974 pending rows** when it was read at 11:20 CST (the operator's page counts differ only
by the age window it shows). Every row was classified by its gate, its stated reasons and the kind of
round it came from. This document is the reading, the four changes made from it, and what the queue
should look like after them. Numbers are **[V]** (read from the store or the code) unless marked
**[I]** (inferred).

## 1. What the 974 rows were

| gate | rows | what it means |
|---|---|---|
| `tint` | 458 | the crystal grader refused the bar and the line was cut before the studio |
| `draft_fragment` | 302 | a model reply with *no finished sentence* was binned whole |
| `segment_brief` | 128 | the round never did what its brief asked (news 113, recap 6, gallery 4, manager 4) |
| `call_contract` | 34 | a caller round broke the phone contract |
| `line_quality` | 20 | near-duplicate of a line already in stock |
| `recording_tint` | 15 | the recording room's own pre-render tint refused the bar |
| `repetition` / `language` / `ad_length` | 17 | the machine's own housekeeping |

By kind: model_draft 302, caller 186, news 152, banter 133, gallery 121. 643 rows predate the 07:38
restart; 331 were new that morning **[V]**.

**The tint refusals (458).** Reasons, with overlap: *no rhyme evidence* 291, *semantic preservation
failed* 184, *rap rhyme evidence did not pass* 147, *semantic checks did not pass* 134, *rhetoric not
materially transformed* 104 **[V]**. By kind: caller 152, banter 133, gallery 117, news 39, manager 17.
The re-ask that follows a refusal carried the fault names and the evaluation JSON but not *what to do*:
the writer was told "no rhyme evidence" and handed the same two landing words back. Half the per-line
re-asks passed nothing **[V, the cupboard scan]**. And when a later ask for the same line DID pass, the
earlier cut stayed in the operator's queue as if the line were still lost **[V]**.

**The fragments (302).** All of them "no finished sentence", nearly all of them whole *transcript
repairs*: the desk asks the model to punctuate and repair a spoken transcript, the transcript comes
back without a full stop because it is speech, and the fragment gate - written for spoken lines
(#264) - binned the whole 5,000-character reply and recorded a cut. No operator can *allow* a fragment
onto the air; these rows were never decisions **[V]**.

**The news (113 of the 128 briefs).** *Never gets to the story the wire carried.* The news round is
handed the wire as its `angle`, then `dj_banter` draws a speakbox seed for it anyway - best of two
700-character swaths - and appends "work these lines in word for word" to the angle; on the legacy road
a further verbatim swath of up to 2,600 characters is stapled to the head or tail of the script. The
model wrote about the film transcript it was told to quote and the bulletin failed its audit **[V]**.

## 2. What changed

| change | where | what it does |
|---|---|---|
| the machine's own gates are **notes**, not requests | `line_review.INFORMATIONAL_GATES` (`draft_fragment`, `draft_trimming`, `repetition`, `language`, `line_quality`, `ad_length`, `tint_output`), `TRIAGE_VERSION = 2` | 339 rows leave the pending queue on the first open after deploy; new rows of those gates are recorded for the learner but never wait for a decision |
| a transcript repair with no full stop **is the repair** | `ask_model`, `_unpunctuated_by_nature` | a `transcript_repair` reply of 400+ characters is kept as it came; a JSON-shaped reply is kept; a short reply that stops mid-word ("Mara left the") is still held |
| a round whose facts arrive in its angle is **not fed a second subject** | `dj_banter(own_material=True)` from the news, recap, gallery (three roads), manager memo, manager call and fan-mail roads | no speakbox seed, no "work this in" aside, no verbatim swath at head or tail, no #844 enforcement; the speakbox's colour still rides every line through `speakbox_flavor` |
| the repair ask says **what to do** | `tint_repair_hint`, `rhyme_options_for`, `report["repair_hint"]` | "your bars land on 'plate' and 'man', which do not rhyme - land the last bar on gate, weight, freight or the first on pan, ran, clan"; "say the name Mara; keep the number 12; drop the number you added: 3; put back these source words: copper, midnight"; the words offered are the crystal's own vocabulary, chosen by the same reading the grader uses, so a word the writer takes is a word the grader accepts. Rides the REPAIR EVIDENCE of the round prompt and the per-line lesson |
| a bar that later passes **retires its cuts** | `line_review_supersede`, `LineReviewStore.supersede` | at both accept sites (whole-round resume, per-line accept) the pending cuts of that exact source line become notes marked *superseded* |

Nothing about the grader's rules changed: what counts as a rhyme, a kept fact or a transformed line is
the reconciliation of `docs/evaluator-reconciliation-2026-09-08.md`, untouched.

## 3. What the queue should look like

Before: 974 pending, 302 of them fragments nobody could allow. After the first open (the 14:33 CST
restart): **586** pending, 7,847 noted **[V]** - every one of them a line that actually left the work
(the first page: tint 29, recording tint 12, briefs 7, call contract 2 of 50) - and from then on:

- no new fragment, trim, repetition, language or ad-length rows in the queue;
- news, recap, gallery and manager rounds written about their own material, so the brief audit's
  "never gets to the story" should fall to the rounds where the model truly wandered;
- tint refusals still recorded, but each re-ask carrying the landing words that would pass and the
  facts to put back, and each line that eventually passes clearing its own earlier cuts.

## 4. How to read it

- `GET /api/orchestrator/rejections` - `pending`, `noted`, `attention`; the noted count should jump
  by ~339 and pending fall by the same on the first open.
- A superseded row shows `effect.status = "superseded"` with the note *a later rewrite of this line was
  accepted*.
- A refused tint's evaluation now carries `repair_hint`; the next ask's prompt shows it under REPAIR
  EVIDENCE and, per line, in EARLIER REVIEW FEEDBACK.
- `tests/test_rejections_census_2026_09_08.py` and the additions to `tests/test_line_review_triage_1088.py`
  pin every rule above.
