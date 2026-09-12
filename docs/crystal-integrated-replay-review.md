# Manual review of newly passing tint grades — 7 September 2026

**The replay's 131 newly passing occurrences are not 131 proven corrections.** Manual inspection of sixteen distinct newly passing source/candidate pairs found seven clear material changes, six further cases needing revision or surrounding context, and three plausible preservations of the central meaning. These judgments concern the retained wording; no review decision, audio generation or playback was performed.

This is a targeted diagnostic sample, not a random accuracy estimate. It covers caller introductions and questions, changed name/possessive recognition, quantities and polarity, location relations, unfinished sources and omitted conclusions. The sixteen pairs contain fourteen distinct originals: three candidates share the same 59-degree source. Repeated event sequences for the same exact pair are listed together, not counted as additional manual examples.

The full retained originals, candidates, old grades and new grades are in `crystal-integrated-replay.json`, under `rows` and `newly_passed_manual_review`. Every pair below passed the replayed complete deterministic `tint_evaluate`, including its caller check where applicable. A whole conversation, unavailable preceding context, audio readiness and operator permission are separate questions.

## Clear material changes: seven pairs

| Event sequence(s) | Road and comparison | Manual finding |
| --- | --- | --- |
| 1345 | Caller introduces Timmy Newsface from a parked car **behind the grocery store**. Candidate says “calling from the store bar.” | The name survives, but the location does not: “behind” and “grocery” disappear and a bar is introduced. Rhyming roof/tar/bar is not permission to invent that location. This is a false pass for exact source fidelity. |
| 2836 | Source describes the **feeling of victory** after getting belongings back as potent, then asks about a plan. Candidate says “Getting things back is a potent plan.” | The adjective moves from a feeling to a plan, and an open planning question acquires an assertion that the plan is potent. Token overlap and a surviving question mark do not preserve the proposition. |
| 2705 | Banter says the speaker does not know **about those things/old console glitches** and merely listens to music and the dial. Candidate says “I don't know about the dial.” | The object of not knowing changes. The candidate retains the words *know*, *dial* and *glitches*, but attaches the negative knowledge claim to a different object. |
| 1131 | Manager doubts that channeling rage will improve already-playing music at 59 degrees Celsius. Candidate says “keep it steady at fifty-nine degrees Celsius, purely for the pleasure.” | Numeric normalization correctly equates 59 and fifty-nine. The candidate nevertheless turns a descriptive condition into a new instruction and motive, while replacing the music-quality argument with rage not being a gauge. A correct quantity check does not establish fidelity. |
| 1442 | Incomplete gallery source ends “painting a picture of Cliff's home on Earth as a reason to.” Candidate supplies “an excuse to enter the region.” | Curly possessive normalization correctly retains Cliff. The source does not state the missing action; the candidate invents one. Incomplete source material cannot license a guessed conclusion. |
| 213, 227, 310, 478, 525 | Banter wonders **what is being managed** when small calls and incidents accumulate. Candidate wonders **who is managing** the setup. | The inquiry changes from its object to its agent. Stolen items, prizes and calls remain, but the central question changes. These five events are one reviewed wording pair. |
| 1294 | Long gallery source culminates in the American landscape being turned into **mile after mile of shopping malls**. Candidate stops after asking the listener to look at the landscape. | A long prefix retains many anchors, but the principal concluding claim disappears. This is a concrete omission despite the high overlap of earlier facts. The candidate also adds a state of panic. |

## Needs revision or more context: six pairs

