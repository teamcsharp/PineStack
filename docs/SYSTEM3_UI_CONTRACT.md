# System 3 — UI contract

The operator instrument is `frontend/system3.js` and `system3.css`. It opens
from the panel's **System 3** button, from the command palette, or
stand-alone at `/system3`. It is a debugging instrument, not a decoration.
**It never shows a roll that was not recorded.**

## Honesty rules (tested by reading the code, enforced by construction)

1. The drum in a Rolodex scrolls only through the `candidates` of the recorded stage, and it stops on the recorded `selected`.
2. A die shows no number while it tumbles. It pops to the recorded `dice`. A decision that was not a draw (an obligation, a door that did not apply, an act-triggered quote) shows `—` and says so.
3. The Speakerbox document drum uses the station's real document list and weights from the material record. It is labelled as the station's rotation, not a System 3 roll.
4. Shadow conversations say, on every view, that nothing they show aired.

## Views and synchronisation

| View | Source | Shows |
|---|---|---|
| **A. Conversation** (messenger) | `turns[]`, `lines`, `/api/segment/inspect` | speaker bubbles (seat colours, left/right). The written text, or the planned direction when there are no words yet. A diamond per recorded decision (family colour, d100). Phase, emotion and intensity, Speakerbox and SFX indicators, estimated seconds, status (`planned`, `generated`, `frozen`, `published`, `heard hh:mm:ss`, `withdrawn`, `plan only`, `simulated`). |
| **B. Technical / RNG Rolodex** | `decision_events`, `observations_air`, `material` | per turn: `SYSTEM 3 — TURN 0003 · A Caine · Initiator's Response · DEVELOP`, then one card per event (`ES 43/100 · 5/10 → ANGER (.43)`, `SPEAKERBOX append 43/100 (needs > 10) → PASS → REFERENCE → 43d.md → passage 1/3`, `SFX at air (both) candidates 17 / eligible 13 → clip.wav`). Expanding a card shows every stage, each candidate's p with a bar and its effective-weight reasons, the excluded candidates and why, state before → after deltas, and the raw event. |
| **C. Final script** | `lines` (block/ord), `turns`, inspect | frozen line text, speaker, performance intent, voice and engine, planned SFX and SFX at air, Speakerbox passages, line id, heard receipt or withdrawal reason, revision. Shadow shows System 3's plan beside the legacy script. |

**Bidirectional selection:** selecting a bubble, a diamond, a Rolodex card
or a script line sets `{turn_id, event_id}`. Every view highlights the same
turn (and event) and scrolls it into view. The join keys are `turn_id`,
`event_id`, `decision_bundle_id`, `line_id` and `block/ord`.

**Layouts:** "All three" (side by side, stacked under 1180 px), each view
alone, and "Cycle view" (Conversation → Rolodex → Script).

**Play the build:** for each turn, an empty message slot with a typing
indicator appears. Then each recorded decision rolls in turn (drum and die),
and the bubble settles into its text. Speed can be slow, normal or fast.
`prefers-reduced-motion` makes it instant.

## How a value was reached (the decision card)

Tapping a diamond in the messenger, or **How it got here** on a Rolodex
card, opens a pop-up built only from the recorded event:

