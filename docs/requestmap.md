# PineBox Radio — Architecture Assimilation Request Map

## Mission

You are inspecting the existing PineBox Radio codebase and, where available, its running environment.

Produce a forensic engineering snapshot detailed enough that another engineering LLM can receive this snapshot together with the proposed **System 3** design and determine exactly how to assimilate that design into PineBox without unnecessarily replacing working infrastructure.

This is **not a redesign task**. First establish what PineBox actually does today.

The final snapshot must answer:

> What exists now, what component owns each decision, how does a broadcast travel through the system, what state and data accompany it, and where can System 3 mechanisms be inserted, extended, or substituted safely?

## Ground Rules

1. Inspect actual code, configuration, schemas, prompts, services, APIs, logs, and runtime behavior.
2. Label important conclusions as **OBSERVED**, **INFERRED**, or **UNKNOWN**.
3. Cite repository file paths and relevant classes/functions/configuration keys wherever possible.
4. Preserve PineBox's actual terminology.
5. Do not expose passwords, tokens, API keys, certificates, cookies, or other secrets.
6. Do not redesign PineBox. You may identify extension points, coupling, constraints, and duplicated responsibility.
7. If a requested subsystem does not exist, explicitly write `NOT PRESENT IN CURRENT IMPLEMENTATION`.
8. Prefer diagrams, schemas, traces, and concrete examples over vague prose.

## Required Output Package

Create:

```text
PINEBOX_ARCHITECTURE_SNAPSHOT/
├── 00_EXECUTIVE_OVERVIEW.md
├── 01_REPOSITORY_MAP.md
├── 02_RUNTIME_TOPOLOGY.md
├── 03_BROADCAST_PIPELINE.md
├── 04_CONVERSATION_ENGINE.md
├── 05_DECISION_OWNERSHIP.md
├── 06_PROMPT_SYSTEM.md
├── 07_STATE_MEMORY_AND_CONTEXT.md
├── 08_SCHEDULER_AND_SEGMENTS.md
├── 09_AUDIO_TTS_PIPELINE.md
├── 10_SFX_AND_MUSIC.md
├── 11_RETRIEVAL_AND_CONTENT.md
├── 12_DATABASES_AND_SCHEMAS.md
├── 13_EVENTS_QUEUES_AND_APIS.md
├── 14_UI_AND_CONTROL_SURFACES.md
├── 15_FAILURE_RECOVERY_AND_CONTINUITY.md
├── 16_EXECUTION_TRACE.md
├── 17_GENERATION_EXAMPLES.md
├── 18_EXTENSION_SURFACES.md
├── 19_OPEN_QUESTIONS.md
└── artifacts/
```

---

# 00 — Executive Overview

Explain PineBox in plain engineering language.

Identify its major subsystems and answer:

- What is PineBox Radio today?
- What process/component performs overall orchestration?
- How is programming scheduled?
- How are segments instantiated?
- How are conversations generated?
- How are topics and speakers selected?
- How is conversation state maintained?
- How are prompts assembled?
- Which LLM/model endpoints are involved?
- How does generated text become audio?
- How are SFX and music inserted?
- How is audio queued and played?
- How does the UI observe/control the station?
- What persists across turns, segments, and restarts?
- What determines when a conversation ends?
- What determines what happens next?

Include a diagram of the **actual current architecture**.

---

# 01 — Repository Map

Produce a useful repository tree approximately 3–5 levels deep. Collapse dependency directories, caches, generated build output, `.git`, virtual environments, etc.

Annotate important directories and identify:

- application entrypoints
- orchestration
- frontend/backend
- workers
- configuration
- databases
- prompts
- conversation code
- scheduling
- retrieval/RAG
- TTS/audio
- music/SFX
- deployment/runtime definitions
- tests

---

# 02 — Runtime Topology

Determine what actually runs.

Inspect Docker/Compose, systemd, process managers, launch scripts, Python/Node services, model servers, Redis, Redpanda/Kafka, vector databases, SQL databases, TTS services, local LLM endpoints, external APIs, WebSockets, and frontend services as applicable.

For each component record:

| Component | Process/Service | Host | Port | Protocol | Dependencies | Started By | Persistent? | Purpose |
|---|---|---|---|---|---|---|---|---|

Include a runtime communication diagram.

---

# 03 — Broadcast Pipeline

Trace the real path from **scheduled programming to audible output**.

For every stage identify:

- owning module/file
- function/class
- input
- output
- state read
- state written
- sync/async behavior
- error behavior
- trigger for the next stage

The trace should expose all transformations between schedule, segment, generation, retrieval, post-processing, TTS, SFX/music, queueing, and playback that actually exist.

---

# 04 — Conversation Engine

Determine:

- how conversations begin
- participant selection
- first/next-speaker selection
- topic selection
- number of turns generated at once
- streamed vs ahead-of-time generation
- history representation
- context-window management
- summaries
- personality/character representation
- character-specific state
- interruptions
- agreement/disagreement
- reactions
- topic transitions
- conversation termination
- duration enforcement
- whether each behavior is deterministic, stochastic, LLM-controlled, rule-controlled, or mixed

