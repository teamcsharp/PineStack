# Events, Queues, and APIs

## Transport Inventory

- **OBSERVED:** REST: FastAPI exposes roughly 872 routes across station, schedule, System 2, DJ/radio, voice, music, SFX, playout, review, orchestration, health, export, and UI assets.
- **OBSERVED:** SSE: inbox event stream only (`app.py:inbox_events`).
- **OBSERVED:** WebSockets: **NOT PRESENT IN CURRENT IMPLEMENTATION** for station telemetry/playout.
- **OBSERVED:** External brokers/pub-sub (Redis, Kafka, Redpanda): **NOT PRESENT IN CURRENT IMPLEMENTATION**.
- **OBSERVED:** Internal queues: `asyncio` tasks/events/locks/semaphores, `queue.Queue` for flow persistence, deques/lists/dicts for model/render/listener work, SQLite job leases, and JSON/JSONL queues.
- **OBSERVED:** Filesystem watching is mostly periodic stat/scan/memo invalidation rather than a central watcher service.

## Significant Messages

| Event/message | Producer -> consumer | Payload/trigger | Persistence/order/retry |
|---|---|---|---|
| Flow event | any instrumented stage -> `FlowJournal`/UI | node, status, summary, details, trace/parent/from | in-memory ordered ID then SQLite async queue; dropped count on full writer queue |
| System 2 job | planner -> preparer | slot, kind, deadline, lease/body | SQLite deadline order; lease renew/reclaim/retry-after |
| System 2 event | operator API -> event loop/planner | kind, request_id, air_at, duration, brief, priority | SQLite idempotent request ID; claim/finish lease |
| Candidate reservation | dispatcher -> delivery | slot/candidate/request IDs, token/state | SQLite; fit/repeat refusal releases or advances |
| Model job | writer -> Ollama lane | model, purpose/category, options/messages | in-memory FIFO visibility; cap may defer as owed; prompt/model ledgers |
| Render assignment | script producer -> performer session | occurrence, actor, text, renderer/capacity | manifest persistence; resume and accepted-take checks |
| Admission event | producer -> `PlayoutController` | candidate/assembly identities and lane | append ledger + checkpoint; observe/enforce mode |
| Playout delivery | sequencer -> page/box | occurrence/delivery ID, route, start, seconds, media | snapshot/event ledger; stale eviction/reconcile |
| Playback ACK | browser/kiosk -> sequencer/flow | listener, delivery, event, position, volume/error | ordered by listener sequence; repeated playing updates; heard/end reconciles timing |
| Air/script row | playback/chat -> keepers/UI/System2 | line/round, actor, text, model/voice/media/times | JSONL and indexes; background append/retention |
| SFX index work | scanner -> speech/vision worker | `(kind,path)` lease, attempts/retry/error | SQLite lease/backoff |

## API Families

`/api/schedule*`, `/api/system2*`, `/api/radio*`, `/api/dj*`, `/api/music*`, `/api/sfx*`, `/api/voice*`, `/v1/audio/speech`, `/api/playout`, `/api/admission`, `/api/script/production`, `/api/orchestrator*`, `/api/director*`, `/api/screenplay*`, `/api/library*`, `/api/pipeline*`, `/api/broadcast/health`, `/healthz`.

Mutation routes generally call `require_auth`; reads call `require_read_auth`, which is open unless `SPARK_AGENT_LOCK_READS` is enabled (`app.py:require_auth`, `require_read_auth`, `LOCK_READS`).

## Event-Stream Suitability for System 3

**OBSERVED:** `station_flow.FlowJournal` already has monotonic IDs, timestamps, named nodes, status, trace/parent/from links, sanitized details, bounded memory, durable SQLite history, incremental reads, and a visualization endpoint. It is the closest current event stream.

**INFERRED:** It can carry fine-grained System 3 decision observations, but it is not currently a transactional command bus: persistence is asynchronous, backpressure can drop disk writes, schemas are open dictionaries, and many existing RNG/prompt decisions are not emitted. Admission/playout/System 2 ledgers provide stronger domain-specific ordering.

**UNKNOWN:** Required delivery guarantees, schema/versioning, retention, and replay semantics for System 3 decisions.

