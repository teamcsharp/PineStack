# The history of the Pine Box station

Eleven eras, 2026-08-08 to 2026-09-13. Every commit is listed with its date in
[docs/commit-log.md](docs/commit-log.md); the knowledge each era left behind is kept in
[docs/notes/](docs/notes/).

This is not a changelog. It is a record of what the station turned out to be, which was
never what it looked like at the time. Read down the table and you can watch a USB
recovery tool become a radio station, and then watch the radio station spend a month
discovering that most of the instruments it had built to watch itself were lying.

| Era | Dates | Commits | What it was about |
|---|---|---|---|
| 1. The box | Aug 8–9 | 18 | A Jetson that would not boot, and a DJ panel |
| 2. It becomes a station | Aug 14–16 | 68 | Talk over records, the public door, a second voice engine |
| 3. The Voice Director | Aug 17 | 19 | An engine bench, wake words, an observatory |
| 4. Crystals and the deadlock | Aug 18–19 | 95 | The tint pass, the freshness engine, the night it went silent |
| 5. The running order | Aug 20–21 | 80 | A schedule with the force of law, an application with a name |
| 6. The orchestrator and the pause | Aug 22–24 | 62 | Gates wired to nothing; what "paused" means |
| 7. Floors, garble, and doctors | Aug 25–28 | 23 | One conversation at a time; services that repair themselves |
| 8. Pulse and the Gazette | Aug 30–Sep 5 | 7 | A newspaper on the hour, and an outage with a cause |
| 9. The universe rhymes | Sep 6–9 | 56 | Every line a bar, System2, and the rejection queue |
| 10. Rooms and measurement | Sep 10–12 | 61 | Why is this line playing, and the loop that kept freezing |
| 11. Written down, and reachable | Sep 12–13 | 119 | The script becomes a document, and every cure gets a button |

---

## Era 1 — The box (Aug 8–9, 18 commits)

It starts as a recovery tool. The first five commits are a USB serial bridge, a console,
a port list that shows only real devices, and a troubleshooter that watches for the box
arriving and says why it has not. The Pine Box was hardware that would not come up, and
the first thing written was a way to talk to it.

By the sixth commit there is a DJ say-menu, replay, and a cover flow that fills the
panel. By the next day the box hears **"play X"**, the station starts, the DJ introduces
the track, and the track plays — `Spoken song requests`. Call-ins arrive the same day,
with web and manual research behind them.

Two commits here set a pattern that repeats for the next month:

- `Song requests no longer hijack ordinary questions; word-boundary matching` — a feature
  that worked too well and ate the thing next to it.
- `Detect that the satellite cannot be told to listen; remove the button that could never
  work` — a control wired to nothing. There will be many more.

## Era 2 — It becomes a station (Aug 14–16, 68 commits)

Five quiet days, then the largest burst of the project. This is where a panel with a play
button becomes a broadcast.

**The air.** `Play means play, one clock for every device` fixes the thing that made
everything else unmeasurable. `#634 an ENGINEER station between the voice and the air`
puts a stage between what is written and what is heard. Then the central idea of the
station arrives in three cuts on one day:

> `#689 third cut: the talk runs BESIDE the record, not in front of it`
>
> `#700 talk radio that never stops, over records that never stop either`

**The door.** `#687 a public listener door on its own port`, then `#687 the public link,
carried by Funnel`, then `#689 an ON AIR light in the header, with the switch and the way
out`.

**The second engine.** `#726 F5-TTS is a second, swappable cloning engine` — the first
admission that one TTS is not enough. The engine bench in Era 3 grows out of this, and
the 12-second reference-clipping trap that comes with F5 is recorded in
[f5-tts-server](docs/notes/f5-tts-server.md).

**The first honest bug report.** `#690 the box was never down; two bugs made it look dead
forever`, and the day after, `#690 a switched-off box is not a broken box`. This is the
era's lesson and the repository's recurring one: *the diagnostic was wrong, not the
machine.*

