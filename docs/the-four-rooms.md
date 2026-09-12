# The four rooms

Where a line of dialogue comes from, and where it goes.

```
    THE RUNNING ORDER              a sheet of entries, each with a kind and some minutes
            |                      schedule_take() advances it by the clock
            v
    THE WRITING DESK               a model turns the entry's brief into a script
            |                      dj_banter(), ask_model(), _MODEL_CALLS
            v
    THE RESERVE                    scripts waiting for a slot
            |                      _LARDER (banter) and _SHELF (everything else)
            v
    THE RECORDING ROOM             one actor at a time, line by line
            |                      larder_prepare() -> prep_render_line() -> voice_generate()
            v
    THE PANTRY                     finished audio, addressed by its own content
            |                      _PANTRY, pantry_key(text, voice, engine)
            v
    THE AIR                        speak_turns() / _banter_air() -> the box, the page, the app
```

Material only ever moves **down** this list. Nothing skips a room. A round that
fails in one room stays where it is and is retried; it is never lost silently.

---

## 1. The running order

**What it is.** A list of entries, each with a `kind` (one of
`SCHEDULE_KIND_NAMES`), a `label`, and `minutes`. Presets hold different hours;
`schedule_preset_now()` picks the one for this hour and `schedule_hour_slots()`
applies any per-hour override the operator has made.

**How it advances.** `schedule_take()` is called once per round. It walks the
clock forward from a saved position (`_RADIO["sched_pos"]`, persisted by
`_sched_pos_save()` so a restart does not restart the hour), and returns the
entry that owns the air right now. It also writes:

- `_RADIO["sched_kind"]` — what the next round is, so the writing desk can be
  given room and temperament to suit the job
- `_RADIO["sched_prompt"]` — the entry's standing instruction, cleared at the
  top of every round so it can never colour the next one
- `_RADIO["sched_slot"]` — the whole entry, for roads that need to read
  something pinned to it

**The map you will need constantly.** `SCHED_PREP_KIND` maps a running-order
kind to the *road* that prepares it. Several kinds share a road:

```python
SCHED_PREP_KIND = {
    "ad": "ad", "manager": "manager",
    "caller": "caller", "banter_caller": "caller",   # <- two kinds, one shelf
    "bombshell": "ad", "gallery": "gallery",
    "banter": "banter", "news": "news",
}
```

`CANNOT_PREPARE` names the kinds that can only be made live, with the reason:
a record is not a round, a recap reads the hour that just happened, a deep
conversation reads the last stretch of the show.

---

## 2. The writing desk

**What it is.** The model. `dj_banter()` is the door every road goes through —
gallery rounds, calls, memos, adverts and plain banter all end up there with a
different `angle` and a different line count.

**What it is given.** In order of authority:

1. the station's own system prompt and radio prompts
2. the entry's standing instruction, via `_schedule_clause()`
3. speakbox material — passages lifted out of the operator's own documents
4. the round's angle, written by the road (the paintings, the caller's premise,
   the memo)

**What it costs.** One visit, held behind `_OLLAMA_GATE`, which is why the desk
is described everywhere in the code as "the thing the whole station queues
behind". `_MODEL_CALLS` keeps the last forty exchanges — prompt as sent, system
prompt armed, what came back, model, milliseconds. That ring is short, which is
why a banked round carries a **copy** of its own paperwork (`entry["desk"]`,
`_desk_paper()`): by the time it airs, the ring has scrolled past it.

**A trap worth knowing.** The speakbox dials can overrule the brief. At
`speakbox_rate = 1.0` the grounding slider is a *guarantee*: if the round comes
back without the passage, the raw passage is pasted in as a spoken turn. With
`speakbox_full_swath_rate` high as well, a memo from upstairs can arrive as
several thousand characters of transcript with no memo in it. That is not a
bug in the scheduler; it is two dials doing what they promise. `segment_audit()`
exists to catch it — see `extending.md`.

---

## 3. The reserve

Two stores, same idea.

| store | holds | ceiling |
| --- | --- | --- |
| `_LARDER` | banter rounds | the horizon dial |
| `_SHELF` | everything with a road: ads, memos, calls, gallery, news, station IDs | `SHELF_CAPS` per road, `SHELF_ROW_CEILING` multiple |

A row goes in through **`shelf_put()`** and comes out through
**`shelf_take()`**. Those two functions are the only doors, which is what makes
it possible to stamp every row with a verdict (`row["brief"]`, `#968`) and to
implement rest-and-reuse in one place.

