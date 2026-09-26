# Sanitized Configuration Surface

Only key names and code defaults are shown. Secret values were not read or copied.

| Key | Code default / role | Source |
|---|---|---|
| `SPARK_AGENT_PORT` | `8096` | `app.py:STATION_PORT` |
| `SPARK_AGENT_DATA_DIR` | `/app/data` | `app.py:DATA_DIR` |
| `SPARK_AGENT_API_KEY` | no safe default; mutation auth | `app.py:SPARK_AGENT_API_KEY`, `require_auth` |
| `SPARK_AGENT_LOCK_READS` | `false` | `app.py:LOCK_READS` |
| `SPARK_AGENT_AUTOFILL_KEY` | `true` on trusted deployment | `app.py:AUTOFILL_KEY` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | `app.py:OLLAMA_URL` |
| `SEARXNG_URL` | `http://127.0.0.1:8081` | `app.py:SEARXNG_URL` |
| `MUSIC_ROOTS` | `/music` | `app.py:MUSIC_ROOTS` |
| `SFX_ROOT` | `/samples` | `app.py:SFX_ROOT` |
| `XTTS_URL` | `http://127.0.0.1:8770` | `app.py:XTTS_URL` |
| `COSYVOICE_URL` | `http://127.0.0.1:8773` | `app.py:COSYVOICE_URL` |
| `INDEXTTS_URL` | `http://127.0.0.1:8774` | `app.py:INDEXTTS_URL` |
| `QWEN_TTS_URL` | `http://127.0.0.1:8020` | `app.py:QWEN_TTS_URL` |
| `VIBEVOICE_URL` | `http://127.0.0.1:8778` | `app.py:VIBEVOICE_URL` |
| `SPARK_AGENT_ADMISSION*` | observe/enforce mode and lanes/order | `app.py` admission initialization |
| `SPARK_AGENT_SCRIPT_PRODUCTION` | off/shadow/on plus road/budget/every/lines | `script_production.py:ProductionSwitch` |
| playout mode file | off/shadow/linear, reread within seconds | `playout_sequencer.py:PlayoutSwitch` |

Primary persisted configuration files observed: `settings.json`, `schedule.json`, `prompt_book.json`, `system2-config.json`, `routing.json`, and subsystem policy/state files.

