# The Orchestrator

*What Pine Box FM is trying to do, how the machinery is arranged, and
what a system taking over this job needs to know before it touches
anything.*

Written for another orchestrator. It assumes you can read the code but
not that you know why any of it is shaped the way it is.

---

## 1. What this station is

Pine Box FM is a radio station with no humans in it. A pair of presenters
talk to each other between records; callers ring in; a manager sends
memos down from upstairs; there are adverts, news bulletins, painting
sales from a gallery, station IDs, and a man in the corner booth with a
sound-effects desk. All of it is written by a language model, spoken by
voice-cloning engines, and assembled into a continuous broadcast.

**The show never stops.** That is the first constraint and every
decision below is downstream of it. There is no "sorry, we're not ready"
state. If a segment is not made, something else has to be in that slot,
and if nothing is in that slot the listener hears silence — which is the
one outcome the whole system exists to prevent.

## 2. The central problem

**Making radio costs more than playing it.**

A minute of talk takes several minutes to produce: one or more visits to
a language model to write it, then a text-to-speech render at roughly
half to a quarter of real time, then any effects. Measured on this box,
the roads cost (p90, seconds of room time per segment):

    gallery      362      caller       308      news         246
    manager      219      banter       184      ad           144
    track_talk    65      station_id    16

The running order asks for about 53 minutes of written speech per hour.
Rendering all of it fresh would take roughly 200 minutes of room, and an
hour has 60. **The sheet is oversubscribed by about 3×**, permanently,
by arithmetic — not by a bug.

Everything the orchestrator does follows from that. It is not scheduling
spare capacity. It is deciding, continuously, which of several things it
cannot all do it will do, and making the rest look deliberate.

## 3. The four rooms

Material moves through four stages. Confusing them is the most common
source of bad decisions, because each is bounded by a *different*
resource and being blocked in one says nothing about the others.

**THE WRITING DESK.** A language model turns a prompt into a script.
Bounded by model time — a semaphore of two concurrent calls. Roughly
90% of a model visit is fixed overhead, so writing four segments in one
visit costs barely more than writing one. This is where batching pays.

**THE RECORDING ROOM.** A script becomes audio, line by line, through a
voice engine. Bounded by render throughput. Fixed cost per call is only
about 3 seconds, so batching here buys almost nothing — this was
measured and confirmed. Audio is content-addressed by
`(text, voice, engine)`, so the same words in the same voice are never
rendered twice.

**THE SHELVES.** Finished segments wait here. Some roads keep whole
rounds (banter, callers, memos); some keep single lines (adverts,
station IDs). A row carries its script, its audio key, when it was made,
and — since the cast can change — which voices were on the microphones
when it was recorded.

**THE AIR.** The running order walks a sheet of entries, each owning a
number of minutes. When an entry comes up, the station takes a prepared
segment if one exists, writes one live if it must, or lets the record
run on if it cannot.

## 4. The scripts, and the phases they pass through

A script is not one thing written once. It is assembled, and the
assembly is where the station's character comes from.

**THE SPEAKBOX** is the operator's own library — hundreds of documents,
chunked and embedded. Before a round is written, a *swath* is drawn from
it: a run of consecutive lines out of one document. That swath goes into
the prompt as material the presenters must actually use, often verbatim.
This is the single most important thing to understand about the writing:
**a small model obeys what is in its mouth far harder than what is in
its instructions.** Telling it to be interesting produces nothing;
handing it three real sentences from a real document produces a show.

The draw is deliberately varied — weighted rotation across documents, an
occasional dive into the oldest material, an occasional scour of the
newest, and a cooldown so the same passage does not come round twice.

**THE CRYSTAL** is an optional second pass. A crystal is a corpus in a
distinctive voice — the one in use is a rapper's complete lyrics. When
one is switched on, every finished line is *rewritten* in that voice: the
same facts, the same names and numbers, but in that writer's lexicon,
cadence and rhyme.

Two things about this that were learned the hard way:

- **It must be a second pass, not a flavouring of the first.** Telling a
  model to write an advert *in a style* produces an advert with the
  style's nouns sprinkled on. Taking the finished advert and doing one
  job on it — rewrite this, keep every fact — produces the style.
- **It must be done one line at a time.** Rewriting a whole round in a
  single ask measures statistically indistinguishable from not rewriting
  it. Per-line, with each line shown the previous rewritten line so the
  rhymes chain, lands at ~84% of the source's own rhyme density.

**THE PROPS** are passages the rewrite may not touch: quoted material
that is meant to be read out word for word. They are named to the
rewrite explicitly, both to protect them and to stop the model spending
its whole effort tidying them.