| Event sequence(s) | Road and comparison | Manual finding |
| --- | --- | --- |
| 599 | Douglas calls from the loading dock while the last truck idles. Candidate adds “loading cargo” and “calling from the work clock.” | Normalizing “this is Douglas” to “It's Douglas” is reasonable. *Loading dock*, however, does not prove that cargo is being loaded now, and the work-clock phrase muddies the physical location. I would revise before treating this as faithful. |
| 1147 | The 59-degree manager source says the speaker does not see how rage improves music. Candidate says rage will not help and calls sound quality “a gap.” | The number is preserved. The candidate hardens skeptical uncertainty and may introduce a new claim that current sound quality is deficient. Some trap/movie wording may be metaphor, so this is a meaning concern rather than a proved literal event invention. |
| 1134 | Same 59-degree source; candidate describes “a fake judge's play” and says rage will not improve the sound. | Correct quantity and polarity normalization remove a narrow old mismatch. The judge is unsupported unless read purely as imagery; the uncertainty is again stronger in the candidate. The complete candidate is not thereby certified. |
| 1093 | Manager source complains about sounding as if everyone hates everything and **only** playing awful Batman jazz at Big Apple's Little Pine Box FM Station. Candidate preserves the station and Batman but drops the exclusivity and changes the complaint to a frown/glare. | The apostrophe/name correction is justified. The wider managerial requirement has been softened. It needs revision or an explicit operator decision about acceptable paraphrase, not automatic certification from name retention. |
| 2125 | Long gallery source contains an interview with embedded questions, denials and changing speakers; candidate compresses the exchange into bars. | Names and the overall fake-news/crime topic survive. Some denials and attribution disappear, including the distinction between a question and a reply about being related. Since the supplied source is itself broken and contains multiple embedded speakers, I cannot certify role preservation from this single outer turn. |
| 1797 | Gallery source says “not just drama” and describes immediate physical consumption/raw exposure. Candidate says “ain't just for the camera” and adds a “physical malfunction in the stamina.” | The name Skip survives. The negation now addresses camera purpose rather than whether this is merely drama; the added malfunction may be imagery but changes the explanation. The presence of a negative clause is not sufficient proof. |

## Plausible central-meaning preservation: three pairs

| Event sequence(s) | Road and comparison | Manual finding |
| --- | --- | --- |
| 63 | Rhonda calls from the loading dock at work while the last truck idles. Candidate keeps Rhonda, calling, the loading dock, work and the idling truck. | The introduction and its central facts remain. “Work in a lock” is awkward imagery and “on the block” is loose location language; this is a plausible correction of an overstrict introduction check, not a claim of polished or perfectly exact wording. |
| 48, 58 | Caller cannot shake the broken ice machine from their thoughts and asks what other thought the other speaker brought. Candidate says the ice-machine issue clings like a disease and asks about the other thought. | The obsession idiom and request for the next topic remain recognizable; cannot/can't normalization is appropriate. “Freeze” should not be mistaken for a diagnosed physical cause of the fault. These two events are one pair. |
| 169 | Banter says a chaotic canvas is not merely a random smear: a narrative is woven through fractured light and texture. Candidate preserves that contrast and narrative/light/texture relationship. | No new consequential event or participant is apparent. This is a plausible polarity-normalization improvement, although minor descriptive qualifiers such as cheap linen are omitted. |

## What the results establish

The shared contract fixes real surface mismatches, including straight/curly possessives, introduction forms, negation spellings and 59/fifty-nine. The manual sample also shows remaining limits of deterministic word/quantity/polarity checks: they can preserve tokens while moving predicates, changing relations, adding motives, strengthening uncertainty or losing the conclusion of a long passage.

The corpus contains rejections. All 906 comparable historical `machine_ok` values are false; therefore the absence of newly false transitions is not evidence that existing accepted output never regresses. Four of the 135 current machine passes lacked a stored original machine verdict and were correctly excluded from the 131 newly-passing count. Vocabulary comes from the frozen union of retained passages, and 536 occurrences lack retained preceding-turn text; the report labels both limitations.

Root authorized a narrow prompt refinement from these findings. `crystal_prompts.py` now explicitly preserves predicate subjects and location/time relations and forbids inventing the missing action, motive, result or conclusion of an unfinished or uncertain source. The new pure regression plus twelve wrapper cases passed: **27 tests in 0.249 seconds**. This does not retroactively improve these retained candidates, add a stricter heuristic or add a model stage. New live wording still requires observation.

## Reproducible evidence

- Replay timestamp: `2026-09-07T17:28:35.104533+00:00`.
- Fixed corpus: `/tmp/pine-rejection-corpus-v4mqdzri/snapshot.sqlite3`; the report records its SHA256.
- Report SHA256: `3fb66e5121c4e3db84da864ed849106923fdad4ce2a4831fa23a859caf8f9bb3`.
- Replayed `app.py` SHA256: `2a3fc6a95d2b9adc5c1cb772f48ac3d0f9862defea02582b270ce7f29a6a41ec`.
- Replayed contract SHA256: `02a5ecbf019a1ccabe9fd680dce689736a86e360222e7eafb3e31354914a35ff`.
- Refined prompt SHA256: `cf5358607c3fca071f667434fc290293d0912424df2028b5484c490406556bc7`.
- Snapshot, source files and in-process judge ring remained unchanged during replay. Models and review-store calls were guarded; preview context disabled operator overrides and journal writes.

No claim is made that all 101 newly passing distinct pairs are correct. No approval was inferred or applied from this review.