**The first anti-repeat rule.** `pine-no-repeats: an hour where a phrase may not come
round again`. It is rebuilt several more times, and in Era 10 it is finally measured and
found to have been resetting on every restart.

## Era 3 — The Voice Director (Aug 17, 19 commits)

One day, nineteen commits, and a whole subsystem.

`#786 the Voice Director: an engine bench, characters, and a service` — a registry of TTS
engines that can be benchmarked against each other, with roles pinned to voices and a
`/feel` route for delivery. Kokoro goes live on the host the same day. Wake words arrive
(`#787-#792`), trained later into `hey_dj.tflite`
([openwakeword-training](docs/notes/openwakeword-training.md)).

The day also produces the station's self-observation gear — the observatory, the deck,
the status bar ("the machine's own ticker tape"), the terminal that reads "like the
station's black box". Much of it is later found to be measuring the wrong thing; see
[dead-air-and-staleness-measurement](docs/notes/dead-air-and-staleness-measurement.md)
and [which-pile-a-road-lives-on](docs/notes/which-pile-a-road-lives-on.md).

And one commit that names the whole problem of the project:

> `#796 the whole machine was wearing ComfyUI's name`

## Era 4 — Crystals and the deadlock (Aug 18–19, 95 commits)

The two biggest days in the history, and the first serious outage.

**The crystal.** `#815/#816 crystals, and the vector store stops strangling the show`
introduces the tint: a second pass over written material that rewrites it in a
character's voice. Within a day it reaches the source rather than the instructions
(`#834 crystals tint the SOURCE, not just the instructions`), and the SFX guy and the
crystal cabinet arrive with it
([sfx-guy-and-crystal-cabinet](docs/notes/sfx-guy-and-crystal-cabinet.md)).

**The freshness engine.** `#824/#825 the 24-hour no-repeat guarantee`, then `#809 the
freshness engine: a repeat is never dead air`. The principle — silence is worse than
repetition — holds for the rest of the project and is still the rule in
[repertoire-dead-air-lcd](docs/notes/repertoire-dead-air-lcd.md).

**The guaranteed voice.** `#842 THE GUARANTEED VOICE — a line always has audio, and no
ceiling on what the cast may say`.

**The night it stopped.** Late on Aug 19, in order:

> `#850 the two fatal findings from the 41-agent audit`
>
> `#851/#852/#853 break the oscillator, wake the watchdogs, watch the floor`
>
> `#854 THE DEADLOCK THAT SILENCED THE STATION`
>
> `#856/#857 the DJs stop killing the record, and the station repairs itself unasked`
>
> `#869 THE STATION IS LIVE — stale dialogue leaves the shelf`

Also this era: `#826 the sting scan was strangling the event loop`. The event loop is
strangled by something else roughly once a week from here on — see
[event-loop-starvation-watchdog](docs/notes/event-loop-starvation-watchdog.md),
[silent-station-needle-and-stores](docs/notes/silent-station-needle-and-stores.md), and
Era 10.

And the larder is born: `#873-#877 the larder finally holds rounds, and the writer stops
being the bottleneck`. It is banked written dialogue — **text only**, which matters
enormously later: "prewritten" rounds still pay full TTS
([dialogue-pipeline-diagnostics](docs/notes/dialogue-pipeline-diagnostics.md)).

## Era 5 — The running order (Aug 20–21, 80 commits)

The station gets a schedule, and the schedule gets teeth.

`#937/#938 the running order is the law, and you can watch it being kept`, followed by
`#951/#952 the clocks obey the sheet, and the hour stops restarting at entry one`. The
coordinator looks ahead (`#944`), the director studio and prompt book land (`#945`), and
`#932 a prepared round writes down which clips it is holding`.

The other half of the era is the Pine Box ceasing to be a script and becoming a product:
`#971 Pine Box is an application, with a name, a mark, and a pin that works`, `#976 the
pine on a box everywhere`, `#979 Application means all of it, out of the application`.
The icon-cache trap that made the pin paint the Electron atom (`#972`) is in
[pinebox-desktop-launcher](docs/notes/pinebox-desktop-launcher.md), along with the
stale-runner trap that caused a white popup much later.