**THE BRIEF AUDIT.** After a round is written it is checked against what
its entry was *for* — a news slot that never reaches the story, a
gallery slot that never describes a painting. Failing rounds are not
thrown away; they go to the back of the queue behind anything that does
the job.

## 5. What the orchestrator actually decides

Every six seconds a keeper wakes, and once it has finished any work
already in flight it asks the planner one question: **what should be
built next?** The planner answers with exactly one task.

Priority order, highest first:

1. **A deadline.** An entry about to take the air with nothing behind it.
   Measured in seconds, so it outranks everything.
2. **The half-hour board.** Each half hour is committed in advance:
   what it owes, what is prepared *and allocated to it* (nearest slot
   eats first), what that leaves short, and whether the shortfall fits
   in the room before the slot opens. A slot that will open incomplete
   is knowable long before its deadline fires.
3. **Arrears.** A road that had to be covered by a repeat is owed a
   fresh one, before the running order asks again.
4. **The cupboard floor.** Every road holds a minimum number of
   fallbacks; a road below it outranks ordinary work.
5. **The ledger.** Of what is left, the road that buys the most airtime
   per second of room — weighted by how often that road actually
   finishes what it starts.

**Two things the planner must be told, which it historically was not:**

- **The model gate.** If both slots are busy, choosing work that needs a
  model is choosing work that will be thrown away. When the gate is
  shut, the board is filtered to work that needs no model — lines
  already written and waiting for a voice.
- **The real depth of the reserve.** There is a render *cache* holding
  everything ever produced, and a *reserve* of things actually waiting
  to go out. The first is much larger and means nothing. Every decision
  must use the second.

## 6. Degrading on purpose

When the sheet cannot be met — which is most of the time — the
orchestrator commits each coming segment, in advance, to one of:

    READY      something already made is free by then; no room spent
    FRESH      there is time to write it
    TIGHT      it will be close; written, but it goes first
    PRERECORD  no time, but the cupboard has one. Committed to a repeat,
               and the preparer stops trying to write what it has
               measured it cannot finish
    CUT        no time and no stock. Stood down in daylight, hours
               early, rather than discovered as a hole
    LIVE       can only be done at the moment (a recap reads the hour
               that just happened)

**This is the heart of the job.** A hole that was decided is a
programming choice. The same hole discovered at zero seconds is a
failure. The station's entire reputation with its operator rests on the
difference.

When a segment must be stood down, the order is: colour before content,
content before promises, and the presenters' own banter last — a half
hour that has stood down its banter has stood down the show.

## 7. The cupboard

The only thing that makes an oversubscribed sheet survivable is airtime
that costs nothing to produce. There are two kinds.

**Records.** Music is free. Every minute of it is a minute the writing
desk gets for nothing.

**Repeats.** Aired segments are kept, not deleted, and re-aired after a
rest. Adverts, painting reads, station IDs, callers and memos are all
reusable; a caller or memo is screened first for anything that ties it
to a moment ("tonight", a weekday, the record that just played).

Three rules govern the cupboard, and each exists because its absence
caused a real failure:

- **A floor, not a cap.** A cap is satisfied by zero. Every road holds
  three to five fallbacks at all times.
- **Nothing is deleted unheard.** A segment that has never aired is not
  eligible for deletion by anything. It cost a model visit and a render;
  airing it once is the entire purpose of having saved it. If it is old,
  that is an argument for airing it sooner.
- **Footage goes off when the cast changes.** A repeat is a recording of
  a specific voice. Change who is on the microphone and every banked
  second is the wrong person. The *words* survive a recast; only the
  recording does not — so a stale fallback keeps its script and costs
  one render rather than a whole model visit.

## 8. The operator

The orchestrator does not decide alone. It raises a **questionnaire** —
three questions, three options each, every option a real action it can
take — whenever it sees something it cannot decide, and once every six
hours regardless, because a system that only speaks up in a crisis
teaches its operator to dread it.

The answers are **policy, not advice**: each one has exactly one reader,
and that reader is the thing it claims to control. If an answer changes
nothing, it is a survey and should be deleted.

Anything the operator marks as **liked** changes what gets drawn next:
the material behind a liked line goes to the front of the draw and stops
resting. That is the operator teaching the station what good looks like,
in the only currency it understands.

## 9. Hard-won lessons

These are the ones that cost the most to learn. A system taking this
over should treat them as load-bearing.

**Measure, then decide.** Almost every serious fault here was a
plausible assumption that measurement contradicted. A rewrite pass
assumed to cost 30 seconds a turn cost 6–12. A "brake" on reserve depth
was on 100% of the time. A batching scheme assumed to be the big win was
worth 1.5%.

