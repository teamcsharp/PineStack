# Full rejection corpus audit

The 2026-09-07 16:51:37 UTC consistent SQLite snapshot contains **1,311 review records and 3,065 occurrence events**. Every row, event and decision was parsed; [the JSON report](rejection-corpus-audit.json) includes all aggregate categories, repeated-source groups, exact IDs and 54 stratified examples. Complete evidence is retained in the private SQLite snapshot named in that report. No votes, model calls, recordings, playback changes or service actions were requested by this audit.

The pending count is **1,305**, with five allowed and one kept record. The earlier screenshot's 943 pending items describes an earlier queue, not the all-time number of lost spoken lines. There are 2,690 `rewrite_rejected` occurrences, 295 marked `cut`, 71 `trimmed` and nine held before recording. The 295 cut events cover 267 IDs and include 165 discarded model replies (`draft_fragment`); **105 events explicitly identify a spoken-turn `turn_cut`**.

The main finding is that missing or mishandled output is inflating the apparent quality failures. Of 2,702 tint events, **1,782 have no candidate text**. Those empty entries account for 1,683 semantic and 1,683 rhyme flags. The 920 nonempty-candidate events contain 611 semantic, 302 basic-rhyme and 206 transformation failures; categories overlap. These are refusal records, not a denominator of all model attempts, so none of these counts is a model rejection rate.

| Gate | Occurrence events | Main implication |
| --- | ---: | --- |
| tint | 2,702 | Separate missing output, old regrading and actual new rewrites. |
| draft_fragment | 165 | 128 contain slash-separated bars; prose punctuation rules discard requested output format. |
| draft_trimming | 71 | Full draft exceeds a character limit or loses its unfinished tail. Preserve repair evidence and distinguish token exhaustion. |
| call_contract | 35 | Actual caller protocol, source and speaker-order obligations remain important. |
| tint_structure | 24 | Missing numbering or changed turn order needs structural repair. |
| radio_draft | 18 | Richness checks need their measured shortcomings carried into the next attempt. |
| segment_brief | 14 | Eight news and six ad failures; source injection and narrow sale-word matching both contribute. |
| blend | 12 | Source preservation, turn count or severe shortening failed. |
| recording_tint | 12 | Required proof is absent; this is not permission to synthesize ungraded wording. |
| repetition / line_quality / remaining gates | 12 | Six repetitions, three line-quality events, and one each of track fidelity, track text and ad length. |

## Causal findings and bounded repairs

**Repeated regrading is creating new rejection events without a new candidate.** Four source families account for 1,162 identical empty-candidate entries: `bb7eb533c5824c4fa04251c670dfc26b` and `03168fcd89a243659b7c1393d08cf038` have 291 each; `9b2c716c4060448697eecbde9900f1cc` and `dc9595c43cde40a6a9cbb5e22f80b7ea` have 290 each. This is historical evidence; it does not establish that the same burst is still occurring after later admission changes.

`_crystal_round_repass` reads `text or rejected_candidate` for grading but captured only `text`. It also journals the refusal before requesting writer admission. Repeated `WritingDeferred` visits therefore recapture the same old evaluation, and a retained candidate can be falsely represented as empty technical output. A failed new batched reply was recorded but not retained for the next pass, which then regraded older words. The four isolated tests in `test_crystal_repair_journal.py` reproduce those three faults and verify that completed accepted work is not rewritten. The intended fix retains the latest actual candidate and a persisted source/candidate/evaluation digest and event pointer, without dropping deferred work or inventing a pass.

**The generic prose-output handler conflicts with the tint output format.** `ask_model` required a finished sentence before returning any output. Example `683dc4f1aaa44091ac841aabb31e4124`, event 16, contains numbered 1/5/8/10 responses with slash-separated rhyming bars, but was discarded for “no finished sentence.” Event 3059 (`ef2f3c618a9c4711bc9e252a90cda17d`) is another complete slash-bar response discarded before tint evaluation. This does not prove those responses preserve meaning. It proves that they should reach the actual tint grader. Tint-specific handling should preserve complete raw bars and numbered output, identify real token truncation, and retain over-limit evidence for bounded repair rather than silently applying prose trimming.

**Transcript-repair instructions have entered source material.** Five retained events contain literal instructions from `speakbox_harvest` in their source. Event 3050 (`de1442cdc06f4f36ac409cb4c88c02f0`) carries “Give back the repaired text and nothing else” inside `context.verbatim`, already assigned to speaker A. `speakbox_harvest` asks a model to repair a transcript, strips only a short colon heading, splits the reply into sentences and caches all of them. An echoed instruction is then selected as a source gem; downstream blending is explicitly required to preserve it.

A separate read-only cache inspection found 44,486 main Speakbox gems and 16,160 DOOM gems. The conservative `crystal_source.py` helper recognizes 435 main-cache prefixes (372 entirely prompt echo) and four DOOM gems, preserving the remaining actual words and returning removed offsets/text for provenance. Among 265 broadly phrase-flagged rows, 203 are safely removable with exact anchored clauses; 62 fused or embedded cases remain untouched. Five tests cover actual reordered and split echoes, old caches, punctuation/case variation, quoted imperatives, ordinary longer statements and idempotence. Root must apply this at harvest output and cache reads before injection. Original source/cache files are not rewritten by this audit.

**Several non-tint failures reflect genuine damaged conversations, not an overly strict universal threshold.** The 35 caller-contract events cover 28 IDs. In event 3062 (`a78daddf3e9341bcb85657d85918856a`), a 21-turn original call has become a 16-turn tint; the introduction and resolution are missing and subsequent indexed fidelity checks cascade. Preserving and repairing the call's structural turns together avoids spending work on an unusable majority-cut call. Merely permitting those downstream faults would not restore the conversation. Repeated-premise refusals also have actual near-template material behind them.

The eight news-brief failures include unrelated source passages overwhelming the requested story (events 3032 and 3051). Source injection should preserve the news obligation and fit its allocated material budget. For ads, event 2506 (`e90785aee496456897d3acf5489e5ce9`) names an XTTS voice-cloning service, specifies payment and asks listeners to sign up, yet the simple `SEGMENT_BRIEF.ad` vocabulary misses those sale expressions. The safe improvement is checking the original product identity plus an observable sale action in context, rather than broadly approving anything containing “pay.” Its long unrelated lead-in still warrants an editorial brief check.

Some source passages are visibly broken transcript fragments or mixed topics. The broad encoding/repetition flags do not reliably detect those semantic problems, and their absence is not proof of a clean source. This report does not label every refusal a false positive, remove caller/track/media requirements, or recommend changing the operator's strict coverage setting.

## Recording and validation limits

The earlier recording investigation and [post-deployment measurements](rejection-workbench-recording-check.json) separately verified ten fresh XTTS gallery clips (99.2 seconds), with accepted items waiting for recording falling from four to zero while one continued recording. The playback take counter remained at 13 shelf serves because that ledger excludes off-air preparation. Preparation also worked before deployment; this is completion evidence, not a controlled speed comparison.

The corpus and cache audit are read-only. Five source-helper tests pass. The four journal tests initially reproduced three failures; after the production owner's patch, all four pass (0.307 seconds with an isolated data/cache directory). This verifies preserved candidate evidence, deferred-event deduplication and accepted-progress reuse. No improvement in semantic or phonetic model quality is claimed until actual bounded trials and the unchanged acceptance checks establish it.
