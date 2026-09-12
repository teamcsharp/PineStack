---
name: voice-director
description: "The Voice Director service — engine bench, role assignment, characters+feeling, benchmark, and the OpenAI-compatible endpoint"
metadata: 
  node_type: memory
  type: project
  originSessionId: 76060765-7250-4692-8400-1a3022b54df3
  modified: 2026-08-17T22:05:49.727Z
---

The Voice Director (#786, app.py) is a standalone TTS service on spark-agent
that other systems (OpenWebUI, Hermes) can use, not just the radio.

**Engine bench**: `ENGINE_REGISTRY` (name → url/family/label/speed/standin/
default_voice) drives everything. `synthesize()` at ~line 5570 is THE seam.
Two contract families: `clone` (base64 reference → wav, errors-as-200:
XTTS, F5, cosyvoice, indextts, voxcpm) via `_clone_synthesize`; `openai`
(POST /v1/audio/speech: kokoro, qwen_tts, voxtral) via `_openai_speech`.
New engines are DATA — add a registry row + env URL; they light up when the
host serves the port (XTTS :8770, F5 :8772, cosyvoice :8773, indextts :8774,
voxcpm :8775, kokoro :8776, qwen_tts :8777). `engine_health(name)` caches 30s.

**Roles & stand-ins**: dj_settings `role_engine{role:engine}` pins an engine
to a role (preset engine → role speaks in its own voice; clone engine →
role's clone through it); `standin_engine` is the fast preset that covers a
slow render. `voice_engine_for(voice, who)` consults both; `render_relief()`
borrow now reaches `_ready_standin_engine()` (fastest ready standin) not just
piper. VOICE_ROLES = dj/cohost/third/caller/drop/guest.

**Characters** (`data/voice_characters/<id>.json`): voice + persistent TRAITS
(baseline_pitch, cadence, emotional_range, speaking_rate, filler_frequency,
breathiness, interruption). The LLM calls `POST /api/voice/director/feel`
{character, emotion:{EMOTION_DIMS 0..1}, macro, note} — the feeling carries
with §30 inertia via speaker_state key `char:<id>`. `character_perf(cid)`
combines stored traits + current feeling → the performance vector for the
next line; the voice is NEVER recreated. Builds on EMOTION_DIMS/MACRO_STATES/
speaker_state (~line 8546+).

**Endpoints**: GET/POST `/api/voice/director` (state/assign/say/feel/
benchmark), PUT/GET `/api/voice/director/character/{id}`, and
**`POST /v1/audio/speech`** (OpenAI-compatible — voice accepts a character
id, clone id, or `engine:voice` like `kokoro:af_heart`; returns wav/mp3/opus
bytes). Benchmark tasks: caller/ad/manager/police_alert/sfx/voice_sfx.

**Standing the bench engines up on the DGX host** (aarch64, GB10, Python
3.12, NO conda, uv at ~/.local/bin/uv, sudo works). Servers live in
`~/reachy-gateway/bench/` (kokoro_server.py, voxcpm_server.py,
indextts_server.py, + bench_launch.sh). Launch pattern mirrors XTTS/F5:
`bench_launch.sh <kokoro|voxcpm|indextts|qwen>` → `uv run --index
https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match
--with <pkg> python <server>.py --port <p> --preload`. Ports match the
ENGINE_REGISTRY: cosyvoice 8773, indextts 8774, voxcpm 8775, kokoro 8776,
qwen_tts 8777. Once a host server answers, spark-agent's director sees it
automatically (engine_health polls) — no redeploy.

CRITICAL: **HF Xet hangs on this box** (confirmed: worker stuck CLOSE-WAIT
to the HF CDN 52.84.x:443, thread in poll). Every HF-downloading engine
MUST launch with `HF_HUB_DISABLE_XET=1 HF_XET_HIGH_PERFORMANCE=0
HF_HUB_ENABLE_HF_TRANSFER=0` (bench_launch.sh sets these). Without it the
model download never completes and health stays loading forever.

**STANDALONE SERVICE (2026-08-17)**: the director now ALSO lives apart from
the radio at `~/voice-director/` on the host, port **:8090** — FastAPI via
uv, console UI at `/`, engine servers in `engines/`, state in `data/`.
Managed by `sc stack voice-up|voice-down|voice-restart|voice-status`
(~/bin/sc, backup sc.bak.voicedirector; also row 10 of stack up/status).
Docs: `~/voice-director/README.md` + stack-root `VOICE-DIRECTOR.md`.
Endpoints: /director (say/read/clone-url/broadcast/benchmark/assign/
character/feel), engine lifecycle /director/engine/{id}/deploy|terminate|
relaunch|status + PUT/DELETE/disable (runtime overlay data/engines.json),
OpenAI /v1/audio/speech + /v1/models. Launch kinds: uv | docker | shell
(qwen compose) | external (xtts/f5).

Engine feasibility on ARM64 (2026-08-17): Kokoro WORKS (~9x realtime).
**VoxCPM WORKS** — but only with `load_denoiser=False` AND
`TORCHDYNAMO_DISABLE=1` (torch.compile dies on sm121 aarch64), AND it
refuses to clone without `prompt_text` — the clone contract now carries
`reference_text`, read from `<voice>/reference.txt` beside reference.wav in
the library (faster-whisper base.en transcribes refs once, on-host via uv).
**Qwen3-TTS WORKS** — the Spark docker (martinb78/faster-qwen3-tts-dgx-
spark, repo ~/reachy-gateway/bench/qwen3tts-spark) on host **:8020**
(container :8000, dgx_net external network must exist). Its
config/speakers/*.wav ARE its voices — library refs copied there make Qwen
clone Pine Box voices; each needs a sidecar `<Name>.txt` transcript or it
returns a 44-byte empty WAV. voices.json regenerates every 10s in-container.
IndexTTS is NOT on PyPI → git install, pins cu128 torch — BLOCKED without an
isolated env. CosyVoice2 BLOCKED: pynini 2.1.6 wants OpenFst 1.8.3, apt has
1.8.2, no aarch64 wheel. VibeVoice: registered :8778, server not written.

**Open WebUI on this box**: /api/chat/completions 400s for EVERY model —
`process_chat: 'NoneType' object has no attribute 'startswith'` (its own
bug; adding chat_id+session_id turns it into a task instead). The working
path is the **ollama proxy** `POST /ollama/api/chat` — ask_openwebui falls
back to it. OPENWEBUI_API_KEY in stack .openwebui.env works; ~/bin/
openwebui_key.txt is stale. OpenWebUI TTS is pointed at the director
(:8090/v1, model kokoro) via POST /api/v1/audio/config/update.

**Wake words are data** (#788): settings["wake"] {enabled, words:[{id,
phrase, route: webui|dj, on}]} — builtins keep generous STT-mangle regexes
(_BUILTIN_WAKE), custom words match normalized-prefix. "hey LLM"→Open WebUI,
"hey DJ"→booth (request, else dj_callin topic). Managed from the desktop
rail 🗣 popup via /api/settings.

Two bugs found wiring the bench (2026-08-17), both non-obvious:
- **voice_generate gated non-xtts/f5/voxtral engines against the Piper
  voice catalog** → a preset engine's own voice (kokoro af_heart) or a new
  clone engine's ref was rejected "No such voice" and the line silently fell
  to Piper (audio came out, wrong voice). Fixed: the gate is registry-aware
  — clone engines gate on voice_ref_path, preset engines own their voice
  namespace. When adding an engine, make sure its voices pass this gate.
- **The right panel column is `<aside>`, not `.col-right`** — every layout
  function (layoutHandles/Save/Restore, the ⇄ swap) targeted `.col-right`
  which never existed, so move/swap silently did nothing and saved layouts
  never restored. Fixed by giving the aside `class="col-right"`.

Memory pressure: the GB10 unified memory (128G) saturates with XTTS (~24G)
+ F5 + Kokoro + ollama's keep-alive models all resident. VoxCPM's MiniCPM4
KV-cache OOM'd until ollama models were evicted (POST /api/generate
keep_alive:0). Five+ large TTS models cannot all stay resident — load on
demand or evict. This is the GPU-pressure lever from the repair toolkit.

See [voice-fidelity-engine](voice-fidelity-engine.md), [f5-tts-server](f5-tts-server.md), [xtts-clone-server](xtts-clone-server.md),
[panel-ui-debugging](panel-ui-debugging.md).
