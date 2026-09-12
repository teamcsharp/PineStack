The twelve existing baseline rewrites produce **9 accepted results under the current grader and bar cleanup**, including eight raw machine passes and one style advisory. No new wording was generated. This is the comparison baseline for a later candidate-prompt run; comparing that run only with the historical 3/12 result would mix prompt changes with grading and cleanup changes.

| The same twelve model responses | Raw machine passes | Accepted, including advisories |
| --- | ---: | ---: |
| Historical recorded verdicts | 3 | 3 |
| Exact delivered wording, current v8 grade | 7 | 8 |
| Exact wire bars, current cleaner and v8 grade | 8 | 9 |

The [full cross-grade report](rejection-learning-baseline-v8-crossgrade.json) uses the actual `RejectionWorkbench.grade` function in an isolated data directory and preview context. Every case retains its original source, style world, style passages, force, meaning-grade setting, and fluid-mode setting. All twelve original responses were proven by matching trace ID and model call ID, ordered wire-request/response/evaluation steps, exact source and style JSON in the request, and exact agreement between the legacy-cleaned response and the delivered trial candidate. Original slash bars were never reconstructed from guessed punctuation.

The restored-bar variant changes the current result for gallery occurrence 5429: its actual rhyme landings survive cleanup. The delivered-text regrade also fixes known phonetic misses and the false numeric interpretation of pronominal “one” in occurrence 4899. Transformation and source-copying verdicts are unchanged across all twelve delivered-text comparisons. News occurrence 5431 is accepted with a transformation advisory; the new rhyme evidence does not turn its raw machine verdict into a pass.

The [frozen vocabulary](rejection-learning-baseline-v8-crossgrade-vocabulary.json) contains 23,165 sorted words, derived from 36,628 stored DOOM text chunks plus the exact retained prompt passages. Its source vector file and frozen word set are hashed. The 625 MB vector file was streamed without loading numeric embeddings or invoking a vector-loader side effect. The file's recorded modification time predates the baseline trials, but the completeness of the old process's in-memory vocabulary cache is not proven. The frozen vocabulary can be reused by the [runner](../tools/crystal-baseline-crossgrade.py) with `--vocabulary` so later comparisons do not depend on changing mind files.

The original six train/six holdout labels are retained only as provenance. **All twelve cases have now informed debugging; none remains a blind holdout.** Machine acceptance remains separate from the [manual wording review](rejection-learning-baseline-manual-review.json): several baseline outputs contain unsupported additions, vague referents, or awkward filler despite passing current checks. No prompt-effect claim is made until actual paired candidate results are available.

The original [baseline trial artifact](rejection-learning-baseline-trials.json) remained byte-identical. This check made no model, voice, review, policy, playback, or station-control request.
