# The Crystal and the Orchestrator

How Pine Box FM writes, tints, records and schedules a broadcast — and how
those four things depend on each other.

This is a companion to [`the-orchestrator.md`](the-orchestrator.md), which
covers scheduling in depth. This one is about the **whole loop**: where words
come from, what the crystal does to them, and why the scheduler and the
tinting pass are not two systems but one system with two appetites for the
same scarce resource.

---

## 1. The one-paragraph version

The station writes dialogue with a language model, rewrites that dialogue into
the voice of a **crystal** — a styled corpus, currently MF DOOM — records the
result with a cloned voice, shelves the recording, and airs it against a
running order. The orchestrator decides what to write next, how far ahead to
work, what to do when there is no time, and what to give up when the hour
cannot be made. **Every one of those decisions and the tinting pass spend the
same model.** That contention is the central fact of the system, and almost
every fault worth knowing about is a version of it.

---

## 2. The four rooms

| Room | What happens | What it spends |
|---|---|---|
| **The writing desk** | A model writes a script for a segment | model time (`_OLLAMA_GATE`) |
| **The crystal** | A second pass rewrites that script into the crystal's voice | **the same model time** |
| **The recording room** | TTS renders lines to audio (XTTS clone, or piper) | GPU / CPU render time |
| **The shelves** | Finished audio and scripts wait to air | disk, and freshness |

Material flows desk → crystal → recording room → shelf → air. It can also skip
steps: a script whose render was refused is banked as **words alone** (`#904`)
and voiced later; a round that airs before the crystal reaches it goes out
plain and can be rewritten on a later pass (`#1068`).

The shelves are three:

- **`_LARDER`** — banked *banter* rounds. Text plus, usually, rendered audio.
- **`_SHELF`** — everything else, per road: ads, news, gallery, callers,
  manager memos, station IDs, track talk.
- **`_PANTRY`** — the render cache. Audio keyed by exact text; if the text
  changes, the key misses and it must be recorded again.

That last sentence is load-bearing and is the cause of a whole class of bug.
**Rewriting a script after it has been recorded invalidates its audio.** Any
code that tints late must drop the render keys with it (`#1077`, `#1104`).

---

## 3. Where lyrics come from

"Lyrics" here means the actual spoken lines. They have three sources, blended:

1. **The model's own writing.** Given a system prompt describing the segment,
   the cast, the hour and the station.
2. **The speakbox** — the operator's document library, chunked and embedded.
   Passages are drawn in and woven into lines: a *prepend*, an *append*, or a
   full **swath** of up to 3,000 characters. Chunks carry a cooldown so the
   same passage does not recur (`chunk_serve`, `chunk_cooling`).
3. **The crystal's own minds** — passages from the styled corpus itself,
   sampled at random rather than by similarity, because the second pass is not
   looking for the passage that *matches* the conversation. It is looking for
   **the world the conversation is being moved into**, and a spread of that
   world is a better sample of it than the nearest neighbour.

A crystal may be configured with `sources_words: false`, which means: *tint the
writing, but let the speakbox keep supplying the raw material.* That is
deliberate and is what the console means by

> *"the DOOM crystal is tinting the writing, but the swath stayed in the
> speakerbox"*

It is not a fault. It is the operator's instruction: **the crystal supplies the
voice, the speakbox supplies the subject.**

---

## 4. The tinting pass — what it actually does

There are **two** tinting mechanisms and they are easy to confuse.

### The clause (first pass)

A description of the crystal is injected into the writing prompt: its
vocabulary, cadence, imagery, disposition, rhetorical style. It scales with
`strength` (0–100). At 75 and above the instruction says the tint is *total* —
diction itself warps, internal rhyme surfaces mid-sentence, station business
gets reframed through the crystal's world.

This is cheap. It happens on every write. It is not what the operator means by
"the tinting pass".

### The rewrite (second pass)

