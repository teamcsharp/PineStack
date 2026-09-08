# Pine Box FM — the recreation guide (#1087)

Request (2026-09-08): *"a full technical recreation guide allowing me to explain to another LLM this
entire project in its entirety and how to recreate it entirely from scratch"* — every back-end
system, how every service works and connects, what the Pine Box uses and how, the psychology of the
DJs and what was attempted with their logic, the logic trees, and the systems and implementation as a
document.

This is a series. Read it in order the first time; afterwards each document stands on its own.

| # | document | what it explains |
|---|---|---|
| 01 | [services-and-topology.md](01-services-and-topology.md) | every service on the box and around it, ports, who talks to whom, what the Pine Box (the satellite) uses |
| 02 | [station-loop-and-orchestrator.md](02-station-loop-and-orchestrator.md) | the show loop, the roads, the schedule and the hour's obligations, the desks and keepers, the floor, the judgment book |
| 03 | [system2.md](03-system2.md) | the planning engine that drives the station now: store, plans, jobs, dispatch, receipts, the legacy hybrid |
| 04 | [crystal-and-tint.md](04-crystal-and-tint.md) | crystals and minds, the two-pass rewrite, prompts, contracts, the evaluator, the hold, review and learning, rhyme assistance, throughput |
| 05 | [the-djs-psychology-and-logic.md](05-the-djs-psychology-and-logic.md) | who the hosts are, what the operator wants from them, the roads as character, the rules they live under, the logic trees |
| 06 | [data-caches-and-ledgers.md](06-data-caches-and-ledgers.md) | every file under `data/`, what writes it, what reads it, what is safe to wipe |
| 07 | [recreate-from-scratch.md](07-recreate-from-scratch.md) | the build order for another LLM: hardware, services, models, directories, the first minute of air, then the layers |

## How to read the code alongside this

- The station is one process: `spark-agent/app.py` (~7.8 MB, ~170,000 lines; Python first, then
  the control panel's HTML/JS as one string `CONTROL_PANEL_HTML`, the radio page `RADIO_PAGE_HTML`,
  the Gazette pages, the request book page `JOURNAL_PAGE_HTML`). Everything is found with a search
  for the function name or the request number (`#1064`) in a comment; the comments are the design
  record, written at the time, with the measurement that motivated the change.
- Beside it: `system2.py` (the planning store), `system2_runtime.py` (the engine), `system2_media.py`,
  `system2_writing.py`, `crystal_prompts.py`, `crystal_contract.py`, `crystal_rhyme.py`,
  `crystal_acceptance.py`, `crystal_source.py`, `line_review.py`, `prompt_learning.py`,
  `rhyme_assistance.py`, `frontend/system2.js`, `desktop/` (the Electron app and the LCD firmware
  tooling), `tools/` (deploy, inbox resolve, smokes), `tests/` (~350 files, pytest).
- Every request the operator ever made and how it was answered is in `data/pine_completed.md` and,
  page by page with costs, in the request book (`/journal`, `data/pine_journal/`). The inbox
  documents under `docs/inbox-*.md` are the long-form engineering notes per request family.

## What this guide is honest about

- Numbers are measurements from the station's own ledgers where they are given; estimates are marked.
- Where a subsystem's exact behaviour is in code that this guide summarises, the function name is
  given so the reader (or the next LLM) reads the source rather than trusting a paraphrase.
- The project is a working radio station that has been rebuilt many times in place; there is no
  clean architecture diagram that matches every code path. The documents describe the design as it
  runs on 2026-09-08, request #1087.
