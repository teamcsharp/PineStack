# PineBox Radio — System 3 Assimilation & Engineering Blueprint

## Companion to the original System 3 PDF

### Required inputs
The implementing LLM/engineer must read together: **(1)** the original System 3 PDF as authoritative product/behavior/UI intent, **(2)** `PINEBOX_ARCHITECTURE_SNAPSHOT/` as authoritative current-state engineering evidence, and **(3)** this blueprint as the assimilation/execution strategy.

Do not use this blueprint to erase requirements from the PDF. Preserve the intended experience and reconcile it against the real architecture rather than silently simplifying it.

# 1. Mission
Transform PineBox so **System 3 explicitly directs conversational behavior and the LLM performs that direction as natural language**.

System 3 must enable emotional variation, disagreement, pushback, escalation/de-escalation, reframing, callbacks, tangents, recovery, retrieved-material intrusions, radio-clock awareness, intentional SFX/performance direction, inspectable decisions, replay/debugging, and synchronized operator interfaces.

> **The LLM writes the words. System 3 decides what kind of conversational action should happen.**

Preserve continuous-radio reliability, scheduling, provenance, rendering, admission, sequencing, publication, and no-dead-air behavior.

# 2. Architectural position
Reuse PineBox's existing System 2 planning/reservations/deadlines, roads, character/voice bindings, speaker-state/performance concepts, Speakbox retrieval, SFX library/assembly, prompt/model infrastructure, script provenance, TTS/render cache, prepared audio, admission, floor ownership, linear sequencing, publication, listener receipts, fallbacks, and evidence ledgers.

The principal missing primitive is an authoritative **ongoing conversation aggregate/state machine**. System 3 fills that gap.

```text
System 2 / Schedule
        ↓
System 3 Conversation Director
        ↓
Structured Scene / Turn Intent
        ↓
LLM Language Performance
        ↓
Validation → Script Freeze
        ↓
Performance/TTS + SFX Plan
        ↓
Existing Assembly / Admission / Sequencing
        ↓
Broadcast → Listener Receipt
```

System 3 owns conversational behavior **before script freeze**. Semantic changes after freeze require a legitimate new script revision. System 3 does not replace the master scheduler or final playout sequencer.

# 3. Authoritative conversation aggregate
Implement one aggregate and reference existing PineBox identities wherever possible.

```text
System3Conversation
├── identity: conversation_id, trace_id, schedule_occurrence_id, system2_slot_id, road_kind, revision
├── timing: target_duration, elapsed_estimated, elapsed_rendered, remaining, deadline
├── subject: topic, sources, active_angle, topic_exhaustion, unresolved_points[]
├── participants[]: actor_id, position, emotion, intensity, energy, recent_actions[], callbacks[]
├── dynamics: phase, tension, agreement, energy, novelty, repetition_risk, closure_pressure
├── turns[]: turn_id, speaker, decision_bundle_id, text, script_id, performance_intent, delivery_id
└── decision_events[]
```

Randomness must be **state-conditioned**, not unrelated rerolls. Previous state, personality, the other speaker's action, topic, phase, tension, agreement, remaining time, unresolved points, callbacks, repetition history, and cooldowns may modify probabilities.

# 4. Canonical decision families
## CTS — Conversation / Topic Selection
Select subject/angle/topic movement only where System 3 has authority. Respect System 2's scheduled subject/source obligations.

## ES — Emotional State
Normalize and extend existing `speaker_state`, weather, `performance_vector`, and `perf_directive`. Record emotion, intensity, energy, transition source, and persistence/decay. ES influences language and TTS where supported.

## RS — Response Strategy
Choose the responder's conversational act. Configurable examples: agree, qualify, disagree, challenge premise, request evidence, tease, joke, deflect, answer, anecdote, correct, misunderstand, clarify, intensify, soften, redirect, callback, reject premise, disbelief, concede, synthesize.

