# Rendering

What speech costs on this box, why, and every dial that changes it.

Every number here is **measured on the live station**, not estimated. Where a
number is an assumption, it is labelled as one — and one of the worst bugs this
station has had was an assumption that nobody ever checked (see §5).

---

## 1. The engines

`ENGINE_REGISTRY` holds them all. What matters is the family:

| engine | family | speed | identity |
| --- | --- | --- | --- |
| `piper` | fixed voices, ONNX, Wyoming :10200 | far faster than real time | not a clone |
| `xtts` | zero-shot clone, :8770 | ~2.7–3x slower than real time | the house standard |
| `f5` | zero-shot clone, :8772 | roughly 5x faster than XTTS | +0.12 identity on normal copy, worse on one-word interjections |
| `indextts` | zero-shot clone, :8774 | — | configured |
| `voxtral` | preset voices | — | experimental |

At the time of writing **only `xtts` and `piper` are up**. `GET /api/voice/engines`
reports readiness; an engine that is down is not an error,
the station simply routes around it.

`voice_engine_for(voice, who)` decides which engine a given seat uses.
`render_relief()` drops the pair to Piper when the clone engine is running slow
enough that the show would otherwise stall — cached lines are still harvested,
nothing new is commissioned on the clone until it recovers.

### The XTTS call

`_xtts_synthesize(text, voice)` posts to `{XTTS_URL}/synthesize` with the
reference wav base64 on **every** call. Two things about that server:

- **It reports failures as HTTP 200 with a JSON body.** The content-type is the
  truth, not the status code. `_xtts_synthesize` checks for `audio/` and raises
  otherwise. Do not remove that check.
- `speed` is applied *inside* the model, not by time-stretching the finished
  clip, so a faster read still sounds like the person rather than a tape
  running fast. `speech_rate` in the DJ settings drives it, clamped 0.75–1.25
  at both ends.

---

## 2. The measured cost of a round

The task ledger (`task_cost`, `task_gain`, `task_rate`, `task_stat`) records
what every kind of work on this station actually costs and what it bought.
`TASK_LEDGER_TRUST` is how many samples it wants before it calls a figure
`measured`.

Live figures at the time of writing:

| road | cost (room seconds) | airtime bought | rate |
| --- | --- | --- | --- |
| a phone call | 273 | 96 | **0.351** |
| a painting round | ~256 | — | — |

A rate of 0.35 means **a third of a second of broadcast per second of work**,
which is exactly what you would expect from an engine running at ~2.85x slower
than real time. There is no waste to find here. The cost *is* the render.

### What that implies for an hour

`coord_capacity()` multiplies each enabled entry's minutes by what its road
costs and sums the hour:

```
the running order asks for 53 min of written speech an hour;
rendering all of it fresh would take about 137 min of room, and an hour has 60.
   a phone call        48 min of room
   banter              23 min
   a painting round    22 min
   an advert           19 min
   a news bulletin     16 min
```

Read that as: **the sheet is oversubscribed 2.2x.** Not a scheduling fault — an
engine ceiling. See `orchestrator.md` §5 for what the station does about it.

---

## 3. The budget, and standing down

The preparer must never become the reason the show is quiet.

- `prep_room_left()` — seconds left on the record playing. The budget always
  ends in `min(room, ...)`.
- `pantry_window()` — is there room to work at all. Asked before every line.
- `prep_should_stop()` — has this pass overrun its deadline, or does the live
  show want the room. `_PREP_DEADLINE[0]` is a single global; any block that
  runs work outside the main preparing loop must set and clear it in a
  `finally`, or that work runs with no deadline at all.
- `engine_prep_take()` / `ENGINE_BUDGET` — how much engine time preparing may
  take before it yields.
- `SHELF_UNVOICED_MOST` (3) — how many written-but-unvoiced rows a road may
  stack up before the writing desk should stop feeding it. Measured before this
  existed: the advert road held **twelve** written reads and had rendered none
  of them, for hours, while news, gallery, manager and caller all sat short.
  Every one of those was a model visit spent on something unusable.

---

## 4. The pantry as a cache

`pantry_key(text, voice, engine)` — identical words, same voice, same engine,
same clip. That is the whole caching strategy and it is why the recording room
can regroup a script by performer without breaking playback.

Ceilings:

- `pantry_max_rows()` follows `prepare_target_seconds()`, floored at
  `PANTRY_MAX_FLOOR`
- `PANTRY_MAX_BYTES` — the byte ceiling
- `VOICE_KEEP_BYTES` — what the voice media directory keeps
- `PANTRY_BURN_SECONDS` — the outer life of any clip

**Eviction order is load-bearing.** Loose clips first, oldest first; spoken-for
clips (`pantry_spoken_for()`) only if still over, and logged when it happens.
Getting this backwards deletes prepared material and was measured as the single
largest cause of on-air silence.

---

## 5. The assumption that cost the station its phone calls

Worth its own section because it is the archetype of the bug you should be
looking for.

`CALL_TURN_SECONDS = 35.0` was derived from a character count — "four to seven
sentences, 60 to 100 words... call it five hundred characters, so about
thirty-five seconds". Reasonable. Written down. Commented. **Never checked
against the station.**

The ledger measures a whole six-turn call at **96 seconds** of air. That is
about 12 seconds a turn, not 35 — out by a factor of three.

The consequence: `call_turns_for_slot()` asked "how many turns fit in a
four-minute entry", answered "six, because that fills 240s", and six turns ran
ninety seconds. A *phone call* segment had a phone call in the first ninety
seconds and nothing for the remaining two and a half minutes.

The fix is not a better constant. It is `call_turn_seconds()`, which divides
the ledger's measured airtime by the turn count those calls were actually
written to, clamped to no *longer* than the old estimate — erring long writes
short calls, which is the failure being fixed; erring short writes more turns
than needed, which the segment can absorb.

**The lesson generalises.** Any constant in this file that describes how long
something takes, how loud something is, or how much something costs should be
checked against a measurement before it is trusted. `task_stat()` exists to make
that cheap.

---

## 6. Dials, and what each one really does

| dial | effect |
| --- | --- |
| `talk_radio` (0–100) | scales the banter clock; high, it opens rounds with speakbox monologues |
| `talk_radio_mode` | the torrent — rounds run back to back *through* the record |
| `box_volume` (0.3–1.6) | amplitude baked into every clip **we render** — speech, stings and the phone bell alike. It can never touch a record, because a record is not rendered by us |
| `music_box_level` (0–1) | a real volume sent to the box's media player entity. Only sent when `box_volume_control` is on |
| `box_volume_control` | **off by default.** Whether the station may set the device's own volume at all. Off, the physical dial owns that number and the station never touches it |
| `speech_rate` | applied inside the model, 0.75–1.25 |
| `speakbox_rate` | at 1.0 this is a *guarantee*: material not used by the model is pasted in verbatim as a spoken turn |
| `speakbox_full_swath_rate` / `_chars` | how often, and how much, raw document lands ahead of a round's own work |
| the horizon dial | `prepare_target_seconds()` — how far ahead the preparer digs, and (via `pantry_max_rows()`) how much the pantry keeps |

The last three are the ones that most often make a round "not do what its entry
is for". `segment_audit()` names them in its log line when it catches one.
