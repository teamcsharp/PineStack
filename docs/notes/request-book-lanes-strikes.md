---
name: request-book-lanes-strikes
description: "#1079-#1082 (2026-09-08 morning): the request book (data/pine_journal, /journal, 📖), OLLAMA_NUM_PARALLEL=2 + OLLAMA_LANES=2 + deploy --recreate, the tint strike cap and fault memo, the cacheable prompt prefix; agents die on the session cap"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-08T14:56:43.895Z
---

# The second pass of the 2026-09-08 inbox (#1079-#1082)

**Throughput (#1080).** Host: `/etc/systemd/system/ollama.service.d/zz-parallel.conf` sets
`OLLAMA_NUM_PARALLEL=2` (installed 11:59Z; every ollama runner now shows `-np 2` in `ps`; the one
`-np 1` runner left is not ollama's). App: `OLLAMA_LANES: "2"` in the spark-agent compose environment
(host `~/pinevoice-stack/compose.yaml`, backup `compose.yaml.bak-1080`; not in git) → `_ollama_lane`
permits, tint/station caps `lanes + 1`, global gate `2 × lanes`. A compose env change needs the
container RECREATED: `tools/deploy-at-radio-gap.py --restart --recreate` (compose up --force-recreate
at a quiet handoff); plain `docker restart` keeps the old env. `_system2_critical_work()` gives a
System2 job whose slot starts within 20 min one extra tint permit. `/api/tint` shows
`lanes_per_model`, `material` (passage sample age), `fault_memo`, `strikes_most`.

**Cacheable prefix (#1081).** `crystal_prompts._frame` order is now rules → strength → contract rules
→ world → passages → road → register → per-line evidence; `frame_prefix(prompt)` names the shared
part and tests pin it byte-identical across roads. `crystal_material(stable=True)` (the tint site)
holds one passage sample for `CRYSTAL_MATERIAL_WINDOW` = 1200 s so the runner's KV cache can reuse
the prefix; the pool builder still samples fresh. Rule 3 asks for the landing words first. Measure
with `prompt_eval_ms` vs `eval_ms` in `data/model_calls.jsonl`. Sources in
`docs/prompting-research-1081.md`; capacity model in `docs/system2-capacity-1080.md`.

**Rejections (#1082).** `_tint_retry_note` counts `strikes` (stagnant model answers, never reset by a
cooldown, reset by progress); at `TINT_STRIKES_MOST` = 12 the entry is `exhausted` → `tint_retry_status`
keeps `waiting` regardless of context change or the ladder clock (only `review_recovery_pending` /
`review_shelf_pending` reopens it); `dialogue_row_viable` refuses an exhausted, not-tint-ready row so
the scheduler writes its replacement. The old ladder test was re-pinned (three writer passes, not
seven). `_TINT_FAULT_MEMO` (in-process, 4096 lines) keeps refused faults/wording per source line;
`tint_prior_lesson(source, lesson)` prefixes them on the FIRST per-line ask in `crystal_tint`.
`_record_talk` wraps `_record_talk_body` and swallows `WritingDeferred` with one pipeline line.
The evaluator reconciliation was DONE by hand on 2026-09-08 (~08:30 CST), rule by rule, no version
bump: `_RAP_END_EXCL` landings (+ two short fragments need an exact coda), silent-e/-ed strip in
`_rap_norm`, `_rap_nuclei_end` final -y; contract: `_OPENERS` extended (interjections/imperatives -
NOT plural nouns), speaker-label heuristic names, em dash = separator, `_bare_one_waived`,
`_pronominal_one` article+adj+one at clause end, idiom-tagged "the only thing" never an ADDED count,
`_FILLER_NEGATIONS` idiom list only (the patch's "3-token anchor" rule was dropped: "No brakes on
that route" must stay refused), `_lexical_negation_kept`, `_interrogative_cue` (raw transcript =
no punctuation at all + a cue anywhere; punctuated source needs the cue at a sentence start);
journal digest = parent/marker/words/grader + process memo validated against the store. Doc:
`docs/evaluator-reconciliation-2026-09-08.md`.

**The request book (#1079).** `data/pine_journal/<id>.md` + `<id>.json` per resolved request, written
in `pine_resolve` (`pine_journal_write`) and backfilled once per process from `pine_completed.md`
(`pine_journal_backfill`, `_PINE_JOURNAL_BACKFILLED`). Costs: tokens at 4 chars/token (estimate),
`elapsed_s`, the station's `model_calls_rows` inside the window (labelled as the station's own).
Graph: headings → sections, bullets/numbered → steps, paragraphs → sections when unheaded.
Routes `GET /api/pine-journal`, `/api/pine-journal/{id}` (page 1 = newest; `next_id` = older),
`/{id}/md`, `/journal?id=` (`JOURNAL_PAGE_HTML`, `?key=` accepted then stripped). Panel: `journalOpen()`
(pineWin "journal", `journalFlowStart/Stop` three.js flow reusing `cloudSprite`), the 📖 `#journalBtn`
before `#trayBtn`, `PINE_3JS` key `journal`, desktop `THREEJS_VIEWS` parity.

**The follow-on inbox (#1083-#1087, same morning).** #1083/#1086 dead air = the throughput ceiling
+ the #1068 wipe (07:11 CST: 1,371 clips, 154 shelf rows, 2 larder rounds, 812 MB) emptying every
pile; hold and coverage 100 NOT changed (operator's rules); recommended next lever: single-line
roads on the fast lane. #1084: `system2_runtime.prepare()` now takes one sitting per lane
(`_prepare_lock` = Semaphore(OLLAMA_LANES), `_works`, `prepare_spawn()`, status `works[]`/`lanes`);
`crystal_stanzas` also holds its draw for the window (`_CRYSTAL_STANZA["served"]`). #1085: the
speakbox folder has NO "Allen Interface"; the crystal is off; the mentions are record announcements
(2,121 Allen Interface tracks in music_index, 12 of the last 300 plays) - no artist exclusion knob
exists. #1087: `docs/recreation/00..07` (the recreation guide). #1088 (rejection notices):
`line_review.py` `review_status='noted'` for `INFORMATIONAL_DISPOSITIONS` (rewrite_rejected, trim,
trimmed) and technical rows (`_initial_status`); a note escalates to pending only when the same
fingerprint is finally cut; one-time backlog triage at store open (`policy.triage_version`,
`reviews_triage` index); the pending feed's events are status-filtered; summaries carry
`attention`/`noted`. The desktop card (`desktopRejectionNotices` in renderer.js) polls
`/api/orchestrator/rejections?status=pending` and counts events since its cursor - before #1088 it
counted every rewrite_rejected intermediate ("550 rejection updates"). Measured before: 4,852
pending, 175 of the latest 200 intermediates, only 12 real cuts.

**The cupboard scan (2026-09-08 ~09:10-10:00, station paused; two agents, live + code):**
the tint ADMISSION gate was the jam: cap lanes+1 refused the 4th caller at once (70/148 asks bounced,
whole-round shelf asks 9/10), six tint drivers vs three permits, each bounce re-ran prep + two file
saves and retried in 6 s; seven "rapping 0/N" rounds sat ≥24 min. The second 31b decode slot gave
0.96× throughput (15.6 s alone vs 32.4 s overlapped) → REVERTED to `OLLAMA_NUM_PARALLEL=1` /
`OLLAMA_LANES=1`. The cupboard GET ran `cupboard_cut_review` DB lookups on the loop every 2 s poll →
8-10 s stalls (watchdog risk). Fixes: tint cap = lanes+3 (a waiting depth), `TINT_DEFERRED_REST`
30 s, deferral saves throttled, `CRYSTAL_GROUP_OUTPUT_CHARS` 1800→3000, `retint_one` pause-honest,
`_CUPBOARD_CUT_MEMO` 300 s + state memo 5 s. Not changed (operator rules): callers may not carry a
cut (20/21 bars thrown away on one cut), `prep_has_assigned_work` finish-first veto, deep model on
every road, avoid_piper. `_tint_turn_yields` and `TINT_TURNS_MOST` are dead code. Docs:
`docs/the-hour.md`, `docs/cupboard-fill-rate-2026-09-08.md`.

**Why:** the operator asked for all of it at once ("do all those things"); the four helper agents I
dispatched all died within minutes on the session rate limit ("session limit · resets 6:30am
America/Chicago"), so the batch was done by hand, sequentially.

**How to apply:** when the session cap is near, do not fan out agents — they share the cap and die
mid-task with nothing delivered; do the work directly and keep tool calls dense. SSH to the host was
very slow this morning (30-90 s per connection while HTTP answered in 0.2 s); keep SSH commands
short, run them in the background, and never put `\-np` style patterns in a remote grep (PowerShell
strips the backslash and grep sees an option). Related: [system2-handoff-and-switch](system2-handoff-and-switch.md),
[tint-yields-to-air](tint-yields-to-air.md), [floor-and-paced-air](floor-and-paced-air.md).
