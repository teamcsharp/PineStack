---
name: every-fix-becomes-a-tool
description: "Operator's standing rule: every cure discovered by hand must become a rung the orchestrator can press itself"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-12T05:44:58.111Z
---

Operator's standing rule, 2026-09-12: **every fix we ever apply by hand to
get the station back on air must be added to the orchestrator's ladder as
a tool it can press itself.** "Any time that we make a fix to the station
to get it back up, I need you informing the orchestrator as far as how to
work the station."

**Why:** over 2026-09-11/12 every cure was found and applied by hand, and
the commonest one — reload the page — had to be asked for in words four
times. The operator does not want to watch the orchestrator sit still
while the station is silent.

**How to apply:** when a new cure is found, add it in three places —
1. `BROADCAST_STEPS` + a branch in `broadcast_step()` (the named step and
   its transcript), so the ⚠ Broadcast Fixer console can run it;
2. `AIR_LADDER` in `air_watch()` (#1213) if it is safe to fire unattended,
   with a quiet-seconds threshold;
3. the #1212 restart rail's ladder in `fixRun()` if it has a client half.

Then say so in the commit, because the ladder IS the documentation.

Hard-won constraints on that ladder:
- **Never auto-undo a pause.** A pause is the operator's own hand on the
  door; the watchdog reports it loudly and stops. See [pause-gags-the-page](pause-gags-the-page.md).
- **Measure the LISTENER, not the station.** `air_quiet_for()` (time since
  any listener reported audible volume) is the only clock that told the
  truth; `dead_air_watch` reported healthy through six hours of silence.
- The process restart rung is rate-limited to once an hour, and when the
  ladder is spent it must NAME what needs hands rather than loop.

**The canonical example is now the Reinitialise ladder (#1331/#1335)** —
one button, thirteen rungs, each one named in `docs/pinetab.md` §23. Auditing
it against the code found **five cures that already existed as working code
with no button anywhere to reach them**: RELIEVE (which the station's own
`AIR_LADDER` puts *first*), a station-wide PAGES (the rung was a
`location.reload()` of the operator's own tab, and the wedged listener is
usually a different tablet), DEEP and SERVICES (never called at all, so a
dead voice engine got "cured" by restarting the station around it), and
`_floor_break`, which had exactly one caller — the silence branch of
`dead_air_watch` — and no operator path at all.

Then the ladder could not reach its own **rung nine**: rung 8 PAGES called
`reload_pages`, which reloaded the operator's own page with no resume mark
written, so the run died there and nothing below it was ever seen. And the
whole client-side vocabulary was **a page reload** — until #1335 added a real
client restart (rung 9 TERMINAL stamps `kiosk_kick`; the desktop sees it on
its `/api/dj` poll and force-stops and relaunches the kiosk over adb, which
is the one cure a reload cannot be).

The rule that came out of it: **"A cure the operator cannot reach during the
fault it cures is not a cure the station has."**

Surfaces: `GET /api/broadcast/watch`, `GET /api/broadcast/console`,
`POST /api/broadcast/fix/{step}`, `data/air_fixes.jsonl`.
