---
name: tint-yields-to-air
description: "#1063 (2026-09-06): the silent station was the #1057 tint contract holding everything - three gates, a 0.7% evaluator pass rate, the crystal_tint_hold dial that fixed it, the line_prints cache; how to read it next time"
metadata: 
  node_type: memory
  type: project
  originSessionId: bffbb184-8e55-4cdc-ab52-c6653e1b0e41
  modified: 2026-09-06T19:46:15.443Z
---

**The 2026-09-06 silence, measured (do not re-derive):** the station was
on, records playing, `dialogue_flow.ready` 0/12 for hours, the chat log
full of `emergency_host` filler ("keeping you company while the next
conversation gets ready"), every phone call ending "NEVER MADE AIR - every
turn of the call was lost before the speaker", writers `deferred: {gemma4:e2b: 92}`.
Nothing was broken on the device or the engines. The previous session's
#1057 batch made the crystal tint a CONTRACT with three gates:
1. readiness - `dialogue_row_ready` = `dialogue_tint_ready and dialogue_audio_ready`,
   so a fully recorded round was not READY without current tint proof;
2. the recording gate in `_speak_turns_floorless._recording_tint` - a selected
   line whose `crystal_line` did not pass was DROPPED (`note_drop "recording held"`);
3. the pre-record door in `dj_speak` (~20872) - same drop for single-line roads.
Plus `legacy_tint_revalidate` marked 324/325 stored rounds `repair_required`
(86 of them for a false negative: `script_plain` A,A,A,B vs tinted A,B,A,B
relettering), and `tint_recovery_clock` burned the model lane repairing them.
The killer number: `GET /api/tint` coverage = offered 144, tinted 1 (0.7%).
The version-2 deterministic evaluator (internal/multisyllabic rhyme + crystal
lexicon + rhetoric transformation, coverage 100, force 0.88) rejects almost
every rewrite, so a contract gated on it is an off switch.

**The fix (#1063, deployed 2026-09-06 ~13:38 CST):** one dial
`dj.crystal_tint_hold` (default False). `dialogue_tint_required()` is now
two_pass AND coverage>0 AND hold; new `dialogue_tint_wanted()` (two_pass AND
coverage>0, or a mocked-true required) is what the roads that RUN the tint
key off (pre-record door, track-talk side, advert). With the hold off a
failed/deferred rewrite airs as written with a `(#1063)` pipeline_log line,
recorded rounds are READY on audio alone, `tint_recovery_step` stands down
("the tint yields to the air"), and `dialogue_flow.blockers` names held
rounds when the hold is on. `GET /api/tint` reports `hold`;
`POST /api/prefs/tint {"hold": true|false}`; a checkbox in the 🔮 tint
settings. Also `line_prints()` is now mtime-cached like `phrase_prints()`
(it was parsed per candidate line - 34 stalls / 95s per 10 min on the pulse).
Tests: `tests/test_tint_yield.py`; the #1057 suites
(test_tint_contract/test_tint_recovery/test_schedule_readiness) still pass
because they mock `dialogue_tint_required`.
Measured after: ready 3/12 within 90s, 2.9h buffered audio, real call turns
on air, Nabu `audible_volume 1.0`, pulse top = only `_load_vectors` at boot.

**How to apply:**
- "No dialogue" with engines fine and records playing: read `/api/tint`
  coverage share and `/api/recording-room.tint_recovery` FIRST; if
  `offered >> tinted` and `hold` is on, that is the whole story.
- Keep `crystal_tint_hold` off unless the operator explicitly wants silence
  over plain lines; the evaluator's pass rate, not model capacity, decides
  whether "tinted" stock ever exists.
- Run tests in the container with an isolated data dir:
  `docker exec -e SPARK_AGENT_DATA_DIR=/tmp/x spark-agent sh -c "cd /app && python3 -m unittest tests.test_tint_yield"`.
  Restart = POST /api/service/restart with the Bearer key from
  `~/pinevoice-stack/.openwebui.env` on the host; healthz back in ~3s.
- The Bash tool truncates a command past roughly 8KB (a long heredoc dies
  with "unexpected EOF"): write big patch scripts with the Write tool, then
  run them. `scp` of app.py to/from the host takes ~1.5s vs minutes on SMB.
- A pyflakes "undefined name 'socket'" at the Wyoming annotation is
  pre-existing noise (string annotation), not a deploy blocker.
See [hour-contract-two-truths](hour-contract-two-truths.md), [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md),
[pulse-library-and-firmware-down](pulse-library-and-firmware-down.md), [orchestrator-dead-wiring](orchestrator-dead-wiring.md).

**Follow-ups the same afternoon (#1062, #1063, commit after 5ab10cc):**
- #1063 "a recorded line airs": `_banter_air` computes `_recorded` =
  frozen + `dialogue_audio_ready`, skips the #901 freshen for it, and
  passes `recorded=True` into `speak_turns`/`_speak_turns_floorless`;
  the gates there go through module-level `air_gate(recorded, who, text,
  why)` (drop when unrecorded, log "(#1063) airs as recorded" otherwise),
  and rerun/phrase gates are exempt on a recorded round. Still stops a
  recorded line: `is_binned` (operator burial) and the writing profile
  changing (`_larder_current`). The two pre-existing number series
  collide: old "#1062/#1063" comments in app.py are the tint-budget era,
  not these requests.
- #1062 "new SFX clips play": `data/sfx_seen.json` first-sighting ledger
  (`_sfx_arrivals_note`, first walk stamps everything old), recent
  arrivals forced into the pool past the `SFX_MAX_FILES` sample,
  `sfx_fresh_paths` (never played OR seen <48h) gets `SFX_FRESH_SHARE`
  0.5 of draws in `sting_due`, `sfx_keeper` walks once a minute while
  on air, `sfx_plays()` mtime-memo. Live after deploy: pool 3,307, fresh
  2,878 (never played) - so "fresh" is most of the pool until it burns down.
- Inbox resolve path that works: write `{"id": "note"}` JSON, `docker cp`
  it in, `docker exec spark-agent python3 tools/inbox-resolve.py FILE --apply`
  (key comes from the container env; UTF-8 safe, no PowerShell traps).

**#1064 (same day, later): the operator's definition - "the crystal is a
hard rewrite BEFORE the recording room; when it's on the entire universe
rhymes and raps"** (they sample the bars into music). What that took:
- `crystal_tint_hold` default flipped to TRUE (nothing recorded/aired
  untinted). NOTE: settings.json had an explicit `false` written by the
  normalizer after the #1063 deploy, so the default alone did nothing -
  `POST /api/prefs/tint {"hold": true}` was needed. Check `/api/tint` hold.
- `crystal_grade_rhyme` (default False = "meaning" grade): the spelling
  rhyme/lexicon proofs are ADVISORY (reported in `advisory`), a bar passes
  on semantic + transformation + no copied 6-word lyric run. Strict refused
  68% of real bars ("we live and clear - spit it, dear"). Measured after:
  share 0.83 (15/18 lines), 15 rounds/9 min, calls airing as bars.
- The whole-round loop no longer breaks at the first refused line (it did:
  "turn N failed tint evaluation" + break = the round's bars thrown away);
  under the hold a line gets 3 asks with its graded faults, 2 without.
- Tint asks are their own admission lane (`_ollama_category` -> "tint",
  cap 0 = wait, never deferred). Before: 51 deferrals/5 min, each deferred
  ask returned the line unchanged and was graded "not transformed".
- `crystal_vocab_warm()` builds the crystal's whole vocabulary once per
  crystal in a thread (the cold `_load_vectors` of the 523MB doom store
  shows as a ~10s "outside app.py" stall at boot - pre-existing cost).
- `ask_model` never appends the heat clause to a "tint*" mark (it echoed
  "THE DIAL (#941)..." into bars). `tint_budget` share 0.9 under hold;
  `tint_retry_rest()` 120s under hold. `crystal_turn` prompt names the
  world + "CONVERT into a bar of a battle rap".
- Roads: SFX guy quip (crystal_line before render; dropped under hold if
  it did not rap), emergency continuity (rapped at prepare, keyed by
  crystal via `continuity_key(..., crystal)` + `plain`), listening
  responses (response_bank rows carry `crystal` + `said`; `ready/take/
  missing_entries(crystal=)`; PHRASES only plain). Paper already tints.
- `/api/tint` coverage: offered = asks, tinted/refused = LINE verdicts,
  rounds separate; share = tinted/(tinted+refused).
- Old-series "#1062/#1063/#1064" comments in app.py predate these requests.

**Throughput under the hold (measured 2026-09-06 evening, the numbers to
remember):** one ask per line on a serialized lane raps ~3 lines/min; the
show needs 5+; a ten-line round only becomes READY when EVERY line passes,
so at p=0.5 the reserve never fills and the plain emergency stopgap airs.
What fixed it: `_crystal_round_first_pass` (the whole round in ONE ask,
seeded into the line-by-line loop as resumable progress - only refused
lines cost another ask), the meaning grade (names rule: sentence starts and
"That's/I've" are not names; anchor floor 0.35 at force>=0.75), the tint
lane, and `tint_model_for` -> fast model while `prepared_seconds() < 600`
under the hold. Measured after: share 0.77 (58/17), 25 rounds/10 min, no
stalls, XTTS voicing 27 renders/10 min; the reserve converges over ~20-30
min after a restart because every re-tinted round must re-render.
`_looks_meta` tells now include the retry prompts' words ("anchor word",
"style sample") - one recited prompt DID air before that. Real lever left
on the host: OLLAMA_NUM_PARALLEL=2 (+ `_ollama_lane` cap 2) would double
tint throughput; not done (needs an ollama restart mid-show).

**The cut rule (final shape of the hold, 2026-09-06 late):** under the
hold a line refused after its 3 asks is CUT before the studio
(`coverage.cut`; the round is whole when every remaining line is a bar and
>= half the required lines passed). Before it: a shelf census showed ZERO
rows with a complete tint - one refused line held every round. After it the
finished reserve climbed 44s -> 416s in ten minutes (with the station paused
by the operator = the banking window). `/api/radio/pause` + `data/paused.json`
say who paused ("the pause control (panel/API)" = the operator, leave it).
#1065: `paper_masthead()` honours editions/paper.json only when `custom` or
same `station`; else rewrites it (the seed had frozen the old name).
#1066: `call_pivots_contextualize` reworks the caller's random Speakerbox
pivots into the theme + current plot act before writing (mark "call pivots").

**The rhyme reading (2026-09-06 night, after the operator's deep-scan ask):**
the meaning grade alone produced DOOM-flavoured PARAPHRASE (1 of 12 aired
lines rhymed; the old spelling proof `_rhyme_pairs` refuses real bars). Now
`rap_rhyme_evidence()` (assonance on the last stressed nucleus, slant codas,
bar ends incl. comma clauses of one sentence, chain with the prior bar,
nearby internal pairs, two-nucleus pairs; grammatical/unstressed endings
never count; long lines need 2 end pairs or 3 internal) is MANDATORY under
the meaning grade ("no rhyme evidence" fault). Calibrated on the station's
own data: real bars 11/12 pass, plain source lines ~34% (long transcripts
rhyme by accident), short paraphrase fails. Prompts ask for bars split by
" / "; `_tint_out_clean` turns marks into commas and strips `*`/`_`
markdown (bold anchors DID air). Evaluator version 3 (tint_coverage_ready,
tint_output_ready, tint_recovery.py, tests) so the whole reserve re-grades.
Scan tool: scratchpad scan1064.py pattern (markers, dials, shelf census
with the detector, aired lines, side roads, pipeline tags) - reuse it.

**Cupboard view + the absolute rule (2026-09-06, last):** `GET /api/cupboard`
(memo 2s) = rounds (state/audio/cut/grade, lines with a rhyme flag from
`rap_rhyme_evidence`), writers, `_PREP_NOW`, recovery why, pipeline feed,
`_TINT_JUDGE_RING` (every `tint_evaluate` verdict, last 40). The desktop
LCD (`desktop/renderer/lcd.js`: `layoutCupboard`/`drawCupboard`) shows it
whenever `station.paused` - needs an APP RELAUNCH to load renderer changes.
Under a crystal the plain continuity pair no longer serves (no stopgap):
rhyme or silence. `tint_recovery_step` yields while the reserve is empty
and the desk is writing ("fresh rounds first"). Legacy rounds re-grade
slowly (long transcripts fail the meaning grade; whole-round ask skipped
when text+400 > reply_max_chars); the reserve rebuilds from FRESH rounds.

**Reading the LCD (2026-09-06, late):** two leaks found by reading the
cupboard: (1) `rhyme_proved = spelling OR rap` let prose with chance suffix
matches through (a transcript with " / " inserted became a READY round) ->
now rap-only under the meaning grade, evaluator v4; (2) `critical=True`
(every banked round) forced the FAST model, so the reserve's "bars" were
the 5B's paraphrase -> under the hold every road uses `tint_model_now()`
(31b while budget > 50%, else fast). Also: names check normalises "in'" ->
"ing"; `cupboard_state` shows `tint_progress` candidates with marks
(bar/cut/pending/refused), bars first, grade rhyme/rapping/old/untinted.
The cupboard endpoint is the ground truth for "what is on the LCD".

## 2026-09-07: records-only starvation under the hold (commit db2b181)
- Symptom: music only, no dialogue, no SFX, unpaused. Cause was THROUGHPUT, not a broken road: the 31b lane is serial (`_ollama_lane` Semaphore(1), runners are `-np 1`), every ask waited 170-235s in the queue, and a 12-turn round re-asked each refused bar one line at a time (up to 18 extra asks). 16 finished rounds (audio cut) sat "waiting for tint" because `evaluate_legacy` refused any rewrite whose speaker order/turn count differed.
- Fixes: `_crystal_round_repass` (refused bars of the whole-round ask re-asked TOGETHER, 2 passes, then per-line tries drop 3→2); `align_turns` in tint_recovery.py (best content-word match per original turn, unmatched extra turns keep the round owed); `_rerun_rhymes` (a call re-air plays as recorded through no gate, so under the hold it must already rap); `_call_tint_strike` resets `entry["tint"]` under the hold; dj_speak door also fires for an unchecked cached clip; the #1154 residue rule now covers "unpause" (a stray "Okay, the resume radio..." off the mic had unpaused a deliberate pause); `_sting_over_record` fires a sample 8-25s into a record when nobody speaks (SFX used to roll only inside speak_turns, so no lines = no SFX).
- Evidence rolls fast: /api/dj/pipeline and /api/dj/flow hold ~2 min / 300 events; docker logs carry none of it. Read them within minutes of an incident.
- Restart key: the Bearer for POST /api/service/restart is SPARK_AGENT_API_KEY in ~/pinevoice-stack/.openwebui.env (OPENWEBUI_API_KEY returns 401).

## 2026-09-07 (later): the air floor, the dead box, and rounds-first (commits c945a14..c427a5f)
- `/api/dj/state` box.floor / box.floor_for now name WHO holds the air floor (`_FLOOR_OWNER`); `_floor_stage()` renames it as a line moves (written / back from its tint / playing on the box). Sample it every 10s to find a starvation - it found: dj_speak took the floor BEFORE the write and the tint, so one intro/ad held the air 150s+ while waiting on the model lane. Fix: `_floor_lend(label, coro)` releases the floor around the write and the tint (single lines and the round's recording gate).
- Rounds first: `_tint_turn_yields` makes a single-line tint ask wait (≤180s) while a "tint round" ask for the same model is waiting/active; the legacy repair (`tint_recovery_step`) stands down while ≥2 tint asks wait. `dialogue_starved()` (240s without a page/box line, one live round per 300s) opens the 100%-talk shelf-only refusal.
- Firmware-down Nabu (every port refuses): `box_firmware_down_now()` = `nabu_firmware_down(_WIRE_LAST)`; `_play_on_box` declines at once, `to_box` is routed around in dj_speak / speak_turns / the record sting, `page_carries_live` carries the line, `box_hold_drain_one` does not take the floor. Only a power pull brings the box back; box.held rows replay when it does.
- The page voice feed (`/api/dj/voice` clips) is the proof a line aired when the box is dead; `last_said` stays empty for page-only lines. `docker top` gives the host PID but py-spy needs sudo (BatchMode ssh cannot).
- Evaluator `semantic.missing` / `semantic.anchors` list the content words a bar dropped; the batched re-ask (`_crystal_round_repass`) quotes them as "KEEP these words" and parses run-on "2: ... 3: ..." answers.
