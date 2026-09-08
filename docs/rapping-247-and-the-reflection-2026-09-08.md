# Rapping 24/7: the rejections, the reflection, and the operator's own hand (2026-09-08, evening)

The operator, seeing *14 cut lines wait for your decision · Rejected lines (586)*:

> do an agentic investigation into these rejections and refine / sharpen the system to reduce their
> occurrence in the future. I need this machine flowing in a smooth stream. Rejections are a waste of
> effort and I don't like seeing the GPU wasting cycles on dead results. The orchestrator needs to
> coordinate and competently alleviate all errors and streamline the system ... The orchestrator
> should have its own neural process that analyzes and makes system accommodations to internalize
> what is learned. I need the system learning from the dialogue being accepted ... To me, once the
> words are rhyming due to tinting, they transcend the ability to be deleted and be treated as
> general dialogue. I want to keep and reuse the elements that are converted into song lyrics. These
> should fill all the dead air and keep the station rapping 24/7.

and, from the review panel's *Try wording* tab:

> I want to have a button to accept what I type and to send it through auto approved. I want to be
> able to correct the lines and assist the algorithm with how to behave. For some reason the line I
> typed didn't pass verification when I meant to tell the verifier what to accept and improve it.

Numbers are **[V]** (measured) unless marked **[I]**.

## 0. What the 584 pending cuts were (read at 15:17 CST)

