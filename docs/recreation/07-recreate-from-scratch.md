# 07 — Recreating it from scratch

A build order for another LLM (or a patient human). Each step ends with something that works.

## 0. Hardware and OS

One box with a GPU that can hold a ~30B model and a 2–5B model resident together with two decode
slots each (a DGX Spark / GB10 with unified memory does; a 24 GB card does with smaller quantisations
and one slot), Ubuntu, Docker with compose, Python 3.12, Node 20 (for the desktop app and the node
tests), `ffmpeg`. A second machine on the LAN for the panel and the desktop app. A speaker/microphone
satellite is optional (Home Assistant Voice PE with the LCD firmware in `desktop/`).

## 1. Services (01)

1. **Ollama** as a systemd service: pull `gemma4:e2b` (writer), `gemma4:31b` (deep tint),
   `nomic-embed-text` (embeddings). Drop-ins: `OLLAMA_HOST`, `OLLAMA_CONTEXT_LENGTH=32768`,
   `OLLAMA_KEEP_ALIVE=2h`, `OLLAMA_NUM_PARALLEL=2`. Verify with `ollama ps` and a `ps` grep for
   `-np 2` on the runners.
2. **A clone TTS**: XTTS v2 (`:8770`) with the hosts' reference clips; F5-TTS (`:8772`) optional;
   the voice-lab (`:8771`) optional (fidelity scores).
3. **Home Assistant** (`:8123`) with `tts.piper` and a media player for the satellite; a long-lived
   token in `.openwebui.env` as `HA_TOKEN`.
4. **SearXNG** (`:8081`), **ComfyUI** (`:8188`, SDXL checkpoint), **Open WebUI** (`:12000`) — each
   optional; the station reports what is down (`services_census`, the 🏥 steward) and routes around it.
5. The **compose stack** `~/pinevoice-stack/compose.yaml`: the `spark-agent` service block from 01
   (host network, bind mounts `./spark-agent:/app` and `./speakbox:/app/data/speakbox`,
   `/etc/localtime` read-only, the environment table, `env_file: .openwebui.env`).
6. The **watchdog** (`spark-agent-watchdog`): three failed `/healthz` probes 8 s apart → `docker
   restart spark-agent`.

## 2. The repository

`git clone` the station repo into `~/pinevoice-stack/spark-agent` (`app.py`, the modules, `frontend/`,
`vendor/` — three.js is vendored at `/vendor/three.module.js` and must be present —, `tools/`,
`tests/`, `desktop/`, `docs/`). `requirements.txt` into the container (`pip install -r`), `pytest`
for the tests. Set `SPARK_AGENT_API_KEY` in `.openwebui.env`; `AUTOFILL_KEY` embeds it in the pages
on a trusted LAN; `LOCK_READS` makes every GET require it.

## 3. The first minute of air

1. `docker compose up -d spark-agent`; `curl :8096/healthz` → `{"status":"ok"}`.
2. Put music under `MUSIC_ROOTS` (`/music`); the index builds (`music_index.json`).
3. Open the panel (`http://box:8096/`), paste the key, press start (`POST /api/dj/start`). Records
   play. The pair introduce them with the fast model and piper before any clone voice exists.
4. Add the two clone voices (the Voice Director), assign them to the DJ and the cohost. Rounds are
   now rendered by XTTS into the pantry.
5. Put a few documents into `speakbox/`; the index clock picks them up within two minutes; the
   pair start talking about them.

## 4. The layers, in the order they were built

1. **The schedule** (02): the running order per hour, `prepare_hours`, the keepers per road, the
   hour's obligations (`/api/hour-owes`), the pause/bank/resume behaviour.
2. **The roads** (05): calls (caller book, voices for names, the phone contract), ads (produced
   spots), the manager, the news wire, the gallery (ComfyUI), track talk (lookahead intros), the SFX
   guy, continuity pairs, station IDs.
3. **The repetition rules**: said lines, prints, the one-hour ledger, reuse rest, expiry, `used_by`.
4. **The crystal** (04): crystals.json, album minds by extraction, the two-pass tint, the contract,
   the evaluator, the hold, line review, the learner, rhyme assistance, the fault memo and the strike
   cap. Ship the tests in `tests/test_crystal_*`, `test_tint_*`, `test_rap_*` with it — they are the
   operator's fidelity rules.
5. **System2** (03): the store, the planner, jobs and leases, dispatch and receipts, the hybrid
   dials; switch the engine with `POST /api/system2/settings {"engine":"system2"}`.
6. **The press** (02): the hourly Gazette, tinted, read as the recap.
7. **Observability**: `/api/pulse` (stall ledger), `/api/dj/pipeline` (the diary), `/api/tint`,
   `/api/orchestrator/logic` (roads, policies, judgment book), `/api/coordinator/capacity`, the
   airlog and `model_calls.jsonl`, the 3JS scenes (station flow, dialogue mind, DJ plexus,
   orchestrator graph, word cloud, rhyme cloud, the request book).
8. **The satellite and the desktop**: the LCD pages, the playback probe, the Electron rail; the
   public listen door (`:8097`) and the bitrate ladder.
9. **The inbox**: Pine Chat dictation into `pine_requests.md`, `tools/inbox-resolve.py` to archive
   a resolution and speak the completion phrase, the request book.

## 5. The rules that were paid for (do not relearn them)

- One asyncio loop; nothing blocking on it (thread it, memoise it, or do less of it). `json.loads`
  holds the GIL — threads do not save a big decode; decode less.
- Every model runner is a queue: measure `-np` before assuming a second concurrent ask helps; keep
  the prompt prefix stable so the KV cache does the reading.
- A round is not ready until its audio AND its verdict are in; "ready" is not "aired"; a receipt is.
- Cut before the studio; never air a line the editor refused; never ask the same line fifty times.
- Deploy at a quiet handoff (`tools/deploy-at-radio-gap.py`); a compose environment change needs
  `--recreate`.
- Write every decision to the pipeline log with the request number that motivated it, and measure
  before and after. The station's own ledgers are the only truth about the station.