Two findings from this era became permanent rules:

- `#983 the agent's prompt and the station's are two different prompts` — the operator's
  chat prompt does not reach the air. Confirmed again in Era 9, when a register audit of
  31 gates found that nothing anywhere blocks swearing
  ([station-register-and-swearing](docs/notes/station-register-and-swearing.md)).
- `#1004/#1003/#1002 the station was deleting the radio it had just made`. This one comes
  back in Era 9 as the gold freeze.

`#1006 the tint is a second pass now, and both versions are kept`, and `#1017 the vault,
and nothing leaves the shelf on its own again` — the first attempt at not throwing away
finished work. It did not take; see Era 9.

## Era 6 — The orchestrator and the pause (Aug 22–24, 62 commits)

Three days on two questions: *does this control do anything*, and *what does paused
mean*.

**The tint learns to rap.** `#1031-#1036 the tint raps now, and the model was the ceiling
all along`, then `#1037 verse keeps its lines — the cause underneath every other cause`.

**The cupboard.** `#1052/#1053/#1054 the repeats cupboard — pre-rolled airtime, kept and
reused`, and `#1068/#1069/#1070 the commitment board — every coming segment decided in
advance`.

**Controls wired to nothing.** This is the era's real subject, and it produced the most
frequently re-used note in the project,
[orchestrator-dead-wiring](docs/notes/orchestrator-dead-wiring.md) — *the desks were
sound but unreachable; ask "called / runs / changes anything" before reading logic.*

> `#1091 four gates wired to nothing: rows against seconds, a veto counting deleted
> audio, a decision on a browser poll, and a guarantee inside an except`
>
> `#1092 "a fresh one is queued so this does not come round again" was not queuing
> anything`
>
> `#1096 three dials the operator could turn that were not connected`
>
> `#1086 ... and a function I wrote that lied`
>
> `#1101 a gauge pinned at its own ceiling reads exactly like no progress`

**What "paused" means.** Aug 23 is spent entirely on it, and the answer took seven
commits to find:

> `#1115/#1116 paused shut the door on speech and left the records playing`
>
> `#1117 there were three broadcasts, and pause had only stopped one`
>
> `#1118 "both" meant two broadcasts, not one show heard in two rooms`
>
> `#1120 my own pause gate was destroying the material the pause exists to bank`
>
> `#1124 a station that is not airing is not behind`
>
> `#1126/#1127 ... paused is a silenced booth rather than a silenced station`

The corollary — that a pause is the station's chance to bank work — is re-measured in Era
8 and found to have been banking nothing after hour five
([pause-banking-and-records-underneath](docs/notes/pause-banking-and-records-underneath.md)).

## Era 7 — Floors, garble, and doctors (Aug 25–28, 23 commits)

Fewer commits, each much larger.

`#1142 the bookkeeping was strangling the switchboard - four memos give the event loop
back to the show` — the unpause-silence root cause, written up in
[event-loop-starvation-watchdog](docs/notes/event-loop-starvation-watchdog.md).

`#1146 the floor, the memo book, and the lesson - conversations air one at a time` — the
`_FLOOR_LOCK` round gate. And then the one that names its own bug precisely:

> `#1147 the garble had five mouths - every way two clips could sound at once, closed`

The five mouths (leaked elements, a shell unmute war, detached tune players, a boot feed
epoch, one append door) are in [floor-and-paced-air](docs/notes/floor-and-paced-air.md).

The era ends with the station learning to fix its own dependencies: `#1152 the comfy
doctor - ask what's wrong and watch it get fixed`, and `#1153 the services steward - ask
after the stack, and it answers, repairs, and proves it`. This is the first appearance of
a rule the operator later made standing: **every hand-applied cure must become a rung the
orchestrator can press itself** ([every-fix-becomes-a-tool](docs/notes/every-fix-becomes-a-tool.md)).

## Era 8 — Pulse and the Gazette (Aug 30–Sep 5, 7 commits)

Seven commits, most of them large enough to have their own notes.

