---
name: silent-fallbacks-hide-exceptions
description: "#1219: an UnboundLocalError in the welded-round road was invisible for two days because every caller falls back; use air-now, the road that returns the exception"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-12T06:42:31.813Z
---

2026-09-12. Two days of "the DJs aren't talking" was **one
`UnboundLocalError`** in `_speak_turns_floorless`: #1201 read `_round_sid`
inside the coalesced burst loop and minted it **385 lines further down the
same function**, so the welded-round road raised on its first turn every
time and the station fell through to single-line interjects.

**Why it stayed hidden:** every caller of that road catches and falls back
to the turn-by-turn path. Nothing logged a traceback, every health surface
read green, and the show kept making noise — just single lines instead of
conversations, 96% of which then went stale and were dropped (#1207).

**What found it:** `POST /api/director/air-now/{kind}` — the only road that
returns the exception in its HTTP body instead of falling back. When a road
"isn't running" and nothing is broken, **force it and read the error**.

**The measurement that localises this class of fault** — `clip_media` is
set only by the welded road, so its share per hour dates the regression to
the deploy:

    09-11 13   264/283  93%
    09-11 14   102/201  51%   <- deploy
    09-11 15    34/240  14%
    09-11 17    12/302   4%

Likewise `sid`/`turn` (#1201) are stamped only there, and `aired:
published` means handed to the page, never heard. After the fix: 58%
welded, 77 rows with sid, calls/news/manager/banter all present again.

**Rule:** when adding a field to a long function, check where the variable
it reads is *assigned* — and prefer minting such ids at the top of the
function. See [pause-gags-the-page](pause-gags-the-page.md), [every-fix-becomes-a-tool](every-fix-becomes-a-tool.md).
