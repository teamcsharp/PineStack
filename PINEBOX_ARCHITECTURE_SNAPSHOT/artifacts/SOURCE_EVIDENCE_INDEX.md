# Source Evidence Index

| Topic | Primary anchors |
|---|---|
| App/config/auth | `app.py:OLLAMA_URL`, `SEARXNG_URL`, `DATA_DIR`, `VOICE_ENGINES`, `require_auth`, `require_read_auth` |
| Show loop/music | `app.py:radio_fill`, `radio_next_track`, `_radio_loop`, `_record_talk`, `_dj_loop` |
| Speech floor/delivery | `app.py:dj_speak`, `_dj_speak_floorless`, `speak_turns`, `_speak_turns_floorless` |
| Conversation | `app.py:dj_banter`, `_banter_air`, `dj_call_generated`, `call_entry_contract`, `approach_pick` |
| Speaker state | `app.py:speaker_state`, `weather_roll_round`, `state_from_text`, `performance_vector`, `perf_directive` |
| Schedule | `app.py:SCHEDULE_KINDS`, `SEGMENT_BRIEF`, `schedule_read`, `schedule_take`, `schedule_prompt_for` |
| Prompt book | `segment_prompts.py:expand`, `govern`, `_dial`, `ride`, `seed_for` |
| Model transport | `app.py:ask_model`, `call_ollama`, `recorded_ollama_post` |
| Crystal/tint | `app.py:crystal_tint`, `_crystal_round_first_pass`, `_crystal_round_repass`, `crystal_turn`; `crystal_prompts.py` |
| System 2 | `system2.py:System2Store`; `system2_runtime.py:System2Runtime.refresh`, `prepare`, `dispatch`, `acknowledge` |
| Retrieval | `library.py:scan`, `ingest_one`, `search`; `library_extract.py:read_document`; `app.py:speakbox_search`, `speakbox_quote` |
| Voice/TTS | `app.py:voice_render_any`, `prep_render_line`; `speaker_session.py:PerformerSession` |
| Script/audio contracts | `script_manifest.py:frozen_script`, `validate_*`, `finished_conversation`, `broadcast_admission` |
| Assembly | `conversation_assembly.py:assemble_conversation`, `verify_assembly`, `manifest_cue_entries` |
| Production/admission | `script_production.py:ScriptProducer`; `broadcast_admission.py:PlayoutController` |
| Playout | `playout_sequencer.py:LinearSequencer`, `replay` |
| Stream | `station_stream.py:StationStream`, `_Encoder`, `_HlsEncoder`, `_Sink` |
| SFX | `sfx_match.py:ClipIndex`, `choose`; `clip_speech.py`; SFX DB functions in `app.py` |
| Ledgers/provenance | `station_flow.py:FlowJournal`; `app.py:airlog_*`, `script_ledger_*`, `screenplay_*` |
| UI | embedded HTML/JS in `app.py`; `frontend/`; `desktop/main.js`; `desktop/renderer/`; Android `app/src/main/` |
| Extension invariants | `docs/extending.md`; `docs/recreation/`; `docs/linux-handoff-2026-09-24.md` |

