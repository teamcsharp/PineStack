# 01 — Services and topology

## The box

One machine, **lilspark** (10.89.1.246): an NVIDIA DGX Spark (GB10, unified memory), Ubuntu, Docker
with `docker compose` for the container stack in `~/pinevoice-stack/`, and a handful of host
services under systemd. The operator's Windows PC reaches it over SMB (`\\10.89.1.246\ehm_eckx`) and
SSH; the listener's radio and the panel are plain HTTP on the LAN. Time: the host keeps
America/Monterrey (no DST), the station container is pinned to `TZ=America/Chicago`.

## The services, one by one

| service | where | port | what it is | how the station uses it |
|---|---|---|---|---|
| **spark-agent** | container `spark-agent` (image `python:3.12-slim`, `network_mode: host`, bind mount `./spark-agent:/app`, `./speakbox:/app/data/speakbox`) | **8096** | the station: FastAPI + uvicorn, one asyncio event loop, `app.py` | everything below is called from here; no hot reload — a code change needs `docker restart spark-agent` (or the quiet-handoff deploy tool) |
| **public funnel** | in-process | 8097 | the public listen door (#1149): the same loop serves the stream to listeners without the panel's key | `music ?br=` bitrate ladder, the `music_lo` cache |
| **Ollama** | host systemd `ollama.service` | 11434 (a capture proxy `zz-llm-capture.conf` fronts the real server on 127.0.0.1:11500) | local LLM server (llama.cpp runners) | `call_ollama()` for every model call: the writer (`gemma4:e2b`, fast), the deep tint (`gemma4:31b`), embeddings (`nomic-embed-text`); env: `OLLAMA_CONTEXT_LENGTH=32768`, `OLLAMA_KEEP_ALIVE=2h`, `OLLAMA_NUM_PARALLEL=2` (#1080) |
| **XTTS v2 clone server** | host process started by `~/reachy-gateway/scripts/tts.sh` (uv) | 8770 | voice cloning TTS (the hosts' and callers' voices) | the recording room renders every line here; reported down by `services_census`, restarted through reachy-gateway (`:9010`), never by the station itself |
| **F5-TTS** | second engine | 8772 | alternative clone engine | the voice bench (`ENGINE_REGISTRY`), role pinning; ≤12 s reference clipping rule |
| **voice-lab** | container | 8771 | the fidelity engine: `/verify`, `/reference/score` | identity cosine per clip (not comparable across clip lengths) |
| **reachy-gateway** | host | 9010 | the robot/voice gateway; owns XTTS | imported clone voices, `reachy_restart` to load new XTTS code |
| **Piper** (via Home Assistant `tts.piper`) | HA | 8123 | fast plain TTS | the emergency host / emergency take (#1087 in code: piper instead of a clone when the road is bare) |
| **Home Assistant** | container | 8123 | home automation; `tts.speak`, media players | spoken announcements to the Pine Box satellite (`HA_MEDIA_PLAYER`), the completion phrase when a request is resolved |
| **Open WebUI** | container | 12000 | chat front end | the station exposes `/v1/chat/completions` and `/v1/audio/speech` so Open WebUI / Hermes can talk to it; Pine Chat dictates inbox requests |
| **SearXNG** | container | 8081 | metasearch | `track_notes()` web research on a record, news feeds, the census |
| **ComfyUI** | host systemd | 8188 | image generation (SDXL checkpoints) | the gallery road paints; `comfy_doctor` troubleshooter and the `data/comfy_kick` restart bridge (#1152) |
| **openWakeWord** | host | 10400 | wake word `hey_dj.tflite` | the listener's microphone wake; "pause the radio" intents (#1154: the mic hearing the show) |
| **The Pine Box satellite** ("Nabu", Home Assistant Voice PE) | 10.89.1.205 | 10700 (Wyoming), LCD firmware | the physical box: speaker, mic, LCD | fetches clips over `VOICE_PUBLIC_URL`, shows the LCD pages (`desktop/lcd-*`), ping-OK/all-ports-refused = power cycle (#1156) |
| **Pine Box Desktop** | Electron app on the operator's PC (`desktop/`) | — | the operator's window onto the panel: 3JS rail, LCD agent, playback probe | loads the panel from :8096; `THREEJS_VIEWS` mirrors the panel's `PINE_3JS` |
| **spark-agent-watchdog** | host systemd | — | probes `/healthz` (3 × 8 s) and restarts the container when the loop is starved | the reason every blocking call in the loop was moved to a thread (#1142, #1156) |
| **hermes-paper-agent** | in-process contract | — | the Gazette press (#1019) | hourly newspaper off the station's log, tinted under the hold (#1077) |

## Who talks to whom

```
listener (browser / satellite) ──► :8096 /radio, /api/music/... ──► spark-agent event loop
                                   :8097 public funnel (same loop)
operator panel (browser, desktop) ─► :8096 CONTROL_PANEL_HTML + /api/*  (Bearer SPARK_AGENT_API_KEY)
Pine Chat / Open WebUI ───────────► :8096 /v1/chat/completions ──► inbox (data/pine_requests.md)
spark-agent ──► Ollama :11434 (writer, tint, embeddings)
            ──► XTTS :8770 / F5 :8772 (renders)  ──► data/pantry (clips)
            ──► ComfyUI :8188 (gallery paintings) ──► data/gallery
            ──► SearXNG :8081 (research, news, census)
            ──► Home Assistant :8123 (tts.speak to the satellite, media players)
            ──► openWakeWord :10400 (wake), satellite :10700 (Wyoming)
host watchdog ──► :8096 /healthz ──► docker restart spark-agent
```

Everything the station does happens on ONE asyncio loop in ONE process. That is the single most
important fact for anyone recreating it: any synchronous work on that loop (a big `json.loads`, a
CIFS read, a SQLite scan) is dead air and, past 24 s, a watchdog restart. The pattern that keeps it
alive: `asyncio.to_thread()` for every file/DB/CPU job, memoised reads (`crystals_read` on
mtime/size, `load_settings`), per-model semaphores on the LLM (`_ollama_lane`), and `/api/pulse`,
the stall ledger that names the frame that held the loop.

## Environment (compose `spark-agent` block)

`OLLAMA_URL`, `OLLAMA_LANES` (#1080), `COMFYUI_URL`, `COMFYUI_CHECKPOINT`, `HA_URL`, `HA_TTS_ENTITY`,
`HA_MEDIA_PLAYER`, `VOICE_PUBLIC_URL`, `SATELLITE_HOST/PORT/MAC/SSID`, `MUSIC_ROOTS` (`/music`),
`XTTS_URL`, `VOXTRAL_URL`, `VOICE_LAB_URL`, `REACHY_GATEWAY_URL`, `OPENWEBUI_URL`, `SEARXNG_URL`,
`DEFAULT_MODEL`, `ENABLE_*` feature flags, `SPARK_HOST_USER`; secrets from `.openwebui.env`
(`SPARK_AGENT_API_KEY`, `HA_TOKEN`). `TZ=America/Chicago`.

## The desktop and the LCD

`desktop/main.js` (Electron), `desktop/renderer/*.js` (renderer, LCD frame/gallery/review/controls),
`desktop/lcd-agent.cjs` and `desktop/lcd-firmware.cjs` (the box's LCD pages and firmware pushes),
`desktop/lcd-stream.cjs`. The runner cache lives in `%LOCALAPPDATA%`; a stale runner means an old
`main.js` until relaunch (the #1148 white-popup lesson).
