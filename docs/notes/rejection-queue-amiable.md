---
name: rejection-queue-amiable
description: "2026-09-09 — the queue's biggest fixable block was the gallery road's INVENTED PAINTING TITLES read as names to retain; the rhyme block is genuine (near reading rescues zero); stored verdicts go stale"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T10:41:36.107Z
---

The operator's panel offered "623 cut lines wait for your decision". Three
findings, only one of which was a grader threshold.

**1. The 623 was not real.** The desktop card's counter (`renderer.js`, the
rejection notice controller) adds every rejection EVENT seen since the window
opened and is only reset by `dismiss()`. The badge beside it showed the actual
queue. A line the station later repaired, superseded or re-graded leaves the
queue and was still counted. The card now shows the queue.

**2. The queue is NOT a backlog** — unlike the 2026-09-08 case
([repertoire-dead-air-lcd](repertoire-dead-air-lcd.md): "THE QUEUE IS THE BACKLOG, check last_at first").
51 of 174 pending rows were last seen inside the hour, 16 inside ten minutes.
Always check `last_at` first; the answer differs by night.

Attributed over 107 pending tint rows, the SINGLE failing leg was: **rhyme 35,
entities 11, negation 11, question 4, anchor floor 3, round-level check 18.**

**3. THE RHYME BLOCK IS GENUINE — do not touch that gate.** Replaying
`crystal_rhyme.rhymes_with` (the near reading) over every row that named a
pair rescues **zero** of 30. Two landed both bars on the same word, two wrote
one bar instead of two. `ponder`/`air`, `called`/`there`, `up`/`gone`,
`seconds`/`now`. The fix there is a better first ask, never a lower bar.

**4. The entity block was one bug: the gallery road's INVENTED TITLES.** 33 of
35 "lost names" were `Furnace`, `Longing`, `Reality`, `Velocity`,
`Bewilderment`, `Inferno`, `Apex`, `Gaze`… — ordinary dictionary words inside
titles the hosts were coining ("it should have been called The Furnace of
Creation"). 18 of 23 entity refusals had a title-proposing source.

The cause was an **asymmetry, not a threshold**: in `crystal_contract`, a
capitalised word at a SENTENCE OPENER is checked against the crystal's
vocabulary and `_descriptive_opener`; the same word one clause later got
reason `interior capital` with **no check at all**. `_coined_title_word` now
joins `speaker label` and `descriptive opener` as reported-but-not-bound, and
is bound where the opener escape is bound — a word WordNet does not know stays
a name (`Dreamscape`, `Shockwave`, `Jarell's`). Also added: a **vocative** said
once may go, a bar that **asks in form** without the mark has asked (auxiliary
inversion required — "How the ground can fall" is a statement), and a source
that **denies by naming an absence** ("a lack of faith in any defense") has
denied.

`crystal_contract.VERSION` deliberately **not** bumped: the number marks a
change in what the contract REFUSES, and these only accept more. That file's
own `Version` test enforces the convention. Two tests pinning it as a literal
now read `crystal_contract.VERSION`.

**5. STORED VERDICTS GO STALE, so the queue lied about why.**
`line_review_regrade_pending` computed today's report, released the passers and
**discarded the report for the rest**. Of 13 rows whose stored reason named a
lost title word, 9 were by then held by the anchor floor (0.04-0.18) instead.
`LineReviewStore.refresh_verdict` now rewrites reasons + evaluation on a kept
row (no write when nothing moved). Live: seen 93, kept 88, refreshed 88; title
words bound fell 33 → 4, entity leg 23 → 11.

**A regression of mine, found by this sweep:** the 2026-09-08 deep scan added
"make/let + one + think/wonder/…" as a pronominal frame ABOVE an older frame
that checked what FOLLOWED the verb, shadowing it — so "Make one wonder
machine" stopped counting its machine. The count now survives only when the
following word is a noun (`_noun_lemmas`, WordNet index.noun).

Live result: the re-grade released 9 of 107 outright; the ongoing saving is
larger because the gallery shelf is the biggest on the station. Remaining known
gap: a title coined in an EARLIER turn and merely referred to ("The Gritty
Confrontation captures the clash well") has no proposal phrase, so it stays
bound. Related: [rejection-deep-scan-and-stack](rejection-deep-scan-and-stack.md), [gold-freeze-1157](gold-freeze-1157.md),
[tint-yields-to-air](tint-yields-to-air.md).
