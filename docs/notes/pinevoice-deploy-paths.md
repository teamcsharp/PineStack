---
name: pinevoice-deploy-paths
description: "How each PineVoice container gets updated — bind mount vs rebuild, and the SSH path"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b7915ce-38d4-41a6-8fe0-c5344d093b3b
  modified: 2026-08-14T20:07:06.490Z
---

**SSH works**: `ssh ehm_eckx@10.89.1.246` (key-based, no password). That's the way to run `docker compose build/up`, read logs, and `docker exec` — the docker-socket-proxy on :2375 is restarts-only and loopback-only.

Deploy per service:
- **spark-agent** — `./spark-agent:/app` bind mount. Copy `app.py` to the share, then `POST /api/service/restart {"name":"spark-agent"}`. No rebuild, no hot reload.
- **voice-lab** — was `COPY app.py` (baked into the image). As of 2026-08-14 I added `./voice-lab/app.py:/srv/app.py:ro` to compose.yaml, so it's now copy-and-restart like spark-agent. **Changing `voice-lab/requirements.txt` still needs `docker compose build voice-lab`** (~4 min).
- **bgutil-pot** — added 2026-08-14, `brainicism/bgutil-ytdlp-pot-provider:1.3.1` on 127.0.0.1:4416, bridge networking (everything else is `network_mode: host`).

`compose.yaml` and `voice-lab/` are **not** in git; only `spark-agent/` is a repo. Don't commit the user's pre-existing unrelated modifications (tools/, voice-messages.md, requirements.txt).

Verify after deploy: `/healthz` (spark-agent) and `:8771/health` (voice-lab, reports ytdlp version, js_runtime, impersonate, pot, cookies). See [spark-agent-environment](spark-agent-environment.md), [ytdlp-extraction-gotchas](ytdlp-extraction-gotchas.md).
