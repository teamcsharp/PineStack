---
name: director-room-and-seeded-conversation
description: "2026-09-10: why the schedule/calls/manager were not heard (System2 caller candidates unrendered, load 0.997), the k=1 theme pin that took 94.7% of the speakerbox, the A:-only swath doors that gave the host 82% of airtime, the unreachable blend pass, and the new director's room"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-10T11:22:26.100Z
---

**The four listener reports, each measured before it was touched.** Do not
re-derive these; the numbers are in commit 45b6af0's message too.

**1. "The schedule never happens / no calls / no manager."** Adherence read
`kept 2 / missed 75` with nothing recorded for 6.6 h. System2 owns the clock
(`schedule_take()` delegates to `system2().current_clock()` whenever
`_system2().enabled`) and its plan is CORRECT - 20 slots, manager at :15/:54,
callers at :17/:21/:31/:47. It allocates nothing to caller, recap, track_talk.
Root cause from `s2_candidates` (query the sqlite directly, it is the truth):
**256 live caller candidates, 3 ready**, 251 blocked on "the complete ordered
script does not yet have verified recordings". The SCRIPTS EXIST - 55 caller
rows on `prep_shelf.json`, median 1,716 chars. The AUDIO does not. Render is
the wall: measured `2.97 + 1.05 x audio`, and the canonical hour asks 56 min
of voiced talk = ~60 min of engine on ONE lane against 60 min of clock,
**load 0.997**. The longest-round road (caller, 17 min/h) starves first. The
torrent's own schedule branch is dormant under System2, which is why
`sched_result` adherence is stale - that log is not evidence any more.

**2. "More randomness from the speakerbox."** NOT a rotation fault. Theme
`stolen garbage` at strength 84 with `doc: ""` ran `speakbox_search(..., k=1)`
on 84% of draws, and k=1 against a static index is a CONSTANT. It pinned
everything to `vil1.md`: 48.3% / 24 h, 70.0% / 6 h, **94.7% of the last hour**,
out of 317 shelf documents - walking past the weighted draw, the
six-document `unrepeated()` rotation and both `_band` dives. Fixed with
`SPEAKBOX_THEME_BAND = 12`, rank-weighted, re-rolled per draw. Live theme is
`data/caller_themes.json` (NOT themes.json). `/api/speakbox/lock` was off.

**3. "The host just monologues / they don't conversate."** All three swath
doors (full 45%, prepend 86%, append 68%) wrote `A:` and `_who_of("A")` is the
dj. Measured 6 h: **Host 81.9% of airtime (106.6 of 130.2 min), co-host 4.4%**,
247 host turns averaging 26 s. Now `_swath_deal` cuts a passage on sentence
then word boundaries into turns under `SPEAKBOX_TURN_CHARS = 260` and passes
them round the seats read off the written script (`_swath_seats`). Under 260
they also clear `_tint_plain_passage` (300+ chars, or a raw run-on, is exempt
from the crystal), so "tint all of it" works by construction. `_verbatim` is
the TINT EXEMPTION as well as the rewrite guard - the new `_dealt` list holds
the pieces and `_verbatim` is only populated when `speakbox_tint_passages` is
off. `_verbatim_turn_text` TRUNCATED a run-on to 240 chars and discarded the
rest; the deal keeps the whole passage.