| Section | From |
|---|---|
| What it is | the family (CTS, ES, RS, IRS, FL, Speaker-box, SFX) in plain words |
| How it came to this | the drum and die replayed from the recorded stages; per stage the arithmetic the engine did: `d100 = floor(u × 100) + 1`; for a weighted draw, `u × total weight` and the slice it lands in, with every candidate's base weight, effective weight, chance and why the weight moved, plus the candidates that were not eligible; the speaker-box odds (DJ-desk dial × `4^(density − 0.5)`) and threshold; the SFX probability build-up; the ES intensity formula with its numbers |
| What it read | `state_before` (phase, tension, agreement, energy, novelty, closure pressure, topic worn, unresolved points, the speaker's emotion), the turn it answered, the operator controls for that family, the material available on the road, seed, draw number, config and engine |
| The passage it fetched | the station's document list and weights (drum), the document and passage position, fetch time, the passage text or why it was not fetched |
| What the station did with the roll | engine-1 door outcomes |
| What it changed | state deltas, the voice ES asked for, the SFX clip at air, the line it helped shape |

Escape, the Close button or a tap outside closes it.

## A line opened into its parts

A bubble that a speaker-box passage went into (a prepend/append/monologue
mark that hit, a reference, a seeded opener, or an engine-1 dealt piece)
carries an amber edge and an **open the passages** button. Tapping the
bubble opens it in place:

- the passage read **before** the line (and the round's seed, or the opening monologue) above it, laid out as its document's own lines, each word lit if it reached the line;
- the line as written, with every word taken from a passage marked in that passage's colour, a strip showing where in the line each passage sits, and a count (`Of the 95 words: 77 from the append passage, 18 their own`);
- the passage read **after** the line below it; references and callbacks after that;
- the validator's own speaker-box check, and **the setup**: the running-order row the writer was given for this turn.

A match is a run of three or more words in the passage's order; a single
common word is not evidence. A line that is one piece of a passage an
engine-1 door dealt across the seats says so and lists every piece, seat by
seat, with this one ringed, and then shows what System 3 had placed on the
turn instead. While a line is open, following pauses (**Resume following**
restarts it). A tap anywhere on an opened line closes it again, except on
its sliders, buttons and inputs. The seed passage is on the record
(`inputs.seed_text`) for rounds planned after 2026-09-26; older openers
show the seed's file name only.

## Lost speaker-box rolls, and the dials behind them

A speaker-box chip that brought no passage in is gray (a dashed chip with a
gray diamond; its die is gray in a build and in the Rolodex) and says why
in its number: `16/32` rolled 16 against a need of over 32, `65 full` won
the roll but the round already held its passages-per-round limit, `off`
never rolled (the dial at 0%, or a road that carries its own material).

A line with such a roll opens too (a faint amber edge, **see the
speaker-box odds**). Every opened line with speaker-box marks carries an
odds panel: per roll, what it needed and why (`the prepend dial was 49%,
x 1.00 for density 0.50 = 49% odds, so the d100 had to land over 51`), and
under it the station's dials as they are now - the DJ desk's prepend,
append and full-swath dials, System 3's Speakerbox density and its
passages-per-round limit. Moving a slider re-works each roll on the spot
(`rolled 65: this roll would WIN`; a roll kept out by the limit points at
the limit instead). **Save to the station** turns the station's own dials -
`POST /api/dj/dial {key, value, was}` for the DJ desk, `POST
/api/system3/settings {controls: {speakerbox_density}}`, `PUT
/api/system3/config/section/speakerbox` for the limit - so the next round
rolls at the new odds. A past roll is never re-rolled.

## The Messenger is a live feed

The Script tab's Messenger shows the last few rounds (up to six) oldest
first, each under its own header (road, mode, time, where it has got to:
planned, turns written, lines in the script). It reads the event cursor
(`/api/system3/events?after=`) every 2.5 s while it is on screen and
nowhere else. A round System 3 has just planned arrives at the bottom and
builds from its recorded rolls: each turn's slot appears, each decision
rolls its drum and die, and the bubble settles into the direction the
writer was given. When the writer's words land, each direction types over
into its dialogue. A round with news is fetched again (at most every 3 s);
the newest round is looked at every 10 s while it is being written, and
heard receipts are read every 15 s until every line has aired or gone. Only
the turns that moved are redrawn.

**Following:** new rounds (the default: the round being developed stays in
view) or the air (the line on air stays in view); a hand scroll or an
opened line pauses either until **Resume following**. The line on air is lit
wherever it sits. **Play the build** replays the newest round's build.

**SFX Guy in the correspondence:** the clip he scheduled appears as a row at
its place (before or after the line), with its die, and says whether it has
played; tapping it opens the decision card. Once the line has aired, what
the station actually played appears as his entry after the line: his quip,
the clip, and why the matcher chose it (the reason, candidates and eligible
counts, length).

## Other tabs

- **Tables:** every table by family, with sliders for table, category and item weights, enable switches, direction text, and a JSON editor for category rules. Add item, add category, make a supplemental table from the current one (ES2 from ES1), and delete (refused if a family would be left empty).
- **Structure (node view):** the banter cycle as nodes with draw chips, the Prepend/Append marks, the speaker role, optional steps and reordering. The closing turn and the handoff loop are drawn below.
- **Controls:** mode, roads, generation mode, test seed, repair, verbosity, the nine controls, and the Speakerbox, SFX and personalities sections. Controls can be reset to defaults, and tables and structure can be reset to defaults.

## Transport

REST with an incremental cursor. It polls every 2 s and pauses while the tab is hidden.

| Call | Use |
|---|---|
| `GET /api/system3/status` | the metrics strip |
| `GET /api/system3/conversations?limit&mode&road&before` | the list |
| `GET /api/system3/conversation/{id}` | one aggregate with its events, observations and lines |
| `GET /api/system3/events?after=<cursor>&limit` | new decisions and observations. `cursor` and `head` come back. With "follow live" on, the newest conversation loads and builds. |
| `GET /api/system3/line?line_id=` | a spoken line → its turn and decision chain |
| `GET /api/segment/inspect?block=` | existing: per-line aired/heard/voice/engine (cached 20 s) |
| `POST /api/system3/simulate` | a plan from the live tables that can never air (`keep` needs write auth) |
| `POST /api/system3/replay/{id}` | decision replay verdict |
| `POST /api/system3/turn/{id}` | Mode B by hand on a recent conversation |
| `POST /api/system3/settings`, `PUT /api/system3/tables/{id}`, `PUT /api/system3/structure`, `PUT /api/system3/config/section/{name}`, `POST /api/system3/config/reset` | edits (write auth) |

Reads use `require_read_auth`. Writes use `require_auth`. An SSE stream was
not added because polling the cursor carries the observed event rate (tens
of events per round). The blueprint reserves SSE for when profiling shows
otherwise.

## 2026-09-27: the Messenger as a pure feed, and System 3 everywhere

**Header.** The Messenger's bar lives in the Script page's own header now
(`mountEmbedded(..., {chrome: {tools, air, facts}})`): the round's facts and
the caution button at the right of the title line, the on-air pill in the
middle of the band toolbar, the icon buttons (latest, turn-by-turn, cuts,
replay, open) at its right end. Nothing is drawn above the messages.

**The now-playing card** (`#spSaying`) jumps every view to the line on air:
the script scrolls to it, and a System 3 view calls `jumpToAir(lineId)`, which
resolves the LINE (not the view's focus), scrolls to its tile and builds it
again where it stands - the dice and the Rolodex roll into place, one slate per
decision, then step aside and the words type in (`v.rebuildTurn`).

**Cut lines.** A message the air never heard carries a note under its chips:
why (the station's own reason), and the switch for the system that cut it.
The switches are the orchestrator's policy book (`POST /api/orchestrator/policy
{does: "cut:off" | "withdraw:off" | "bound:off" | "floor:hold" |
"breakin:off"}`); the bar's cut icon opens them all. A withdrawn round says why
the sheet refused it; a restart is not a policy and says so.

**Speaker-box rolls** show, after the roll: the document reel (the station's
weighted list landing on the document drawn) and the line reel (the harvested
lines of that document - `GET /api/speakbox/{name}?lines=1` - rolling to the
passage's first line, which opens out into the passage). When the harvest no
longer holds the passage the document's own paragraph is shown with the passage
marked. The dials fold shut under their heading until tapped.

**Topics** reach a round only through System 3: the TOPIC roll (dice: the
`topics` control, 0.5 = 40% of rounds; item: the least-sprung weigh most; turn:
never the opener or the close) and CTS1's "From Topics Database". A "1. / 2."
entry is said word for word and answered word for word. The station's own
topic roads (banter's 60% pick, the caller's 12% share, the manager's memo, the
SFX Guy's board lines) are off while `topics_by_rng` is on (the default).

**Calls** are System 3 rounds built from `config.structures.caller` - every
leg a node with its act, seat, place and draws; `PUT /api/system3/structures/
{road}` edits them. The Messenger shows a call's legs like any other turns. A
System 3 call whose write fails is dropped; the built-in template never airs.

**The line inspector** ("How this line came to be") has a System 3 section
(`mountLineStory`): the tile built again, every roll with its decision card,
the running-order row System 3 wrote and where it sits in the prompt the
writer was given, the line as it came back with passages marked, and the
checks on the turn. A line System 3 did not direct says so.

**Tablet performance.** One thumbnail plays at a time, once through, only
while on screen; the feed keeps 14 rounds; the Script page does not hit-test
the script pane while a System 3 view covers it.

## 2026-09-27 (evening): the rewrite passes are rolls; Timing and Parameters

**Rewrites as rolls** (`[s3-rewrite]`). Three new families, three new controls
(`tint`, `repair`, `room`, 0.5 each): TINT is rolled per turn - which lines the
crystal tint may rhyme (one event per round saying the pass is off when the
station has it off); REPAIR once per round - whether a round that misses its
target goes back to the writer (on System 3 rounds the review gate no longer
decides); ROOM once per round - whether the Writers' Room may add to or
rewrite it later. The bind stamps `entry.system3.tint_turns / repair / room`;
`crystal_tint(only_turns=)`, the richness rewrite and both Room tickets read
them. The Messenger shows the round-level rolls as chips under each round
head (`roundRolls`), TINT as a chip on the message.

**The tapped line** has two more tabs. *Timing*: the clocks of the line from
plan to air with each step's duration, then what the station was doing while
it was made - loop stalls in that window (`/api/pulse?since=&until=`), the
model calls that overlapped it and how long they held the lane, GC, System 3's
own planning times. *Parameters*: every parameter that painted the line as a
fold - System 3's controls (value at planning, live slider), the DJ desk dials
it read, the speaker-box and SFX config sections, the station's switches (cut,
withdraw, bound, floor, break-in, topics), and the round itself (generation
mode, structure, seed, config, inputs) - each with what it pertains to and the
door that changes it.

**Single lines** (`[s3-line-fix]`): a line's node sits in the speaker's seat;
a line that speaks its own running-order row is written again without the
sheet, then withheld; the ledger asks for a single line's stamp once, so
intros, interjections and station IDs now link to their node.
