# Failure Recovery and Continuity

| Failure | Observed behavior | Evidence/source |
|---|---|---|
| LLM timeout/failure | async HTTP call bounded by timeout; model lane job removed in `finally`; road may return fallback/empty, rest job, or use prepared stock | `app.py:call_ollama`, `ask_model`; `System2Runtime.prepare` |
| Model capacity | per-model lane plus global gate; category caps return `deferred` and mark work owed rather than creating an unbounded queue | `app.py:_ollama_lane`, `_OLLAMA_GATE`, `call_ollama` |
| Malformed output | road parser/contract rejects, retries/repasses, cuts lines, files review evidence, or rests/strikes candidate | crystal/line-review code; `call_entry_contract`; `system2_writing.scene_complete` |
| TTS failure | requested engine -> eligible alternate clone engine -> Piper floor for ordinary lines; cast-locked lines can wait rather than swap identity | `app.py:voice_render_any` |
| Oversize TTS text | sentence split plus forced character-safe split; render pieces and join local files | `voice_render_any` lines 9627+ |
| Retrieval failure | returns no chunks/empty context; generation continues with other facts; indexing work has leases/retry fields | `library.py`; `clip_speech.py:sfx_index_work` |
| SFX unavailable | omit effect/use sting or other eligible clip; cadence reservations released on assembly exception | `app.py` SFX paths; `sfx_match.py`; `_sfx_cadence_release` |
| Music unavailable | queue refill/search; show loop exits music-only loop if no track; continuity reserves and station health expose shortage | `radio_fill`, `radio_next_track`, `_radio_loop`, `_dj_loop` |
| Database contention/failure | WAL/busy timeout, bounded reads, hot work moved to threads; flow journal keeps memory and counts unwritten rows | `system2.py:_connect`; `station_flow.FlowJournal` |
| Audio queue empty | prepared pantry/shelves/larder/cupboard, dead-air rescue order, emergency Piper/sting, records-first behavior | `dead_air_stock`; `/api/director/deadair`; `dialogue_flow_state` |
| Generation late | System 2 deadlines/debt, lease/retry, pre-generation horizon; legacy fallback after `fallback_due()` | `system2_runtime.py` |
| Under/overrun | pre-reservation fit checks, measured durations/cue maps, sequence start/end correction; filler/debt for gaps | System 2 dispatch; `LinearSequencer`; assembly |
| Process crash | startup reclaims System 2 jobs/reservations; admission/playout restore snapshots/events; radio state and ledgers reconstruct partial state | `start_system2`; `PlayoutController.resume`; `LinearSequencer._restore` |
| Network service loss | service census/health, local cache/stock, engine fallback; optional services degrade their road | startup/service health helpers in `app.py` |
| Event-loop starvation | pulse/stall ledger and external watchdog restart described in ops docs; blocking work progressively moved to threads | `/api/pulse`; `docs/recreation/01-services-and-topology.md` |
| Listener/browser wedge | playback heartbeats, canplay/playing/ended ACKs, page-wedge health, kiosk kick via Electron/ADB | `page_playback_ack`; `/api/broadcast/health`; `desktop/main.js` |

## Continuity Layers

1. **Stock:** generation and rendering happen ahead into road shelves and the pantry.
2. **Planning:** System 2 retains hours/jobs/reservations and reclaims dead leases.
3. **Ordering:** script ledger, admission, and linear playout retain intended and delivered sequence.
4. **Audibility:** listener ACKs distinguish publish from heard and correct end time.
5. **Fallback:** legacy keepers, records, rested stock, emergency voice, and stings cover missing roads.
6. **Recovery:** checkpoints, append ledgers, startup reconciliation, health endpoints, and host/desktop restart bridges restore service.

**OBSERVED:** Air-path policy in `docs/extending.md` is explicit: avoid raising; return empty/fallback, keep state stamped consistently, and never make reports infer truth from log prose when authoritative state exists.

**INFERRED:** Recovery is intentionally layered and occasionally duplicative. A new controller that only handles generation failure would still need to cooperate with planner leases, floor release, admission withdrawal, sequence reconciliation, and listener receipts.