**`shelf_take()` refuses a row for reasons, and says them.** A row is skipped
when it is burnt (older than `PANTRY_BURN_SECONDS`), when it has already aired
and its road is not in `SHELF_REUSABLE`, when it has used its innings
(`SHELF_REUSE_MOST`), when it is still resting (`SHELF_REUSE_REST`, three
hours), when its clip has been pruned, or when it was written against a
contract that has since moved. If every row is refused it logs *why*, because
"the shelf is stocked and the air is live" is otherwise unexplainable.

**Reuse.** `SHELF_REUSABLE` roads keep an aired row rather than consuming it —
stamped with `aired_at` and an `aired` count, sorted to the back. Fresh always
goes first; reuse is what happens when the desk is behind, never a substitute
for writing.

**Persistence.** `SHELF_PATH` (`data/prep_shelf.json`) is written on change and
read at startup. Rows restored from disk **bypass `shelf_put()`**, which is a
standing hazard: anything you stamp in `shelf_put()` must also be stamped on
the restore path or it will be missing for exactly the rows that survived a
restart.

---

## 4. The recording room

**`larder_prepare(entry)`** takes one banked round and makes its audio.

1. `banter_turns()` parses the script into `(marker, text)` turns.
   Markers: `A` host, `B` co-host, `C` caller, `D` third, `E` second caller.
2. `_round_chunks(turns, voices, caller_name)` turns that into the exact
   `(text, voice, who)` list the air road will ask the engine for. It mirrors
   the playlist build deliberately — anything it gets wrong is a cache miss,
   which is just today's behaviour.
3. **The plan is regrouped by performer** before a word is made. The script
   alternates speakers; rendering in script order makes the engine swap speaker
   conditioning on every line. Grouping lets one actor run everything they say
   in one sitting.
4. Each line goes to `prep_render_line()` → `voice_generate()`, and the result
   is written to the pantry under `pantry_key(text, voice, engine)`.
5. `prep_note()` publishes who is at the microphone and how far through.

**Why the regrouping is safe.** The pantry is *content-addressed*. Playback
looks each line up by its own text, so the order takes were recorded in has no
bearing at all on the order they air. Nothing is spliced and no boundary is
guessed. `#934` keeps each line's place in the script beside it so the
transcript still reads in the order it is spoken.

**Why it is per-round and not per-actor-across-all-rounds.** Measured on this
box, grouping across rounds saves roughly a tenth of the render time — and it
would mean no round is finished until every actor has been through, so the
first airable round arrives much later. The round is the unit that can go on
the air, so the round stays the unit that gets finished. `GET
/api/rooms/call-sheet` shows who is owed what across the whole reserve if you
want to see the cross-round picture anyway.

---

## 5. The pantry

**`_PANTRY`**, keyed by `pantry_key(text, voice, engine)`. That key is the
whole design: identical words in the same voice on the same engine are the same
clip, so a line prepared hours ago is found instantly by the air road without
anybody having to track which round it belonged to.

**Eviction is the dangerous part.** `pantry_max_rows()` follows
`prepare_target_seconds()` with a floor of `PANTRY_MAX_FLOOR`, and there is a
byte ceiling as well (`PANTRY_MAX_BYTES`). When either is exceeded:

1. **loose** clips are shed first, oldest first — those are clips no banked
   round is relying on
2. only if still over does it touch clips that are **spoken for**
   (`pantry_spoken_for()`), and it says so in the log when it does

Getting that order wrong is how a station deletes the material it just spent an
hour making. It was measured: fixing the eviction order took the longest
on-air silence from 157s to 81s in one change.

`PANTRY_BURN_SECONDS` is the outer life of a clip. `pantry_window()` is the
question "is there room to work right now" — the preparer asks it before every
line.

---

## 6. The air

`speak_turns()` puts an exchange out turn by turn. `_banter_air(entry, track)`
is the door a *prepared* round goes through, and it is the single place every
banked round passes on its way to the air — which makes it the right place to
bind anything that belongs to the round rather than to the station (the
gallery's pictures, for instance).

Three destinations, routed independently: the Pine Box (`music_to`, `voice_to`,
`reply_to`), this app, or both. A line the box accepts and never plays is
**held** — `_BOX_HOLD` — and a wedged box diverts to the page rather than
silencing the show.

Every aired line is written into `_RADIO["chat"]` — the booth log — with its
id, who said it, the voice, when it will actually be audible (`air_at`, not
when the batch was written), and its dossier.
