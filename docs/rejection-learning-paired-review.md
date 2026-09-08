The candidate run accepted **10 of 12 cases**, compared with **9 of 12 baseline cases under the same current grader and frozen vocabulary**. Manual review was mixed and does not demonstrate an overall improvement in prompt quality.

| Comparison | Raw machine passes | Accepted | Accepted with style advisories |
| --- | ---: | ---: | ---: |
| Baseline as originally evaluated | 3/12 | 3/12 | 0 |
| Baseline with proven original bar boundaries, current grader8 | 8/12 | 9/12 | 1 |
| Candidate, current grader8 and the same frozen vocabulary | 9/12 | 10/12 | 2 |

The historical 3-to-10 change includes grading and cleanup fixes. It is not evidence that the revised prompt alone produced that improvement. The comparable acceptance change is 9-to-10: cases 5323 and 5270 became accepted, while 5431 became held. Case 5431 passes the raw checks but the factual guard correctly holds its change from *trying to spin* into the asserted *you spin*, which explains why raw passes plus advisories do not equal accepted cases.

Both cross-grades use the actual workbench grader in an isolated preview, identical source/style passages, strength0.88, meaning mode, fluid acceptance, and the [same frozen vocabulary](rejection-learning-baseline-v8-crossgrade-vocabulary.json). All twelve outputs on each side have exact request/response trace proof; baseline bar boundaries come from the actual model response rather than invented punctuation. The candidate already preserves those boundaries. Original model artifacts remain unchanged: [baseline trials](rejection-learning-baseline-trials.json), [candidate trials](rejection-learning-candidate-trials.json), [baseline cross-grade](rejection-learning-baseline-v8-crossgrade.json), and [candidate cross-grade](rejection-learning-candidate-v8-crossgrade.json).

The baseline used prompt2 and learning revision2. The candidate used prompt4 and learning revisions8,9,10 as guidance changed during the run. This is a comparison of combined configurations, not a controlled test of one instruction. All twelve cases have now been used for debugging; their original train/holdout labels record provenance and do not establish a blind holdout.

Manual comparison of all twelve cases found:

| Assessment | Cases | Evidence |
| --- | --- | --- |
| Clear relative fidelity improvement | 5270 | Removes the invented *for the win* motive while preserving radio returns and apparent theft. |
| Qualified fluency improvement | 5300 | Piano/track facts remain and awkward wording improves, although generic rhyme padding remains. |
| Quality regression | 5039, 5431, 4301, 5325 | Adds street/cold/thirsty details; loses the attempt distinction; invents a mutation; changes identity revelation into an unclear plot/possession comparison. Only 5431 is held. |
| Identical wording | 5426, 5428 | No wording improvement after applying the same current cleanup. |
| No clear quality gain | 5323, 4899, 5308, 4310 | Unsupported pan/location, strained filler, an invented play referent, or the same no-brake invention remain. Dale case4310 is correctly held. |

These are reviewer judgments about this small debugging set. Rhyme and acceptance checks still miss some unsupported meaning changes. [The full paired review](rejection-learning-paired-review.json) preserves every source, both outputs, grades, trace proof, profile, individual explanation, and input hashes. This review made no model, apply, vote, settings, or playback request.