`#1154 a command is a sentence, not a cameo - the mystery pauses were the mic hearing the
show`. The station had been pausing itself, because its own broadcast — picked up by the
room microphone — contained the words "pause the radio".

`#1156 the pulse names the blocker` came out of a real outage: CIFS over Wi-Fi crawled,
sync saves starved the loop, and a watchdog storm followed. Separately, a Nabu speaker
that answers ping but refuses every port turns out to mean firmware-down, and needs a
power cycle ([pulse-library-and-firmware-down](docs/notes/pulse-library-and-firmware-down.md)).

`#1019 the Gazette - a newspaper printed on the hour off the station's own log`. Over
Sep 4–5 it grows real pages, a PDF writer, a screenplay and a slideshow.

## Era 9 — The universe rhymes (Sep 6–9, 56 commits)

The most ambitious change in the project: **every line the station says, while a crystal
is held, must be a bar.**

> `#1064 the universe rhymes - every line a bar while a crystal is on`
>
> `#1064 the hold is the rule: meaning grade, every road, one ask per round`
>
> `#1064 the cut before the studio - a line that will not rap is cut, the bars are the
> round`

It immediately collides with the air. `#1063 the tint yields to the air` and the note
[tint-yields-to-air](docs/notes/tint-yields-to-air.md) record the settlement: the hold is
on by default, the tint gets its own lane, three asks per line, and the air always wins.
A documentation section was written specifically for *when the hold starves the air*.

**System2.** `#1068 #1069 #1070 System2 drives the station; the rhyme lookup leaves the
loop; no line twice inside an hour` — a new writing engine becomes the default, with
fallback and `legacy_keepers` dials
([system2-handoff-and-switch](docs/notes/system2-handoff-and-switch.md)).

**The request book and the lanes.** `#1079 #1080 #1081 #1082 the request book, two lanes
and the schedule's permit, one cacheable prefix, the strike cap and the fault memo`. Two
Ollama slots were measured and found *slower* than one (0.96×), so the stack went back to
`OLLAMA_NUM_PARALLEL=1`
([request-book-lanes-strikes](docs/notes/request-book-lanes-strikes.md)).

**The rejection queue.** Four separate audits, because the queue kept lying about itself:

- `#1088 rejection notices: machine-handled refusals are notes, only a cut is pending`
- `the evaluator reconciliation: the audited false refusals fixed rule by rule`
- `The deep scan: the readers stop refusing rhymes, the queue drains itself` — 1,205 of
  1,884 "rhyme suggestions" were not rhymes at all
  ([rejection-deep-scan-and-stack](docs/notes/rejection-deep-scan-and-stack.md))
- `The rejection queue read row by row: four false refusals closed, one panel lie` — the
  panel's "623" was a running event tally; the real queue was 174
  ([rejection-queue-amiable](docs/notes/rejection-queue-amiable.md))

**The retirement desk** arrives — `nothing rhymed leaves the cupboard without the
operator's answer` — and then the finding that justified it:

> `#1157 a rhymed line is not deleted, and the bank fills the air`

The retirement desk had **never recorded a single row**, because `resort_may_drop`
returned above `retire_may`. Six separate roads had been deleting rhymed work unasked.
An empty audit trail is not evidence that nothing happened
([gold-freeze-1157](docs/notes/gold-freeze-1157.md)).

Two measurements from this era set hard limits on everything after it:

- **Render is slower than speech.** `render = 2.97 + 1.05 × audio`. The marginal term is
  above one, so continuously live-rendered talk is arithmetically impossible; only banked
  material can fill a hole, and shorter lines make it worse
  ([render-is-slower-than-speech](docs/notes/render-is-slower-than-speech.md)).
- **The anchor floor, not the prompt**, was why the writer kept landing on furniture
  ([rhyme-variety-flow-calls](docs/notes/rhyme-variety-flow-calls.md)).

## Era 10 — Rooms and measurement (Sep 10–12, 61 commits)

The last era is the station being audited by its own operator, hard, and mostly failing.

