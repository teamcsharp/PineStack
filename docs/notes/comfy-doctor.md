---
name: comfy-doctor
description: "#1152: ComfyUI runs under systemd with a data/comfy_kick restart bridge; comfy_doctor() troubleshooter + 🩺 panel console; venv needs --break-system-packages"
metadata: 
  node_type: memory
  type: project
  originSessionId: 21948932-a31d-4dd3-9e25-119ba26127d8
  modified: 2026-08-28T19:42:24.094Z
---

**ComfyUI on lilspark (fixed 2026-08-28, #1152):** the engine is a HOST
venv process (`~/ComfyUI` + `~/comfyui-env`, log `~/comfyui.log`), NOT a
container — it was hand-launched with no supervisor, so when it died
(code updated under it; venv missing `sqlalchemy` → crash on start) it
stayed dead and renders errored. Now supervised:
- `comfyui.service` (system unit, User=ehm_eckx, Restart=on-failure,
  RestartSec=10, appends to ~/comfyui.log).
- **The kick bridge**: `comfyui-kick.path` watches
  `spark-agent/data/comfy_kick` (the bind-mounted data dir) →
  `comfyui-kick.service` rm's the flag + `systemctl restart comfyui`.
  The container heals the host engine by touching ONE file. Verified
  end-to-end (flag consumed, service restarted).
- The venv is PEP-668 marked: pip needs `--break-system-packages`; deps
  actually land in `~/.local`. After any ComfyUI code update run
  `~/comfyui-env/bin/python -m pip install --break-system-packages -r
  ~/ComfyUI/requirements.txt` or the service crashloops on import.
- Cold start ≈ 60-120s (pytorch + model scan). GB10, cudaMallocAsync.

**comfy_doctor()** (app.py, #1152): knock /system_stats → up: vitals +
/queue + which workflow (override data/comfy_workflow.json vs
COMFYUI_CHECKPOINT); down: write COMFY_KICK_PATH, poll 180s, re-kick at
95s, verdict REPAIRED/DOWN; deep or post-repair: real test render via
/prompt + /history poll. Ledger `_COMFY_DOCTOR` {running, steps[{at,
line}], verdict}; steps also pipeline_log lane "model". Endpoints: GET/
POST `/api/comfy/doctor` ({"deep":true}). Chat: `is_comfy_status_query`
("what's going on with comfy…") ranks ABOVE image intent → fires doctor
+ immediate probe answer; a FAILED render submit fires it too (auto,
600s throttle). Panel: 🩺 Comfy Doctor in the tile registry
(`comfyDoctorPanel()`), terminal console polling 2s, AUTO-OPENS via
`comfyDoctorWatch` in pollDJ reading dj_state.comfy_doctor.started.

See [pinevoice-deploy-paths](pinevoice-deploy-paths.md), [spark-agent-environment](spark-agent-environment.md).
