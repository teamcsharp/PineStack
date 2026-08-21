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

A radio station that never stops talking has to write and record its dialogue
**before** it needs it, because the voice engine on this box runs about three
times slower than real time. So the station is built as four rooms with
material moving through them — **the writing desk** turns a segment's brief
into a script, **the reserve** holds scripts waiting for a slot, **the
recording room** turns a script into audio one actor at a time, and **the
pantry** holds finished audio until the moment it airs. The **orchestrator**
is the general manager who walks between those rooms deciding what gets made
next, working backwards from what the running order is about to want.

## The thing that surprises everyone

The station's bottleneck is not the model and it is not the disk. It is the
**clone engine**, and the arithmetic is unforgiving:

> One phone call costs about **273 seconds of room time** and buys about
> **96 seconds of air**. That is a rate of **0.35** — a third of a second of
> broadcast for every second of work. The canonical hour asks for seventeen
> minutes of phone.

Everything else in these documents follows from that number. `GET
/api/coordinator/capacity` computes it live for the running order you actually
have.

## Where the code is

All of it is in `app.py` — one file, one process. The panel and the radio page
are HTML strings inside it (`CONTROL_PANEL_HTML`, `RADIO_PAGE_HTML`); the
desktop shell is a thin Electron wrapper in `desktop/`. Every symbol named in
these documents is real and can be grepped for.