**The rooms.** The writers room, the script desk (`an edit is a training pair`), the
director's room, Cupboard View, the conductor's stage, the SFX desk. And the one that
made everything else checkable:

> `Why is this line playing: the whole chain, from the clip back to the prompt`

**The loop, again.** Four separate freezes, each with a number attached:

> `The talk yields to the record: an unbounded await stopped the music for 21 minutes`
>
> `The banned list is not checked sixty times a second`
>
> `One check re-read a file per line, and the loop froze 16% of the show`
>
> `A 625 MB JSON parse on the event loop, once per restart`

`Retention for three stores that had none, and a hot read off a contended lock` — 7.5 GB
of store with no retention policy at all
([silent-station-needle-and-stores](docs/notes/silent-station-needle-and-stores.md)).

**Everything measured turned out worse than it looked.**

- 43.6% of aired lines were exact repeats. `emergency_host` was 28 lines across 919
  airings — a 97% repeat rate — while 1,416 unused gold bars sat beside it. The one-hour
  cooldown map lived only in memory, so every restart reset it
  ([repetition-on-air-measured](docs/notes/repetition-on-air-measured.md)).
- `Eighty-eight recorded phone calls, and one word refusing all of them.`
- `Twenty-eight lines carrying a fifth of the air.`
- `"The hour on air" was whichever hour came first in the list.`
- `A dead lease is not an active performance: thirteen corpses had stopped the
  orchestrator planning.`
- A `caller_per_hour` quota of 10 against 4 sheet entries produced a deficit that never
  closes, so calls pre-empted the manager permanently — 81 call lines and 0 manager lines
  in one hour ([quota-outranks-the-sheet](docs/notes/quota-outranks-the-sheet.md)).
- `A draw of one is not a draw`, and the rest of the randomness audit.

**The orchestrator gets hands.** `The orchestrator gets a lever on the air`, `The station
says when it is stuck, and offers to unstick itself`, `The restart rail, and an
orchestrator that works the silence instead of watching it`, `The one rung that can
actually help a congested loop` — the operator's standing rule, finally applied across
the board.

The commits immediately before this repository was published, still the same kind of
finding the project had been making since Era 4:

> `The line that was read 385 lines before it was written`
>
> `A 625 MB JSON parse on the event loop, once per restart`
>
> `The debt paid to the road that earned it, and the binding shown`

## Era 11 — Written down, and reachable (Sep 12–13, 119 commits)

Publication changed nothing about the work. `The chronicle: ten eras, 489 commits, and
the notes underneath them` went up, and the next hundred and nineteen commits went at the
two things the audit of Era 10 had left standing: a script nobody had ever written down,
and cures nobody could reach.

**The script became a document.** There had never been a script. `screenplay_compose`
rebuilt the hour out of `air_log.jsonl` on every poll, ordered it by `air_at` — a field
eight separate paths rewrite — and then ran four corrective passes to undo what the clock
had got wrong. `The script's own sequence decides, not a timestamp`, and then `The script
is kept, not rebuilt`: `data/script_ledger.jsonl` records the running order as `(block,
ord)`, assigned once before a round is audible and never rewritten after. The SFX guy is
committed in position with everybody else, because his cadence and his random roll already
happen at assembly time — that was never the problem, it had simply never been written
down
([script-ledger-and-the-reading-order](docs/notes/script-ledger-and-the-reading-order.md)).

Then the reading order itself. Anchoring a whole block at its earliest time meant that
anything which happened *during* a round sorted to the far side of it — 15 backward pairs
in 365 elements, worst 93.3s, every single one of them `dialogue → action`. Giving each
row its own stamp and making them monotone across the block — `A conversation is anchored
on the one stamp that is never rewritten` — left 0 backward pairs in 558 elements, 0 order
inversions, 23 of 23 SFX rows still inside their own conversation, and 47 previously
unledgered events now sitting inside the block where they happened.

