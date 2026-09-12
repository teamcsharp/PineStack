# 05 — The DJs: psychology, goals, logic

## Who is on air

- **The DJ** — the host's chair, a cloned voice (XTTS), the station's own persona from the prompt
  desk (the active system prompt, e.g. `jerk4` on 2026-09-08). Introduces records, runs the running
  order, takes the calls, reads the manager's memos back with attitude.
- **The cohost** — the second chair: the foil, the one who answers, disagrees, lands the punchline;
  a second cloned voice.
- **The third seat** (#568) — a guest: a named character with a voice, a "who" and a "why", booked
  through the events API (#1135, the interview airs live-only with banter as the fallback).
- **The callers** — listeners phoning in: a name, a cloned voice picked for the name
  (`caller_line_voice`), a topic, a transcript; the phone contract (`call_entry_contract`) grades
  every call: the caller must hold 40–55 % of the turns, the topic must be named, the fingerprint must
  match the script, the quality must be `ok`.
- **The manager upstairs** — angry memos read on air (`manager`), the station's comic authority.
- **The SFX guy** — per-voice quip databases and a rate (`sfxguy_rate`), the drop-ins between lines.
- **The emergency host** — piper-voiced filler when a road arrives bare; the station's own admission
  that it is short (the "emergency take", conservative cost 0.40 × a clone).

## What the operator wants from them

In the operator's words across the request book: *talk radio going on and on*, *constant and
incessant and never ending*; the pair should speak **in the crystal's world** (DOOM: dense internal
rhyme, the mask, food as metaphor, cartoon menace played dead serious) at the crystal's own level —
every line a rap bar that keeps the facts; **never the same line twice in an hour**, varied over five
hours; **more callers**; **the hosts learn** from their rejections; the newspaper, the calls, the
memos, the ads all in the same voice. And the station must say what it is doing: every silence
should have a reason in the log.

## What was attempted, in order of the ideas

1. **Characters and feeling** (the Voice Director): an engine bench per voice (`ENGINE_REGISTRY`),
   role pinning, characters with a feeling via `/feel`; the OpenAI-compatible `/v1/audio/speech` so
   other tools can speak in the station's voices.
2. **Grounding in the operator's own documents** (the speakbox): the pair talk ABOUT something —
   the swath drawn from one document, the document lock for study hours, the word cloud of what has
   been said, the "heard" ledger.
3. **Roads as character**: calls, memos, ads, news, gallery, track talk — each a different register
   for the same two voices, each with its own writer prompt and contract.
4. **Repetition rules**: `said_lines.json`, phrase prints and line prints (fingerprints of what was
   said), the one-hour repeat ledger (`can_play`), the reuse rest (3 h, `SHELF_REUSE_REST_FLOOR`
   never below 1 h), the continuity pairs' rest (1 h), expiry and `used_by` on every stored line.
5. **The crystal** (04): the world put in their mouths, the evaluator as the editor who refuses.
6. **The judgment book** (02): the station asks the operator when its own guess and the result
   disagree ("You told me a phone call is worth 2 × the usual push — and it still closed its hour at
   12 %. Which one gives?") and remembers the answer as a standing judgment.
7. **Learning from rejections** (04): fault families → prompt recipes, measured per attempt; the
   fault memo so a line is not refused twice for the same reason; the strike cap so nothing is asked
   fifty times.
8. **Honesty about silence**: every early return names itself in the pipeline log (#1063); the
   pulse names the frame that held the loop; the hour scorecard names the road that missed.

## The logic trees

### When the running order reaches an entry

```
entry due (kind K)
├─ System2 on? ─ yes ─ dispatch(): a slot in play with a ready allocation?
│                       ├─ yes → reserve → deliver → audible receipt → done
│                       └─ no  → fallback_due()? ─ no → wait (paced, page counts as air)
│                                                └─ yes ↓
└─ legacy chain for K:
   ├─ stock ready for K (dialogue_stock_items: viable, not expired, tint ready, audio ready, not heard within the hour)?
   │    ├─ yes → shelf_take → air (pantry clip; dj_speak keys on the exact text)
   │    └─ no ↓
   ├─ repeats_hard? → a rested repeat (reuse_rest, floor 1 h) → air
   ├─ when_empty == live? → write now in front of the listener (writer → tint (hold: cut what fails) → render → air)
   └─ nothing → the emergency host (piper) / the record plays on, and the log says why
```

### Preparing one round (the keepers and System2 alike)

```
pick the road furthest behind (order: banter, track_talk, news, ad, caller; prefer_road / drive_road weigh in)
├─ write plain (fast model): brief + speakbox swath + persona; generation_turns
├─ tint (deep model): whole round → batched re-ask over refused turns → per line, ≤3 asks, faults ride each re-ask,
│     the first ask carries the fault memo; word options from CMUdict/WordNet
│     ├─ line passes → kept
│     ├─ line refused after its asks → cut before the studio (line review filed)
│     └─ round stagnant 4 answers → cooldown ladder; 12 → struck out (row retired, replacement written)
├─ coverage met? (100 %: every eligible line passed or was cut) → recording room (one render per engine)
└─ shelf/larder/cupboard row: ready when audio + verdict are in; expires_at, used_by, system2 slot binding
```

### A phone call

```
caller name → voice for the name → topic → writer (caller ≥40 % of turns, hosts answer) → phone contract grade
├─ fails contract → rewrite (2×) → strike the tint, bank the graded plain call (#1146) → next pass carries the lesson
└─ passes → tint → cupboard → System2 slot / the caller road
```

### When the operator pauses

```
pause (panel / spoken / mic) → why into paused.json → clocks stop honestly → bank stock (phone clock first)
→ resume → the resume reel replays what was cut going in → the floor is handed back
```

## Where the personas live

The prompt desk (settings `prompts`, the active prompt), the schedule's per-entry prompts, the
characters (`/feel`, the Voice Director), the crystal's world text (`crystals.json` → `tint`), and the
callers' names and voices (`data/callers*`, the cupboard). Change the persona and the station keeps its
logic; change the crystal and it keeps its persona.
