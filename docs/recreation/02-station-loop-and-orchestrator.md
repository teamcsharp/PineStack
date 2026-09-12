# 02 — The station loop and the orchestrator

## The show loop

`dj_start()` starts the radio; the running task is `_torrent_talk()` (the "torrent": records and
talk poured one after another). Each pass of the loop: pick the next record from the music index
(`MUSIC_ROOTS`, `data/music_index.json`, ~36,000 tracks), start it, and run `_record_talk()` beside
it — the pair's introduction, the round of banter, the coming-up line — as a task that is never on
the record's critical path (#689). Between records the loop serves **the running order**: the
schedule's entries (a phone call, an advert, the news, a painting round, a memo from upstairs, talk
over the record, the recap on the hour), each a **road** (`kind`).

With System2 on (#1070) the loop first asks `_system2().dispatch()` for the occurrence the plan wants
now; if nothing is served and `fallback_due()`, the legacy chain serves the entry as before.

## Roads

| kind | what airs | who prepares it |
|---|---|---|
| `banter` | a round between the DJ and the cohost (and the third seat when a guest is in) during or between records | the larder keeper (banked rounds) and System2 |
| `caller` / `banter_caller` | a phone call: a caller with a name and a cloned voice, a topic, the phone contract (`call_entry_contract`) | the pantry/cupboard keepers and System2 |
| `ad` | an advert (produced spots and single reads) | the shelf keeper |
| `news` | a bulletin from the wire (feeds through SearXNG; `NEWS_PREP_LIFE`) | the news keeper |
| `gallery` | a painting round: ComfyUI paints, the pair describe and sell it | the gallery keeper |
| `manager` | a message from upstairs (the station manager's memo) | the shelf keeper |
| `track_talk` | intro / outro over the record, with the record's own notes and lyrics | `track_talk_get` lookahead (#869) |
| `recap` | the hour's recap, written from what actually aired | the press |
| `record` | a record; not a round | the loop |
| station IDs, the SFX guy, continuity pairs, responses | short inserts | their own keepers (#1062, `CONTINUITY_PAIRS`) |

## The schedule and what the hour owes

The running order is a template per hour (`data/settings.json` → the schedule; `prepare_hours` = 6).
`hour_owes` / `/api/hour-owes` turn it into obligations per road in seconds; `/api/orchestrator/logic`
shows, per road, `owed / held / uncovered / cost` and the learning factor (how often the road arrived
bare, the closed-hour miss premium) and the operator's standing judgment (`judgment:more:caller`).
`/api/coordinator/capacity` compares the asks the hour makes with the room the writers have.

## The desks and the keepers (the legacy engine)

Stock lives in four piles, all under `data/` (see 06):

- **the pantry** — rendered clips (audio) keyed on the exact spoken text (`dj_speak` finds a clip
  already made and airs it without a model visit or a render);
- **the shelf** — prepared segments per road (ads, calls, memos, painting rounds) with their scripts
  and the tint's verdict (`shelf_put`, `shelf_take`, `shelf_reuse_rest`, `stock_expires_at`,
  `stock_used_by`);
- **the larder** — banked banter rounds waiting for a slot (`_LARDER`);
- **the cupboard** — graded phone calls (`call_entry_contract`, `CALL_CONTRACT_VERSION`).

Keepers are background tasks that top the piles up to `stock_depth` while the station is on: the
larder keeper writes rounds with the writer model, the tint rewrites them, the recording room
(`booths`, one preparation render per engine) renders them, and `dialogue_stock_items` is the ONE
inventory every reader consults (#1076 lesson: two inventories drift). The **hold shelf** protects
clips still waiting to play out of the satellite.

## The floor and paced air (#1146, #1147)

`_FLOOR_LOCK` is the round gate: one thing holds the floor at a time; pages are paced so a page
delivery counts as air for the starvation clock (#1156). The five "garble mouths" (leaked audio
elements, the shell unmute war, detached tune players, the boot feed epoch, the one append door) are
the lessons in `docs/pine-box-lcd.md` and the memory notes: every path that puts sound on the air
goes through one door.

## Pause, resume, banking

`radio_paused()`; the pause is honest about clocks (#1150), banks stock while paused (#1155: the
phone clock takes the bank first), and the resume reel (#1151) replays what was cut going in.
`paused.json` carries why (a listener's "pause the radio" from the mic hearing the show, #1154).

## The orchestrator's judgment book (#1150)

Policies the station asks the operator about and remembers (`/api/orchestrator/logic` → `policy`,
`book`): `repeats_hard`, `prefer_road`, `postpone_first`, `innings_bonus`, `reuse_rest`,
`stock_depth`, `tint_share`, `ballast_minutes`, `when_empty` (`live`: write in front of the listener
when nothing is ready), `drive_road`, and free-text `operator_notes` ("from now on I want more
callers"). Each ask has a face (the button the operator saw), what it does, and why. The 🕸 logic
graph in the panel draws the roads, the factors and the lessons.

## The pipeline stages

`pipeline_log(stage, text)` is the station's diary (`/api/dj/pipeline`): `air`, `crystal`, `call`,
`drop`, `lookahead`, `system2`, `speakbox`… Every important decision writes a line with its request
number, so a night can be reconstructed from the log. `/api/orchestrator/logic` → `pipeline.stages`
counts stored items by stage: `ready`, `awaiting_tint`, `rewriting`, `awaiting_recording`,
`recording`, `needs_replacement`.

## The press (#1019)

Every hour the Gazette is set from the airlog (`paper_print`), tinted paragraph by paragraph
(`paper_tint_story`, hold until tinted, cut what will not rap — #1077), rendered as a broadsheet or a
tabloid, and read on air as the recap. Editions are on disk; the 📰 window turns the pages.
