# H3 technical explanations and advance recording audit

The station is banking material while paused, and its recording room groups a performer's lines across several scripts. H3 technical overviews use a separate hourly video pipeline. They do not currently share the recording sitting or reserve clips for each future broadcast hour. The original overview prompts encouraged slogans more strongly than explanations; the live prompt book now requests one concrete explanation within the existing 10-second limit.

The operator confirmed that the target is a clear 10-second explanation of one feature. This audit traced the source, read the live station and saved prompt history, exercised the prompts against the configured model, and updated the three existing prompt alternatives through the station API. The station remained paused. No video benchmark or viewing assessment was performed.

## Current preparation coverage

Live observation: October 1, 2026, at 2:47 PM America/Chicago. Values describe that snapshot, not a permanent reserve. The [evidence file](h3-technical-guide-audit-2026-10-01.json) contains the selected live summaries and model replies.

| Measure | Observed value | Meaning |
| --- | --- | --- |
| Station state | On, paused | Preparation continues while the show is off air. |
| Normal preparation setting | 6 hours | The ordinary schedule horizon. |
| Additional pause reserve | 72 hours, caller and manager | Extra demand for these two roads; this is a target, not proof of completed recordings. |
| Six-hour schedule obligations | 21,600 seconds | The coverage the inventory planner owes. |
| Ready schedule coverage | 13,975.7 seconds, about 3 hours 53 minutes | Material currently counted as ready against those obligations. This does not establish one contiguous ready interval. |
| Planned coverage including unfinished stock | 18,717.5 seconds | Assignment includes material that is still being prepared. |
| Unplanned shortage | 2,883.5 seconds, about 48 minutes | Obligations without assigned stock. |
| Selected recording work | 276 lines across 35 rounds | About 31.9 minutes of speech; the room estimates about 79.5 minutes to record it. |
| Pantry cache | 23,387.4 seconds, about 6.5 hours | Cached audio is broader than material usable in the next six hours. |

The cache figure alone would overstate readiness. Live readiness also differs from persisted `prepared` flags: callers had 23 such flags but 11 ready rows in the live recording-room summary; gallery had 43 flags but one ready row. These comparisons establish that the flags are insufficient, not the reason for each refusal. Cast, freshness, content and production checks must be consulted before counting a row as usable.

## What one recording sitting actually does

In [app.py](../app.py), `pantry_keeper` pools viable, tinted scripts and invokes `recording_sitting` when more than one is waiting. A sitting takes at most six scripts. It counts missing chunks by voice, gives priority to voices that can complete rounds, and calls `larder_prepare(entry, only_voice=voice)` across the pool before moving to the next performer. While paused, the keeper allows at least 120 seconds per sitting slice. Different engines can work in parallel; preparation on the same engine is limited to one render.

At the snapshot, the room was recording a gallery round through XTTS. `/api/rooms/sitting` previewed four actors across six scripts. That preview counts scripted lines without the sitting's missing-audio filtering, so its 85 lines are not a trustworthy count of remaining recording work. `/api/rooms/call-sheet?hours=6` is the stronger diagnostic for work selected by the schedule.

Grouping the work is implemented. A single continuous recording spanning all those scripts is not the default execution path. The engine still synthesizes bounded chunks, stores individual takes, and later assembles them in script order. [script_production.py](../script_production.py) labels this `segmented_synthesis`; its continuous-take road requires a separately enabled mode and verified alignment. The current production mode file reads `on`, without the continuous option.

There is a reason to retain the distinction. The [September continuous-take benchmark](notes/continuous-take-bench-2026-09-15.md) found adapter truncation above 1,000 characters, accepted cuts for only five of eleven performer parts, and no established general speed advantage. This audit did not repeat that benchmark. Enlarging requests or removing the six-script cap would need new measurement.

## How the H3 explanation is generated

The hourly path is `h3_hourly_ad_clock` → `h3_hourly_render` → `h3_overview_prepare` → `h3_prompts_hour` → the video queue.

The clock checks `_RADIO.on`, not `radio_paused()`. With the station on and paused, H3 can continue generating one hourly clip. It does not commission six future clips because `prepare_hours` is six, and no future schedule obligation is attached to an overview by this path. The request uses a freshly selected reference clip, gallery image or host route; it does not take an actor's master recording from `recording_sitting` and cut multiple overview segments from it.