**A brake that is always on is an off switch.** Any threshold on a
quantity that sits permanently on one side of it is not a control, it is
a disabled feature with a comment explaining why it should not be.
Prefer budgets — a share of a resource, spent as it goes — which are
never wholly on or wholly off.

**Silence is the enemy.** This code swallows exceptions widely, for good
reasons. The cost is that a road which never runs looks exactly like one
nobody asked. **Every early return that skips work must say so.** More
time has been lost here to unlogged `return`s than to any bug.

**Instruments lie.** A depth ceiling satisfied by already-aired audio. A
log tag truncated past a 200-character cut so a grep for it found
nothing while the events fired. A shelf reporting "the barest on the
board" for a shelf that was 96% full. **When a measurement disagrees
with the symptom, suspect the measurement.**

**Two functions with one name.** In a file this size a name collision is
a certainty, and Python resolves it silently: the later definition wins
and the earlier one stops existing. This has caused three separate
outages. There is a startup check now; keep it.

**Correct, called, running, and changing nothing.** This is the one
that cost the most, and it is the first thing to check. A whole day was
spent asking "why is the orchestrator falling behind" while its desks
were reasoning correctly and none of their conclusions reached
anything. Ask three questions of every mechanism, in this order: **is it
CALLED, does it RUN, does it CHANGE ANYTHING?** Most of what looked like
bad judgement was a gate wired to nothing. The shapes it takes:

- *Two variables with one name, in different units.* `target` is a count
  of rounds in one function and a number of seconds in another. A line
  copied between them compared 14 against 7,200 and was false for the
  station's entire life — and it was the gate that decided whether the
  main preparer ran at all. This is the same fault as two functions with
  one name and it is harder to see, because nothing collides and nothing
  raises.
- *A decision fired from a panel read.* The "there is no time, cover it"
  call lived inside a status function polled every five seconds by the
  browser. It fired twenty times a minute with a tab open and never
  without one. **Anything a page can poll must be free of side effects**
  — no counters, no budgets, no queued work. If a decision belongs to
  the station, put it on the station's own timer.
- *A guarantee inside `except`.* The protection for "nothing is deleted
  before it airs" sat in the error path of the function that deletes
  things. It held only when the code crashed.
- *A key with one end wired.* Three policy answers were written by the
  questionnaire and read by nothing; one was read with no writer
  anywhere. The operator could answer, the answer was stored, and
  nothing happened. **Grep both directions for every setting.**

**Fixing the gate reveals the next one.** Banter starving the board was
two loops, not one. The first fix made the second visible, and the
second was where the time actually went — 42 minutes of an hour by the
station's own arithmetic. Expect the first fix to uncover rather than
resolve, and re-measure before declaring victory.

**A ledger with no ceiling cannot recover from a counting fault.** Debts
were added one per event and paid off one per segment made. When a poll
bug added a hundred of them, the road needed ten hours of writing to
clear a debt that never existed — and sat at the top of the planner
until then. Cap anything that accumulates, and expire it.

**Words and footage age differently.** A script is durable — it says the
same thing next week. A recording is not: it is one voice, and the cast
can change. Anything that keeps material must know which of the two it
is holding.

**A promise that cannot be kept is worse than no promise.** The station
told itself "it is tinted properly on a later pass" on every round it
refused to rewrite. There was no later pass. It told its operator "I am
on it" about a segment it had already measured it could not make in the
time. Both were comforting and both were false, and both delayed the
real fix by hiding the symptom.

## 10. What is still true and unsolved

An honest handover names what is not working.

- **The sheet is ~3× oversubscribed.** No scheduling fixes this. It is
  closed by adding records, deepening reuse, or cutting the dearest
  segments — and that is the operator's decision, not the system's.
- **There is no single broadcast.** Every listener assembles the show
  independently from a clock and a clip feed, so two devices playing at
  once will not agree. A unified stream is the correct architecture and
  does not exist yet.
- **Per-model quality and failure are not measured.** Speed is. A call
  that comes back unusable returns before the recorder runs, so the
  station cannot yet say "this model is failing you" with evidence.
- **Settings changes are not journalled**, so the system cannot reason
  about what the operator just did.
- **The larder floor is absolute, and consumption can pin the reserve
  just under it.** Banter yields to a starved road only above its floor,
  because a quiet pair is the one fault this station may not have. If
  rounds air as fast as they are written the reserve sits below the
  floor and banter never yields at all. Watch `standing_down` on
  `/api/surplus`: if it is false for long stretches while roads are
  bare, the floor is too high for the consumption rate, not too low.

---

*The purpose of all of it is one sentence: the trains arrive on time.
Everything above is in service of a listener never hearing the machine
behind the station — and where the machine must show, showing a choice
rather than a failure.*
