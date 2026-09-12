---
name: services-steward
description: "#1153: services_census + steward (census→repair→re-census), chat 'how are the services' + spoken restart commands, hostsvc-kick bridge, 🏥 console"
metadata: 
  node_type: memory
  type: project
  originSessionId: 21948932-a31d-4dd3-9e25-119ba26127d8
  modified: 2026-08-29T02:46:05.895Z
---

**#1153 (2026-08-28): the services steward.** `services_census()` (the
refactored `/api/health/details` body) probes the WHOLE stack: ollama,
searxng (with a real test query), comfyui, home-assistant, open-webui
(pre-existing) + piper/whisper (tcp), voice-lab :8771/health, bgutil
:4416, `xtts_health(force)`/`f5_health(force)`, and "vector guides" as a
virtual service (EMBED_MODEL=nomic-embed-text ∈ ollama tags + te_devices
count). `service_steward(reason, fix)` = census → say each line →
restart every sick service with a wrench → wait 30s (90s if comfy) →
census again → recovered/still-down by name. Ledger `_STEWARD` (comfy-
doctor shape); endpoints GET/POST `/api/steward` ({"fix": false} =
census only); 🏥 Services console auto-opens via dj_state.steward pulse.

**The wrench map** (`steward_restart_one`): compose containers →
socket-proxy restart (SERVICE_CONTAINERS now includes bgutil-pot);
comfyui → COMFY_KICK_PATH; **ollama → data/hostsvc_kick** (host
`hostsvc-kick.path`/`.service` validates content ∈ {ollama, comfyui} →
systemctl restart; bogus names consumed+refused — verified); **xtts →
POST {REACHY_GATEWAY_URL}/api/speech/autofix** (:9010 — tts.sh is just a
wrapper over this API; "launches the clone no matter what"); f5 →
no wrench (honest "needs a hand"; runs from ~/voice-director somehow);
spark-agent → refused (self-restart via panel only).

**Chat**: `is_services_query` ("how are the services doing" etc.) →
live census injected → conversational answer; sick-with-wrench auto-
fires the steward before the reply is spoken; wrench-less named
honestly. `parse_service_command` ("restart/reboot/relaunch/bounce
<alias>", SERVICE_ALIASES covers 'the llm'→ollama, 'web search'→searxng,
'clone server'→xtts, 'yourself'→spark-agent...) OUTRANKS every status
intent incl. comfy_status ("restart comfyui" acts, not diagnoses) and
returns a deterministic confirmation, no LLM.

Verified live: 16-service census ALL WELL; chat ask answered "everything
is running smoothly"; spoken "restart the web search" → searxng Up 10s.

**#1153b — routing, spoken:** `parse_broadcast_command` ("broadcast to
the Nabu", "broadcast locally to the app", "send the music to the pine
box", "route replies here") → the real `/api/dj/output` door via
in-process HTTP with SPARK_AGENT_API_KEY, so #818/#741 side effects ride
along (record moves NOW, feed clears, box wakes, ledger stamped).
Destinations: nabu (route nabu → normalized box+device), pine box
(box + voice_device "pine"), app/locally/here, web page→here, both,
off. Scoped per stream when music/voice/replies named; whole broadcast
otherwise. Outranks status intents; deterministic reply. Verified both
directions against live routing state.
See [comfy-doctor](comfy-doctor.md), [pinevoice-deploy-paths](pinevoice-deploy-paths.md).