[h3_overview.py](../h3_overview.py) reads up to 300 changelog entries, groups tagged commits by their first tag, and rolls one feature. The model receives its tag, subjects, commit bodies, touched files and change counts, plus the selected presenter and one to three actions. The brief includes up to six commits and is capped at 5,000 characters. This is commit-message evidence; it does not inspect the implementation or diff to prove that the feature still behaves that way.

The model returns `say` and `do`. Ten seconds has a 19-word spoken budget at the existing pacing allowance. The parser and speech checks assess sentence shape and length. They do not independently establish factual correctness, explanation quality, or whether the finished video faithfully speaks the requested words.

## Problems found and changes applied

Saved history contained eight overview attempts: five fell back, including four with `KeyError`, followed by three model outputs. The model-setting error already has a fix in the current source; it was not introduced or repaired by this audit. The later outputs still showed the prompt problem. Examples included “Every slot preset saves your time now” and “Our pause-bed feature fixes that instantly.” They named or praised a feature without teaching its operation.

The original alternatives explicitly asked the model to sell, sound world-changing, or create urgency. Adding constraints underneath those instructions improved some outputs but still produced filler in the first model trial. The three built-in styles have therefore been rewritten: infomercial energy, thoughtful TED delivery and emphatic delivery remain, but each asks for actual behavior in plain language.

All three live alternatives were updated through `/api/segment/prompts/h3_overview/alternative/{id}` and read back through `/api/segment/prompts`. Their IDs, names, weights, enabled states and random selection mode remain intact. Their previous contents are retained in `data/h3-guide-prompt-book-before.json`.

The common requirements ask for a trigger and concrete operation, permit only supported results, distinguish historical faults from current behavior, exclude engineering metadata from speech, and subordinate gestures to a simple diagram of the same explanation. The 19-word budget is explicit in the system prompt. The source also applies these requirements when constructing requests, so future saved alternatives receive them after the module is reloaded.

The parser previously shortened an oversized first sentence by taking its first words and adding a period. That could turn a sentence into an apparently valid fragment or remove a qualification. The source now keeps only a complete sentence prefix that fits and rejects an oversized or unfinished first sentence. This source change is tested but awaits the next service reload. The live prompt updates are already active; no restart was performed during the station's ongoing preparation.

## Validation and remaining limits

The focused suites passed 35 tests: 13 overview, nine feature-slot and 13 speech tests. The broader preset suite passed 12 of 13. Its existing patch-verification assertion reports eight applied edits against nine planned edits; both `app.py` and that patch tool are unchanged from the repository baseline. That failure was not concealed or altered.

Three final probes used the configured `huihui_ai/gemma-4-abliterated:e2b` model, thinking disabled, temperature 0.9, a 420-token limit and a 4,096-token context. Every final output fit the spoken budget and passed the speech gate. Examples:

- Pause bed, 13 words: “When paused, the station plays an endless set so listeners hear continuous music.”
- Advance banking, 17 words: “When paused, the system stores caller and manager memos for days ahead so real-time pressure is reduced.”
- Footage reference, 18 words: “When footage is loaded, the system opens the H3 stinger window, so you can reference the video instantly.”

These outputs explain more than the saved slogans. They are a small sample, not a factual-quality guarantee. The footage example still compresses an operator option into “when footage is loaded” and adds “instantly”. An additional instruction now explicitly preserves who initiates an operation and excludes unmeasured timing claims. A fourth probe removed “instantly” but still blurred the operator option. This is an observed limitation of the current model and evidence, not a solved quality check. Future review should check exact triggers before spending video-render time. The probes exercised the model directly, not the complete station queue or a newly rendered video. Initial probes accidentally left thinking enabled and exhausted the token budget; those results were excluded from the final comparison after correcting the request to match the station's thinking setting.

The next substantive planning change would be to commission one H3 overview for each future hour, retain the chosen feature and evidence with that obligation, and mark it ready only after the finished clip is verified. Actor grouping and segmented audio already exist; H3 needs that scheduling integration separately. Changing only a prompt cannot supply it.
