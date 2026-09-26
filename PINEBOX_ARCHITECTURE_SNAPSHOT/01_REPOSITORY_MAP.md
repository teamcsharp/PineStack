# Repository Map

## Tree

```text
spark-agent/
|-- app.py                         # FastAPI entrypoint, show loop, roads, embedded UIs
|-- system2.py                     # SQLite planning store
|-- system2_runtime.py             # planner/preparer/dispatcher and /api/system2
|-- system2_media.py               # System2 delivery adapter
|-- system2_writing.py             # turn budgets/completion tests
|-- station_flow.py                # durable flow/event journal
|-- director.py                    # notes, scripts, beats, feedback
|-- segment_prompts.py             # prompt-book alternatives and source expansion
|-- library.py                     # document index and hybrid retrieval
|-- library_extract.py             # PDF/EPUB/DOCX/HTML/text extraction
|-- crystal_*.py                   # tint prompts, contracts, acceptance, rhyme/source
|-- line_review*.py                # refusal evidence, decisions, runtime API
|-- rejection_*.py                 # rejection lab/workbench
|-- prompt_history.py              # model call/config/edit history
|-- prompt_learning.py             # evidence/outcome/recipe learner
|-- script_manifest.py             # frozen script/audio/admission contracts
|-- speaker_session.py             # actor render sessions and resumable takes
|-- conversation_assembly.py       # cut verification, mixing, cue maps
|-- script_production.py           # shadow/on production pipeline
|-- broadcast_admission.py         # candidate verification and occurrence ledger
|-- playout_sequencer.py           # linear playback ordering and receipts
|-- station_stream.py              # PCM mix, MP3/HLS encoding, listener sinks
|-- sfx_*.py                       # SFX match, cues, reactions, cadence, speech
|-- nabu_audio.py                  # box audio cache/gain
|-- resource_guard.py              # resource pressure policy
|-- frontend/
|   |-- system2.js/css             # planner surface
|   |-- station-flow.js/css        # flow visualization
|   `-- other focused panel modules
|-- desktop/
|   |-- main.js                    # Electron main process, station/ADB bridges
|   |-- preload.js
|   |-- renderer/
|   |   |-- renderer.js            # desktop control surface
|   |   |-- webview-preload.js     # panel-to-chrome bridge
|   |   `-- focused views/controllers
|   `-- package.json
|-- app/                            # Android kiosk application
|   |-- build.gradle.kts
|   `-- src/main/
|       |-- AndroidManifest.xml
|       |-- java/com/pinebox/kiosk/
|       `-- assets/pine-views/      # copied listener/control assets
|-- tests/                          # ~340 tracked Python/JS/Kotlin-oriented tests
|-- tools/                          # deployment, smoke, recovery, systemd helpers
|-- docs/
|   |-- requestmap.md               # specification executed by this package
|   |-- extending.md                # extension invariants
|   |-- recreation/                 # prior operational reconstruction guide
|   `-- notes/, inbox-*, recovery docs
|-- vendor/                         # pinned browser/model support assets
|-- requirements.txt                # Python dependencies
|-- package.json                    # root Node checks/tooling
|-- build.gradle.kts                # Android root build
|-- settings.gradle.kts
`-- data/                            # live runtime state, ignored/untracked
    |-- settings.json, schedule.json, prompt_book.json
    |-- prep_shelf.json, larder.json, pantry.json
    |-- air_log.jsonl, model_calls.jsonl, script_ledger.jsonl
    |-- station_flow.sqlite3, system2.sqlite3
    |-- line_review.sqlite3, rejection_lab.sqlite3
    |-- prompt_history.sqlite3, prompt_learning.sqlite3
    |-- sfx_clips.db, sfx_cadence.sqlite3
    `-- media/index/cache subdirectories
```

## Ownership Notes

| Area | Entrypoint/owner | Supporting code |
|---|---|---|
| Application and HTTP | **OBSERVED:** `app.py:app` | FastAPI routes and embedded HTML/JS in `app.py` |
| Overall orchestration | **OBSERVED:** `_dj_loop`, startup keepers, `_system2().dispatch()` | `system2_runtime.py`, `orchestrator_rooms.py`, `resource_guard.py` |
| Scheduling | **OBSERVED:** `schedule_read`, `schedule_take` | `segment_prompts.py`, `director.py`, System 2 |
| Conversation | **OBSERVED:** `dj_banter`, `dj_call_generated`, `speak_turns` | `call_scenarios.py`, `caller_topic.py`, `response_bank.py` |
| Prompting | **OBSERVED:** `ask_model`, `call_ollama` | `crystal_prompts.py`, `segment_prompts.py`, `prompt_*` |
| Retrieval | **OBSERVED:** `library.py`, Speakbox functions in `app.py` | `library_extract.py`, `crystal_source.py` |
| TTS/audio | **OBSERVED:** `voice_render_any`, `dj_speak` | `speaker_session.py`, `conversation_assembly.py`, `station_stream.py` |
| SFX/music | **OBSERVED:** SFX and music sections in `app.py` | `sfx_match.py`, `sfx_cue.py`, `sfx_reaction.py` |
| Deployment/runtime | **OBSERVED:** `desktop/main.js`, `tools/*.service`, docs | Authoritative host Compose/systemd files are **NOT PRESENT IN CURRENT REPOSITORY** |
| Tests | **OBSERVED:** `tests/` | Targeted regression files carry request/date suffixes |

**INFERRED:** `app.py` is intentionally a composition root but has also accumulated domain logic and embedded frontend assets. Module boundaries are real for newer contract-heavy systems; many older roads still share globals through `app.py`.