**4. `blend_script` (#862) was unreachable** - gated
`bank and not _system2_job and not caller_name`, and System2 became the
default engine at #1070. That is the pass whose entire job is making the room
react to a stapled passage. Now runs on any PREPARED round (`bank or
_system2_job`), callers included. Same lesson as [orchestrator-dead-wiring](orchestrator-dead-wiring.md):
**ask whether a desk is REACHED before reading its logic.**

**5. The booth showed unsaid lines.** #770 sorts on `air_at`, correct, but a
written-never-aired row has none and fell back to `ts`, the WRITE time - two
clocks in one list. `djTalkOrderKey` now puts those in a band below every
aired row, behind a divider.

**TWO DIAGNOSTICS THAT LIED - do not trust them blind.**
- `/api/recording-room/rows/{kind}` read `row["text"]`, which only single-line
  roads (ad, station_id) set. It answered **"no words to say" about 55 fully
  written caller rounds**. Dialogue rounds keep words at
  `row["entry"]["script"]`. Fixed; now says "waiting on the engine", which is
  the truth. **This nearly sent me after the wrong bug - check
  `data/prep_shelf.json` directly.**
- My own first director read counted 359 rows / 2,442 s of "air" in a 240 s
  entry: a staged burst stamps an ESTIMATED `air_at` on every turn, so a
  window read on `air_at` alone counts PLANS as broadcasts. Filter on
  `AIRLOG_AIRED = ("box","stream","both")`.

**The director's room (new, 🎬 `director.py` + `/api/director`).** Every entry
of the hour: what it is, the script System2 has BOUND to it turn by turn with
the seat the listener will hear, what actually aired in its window, the
engine load, and the direction in force. Notes are **standing** (every future
segment of that kind) or **one-shot** (pinned to an occurrence, spent by
`_schedule_action_complete`). They reach the writing through
`director_clause()` inside **`_schedule_clause`** - the one choke point every
scheduled round passes through, System2's per-slot prompt included. Book is
`data/director_notes.json`.

**THE WRITERS ROOM (commit fe1a79b, same day).** Five things, all reaching the
writing through `_schedule_clause`:
- **Fork on edit.** Refusing to edit kept material was correct and nearly
  useless - most of what airs is a `frozen` round on its second innings. A
  frozen/aired round is now COPIED (`director_fork_kept`) and the rewrite lands
  on the copy; the fork carries script/cast/voices/takes so only the changed
  line records. Verified: forks unfrozen, `director_fork_of` set, 142 kept
  rounds untouched.
- **The tint stopped silencing roads.** `crystal_coverage` 82 (about one turn
  in six may air plain) + `crystal_tint_must_flow` (manager) exempt outright,
  checked in `dialogue_tint_ready`. A tint hold on a road that runs twice an
  hour is an OFF SWITCH, not a quality gate.
- **Segment shapes** (`director_beats`) - ordered beats (seed/banter/manager/
  outside/caller/sfx/close), per kind or per occurrence, compiled to a prompt
  paragraph. A graph that does not reach the prompt is a drawing.
- **Learning from edits** (`director_lessons_clause`) - four was/now pairs as
  worked examples; punctuation-only tidies filtered.
- **`headroom_plan`** - the hour was over-subscribed at load 0.997. Thins
  proportionally with a 2-min floor, keeps every kind, gives reclaimed minutes
  to records. 56 -> 42.5 min of talk, load 0.997 -> 0.76, written as a NEW
  preset ("canonical hour (fits the engine)") with the original intact.
  **Result: 18 of 20 entries aired, 1 on air, 1 empty** - against every caller
  slot reading "nothing behind it" that morning.
- **Test contract changed:** `test_recording_before_tint` asserted an untinted
  MANAGER row is skipped; that behaviour is retired. The rule is asserted on
  `news` now, plus two tests for the exemption. 178 green.

**Where the operator wants this to go** (stated 2026-09-10, partly built):
System2 as a scripted-show pipeline - scenario seeded from randomized
speakbox chunks, a **writers room as an interactive flowchart** where banter
nodes are interrupted by manager/outside nodes, then script -> **operator
edit + approval gate** -> tint -> **tint approval** -> recording room -> air;
the operator's edits feed the chunk/vector learning so the station gets
autonomous from seeded intent. Substrate that already exists for it: the
speakbox vectors, `prompt_learning.sqlite3`, `s2_candidates` states,
`rejection_lab`/`line_review`, and the director's notes book. **The blocker to
design around is load 0.997** - an approval gate that holds segments will
silence the station unless unapproved work still airs by default.

Related: [system2-handoff-and-switch](system2-handoff-and-switch.md), [dialogue-pipeline-diagnostics](dialogue-pipeline-diagnostics.md),
[render-is-slower-than-speech](render-is-slower-than-speech.md), [tint-yields-to-air](tint-yields-to-air.md),
[orchestrator-dead-wiring](orchestrator-dead-wiring.md), [hour-contract-two-truths](hour-contract-two-truths.md).
