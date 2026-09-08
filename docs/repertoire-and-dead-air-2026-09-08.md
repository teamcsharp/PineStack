# The repertoire, the dead air and the screen (2026-09-08)

Three rules from the operator on the afternoon of 2026-09-08, each read against the code by a scan of
the station's stores, its silence paths and the Pine Box LCD, and each changed the same day:

1. *Tinted rhetoric should not expire for 96 hours. Once it is rhyming, I need that stored and played
   and added to the repertoire.*
2. *I want dead air always being punctuated with SFX clips. If there is a period of dead air, let the
   SFX attempt to fill it with clips and keep the momentum going.*
3. *The LCD text is scrolling incessantly despite there being no activity … I need it to accurately
   reflect what is actively playing.*

Numbers are **[V]** (read from the code or a ledger) unless marked **[I]** (inferred).

## 1. What expired, before

| store | rule | value | knew the round was tinted? |
|---|---|---|---|
| larder (banked banter) | a round past `larder_fresh()` is pruned every 3 s unless it is an aired repeat inside 72 h, or the station is paused and it is unheard | `max(1200, pantry_life())` = **90 min** | no |
| larder | every append trimmed to `larder_cap()`, oldest first | 14 × hours dial | no |
| larder, on take | popped after its innings, or at once if not repeat-safe | banter **3** airings | no |
| shelf (ready rows) | `stock_expires_at`: unheard → 72 h, aired repeat → 72 h from creation, news → 3 h | 72 h | no |
| shelf | burnt past 24 h when `resort_may_drop` allows (aired, not a last-resort) | 24 h | no |
| pantry (rendered clips) | a clip past `pantry_life()` is deleted on take unless something viable holds it | **90 min** floor | no |
| pantry | row ceiling 600–4,000 and 6 GiB: loose clips first, then held clips oldest-first | 600 × hours × 1.5 | no |
| cache purge | `shelf` = clear, `larder` = clear, no protection at all | – | no |

The only tint-aware lifetime rule in the file went the other way: `tint_exhausted` retires a row after
twelve refused answers **[V]**. An unaired round that had cost minutes of the deep lane died at ninety
minutes if the station was on air; its clips died at ninety minutes on the next take **[V]**.

## 2. The keep (rule 1)

`tinted_keep_until(kind, row)` stamps `keep_until = first seen tinted + TINTED_KEEP_SECONDS` (**96 h**,
env-settable) on the row and its entry the first time any expiry question is asked of a row that
`dialogue_tint_ready` accepts. Nothing is stamped for news (a bulletin dies with its stories), for a
plain round, or while the crystal is off (nothing rhymes); a stamp written while the crystal was on
stands after it is turned off, because the round *was* rhymed.

Every clock and predicate reads the stamp:

