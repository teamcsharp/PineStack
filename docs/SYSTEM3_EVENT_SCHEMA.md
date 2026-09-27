# System 3 — Event and state schema

The authoritative store is `data/system3.sqlite3` (`system3_store.py`).
FlowJournal receives one observational row per plan or bind, on node `draft`
with status `system3`. It is never read back as truth.

Versions: engine `system3-engine/1`, events `system3.decision-event/1`,
aggregate `system3.conversation/1`, config `system3.config/1`. Every
conversation stores the `config_hash` it was planned under, and every
config version is kept by hash, so old conversations stay interpretable.

## System3DecisionEvent

One per recorded decision, including decisions that were **not** a draw
(an obligation, a door that did not apply). Those have `rng: null`.

```json
{
  "schema": "system3.decision-event/1",
  "event_id": "e3630402a91d4415:0009",          // conversation_id:seq
  "seq": 9,
  "conversation_id": "e3630402a91d4415",
  "trace_id": "s3-e3630402a91d4415",            // or the System 2 trace
  "turn_id": "e3630402a91d4415:t01",            // "" for pre-turn (doors)
  "turn_index": 1,
  "at": 1790463053.1,
  "family": "RS",                               // CTS ES RS IRS FL SPEAKERBOX SFX TOPIC SFXGUY LINE
  "stages": [                                    // the Rolodex, in order
    {"stage": "table",    "candidates": [...], "selected": "RS2", "draw": {...}},
    {"stage": "category", "candidates": [...], "excluded": [...], "selected": "playful", "draw": {...}},
    {"stage": "item",     "candidates": [
        {"id": "tease", "label": "Tease", "base": 1.0, "weight": 1.4,
         "p": 0.41, "why": ["speaker in joy x1.70", "used recently x0.4"]}],
      "excluded": [{"id": "callback", "label": "Callback", "why": "nothing to call back to yet"}],
      "total": 3.41, "selected": "tease", "selected_index": 1, "of": 4,
      "draw": {"seed": "…", "n": 17, "label": "RS:item", "u": 0.1034, "dice": 11, "sides": 100}}
  ],
  "rng": {"seed": "…", "n": 17, "u": 0.1034, "dice": 11, "sides": 100},
  "selected": {"table": "RS2", "category": "playful", "id": "tease", "label": "Tease",
               "text": "teases them about it", "index": 1, "of": 4},
  "state_before": {"phase": "ESTABLISH", "tension": 0.35, "agreement": 0.5, "energy": 0.5,
                   "novelty": 0.5, "repetition_risk": 0.0, "closure_pressure": 0.02,
                   "topic_exhaustion": 0.1, "initiator": "A", "unresolved": 0,
                   "speaker": "B", "speaker_emotion": "calm", "speaker_intensity": 0.47,
                   "speaker_position": 0.0},
  "state_after": {…same shape…},
  "links": {"prompt_id": "", "script_id": "", "render_id": "", "delivery_id": ""},
  "meta": {},
  "config_hash": "fd04d1fdc9e507c2",
  "engine": "system3-engine/1"
}
```

Stage-specific extras:

- **ES** adds a stage `intensity` with its own draw. `selected.intensity` is the result.
- **SPEAKERBOX (mark)** has stage `dice` (`threshold` and `rule`: a hit when the d100 lands above `100 − rate×100`), then optionally stage `mode`. `meta.mark` is `prepend|append|act`, and `meta.insertion_point` is recorded.
- **SPEAKERBOX (full)** (engine v2) has stage `dice` against the full-swath dial, then a `mode` stage selecting `FULL_SWATH`: an opening monologue on turn 1, read by its speaker. The round-level doors no longer roll under System 3; their `door-outcome` observation records `applies: false` and why.
- **SFX** has stage `dice` (`threshold` is the probability) and optional stage `placement`. `selected.intent` holds the words handed to the station's matcher. `meta.resolved_at` says who picks the file.
- **CTS OBLIGATED / CONTINUE** has `stages: []` and `rng: null`, and `meta.why` says whose subject it is.

`p` is the candidate's share of the stage's total effective weight. It is what
the draw actually used. `base` is the table weight before conditioning.

## Observations (recorded after the plan)

Stored in the same `events` table with `kind='observation'` and a global
cursor. Families and bodies:

| family | stage | body |
|---|---|---|
| `SPEAKERBOX` | `door-outcome` | `door, applies, why, rate, lift, roll, hit, file, turns, system3_roll, rolled_by (system3/station), decided_by` |
| `SFX` | `air` | `turn_index` (script index), `due (cadence/system3/both)`, `decided_by`, `intent`, `played[{clip, sample_id, seconds, why}]`, `sfx_guy[]`, `matcher{path, why, score, cands, tied, eligible}` |
| `COMMIT` | `script-ledger` | `block, sid, round, lines[], turns[]` (the freeze) |
| `REPAIR` | — | `why, validation{score, verdict, seat_order, turn_ratio}` |

Material resolution (a passage the plan asked for) is kept on the aggregate
under `material[]`: `request_id, mode, selected{file, passage{index, of}},
candidates[{id, weight}]` (the station's real document list and weights),
`draw` (a sentence saying the station's rotation chose it, not a System 3
draw), `ms`, `decided_by`.

## System3Conversation (the aggregate)

```text
identity   conversation_id, trace_id, schedule_occurrence_id, system2_slot_id,
           system2_job_id, road_kind, revision, script_digest
mode       off | shadow | active | simulation          generation_mode batch | turn
seed, draws, config_hash, settings (snapshot), inputs (everything the road knew,
           including seed_file and, from 2026-09-26, seed_text: the seed passage itself)
timing     target_duration, turn_budget, deadline, seconds_per_word, words_per_turn,
           turn_seconds (host mean_turn_seconds), elapsed_estimated, elapsed_rendered, remaining
subject    topic, authority, category, sources[], seeded, keywords[], active_angle,
           topic_exhaustion, unresolved_points[{turn, by, act}]
participants[] actor_id (seat), role, name, position, emotion{table, category, id, label,
           intensity, source rolled/persisted/reaction, since_turn, dims}, intensity,
           energy, recent_actions[], callbacks[]
dynamics   phase, tension, agreement, energy, novelty, repetition_risk,
           closure_pressure, topic_exhaustion
cursor     cycle, step, initiator, last, pending_topic, topic_count
turns[]    turn_id, index, speaker, name, step, step_label, cycle, phase,
           decisions[{family, event_id, table, category, item, label, text, lean, tags, cue, u, intensity}],
           directions[], speakerbox[{mark, rate, dice, threshold, hit, mode, request_id, material, event_id}],
           sfx{play, placement, p, reason, intent[], gain, event_id},
           performance (PerformanceIntent), decision_bundle_id, text, script_index,
           status planned/generated/dropped, estimated_seconds, state_before, cursor_before, state_after
decision_events[]  (stored in the events table, re-attached on read)
doors      {full|prepend|append: {u, dice, event_id}}
material_requests[], material[], observations[] (Mode B), observed_delta, replans[]
validation (see below)   comparison (shadow)   actual[] (shadow: the legacy script)
bindings[{turn_id, script_index}]   plan{sheet, plan_ms, active}   status
```

`decision_bundle_id` is `turn_id:b<hash of the turn's event ids>`, the one ID for
"the chain that made this line".

### PerformanceIntent

`emotion, family, table, intensity, energy, pace, emphasis, warmth, tension,
pause_style (clipped/natural/spacious), valence, arousal, dims{amusement,
excitement, confusion, irritation, fatigue, nervousness}, engine_hints`.

`dims` is what reaches the voice: `performance_vector(state=dims)` feeds
`perf_apply` (tempo, pitch drift, energy, pause length) on every engine's take.
The vector sits in the render's `fx["perf"]` and therefore in its cache
identity.

### Validation

`method: deterministic/lexical`, `planned, written, matched, turn_ratio,
seat_order, acts{met, missed, unchecked, rate}, closing, violations, score,
verdict compliant/partial/non_compliant, repair_wanted, turns[{turn_id,
script_index, checks[{what, result met/missed/unchecked/violated, how}]}]`.

## What rides a script line

`entry["turn_dice"][script_index]` (and from there every script-ledger row's
`dice`) carries the legacy #1386 fields plus:

```json
"s3": {"conversation_id": "…", "turn_id": "…:t03", "bundle_id": "…:t03:b1a2b3c4",
       "revision": 1, "phase": "DEVELOP", "step": "response_a2", "es": "skepticism",
       "intensity": 0.46, "acts": [{"family": "RS", "id": "tease", "label": "Tease"}],
       "perf": {"dims": {...}, "pace": 1.0, "pause_style": "natural"},
       "speakerbox": ["REFERENCE"], "sfx": {"play": true, "placement": "after", "intent": [...], "event_id": "…"}}
```

The round itself carries `entry["system3"] = {conversation_id, trace_id, mode,
revision, seed, config_hash, verdict}`.

## Tables in the store

```sql
settings(key PRIMARY KEY, value, at)                      -- 'settings', 'config' -> hash
configs(hash PRIMARY KEY, created, note, body zlib-json)
conversations(id PRIMARY KEY, created, updated, road, mode, status, trace_id,
              slot_id, seed, config_hash, verdict, score, summary json, body zlib-json)
events(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id, seq, kind decision|observation,
       family, turn_id, at, body zlib-json)                -- id is the live cursor
lines(line_id PRIMARY KEY, conversation_id, turn_id, block, ord, sid, who, text, at)
```

Retention is hourly: conversations older than 7 days, or beyond 30,000, go
with their events and lines. Config versions stay.

## Replay scopes (blueprint §16)

| scope | what is reproduced | how |
|---|---|---|
| decision | every draw, candidate set and selection | `system3.replay(conversation, config_by_hash)`: same inputs, seed and config give the same events. Mode B re-applies the stored observations. `POST /api/system3/replay/{id}` |
| script | the words | the frozen script-ledger rows (`lines`, block/ord) |
| audio | the takes | pantry / render identities (unchanged) |
| playout | order and delivery | the sequencer's occurrence/delivery ledger (unchanged) |

LLM and TTS outputs are **not** claimed to be deterministic. They are
replayed only by reusing what was captured.

## TOPIC (2026-09-27)

One event per round, before its first turn; `turn_id`/`turn_index` are set
to the turn that raises it once that turn is planned.

    stages[0]  dice   RAISE | NONE          weight = TOPIC_RATE_AT_FULL x controls.topics
    stages[1]  item   <topic id>            weight = 1 / (1 + uses)
    stages[2]  turn   t<index>              uniform over the middle turns (a call: its open legs)
    selected   {id, label}                  NONE when nothing off the board comes up
    meta       {rate, control, bank, turn_index?, reply?, applies?: false, why?}

The turn carries `bank_topic {id, text, reply}`; the next turn carries
`bank_topic_reply` when the entry was a "1. / 2." exchange. CTS1's "From
Topics Database" adds a `topic` stage to its CTS event and sets
`turn.topic_material {text, source: "the topics board", topic_id}`.

## Calls (2026-09-27)

A caller round plans from `config.structures.caller`: each turn carries
`leg` (the structure's leg id), `place` (open | middle | close) and
`protocol` (the leg's act with the caller's name filled in); the sheet is
`render_call_sheet(conv)`. `conv.call_structure` records the structure's id
and version.

## Roads, the SFX Guy's node and single lines (2026-09-27, `[s3-roads]`)

Engine `system3-engine/3`. `identity.road_kind` is the road that asked
(recap, ad, news, ... track_talk, station_id, upstairs, interject, ad_spot);
a legs road carries `road_structure {id, version, road, head, tail}` and each
turn `leg`, `place`, `protocol` (the leg's act with names filled in).

**SFXGUY** (one per host turn when the station has a drop voice; his own
draw stream `seed|sfxguy`, counted in `sfxguy_draws`):

    stages[0]  dice   SPEAK | PASS   threshold = sfxguy_rate/100 (or config rate)
    stages[1]  item   news | reaction | quip   weights: news_share, warp/100, 1-warp/100
    selected   {id: SPEAK|PASS, kind, order[], label}
    meta       {dial, warp, resolved_at, stream}

The turn carries `sfxguy {speak, kind, order, event_id}` (also in
`turn_dice.s3.sfxguy`). A caller's turn is PASS with `why` and no event.

**SFXGUY observation** `stage: line` (recorded at air by `sfxguy_spoke`):
`turn_index` (script index), `decided_by`, `planned`, `order`, `kind`
(news | reaction | quip | bank), `line`, `how`, `draws[{pool, of, index, u,
dice, candidates[]}]` (stream `seed|air|turn_id`), `fell_through[]`.

**LINE** (a single-voice road that handed over candidates): `stages[0]
item` over the candidates with their weights (weight 0 excluded), `selected
{id, label, index, of}`, `meta {road, source}`; the conversation carries
`line_choice {id, index, of, event_id}`. A pick the road makes at air over
its own pool (`LineHandle.pick`, e.g. the liner stack) lands in
`line_draws[{pool, of, index, u, dice, candidates}]`.

**The ledger row of a single line** carries `system3 {conversation_id,
mode, turn_id, road, seed, config_hash}`: `dj_speak(system3=)` remembers
it by line id and `script_ledger_catch_up` writes it on the row. A round's
entry carries `entry["road"]`.

## LENGTH and the line on air (2026-09-27, `[s3-glass]`)

**LENGTH** (one per free round, before its first turn, when the station's
count was the dial's random): `stages[0] dice` with `rule` "uniform over
lo..hi turns", `selected {id, label, rolled, turns}`, `meta {base, asked,
final, why}`; the conversation carries `length_roll {rolled, turns,
event_id, lo, hi}` and `timing.turn_budget` becomes `turns`.

**`GET /api/system3/now`**: `{at, line {id, who, name, kind, text, at} |
null, system3 {conversation_id, turn_id, road, mode, topic, turns, turn
(the compact turn: rolls[{family, dice, label, reel, index, of}],
speakerbox, sfx), structure, budget {turn_budget, target_seconds,
estimated_seconds, turn_seconds, length_roll}, verdict, line_choice} |
false | null, register {roads, directed, mode}}`. `false` is a line no
node made.

## The round's rolls, the carry, withheld rounds (2026-09-27, `[s3-rounds]`, `[s3-carry]`, `[s3-withhold]`)

Decision events, all with `turn_index: -1` at planning (a `SHOCK` / `MENTION`
event is re-pointed at the turn it lands on; an `INTERJECT` event at the turn
that runs long):

- `CARRY` - no `rng`, no stages. `selected.id = CARRIED`; `meta`: `from`
  (conversation id), `road`, `age`, `factor`, `seats`, `landing {who, name,
  text}`, `unresolved`. Present only when the runtime handed a carry in.
- `TEMPER` - one per host seat; `meta.seat`; one `item` stage over the
  `TEMPER1` items (worn tempers carry `why: ["worn in the last rounds x0.25"]`);
  `selected {id, label, text, seat, table, index, of}`.
- `SHOCK` - stages `dice` (`BEAT` / `NONE`), then `item` and `turn` on a hit;
  `selected.turn_index`, `meta.rate`.
- `INTERJECT` - stages `dice` (`ROLL` / `NONE`), then `turn`, `phrase-1..3`;
  `selected {turn_index, phrases}`, `meta.source` (`the desk's
  diatribe_interjections` or `INTERJECT1`).
- `MENTION` - stages `dice` (`MENTION` / `NONE`), then `turn`; `meta.name`.

On a turn: `shock {id, text, event_id}`, `long_roll: true`, `interject
[phrases]` (step `interject`), `carry_on: true` (step `carry_on`), `mention`
(the name). The stamp that rides a script line gains `round {shock,
long_roll, interject, carry_on, mention}` (only the true ones).

On the conversation: `carry {from, road, age, factor, seats, landing,
tempers, unresolved, event_id}`, `tempers {seat: {id, text, event_id}}`,
`shock_plan` / `interject_plan` / `mention_plan` (`done`, `attached_index`),
`round_rolls.draws`, `withheld {why, stage, at}`; `status` may be `withheld`
or `abandoned`.

Observations: `CARRY` `{stage: "handed on", seats, landing, tempers,
dynamics, unresolved}` at the ledger commit; `CARRY` `{stage: "delivery",
from, factor, blend}` once per banked round at air; `WITHHELD` `{stage, why}`;
`ABANDONED` `{stage: "abandoned", why, road, bank}`.

The round's meta on the entry (`entry["system3"]`) gains `planned_turns`
(the air's incomplete-conversation gate read it and it was never set),
`bank` and `carry`.

## TINT / REPAIR / ROOM (2026-09-27, `[s3-rewrite]`)

    TINT    per turn (stream seed|tint): stages[0] dice RHYME | NONE, rate = 1.0 x controls.tint;
            selected {id: RHYME | PLAIN}; meta {rate, control, coverage_target}; turn.tint {rhyme, event_id};
            turn_stamp().tint carries it onto entry.turn_dice[i].s3.tint. When the station's tint pass is
            off: ONE round-level event, selected OFF, meta.applies False, meta.why.
    REPAIR  once per round (seed|round:REPAIR): dice REPAIR | NONE, rate = controls.repair;
            conv.repair_roll {repair, event_id, rate}; bound as entry.system3.repair.
    ROOM    once per round (seed|round:ROOM): dice ROOM | NONE, rate = controls.room;
            conv.room_roll {room, event_id, rate}; bound as entry.system3.room.

Opt-in through inputs.rewrite_rolls (the runtime sets it), so older plans and the golden trajectory
are unchanged. inputs.tint = {wanted, coverage, why} is the station's tint state at planning.