The finished script is handed back to a model with the crystal's own passages
and an instruction to **put it in that world's mouth**. This is where the
lexicon, the allegory, the simile and the metaphor come from, because the model
is no longer inventing content — the content is fixed, and its only job is
transformation.

The rubric it works to:

- **Lexicon.** Adopt the crystal's vocabulary, not merely its topics.
- **Cadence and rhyme.** Internal rhyme, multisyllabic chains, bar structure.
  This is why the rewrite runs **turn by turn** rather than whole-round
  (`#1021`): a small model cannot hold a rhyme scheme across a whole
  conversation, but it can across one turn. Each turn is given the *previous
  turn as already tinted*, so the pair land on each other's rhymes instead of
  each rapping alone.
- **Allegory and metaphor.** The crystal's characteristic figures — for DOOM,
  supervillain logic, mask mythology, food-as-metaphor, cartoon menace played
  dead serious.
- **What must not change.** Quoted material is protected: any verbatim swath
  from the speakbox is listed as *"leave these passages exactly as they are"*.
  Facts, names and the station's own identity survive the rewrite.
- **What must never appear.** The rewrite must not mention the crystal, the
  lyrics, the writer, or that anything was rewritten. The listener hears a
  radio station with a voice, not a machine doing a style transfer.

A real before-and-after from the station's own trail:

> **Plain:** *"Coming up next on Big Apple's Little Pine Box FM Station, here
> is Sol Tapado by Thievery Corporation. This track is going to hit you with
> that atmosphere right off the bat..."*
>
> **Tinted:** *"Big Apple's Little Pine Box FM / where we over charge em /
> Thievery Corporation bringing Sol Tapado and Patrick de Santos to target em /
> hitting raw like elements of atmosphere, a deep territory journey for the
> ears / see the layers in the haze as it settles, pulling you in till the
> vision clears"*

That is the transformation. When people say the crystal is missing, this is
what is missing.

---

## 5. Why the crystal and the scheduler fight

**The rewrite is a model operation.** It queues on the same `_OLLAMA_GATE` as
every piece of writing the station does. Measured, the tint has run at up to
58% of all model load, and 40% of writing-desk time while it is active.

So the station cannot simply "tint everything" — every rewrite is a segment
that did not get written. The resolution is a **budget**: the rewrite may take
a share of the hour's model time (`TINT_SHARE`) and no more.

Three things about that budget are hard-won and must not be undone:

1. **It must be a share, never a threshold.** `#1063` replaced a
   reserve-depth brake that measured *below its threshold in 153 of 153
   samples* — an off switch with a comment explaining why it should not be.
2. **It must be paced, not spent greedily.** An hourly total with nothing
   metering it in between is consumed in one burst at the top of the hour, and
   the station airs plain for the remaining thirty-five minutes. That is
   exactly what happened, and it is why `tint_spent()` is now a **leaky
   bucket** that drains continuously (`#1105`).
3. **The cost side matters more than the budget side.** The rewrite was
   running on a 31-billion-parameter model at a mean of 29.6 s per turn while
   the station wrote on a small model at 14.4 s — and the budget is charged in
   *wall-clock*, so model-swap and queue time are billed to the crystal too.
   Halving the cost buys more tinted radio than doubling the allowance.
   `tint_model_now()` therefore takes the big model while there is headroom and
   the fast one when there is not.

---

## 6. How the orchestrator works, in one page

The orchestrator answers one question repeatedly: **what should the station
build next, and what should it do if it cannot?**

Its desks, in the order they are consulted:

1. **`shelf_full()`** — is this road already covered? A road called full is
   invisible to every desk below, so this gate must measure *what could
   actually air* (audio present, innings left, rested) and not merely count
   rows.
2. **`commit_board()`** — for each coming entry: is it *ready*, *fresh*,
   *tight*, or must it be a *prerecord*, a *piper* take, or a *cut*?
3. **`prep_deadline_pick()`** — something arrives soon with nothing for it;
   this outranks the ledger, because a deadline is not an optimisation.
