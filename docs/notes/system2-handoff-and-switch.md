---
name: system2-handoff-and-switch
description: "#1068/#1069/#1070 (2026-09-08): the Codex hand-off (uncommitted System2 + rhyme + rejection work), the watchdog restart it caused, what was finished, and how System2 now drives the station (fallback + keepers dials)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-08T10:46:22.161Z
---

**The hand-off (2026-09-08 ~00:26 CST):** a Codex session (GPT-6 Astra) resolving #1068/#1069 ran out
of credits mid-task with EVERYTHING uncommitted: app.py modified (+6.6k lines), ~20 new modules
(system2*.py, rhyme_assistance.py, prompt_learning.py, rejection_*.py, line_review*.py, crystal_*.py,
nabu_audio.py, sfx_*.py), `vendor/` (CMUdict + WordNet, 31 MB, REQUIRED at runtime by
rhyme_assistance/crystal_rhyme), ~120 tests, ~50 tools, ~30 docs and ~200 MB of docs/*.json evidence.
Its own final test run was SIGTERMed. The inbox request #1070 = "finish what GPT left". Four
subagent audits are in the session scratchpad (system2-audit.md, rhyme-rejection-audit.md,
cache-scripts-audit.md, code-health.md) - reuse that shape: one agent per subsystem, read-only GETs,
file:line evidence.

**What the live station showed (do not re-derive):**
- The host watchdog restarted spark-agent at 00:36 CST: `crystal_prompt_contract` ran
  `rhyme_assistance.assist()` (SQLite/FTS/regex, 2-5 s) SYNCHRONOUSLY on the loop, 5+ times per source per
  round; `/api/orchestrator/rejections` ran `LineReviewStore.summaries` (`SELECT *` on a 655 MB DB) on the
  loop for the panel/LCD polls. py-spy on the container (`/proc` PID scan; no pgrep/ps in the image)
  named both. Fixed: `crystal_prompt_contracts()` (to_thread + 10-min memo), review reads in threads,
  slim summary SQL with json_extract, `policy()` lock-free (a thread holding the store RLock stalled the
  readiness path 3.6 s), System2 status built+serialised in a thread, WAL checkpoint after the rhyme import.
  After: 8 stalls/26 s per 10 min (boot window) vs 43/99 s; the review page 243 ms.
- Rhyme index: built (132,962 phones / 117,659 senses / 206,941 lemmas) but neural vectors 8/117,659 -
  the warm loop only runs when no model job is active, which never happens. `/api/tint.rhyme_assistance`
  now reports it. A bulk warm at a quiet hour (~20 min of nomic-embed-text) is still owed.
- The "looping" the listener hears = 4 continuity pairs aired 71-87x/day with no gate. Now 14 pairs,
  1-hour rest per line (`CONTINUITY_REST_SECONDS`), refused lines retried after 10 min instead of blocking.
- Cache: never cleared; rows road-bound not slot-bound; `repeats_hard` (the station's own judgment)
  zeroed the reuse rest -> now `shelf_rest_now()` floors it at 3600 s; `stock_expires_at()` is the one
  expiry clock (stamped `expires_at`, honoured in `dialogue_stock_items._viable`); `stock_used_by()` beside
  `aired_at`. A TOTAL wipe was NOT run: `POST /api/cache/purge areas:[larder,shelf,takes,pantry]`.
- `crystal_demand` (style-level text) was dead since the shared prompt builder -> `crystal_prompts._demand`.
- Rhyme Cloud (🎤, PINE_3JS + renderer THREEJS_VIEWS): `GET /api/crystals/{id}/rhymes?mind=&file=&start=&span=`
  (DOOM: 36,623 landings, 10,731 words, 3.4 s cold in a thread, memo 10 min).

**The GIL lesson (measured after the switch, do not re-learn):** `asyncio.to_thread` does NOT free the
loop for CPU-bound Python or C-`json.loads` work - with 5-8 busy ThreadPoolExecutor workers the main
thread loses most GIL contests and the pulse shows 2-3 s freezes at random main-thread frames
(`load_settings` was the scapegoat). Dense py-spy (`pyspy_gil.sh` in the scratchpad: 60 samples at 0.4 s,
print threads marked `active+gil`) named System2's refresh (`include_drafts` → `candidates_for_slot` per
slot decoding every body; `plan_hour`). Cure = do LESS work: `candidates_by_slot` (one decode per hour),
refresh 60 s, no deepcopy for the status poll. `plan_hour` (system2.py ~315) still decodes the whole
candidate table per planned hour - next lever is a decoded-row cache or pruning absent candidates.
Read `/api/pulse` first, then sample the GIL holders.

**Measured at the end (build 4, 08:46Z restart):** pulse 6 stalls/21.7 s per 10 min of which 11.9 s is
the one-time boot `_load_vectors` (was 43/99 s at the start); worker GIL holds 7/60 samples (was 26/60);
System2 preparer cycling with errors=0, 11-12 allocations, 138 s heard; /api/orchestrator/rejections 243 ms.
Commits 2d2cc97 (the whole hand-off + tonight) and 80f7849 (refresh cost). #1068/#1069/#1070 resolved.

**System2 now drives the station (the operator's order: default and swapped in):**
- The default is carried by `data/system2-config.json` (`POST /api/system2/settings {"engine":"system2"}`
  writes it; it did not exist before). The CODE default stays `legacy` on purpose: flipping it made bare
  runtimes in test hosts prepare/dispatch for real and hung the suite. Rollback = `{"engine":"legacy"}`.
- Two dials, both default True: `fallback` - `_torrent_talk` lets the legacy chain serve the running
  occurrence when `fallback_due()` (no undelivered verified allocation, nothing of System2's on the air);
  `legacy_keepers` - pantry/larder keepers keep writing (`owns_preparation` gates them, not `enabled`).
- `prepare()` renews its lease every 600 s (was discarded at 1800 s). `_system2_acknowledge_row` swallows
  ledger conflicts (a reused receipt id raised into the page ack).
- Still not built: mid-performance interrupt/resume for call-ins (`suspend`/`resume` unused), gating the
  four legacy clocks (caller/ad/upstairs/news) onto the plan, segment-correct binding of legacy rows.
- `_ready_slot_window` reads `_system2().enabled`; any test fixture that patches `_system2` with a bare
  Mock must set `enabled=False` or ready rounds stop fitting (fixed in test_ready_stream_playback.py and
  the Ledger stub). `test_system2_clock.py` needed `ast.fix_missing_locations`.

**#1071 (same night): the Gazette "fails to tint"** = `paper_tint_story` asked the 31b tint lane (two
permits, all the dialogue's) → `WritingDeferred` in ~9 s per paragraph, charged as an attempt, logged as
"rewrite not accepted" (74 eligible / 60 attempted / 8 accepted per edition). Fix: `crystal_line(...,
model=)` pass-through; the paper asks `tint_fast_model()` (e2b, its own lane) with `kind="paper"`, waits
out deferrals without charging the cap, records why. Any road that tints with the deep model under load
will show this same "deferred = failed" shape - check `/api/paper/{id}` `articles[].meta.tint.paragraphs[].faults`.

**#1075/#1077 the paper's rule = the dialogue's rule:** every Ollama runner is `-np 1` (one ask at a
time per model; `ps -eo args | grep llama-server`), so ~80 paragraphs cannot tint in 10-20 min. Under the
hold the press holds the edition up to 45 min (`paper_tint_caps`), re-asks refused paragraphs sentence by
sentence (`crystal_line room 3`), skips accepted ones (`done_keys`), and `paper_tint_cut` cuts what never
passed before print (first paragraph + Q/A kept). Real throughput lever = OLLAMA_NUM_PARALLEL on the host
(needs an ollama restart mid-show) + `_ollama_lane` cap. Seven more inbox requests (#1072-#1078) arrived
04:03-04:20; four deep agents were dispatched (audit-1074/1075/1076/1072 in the scratchpad).

**#1074 (System2's real blockers, measured 04:26-04:50):** (1) ONE malformed candidate (duplicate line
ids) raised in `sync_candidates` and aborted refresh/prepare/dispatch entirely - now validated per row in
`inventory()`; (2) every restart orphaned the working job for the 1800 s lease - now `reclaim_jobs` at
startup + 900 s lease renewed every 300 s; (3) dispatch reserved rounds `_ready_round_fits` then refused
(17 reserve/release cycles in 90 s) and `fallback_due()` stayed False meanwhile - now a fit pre-check +
recorded refusal reason; (4) MY `stock_expires_at` (24 h burn) hid 6,400 s of verified never-aired rounds
(`candidate_expired` is silent in the store) - now unheard rows live 3 days and the runtime says
"Past its expiry" in `why`. Still open: a third tint permit for schedule-critical System2 work; the
keepers produced all six rounds System2 aired. Patches: scratchpad/patches/1074-*.diff (95/95 green).
**#1072/#1073:** panel `pineWin(key,title,opts)` = the one movable/resizable frame (geometry in
localStorage `pineWin:<key>`); every PINE_3JS entry opens in one; desktop `THREEJS_VIEWS` mirrors PINE_3JS
(24 keys); desktop Scheduler tile `#schedCell` + `⧗ Scheduler` rail (renderer.js) → needs an app relaunch.

**#1075/#1076/#1078 (rejections, measured on 6 h / 1,090 refusals):** 30% were SIX lines of one caller
script retried forever (no per-source strike cap - still the biggest open lever); 17% evaluator false
refusals (clock times, "PM" as a name, "the only thing"=1, filler negations, unmarked transcript questions,
rap landings on stop words / silent-e / final -y) - ONLY the clock/PM fix is deployed (1075-a); the
1076-1 rap-landing and 1076-3 contract patches were REVERTED: they break 17 existing fidelity tests
(changed-name refusal, question word order, unknown opener, "one thing" count) - reconcile rule by rule
before re-applying; 1076-2 journal dedupe reverted too (silences the first editorial record). NOTE:
`tint_coverage_ready` uses a separate MINIMUM version, so a grader bump does not wipe the reserve.
Phantom rows (a refused turn hands back the SOURCE and crystal_line graded it against itself) - fixed
(`_crystal_line_refused`, `report=` out-param);
the learner never fired (75% trigger vs one-exposure-per-source metric, cohorts reset by version bumps) -
now attempt-level + pooled + 10% trigger. Patches scratchpad/patches/1075-*.diff, 1076-*.diff.

**Where the night ended (05:50 local):** commits 2d2cc97, 80f7849, ab330ec, 0e5b5fd, d7f016a, 3dea666,
92806b5, 4fdc2e6 on master (host repo); eight restarts, all via tools/deploy-at-radio-gap.py; inbox
#1068-#1078 resolved; #1079 (a paged request/reply journal with token costs, HTML + 3JS flowcharts, top-
right icon), #1080 (what System2 needs to satisfy the screenshot's requirements), #1081 (online research on
system prompts/LLM use for System2), #1082 (learn from every rejection, "no mistake denied twice" = the
per-source strike cap) were still OPEN. Known noise: `_record_talk` lets WritingDeferred escape a
fire-and-forget task ("Task exception was never retrieved") - wrap it. The desktop app needs a relaunch
for the renderer changes (Scheduler tile, 3JS list parity).

**How to work here now:** the Bash tool HANGS (cwd on the SMB share) - use PowerShell; robocopy the repo
to the scratchpad (exclude data/, node_modules, docs JSON >1.5 MB) and edit a `work/` copy; deploy with
scp to `~/pinevoice-stack/spark-agent/` on the host (seconds) then `tools/deploy-at-radio-gap.py
--restart` on the host (restarts at a quiet handoff, records docs/*-restart.json); git on the host, not
over SMB. Tests: pytest per-file batches with an isolated data dir and a LOOPBACK-permitting socket
guard (asyncio's self-pipe needs 127.0.0.1); expect Windows-only noise (TemporaryDirectory on open
sqlite handles, 8.3 TEMP paths in test_sfx_pool_warm). Big pytest batches leak patches between files -
re-run a failing file alone before believing it. docs/*.json|png|jpg are now gitignored (evidence stays
on the share like data/).
See [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md), [pulse-library-and-firmware-down](pulse-library-and-firmware-down.md), [tint-yields-to-air](tint-yields-to-air.md),
[pine-inbox-workflow](pine-inbox-workflow.md).