**The chrome could not hear the panel.** The SCRIPT view placed its highlight from the DJ
voice element's `currentTime`, and went looking for that element with `querySelectorAll`
in the Electron chrome — whose document holds exactly one `<audio>`. The voice elements
belong to the panel, and the panel runs inside a `<webview>`. So the scan returned null
ALWAYS, not sometimes, and the view silently ran on the clock estimate that three earlier
tickets existed to replace
([the-chrome-cannot-see-the-panel](docs/notes/the-chrome-cannot-see-the-panel.md)).

**One tap grew from five rungs to twelve.** `One tap now reaches every cure the station
owns, and RELEASE finally runs`, then `The out-loud switch is a cure too, and the ladder
now counts to twelve`. The audit behind those two found four cures that existed as working
code with no button anywhere that reached them — RELIEVE, PAGES station-wide, DEEP and
SERVICES — plus `_floor_break`, the cure for a deadlock that had put the station six
minutes off the air with 134 finished rounds sitting on the shelf, which had one caller
and no operator path at all
([every-fix-becomes-a-tool](docs/notes/every-fix-becomes-a-tool.md)).

> A cure the operator cannot reach during the fault it cures is not a cure the station
> has.

**And the button could not reach its own rung nine.** `reload_pages` reloads every page,
the operator's own included, and no resume mark was written — so DEEP, SERVICES, RELOAD
and RESTART never ran, while the transcript's last line read like success. `The ladder
could not reach its own rung nine, and ON AIR never touched the switch.`

**Polling is not consuming.** A freshly launched desktop claimed the audio exclusive with
its play switch on, polled steadily enough that the stopped-polling test passed, and
acknowledged nothing at all — while two tablets that had played 52 and 50 clips sat muted
75 and 74 times waiting for it
([audio-owner-and-the-play-switch](docs/notes/audio-owner-and-the-play-switch.md)).

**Most of the era is instruments**, built on top of all that: a sampler that `keeps the
last two minutes of air, and a pad can be cleared, tuned or carried away in a kit`, a kit
`an MPC can open`, `DGX Terminal: a shell on the Spark, and the three bugs between here
and typing`, a camera `window of its own, streamed from the tablet`, `Right-click any line
anywhere, and inspect it in conversational context`, and `Carbon icons, not emoji`.

And it closes on three diagnostics that lied, each caught only by measuring it: a
`health.gagged` that had never existed; then `Two different gags wore the same word`, a
`gagged` that meant a different fault from the one the rung was asking about; then a
`solo_gagged` that read True with the station audible — `Sixty seconds, because at thirty
the gagged light came on with the station audible`.

---

## What the whole thing taught

Read in order, the same five lessons keep arriving with different names on them.

1. **The diagnostic lies before the machine does.** `#690 the box was never down`;
   `#933 "the works are unreachable" was a lie`; the panel's "623" was an event tally; an
   empty audit trail is not evidence; six readers reported "empty" about full roads.
   Before reading the logic, ask whether the thing reporting the problem can see the
   problem ([which-pile-a-road-lives-on](docs/notes/which-pile-a-road-lives-on.md)).
2. **A control that is not called is not a control.** Whole desks were correct and
   unreachable for weeks. Ask *called / runs / changes anything* first
   ([orchestrator-dead-wiring](docs/notes/orchestrator-dead-wiring.md)).
3. **Anything that can block the event loop eventually will.** A sting scan, a
   bookkeeping pass, `nvidia-smi`, a 625 MB `json.load`, a file re-read per line, an
   unbounded `await`. This is a soft-real-time system wearing a web app's clothes.
4. **Silence is the only true failure.** Repetition, staleness, and a worse take are all
   preferable. Every guarantee in the codebase resolves to *say something*
   ([repertoire-dead-air-lcd](docs/notes/repertoire-dead-air-lcd.md)).
5. **Finished work must not be thrown away.** It was, repeatedly, by six different roads,
   for a month, before anyone noticed — because the deletions left no trail
   ([gold-freeze-1157](docs/notes/gold-freeze-1157.md)).

And one standing rule that came out of all of them:

> Every hand-applied cure must become a rung the orchestrator can press itself.