## IRS — Initiator Response / Pushback
Choose the initiator's reaction: accept, double down, defensive response, concede, escalate, clarify, counter, laugh off, reframe, retreat, challenge detail, emotional transition. This prevents automatic LLM conciliation unless selected.

## FL — Flow / Conversational Movement
Choose continue, deepen, broaden, tangent, anecdotal reframe, callback, escalation, de-escalation, contradiction, unresolved-point return, bridge, closure, final callback, or segue. FL becomes increasingly radio-clock aware.

# 5. Behavioral tables
Store CTS/ES/RS/IRS/FL outcomes as versioned data, not scattered conditionals. Support `id`, label, description, base weight, allowed/disallowed phases, compatible emotions/actions, cooldown, min/max remaining time, and speaker/topic/tension/agreement modifiers. Compute and record **effective weights** so behavior can be tuned without code changes.

# 6. System 3 RNG and decision ledger
Give each conversation a root seed. Every System 3 draw records decision family, candidate set, effective weights, random value, selected candidate, state before/after, and common IDs.

Create versioned `System3DecisionEvent` records containing event/schema IDs, conversation/trace/turn IDs, timestamp, decision family, state before, candidate set, effective weights, RNG seed/draw, selected value, state after, prompt/script/render/delivery IDs, and metadata.

FlowJournal may receive observational copies, but define one authoritative System 3 event/state source. Do not claim external LLM/TTS determinism unless captured outputs are reused.

# 7. Generation modes
## Mode A — Planned Scene / Batch Rendering — implement first
System 3 plans the behavioral trajectory, then the existing LLM renders natural multi-turn dialogue.

```text
T1 Ashley: ES curious / RS question
T2 Marcus: ES amused / RS answer / FL anecdote
T3 Ashley: ES skeptical / RS challenge
T4 Marcus: ES defensive / IRS pushback / FL escalate
                     ↓
                 ONE LLM CALL
                     ↓
              natural dialogue
```

This preserves ahead-of-time generation, TTS preparation, parsers, buffering, and no-dead-air behavior.

## Mode B — Turn-by-Turn Direction — later/selective
`generate → validate → update state → decide → generate next turn`

Use for callers, arguments, interactive segments, operator intervention, and unpredictable retrieval. Maintain a prepared-content/audio buffer.

# 8. Validate LLM compliance
Do not assume prompt compliance. Validate speaker/turn count, RS/IRS behavior, emotional direction, required Speakerbox material, prohibited behavior, topic/source obligations, closure/segue requirements, and existing line/round contracts. Prefer deterministic validation. Log model-based semantic judgments separately when needed. Before freeze, failures may trigger bounded targeted repair/regeneration with provenance. Never risk dead air.

# 9. Speakerbox
Reuse current ingestion, chunking, embeddings, retrieval, locks, cooldowns, provenance, and prepend/append/full-swath concepts. Add explicit modes:

`NONE | PREPEND | APPEND | FULL_SWATH | REFERENCE | CALLBACK_TO_PRIOR`

Record attempt/weight, mode, candidates, selected source/chunk, retrieval score, cooldown effects, insertion point, and influenced lines where traceable. Never silently override scheduled source obligations.

# 10. SFX Guy
Implement the PDF's SFX concept as a decision controller over the existing SFX library, not a replacement for indexing/assembly. Inputs include recent conversation, turn intent, emotion, topic, recent SFX, candidate metadata, repetition/cadence constraints, and timing.

Output should include `play`, semantic intent, candidates, selected clip, placement, timing, gain/ducking intent, and reason code. Existing SFX scoring/rotation remains authoritative for real media paths. The LLM never invents paths. Add an **SFX aggression/density** control from restrained to deliberately chaotic.

# 11. Duration-aware direction
Use System 2 targets/deadlines/writing budgets plus actual rendered duration. Track elapsed, remaining, phase, closure pressure, topic exhaustion, and estimated-next-turn duration.

