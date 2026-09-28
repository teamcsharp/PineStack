# System 3 — Decision ownership

This updates `PINEBOX_ARCHITECTURE_SNAPSHOT/05_DECISION_OWNERSHIP.md` for a
road where System 3 is **ACTIVE**. In **SHADOW** and **OFF** the snapshot's
table is still exactly true, and System 3 only records.

| Decision | Owner under System 3 (active) | Mechanism | Recorded as |
|---|---|---|---|
| Next segment, slot, deadline | scheduler + System 2 + show loop (unchanged) | clock/slot/reservation | System 2 ledgers |
| Road material (seed passage, wire, memo, painting) | the road (unchanged) | road writer's own draws | `CTS OBLIGATED` event, no draw |
| Topic movement inside a round | **System 3** (FL frame → CTS) | FL1 `cancel_topic`/`anger` sets a pending topic; the next cycle draws CTS from what is available | `FL` + `CTS` events; material via `speakbox_quote` |
| Who speaks, in what order | **System 3** structure + parser | the banter cycle, handing the initiator role on each cycle; nobody speaks twice | turn `speaker`, `step`, `cycle` |
| Emotion of each turn | **System 3** (ES) | weighted draw conditioned on tension, the speaker's current emotion (volatility), and the previous turn's lean | `ES` event with intensity draw |
| Response act (agree, challenge, mock...) | **System 3** (RS) | weighted draw conditioned on dynamics, speaker emotion, controls, personality, cooldowns | `RS` event |
| Initiator pushback | **System 3** (IRS) | as RS; conceding is one outcome, not the default | `IRS` event |
| Flow move / frame | **System 3** (FL1 at the frame, FL2 on responses) | phase- and closure-aware weights; closing moves only in the last turns | `FL` event |
| Closing turn | **System 3** | the last planned turn draws from closing moves only | `FL` event (category `land`) |
| Wording | **LLM** | realises the running order | the script; validated after |
| Speakerbox doors (full / prepend / append) | **stand down** on a System 3-directed round (engine v2) | `_quote_door` records "System 3 places the speakerbox inside its running order"; the legacy splice dealt one passage across the seats after the writing, which is a monologue split between two voices (measured 2026-09-26: 8 dealt turns of one transcript) | `door-outcome` observation, `applies: false` |
| Full-swath dial | **System 3** (engine v2) | a d100 against `speakbox_full_swath_rate` opens turn 1 with a speaker-box monologue (≤700 chars) the initiator reads; the next turn answers it | `SPEAKERBOX` event, mark `full`, mode `FULL_SWATH` |
| Speakerbox marks on structure lines | **System 3** | d100 against the slider scaled by density, then a mode draw | `SPEAKERBOX` event |
| Which document / passage | **station** `speakbox_quote` (locks, themes, cooldowns, rotation) | unchanged | material record: real candidate list with weights, `passage i/n` |
| SFX: whether a clip is wanted, where, about what | **System 3** SFX Guy | aggression, arousal and comedy terms, first exchange, cooldown | `SFX` event |
| SFX: minimum cadence | **station** `sfx_every_units` (unchanged floor) | two-line cadence | `SFX` air observation `due=cadence` |
| SFX: the actual file | **station** matcher, bans, weights, rotation, recency | unchanged; System 3 only adds intent words | `SFX` air observation with matcher counts |
| TTS voice / engine | station (unchanged) | role binding, render ladder | render provenance |
| Delivery (pace, pitch drift, energy, pauses) | **System 3** ES → six emotion dims → `performance_vector` → `perf_apply` | engine-neutral DSP on every take | `turn_dice.s3.perf` on each line |
| Repair of a non-compliant script | **System 3** asks, station rewrites | one bounded rewrite, **banked or System 2 rounds only** | `REPAIR` observation |
| Admission, order, publication, receipts | station (unchanged) | admission/sequencer | playout ledgers |
| Which road a round is, and its shape | **System 3** (`[s3-roads]`) | `dj_banter(road=)`; the road's legs in `config.structures.<road>` (recap, ad, news, manager, memo, gallery, mixtape, open_show, fan_mail, guest); a memo is directed like the rest | `identity.road_kind`, `road_structure`, `entry["road"]` |
| Whether the SFX Guy pipes up after a line, and what kind of line | **System 3** SFXGUY node on every host turn (his own stream) | d100 at the interjections dial; kind by news_share / warp; never over a caller | `SFXGUY` event; `turn_dice.s3.sfxguy` |
| Which of his lines | **System 3** at air, through the chooser | the plan's kind order against the pools that have something; one recorded draw per pool (the shelf, the shed, the wire); the speech bank's take keeps the bank's context matcher, the SPEAK roll is System 3's | `SFXGUY` observation `line` |
| A single-voice line (record link, station ID, the manager's page) | **System 3** `system3_direct_line` | one-seat legs, ES rolled, the clause in the writer's prompt; the liner stack drawn through `unrepeated(director=)` | a conversation of its own; `system3` on the ledger row |
| A stock line (memo announcement, complaint), a produced spot | **System 3** LINE draw | the list / the ad book's least-used reads are the candidates, every weight recorded | `LINE` event; `system3` on the ledger row |

## Decisions explicitly not taken over

- **Live rounds are never repaired.** A second model visit in front of the listener is dead-air risk (blueprint §8, §17).
- **Callers keep their protocol** as legs of System 3's call structure (`[s3-calls]`); a story call-back handed its own protocol keeps it, annotated; one handed none (the station's case today) is built from System 3's call legs with call-back acts (2026-09-28).
- **No path is invented.** The SFX Guy produces intent words and dues. Only the station's indexed book produces files.
- **Scheduled sources are never discarded.** Turn 0 speaks the road's own subject (`CTS OBLIGATED`), and a CTS category whose material the road does not hold is ineligible.
- **Frozen scripts are not mutated.** Binding reads the script and writes only `turn_dice`, `dice`, `system3`, plus additions to `passage_source`/`dealt`. The words are not touched (tested).