| where | now |
|---|---|
| `stock_expires_at` | `max(the old clock, keep_until)` – the planner, the cupboard and System2 read one number |
| `resort_may_drop` | a kept round may not be dropped – which guards `shelf_take`'s burn, its tail rebind, the burn sweep and `alt_shelf_trim` |
| larder prune, disk restore, `alt_larder_index` | a kept round is not stale at 90 min |
| `larder_trim` (replaces `del _LARDER[:-larder_cap()]` at both appends and the restore) | the larder holds `larder_cap()` rounds of **stock** plus the **repertoire**, bounded at `TINTED_KEEP_ROWS` (80); beyond it the oldest-aired go first and an unheard round is the last to go |
| `larder_stock_count` (the writer's cap) | a resting kept round is not stock: it never stops a fresh round being written beside it |
| `row_innings` | a kept round has the **evergreen** innings (12, plus the operator's bonus) instead of banter's 3 – read at `shelf_is_repeat`, `shelf_take`, the tail rebind, the cupboard listing, the schedule's `remaining_airings`, the gap cover's stock pick and the larder's burn-on-take |
| pantry row ceiling | rises to `held clips + 300` so a 96-hour keep of clips is not evicted by a ceiling written for a ninety-minute cache |
| `POST /api/cache/purge` | `shelf` and `larder` spare kept rounds and report `shelf_kept` / `larder_kept`; `{"force": true}` wipes them too |

Untouched on purpose: the **3-hour rest** between airings (`SHELF_REUSE_REST`, the operator's own
number – a longer life is not a shorter rest), `repeat_safe` (a call or memo that names the hour still
may not come back), the `_larder_current` contract clause (a cast or crystal change still retires a
round written under the old one), and callers' single-use FIFO with their own 6–10 h re-air window.

Where to see it: `/api/dj` → `dialogue_flow.repertoire` (kept / aired / unaired / resting / soonest
free / keep left, per store) and `resort_state()["repertoire"]`; the cupboard listing marks
`kept: true` and shows `of: 12`.

## 3. The gap filler (rule 2)

Before: silence was answered by `dead_air_watch` dropping the needle on the next record; the talk gap's
cover (`cover_the_gap`) went continuity reserve → shelf banter → a **live TTS render**, which extends the
hole it covers; a floor held for a slow render (#1146) was a silence neither watchdog could touch; the
~23,000 pre-rendered samples and the SFX Guy's recorded liners were never drawn from any silence path
**[V]**.

`sfx_fill_gap(why, under_floor)` puts out a clip that already exists – the SFX Guy's prepared station
liner off its shelf on every other turn when he has one (the pantry serves it, nothing renders), else a
short sample off the pool through `dj_sting(force=True)` – never over a voice, never while paused, and
resting `SFX_GAP_REST` (9 s) or the operator's `sfx_gap` dial, whichever is longer. It is called from:

- `dead_air_watch`: every 20-second tick the room has been silent more than 12 s (well before the
  dead-air strike), and the strike itself still kicks the next record;
- `cover_the_gap`: after the continuity reserve fails and **before** the live render, which still
  follows – the clip buys the render its time; and as the last resort of the constant-talk branch;
- `talk_watch`: when the floor is held for a render that has not started playing and the talk gap is
  past its limit – a sample only, because a liner would take the floor and queue behind the round.

`/api/dj` → `dialogue_flow.gap_filler` shows what last went out and why (count, turn, last reason);
the pipeline log line is *dead air punctuated with a sample/liner*.

What stands down on pause and should: both watchdogs, the sting over the record and the filler – a
pause is silence on purpose. What keeps building on pause (unchanged): the larder keeper to its full
cap, the recording room in parallel, the resume reel, the response bank, the SFX Guy's ready bank and
the continuity reserve.

## 4. The screen (rule 3)

The LCD reads `/api/dj` once a second and computes the correct "now" pointer from `stream_now` and
`speaking_now` – but when that pointer was null (nothing on the air) the drawing code fell back to the
**five newest feed rows** (booth activity, recorded/waiting) and panned them on the **wall clock**, so
the text scrolled and jumped while nothing was said **[V]** (`desktop/renderer/lcd.js`).

Now the dialogue page shows the line being spoken, panning on that line's own clock; when it ends the
line is held for six seconds (its tail is still in the room) with the pan frozen, then the screen goes
idle and says why: *Paused · nothing is being said*, *♪ artist - title* while a record spins, *Off the
air*, or *On the air · nothing is being said*. The feed never scrolls on its own again. The paused
cupboard page and the newspaper page keep their own reading scroll; they are pages the operator chose,
not the dialogue feed. The desktop app must be relaunched to load the new renderer.

## 5. Pinned

`tests/test_repertoire_keep_2026_09_08.py` (the stamp, the clocks, the innings, the larder holding the
repertoire beside its stock, the unheard round last to go, the status), `tests/test_sfx_gap_fill.py`
(a sample that exists, the rest, never over a voice or while paused, the held floor, the liner
alternating, the operator's dial), and the LCD agent tests (`tests/test_lcd_agent.cjs`, 25 green).
