# Extension Surfaces for System 3

This is a compatibility map, not a target design.

| System 3 concept | Closest existing components | Current owner | Likely seam | Data available / missing | Conflicts, risk, unknowns |
|---|---|---|---|---|---|
| CTS: topic/conversation selection | topic cooker, caller topics, schedule/System2, Speakbox | mixed scheduler/RNG/operator/LLM | before `dj_banter`/`dj_call_generated`, or System 2 candidate preparation | available: road, slot, recent topics, sources, deadlines; missing: normalized topic decision record | may conflict with schedule briefs, source cooldown, operator angle; high coupling to roads |
| ES: emotional-state selection | `speaker_state`, weather, `performance_vector`, `perf_directive` | code/RNG plus LLM wording | before prompt assembly and render assignment | available: seat/voice/current vector; missing: durable normalized emotion timeline | engine semantics vary; state persistence/decay ownership unclear |
| RS: response behavior | approach picker, prompts, response bank, LLM | mostly LLM under prompt | structured clause before each turn/round, then validator | available: cast, topic, recent text; missing: explicit response-act field | can duplicate approach/director rules; whole-round generation limits per-turn intervention |
| IRS: initiator response/pushback | escalation feel, approach, caller/banter prompts | mostly LLM | road prompt immediately before generation or structured post-parse check | available: initiating turn and speaker state; missing: explicit pushback decision | forcing post-generation changes can invalidate script/audio digests |
| FL: flow/reframing | schedule/road transition, approach, LLM transitions | LLM within round; scheduler between | round planning before prompt, or between generated turns if generation mode changes | available: source/topic/history/budget; missing: canonical conversation phase | conflicts with model-authored sequence and line-count contracts |
| Speakerbox prepend/append | Speakbox quote/search, rate dials, segment prompt expansion | RNG/config/retrieval | existing `speakbox_quote` result and prompt insertion points | chunks, source, mind, cooldown, prepend/append/full-swath dials exist | spelling/concept contract; duplicate injections/provenance |
| SFX operator/agent | `sfx_match`, cue/reaction, cadence, assembly | deterministic scoring + RNG | cue planning before `assemble_conversation` | clip metadata, scores, bans, history, line positions; missing: unified candidate explanation in final ledger | must preserve deck/cadence and audio timing; model must not invent paths |
| TTS emotion/intonation | performance vector, renderer config, render request | code/RNG + adapter | actor assignment/render request before cache key/render | actor/voice/engine/fx available; missing: engine-neutral guaranteed schema | cache identity and engine support differ; fallback loses nuance |
| Duration-aware direction | System2 slot targets/deadlines, writing budget, measured audio | scheduler/code | `system2_writing.turn_instruction`, before generation, and fit gate | target/debt/deadline, expected turns, measured renders; missing: predicted duration per semantic act | overruns affect record binding/playout; model word count is not audio duration |
| Technical RNG visualization | flow UI, model options, schedule/source/SFX ledgers | distributed `random` calls | emit draw events to FlowJournal and expose common trace ID | selected outcomes often available; missing: pre-draw population/weights/seed for most decisions | instrumentation overhead and schema volume; no current deterministic RNG root |
| Decision/event ledger | FlowJournal, System2/review/admission/playout ledgers | each subsystem | FlowJournal for observations, domain ledger for authoritative state | IDs/timestamps/trace links already exist; missing: versioned universal decision schema | async flow persistence is not transactional; avoid creating a second source of truth |
| Deterministic replay/debugging | `playout_sequencer.replay`, manifests, script/air/model ledgers | playout and domain stores | script/manifests for content replay; sequencer replay for ordering | text/audio IDs/order/receipts partly available; missing: all RNG inputs, exact prompts, external responses | exact full-station replay currently impossible; define replay scope first |

## General Coupling Boundaries

- **OBSERVED:** Before model generation, content can change freely while preserving slot identity.
- **OBSERVED:** After a script is frozen, changes require a new revision/occurrence and render work.
- **OBSERVED:** After assembly/admission, changes must preserve digests/cue maps or create a new assembly/admission.
- **OBSERVED:** After publish, correction is a withdrawal/replay/new delivery, never silent mutation.
- **INFERRED:** System 3 responsibilities that operate on intent fit naturally before script freeze; responsibilities that operate on performance fit at render request; final ordering belongs at admission/sequencing boundaries.