Suggested flexible phases:
`OPEN → ESTABLISH → DEVELOP → ESCALATE/EXPLORE → WILDCARD/TANGENT → RESOLVE → WRAP → SEGUE`

Not every conversation must visit every phase. As time shrinks, reduce new-tangent weights and increase callback/resolution/closure/segue weights. Calibrate from rendered audio.

# 12. Performance → TTS
Map ES onto existing performance machinery through an engine-neutral `PerformanceIntent`: emotion, intensity, energy, pace, emphasis, warmth, tension, pause style, and optional engine hints. Each TTS adapter reports capabilities and degrades unsupported controls gracefully. Material performance changes belong in render provenance/cache identity.

# 13. Three synchronized UI views
The UI is an **operator/debugging instrument**, not decorative animation. Synchronize on conversation, turn, decision-bundle, script, render, and delivery identities.

## A. Conversation View
Show speaker, final text, emotion, phase, Speakerbox/SFX indicators, timing, and generated/frozen/aired/heard status.

## B. Technical / RNG Rolodex
Render the PDF's rolling visualization from **actual recorded events**. Show each CTS/ES/RS/IRS/FL/Speakerbox/SFX draw, candidate set, effective weights, selected result, prior/resulting state, and associated prompt/script/audio IDs. **Never fabricate rolls for visual effect.**

Example:
```text
SYSTEM 3 — TURN 0184
ES  82/100 → APPALLED (.74)
RS  22/48  → CHALLENGE PREMISE
FL  41/60  → ESCALATE
SPEAKERBOX 63/100 → PASS → office_rants.md → passage 18/43
SFX candidates 17 / eligible 13 → clip_0298.wav
```

## C. Final Script / Provenance
Show frozen script, actor/voice, performance intent, SFX/cues, revision, render status, audio identity, playout state, and listener receipt.

## Bidirectional selection
Conversation line → exact decision chain + script/audio provenance. RNG event → affected line. Script line → planning decisions that produced it. This linked inspection experience is a primary product requirement.

# 14. UI transport and controls
Begin by extending existing REST APIs with common IDs and incremental event queries. If profiling shows polling cannot support the live Rolodex, add a dedicated SSE/WebSocket stream while retaining REST snapshots/reconnect recovery.

Initial controls: System 3 OFF/SHADOW/ACTIVE_SELECTED_ROADS/ACTIVE; test seed; emotional volatility; disagreement; escalation; tangent; callback; Speakerbox density; SFX aggression; novelty; closure aggressiveness; generation mode; debug verbosity. Controls alter documented weights/policies, not arbitrary hidden prompt prose. Provide defaults/reset.

# 15. Shadow mode is mandatory
Before live authority: existing PineBox produces the real script; System 3 receives equivalent inputs and creates its plan; that plan cannot reach air; UI/logs show what System 3 **would** have done; compare planned behavior to actual behavior. This validates coherence, timing, event volume, and UI without risking broadcast continuity.

# 16. Replay and persistence
Define replay honestly: **decision replay** reproduces System 3 decisions from state/config/version/seed; **script replay** reuses captured frozen script; **audio replay** reuses captured render/media identities; **playout replay** preserves existing occurrence/delivery semantics. Persist schema/config versions or hashes so old conversations remain interpretable.

# 17. Continuous-radio constraints
System 3 must not block the main event loop with slow file, DB, network, model, or embedding work. Require bounded timeouts/queues, cancellation, fallbacks, no leaked floor ownership, prepared-content buffering, health metrics, and no-dead-air compatibility. Measure decision, LLM, validation, TTS/render, and assembly latency; prepared-audio buffer depth; deadline slack; System 3 failures; and fallbacks.

# 18. Road-by-road adoption
Recommended order: ordinary DJ banter → generated caller conversations → conversational track talk/recap → experimental/special segments → other roads where useful. Fixed IDs, adverts, and deterministic manager messages may not need the full director.

