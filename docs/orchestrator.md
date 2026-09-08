# The orchestrator

The LCD's Behind the scenes view now links newly cut turns to their retained rejection event. Its Words, Why and System popup shows complete evidence, accepts individual Accept/Reject feedback, and dismisses on an outside tap. Event and revision checks prevent a decision against a different or superseded occurrence. Legacy cuts without an exact retained link cannot be voted on from that row.

Individual editorial approvals and confirmed rejections are also saved as literal preference examples. The writing/tint model receives at most three relevant examples in a separate system message; the current rewrite material is kept separate. The coordinator brief exposes the same guidance. Examples are bounded, cached and restored from durable decisions, and exclude technical failures and one-time batch approvals. They guide comparable wording choices without automatically changing acceptance thresholds, replacing source facts or bypassing recording checks.

The [inbox #1057 execution audit](orchestrator-audit-1057.md) documents the
current recording booths, complete-line reconciliation, durable ordered
recovery, neural outcome memory and the regression evidence behind them.

The general manager. Nobody reports to it and it cannot make anybody do
anything — it decides **what gets made next**, and everything else follows from
that one decision being made well.

Its job, stated the way the operator states it:

> ensuring that everything is flowing, and that everyone is making it to the
> voice acting room after getting scripts from the writing desk, in order to
> produce pre-recorded dialogue and keep the station flowing ahead of the live
> generation.

---

## 1. The one decision

**`prep_plan(skip)`** returns what to prepare next and *why*, as a readable
sentence. Everything below is an input to that function or a consequence of it.

```python
{
  "kind": "caller",                  # the road to work
  "why":  "Phone call takes the air in 30s and is 240s short of the 240s "
          "it owns - a phone call at about 273s covers it, and a deadline "
          "outranks the ledger (#957)",
  "tier": "deep",                    # bare | thin | deep
  "room": 174.2,                     # seconds of window open right now
  "cover": 7630.4,                   # seconds of finished audio banked
  "budget": 174.2,                   # what may be spent this pass
  "deadline": {...},                 # the entry that forced it, if any
  "candidates": [...]                # every road, costed
}
```

### The ranking, in order of authority

1. **The reserve is bare.** When there is not enough finished audio to stay on
   the air, the board is ordered by measured **rate** — seconds of airtime
   bought per second of room time — and the fastest cover wins outright. A
   running order is no use to a station that has gone quiet.
2. **A deadline.** `prep_deadline_pick()` walks `coord_upcoming()` in deadline
   order and returns the first coming entry that will take the air short and
   whose road is buildable. A deadline outranks the ledger's efficiency
   ranking, deliberately — see §4 for why that had to be said explicitly.
3. **The running order.** `schedule_prep_order()` names the roads the sheet is
   about to want, soonest first.
4. **The ledger.** Among what is left, cheapest useful thing first.

### The tiers

`prep_tier(cover)` reads how much finished audio is banked and returns `bare`,
`thin` or `deep`. `prep_budget(tier, room, cover)` turns that into seconds
allowed this pass. The budget always ends in `min(room, ...)` — it can never
exceed the time left on the record that is playing.

That clamp is why **`fits` is not a veto**. A gallery round measures ~256s and
a call ~273s on this box, and an ordinary three-minute record leaves ~155s of
window — so both roads are permanently `fits: false` and would never be built
at all. A deadline pick is therefore measured against the **reserve** instead:
there must be enough banked audio to stay on the air while the work is done,
and a real window to start in. Those two are the safety. The budget is an
efficiency rule, and efficiency does not get to overrule the clock.

---

## 2. What it looks at

| function | answers |
| --- | --- |
| `coord_upcoming(window)` | every entry about to take the air, with `starts_in`, `owns_seconds`, `held_seconds`, `short_seconds`, `bare`, `covered` |
| `hour_needs()` / `hour_needs_now()` | what each road owes the hour against what it is holding |
| `hour_shortfall()` | the honest answer about the hour, in seconds |
| `pantry_seconds()` / `prepared_seconds()` | finished audio banked, and how much of it is spoken for |
| `prepare_target_seconds()` | the horizon dial, in seconds |
| `prep_room_left()` | how long the record playing has left |
| `task_cost(kind)` / `task_gain(kind)` / `task_rate(kind)` | the measured ledger: what a road costs, what it buys, the ratio |
| `coord_air_sample()` | real dead air, measured over a window |
| `render_relief()` | is the clone engine slow enough that the pair should drop to Piper |
| `schedule_jammed()` | has the clock stopped advancing |

### `coord_upcoming()` and the thing it gets right

**One shelf, many entries.** The canonical hour has three *Painting selling*
entries and one gallery shelf between them. Reporting the same `held` against
each of them is what let the second and third read as covered while nothing had
been made for them. So the stock is **spent as the walk goes forward**: the
first entry is covered, the second is short by what is left, the third is bare
— which is what actually happens on air.

`short_seconds` rather than `bare` is the figure the deadline planner works in,
because an entry that owns three minutes with forty seconds standing by is not
bare — it is short, and it will still go quiet two thirds of the way through.

---

## 3. What it does about what it sees

| function | action |
| --- | --- |
| `coord_fill_gap()` | puts a stacked spot into a hole, conservatively — the worst it can do is one commercial every four minutes on a station that is otherwise silent |
| `coord_carry_forward(road, label)` | an entry's time is up; anything still on its shelf is carried forward rather than left to go stale |
| `coord_bare_note(road)` | an entry arrived with nothing prepared. Counted, and the road is asked for more, sooner |
| `coord_passed_over(road)` | an entry came round, it had material, something else went out. The material is pushed **up** the order |
| `coord_retire()` | let go of what genuinely will not be used, audio and all — `COORD_RETIRE_SECONDS`, three hours |
| `engine_prep_take()` / `prep_should_stop()` | stand down the instant the live show wants the room |

### The reporting layer

These exist because a coordinator that cannot explain itself cannot be trusted
or debugged.

| endpoint | says |
| --- | --- |
| `GET /api/coordinator/brief` | what is wrong right now, in the order that matters, and what is being done about each. Deterministic — **no model call** |
| `GET /api/coordinator/capacity` | what the sheet asks for against what this box can render in an hour, and which road is eating it |
| `GET /api/coordinator/road/{road}` | one road, fully: what it owes, what it holds, what is being built, why not, and its quota |
| `GET /api/schedule/brief-audit` | whether the scripts coming out actually do what their entries are for |
| `GET /api/rooms/call-sheet` | who is wanted in the recording room, for how many lines, and which segments those lines are for |
| `GET /api/schedule/interject/progress` | how far a segment change has got, stage by stage |

**Why the brief is not a model call.** The engine on this box runs about 2.7x
slower than real time and the writing desk is the bottleneck the whole station
queues behind. An LLM ticking every minute to narrate the station would be
taking writing time away from the show it is narrating, in order to describe
the show it is starving. Every fact in the brief is already measured and the
judgement is a handful of rules — so it costs nothing and cannot itself become
the fault.

---

## 4. The mistakes this system has already made

Each of these is load-bearing history. Reverting the fix reintroduces the
failure.

**The quota overruling the sheet.** A quota deputy was allowed to overrule the
running order whenever it was behind pace. On a station running five calls and
four memos an hour, something is behind pace nearly always — so the sheet was
named and overruled round after round, and *News coverage*, *Painting selling*,
*Ad read* and the memos never got the air. The rule now: **the running order is
the law, the quota is its deputy, and the deputy may only act when the law is
silent or jammed** (`schedule_jammed()`).

**The pantry eating prepared material.** Eviction shed the oldest clips without
asking whether a banked round was relying on them, so the station deleted
material it had just spent an hour making. Loose clips are shed first now;
spoken-for clips only if still over, and it says so.

**Caller turns never recorded.** `_round_chunks()` returned `[]` for the whole
round the moment it saw a caller marker, so every "prepared call" was banked
with no audio in it and skipped for ever. Only the caller's *phone line* cannot
be pre-keyed; the hosts are ordinary seats.

**A call written to the whole entry.** `call_turns_for_slot()` measured a call
against the entry's full minutes using an *assumed* 35 seconds a turn. The
ledger measures a six-turn call at 96 seconds — about 12s a turn. So one call
was commissioned to fill four minutes, filled ninety seconds of it, and the
rest of a *phone call* segment had no phone call in it.

**Pictures read off station state instead of the round.** Hanging the gallery's
painting on booth lines by asking "what is the station holding up right now"
put a painting beside a phone call about a library book, because an ad had sold
one a minute earlier. Things that belong to a round must be bound to the round.

---

## 5. The ceiling, and why you must know it

Every road has a measured rate. Multiply each entry's minutes by what its road
costs, sum the hour, and compare with the 3600 seconds an hour has. That is
`coord_capacity()`, and on the canonical hour it says:

> the running order asks for **53 min** of written speech an hour; rendering all
> of it fresh would take about **137 min** of room, and an hour has 60.
> **a phone call alone wants 48 min of it.**

This is not a bug anywhere. It is the clone engine, which runs near three times
slower than real time, so a road that renders every word fresh buys about 0.35
seconds of air per second of work.

The consequences are visible everywhere in the code and they are not
workarounds — they are the correct response to a real constraint:

- rested material is re-aired (`SHELF_REUSABLE`) rather than the segment going
  silent
- a road that bleeds dead air is asked for more, sooner (`coord_bare_note`)
- prepared material that was passed over is pushed up rather than wasted
- the coordinator says the number out loud instead of leaving the operator to
  wonder why the sheet is not being kept

**If you want everything fresh, the levers are:** shorten the expensive entries,
or add a faster engine and pin the expensive seat to it. Only XTTS is running
at the time of writing; F5 measured roughly five times faster, and pinning the
caller's own turns to it would take the phone road from 0.35 to somewhere near
1.7 — at which point the sheet fits inside the hour.

## 6. The second pass and the air (#1063)

The crystal tint is a second pass over finished dialogue. Every road still runs
it, and a rewrite that passes the evaluator is the version that airs. What the
pass may never do is silence the station.

`crystal_tint_hold` (off by default) is the one dial. Off, a rewrite that fails
or is deferred goes out as written and the pipeline log says so, and a stored
round is READY on its audio alone. On, the #1057 contract stands: a selected
line that fails the evaluator is held before recording, a stored round needs
current tint proof to be READY, and the repair clock re-tints legacy stock.

Why the default is off, measured on 6 September 2026 with the contract in
force: 144 lines were offered to the tint and one passed; 324 of 325 stored
rounds were marked `repair_required`; every phone call was lost before the
speaker ("NEVER MADE AIR"); the emergency host read filler for three hours
while `dialogue_flow.ready` sat at 0 of 12. The blocker list now names the
hold when it is the reason, and `GET /api/tint` reports `hold`.

## 7. Recorded means aired, and the sample pool (#1062, #1063)

**#1063.** A frozen round whose every line has a finished take is recorded.
At air time it is not freshened for repeats (the #901 scan still runs and the
log says what it would have cut), and the editorial gates in the speaking loop
(a record not on air, another language, a made-up running time, the repeat and
phrase gates) write down their verdict instead of dropping the line. The cut is
owed to the writing desk, before the studio. `air_gate()` is the one function;
`speak_turns(..., recorded=True)` is the flag `_banter_air` sets. Two things
still stop a recorded line: the operator burying it, and the writing profile
(cast, crystal, plot act) having changed since it was written.

**#1062.** First sightings of samples are written to `data/sfx_seen.json`, so an
arrival is an arrival across restarts; a recent arrival is always in the pool
even when a big folder is sampled to `SFX_MAX_FILES`; half the draws go to what
is fresh (never played, or first seen inside 48 hours) through the same
no-repeat memory; and `sfx_keeper` walks the folders once a minute while the
show is on instead of only when a sting happened to be due.
`GET /api/sfx/history` reports `fresh`, `arrivals_48h`, `fresh_share` and
`walked_at`.

## 8. Every line a bar (#1064)

Tinting, by the operator's definition: while a crystal is on, every line is
converted into a battle rap in that crystal's lexicon, rhetoric, simile and
metaphor, until the crystal is switched off. Three things stood in the way,
all measured on the station's own trail. The whole-round pass stopped at the
first line the grader refused and threw away every bar that had passed, so at
100% coverage a single refusal cost the round. The grader demanded both an
internal and a multisyllabic rhyme inside every line, short ones included.
And the writer's heat clause was appended after "return only the rewritten
line", so the model rewrote the clause: eight of forty bars read "THE DIAL
(#941)".

Now a refused line is asked once more with its own graded faults, and if it is
refused again it keeps its words while the pass carries on; the bars that passed
are the ones that air, and the coverage paperwork stays honest (`met` is false).
The per-line prompt names the crystal's world and the job as conversion into a
bar. The grader accepts proven rhyme of any of its three kinds and reads the
crystal's sampled vocabulary as lexicon, not only the two passages shown. The
heat clause never rides a tint prompt. `GET /api/tint` `coverage.share` is now
lines that passed over lines graded, with `rounds` counted separately. With
`crystal_tint_hold` on, the #1057 contract still stops a round at a refused line.

## 9. The universe rhymes (#1064, continued)

The operator's rule, restated: the crystal is a hard rewrite of the material
before it reaches the recording room, and while a crystal is on, everything on
the station raps in its style. Four more things made that impossible, all
measured on the live station after section 8 shipped.

- **The tint was being turned away, not refused.** Tint asks sat in the
  station's writer lane (two admitted per model, the rest deferred with an
  empty answer), so a deferred ask came back unchanged and the grader refused
  it as "not transformed". 51 deferrals in five minutes. Tint asks now have
  their own lane and wait their turn; they are never deferred.
- **Refusals that were rhymes.** A couplet that lands its end rhymes ("we live
  and clear / spit it, dear") now counts. The lexicon check reads the crystal's
  whole vocabulary, built once per crystal in a worker thread, instead of the
  two passages a line was shown.
- **One ask per line.** Under the hold a refused line is asked three times
  with its own graded faults; without it, twice.
- **The rewrite starved itself.** The tint's share of the hour is 90% while the
  hold is on (nothing airs until it is rapped, so the desk's plain writing is
  not the product), and a refused round rests two minutes instead of thirty.

The dial that makes the rule binding is `crystal_tint_hold`: on, nothing is
recorded or aired until it has passed the crystal. `GET /api/tint` reports the
line-level pass rate; watch `coverage.share` after switching a crystal on.

## 10. The hold is the rule, and the grade is meaning (#1064, final)

Two dials now govern the crystal, both under `dj` in settings and on the tint
panel. `crystal_tint_hold` is ON by default: while a crystal is on, nothing is
recorded or aired until it has passed the crystal, which is the operator's
definition of tinting. `crystal_grade_rhyme` is OFF by default: a bar is
accepted when it keeps what was said (names, numbers, a question stays a
question, half the content words), actually transforms the line, and recites
none of the crystal's own lyrics; the spelling-level rhyme and lexicon proofs
are reported as advisory beside it. Turn `crystal_grade_rhyme` on to make those
proofs block again, as they did under #1057. Measured on the live station, the
strict grade refused 68% of real bars, including couplets that plainly rhyme,
and at 100% coverage a single refusal held the whole round; that is why the
default is meaning.

What the hold costs: rounds recorded before the rule under the old grade are
held until the repair clock re-tints them, and the reserve runs only as fast as
the tint lane can rap. The emergency continuity lines stay plain by design.

## 11. Every road, including the small ones (#1064, roads)

"Every dialogue, phone call, upstairs message, orchestrator request, newspaper
post, every single thing needs to be tinted and spitting bars." Three roads
still spoke plain after the hold went on, and each now goes through the crystal:
the SFX guy's quips (rendered directly, never through the pre-record door; under
the hold a quip that did not rap is dropped rather than aired plain), the
emergency continuity lines (recorded plain by design; now rapped at recording
time, keyed by crystal, and re-recorded when the crystal changes), and the
listening responses (the response bank keeps a crystal-tagged repertoire: drafts
are rapped and tagged, only tagged takes serve while that crystal is on, and the
eight fixed acknowledgments belong to the plain repertoire only). The newspaper
already tints through `paper_tint_story`, and the meaning grade applies there
too.

**Meaning, measured (#1064, later the same evening).** With the hold on, 36 of
38 refusals were "semantic preservation failed", and the commonest cause was the
name rule calling a sentence start a name ("Relax," and "When" after a closing
quote had to reappear word for word in the bar). A sentence-start capital is now
a name only when the crystal's own vocabulary does not know it as an ordinary
word, a word after a quote or bracket counts as a sentence start, and at full
strength a bar may keep a third of the content words rather than half (a real
bar scored 0.47; recited lyrics score 0.02 and still fail). The emergency
continuity pair airs plain, labelled as a stopgap, only while its rapped version
is still being recorded, so the hold can never leave dead air with no net.

**The cut before the studio (#1064, last).** Under the hold, one refused line
held the whole round; a census of the shelf found not one row with a complete
tint, and rounds that were nine bars and one plain line sat unairable behind the
emergency host. #1063 already says where a cut belongs. A line that will not rap
after its three asks is cut before the recording room; the round is whole when
every line that remains is a bar and at least half of the required lines made
it. `coverage.cut` counts the cuts, and the pipeline log names each one.

## 12. The masthead follows the name, and a caller's pivots enter the story (#1065, #1066)

**#1065.** The paper's identity file (`editions/paper.json`) was seeded under the
station's old name and won over the current one, so the masthead read one name
above a headline that carried another. The file's masthead now wins only when
the owner marks it `custom`, or it was derived under the same `station` name;
otherwise it is rewritten under the current name and stays there to be edited.

**#1066.** A caller's two mid-call pivots are random Speakerbox scraps. With a
caller theme and a plotline on the air, `call_pivots_contextualize` reworks each
scrap into the situation and the current act before the writer sees it (one
ask, fails closed to the originals), the seed clause is retold with the new
words, and the crystal then raps the round as usual. With the crystal off, the
second pass does not run, rows written under it fall out of the writing
profile, and the plain repertoires serve again.

## 13. Every line rhymes (#1064, the rhyme reading)

A deep scan after the hold went on found the changes live and the reserve full,
but not every line a bar: the meaning grade accepted a rewrite that kept its
meaning and changed its words without landing a rhyme, and only one aired line
in twelve rhymed. The spelling proof could not be made mandatory because it
refused real bars ("we live and clear / spit it, dear").

`rap_rhyme_evidence` is the reading that can: assonance on the last stressed
nucleus with slant codas, bar ends (bar marks, line breaks, sentence ends, or
the comma clauses of a single sentence), a chain with the previous bar, nearby
internal pairs and two-nucleus pairs; shared endings ("-ing", "-ed",
"garbage"/"back") never count. Measured on the station's own material: eleven
of twelve real bars pass, plain paraphrase fails. Under the meaning grade a bar
with no rhyme by either reading is refused ("no rhyme evidence"). The prompt
asks for bars split by " / " with end rhymes; the spoken form turns the marks
into commas and strips markdown. The evaluator is version 3, so every round
graded before this re-grades and a plain line in it is cut or re-asked.

## 14. The crystal audit (#1064, closing)

A road-by-road check that everything the station says or prints goes through
the crystal, in its world and lexicon, and lands a rhyme. Found and fixed: the
whole-round prompt never named the world or how hard to push (only the per-line
prompt did); the paper's tint was capped at six stories, ten paragraphs and
ninety seconds, so 20 of 23 stories were deferred; 13 of 38 crystal-tagged
listening responses had been drafted under the old grade and did not rhyme (they
are retagged and never serve); the empty-reserve rule had dropped the pair to
the fast model (the pair keeps the deep one); and the round's tint deadline was
sized for one fast ask per line, so on the deep model every caller round expired
before its first bar (it is sized per model and per ask now). Verified live
through `POST /api/tint/try`: a three-turn phone call came back with every turn
rhymed and borrowing DOOM lexicon in 47 seconds. The LCD's paused-state
cupboard view is a renderer change; the display firmware shows whatever the app
draws and needs no update, the app needs a relaunch.

## 15. Gold bars, the fresh samples, and the spoken destinations

**Gold bars.** A rhymed line that aired with its finished take is gold: its take
is protected from the media sweep (`data/gold_bars.json`), its print row lives
twice as long, it may come round after half the rejection window, and at a
sting moment (half of them) a gold bar from the other seat fires first with the
sting after it. Rested twenty minutes, least-fired first.

**Samples.** The sting rate and the SFX guy's rate were doubled by the operator
(1.0 and 80), and three quarters of sting draws go to fresh samples, which the
drop folder under samples_grabbed feeds through the minute-by-minute walk.

**Spoken destinations.** "Broadcast to the Nabu device", "the speaker",
"the application", "my computer" and "the desktop" all route through
`parse_broadcast_command`, the same door as the panel's selectors.

**Grader.** A bar that spells its numbers out ("nine-fifty-nine") keeps the
source's numbers; a hard bar keeps a fifth of the content words at full
strength; a leading speaker label is not part of a bar; and under the hold the
tint budget does not apply, since the rewrite runs on its own model lane.

## 16. 2026-09-07: when the hold starves the air

Measured with the operator hearing records and nothing else: the deep tint lane is serial (one permit per model; the runners are launched `-np 1`), every ask waited 170-235 seconds in the queue, the reserve held zero ready rounds, sixteen finished rounds (audio already cut) sat "waiting for tint" behind the legacy audit's speaker-order refusal, a plain recorded call re-aired through no gate, and no sound effect could play because every sting rolled inside a dialogue round.

What changed:

- **The refused bars are re-asked together.** After the whole-round ask is graded, `_crystal_round_repass` sends every refused line with its faults in ONE ask, twice at most; only the stubborn lines reach the line-by-line pass, which then gets two tries under the hold instead of three.
- **Old rounds are aligned, not refused.** `tint_recovery.align_turns` matches each original turn to the unused rewritten turn that shares the most content words (same speaker preferred). Passing lines are reused with their audio; an unanswered original is left empty for the resumable writer; an extra rewritten turn that answers nothing keeps the round owed.
- **A re-aired call must already rap** (`_rerun_rhymes`): the take plays as recorded and passes no gate on its way out.
- **A struck call is untinted** under the hold: the tinted pass's coverage stamp no longer survives the strike.
- **The pre-record door** also fires for a cached clip that arrives unchecked under the hold.
- **A spoken "resume the radio" is held to the #1154 residue rule** like pause and off: a command wrapped in a recording is refused and logged.
- **A sting rides the record** (`_sting_over_record`): 8-25 seconds after the needle drops, if nobody is speaking and the station is not paused, the dice roll at the same dial and gap.
- **The cupboard lists bars first**: ready rhymed rounds, then rounds rapping or recording, then rhymed, then old, then plain.

Evidence rolls fast: the pipeline ring and the flow journal hold about two minutes and 300 events; the container log carries none of it. Read them within minutes of an incident.

### 16.1 Later the same night: the floor, the dead box, rounds first

Sampling `box.floor` in `/api/dj/state` every ten seconds found the second cause: `dj_speak` took the air floor before a single line was written and tinted, so one intro or advert held the air for 150 seconds while its draft and its rewrite waited on the model lane. `_floor_lend` now releases the floor around the write and the tint; the floor is for the render and the play. The Pine Box itself was firmware-down (every port refused), and every road still knocked on it with the floor held; `box_firmware_down_now` makes `_play_on_box` decline at once, routes `to_box` around it on every road, and the page carries the line. Single-line tint asks yield to a waiting whole-round ask (`_tint_turn_yields`), the legacy repair stands down while the lane is deep, and after four minutes without a page or box line the 100%-talk shelf-only refusal lets one live round be written (`dialogue_starved`). The batched re-ask names the content words a bar dropped (`semantic.missing`) and reads run-on answers.

## 17. Review rejected lines and control editorial acceptance

The **Rejected lines** entry in the Orchestrator opens a retained review queue. A new cut produces one clickable popup; additional cuts update that popup. **Later** dismisses the current notice, while a subsequent cut can notify again. In the desktop app the shell owns notifications across tabs and opens the selected record in Radio. Browser pages show their own in-page notice. Neither opening a review nor submitting a decision requests playback.

Select a line to read its complete rejected candidate, original source, machine reasons and evaluation, original speaker/script context, and occurrence history. **Machine decision** and **Operator decision** remain separate: approving a line does not rewrite its raw machine grade. **Should not reject** records an exact approval and attempts to restore retained words through the ordinary writing and recording rooms. **Rejection is correct** retains the rejection and removes that exact approval. The result says whether recovery was queued, recorded, retained, or needs context; an approval is not proof that a recording exists or aired. An optional note is saved with the decision. A concurrent change produces a revision conflict, preserving the unfinished note for inspection and retry.

The header's **Rejection system** switch turns editorial rejection on or off. **Approve all** approves the current pending editorial queue once, across every page and gate regardless of the active filter. It does not change the future policy or give later identical occurrences permanent approval. Technical failures and empty records remain for repair. Each accepted occurrence retains its original evidence and queues through the normal writing and recording rooms; the result distinguishes approval from completed recording. Retrying an unconfirmed request uses the same request ID to avoid applying a committed batch twice.

**Rejection controls** offers **Allow up to N editorial flags** (0–10; higher accepts more) and individual editorial gate switches. These affect editorial acceptance, while missing voices/audio, invalid or empty content and other technical requirements still need repair. A technical rejection remains inspectable, with **Should not reject** disabled and an explanation. The room overview shows the writing-to-air stages and current writing, recording and tint state; **Decision graph** and **Station flow** open their existing inspectors. These acceptance controls are separate from the Orchestrator's scheduling-priority judgment dial.

The authenticated API is:

- `POST /api/orchestrator/rejections/approve-current` with `{request_id}`: atomically snapshots every pending record, persists eligible one-time grants, and returns counts and skipped reasons. Reusing a request ID returns its original result. The background worker restores those exact occurrences after restart; a later cut cannot overwrite their evidence. Grants and their short-lived tint proofs apply only while processing the associated stored entry.
- `GET /api/orchestrator/rejections`: summary queue with `status`, `gate`, `before`, `after` and `limit`; events include the first cut after an empty database (`after=0`). `latest_cursor` reports the server head; clients advance only through the delivered `next_after`, draining more pages while `events_has_more` is true.
- `GET /api/orchestrator/rejections/{id}`: full evidence and paginated occurrence history (`before`, `limit`); `POST` accepts `{action: "allow" | "keep", note, expected_revision}` and returns the actual recovery effect.
- `GET/POST /api/orchestrator/rejection-policy`: persisted `enabled`, `max_faults`, `disabled_gates` and revision; updates may include `expected_revision`.
- `GET /api/orchestrator/rejections/context`: current room summaries and stage explanations.

New records preserve full source, candidate and context in `data/line_review.sqlite3`, with repeated occurrences retained separately. This cannot reconstruct words or speaker identity already missing from older truncated logs. Recovery never invents a missing caller identity or substitutes an unrelated track position, and existing media files are retained. Previously completed audio is not replayed simply because a review was opened or approved.

Single-voice shelf items, including older adverts, retain their explicit stored voice and shelf position. Recovery matches the original text and kind uniquely, grades the exact reviewed wording, then records it through the normal voice engine. Withdrawing approval before or during that recording restores the previous shelf text and take. If a different editorial check still refuses the wording, that refusal is retained for its own review; approving one gate does not falsify another gate's machine report.

One-time bulk recovery merges sibling cuts from the same original programme and retains compatible approvals for the same track position. Original shelf rollback snapshots survive multiple approvals. Withdrawing one approval holds the other unfinished recoveries for that item, preventing them from restarting cancelled work. Restart restoration clears process ownership while retaining each occurrence's approval scope.

The header controls were deployed and checked on both live Control and Radio pages on 2026-09-07. Validation passed 572 Python tests, 16 Node tests, and 146 isolated Electron assertions, including network retries, selection/note preservation, narrow layouts, grouped recovery, withdrawal during recording, and restart. The live checker sent zero review writes and started zero media; the station's paused state was preserved. See the [deployment evidence](rejected-lines-master-deployment.json), [live page check](rejected-lines-master-live-check.json), and [deployed controls](rejected-lines-master-live.png).

Validation includes isolated Node tests for initial snapshots, burst cursor boundaries and desktop record routing, plus `tools/rejection-review-smoke.cjs`, a hidden Electron fixture covering full text/escaping, queue and history pagination, policy controls, review conflicts, technical exclusions, keyboard/focus behavior, desktop notification ownership, and a 125-event burst. It makes no real station requests or playback calls. Screenshots and the assertion result are written to `%TEMP%/pine-rejection-review-smoke`; fixture success alone does not establish live deployment or successful recording recovery.

Live verification on 2026-09-07 used `tools/rejection-review-live-smoke.cjs` against the deployed Control and Radio pages. Both automatically loaded the module, exposed a working Rejected lines button, showed the real room overview and policy controls, and opened the same naturally occurring tint rejection with its full evidence. Final review and room screenshots were inspected in `%TEMP%/pine-rejection-review-live-smoke`. The checker sent zero writes and started zero media; it blocked the Control page's automatic reconciliation POST and media requests. No live approval, rejection verdict or policy change was submitted, so this read-only check does not claim a completed recovery recording. The isolated browser/desktop fixture separately passed 86 assertions, including the first notification after an initially empty database.

## 18. Writing, recording and slot coordination

The [7 September pipeline audit](pipeline-audit-2026-09-07.md) records reproduced
handoff failures, their corrections, isolated regressions and live evidence.
The decision graph now shows **Work moving through the rooms**, using current
editorial and audio readiness rather than old prepared flags. It reports the
blocking stage and opens the retained rejection queue for inspection.

Schedule occurrences own their first actions, tint work uses bounded admission,
and recording workers finish eligible assigned work without queuing every
engine behind one owned script. At 100% talk, finished gallery, news and manager
rounds use their exact saved takes, including through independent clock calls.
Handoff refusal retains stock; verified playback credits the actual programme
type. Fallback cover does not fulfill the original scheduled requirement.

## 19. Discuss a rejection and test a repair

The rejection notification opens the exact occurrence it describes. Select
**Discuss** in the Rejected lines popup to talk with the orchestrator about its
source, rejected wording, failed checks, workflow and current room status.
Messages and replies stay with that occurrence, including after reopening the
app. Sending a message does not approve wording or change station settings.
The orchestrator receives measured queue and model information, with an
explicitly bounded evidence window; the inspector retains the full records.

**Trace** shows the actual model messages, final HTTP request options, raw
replies, elapsed time, crystal settings, grades and observed steps captured
during a crystal rewrite. Each model call has a unique ID. The original view
stops at this rejection's decision; it does not quietly include later turns
from the shared round. Separate discussion and trial runs can be selected,
including failed runs. Earlier records and checks outside the captured crystal
path explain when an exact prompt was not retained. A stored previous prompt
is not presented as proof of what caused a later cut.

**Try wording** accepts edited text or generates a rhyming alternative for a
retained, nontechnical crystal turn. It grades the cleaned wording with the
current machine checks, without editorial overrides or production rejection
writes. Each result keeps its original baseline, candidate, detailed grade,
instruction and model trace. A failed trial stays inspectable. A passing trial
offers **Apply wording to recording**: the server checks the occurrence, settings
and grade again before giving the ordinary recovery worker the exact tested
words. This does not claim that recording or playback has completed. Existing
approved recovery must be withdrawn before a different replacement is applied.

The future crystal instruction in Trace changes only through its explicit
save control. When enabled, that instruction reaches whole-round rewrites,
batched repairs and individual turns. It does not lower the evaluator's
thresholds or retroactively alter saved grades. Existing rejection controls
remain available for deliberate acceptance-policy changes.

Diagnostic conversations, trials, requests and complete traces are persisted
in `data/rejection_lab.sqlite3`. Exact request IDs have durable scoped receipts;
a lost response can be retried without duplicating the model call or apply.
One diagnostic model operation runs at a time. Failed or expired operations
require an explicit new attempt. Opening the inspector never restarts work.

API additions, all authenticated:

- `GET /api/orchestrator/rejections/{id}/workbench?event_seq=N`, with paged
  `messages_before`, `trials_before`, `trace_before`, and a scoped `trace_id`.
- `POST /api/orchestrator/rejections/{id}/discuss`, `/try`, or `/apply`, each
  carrying `event_seq`, `expected_revision` and `request_id`. Discussion adds
  `message`; a trial adds optional `candidate` and `instruction`; apply adds
  `trial_id`. Responses expose a durable operation polled through workbench.
- `POST /api/orchestrator/rejection-lab/settings` with `expected_revision`,
  `crystal_instruction` and `enabled`.

The [recording investigation](rejection-bottleneck-investigation.md) found a
specific scheduling delay: the pantry recording worker could await costly
untinted adverts before reaching accepted dialogue. It now leaves unfinished
rewrites to the existing writing worker and visits accepted recording work.
Tests exercise the actual keeper with a blocked writer, accepted pool,
fallback, banter, off-brief rows and exact voice/wording handoff. This is a
priority correction, not proof that all prior preparation was stopped: fresh
XTTS files also existed before deployment. Playback take counts exclude some
preparation renders, so production evidence uses media files and render
receipts as well as current booth state.

Deployment on 7 September passed **634 Python tests, 13 Node tests and 223
isolated Electron assertions**. Both delivered browser pages opened all four
tabs using authenticated reads with zero review writes or media starts. The
normal desktop app was reloaded and its three-minute observation confirmed
the review module loaded and audio stayed paused. The station's enabled,
paused state and acceptance settings were preserved. See the
[deployment record](rejection-workbench-deployment.json),
[validation and source hashes](rejection-workbench-validation.json),
[live UI check](rejection-workbench-live-ui-check.json) and
[discussion view](rejection-workbench-discuss.png).

A labelled live discussion completed in 58.4 seconds. A separate generated
trial completed in 36.8 seconds: rhyme passed, but the deterministic meaning
check failed. Both the exact candidate and detailed faults remain saved in
the popup; nothing was applied. This verifies the diagnostic path, not that
the model's explanation is authoritative or that every rejected line is now
fixed. The [model check](rejection-workbench-model-check.json) retains the
occurrence and trial IDs. The first live call also exposed a purpose-label
error that wrongly applied background admission limits to the discussion;
the corrected call uses the existing interactive FIFO, tested with two
background jobs already admitted.

The [recording check](rejection-workbench-recording-check.json) observed ten
new gallery clips, 99.2 seconds of audio, each with a matching positive XTTS
synthesis receipt. Accepted items waiting for recording fell from four to
zero while another item recorded. Fresh preparation also occurred before
the update; these observations establish continued completion, not a
controlled speed comparison. Physical LCD verification was unavailable:
the correct `10.89.1.10/status` endpoint could not connect, Windows reported
the neighbor unreachable, and no LCD USB bridge was present. The existing
LCD review controller loaded in the app.

## 20. Rejection-driven crystal repair

The [7 September backend refinement](crystal-refinement-2026-09-07.md)
audited all 3,065 retained rejection occurrences at a fixed snapshot. It
separates actual failed wording from empty output, repeated deferred work,
format conflicts and imperfect language checks. Four old source families
alone accounted for 1,162 repeated entries; repair progress now keeps the
latest candidate and a persisted evaluation digest rather than recapturing
the same failure each time model admission defers it.

All crystal paths use shared source facts and repair instructions. Accepted
turns survive retries; failed turns carry their actual candidate, missing
facts and specific grade back to the writer. Original speaker positions and
complete caller structure remain required. Output planning gives rhyming
bars room within the configured cap, while finished bars bypass the generic
prose-fragment filter. Speech cleanup and rhyme segmentation now agree about
bar boundaries. Exact known transcript-repair instruction echoes are removed
before source injection, with original files retained.

The [measured prompt reconstruction](crystal-prompt-size-check.json) reduced
one real request from 63,690 to 15,966 characters while preserving all original
turns, style passages, world, feedback and factual contracts. Repeated
instructions and synthetic reports for nonexistent candidates caused most
of that excess. This is a measured character reduction; latency also depends
on model admission and decoding. A retained trace separately shows 140.8
seconds of admission wait followed by 9.2 seconds of inference.

Workbench trials use this same repair builder and retain exact evidence.
Individual operator decisions still supply literal preference examples;
explicit future instructions remain reviewable settings. Neither a lower
rejection count nor a passing lexical screen proves faithful meaning. The
[integrated replay review](crystal-integrated-replay-review.md) and
[live trial review](crystal-rewrite-benchmark-review.json) identify remaining
predicate, location, uncertainty and filler errors. Full reports stay in the
inspector even where the model receives a compact version of the relevant
feedback. No historical rejection was bulk-approved by this investigation.

Ordinary first-pass and repair groups plan at most 1,800 output characters,
respecting a lower configured cap. Original context and turn IDs remain
available to each group; accepted progress survives admission deferral.
Oversized individual repairs retain the configured full-cap fallback. This
lets queued work run between groups without clipping a long turn. It is
not a wall-clock guarantee: observed GPU-resident decoding still dominated
one compact production request.

An explicit boolean `reasoning` field on workbench `/try` requests enables
model thinking for that diagnostic only. It defaults to false and does not
change station settings or normal production behavior. The two paired
[reasoning trials](crystal-reasoning-benchmark-review.json) exhausted a
768-token combined budget before producing final wording, so that setting
is not a validated production fix. The [targeted rewrite review](crystal-rewrite-second-pass-review.json)
also distinguishes machine passes from remaining meaning and filler errors.
Final backend validation passed **733 tests**; see the
[deployment evidence](crystal-refinement-final-validation.json).

## 21. Flexible style acceptance and learned prompt reminders

**Rejected lines > Learn and improve** now separates learning from acceptance
mode. Fluid treats insufficient transformation and missing new crystal vocabulary
as style advisories when meaning, required rhyme, structure, copying and technical
checks pass. Strict preserves the raw grading behavior. Raw verdicts remain visible;
neither mode sets a blanket allowance for factual faults.

Automatic learning activates fixed, bounded reminders after the same fault appears
in three distinct source lines across two known original conversations. Supporting
occurrences and immutable revisions are inspectable. Changed individual votes can
retract or confirm support; one-time bulk approval does not train preferences.
Save explicitly applies drafted controls. Restore rolls back a revision and pauses
adaptation until Resume; switching learning off does not change acceptance mode.

Authenticated `GET /api/orchestrator/prompt-learning` returns status and history.
`POST` to that path accepts `expected_revision` with `enabled`, `mode` or `resume`;
`/refresh` reads recent decline evidence, and `/rollback` additionally takes the
saved `revision`. These actions do not install trial wording or request playback.

The [7 September deployment](orchestrator-prompt-learning-2026-09-07.md) enabled
learning and Fluid at revision 2 with 12 reminders. Validation passed 787 Python
tests, 20 Node tests and 294 isolated Electron assertions. Both delivered pages
were inspected with writes and media blocked. A replay accepted 13 of 47 retained
failure occurrences across seven wording pairs, including ten style advisories;
this is not a production success rate. Two live trials passed raw checks but retained
meaning/filler problems. Production traces verify actual reminder delivery and one
fresh synthesis receipt, without proving improved acceptance or sustained throughput.
See [validation](prompt-learning-validation.json), [live UI](prompt-learning-live-ui-check.json),
[wording trials](prompt-learning-rewrite-trials.md) and [production evidence](prompt-learning-production.json).

## 22. Nabu stream levels and regular sound effects

Nabu's physical dial is a shared master. Pine Box now adjusts music, DJs and replies
in their own delivered audio files. Music zero stops only the music pipeline; speech
50% preserves original gain and 100% gives a limited 2x boost. A speech change applies
at the next dispatch, including an existing recording. It does not alter audio already
buffered by the device. Changing music resumes the current record at its current offset.
See [the implementation and device evidence](nabu-independent-mix-2026-09-07.md).

SFX cadence counts completed recorded host units, with durable deduplication across
page and hardware delivery. The setting can insert a random sample after every second
unit and a prepared SFX-character turn every fourth. Original dialogue stays intact;
optional additions yield to the programme's remaining time. Character turns come from
an off-air bank checked against the active Crystal and recorded in the selected voice,
so the playout path does not wait for generation. Muted hardware transport can complete
without claiming the audio was heard. See [cadence behavior and checks](sfx-cadence-repair.md)
and [the sample library inventory](sfx-library-and-nabu-2026-09-07.md).
