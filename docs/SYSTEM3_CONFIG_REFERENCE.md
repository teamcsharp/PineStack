# System 3 — Configuration reference

There are two things to configure: **settings** (the operator's switches)
and **config** (the versioned behaviour data: tables, structure, sections).
Both live in `data/system3.sqlite3`. Both are edited in the System 3 window
or through the API below. Every config save is a new version, recorded by hash.

## Settings — `GET/POST /api/system3/settings`

| key | values | default | meaning |
|---|---|---|---|
| `mode` | `off`, `shadow`, `active_selected_roads`, `active` | `shadow` | `off`: the legacy station exactly. `shadow`: System 3 plans every round beside the legacy writer and nothing reaches air. `active_selected_roads`: directs the roads in `roads`, shadows the rest. `active`: directs every supported road. |
| `roads` | subset of `system3.ROADS` (banter, caller, recap, ad, news, manager, memo, gallery, mixtape, open_show, fan_mail, guest, track_talk, station_id, upstairs, interject, ad_spot) | `["banter"]` | the roads that `active_selected_roads` directs; `active` directs every road on the register |
| `generation_mode` | `batch`, `turn` | `batch` | `batch`: one planned scene (Mode A). `turn`: banked beat-chain rounds are re-decided after each beat (Mode B). Live rounds are always batch. |
| `test_seed` | string | `""` | a fixed root seed for every conversation (testing). Blank means a fresh seed per conversation. |
| `repair` | bool | `true` | a banked round whose script ignored the running order (seat order or turn count under 50%) gets one bounded rewrite with the order attached |
| `debug_verbosity` | `quiet`, `normal`, `full` | `normal` | reserved for log volume; the ledger always records every decision |
| `controls.*` | 0..1 | 0.5 each | see below |

`POST {"reset": true}` resets the controls and keeps the mode and roads.

### Controls

Each control multiplies the weight of every outcome **tagged** with it by
`4^(c−0.5)`, which is ×0.5 at 0, ×1 at 0.5 and ×2 at 1. The multiplier is
written into the candidate's `why` in every event it touched.

| control | tag(s) | notes |
|---|---|---|
| `disagreement` | `disagreement` (and `agreement` inversely) | RS1 argue/push back, RS2 oppositional, IRS opposite/refutation/confrontational/hold |
| `escalation` | `escalation` | IRS confrontational/escalate, FL2 escalation, FL1 anger |
| `tangent` | `tangent` | FL2 wander, RS2 anecdote/redirect |
| `callback` | `callback` | callbacks (eligible only once something can be called back to) |
| `novelty` | `novelty` | FL1 cancel topic, FL2 wander |
| `closure_aggressiveness` | `closure` | also scales `closure_pressure = frac² × (0.5 + c)` |
| `emotional_volatility` | ES persistence | the speaker's current emotion category ×(1 + 3(1−c)) |
| `speakerbox_density` | Speakerbox marks | the prepend/append slider × `4^(c−0.5)`, capped at 1 |
| `sfx_aggression` | SFX Guy | p = `p_low + (p_high − p_low)·c`. At or above 0.85, back-to-back clips are allowed. The station's two-line cadence is always the floor. |

## Config — `GET /api/system3/config`

`?hash=<h>` returns any retained version. `POST /api/system3/config/reset` restores the defaults as a new version.

### Tables — `PUT/DELETE /api/system3/tables/{id}`

```text
{id: "ES2", family: CTS|ES|RS|IRS|FL, label, version, enabled, weight,
 description, categories: [{id, label, weight, <rules>, items: [{id, label,
 text, weight, enabled, <rules>}]}]}
```

A family can hold any number of tables (ES1 + ES2...). The raffle first
draws a table by `weight` (only when more than one table is eligible), then
a category by `weight × mean eligible item weight`, then an item by its
effective weight.

**Rules** (set on a category and inherited by its items; an item can override):

| rule | type | effect |
|---|---|---|
| `requires` | list of `speakbox news gazette manager gallery topics research` | ineligible unless the road holds that material this round |
| `requires_state` | list of `callbacks unresolved` | ineligible until the conversation has one |
| `phases` / `not_phases` | list of phases | phase gating: `OPEN ESTABLISH DEVELOP ESCALATE EXPLORE WILDCARD RESOLVE WRAP SEGUE` |
| `min_turns_left` / `max_turns_left` | int | time gating (e.g. no new topic with under 4 turns left; closing moves only in the last 1–2) |
| `modifiers` | `{dynamic: coef}` | factor `clamp(1 + coef·(2x−1), 0.05, 4)` for `tension agreement energy novelty repetition_risk closure_pressure topic_exhaustion` |
| `emotions` | `{es_category: mult}` | applies when the speaker's current ES category matches |
| `after_lean` (ES) | `{"-1"/"0"/"1": mult}` | reaction to the previous turn's lean (pushback, neutral, support) |
| `tags` | list | links to controls and personalities |
| `cooldown_turns` | int | excluded if used within N turns (RS/IRS/FL default 2); plus ×0.4 if used in the last 6 |
| `lean` | −1, 0, 1 | oppositional / neutral / supportive; moves `position` and `agreement` |
| `effects` | `{dynamic: delta}` | applied to the dynamics after selection |
| `cue` | `agree disagree question humor concede insult close` | the deterministic validator's lexical test for this act |
| `speaker` (FL) | `initiator responder any` | preference (×0.35 when the frame speaker is the other kind) |
| `new_topic` / `keep_initiator` / `closes` / `resolves` / `keeps_unresolved` / `callback_source` | bool | state-machine effects (topic change, no handoff, closing move, settles or opens an unresolved point, becomes something to call back to) |
| `speakerbox` (RS/IRS) | `REFERENCE PREPEND APPEND` | the act itself asks for a passage (no extra dice; bounded by the inline budget) |
| `resolver` (CTS) | `speakbox direction` | `speakbox`: the station draws a real passage. `direction`: an instruction only, and only eligible when `requires` is met. |
| `valence`, `arousal`, `dims` (ES) | numbers | feed the PerformanceIntent and the voice |

`calling_slur` in IRS1 is kept from the operator's list and ships **disabled**.
Turning it on is a table edit.

### Structure — `PUT /api/system3/structure`

```text
{steps: [{id, label, speaker: initiator|responder_a|responder_b|frame,
          optional, draws: [{family, tables?: [...]}], speakerbox: [prepend, append]}],
 closing: {draws: [...]}, handoff: true}
```

The default is the PDF's banter cycle. `speakerbox` marks are the PDF p.7
red Prepend/Append lines. After the last step the initiator role passes to
the next seat (unless an FL `keep_initiator` outcome was drawn), and the
cycle loops until the turn budget is met. The last turn uses `closing.draws`.

### Road structures — `PUT /api/system3/structures/{road}` (`[s3-roads]`)

Every road but banter has a structure of **legs** (banter keeps the cycle
above). `GET /api/system3/config` shows every road's structure, the saved
one or the default. Editable on the Structure tab (road picker).

```text
{id, label, version, kind: legs|protocol|line, min_turns, max_turns, topics,
 alternate_seats?: [seats], head, tail,
 legs: [{id, label, place: open|middle|close, seat: A..E|alternate, act,
         draws: [{family, tables?, closes?}]}]}
```

`place`: the open legs come first in order; the middle leg(s) repeat until
the turn budget (`turns` asked by the road, clamped to `min_turns..max_turns`)
is met, `alternate` seats taking turns (A/B, or A/C when a caller seat is
present, or `alternate_seats`); the closing legs come last. Nobody speaks
twice in a row: a collision trims or adds one middle turn. `act` is what the
writer is told the turn does (`{host}`, `{cohost}`, `{first}` are filled in).
A `line` structure has one seat and one leg per line. `topics` lets the
TOPIC roll raise something off the board on a middle leg.
`single_line` covers direct speech without an earlier road stamp. `reply`
covers listener answers and draws ES and RS. Both use the same structure
editor as the named record link, station ID, and interjection roads.

The register - `/api/system3/status.roads` - lists every road with its
writer, its hook, its mode and the label its lines carry when it stands
aside ("not directed by System 3").

### Sections — `PUT /api/system3/config/section/{speakerbox|sfx|sfxguy|personalities}`

| section | keys | defaults |
|---|---|---|
| `speakerbox` | `modes{verbatim, reference, callback}`, `max_inline`, `passage_chars` | 1.0 / 1.0 / 0.6, 2, 420 |
| `sfx` | `p_low`, `p_high`, `first_exchange`, `arousal_boost`, `humor_boost` | 0.08, 0.7, true, 0.3, 0.15 |
| `sfxguy` | `rate_by_dial` (SPEAK threshold = the desk's `sfxguy_rate`), `rate` (used when not), `reaction_by_warp` (reaction weight = `sfxguy_warp`), `reaction_share`, `news_share`, `never_over_callers` | true, 0.4, true, 0.35, 0.15, true |
| `personalities` | `{seat: {tag: multiplier}}` | `{}` |

## Inputs System 3 reads from the station (not configured here)

`banter_min_lines` / `banter_max_lines` (the range of a free round's LENGTH roll, `[s3-glass]`), `_SPEAKING_NOW` (the line on air, for `/api/system3/now`).

`speakbox_prepend_rate` and `speakbox_append_rate` (DJ desk sliders),
`sfx_every_units` (cadence floor), `sfxguy_rate` / `sfxguy_warp` / `drop_voice` (the SFX Guy's node), the round's weather roll (initial emotion
dims per seat), System 2's budget (`seconds`, `words_high`), and
`mean_turn_seconds(road)` for timing calibration from rendered audio.

## The round's own rolls and the carry (2026-09-27, `[s3-rounds]`, `[s3-carry]`)

Three tables joined the defaults (`tools/system3_rounds_patch.py`, engine
`system3-engine/3`, default config hash `48e47262ef173867`):

| Table | Family | Drawn | Reaches the writer as |
|---|---|---|---|
| `TEMPER1` | `TEMPER` | once per host seat per round, when the desk's `dice_hosts` switch is on; a temper worn in the last rounds weighs x0.25, the other seat's is excluded | the head of the running order: `TONIGHT'S TEMPERS (rolled): A (Host) is ...; B (Skip) is ...` |
| `SHOCK1` | `SHOCK` | three stages: dice at `SHOCK_RATE_AT_FULL (1.0) x shock_beat`, the reaction, the turn (never the opener or the close, never a caller) | on that turn's row: `HERE Skip IS OPENLY APPALLED at what Host just said ...` |
| `INTERJECT1` | `INTERJECT` | banter only, two host seats, no caller, six turns or more: dice at `INTERJECT_RATE_AT_FULL (1.0) x interjections`, the turn that runs long, three phrases (the desk's `diatribe_interjections` when it has any, else this table) | that turn's row says it goes on a roll; the running order gains two turns: the other host's `interject` (the phrases, a reaction not a reply) and the first host's `carry_on` |
| - | `MENTION` | dice at `MENTION_RATE_AT_FULL (0.6) x mention`, then the turn | `Works the station's name, Pine Box FM, in naturally here` on that row |

Controls added to `settings.controls`: `shock_beat`, `interjections`,
`mention` (0.5 each by default, which reproduces the old odds where they were
odds: one shock beat in two rounds, a 30% mention). They are rates, not
weight multipliers. The rolls live on their own streams (`seed|round:<FAMILY>`),
so the turn trajectory of a seed is unchanged and switching one family off
never moves another's dice. They run only when the runtime asks
(`inputs.round_rolls`): a stored conversation from before them replays as it
was planned.

**Carry** (`inputs.carry`, no table): the runtime hands a live or System 2
round what the last round left on the air - each host seat's ending emotion,
position and energy, the dynamics, up to three unresolved points, the line
it landed on, the tempers it wore - decayed linearly over `CARRY_WINDOW`
(1200 s). It is recorded as a `CARRY` event with no draw; turn 1's row picks
up from the landing. A banked round takes it in the voice only, at air
(`perf_state` blends 0.4 x factor of the carried dims). `GET
/api/system3/status` shows `carry` and `open_rounds`.
