# Databases and Schemas

## SQLite Stores

| Store | Principal schema | Relationships/purpose | Source |
|---|---|---|---|
| `system2.sqlite3` | `s2_hours`, `s2_slots(hour_id,ordinal)`, `s2_jobs(slot_id,state,deadline)`, `s2_candidates`, `s2_reservations(slot_id,candidate_id,request_id)`, `s2_receipts`, `s2_heard`, `s2_events` | hour -> slots -> jobs/reservations -> receipts/heard | `system2.py:System2Store.__init__` |
| `station_flow.sqlite3` | `events(id,body)`, `embeddings(event_id,model,vector)` | append event evidence; embeddings only for measured broadcast outcomes | `station_flow.py:FlowJournal` |
| `line_review.sqlite3` | policy, reviews, events, decisions, batches, instances, replacements | refusal fingerprint -> occurrences/decisions/replacement requests | `line_review.py:LineReviewStore` |
| `rejection_lab.sqlite3` | operations, messages, trials, traces, settings | review event -> leased operation -> trial/trace | `rejection_lab.py:RejectionLabStore` |
| `prompt_history.sqlite3` | configurations, calls, edits | content-addressed config -> model calls; prompt edits | `prompt_history.py` |
| `prompt_learning.sqlite3` | evidence, decisions, outcomes, recipes, classifications, state, revisions | review evidence -> recipes/revisions -> outcomes | `prompt_learning.py` |
| `sfx_clips.db` | clips, `sfx_meta`, `sfx_index_work` | media row -> speech/vision indexing lease and deck state | `app.py:sfx_db`; `clip_speech.py` |
| `sfx_cadence.sqlite3` | `receipts(id,units,sample)` | durable effect cadence/consumption | `sfx_cadence.py` |
| `rhyme_assistance.sqlite3` | metadata, phones, senses, lemmas, usage, forms, embeddings, query_vectors, FTS5 search | word/pronunciation/sense graph and cached vectors | `rhyme_assistance.py` |
| `parody_stinger_queue.sqlite3` | jobs with state/retry/attempt fields | durable generation queue | `parody_stinger_queue.py` |

## Flat/Event Stores

| Category | Examples | Ownership |
|---|---|---|
| Configuration | `settings.json`, `schedule.json`, `system2-config.json`, `routing*.json`, `prompt_book.json` | operator/API writers, memoized readers |
| Prepared stock | `prep_shelf.json`, `larder.json`, `pantry.json`, `call_log.json`, media directories | keepers/System 2 -> air paths |
| Broadcast truth | `script_ledger.jsonl`, `air_log.jsonl`, `airings.jsonl`, `screenplay_lines.jsonl`, `screenplay_rounds.jsonl` | commit/publish/air/screenplay keepers |
| Model/prompt evidence | `model_calls.jsonl`, `repeat_calls.jsonl`, System 2 trace JSON | model wrapper and tracing |
| Retrieval | library shards, `speakbox_vectors.json`, `.meta`, chunk/source ledgers | ingest/search code |
| Repetition/rotation | `said_lines.json`, `line_prints.json`, `phrase_prints.json`, `played.json`, SFX histories | air/music/SFX code |
| Recovery/continuity | playout/admission checkpoints, hold/pause/recovery files | sequencer/admission/watchdogs |
| Media/assets | `voice_media/`, `radio_cache/`, `music_hot/`, `ads_audio/`, gallery/art | render/mix/export paths |

## Domain Relationships

```text
schedule preset/day -> hour template -> System2 hour -> slot/job
slot -> candidate reservation -> prepared road row -> script revision
script revision -> ordered occurrence IDs -> actor render sessions -> master/cut
cuts -> finished assembly/cue map -> admission -> playout delivery -> listener receipt
receipt -> System2 heard/debt + flow/air/screenplay evidence

road row -> topic/source/director/prompt metadata
actor -> voice/engine/performance metadata
spoken line -> repeat fingerprints + review evidence + rendered media
```

## Persistence Findings

- **OBSERVED:** Redis/Postgres/external vector DB are **NOT PRESENT IN CURRENT IMPLEMENTATION**.
- **OBSERVED:** Many SQLite bodies are JSON text, preserving flexible domain payloads at the cost of relational queryability.
- **OBSERVED:** Major databases use WAL and busy timeouts; hot-path comments document prior event-loop stalls and move expensive reads/serialization to threads.
- **OBSERVED:** Live sizes are operationally significant: flow ~1.76 GB, System 2 ~143 MB, line review ~3.01 GB, rejection lab ~3.20 GB, Speakbox vectors ~653 MB. Retention/compaction is part of system behavior, not optional housekeeping.

