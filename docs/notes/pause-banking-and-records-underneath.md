---
name: pause-banking-and-records-underneath
description: "#1155: why a days-long pause banked nothing after hour 5 (desk-bound finishing, larder starved by the desk, dead news counted as cover) and why resume had no music (Records-first off + torrent = record loop queued on the floor); the phone clock now takes the bank first"
metadata: 
  node_type: memory
  type: project
  originSessionId: 16fb2ec5-04cd-441b-a343-15321a690eb0
  modified: 2026-09-01T09:05:30.810Z
---

**Scan 2026-09-01 (#1155), user: "paused for days, still behind on
resume; right now silent, not even music".** Measured, not reasoned:

- **Pause timeline (pantry `at` per UTC hour):** the booth rendered
  01:33->~06:30 on 08-31 (5h), then ZERO clips for ~24.5h until resume.
  Shelf at resume: 207 callers (82 fully prepared, 78 partial, 42
  never chunked), gallery 74 (31 with audio), manager 51 (15), news 10
  (all 37-40h old = dead past `NEWS_PREP_LIFE` 3h). Larder: 7 entries =
  1 unaired + 5 already-aired repeats + the reel.
- **Why it stopped:** `pantry_keeper`'s finishing rooms only took rows
  in `committed_stock_ids(ready=False)` (the desk's picks); the desk
  binds FINISHED rows to every entry it can see, so with 82 ready
  callers it had nothing unready -> 125 half-written calls never got
  audio. `prep_one`/`prep_plan` refuse writes as "assigned" unless
  paused+`hour_short_kinds()`; `larder_keeper` had NO paused bypass
  (`commitment_write_needed("banter")` false because the desk counts
  aired repeats as stock) -> one fresh banter round after 30h.
  `hour_needs` counted dead bulletins as held (no age term) -> news
  never short, never rebanked -> live 8-stretch news segment at resume.
  #1150's resume shift for news looked for `prep_news_at` on the ROW;
  it lives on the ENTRY -> no-op.
- **Why no music:** `dj.records_first=false` + `talk_radio_mode=true`:
  `_dj_loop` awaited `_record_talk` INLINE (no `intro_only`, `_room()`
  = 1e9) while `_torrent_talk` ran rounds; both need `_FLOOR_LOCK`.
  Measured 62 min past the end of a 254s record, four tasks queued at
  `_floor_take`. Recording room: cohost 216 of 228 takes LIVE (5% from
  shelf) in the hour after resume.
- **Live-write roads that ignored the bank:** `caller_clock`
  (`callin_per_hour` 12) called `dj_call_generated` only; only the
  sheet's phone entry (`dj_caller`) ever took from the 82 banked calls.
- Refuted on the way (do not re-chase): shelf `cast` label mismatch
  (`cast_signature()` equals the stamp; takes ARE the XTTS air cast),
  `_larder_current` profile drift (one profile across 349 rounds),
  caller contract version (all v7, quality ok).
- **Routing:** music/voice/reply were `here` since 08-31 00:52 UTC,
  moved by `10.89.1.13` UA `node` (desktop app main process) per
  `GET /api/routing/moves` (#1029 ledger). Not the mic. Nabu satellite
  was unavailable at scan time anyway. Left as found; told the user.

**#1155 invariants (deployed 2026-09-01, do not undo):**
- Talk-radio mode => needle drops first even with Records-first off
  (`spin_first` forced in `_dj_loop`; the spawned branch already did
  `intro_only=torrent`).
- Paused: `_pause_unfinished_rows()` (5s memo) keeps the keeper awake
  past "covered", and `_bank_all` lets every finishing block take ALL
  viable rows (dead news excluded via `_news_row_alive`).
- Paused: `larder_keeper` writes until UNAIRED viable rounds reach
  `_want` (reserve target x prepare hours) under `larder_cap`.
- `hour_needs` skips news rows past `NEWS_PREP_LIFE`; resume shift
  steps `entry["prep_news_at"]`.
- `workshop_tick` yields while unfinished rows exist.
- `caller_clock` -> `dj_caller(now, shelf_only=True)` first, generated
  call as fallback.
- Paused keeper slice floor 120s (was 15s = 3240s room / 212 rows ->
  one line per visit, a round took ~26 passes).
- `_torrent_talk` re-checks `radio_paused()` after its breath: the
  controlled pause test caught it taking a banked gallery round 11s
  INTO the pause (shelf_take marks it aired; nobody hears it).

Verified after deploy: new record dropped within ~60s of restart,
`_dj_loop` in `_hold`, banked caller "Rhonda" aired off the shelf.
Controlled 134s pause: 11s in, "(#1155) off air with 212 written
round(s)..."; x-ray showed pantry_keeper->recording_sitting->
larder_prepare->voice_render_any and larder_keeper->dj_banter->
ask_model; resume aired the reel (139s) and dropped a record.
Diagnosis method that worked: pantry `at` histogram per UTC hour,
`/api/debug/tasks` for the floor queue, `/api/recording-room` actors
shelf-vs-live counts, `/api/routing/moves` for who moved routing.
See [orchestrator-judgment-book](orchestrator-judgment-book.md), [resume-reel-and-shelf-burn](resume-reel-and-shelf-burn.md),
[hour-contract-two-truths](hour-contract-two-truths.md), [floor-and-paced-air](floor-and-paced-air.md).
