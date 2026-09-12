# Rhyme assistance and retained-rejection audit

The prepared change adds a persistent local pronunciation and WordNet sense index before Crystal generation. Shared prompts are version **5**, the grader is **9**, and the source contract is **3**. The 160 focused regressions passed. This report records source and isolated verification; it does not assert deployment or new live rewrite quality.

## Dictionary, senses, and vectors

[rhyme_assistance.py](../rhyme_assistance.py) imports the complete bundled resources into `data/rhyme_assistance.sqlite3`: **132,962 pronunciations, 117,659 senses, 206,941 lemma/sense links, and 6,046 inflection links**. The measured fresh import took **5.424 seconds**. A compatible existing index opens without importing the corpora again. Full source hashes are checked when building; a failed replacement preserves the existing index.

| Resource | Pinned source and provenance |
| --- | --- |
| CMUdict | Commit `74790861f652b15e4ac49015a90074ad62a27690`; dictionary SHA-256 `81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22`; [bundled provenance](../vendor/cmudict/provenance.json) and [license](../vendor/cmudict/LICENSE). |
| Princeton WordNet | Version 3.0; official archive SHA-256 `640db279c949a88f61f851dd54ebbb22d003f8b90b85267042ef85a3781d3a52`; [every bundled file hash and archive member](../vendor/wordnet/provenance.json), [license](../vendor/wordnet/LICENSE), and [README](../vendor/wordnet/README). |

