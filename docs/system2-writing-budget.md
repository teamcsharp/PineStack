# System2 authoring budget — 2026-09-08

The old writer asked every turn for four to seven sentences and 60–100 words.
Eleven caller turns therefore requested 660–1,100 words before the rhyme pass,
despite a three-minute scheduled slot. Its repair prompt independently demanded
55 words per turn. Full-source/prepend/append branches could then insert thousands
of characters after drafting; repetition pressure added passages even at zero
prepend/append settings.

New System2 work gets a task-local authoring budget of at most 90 seconds, reduced
for a smaller slot or remaining debt. It reserves eight seconds plus four seconds
per pair of turns, estimates speech at 170 words/minute, and leaves 25% room for
the later rhyme rewrite. These are estimates, not proof of playback duration.
The existing exact recorded-media duration check still determines slot admission.
The global reply cap, caller arc, factual and rhyme grades are unchanged.

Primary and structural-repair prompts now share the short-turn instruction and
output limit. The original writer remains unchanged outside System2. The legacy
long-form size test is replaced for System2 scenes by a complete-turn structural
check; callers retain the existing separate introduction, question/answer,
grounding and resolution contract.

A complete source sentence is selected before the model request. Its full exact
source and original lines are retained alongside the selection; this syntactic
boundary does not claim to certify independent semantic completeness. A sentence
that cannot fit is never cut into a fragment. A required caller source without a
fitting sentence defers the draft. System2 performs no postdraft forced reading,
prepend/append/full-swath insertion or source blending. Accepted scripts and
recordings are never trimmed by this change.

Validation: 151 focused tests passed in 6.905 seconds using fresh data/import
directories. Seven new tests include the actual `dj_banter` primary and repair
paths, maximum legacy additive settings plus maximum repetition pressure,
unchanged text entering tint, complete-source evidence, and task-local settings.
No live model request, playback, setting change or deployment was performed.