4. **`slot_needs()`** — what the coming half hour is short of.
5. **The ledger** — `task_rate()` = gain × odds ÷ cost, from measured p90s.

And when there is no time, it degrades **on purpose**, in this order:

- air a **repeat** from the cupboard (it was made properly),
- else make it fast on **piper** voices (`#1087` — *"not the best idea, but
  better than no segment"*),
- else give the entry's airtime back to a **record** and queue the segment for
  next time (`#1093`),
- else let the record run on and **owe** the road one (`arrears`).

The floor under all of it: **the pair must never stop talking.** The talk
watchdog (`#1088`) measures time since a *cast line* aired — not since "air",
which a spinning record satisfies — and covers a gap from a pre-stocked pool
that needs no model call, so it can never itself become the thing being waited
on.

---

## 7. How they work in tandem

The loop the operator is aiming for:

```
stack ahead  ->  the recording room gets slack
     ^                      |
     |                      v
buy more time  <-  spend the slack on richer writing,
                   deeper speakbox draws, and the crystal
```

Three settings govern it, and they answer **different questions**. Conflating
any two of them has caused a fault:

| Setting | Question it answers | Do not use it for |
|---|---|---|
| `prepare_hours` | How deep should the reserve eventually be? | anything urgent |
| `dialogue_reserve_target` | How many banter rounds to bank? | how many are *enough to coast on* |
| `TINT_SHARE` | What fraction of model time may the rewrite take? | whether to tint at all |

- **Stocking goal vs safety margin.** The larder yields to a starved road only
  *above a floor*. Setting that floor equal to the stocking target means it is
  satisfied only when the target is met exactly — which, on a consuming
  station, is never (`#1100`).
- **Stocking goal vs being ahead.** "Are we far enough ahead to spend room on
  something richer?" is a question about **the next hour**, not about the
  long-term goal. Measuring surplus against the goal means the more ambitious
  the operator, the poorer the station judges itself (`#1103`).

---

## 8. The failure modes, and how to recognise them

Everything below has actually happened.

**The crystal goes quiet.** Almost always the budget, not the crystal. Check
`/api/dj/pipeline` (**not** `/api/glyphy` — its console is truncated to 40 rows
and floods with the voice road) for `crystal` events. The message names the
gate. If it says *"spent its share of the hour"*, the tint is working and
starving.

**Only some roads sound tinted.** The rewrite historically reached banter and
deep rounds only. Anything that reaches air off `_SHELF` without passing
`crystal_tint()` — and anything hardcoded, like fallback station IDs that never
touch a model — cannot be tinted at all.

**A repeat sounds plain.** Nothing re-tints a repeat. It airs byte-identical to
how it was banked, so material banked before a tinting change stays as it was,
for as long as the cupboard keeps it.

**Throttling banter throttles the crystal.** If banter is the only fully tinted
road, any scheduling change that makes banter yield reduces how much tinted
radio exists. The scheduler and the crystal are coupled through the roads they
share.

**A gauge stops moving.** Suspect the gauge. Truncated lists reported by their
length (`bare[:4]`, a 40-row console) read exactly like "no progress" while the
real number changes underneath.

---

## 9. Handover checklist

If you take this over, verify these in order:

1. `/api/tint` → `two_pass: true` and a crystal `on`.
2. `/api/dj/pipeline` → recent `crystal` events, and **what they say**.
3. `/api/surplus` → `tinted.share` — how much of what is standing by has
   actually been through the crystal.
4. `/api/surplus` → `larder.standing_down` — is banter yielding, and for what?
5. `/api/coordinator/capacity` → `over` — how oversubscribed the hour is. No
   amount of wiring fixes this; only fewer or cheaper entries do.
6. `/api/commitments` → any `cut` is a segment the station has decided it
   cannot make.

---

*The crystal is the reason the station sounds like something rather than like a
text-to-speech engine reading a schedule. The orchestrator is the reason it
keeps sounding like it at four in the morning. Neither survives the other being
starved.*
