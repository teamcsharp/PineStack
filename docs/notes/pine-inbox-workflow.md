---
name: pine-inbox-workflow
description: "What \"inbox\" means here and the full resolver workflow for Pine Box requests"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b7915ce-38d4-41a6-8fe0-c5344d093b3b
  modified: 2026-08-15T22:16:26.119Z
---

When the user says **"inbox"** they mean: process the Pine Box inbox — open requests in `data/pine_requests.md` (canonical, newest first, human/Claude-editable). Each request may have screenshots in `data/pine_uploads/` (read them — they carry most of the context).

Resolver workflow:
1. Implement each request in `app.py` (single ~49k-line FastAPI file; Python ~1–26k, embedded panel HTML/JS after).
2. Deploy: no hot reload — `POST http://10.89.1.246:8096/api/service/restart`
   with body `{"name":"spark-agent"}` (it 500s on an empty body — the handler
   reads `payload["name"]` first), then poll `/healthz`; it is back in ~3s.
   Or `docker restart spark-agent` on the host.
3. Resolve: `POST /api/pine-requests/{id}/resolve` with JSON `{"reply": "..."}` and header `Authorization: Bearer <SPARK_AGENT_API_KEY>` — logs to chat history, removes from the .md, speaks a completion phrase. Reads (GET) need no auth.
4. Commit batch with request numbers in the message (e.g. "#163 voice call-in, #166 …").

Two encoding traps when driving this from PowerShell:
- `Invoke-RestMethod -Body "<json string>"` sends **latin-1**: em dashes come out
  as `-`, and any non-latin-1 char (e.g. `·`) 500s the resolve endpoint with a
  `UnicodeDecodeError`. Pass bytes instead —
  `-Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType "application/json; charset=utf-8"`.
- Multi-line `git commit -m @'…'@` breaks on a `"` inside the here-string. Write
  the message to a scratchpad file and use `git commit -F`.

API key: `SPARK_AGENT_API_KEY` in `\\10.89.1.246\ehm_eckx\pinevoice-stack\.openwebui.env`. App base: `http://10.89.1.246:8096`. See [spark-agent-environment](spark-agent-environment.md).