Inventory **every source of randomness**:

```text
Random decision:
Implementation:
Possible outcomes:
Weighting:
Seeded?:
Logged?:
Persistent?:
Consumer:
```

---

# 05 — Decision Ownership

This is a critical deliverable.

Determine what currently decides each behavior.

| Decision | Current Owner | Mechanism | Source Location | Observable? | Logged? |
|---|---|---|---|---|---|
| Next segment | | | | | |
| Segment duration | | | | | |
| Topic | | | | | |
| Initial speaker | | | | | |
| Next speaker | | | | | |
| Emotional tone | | | | | |
| Agreement/disagreement | | | | | |
| Conversational reaction | | | | | |
| Pushback/escalation | | | | | |
| Topic transition/reframe | | | | | |
| Conversation ending | | | | | |
| Prompt contents | | | | | |
| Context selection | | | | | |
| Retrieval result | | | | | |
| SFX selection | | | | | |
| SFX timing | | | | | |
| Music selection | | | | | |
| TTS voice | | | | | |
| TTS style/intonation | | | | | |
| Playback order | | | | | |
| Failure recovery | | | | | |

Use classifications such as **LLM**, **deterministic code**, **RNG**, **weighted RNG**, **configuration/database**, **scheduler**, **operator**, **external service**, or **mixed**.

Make especially clear which decisions are currently delegated implicitly to the LLM.

---

# 06 — Prompt System

Inventory every significant LLM invocation and prompt family: system, character, segment, conversation, topic, classification, retrieval, SFX, summarization, formatting, etc.

For each significant call document:

```text
Call:
Called from:
Model/provider:
Purpose:
Inputs:
Context supplied:
Template source:
Expected output/schema:
Parser:
Retry/fallback:
Downstream consumer:
```

Explain exactly how final prompts are assembled. Include representative templates where safe and useful.

---

# 07 — State, Memory, and Context

Identify all:

- global station state
- scheduler state
- segment state
- conversation state
- character state
- topic state
- conversation history
- summaries
- persistent memories
- temporary context
- retrieved context
- playback/audio state

Provide actual schemas/classes/objects.

For every major state object identify its creator, owner, lifetime, persistence, mutation points, and consumers.

Distinguish state that survives:

1. one turn
2. one conversation
3. one segment
4. multiple segments
5. process restart

---

# 08 — Scheduler and Segments

Explain how PineBox structures broadcast time.

Determine:

- hour/day programming representation
- segment schemas
- fixed/dynamic durations
- randomization/shuffling
- priorities
- recurrence
- filler
- dead-air prevention
- overruns/underruns
- transitions
- IDs/bumps
- music breaks
- talk
- callers
- news
- advertisements
- other segment types

Trace one real scheduled segment from definition through execution.

---

# 09 — Audio and TTS

Trace:

```text
generated text
→ speaker/voice mapping
→ TTS
→ returned audio
→ processing
→ queue
→ playback
```

Document engines, endpoints, speaker mapping, voice cloning, emotion/style controls, prosody, speed, pitch, pauses, pronunciation, caching, formats, sample rate, processing, latency, concurrency, and fallbacks.

Explicitly determine whether structured **emotion/intonation metadata** can be supplied independently from spoken text.

---

# 10 — SFX and Music

## SFX

Determine storage, metadata, indexing, semantic/keyword/vector search, selection logic, randomness, repetition avoidance, timing, mixing, volume/ducking, triggers, and whether the LLM selects effects.

## Music

Determine library organization, metadata, selection, scheduling, transitions, fades, queueing, now-playing state, and duration handling.

Explain how both systems interact with conversations and the audio pipeline.

---

# 11 — Retrieval and Content Injection

Inventory every mechanism that can inject external material into generation:

- Markdown/text collections
- databases
- vector stores
- embeddings
- RAG
- semantic search
- quote/joke collections
- news
- caller material
- station lore
- character memories
- other content libraries

For each retrieval system document:

```text
Source:
Ingestion:
Chunking:
Embedding model:
Index/vector DB:
Retrieval:
Top-K:
Reranking/filtering:
Prompt insertion point:
Caching:
Refresh/reindex behavior:
```

Determine whether existing infrastructure could support the proposed **Speakerbox** mechanism. Report compatibility; do not redesign it.

---

# 12 — Databases and Schemas

Inventory SQL/SQLite/Postgres, Redis, vector databases, JSON/flat-file stores, caches, event stores, and other persistence.

Provide relevant schemas/models and relationships among characters, segments, topics, prompts, conversations, turns, schedules, SFX, music, and generated audio/assets.

---

# 13 — Events, Queues, and APIs

Inventory REST, WebSockets, SSE, Redis pub/sub, Kafka/Redpanda, internal event buses, job queues, callbacks, polling, and filesystem watchers.

For significant events/messages provide:

```text
Event/message:
Producer:
Consumer:
Payload/schema:
Trigger:
Persistence:
Ordering:
Retry behavior:
```

Determine whether PineBox already has an event stream suitable for carrying fine-grained System 3 decision events.

---

# 14 — UI and Control Surfaces