# 19. Implementation phases
1. **Baseline/contracts:** freeze known-good revision, capture strong/typical/weak examples, define metrics and regression tests.
2. **Domain model:** conversation state, participant/dynamics state, intents, events, performance intent, versions, identity correlation. No behavior change.
3. **RNG + decision engine:** root seed, weighted draws, filtering, transitions, CTS/ES/RS/IRS/FL tables, persistence. Same state/config/seed must reproduce the same plan.
4. **Shadow mode:** produce plans/events upstream without changing broadcast. Prove stability and coherence.
5. **Planned-scene integration:** translate decision bundles into structured generation constraints; use existing LLM; validate/repair before freeze.
6. **Speakerbox + performance:** explicit Speakerbox decisions and ES → TTS/performance mapping.
7. **SFX Guy:** connect structured SFX intent to existing candidate/scoring/assembly machinery; never invent paths.
8. **System 3 UI:** Conversation, Rolodex, Final Script views, bidirectional selection, operator controls.
9. **Active selected roads:** enable one road at a time behind feature flags; run long-duration stability tests.
10. **Turn-by-turn mode:** add only after batch mode is stable and latency/buffer measurements prove safety.

Each phase requires tests and a rollback/disable path. Do not begin a broad activation merely because code compiles.

# 20. Testing requirements
Use unit tests for weighted selection, seeds, transitions, cooldowns, time gating, config, serialization. Use invariant/property tests to ensure invalid candidates are never selected, weights remain valid, scheduled sources are not discarded, frozen scripts are not silently mutated, and IDs remain correlatable. Add integration tests from System 2 → System 3 → prompt → generation → validation → freeze → TTS/SFX → assembly. Test failures/timeouts and run hours-long shadow/active tests. Maintain golden-seed tests for known decision trajectories.

# 21. Acceptance criteria
System 3 succeeds when:
1. it explicitly owns the intended behavioral decisions;
2. the LLM primarily realizes structured intent rather than choosing the whole trajectory;
3. conversations maintain coherent evolving state;
4. disagreement/pushback/reframing can persist;
5. emotion affects language and performance where supported;
6. Speakerbox injections are stochastic, traceable, and source-safe;
7. SFX decisions are contextual, traceable, and use real indexed media;
8. flow responds to the radio clock;
9. existing scheduling/playout/no-dead-air contracts remain intact;
10. every System 3 decision is inspectable;
11. the UI can traverse spoken line → decisions → script → render → delivery/heard state;
12. decisions replay at the declared scope;
13. behavior is tunable through versioned data/operator controls;
14. System 3 can be disabled without breaking legacy PineBox;
15. long-run operation remains stable.

# 22. Required implementation documentation
Maintain `SYSTEM3_DECISION_OWNERSHIP.md`, `SYSTEM3_EVENT_SCHEMA.md`, `SYSTEM3_CONFIG_REFERENCE.md`, `SYSTEM3_UI_CONTRACT.md`, `SYSTEM3_ROLLOUT.md`, and an updated architecture diagram. Adapt module paths to the real repository rather than forcing a new tree.

# 23. Rules for the implementing LLM
Before modifying code, map every proposed change to the architecture snapshot and cite the actual files/functions it will affect. Do not invent modules that duplicate existing responsibilities. Make small reversible changes. Keep legacy behavior available behind flags. Do not weaken existing provenance/admission/ordering contracts to make System 3 easier. Do not fabricate runtime evidence. After each phase, report changed files, migrations/configuration, tests, observed results, unresolved risks, and the next gate.

# 24. Final target
The finished system should behave conceptually as:

```text
SYSTEM 2: What belongs on the radio and when?
              ↓
SYSTEM 3: What should these people do conversationally now?
              ↓
LLM: What natural words perform that intent?
              ↓
PINEBOX AUDIO: How should it sound?
              ↓
PLAYOUT: When is it legally/safely admitted to air?
              ↓
OBSERVABILITY: Why did every audible thing happen?
```

The original PDF defines the desired PineBox experience. The architecture snapshot defines reality. **This blueprint is the bridge between them.**
