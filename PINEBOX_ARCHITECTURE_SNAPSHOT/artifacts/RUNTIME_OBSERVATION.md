# Runtime Observation

Observation window: approximately 2026-09-26 16:28-16:37 CDT.  
Method: read-only HTTP GETs, TCP connection probes, process listing on the operator machine, and reads of live ledgers on the shared repository path.

## Service Reachability

| Host:port | Result | Interpreted component |
|---|---:|---|
| `10.89.1.246:8096` | open | station API/UI |
| `10.89.1.246:8097` | open | public listen door |
| `10.89.1.246:11434` | open | Ollama |
| `10.89.1.246:8081` | open | SearXNG |
| `10.89.1.246:8188` | open | ComfyUI |
| `10.89.1.246:7860` | closed/no answer | unidentified optional service |
| `10.89.1.125:445` | open | SMB/QuickSwap |
| `10.89.1.154:5555` | open | Android ADB |

## Read API Results

| Endpoint | Reduced observation |
|---|---|
| `/healthz` | HTTP 200, `{status: ok}` |
| `/api/broadcast/health` | `stuck=false`, listeners `3`, "last heard 0s ago" |
| `/api/radio` | `playing=true`, `paused=false`; current music row populated |
| `/api/dj/state` | `on=true`, `playing=true`, `paused=false`; active chat/history/media state |
| `/api/playout?lean=true` | available, mode `linear`, sounding delivery with listener position |
| `/api/admission?limit=3` | mode `off`, unavailable for enforcement |
| `/api/script/production?limit=3` | mode `on`, available |
| `/api/system2/status` | `enabled=true`, `on=true`, `paused=false`, no reported errors |
| `/api/schedule` | active `canonical hour (fits the engine)`, 18 slots |
| `/api/director/deadair` | 498 finished rounds: manager 46, gallery 62, news 15, caller 39, ad 134, station ID 202 |
| `/api/screenplay` | recording active; current hour `2026-09-26T16` |
| `/api/orchestrator/glass` | four rooms: writing, reserve, recording, pantry |

## Orchestrator Room Snapshot

- Writing: 9 in / 11 out in the window, 1 stuck, 2 lanes, oldest 111.7 s.
- Reserve: 651 holding, 587 reported stuck/aged, 3 out in the window.
- Recording: 66 in / 96 out, 398 unrecorded stock, pool cap 6.
- Pantry: 3,406 takes, 31 in / 15 out, ceiling 4,000, 2,904 spoken-for.

These labels are the API's own operational terms; `stuck` in stock rooms includes old held inventory and does not by itself mean the broadcast was unhealthy.

## Live Evidence Stores

During collection, `air_log.jsonl`, `screenplay_*`, `model_calls.jsonl`, `station_flow.sqlite3`, SFX databases, and several stock/coordination JSON files were actively updating. The station server itself ran remotely/on the Spark host; local Windows processes included Electron, ADB, Docker tooling, Node, Python, and ffmpeg.