Inventory station dashboards, timeline/scheduler views, conversation views, speaker displays, logs, generation status, queues, now-playing UI, audio controls, prompt/segment controls, and configuration surfaces.

For each significant view identify:

- frontend component
- backend source
- update mechanism
- available state
- actions
- event subscription

Determine whether the existing UI could support synchronized:

1. **Conversation View**
2. **Technical/RNG View**
3. **Final Script View**

Report compatibility only.

---

# 15 — Failure Recovery and Continuity

Document behavior when:

- LLM fails/times out
- malformed output arrives
- TTS fails
- retrieval fails
- SFX is unavailable
- music is unavailable
- database fails
- audio queue empties
- generation is late
- segment under/overruns
- a service crashes
- a network dependency disappears

Identify retries, backoff, fallback material, watchdogs, buffering, pre-generation, service restart, and dead-air protection.

---

# 16 — Real Execution Trace

If runtime observation is available, capture at least **one complete representative talk/conversation segment** from scheduling through audible playback.

Use timestamps where available.

For every significant step record:

```text
Timestamp:
Event/action:
Source file/function:
Input:
Output:
State mutation:
Decision/random result:
Next consumer:
```

The trace should expose control flow, model calls, state mutations, retrieval, randomness, SFX, TTS, queueing, and playback.

If current instrumentation cannot expose a stage, say so explicitly. Do not fabricate it.

---

# 17 — Representative Generation Examples

Capture three examples if available:

### A. Strong
A conversation/segment representative of PineBox working especially well.

### B. Typical
An ordinary representative output.

### C. Failure/Weakness
An output that exposes undesirable behavior such as excessive agreement, repetitive transitions, shallow emotional range, premature conclusions, poor topic persistence, unnatural speaker changes, repetitive SFX, or other deficiencies.

For each example preserve, where available:

- input segment
- topic
- participating characters
- assembled prompt
- retrieval
- generated text
- SFX/music decisions
- TTS metadata
- timing
- relevant logs

Do not editorialize unnecessarily; expose the evidence.

---

# 18 — Extension Surfaces for System 3

Do **not** design System 3.

Instead identify existing seams where the following proposed responsibilities could potentially attach:

- CTS — topic/conversation selection
- ES — emotional-state selection
- RS — response behavior
- IRS — initiator response/pushback
- FL — conversational flow/reframing
- Speakerbox prepend/append injection
- SFX operator/agent
- TTS emotion/intonation
- duration-aware conversation direction
- technical RNG visualization
- decision/event ledger
- deterministic replay/debugging

For each proposed responsibility report:

```text
System 3 concept:
Closest existing component(s):
Current owner of this decision:
Likely integration seam:
Data already available:
Data missing:
Potential conflicts:
Coupling/risk:
Unknowns requiring investigation:
```

Do not decide yet whether the component should be replaced, modified, or retained. Supply the evidence needed for that later decision.

---

# 19 — Open Questions and Information Gaps

List anything that cannot be determined reliably.

Prioritize gaps that prevent answering:

- who owns a decision
- where state lives
- what a component consumes/produces
- how timing works
- how audio reaches playback
- how generation is orchestrated
- how the UI receives state
- where System 3 could intercept/control behavior

For each gap state exactly what evidence would resolve it.

---

# Required Cross-System Schematics

In addition to the individual documents, include these diagrams somewhere in the package.

## A. Component topology

Show processes/services and their connections.

## B. Broadcast data flow

Show data from schedule → segment → conversation/generation → audio → playback.

## C. Conversation control flow

Show exactly what causes each conversational turn and what decides the next action.

## D. State ownership

Show where conversation, character, segment, scheduler, retrieval, and playback state reside.

## E. LLM call graph

Show every significant LLM invocation and what calls it.

## F. Audio graph

Show text/TTS/SFX/music/mixing/queue/playback.

## G. UI telemetry flow

Show how runtime state reaches the operator interface.

Use Mermaid where practical so diagrams remain editable.

---

# Artifact Collection

Place useful supporting evidence in `artifacts/` where practical, such as:

- sanitized configuration excerpts
- representative JSON payloads
- schema excerpts
- event payloads
- sample logs
- generated conversation output
- prompt assembly examples
- API response examples

Do not duplicate huge source files or dependency trees.

---

# Final Assimilation Summary

At the end of `00_EXECUTIVE_OVERVIEW.md`, include a section titled:

## What Another Engineer Must Understand Before Integrating System 3

Summarize the minimum architectural truths that must not be violated.

Then include:

## Existing Capabilities Potentially Reusable by System 3

and:

## Architectural Constraints System 3 Must Respect

and:

## Unknowns That Must Be Resolved Before Implementation

Do not recommend a final implementation yet.

The purpose of this package is to allow the next engineering pass to compare:

```text
CURRENT PINEBOX
        +
SYSTEM 3 DESIGN INTENT
        ↓
ASSIMILATION / GAP ANALYSIS
        ↓
TARGET ARCHITECTURE
        ↓
IMPLEMENTATION PLAN
```

The snapshot should be sufficiently concrete that the next engineer does **not** need to guess how PineBox currently works.
