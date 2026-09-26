# API Family Inventory

The FastAPI application exposes approximately 872 routes. This is a family inventory, not a verbatim route dump.

| Family | Representative routes | Purpose |
|---|---|---|
| health/runtime | `/healthz`, `/health`, `/api/pulse`, `/api/broadcast/health` | process, loop, listener audibility |
| radio/DJ | `/api/radio*`, `/api/dj/state`, `/api/dj/flow`, `/api/dj/banter`, `/api/dj/converse` | show state and actions |
| schedule | `/api/schedule*`, `/api/schedule/hours`, `/api/schedule/segment*`, `/api/schedule/promptbook*` | programs, slots, prompts, generation |
| System 2 | `/api/system2/status`, `/hour`, `/script`, `/line`, `/events`, `/settings` | plan/jobs/traces/events |
| playout/contracts | `/api/playout`, `/api/admission`, `/api/script/production`, `/api/hour/contract`, `/api/bank` | order, gate, production, delivery |
| script/provenance | `/api/screenplay*`, `/api/director/trace`, `/api/script/line/replay` | final script, evidence, replay |
| orchestration | `/api/orchestrator/glass`, `/logic`, `/asks`, `/policy`, `/judgment`, `/rejections*` | capacity, policy, review |
| voice/audio | `/api/voice*`, `/v1/audio/speech`, booth/media routes | voice registry, render, clips |
| music/SFX | `/api/music*`, `/api/sfx*`, `/api/sfx/doctor` | library, queue, soundboard/index |
| retrieval | `/api/library`, Speakbox/vector/search routes | ingest/search/source inspection |
| cache/export | `/api/radio-cache*`, export/staging routes | recordings, cuts, compiled output |
| UI/pages | `/`, `/radio`, `/spark`, `/system2`, `/station-flow/*` | operator/listener surfaces |

Mutation auth: `require_auth` validates Bearer credentials. Read auth: `require_read_auth` applies the read-lock policy. Some diagnostic routes in older embedded UI sections are intentionally open on the trusted LAN; this snapshot does not perform a security review.

