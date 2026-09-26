# Persistence Inventory

## Live Size Sample

| Store | Approximate size at observation | Notes |
|---|---:|---|
| `station_flow.sqlite3` | 1.76 GB | flow events and outcome embeddings |
| `system2.sqlite3` | 143 MB | hours, slots, jobs, candidates, reservations, receipts |
| `line_review.sqlite3` | 3.01 GB | refusal evidence and decisions |
| `rejection_lab.sqlite3` | 3.20 GB | lab operations/trials/traces |
| `prompt_history.sqlite3` | 29.6 MB | model request/response/config history |
| `prompt_learning.sqlite3` | 86.1 MB | evidence, recipes, outcomes, revisions |
| `sfx_clips.db` | 115.8 MB plus WAL | clip metadata/index work |
| `sfx_cadence.sqlite3` | 5.3 MB | cadence receipts |
| `rhyme_assistance.sqlite3` | 296.6 MB plus WAL | pronunciation/semantic index |
| `speakbox_vectors.json` | 652.7 MB | embedding vectors |
| `air_log.jsonl` | 21.6 MB | heard/published/withdrawn line evidence |
| `script_ledger.jsonl` | 44.1 MB | intended/caught-up line order |
| `screenplay_lines.jsonl` | 8.8 MB | line provenance feed |
| `screenplay_rounds.jsonl` | 5.0 MB | round-level provenance |
| `model_calls.jsonl` | 2.1 MB | model timing summaries |

## Operational Properties

- SQLite stores generally use WAL; some have large live WAL files.
- JSON writers commonly use temporary file plus atomic replace.
- JSONL stores tolerate/drop a torn final row and are retention-trimmed.
- Flow persistence is asynchronous; recent memory remains available if its writer fails.
- Media caches and stock are rebuildable but clearing them reduces continuity until refilled.
- Operator books, schedules, prompts, voice assets, review decisions, and archives are not wipe-safe.

Schema source excerpts are identified in `12_DATABASES_AND_SCHEMAS.md`; no multi-gigabyte database was copied into this package.