| gate × kind | rows |
|---|---|
| tint · banter / gallery / caller / news / manager | 137 / 109 / 81 / 40 / 17 |
| segment_brief · news (and recap 6, gallery 4, manager 4, ad 1) | 122 |
| call_contract · caller | 36 |
| recording_tint (the recording room's hold, no candidate, no evidence) | 27 |

Of the 411 tint rows: a rhyme fault in 234, a meaning fault in 155, *not transformed* in 95 (31 of
them with **no other fault** - every one of those with a proved rhyme and the meaning intact), a
copied phrase in 3 **[V]**. The 95 *not transformed* rows: 92 hand the source back nearly unchanged
(lexical distance under 0.05; median 0.0), sources of 35 words - the model gave up and echoed
**[V]**. Accepted bars against refused ones: 94% of accepted candidates have two or more bars of
about nine words with a proved landing on 79%; refused ones have two bars only 58% of the time, run
twelve words a bar, and land nothing on 68% (77% among the rhyme refusals). Refused-for-meaning
candidates transform *too* far (lexical distance 0.5 against 0.43 accepted) and keep 60% of the
anchors against 72% **[V]**. So the writer's two systematic failures are *one long bar instead of two
short ones* and *echoing a long source* - the shape rule in the frame, the repair hint and the
reflection all aim at exactly those.

Changed from the census: the recording room's evidence-less holds are notes, not decisions
(`recording_tint` joins `INFORMATIONAL_GATES`, triage version 3: the 27 rows leave the queue), and
the repair hint names an **echo** as an echo, with the shape to write instead.

## 1. The operator's own edit, refused - and the rule that refused it

The typed wording (*"Hold on to line seven five six three eight; Hello now, what you see there this
late."*) was reproduced against the grader: it rhymes (*eight / late*, confirmed by the pronunciation
dictionary), keeps every number and word, and was refused for exactly one fault - *rhetoric was not
materially transformed* - because the candidate contains the source verbatim plus a rhyming tail
(lexical distance 0.143 against a 0.18 threshold, and the "unchanged proposition" test) **[V]**.

Changed: under the **meaning** grade a proved **end** rhyme that the source did not have *is* the
transformation - the line rhymes now, whatever share of the source's words it keeps
(`rhyme_added` in the report). The strict grade still demands the full lexical change; an internal
pair inside an appended clause does not count; an echo that does not rhyme is still refused. Two
pinned tests that expected the old reading were re-pinned; the operator's own wording is the new
test.

## 2. Approve as written

Before: *Preview trial* graded the typed text and stored a receipt; *Apply* was disabled unless the
machine passed it, the server refused it a second time, and the store a third - so a wording the
operator meant as the verdict was recorded and dropped **[V]**.

Now the *Try wording* tab has **Approve as written** (and each failed trial card has one):

- the machine grades the wording once, **for the record** (`machine_ok`, `machine_faults` on the
  receipt), never as a gate;
- the line is allowed with the operator's wording as an instance grant, recovery records and airs
  **that** wording (`line_review_recover` receives the instance whose candidate is the typed text);
- the source/wording pair is approved outright (`_approved`), so the gate never refuses it again;
- the *Instruction for this trial* text (or "Approved as written by the operator") is the decision's
  note, and the pair joins the writer's **operator wording preferences** - the system message every
  crystal call carries - as the strongest example there is (`by_operator`).

Endpoint: `POST /api/orchestrator/rejections/{id}/accept` with `{candidate, instruction, event_seq,
expected_revision, request_id}`; `lab_operations` kind `accept`; pinned by
`tests/test_accept_as_written_2026_09_08.py`.

## 3. The orchestrator's reflection

What the station already learned (read from the code): the learner's catalogue hints and the
operator's allow/keep preferences change prompt text; the per-line fault memo and the repair hint
help a retry. Nothing showed the writer an accepted bar from another round, nothing adapted from the
hour as a whole, the lab's 180k trial traces taught nothing, and the judgment book's lessons never
reached a rewrite **[V]**.

Now, every ten minutes, `reflection_clock` finds the road with the most refusals in the last hour
(at least 8 graded bars and 2 refusals; each road at most hourly), gathers the hour - the accepted
and refused bars with the grader's faults (the judge ring and the review store) and the measured
counts (the learner's outcome table) - and asks the road's own deep model to read them like a coach:
three concrete writing rules that would have turned the refusals into passes without losing what the
accepted bars do, and which accepted bars best show the shape. The answer is a versioned reflection
per road (`data/orchestrator_reflections.json`) and rides every rewrite prompt of that road inside
`crystal_operator_refinement` as **THE ORCHESTRATOR'S REFLECTION** with two **BARS OF THIS ROAD THAT
PASSED** - the station's own successes shown back to it. Every version records the road's acceptance
rate at birth; the next reflection measures the hour under it and **retires** a version that made
the road worse by ten points or more, falling back to the one before. Nothing relaxes the grader.

`GET /api/orchestrator/reflection[?kind=]` shows the rules, their measured effect and the history;
`POST /api/orchestrator/reflection/run {kind, force}` reflects now. The action log gets *🧠 the
orchestrator's reflection on caller (v1): …*.

## 4. Rhymed bars fill the air

Before: a **gold bar** (a rhymed line that aired, with its exact take) could fire only at a sting
moment *inside a round already playing* - precisely when there is no dead air; a cut round's accepted
bars and their takes were thrown away with it (a 21-line call: 20 accepted bars gone) **[V]**.

Now:

- `sfx_fill_gap` reaches for a **gold bar first** (`gold_fill_gap`): the take plays through
  `dj_speak(clip=…)` with no render and no model, on the box and the page; the liner and the sample
  are what is left while the gold rests (five minutes on the dead-air road, twenty at a sting);
- every accepted bar of a round that is let go - a tint strike, a replacement, a removal at the
  retirement desk - is **harvested into gold with its take** (`gold_harvest_entry`) before the audio
  is dropped; the gold store protects those files from the media sweep;
- the retirement desk and the 96-hour keep (earlier today) already keep whole rhymed rounds; this is
  the bar-level companion.

## 5. Pinned

`tests/test_rejections_learning_2026_09_08.py` (the operator's edit passes; an echo without rhyme
does not; the strict grade unchanged), `tests/test_accept_as_written_2026_09_08.py`,
`tests/test_rapping_247_2026_09_08.py` (harvest, the gold-first gap, the reflection's gather / parse /
keep / ride / retire / due), and the review, workbench, replacement, gold and gap suites.
