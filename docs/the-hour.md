# The hour: the schedule and every act in it

What one hour of Pine Box FM is made of, read from the station itself on 2026-09-08 (the live
running order in `data/schedule.json` as System2 planned the 09:00 hour, the dials in
`data/settings.json` → `dj`, and the hour's ledgers). Where a number is a measurement it names its
source; the code that runs each act is named so the next reader goes to the source.

## 1. The running order (the "canonical hour", 20 entries, 60 minutes)

The sheet is the operator's own (#843): twenty entries, sixty minutes, and the last one wraps the
clock back to the top. It lives in `data/schedule.json` (the panel's schedule editor; defaults in
`CANONICAL_HOUR`, app.py ~42273). Every entry is one of the `SCHEDULE_KINDS` — nothing on it is a new
kind of show, it is the shows already in the building put in an order somebody chose.

| # | at | kind | entry | min | the standing instruction (what the writer is told) |
|---|---|---|---|---|---|
| 0 | :00 | news | News coverage | 4 | Cover it like two people who actually read the story; react as yourselves, never as a wire service; back to the music before it turns into a lecture. |
| 1 | :04 | record | Spin record (start) | 3 | The top of the hour: the needle goes down and the record gets the air. Not a round — the end of one. |
| 2 | :07 | gallery | Painting selling | 3 | Sell the painting off what you can actually SEE in it: describe, argue, a ludicrous price, first caller takes it. |
| 3 | :10 | ad | Ad read | 2 | Read it like the best thing in the world and only slightly embarrassed; name the product, what it does, land the price. |
| 4 | :12 | banter | Banter during recordings | 3 | Talk to each other, not at the listener; every line answers the one before; they talk OVER the record. |
| 5 | :15 | manager | Angry messages from upstairs | 2 | A memo, not an order; read it out, react honestly; this one is a rocket and the pair take it standing up. |
| 6 | :17 | caller | Call | 4 | The request line: find out what they want, read it back, take the mickey affectionately, cut to the record. |
| 7 | :21 | caller | Call with banter | 5 | The caller is a person with a reason for ringing; let them finish, dig in, let the call ARRIVE somewhere. |
| 8 | :26 | ad | Ad read | 2 | as above |
| 9 | :28 | track_talk | Talk over the record | 3 | An intro written for THIS song and a send-off after it; the record has the air. |
| 10 | :31 | caller | Call with banter | 4 | as 7 |
| 11 | :35 | gallery | Painting selling | 3 | as 2 |
| 12 | :38 | ad | Ad read | 2 | as 3 |
| 13 | :40 | news | Different news story | 4 | A DIFFERENT story from the one at the top of the hour — not the same lead said twice. |
| 14 | :44 | banter | Banter | 3 | as 4, without the record underneath |
| 15 | :47 | caller | Phone call | 4 | as 6 |
| 16 | :51 | gallery | Painting selling | 3 | as 2 |
| 17 | :54 | manager | Message from upstairs | 2 | as 5, without the anger |
| 18 | :56 | recap | Recap on the hour | 3 | Take stock of the hour that just went out: what played, who rang, what sold, what came down from upstairs; two moments, a joke on each, back to the music. |
| 19 | :59 | record | Repeat (end) | 1 | The hour wraps here and begins again at the top. |

Per hour that is: 2 news bulletins (8 min), 3 painting rounds (9), 3 ad reads (6), 2 banter rounds
(6), 2 memos from upstairs (4), 4 calls (17), 1 talk-over-the-record (3), 1 recap (3) and the two
record markers (4) — **56 minutes of entries that need words and 4 that do not**. The coordinator
reads the same sheet as "the running order asks for 50 min of written speech an hour"
(`/api/coordinator/capacity`; the track-talk entry is music with two tinted bookends, not three
minutes of speech). The defaults in code differ from the live sheet in two places: the code's
entries 7 and 10 are `banter_caller` (a whole generated caller) and its entry 9 is "Banter without
caller"; the live sheet runs three `caller` entries and a `track_talk` there instead.

## 2. The acts, one by one

Every act is written plain by the writer model (gemma4:e2b), rewritten through the crystal by the
deep model (gemma4:31b, the hold on, every line a bar or cut), rendered by the recording room (XTTS,
the hosts' cloned voices), and only then counts as READY (audio and tint verdict both in). The
"cost" is the station's own measurement of what one entry takes to build (`/api/orchestrator/logic`
→ `roads.<kind>.cost`, seconds of writing-room time, 2026-09-08 09:11).

**News coverage** (`dj_news`; cost 342 s; the news keeper). The pair take the wire: headlines
pulled live through SearXNG, the lead story dug into and reacted to. `news_hourly` puts the bulletin
on the hour; `news_every` 8 adds a loose story between records. A bulletin has a prep life
(`NEWS_PREP_LIFE`) — stale news is not aired. The second bulletin at :40 must be a different story.

**Spin record / Repeat** (`dj_skip`; no words). Not rounds: the markers where talk stops and the
record has the air. Records play whole (`records_whole` on) and, with `records_first` OFF as it is
today, the pair finish their round before the needle drops rather than introducing it over the
opening.

**Painting selling** (`dj_gallery_round`; cost 439 s; the gallery keeper). ComfyUI paints; the pair
describe the painting from its actual pixels, argue over it, price it absurdly and hawk it. Three
times an hour; `gallery_ads` on folds an advert into the pitch.

**Ad read** (`dj_ad_break`, `dj_ad`; cost 273 s; the shelf keeper). A stored read, a sponsor
(`sponsors`, one today), or a fresh spot bedded in the station's own music (`ad_bed_pct` 30). Three
on the sheet; the clock adds more: `ad_every` 2 (an ad every two records) and `ad_minutes` 10 (at
least one every ten minutes whatever the records do); `random_ad_pct` 8.

**Banter** (`dj_banter`; cost 108 s — the cheapest words on the board; the larder keeper). The pair
talking, seeded from the speakbox (a swath of one of the operator's documents underneath,
`speakbox_rate` 1.0, prepend 0.86, full swath 0.45 up to 3000 chars). 8–11 lines, one to two
minutes (`banter_min/max_lines`, `banter_min/max_minutes`). Entry 4 talks over the record; entry 14
does not.

**Messages from upstairs** (`dj_manager_note`; cost 306 s; the shelf keeper). The manager is the
active system prompt (#189): a memo comes down, is read on air and reacted to. `manager_per_hour` 4
is the quota counted against what actually aired in the last sixty minutes; the intercom also pages
`upstairs_per_hour` 3 times.

**Call / Call with banter / Phone call** (`dj_caller`, `dj_call_generated`; cost 439 s — the dearest
road; the call writer and the cupboard). A caller with a name, a cloned voice picked for the name
(`clone_caller_pct` 70), a topic, an arc; the request line reads one of the operator's own past
requests back to him by a stranger. `caller_per_hour` 5 is the quota, `callin_per_hour` 12 the
generated call-ins, `caller_bank_floor` 6 the finished never-aired calls that must stand on the
shelf before the road counts as covered, `caller_repeat_hours` 6. Every call is graded by the phone
contract (`call_entry_contract`: the caller holds 40–55 % of the turns, a topic, a fingerprint, a
quality `ok`). Four entries, 17 minutes: the road the hour owes the most.

**Talk over the record** (`prep_track_talk`; cost 68 s). An intro written for the song that is
playing and a send-off after it; measured the cheapest and most reliable road (1.43 s of room per
second of speech against banter's 3.28). Written `track_talk_ahead` 10 records deep; an intro
written during an earlier record airs without a model visit (#869).

**Recap on the hour** (the press). Written from the station's own log — what played, who rang, what
sold, what came down — three minutes before its slot (a recap cannot truthfully be written earlier).
The same log sets the Gazette (`paper_hourly` on): the hourly newspaper, tinted paragraph by
paragraph under the hold (#1077).

**Not on the sheet but in every hour.** Station IDs 3 times an hour (`station_id_per_hour`, five
IDs on file); the SFX guy, a quip every 4 units at rate 100 (`sfxguy_every_units`, `sfxguy_rate`);
a sound effect every 2 units (`sfx_every_units`); interjections over the record (`interject_rate`
0.85); continuity pairs between entries (fourteen pairs, one hour's rest each); a mixtape every 8
records (`mixtape_every`); the name remark on a caller (`name_remark_rate` 0.3); a guest interview
when someone is in the third seat (#568/#1135, otherwise plain banter); the emergency host (piper)
when a road arrives bare.

## 3. What the hour owes, and how it stood this morning

The obligations are six-hour totals (`prepare_hours` 6): the station tries to hold six hours of
every road ahead of the clock, and `/api/orchestrator/logic` scores each closed hour by how much of
each road's entries were covered by prepared material.

| road | owed / 6 h | per hour | held at 09:11 | last hour's attainment |
|---|---|---|---|---|
| caller | 6120 s | 17 min | 166 s | 7 % |
| gallery | 3240 s | 9 min | 56 s | 38 % |
| news | 2880 s | 8 min | 0 s | 2 % |
| ad | 2160 s | 6 min | 103 s | 45 % |
| banter | 2160 s | 6 min | 280 s | 2 % |
| manager | 1440 s | 4 min | 19 s | 1 % |
| track_talk | 1080 s | 3 min | 0 s | 56 % |

Hour score 20 (of 100); `hours_ready` 0.06 of the 6.0 target — the piles were wiped at 07:11 at the
operator's request (#1068) and are refilling. The order the writing rooms take the roads in today:
track_talk, ad, banter, manager, caller, gallery, news (`order`), with the operator's standing
judgments weighing caller and news at 2× and `prefer_road` caller.

## 4. How the loop walks the sheet

1. **System2 plans** the next two hours (`horizon_hours` 2) into twenty slots each, one per entry,
   with a `start`, a `deadline`, the entry's `seconds` and the standing instruction; a slot needing
   words is a job (`needs_preparation`), claimed by a sitting (one per model lane, two since #1084),
   written, tinted, rendered, and booked to the slot as an allocation.
2. **When the clock reaches an entry**, `dispatch()` serves the slot's best ready allocation and
   writes an audible receipt when it airs; if nothing is ready and `fallback` is on, the legacy chain
   serves the entry from the piles as it always did; if the piles are empty, `when_empty: live`
   writes it in front of the listener, and under the hold that still means a tint before the
   studio; if even that fails, the record plays on and the pipeline log says why.
3. **Between entries** the records spin (`MUSIC_ROOTS`, the rotation, `repeat_window_hours` 4), the
   clock-driven extras land (ads on the clock, station IDs, the SFX guy, interjections), and the
   keepers write ahead for the entries still to come.
4. **On the hour** the recap is written from the log, the Gazette is set and tinted, and the sheet
   wraps to entry 0.
5. **Paused** (as the station is while this is written): the clocks stop honestly, the keepers keep
   writing (`pause_bank_rounds` 12, `dialogue_reserve_target` 12 — the reserve of finished rounds
   the loop wants before it feels safe), the recording room may run one render per engine in
   parallel, and the phone clock takes the bank first (#1155). The first minutes after resume come
   off the shelf, not the model.

## 5. Where to change it

- The sheet itself: the panel's schedule editor → `data/schedule.json` (kinds, labels, minutes,
  per-entry prompts and notes; a track can be pinned to a `record` entry).
- The quotas and clocks: `dj.caller_per_hour`, `manager_per_hour`, `callin_per_hour`, `news_hourly`,
  `news_every`, `ad_every`, `ad_minutes`, `station_id_per_hour`, `sfxguy_every_units`,
  `mixtape_every`, `prepare_hours`, `dialogue_reserve_target`, `pause_bank_rounds`.
- The standing instructions per kind: `SCHEDULE_PROMPT_SEED` (app.py ~42226) and the per-entry
  prompt in the sheet; the persona above them: the prompt desk.
- The engine: `POST /api/system2/settings` (`horizon_hours`, `generation_turns`, `legacy_keepers`,
  `fallback`).
- The crystal on every act: `dj.crystal_tint_hold`, `crystal_coverage`, `crystal_tint_model`
  (`docs/recreation/04-crystal-and-tint.md`).

Why the cupboard behind all of this fills at the rate it does is a separate question, answered with
the station's ledgers in `docs/cupboard-fill-rate-2026-09-08.md`.
