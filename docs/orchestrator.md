# The orchestrator

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
