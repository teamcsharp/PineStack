# Prompt Assembly Example

## Safe Structural Reconstruction

For a scheduled caller or banter round, the assembled request has this observed structure:

```text
SYSTEM/FOUNDATION
  active prompt/persona and station rules

SCHEDULE/ROAD
  active schedule name, slot kind, standing instruction, line/time budget

DIRECTOR/OPERATOR
  scoped notes, beats, prompt-book alternative, explicit angle

CAST AND OUTPUT CONTRACT
  allowed speaker labels, caller/guest identity, turn count, spoken-only format

FACTS AND RETRIEVAL
  selected topic/record/news facts
  Speakbox/library chunks with source-use instructions

QUALITY/CONTINUITY
  no-repeat constraints, call balance/contract, current binding, ending requirement
```

`ask_model` then clamps the character/token budget, computes temperature/top-p jitter and optional seed, and calls `call_ollama` with `stream: false`.

## Provenance Warning

The live screenplay API may use a nearby call when exact model identity is absent (`model.desk.matched = "recent"`). One observed banter round pointed to an unrelated gallery/transcript-repair prompt. Therefore:

- the shape above is source-derived and reliable;
- a specific live prompt must only be attributed when an exact call/trace ID is present;
- nearby timestamps alone are insufficient evidence.

