---
name: repetition-on-air-measured
description: 43.6% of aired lines are exact repeats; emergency_host is 28 lines / 919 airings / 97% - the cooldown map was never persisted
metadata:
  type: project
---

2026-09-10 (#1175). "It was repeating lines and not varying enough",
counted off `data/air_log.jsonl` — 19,752 rows over 48.2 h, keeping only
rows whose `aired` is box/stream (the rest are `prepared`, i.e. plans).

**6,256 lines sounded → 3,528 distinct → 2,728 (43.6%) exact repeats.**

It is NOT spread about. Two fixed banks own nearly all of it:

    kind             aired  distinct  repeat%   worst
    emergency_host     919        28    97.0%   91 airings of one line
    sfxguy             427        34    92.0%   66
    gallery            216        82    62.0%    8
    call             1,156       786    32.0%    7
    interject        1,212     1,212     0.0%    -

Those two are **28.7% of every spoken line on the station**. One line went
out 91 times in two days — once every 32 minutes.

**THE COOLDOWN WAS NEVER PERSISTED.** #1068 saw this ("the same eight lines
seventy times in a day"), went 4 pairs → 14, and added "no continuity line
twice inside an hour" written against
`said_at = _CONTINUITY_STATE.setdefault("said", {})` — an in-process dict
never written to disk. The recorded CLIPS persist; the memory of playing
them does not. Measured minimum gap between two airings of the same line:
**31 seconds** against a rule that says 3,600. Every restart hands the
reserve its whole rotation back — and a day of heavy deploying is a day of
heavy repetition.

**THE CONTRAST THAT MATTERS:** `gold_bars.json` holds **1,416 distinct
rhymed recorded lines, 138 never fired, not one fired twice**, sitting
beside a 28-line bank carrying a fifth of the air. #1064 already taught
`sfx_fill_gap` gold-first and measured why (gold: 6s median gap;
continuity: 32s mean, rate-limited by construction). `continuity_air`
never learned it — it does now, at the top, so every caller benefits.

**Method note:** sampling the API during a restart returns an EMPTY shelf
(rows load from disk after the port opens). A watch that samples across a
deploy will report a catastrophic loss that did not happen — check
`/api/director/why/<kind>` again before believing it.

See [which-pile-a-road-lives-on](which-pile-a-road-lives-on.md), [repertoire-dead-air-lcd](repertoire-dead-air-lcd.md),
[rhyme-variety-flow-calls](rhyme-variety-flow-calls.md).
