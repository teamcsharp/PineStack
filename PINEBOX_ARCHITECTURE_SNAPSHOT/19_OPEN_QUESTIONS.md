# Open Questions and Information Gaps

| Priority | Gap | Why it matters | Evidence that would resolve it |
|---|---|---|---|
| P0 | Exact System 3 contracts are unavailable | cannot decide compatibility or ownership transfer | design document, event schemas, latency/replay requirements |
| P0 | No exact end-to-end ID joins every current stage | assimilation could produce duplicate or unauditable decisions | add/read a trace carrying schedule occurrence -> model call -> script revision -> assembly -> delivery -> receipt |
| P0 | Whole-round vs per-turn System 3 generation expectation | current engine normally generates batches | explicit System 3 generation granularity and interruption contract |
| P0 | Authoritative live Compose/systemd definitions not in repo | process ownership/restart/resource assumptions could be wrong | read-only host copies of Compose, unit files, env key names with values redacted |
| P1 | Which legacy keepers/fallback roads are intended to remain | dual production paths can race or duplicate work | operator policy and live System 2 config/road-by-road ownership decision |
| P1 | Emotion field support per active TTS engine | structured ES metadata may be discarded or change cache identity | engine capability probes and sanitized request/response samples |
| P1 | Required deterministic replay scope | current data can replay order/content but not every decision/external result | definition: text, audio, timing, or full listener-observed broadcast |
| P1 | Canonical conversation identity | chat, screenplay, call, round, SID, script, and delivery IDs are not universally joined | documented identity model or runtime trace with all IDs |
| P1 | Schedule occurrence identity on non-System2/interjection roads | several observed air rows had empty `sid` | instrument the road trigger and commit with occurrence/slot ID |
| P1 | Exact prompt provenance coverage | screenplay may use `matched: recent`, creating false associations | durable model call ID stamped into generated script/line and carried through render |
| P1 | RNG reproducibility and logging overhead | technical RNG/replay cannot be guaranteed | inventory with seed/state/candidate population; performance test for event emission |
| P2 | Active crystal/tint policy during snapshot | current hour showed zero tinted screenplay lines | live sanitized tint settings, `/api/tint`, and exact line-level verdict joins |
| P2 | Optional service health (F5/Cosy/Index/Qwen/Vibe/HA) | source lists adapters, not live capability | `/health`/service census captures with secrets removed |
| P2 | SFX final-choice explanation | selected clip is known; full candidates/scores often are not joined | emit candidate set, scores, RNG/deck draw, and cue ID under trace |
| P2 | Music transition semantics across all routes | browser, public stream, and box can differ | synchronized route capture with start/end/fade/ACK events |
| P2 | Data retention objectives | multi-GB stores affect query latency and evidence availability | operator retention policy plus measured compaction/recovery tests |
| P2 | Whether UI needs push synchronization | current polling may be sufficient or too coarse | System 3 UI latency target and expected event rate |
| P3 | Quality labels for representative output | no authoritative strong/typical/weak corpus was found | operator-rated examples tied to line/round IDs |

## Explicit Absences

- Redis/pub-sub: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- Kafka/Redpanda: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- Postgres: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- Dedicated vector database service: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- General WebSocket telemetry bus: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- Universal deterministic RNG/decision ledger: `NOT PRESENT IN CURRENT IMPLEMENTATION`.
- Single durable conversation aggregate/state machine: `NOT PRESENT IN CURRENT IMPLEMENTATION`.