WordNet supplies sense-specific relationships, definitions, part of speech, exception forms, and tagged-use counts. The provider retains exact data-file offsets rather than inventing synonym relationships. The structure and redistribution terms are documented by Princeton in [the database format reference](https://wordnet.princeton.edu/documentation/wndb5wn) and [license guidance](https://wordnet.princeton.edu/license-and-commercial-use). Bundled resources are also included in desktop packaging; runtime retrieval needs no corpus download.

Each source gets a bounded shortlist of source words, cited sense alternatives, and distinct rhyming endpoints. Exact CMU phones, dictionary revision, source hash, and WordNet sense identifiers remain in the trace receipt. Common sound-only options use actual WordNet tagged-use counts; uncommon words remain possible when supplied by the source or its cited sense. Names, repeated vocative tags, and the grader's same-word/suffix exclusions are respected. Sound matches still do not establish meaning.

The persistent search has two explicit layers. FTS and normalized 512-dimensional hashed lexical vectors provide an immediate local fallback. Real cached `nomic-embed-text` query and sense vectors can rerank that shortlist when model, dimensions, and exact source match. Model vectors are stored as bounded, validated float arrays with model/source/corpus provenance; wrong dimensions, nonfinite values, stale source hashes, and incomplete batches are rejected. No neural synonym is inferred solely from a cosine score.

The idle worker may prepare at most eight missing sense vectors plus one exact-source query in a batch, once per 30-second loop, with a 30-second timeout. It waits while ordinary model jobs or the common model gate are occupied. One lock prevents overlapping warm batches; query caching is bounded to 2,048 entries and pending source requests to 64. Source generation only reads available results. Cancellation joins an in-progress corpus import before closing SQLite, and preserves unfinished embedding requests for a later attempt.

**The verification index had no neural embeddings.** All six measured queries used the labelled lexical fallback, with median **26.446 ms**, maximum **34.271 ms**, and **1,997–2,145 additional prompt characters**. [Full receipts and timings](rhyme-assistance-retrieval-check.json) distinguish actual data from mocked neural persistence tests. Full-corpus lexical availability does not mean all 117,659 senses already have neural vectors. Sustained model load can delay that background enrichment.

## Shared prompt and grader boundaries

`crystal_source_contract` remains a pure grader contract. The separate `crystal_prompt_contract` adds optional assistance only for actual turn, whole-round, and failed-turn repair prompts. Workbench trials use the same prompt builder. The full receipt is traceable; the prompt includes only a compact selection of endings and definitions, with explicit instructions to preserve source propositions and not borrow dictionary examples as facts. A source-hash mismatch omits the suggestions. Accepted neighboring turns are not rewritten or supplied fresh word options.

Three narrowly reproduced false refusals are corrected in grader 9:

- CMU pronunciation evidence now includes two-letter terminals such as **go**, while preserving different-word, actual-terminal, suffix, numeric-ending, and semantic controls.
- Sentence-initial **Reclaiming** and **Teaming** are not inferred as personal names in the demonstrated grammatical contexts. Actual names, capitalized titles, uppercase names, and interior proper names remain protected.
- A comma-delimited declarative **you know?** discourse tag does not force a substantive question. Actual questions and other question clauses remain protected, and the caller contract uses the same result.

This does not broadly equate negation with words such as “unaware,” weaken source facts, or waive rhyme. Retained examples that lose an attempt, invent an event, or change a source contrast may still fail. A machine pass can also miss such drift; manual limits are recorded below.

## Retained failures and counterfactual replay

The audit classifies all **5,822 retained events** through cursor 5822 and preserves per-event evidence for **389 events after cursor 5433**. Of those new events, 239 are tint records: 62 from grader 6, 78 from grader 7, 98 from grader 8, and one without a comparable recorded grade. Exact source, candidate, force, style passages, and answering context allow replay of **238 events**, comprising **213 context variants and 181 distinct source/candidate pairs**.

The replay uses the actual current evaluator in an isolated data directory, frozen fluid policy, preview context, and the earlier 23,165-word retained vocabulary plus exact current style passages. No model, embedding, vote, recovery, or playback request is made. Historical cache completeness is unknown. Repeated refusal and regrade records are events, not independent generation attempts. See [all event classifications and exact grades](rhyme-assistance-rejection-replay.json), [the read-only replay tool](../tools/rhyme-assistance-replay.py), and the preserved [earlier capture](rhyme-assistance-failure-audit.json).

| Comparable event result | Stored historical grade | Current grader 9 |
| --- | ---: | ---: |
| Effective acceptance | 0 | 16 |
| Raw machine pass | 3 | 19 |
| Semantic check pass | 163 | 167 |
| Rap evidence pass | 69 | 80 |
| Accepted with style advisories | 0 | 0 |

There are **16 newly accepted events across 15 context variants and 14 wording pairs**, with no newly held event in this retained cohort. This compares several historical graders to the current grader; it is neither a production pass rate nor a prompt-quality experiment.

Independent reading of all 14 newly accepted pairs found mixed quality. The Skip/planned-performance rewrite broadly preserves the source. Several phone greetings add an unrelated “fate” question; the flow/go news line loses an attempted search and gives thin air new agency; one setup rewrite remains ungrammatical. Other imagery is context dependent rather than necessarily a new literal fact. [The manual review](rhyme-assistance-replay-review.json) keeps exact wording, every affected event, and these distinctions. Pronunciation and normalization fixes recover real false refusals without certifying every recovered candidate.

Other retained failures need different remedies. The remaining 150 events include trimming (31), unfinished fragments (25), segment brief failures (21), blend contracts (19), caller contracts (13), radio-draft checks (12), line quality (11), repetition (8), language checks (7), and one each of freshen structure, tint structure, and ad repetition. Source-bound word options cannot by themselves repair missing products, incomplete sentences, speaker order, missing caller introductions, repeated topics, or output-budget failures. Their complete recorded reasons remain in the event artifact for the scheduler and drafting work.

The prior 12-case experiment was also regraded without generation under current v9 and the same frozen vocabulary. The baseline's exact wire-restored wording remains **9/12 accepted**; the previous candidate cohort remains **10/12 accepted**. Those files are [baseline cross-grade](rhyme-assistance-baseline-v9-crossgrade.json) and [candidate cross-grade](rhyme-assistance-candidate-v9-crossgrade.json). Earlier delivered wording had lost bar separators, so delivered and wire-restored grades stay separate. This result supplies a comparison baseline, not evidence that prompt 5 improves wording.

## Verification and prepared live plan

[The focused run](rhyme-assistance-focused-tests.json) passed **160 tests in 13.209 seconds**. Coverage includes full corpus import/restart and integrity failure, source-bound receipts, vector persistence and model/dimension fencing, concurrent read isolation, long-source lookup, prompt compaction, existing whole-round/failed-ID repair contracts, real CMU and negative controls, caller questions, workbench behavior, background admission, bounded warming, and cancellation cleanup. Test data and generated indexes are isolated; no live provider calls or controls were used.

Six cases are prepared in [the exact-source plan](rhyme-assistance-live-plan.json). [The GET-only preflight](rhyme-assistance-live-preflight.json) found all six current, pending, and nontechnical, with exact source matches. It records current revisions and serial `/try` request bodies with no extra operator instruction and reasoning off. These are debugging cases, not a blind holdout. No trial has been started by this work.

At preflight, the configured deep model was `gemma4:31b`, fast fallback `gemma4:e2b`, context 65,536, force 0.88, hold on, and learning revision 15 in enabled fluid mode. `/try` chooses `tint_model_for(kind)` when the request executes and does not accept a model override. The budget can select the fast model. Therefore a future trial must retain the actual wire-model receipt, current prompt/grader/learning revisions, retrieved suggestions, raw and effective grades, output, and timing. Recheck source/event/revision before each POST; a changed case must not silently be replaced. No applies, votes, settings changes, or playback belong in this plan.

[The validation manifest](rhyme-assistance-validation.json) records final source hashes, corpus provenance, artifact hashes, and the limits of this verification.
