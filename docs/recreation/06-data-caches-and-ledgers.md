# 06 — Data, caches and ledgers (`spark-agent/data/`)

Every path is made with `data_path(name)` in `app.py`; search for the constant to find the writer.
"Wipe-safe" means the station regenerates it; "keep" means it is the operator's own material or an
archive. Sizes are from 2026-09-08.

| file / folder | what it is | writer → reader | wipe? |
|---|---|---|---|
| `settings.json` | every dial: prompts, `dj` (the schedule, the crystal dials, speakbox rates, minds, voices), pine chat phrases | the panel / `save_settings` → `load_settings` (memoised) | keep |
| `pine_requests.md`, `pine_completed.md`, `pine_uploads/` | the inbox (open requests, newest first), the archive of every resolution, attached screenshots | Pine Chat → `pine_complete` (`tools/inbox-resolve.py`) | keep |
| `pine_journal/<id>.md` + `.json` | the request book: request, reply, costs, flow (#1079) | `pine_journal_write`, backfilled from the archive | regenerable from the archive |
| `conversations.jsonl` (1 MB), `feedback.jsonl` | every chat turn (`log_turn`), thumbs | chat → memory/context | keep |
| `model_calls.jsonl` | one row per Ollama call: model, kind, ms, working/waiting, `prompt_eval_count/ms`, `eval_count/ms`, tinted | `airlog_model_call` → the airlog, the request book costs, the #1081 measurement | trimmed by `airlog_jsonl_trim` |
| `airlog/*.jsonl` | what aired, when, who, the heat ring (GPU temp/load) | `airlog_append_bg` → the Gazette, `/api/airlog` | trimmed |
| `crystals.json`, `crystal_notes.json`, `crystals/` | the crystals and their notes/builds | the 🔮 cabinet | keep |
| `minds/<id>/docs/` | each mind's documents (album lyrics from crystal extraction, topical minds) | extraction → `speakbox_reindex` | keep |
| `speakbox/` (bind mount `../speakbox`) | the operator's own documents | operator → `speakbox_reindex` | keep |
| `speakbox_vectors.json` (+`.meta.json`), `speakbox_gems.json`, `speakbox_heard.json`, `speakbox_vault/`, `speakbox_evicted/`, `decision_vectors.json`, `chunk_ledger.json` | the embeddings index per mind, the gems, what has been heard, the chunk serving/cooldown ledger | the index clock (every 120 s) → grounding, the crystal passages | regenerable (slow) |
| `said_lines.json` (6000), `phrase_prints.json`, `line_prints.json` | what was said and its fingerprints — the repetition rules | every air → `can_play`, repeat checks | wipe-safe |
| `played.json` (300), `music_index.json` (36k tracks), `music_hot` | the rotation and the library index | the loop | index regenerable |
| `ad_reads.json`, `lyric_jobs.json`, guests, callers | produced spots, lyric extraction jobs, the guest book, the caller book | their keepers | keep the books |
| `pantry/` (clips, 812 MB before the wipe), shelf, larder, takes (the recording-room ledger), cupboard | the four piles of stock (02) | keepers/System2 → the loop; `POST /api/cache/purge {"areas": [...]}` wipes them | wipe-safe (the hour goes bare until refilled) |
| `system2*.sqlite`, `system2-config.json`, `system2-traces/` | the plan store, the dials, one JSON per sitting with every captured model call | System2 | config keep; store regenerable; traces are evidence |
| `line_reviews*.sqlite` (655 MB) | every refusal with its evidence and the operator's decisions | `line_review_capture` → the Rejected lines view, the learner | keep the decisions |
| `learning.sqlite3` | the prompt learner's ledger and recipes | `prompt_learning_observe` | keep |
| `rhyme*.sqlite` | the CMUdict/WordNet index and vectors | `rhyme_assistance.initialize` (built in 13 s, compacted) | regenerable |
| `paper/` editions, `newspaper-*.md` | the Gazette | the press | archive |
| `paused.json`, `doc_lock.json`, `comfy_kick`, `hostsvc-kick` | state files and restart bridges to host services | the panel / the steward | wipe-safe |
| `gallery/` | paintings and their descriptions | ComfyUI → the gallery road | keep what you like |

## The caches that are not files

- `_OLLAMA_JOBS`, `_OLLAMA_ONE`, `_OLLAMA_DEFERRED*` — the writing room (admission per model and
  category, `writing_room_state`).
- `_CRYSTALS_MEMO`, `_CRYSTAL_VOCAB`, `_CRYSTAL_POOL`, `_CRYSTAL_STANZA`, `_CRYSTAL_MATERIAL_MEMO`,
  `_RHYME_ASSIST_MEMO`, `_RHYME_CLOUD_MEMO`, `_TINT_FAULT_MEMO` — per-process memos; lost on restart,
  rebuilt on first use.
- `_LARDER`, the hold shelf, `_READY_SHELF_BUSY`, `_SEGMENT_TASK`, `_RADIO` — the live state of the
  show.
