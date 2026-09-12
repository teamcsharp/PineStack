---
name: rejection-deep-scan-and-stack
description: "2026-09-08 night: the five-agent deep scan of the rejection queue (the hint was lying, the near reading, read-plain passages, the queue drains itself) and the measured stacking bottleneck (the deep tint lane, 12 rounds/h vs 44 asked)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T02:37:37.473Z
---

**The operator's standing goals (2026-09-08 night):** drive the cut lines toward ZERO, and keep the
station "stacking dialogue and making the rhetoric continuous without fail".

**THE BOTTLENECK IS THE DEEP TINT LANE — measure before changing anything else.** The air asks for
~44 ready rounds an hour (3,180 s of speech at talk 100). The lane makes 8-12 (3.6-5.4 min wall per
round; one decode slot; the deep model on every line under the hold because `tint_budget` takes
`share = max(share, 0.9)` there, so `tint_model_now` never falls to e2b). The recorder is 23% busy
(XTTS 1.43x real time, could do 45 rounds/h); the writer scripts 5 rounds per round the lane can rap
(85-87% round-level task failures). GPU 86-96% in every sample. Pause banks 261 s of air per hour
(one tinted round every 16 min). Talk share achieved unpaused: 16-33% against the 100% dial.
Where the lane was going: 174 deep answers on the phone road for ZERO ready calls; 25 min on recaps
that were off brief; ~220 refused fast-lane asks/h on the Gazette (335 of 600 recent notes).
Dials the operator can turn (not code): judgment `prefer_road`/`drive_road` off caller + drop the
2.0x caller/news factors (+10-15 rounds/h); `reuse_rest` 3 h -> 1 h (59 kept rhymed recorded rounds
then carry ~65 min/h instead of ~22); `paper_hourly` off while short; System2 `generation_turns`
6 -> 8-10. A second decode slot is measured at 0.96x — never.

**What the readers were getting wrong (measured, not guessed):**
- `rhyme_options_for` picked suggestions with `_rap_slant`, whose vowel classes merge heat/bed and
  whose igh/ow digraph rules are dead code: **1,205 of 1,884 hint suggestions were not rhymes** and
  all of them PASSED the grader (same reading). Fixed: `crystal_rhyme.rhymes_with` (CMUdict) decides.
- 12% of refused bars rhymed to the ear: `terminal_near_rhymes`/`near_tails` (same final stressed
  vowel; codas equal after voicing/manner folding, or differing by one NON-LIQUID insertion) now
  count. L and R must NOT fold (calm K AA L M / harm H AA R M is a pinned refusal) and two
  fragments of <=3 words still need a full coda.
- `_rap_untag`: a vocative tag ("...against decay, man") hid the landing on 9 rows.
- Meaning cuts were FORM checks: rhetorical negation frames, inner questions, the station name,
  descriptive openers, the caller's introduction regex.

**The queue was mostly moot** (199 tint rows): 114 rounds gone, 39 accepted-without-the-line, 19
already carrying an accepted bar (the supersede gap: `_crystal_round_repass`'s accept and the
`_prior`/resume branch never called `line_review_supersede`), 22 older duplicates, 13 struck out, 12
made by the operator's own recoveries (`build_recovery` re-tints the WHOLE round -> new cuts on
neighbours; now `prior_ok` neighbours are not re-graded). Nothing drained the queue but the operator;
now `line_review_regrade_pending` runs every 10 min and notes `round_gone`/`superseded`/`read_plain`.

**Shipped (deploy + commit 5da539a, 2026-09-08 ~20:30 CST; queue 273 -> 90 in two sweeps, ready
rounds 58 -> 77, schedule short 5 -> 0, pulse stalls 19 -> 5, zero tracebacks):** `_tint_plain_passage` (a verbatim
passage >=300 chars / raw / mid-word stub is READ PLAIN — #838 says the operator's documents are not
reworded and the tint was the last door that did); `_verbatim_turn_text` at the full-swath and
seed-put-back doors; `_harvest_window_start` + `_gem_is_stub` (this is where "Mfortable." and
"Sgard." were born: the 5,000-char window started at a random CHARACTER offset); brief BEFORE tint in
`ensure_entry_tinted`; `_cut_caller` (a cut HOST line no longer kills a call); `call_flow_report
(soft_quality=)` — a rapped call's three richness legs are advisory; banter banks past the
two-round gate while paused; `reflection_gather` off the loop (it stalled the station 23 s and the
host watchdog restarts at 8).

**THE DIALS WERE SET AND TESTED (20:25-21:00 CST, commit c4b9d9d):** judgment off caller/news
(`POST /api/orchestrator/judgment {"road":...,"move":"drop"}`), `prefer_road`/`drive_road` unpinned
and `reuse_rest` 10800 -> 3600 in `data/orchestrator_policy.json` (NOTE: `_ORCH` is loaded once, so
a policy-file edit needs a restart; `shelf_rest_now()` was already 3600 because `repeats_hard` is on
- the 3 h number was gating the COVER pool at `shelf_reuse_rest()` line ~39593, which is why misses
read "no cover aired"), System2 `generation_turns` 9, `paper_hourly` false in `data/settings.json`
(mtime-cached, picked up live). Backups in /tmp/dials. NONE of these are in
`_larder_profile_signature` (reply budget, turn range, swath dials, crystal, plot act), so no stored
round is invalidated.
**Two lessons from the test:** (1) THE STATION RE-PINS THE PHONE ROAD ITSELF within minutes
(`orch_apply("drive:" + road)` at ~37746 and its own `judgment_move(...,"more")`) because the sheet
asks for 4 calls an hour and none had aired - the pin was starving because no call could ever be
READY, so the cure is the contract, not the dial. (2) A VERDICT A ROUND STORES ABOUT ITSELF NEEDS A
ROAD THAT RE-READS IT: five fully rapped calls (11/11 bars) stayed non-viable after the contract
changed because `call_entry_regrade` only runs inside `ensure_entry_tinted`, which only runs when
the row is prepared, and a non-viable row is never prepared. `call_entry_recheck()` (deterministic,
6 rows a pass, on the 10-min regrade clock and the regrade endpoint) recovered 5 of 6 - 55 rapped
bars; the sixth was correctly held for "tint turn 3 lost a name".

**Method that worked:** five parallel subagents, each with a read-only local snapshot
(`rej3/pending.json`, `noted.json`, the stores, `rej3/live/*` from `/api/*` + `data/*`), the offline
grader (`SPARK_AGENT_DATA_DIR=<scratch> PYTHONPATH=<work> python`, `app.tint_evaluate`), a shadow
copy of a module first on PYTHONPATH for prototypes, and a brief demanding counts + 5 verbatim
examples + a measured effect + the pinned tests. **Subagents cannot write report files** — they
return the report as text; save it yourself. Reports live in `rej3/{rhyme,meaning,sources,drain,stack}/report.md`.

**Why:** the operator's product is an endless rapping station; every refusal that is the reader's
fault costs three deep asks on the one lane that gates the whole stack.
**How to apply:** before touching a grader threshold, ask which READER refused and whether the ear
agrees; before adding lane work, price it in rounds/hour against the 8-12 the lane has. See
[repertoire-dead-air-lcd](repertoire-dead-air-lcd.md), [tint-yields-to-air](tint-yields-to-air.md), [request-book-lanes-strikes](request-book-lanes-strikes.md).
