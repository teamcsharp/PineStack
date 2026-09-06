# Pine Box FM — how the station actually works

Four documents. Read them in order the first time; after that, `orchestrator.md`
is the one you come back to.

| document | what it answers |
| --- | --- |
| [`the-four-rooms.md`](the-four-rooms.md) | Where a line of dialogue comes from and where it goes. The writing desk, the reserve, the recording room, the pantry, the air. |
| [`orchestrator.md`](orchestrator.md) | The general manager. What it looks at, what it decides, what it can and cannot make anybody do. |
| [`rendering.md`](rendering.md) | What speech costs on this box, why, and every dial that changes it. The numbers are measured, not estimated. |
| [`extending.md`](extending.md) | How to add a segment, a road, or a check without breaking the station. The invariants, and what happens when each one is violated. |

## The one paragraph version

A radio station needs to write and record its dialogue **before** it needs it.
The station is built as four rooms with
material moving through them — **the writing desk** turns a segment's brief
into a script, **the reserve** holds scripts waiting for a slot, **the
recording room** turns a script into audio one actor at a time, and **the
pantry** holds finished audio until the moment it airs. The **orchestrator**
is the general manager who walks between those rooms deciding what gets made
next, working backwards from what the running order is about to want.

## The thing that surprises everyone

The bottleneck changes with workload. Older production samples recorded:

> One phone call costs about **273 seconds of room time** and buys about
> **96 seconds of air**. That is a rate of **0.35** — a third of a second of
> broadcast for every second of work. The canonical hour asks for seventeen
> minutes of phone.

These are elapsed production costs, including queue waits, rather than a
physical limit of the clone engine. The September 2026 audit found some writers
waiting about 670 seconds for seconds of inference. Admission control now
limits that queue, while recording capacity is shared by active engines.
`GET /api/coordinator/capacity` reports the current running order's observed
cost, and `/api/coordinator/resources` exposes measured memory, GPU and work
queues. See [the DGX audit](dgx-resource-audit-1060.md) and
[the inbox verification report](inbox-resolution-audit-2026-09-06.md).

## Where the code is

Most station behavior is in `app.py`, in one process. The panel and radio
page are HTML strings inside it (`CONTROL_PANEL_HTML`, `RADIO_PAGE_HTML`).
`station_flow.py` stores the event journal and broadcast outcome memory;
`response_bank.py` stores reusable listening responses, `tint_recovery.py`
revalidates saved rewrite evidence, `resource_guard.py` evaluates measured
resource use, and `newspaper_city.py` prepares varied local image stories.
The Electron app in
`desktop/` also manages LCD discovery, display modes, firmware and local
sample downloads. These Python modules ship with the desktop app.