## Added 2026-09-27 (`[s3-rounds]`, `[s3-carry]`, `[s3-withhold]`)

| Decision | Owner under System 3 (active) | Mechanism | Recorded as |
|---|---|---|---|
| The hosts' tempers for the round | **System 3** `TEMPER` (the desk's `dice_hosts` switch still gates it) | one weighted draw per host seat over `TEMPER1`, worn tempers x0.25 | `TEMPER` event per seat; the running order's head |
| The one open reaction that turns the round ("at least once X is openly shocked") | **System 3** `SHOCK` | dice at the `shock_beat` control, the reaction, the turn | `SHOCK` event; the turn's row and `decisions` |
| A host going on a roll and the other getting a word in edgewise | **System 3** `INTERJECT` | dice at the `interjections` control, the long turn, three phrases; two planned turns (`interject`, `carry_on`) inside the budget | `INTERJECT` event; steps `interject` / `carry_on` |
| Whether the station's name is worked in | **System 3** `MENTION` | dice at the `mention` control, the turn | `MENTION` event; the turn's row |
| Where a round starts emotionally, and what it picks up from | **System 3** carry (the last round's ending, aged) | `observe_ledger` hands on; `direct` hands in for live / System 2 rounds; `perf_state` blends for banked rounds | `CARRY` event (plan) and `CARRY` observations (`handed on`, `delivery`) |
| A planned round that will not air | **System 3** says why | `system3_withhold(handle, why, stage)` from dj_banter (deferred writer, no turns); the sweep files rounds nobody bound within 30 min | `WITHHELD` / `ABANDONED` observations; `status` `withheld` / `abandoned` |
| The writer lane: who waits for whom | station (`call_ollama`) | the transcript-repair harvest is its own category (cap 1) and yields while a round writer waits; a LIVE round waits up to 45 s for a slot instead of being refused; a document whose repair came back unpunctuated is skipped 12 h; one harvest per speakbox draw | `pipeline_log` `speakbox` / `lookahead` |

The four station-side random() directives in dj_banter's one-call prompt
(the tempers, "openly shocked", the diatribe interjections, the 30% name
mention) and `show_memory`'s "moods right now" stand down when System 3 owns
the round. A deferred or empty writer never leaves the seed passage standing
in for the round: the round is withheld and recorded.

## Added 2026-09-28 (`[air-order]`, `[s3-material]`, `[s3-story]`, `[s3-source]`, `[s3-sfx-roll]`, `[s3-bank]`)

The principle, from the operator: "no dialogue hit the station unless it is scripted via the RNG roulette
system" - and banks are welcome when they are made from System 3's node-scripted conversations.

| Decision | Owner under System 3 (active) | Mechanism | Recorded as |
|---|---|---|---|
| When a single line may reach the page | the page door, behind the committed rounds | parked off the page while held rounds wait; published after them; stale ones withdrawn (orch policy `air_order_strict`) | `/api/playout` `waiting_line`; feed row `withdrawn` + why |
| A line's place in the script | where it joins the air queue | `script_ledger_reserve` | ledger `(block, ord)` |
| The manager's words / a gallery piece / what people online say, on a row that names them | **System 3** row + the station's material (`system3_cts_material`) | eligible only when present; the gallery piece is a roll | the event's `selected.material` |
| A story call-back's shape | **System 3** call legs | `plan_call` with `STORY_ACTS` | the call's turns |
| The document a round opens from, when pinned | the operator, on the initiator node | `system3_pinned_source` -> `speakbox_quote(only=)` | pipeline log `system3` |
| The board's clip | **System 3**: family then clip | `sfx.category`, `sfx.clip`, `sfxtv.*`, `sfx.match` | STATION events; `sfx_roll` + `poster` on the line |
| Whether one of the SFX Guy's banked lines airs, and which | **System 3** | `sfxguy.bank_line` (chance), `sfxguy.bank_take` (pick); 6 h rest | STATION events |
| Every prompt block | **System 3** blocks table | every DEFAULT_BLOCKS name now has a marked site | BLOCK events; the Prompt tab |
