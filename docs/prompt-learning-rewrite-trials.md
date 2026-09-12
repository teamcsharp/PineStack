# Two deployed prompt-learning wording trials

Run `ee1b306bccb24b6eb09ddc6d167939cd` used two current pending source occurrences, serially through the normal model queue. Exactly two `gemma4:31b` requests completed with thinking off, no extra operator instruction, grader 6, prompt 2 and learning revision 2 in fluid mode. Both passed the raw machine checks and were accepted; neither needed a fluid style waiver.

Manual inspection found remaining wording problems. These are two selected retained failures, not a station-wide pass rate or a controlled estimate of learning effectiveness.

| Source occurrence | Raw model output | Raw / accepted | FIFO wait / model wire |
| --- | --- | --- | --- |
| banter 3123 | Why you bother with the act / why let him hit that fact? | Pass / yes, no waiver | 32.376 s / 5.916 s |
| news 2616 | Request some metaphors to make it clear / explain the rest so the vision's near | Pass / yes, no waiver | 30.003 s / 5.456 s |

The banter source was "Why did you bother to have sex with him then?" The new act/fact bars rhyme, but the sexual encounter becomes vague, the explicit past tense disappears, and "hit that fact" is awkward filler. All three qualified banter reminders appear verbatim in the actual model request; this sample does not show that they solved those faults.

The news source was "Ask for metaphors to explain the rest." Its new wording preserves the central instruction and gives a clear clear/near rhyme. "So the vision's near" remains vague padding. It avoids the concrete test, plot and gear invented by earlier attempts, but this single sample is not a clean-quality or causal improvement claim. There were no qualifying news-specific reminders at revision 2: its effective learned guidance was empty, while the shared fluid prompt guidance was present.

The JSON retains each exact original, stored rejected attempt, request, current revision, full wire prompt and response, complete trace, trial grading, manual assessment, model counters and timing. Both requests used a 180-token output limit and ended normally, with 15 and 18 generated tokens respectively. The observation totals were 39.921 s and 35.969 s; most elapsed time was queue wait, not generation.

Only isolated `/try` operations were posted. There were no votes, wording applications, settings writes, recordings or playback requests. Rejection policy and manual Crystal settings were unchanged. Read-only station snapshots remained on and unpaused; no station state was modified. Learning revision remained 2 across the check.

Exact evidence: [prompt-learning-rewrite-trials.json](prompt-learning-rewrite-trials.json).
