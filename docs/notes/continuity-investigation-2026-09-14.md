---
name: continuity-investigation-2026-09-14
description: "#1390/#1396/#1397/#1400/#1401/#1407/#1408 - the voices stopped because System2's own output was pinned to dead slots, its 89 MB catalogue and 99 MB reservation table held the GIL, the hour re-planned itself every minute, a 684 MB store was json.dumps-ed whole, and the page turned every stall into silence. The census named bystanders; py-spy named the holders"
metadata:
  node_type: memory
  type: project
---

2026-09-14. The operator's requirement, verbatim: *"The station has to be
continuous and the voices cannot stop."* At 11:57 the panel page held ten
voice clips handed over and not started, the head one 429 s old, answered
"clip expired before playback"; `/api/deadair?hours=1` read 1,530 s of dead
air, 94% of it with the event loop blocked; `/api/pulse` read 47 stalls in
ten minutes, worst 8.0 s, "mostly outside: run"; `/api/system2/binding`
read **"18 of 18 slot(s) carry nothing. 17 of those are past their
deadline"**. The host watchdog (probe 8 s) had restarted the station at
10:26 and did again at 12:06.

Three questions, in order, each measured before it was touched. Another
session worked the same file at the same time (read_history, _embed_texts,
line_review_capture, call_log_read, the SFX set - #1391-#1395, #1398,
#1402-#1406 are theirs); the numbers here are mine.

## 1. Why the System2 hour was empty

**The 18-of-18 reading was the PREVIOUS hour three minutes before it
ended** - a spent hour reads that way by construction. The honest reading
came at 12:03 on the fresh hour: "12 of 18 carry nothing", `would_fit: 0`
on every slot, and the refusals were `slot_binding` and
`absent_from_current_inventory`:

    caller slots   495 of this road: slot_binding 297, absent 158, not-ready 37
    gallery slots  208 of this road: slot_binding 134, absent  61, too_long 10
    news slots     816 of this road: absent 564, slot_binding 249

`slot_binding` means the candidate carries a `slot_id` that is not this
slot. A sitting stamps every row it makes with the occurrence it was
commissioned for (`system2_slot`), and `_slot_matches` honoured that pin
**forever**: when the slot passed unfilled - a stalled loop, a refused
transport, a restart - the finished round stayed pinned to an occurrence
that could never be filled again, and so did every half-made row the
sitting left behind, because `prepare()` would not pick those up for any
other job either. Read straight off the store at 12:03:

    bound to slots of PAST hours, ready:     ad 8  banter 11  caller 9  gallery 3  manager 8   = 39
    bound to slots of PAST hours, not ready: ad 18 banter 10  caller 79 gallery 106 manager 21 = 234
    unbound and ready, every road together:                                                    = 28

**The hour was empty because its own output was locked in the past.** The
unbound pool of the caller road held ONE round.

Underneath it, the catalogue was an archive: 2,467 rows, 89.1 MB of JSON,
2,073 of them marked absent (median age 111 h, the oldest 15 days), 67
eligible for anything. `_sync(replace=True)` re-read all 2,467 bodies every
refresh (once a minute, and again after every sitting), decoded and
re-serialised the 2,073 absent ones to mark them absent AGAIN, rewrote
every live row unchanged (45 MB of WAL a minute), and `plan_hour` then
decoded the whole 89 MB per planned hour - 0.81 s of C decoder per call,
GIL held throughout. Bookings walked all 2,966 slot rows of six days.
`_eligible` and `can_play` decoded 87 `reserved` reservation bodies (65 KB
each) per candidate weighed - 86 of them dead leases nobody released.

And the hour was re-planned from scratch EVERY MINUTE: `s2_hours` showed
the 12:00 hour at revision 60 and the 13:00 hour at 42, +1 per refresh.
The slot prompt embeds *"THE BATTLE (#1090) ... Round 17321."* - the
battle's round counter - so `digest(templates)` and `plan_hour`'s config
hash changed on every pass; every allocation was dropped and rebuilt,
every prepare job replaced, every sitting ended in "Preparation job
ownership changed" (12:33, 12:37, 12:42 - one per sitting), and while a
System2 round was on the air the changed-config path raised
`System2Conflict` on every refresh (the transient form of
[[silent-station-needle-and-stores]]' "orchestrator stops dead").

**Fixes:**

- **#1390** `binding_live(slot_id)`: a pin is honoured only while its
  slot's deadline is ahead (the in-memory plan first, the hour in the id
  as the fallback; event occurrences keep theirs). `candidate()` carries a
  live pin only; `prepare()` neither skips a row for a stale pin nor keeps
  the stale pin when it re-commissions the row (`stamp_entry` uses
  `setdefault`). `plan_hour` decodes only rows with no blocked reason (73
  rows, 0.13 s, measured in the container); bookings come from hours that
  started inside the last four (90 slots); `_eligible`/`can_play` read live
  reservations only (SQL on `lease_until`); `candidates_by_slot` and
  `candidates_for_slot` read the pin in SQL. `_sync`: a row newly absent
  is marked; a row already marked and held by no live reservation is
  deleted (two strikes); a byte-identical live row is not rewritten. The
  runtime keeps the validated row so the store does not normalise it
  twice. `reclaim_reservations` releases dead `reserved` leases too.
- **#1400** `reserve()` with a `request_id` json-decoded EVERY reservation
  row looking for a match - and the dispatcher passes a fresh uuid every
  time, so the scan never hit and always ran to the end: **1,528 rows,
  99.4 MB, 4.14 s, on the main thread, per dispatch** (py-spy: 12 of 60
  main-thread samples under `_torrent_talk`). An indexed `request_id`
  column, added and back-filled once at store init (0.62 s), and the
  dispatcher's `reserve()` awaits `to_thread`.
- **#1408** the config hash and `config_revision` are digested without
  `prompt`. The stored slot still carries the current prompt (plan_hour
  rebuilds slots from the templates every pass); only the revision stops
  churning. Measured on the 13:04:52 boot: the 13:00 hour held at revision
  55 and the 14:00 hour at 9 across three readings spanning two refreshes.

After (12:29:53, one refresh after #1390): catalogue 396 rows / 21 MB, 0
absent, `reserved` 87 -> 0; every live dialogue slot of the 12:00 hour
allocated; `slot_binding` refusals 297/134 -> 1/0. At 13:15:51 on the
final boot: 14 live slots, 12 allocated, the two empty being recap (in
`CANNOT_PREPARE`) and the end record slot (satisfied) - **every preparable
live slot bound**; what is left refused is `adapter_not_ready` (half-made
rounds the preparer can now finish for a live slot).

## 2. Why the page dropped clips

Three laws in the panel, each written for a LISTENER page keeping step
with the world, and one on the server:

    djVoiceNext          a plain line 15 s late is "stale" - dropped
    onloadedmetadata     lateBy >= duration - "expired" - dropped; else
                         currentTime = lateBy - 0.25 (started mid-word)
    retry()              a line 15 s past its moment is not re-queued
    /api/dj/voice        a plain line is not OFFERED 20 s past broadcast_ms

A stalled loop hands its clips over late, and every one of those laws
turned the lateness into SILENCE - twice over, because the server had
already declined to offer anything older than 20 s. The device that owns
the air (`pineSoloGate`: one page sounds, every other is gagged, #1008/
#1185) has no world to keep step with; a line heard forty seconds late is
the line, a dropped one is a hole in the programme.

**#1396** (`app.py`, panel + server): `VOICE_LATE_PLAY_MS = 45000` on the
page and `VOICE_LATE_OFFER_MS` (env `PINE_VOICE_LATE_MS`) on the server,
the two agreeing. `djLatePlay()` is `!window.__pineGagged`; on the owning
page a late clip is kept up to the bound and played through from its
first word, in order, no seek; past the bound it is history. A gagged page
keeps the old law so it is in step on the day it is handed the air.
Streams (rounds) already played late through `keepWhole`; this reaches the
single lines. 45 s covers the measured stalls at p90 (36 s,
[[dead-air-has-a-named-frame]]). Verified: served page `node --check` 0
bad, pages reloaded, zero "expired before playback" acks from the owner
since; the owner is the tablet (`pblcxtg52o`, 10.89.1.154), which loads the
panel from the server and so carries the new law.

**Open (#1410, main's):** `fix/look` counted "19 clip(s) handed over and
not started, head 690 s"; the feed shows stings ringed with FUTURE stamps
(-27..-86 s; #1395's set) plus picture clips that never ack past
`received` - `djVoicePlay` diverts `clip.video` to `djVideoTv()` and inside
the desktop shell returns at `pineInsideDesktopShell()` because
`desktop/renderer/sfx-tv.js` owns the set, so nothing acks the play. Main
settles a picture-only `received` at the ack door rather than in the
renderer.

## 3. The named blockers, and what they really were

`read_history` (450 s), `<genexpr>` (450 s), `crystal_line` (223 s),
`crystal_source_contract` (163 s) in the deadair census. **Timed in the
container: `read_history` reads its 1 MB file in 0.00 s; `extract_contract`
is 1 ms warm, `compare_contract` 2 ms.** Those frames were the main thread
PARKED, waiting for the GIL, while a pool thread held it in a C call - the
census names where the main thread was standing, not who was holding the
room. So was `_gc_report` (three cheap `gc` calls, 8 of 60 samples). The
holders were named by py-spy bursts on the live process (60-80 dumps at
0.2-0.25 s; the python pid is 55, pid 1 is the sh wrapper - find it with
`readlink /proc/*/exe`; `pip install py-spy` in the container each boot):

    12:10  pool thread in raw_decode, 21 of 60 samples   plan_hour (system2.py:357), _eligible   -> #1390
    12:31  main thread in raw_decode under reserve()      12 of 60 samples                        -> #1400
    12:52  pool thread in json.dumps under _save_vectors  43 of 80 samples                        -> #1407

What WAS real on the main thread:

- `_system2_repeat_rows` -> `repeat_allowed` -> `store.can_play`, 8-9 s:
  the store lock (held for seconds by a worker's plan_hour/sync/reserve)
  and then 87 reservation bodies decoded once per round and again per
  line. Cut by #1390 and #1400; gone from the pulse top.
- `crystal_acceptance_mode()` took the learning store's lock, which the
  desk writer holds through its fsync commits; 5.5 s worst on the pulse.
  **#1397**: a 3 s memo, `air_first()` serves the last reading (the #1314
  shape). `scoped_instances()` took the review store's lock on the loop
  after every accepted bar; now lock-free (the #1070 `policy()` argument).
- `extract_contract` canonicalised the WHOLE vocabulary per call -
  `{_canonical_word(w) for w in vocabulary}` over the crystal's lexicon: 65
  ms per extract, 130 per compare with a 150k-word set, and
  `call_tint_report` asks 22 times per eleven-turn call on the loop (pulse:
  `call_tint_report` 8x/32 s, `crystal_source_contract` 7x/25 s). **#1401**:
  the frozenset is canonicalised once by identity
  (`crystal_contract._canonical_vocabulary`), and `crystal_source_contract`
  memoises by text + vocabulary identity.
- `_save_vectors` serialised `data/speakbox_vectors.json` - **683,870,963
  bytes, 40,000 chunks of 768 floats** - with one `json.dumps`, in a
  worker thread that bought the loop nothing because the C encoder holds
  the GIL for its whole run; the pulse read those minutes as "outside:
  run", worst 16.0 s at 12:46. A rebuild saved it every 25 files. **#1407**:
  `_json_write_sliced` writes the store 200 chunks per `json.dumps` call
  (about 3 MB, tens of ms) with a loop turn between slices - the output is
  byte-identical to `json.dumps` (five-case round-trip) - and progress
  saves are floored at 300 s.
- Still on the loop, not mine: `line_review_capture` (a store write with
  fsync; #1398), `call_log_read` (#1403), `pushed_sections()` (#1404), the
  httpcore failed-import stat scan (#1406), `sfx_history_add` 13.0 s and
  `gold_pick` 6.1 s (seen once each on the 12:57 boot), `_allocation_metrics`
  decoding one candidate body per allocation per `_slot_totals` call.

## Measured

    /api/pulse, 10 min           12:03 (boot 11:49)     12:36 (after #1390)   13:15 (final boot 13:04:52)
    stalls                              82                    30                    21
    stalled_s                        231.8                 106.8                  57.3
    worst_s                            7.7 (9.3 at 12:11,     6.9                   6.8
                                       16.0 at 12:46)
    "outside: run" (blind)      41x / 90.1 s          2x / 8.9 s            5x / 8.3 s, worst 1.9
    py-spy pool thread in raw_decode   21 / 60               6 / 60                6 / 60
    py-spy main thread idle            25 / 60              39 / 60               47 / 60
    watchdog probe failures           4 in the hour         1 (boot)              0

The 8-second probe is the line: every worst_s on the final boot is under
it, and the journal shows no failed probe since 13:04.

`/api/deadair?hours=1` cannot be read for an "after" today - every hour
window contains a restart (12:06, 12:26, 12:57, 13:04). The restart-free
`gap_log` reading, anchored at 13:05:30 on the final boot, is in the
closing section.

## How to apply

- `GET /api/system2/binding` on the FRESH hour, and read `slot_binding`
  against `of_this_road`: a pinned majority means the preparer's output is
  stranded - check `binding_live` before theorising about candidates. A
  climbing `revision` in `s2_hours` means something volatile is in the
  templates' hash; diff the stored `templates` across one refresh.
- When the census names a cheap function, time it in the container before
  moving it. If it is cheap, it is a bystander: sample with py-spy and look
  for the OTHER thread in `raw_decode`/`iterencode`. A worker holding the
  GIL in C does not show up under its own name on the main thread, and
  `asyncio.to_thread` does not help it.
- Big JSON goes in slices, both ways (#1392 decode, #1407 encode), and a
  store read whole by several roads is kept small and SQL-filtered
  (`json_extract` runs in C without building objects). `s2_reservations`
  is still 99 MB of history with no retention - the next lever there.
- The late-line bound is one number in two places (`VOICE_LATE_PLAY_MS`,
  `VOICE_LATE_OFFER_MS`); change both or neither.
- Never quote a rate from a window that contains a restart; today there
  were four before 13:05.

Related: [[binding-and-the-hour-shape]], [[dead-air-has-a-named-frame]],
[[event-loop-starvation-watchdog]], [[pulse-library-and-firmware-down]],
[[audio-owner-and-the-play-switch]], [[silent-station-needle-and-stores]],
[[silent-fallbacks-hide-exceptions]].

## The thirty-minute reading (final boot 13:04:52, anchored 13:05:30)

Read at the close of the window, restart-free, nothing pulled before it:

    GAP_LOG since 13:05:30 (0.51 h, restart-free): 22 gaps, 963 s dead = 1894 s/h; stall-attributed 235 s = 463 s/h
    event-loop stall         n= 15 dead=  791.8 s  stall= 231.0 s
    page join                n=  5 dead=  143.2 s  stall=   4.4 s
    mid-round hole           n=  2 dead=   28.2 s  stall=   0.0 s
    13:13:46   144s stall  14.3s event-loop stall   top=['', 'pantry_get', 'plot_read']
    13:26:23    94s stall  10.7s event-loop stall   top=['read_history', '', '']
    13:29:57    77s stall  36.0s event-loop stall   top=['_vector_meta', '_gem_cache', 'response_bank_prepare']
    13:23:48    68s stall  23.8s event-loop stall   top=['_voice_json_cached', '', 'read_te_feed']
    13:06:44    60s stall  12.9s event-loop stall   top=['<genexpr>', 'gold_pick']
    13:21:30    56s stall  26.8s event-loop stall   top=['load_settings', '', '']

Against the 858 s/h stall-attributed baseline of [[dead-air-has-a-named-frame]]
and the 1,530 s/h of the 11:57 hour that opened this note.

    PULSE now: 64 stall(s) in the last 10 min, worst 15.0s - mostly outside: run (34x, 61.4s) - past the host watchdog's 8s probe; this is what restarts the station | stalled_s 183.3 worst 15.0
    outside: run                             n= 34 s=  61.4 worst=2.8
    gold_pick                                n=  5 s=  29.1 worst=6.8
    pantry_get                               n= 11 s=  23.5 worst=3.3
    schedule_take                            n=  1 s=  15.0 worst=15.0
    _clip_seconds                            n=  6 s=  13.7 worst=4.5
    speakbox_heard                           n=  3 s=  10.5 worst=4.6
    watchdog journal since 13:04: Sep 14 13:35:29 lilspark spark-agent-watchdog[2489116]: probe 2/3 failed (no answer within 8s)
    /api/deadair?hours=1 (contains the 13:04:52 boot, so not a rate): 1767 s dead, 1440 s stall, gaps 35 | top: [('pantry_get', 351), ('crystal_acceptance_mode', 237), ('response_bank_prepare', 198), ('speakbox_vector_stats', 172), ('<lambda>', 159), ('read_history', 147)]
    fix/look: $ locate / station    on=True paused=False routed=here / page       31 clip(s) handed over and not started, 2 stall/interrupt report(s) / heard      2s ago / air        held by pbf893kebx / head       10a97e90b5, handed over 1847s ago /  / verdict    the room has only been quiet 1s / suggest    the queue is deep but nothing has failed yet - give it a moment before pulling a lever
    health: {'say': 'Reaching 3 listener(s); last heard 1s ago.', 'dialogue_quiet': 1.7, 'stuck': False, 'gagged': False}
    page acks in the ledger window: events 60 {('playing', ''): 38, ('received', ''): 20, ('canplay', ''): 1, ('error', 'The play() request was interrupted by a '): 1}
    hour hour-1789416000000 revision 9 updated 13:35:36
    hour hour-1789412400000 revision 55 updated 13:35:33
    candidates (402, 21671988)

What that says, honestly: the blockers this note names are gone from the
meter - no 12-16 s "outside: run", no `_system2_repeat_rows`, no
`reserve()`, no `_save_vectors` - and the stall-attributed rate is about
half the baseline. The loop is NOT yet clean. From about 13:20 a different
set of frames took over: `schedule_take` 15.0 s, `_vector_meta` /
`_gem_cache` / `response_bank_prepare` 36 s, `load_settings` 26.8 s (the
SETTINGS_LOCK wait), `_voice_json_cached` / `read_te_feed` 23.8 s,
`gold_pick` 5x/29 s, `pantry_get` 11x/23.5 s - and the watchdog failed two
of three probes at 13:35. Most of the 1,894 s/h of dead air is the hole a
stall leaves BEHIND it (791 s of dead air across 15 stall gaps carrying 231 s
of stall): the round is broken, the page's queue runs dry, the next round
is not banked. So the next pass is the same method on those frames: time
each in the container, py-spy for the holder if it is cheap, SQL-filter or
slice what is big, memo what is a lock. The three questions this note was
asked are answered and measured; the requirement is not yet met.
