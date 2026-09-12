---
name: render-is-slower-than-speech
description: "render = 2.97 + 1.05 x audio — the marginal term is ABOVE ONE, so continuous live-rendered talk is arithmetically impossible; only the bank can fill a hole"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T06:45:02.368Z
---

Fitted over the last 600 renders in `data/render_replay.json` on 2026-09-09:

**`render_seconds = 2.97 + 1.05 × audio_seconds`**

The marginal term is **above one**. The voice engine is slower than speech itself, so
"just render faster" can never produce continuous talk — the ceiling is about **41
minutes of speech an hour at 100% duty**. Any plan that answers dead air by making or
speeding up live renders is arithmetically dead on arrival. Only **banked** audio has
no such ceiling.

The two measurements that go with it:

- The station **speaks 9.6 min/hour** and **makes 9.7 min/hour of audio**. Those being
  equal is the whole story: `render_replay.json` shows `uses: 1` for all 600 of the
  last renders — every second of speech is synthesised fresh for exactly one airing.
  There is no buffer. The GPU is idle 46 minutes an hour and the station is silent 50,
  simultaneously.
- **Shortening lines makes it worse**, not better: a 3.8 s line costs 1.79× realtime
  against 1.47× for a 7.6 s line. Do not answer "gaps between phrases" by writing
  shorter bars.

**Where the holes actually are** (measured over 6,000 aired lines, 4 days):
inside a round, four phrases in five are already back to back — median TRUE silence
(gap minus how long the first phrase takes to say, at a fitted **15.0-15.2 characters
per second**) is **−0.6 s**. The audible holes are the other fifth: 447 seams over two
seconds. Between rounds is far worse: median 52 s, the ten-second rule met 20 times in
1,549 gaps — but ~103% of that has a record spinning under it, so it is a hole in the
TALKING, not silence.

`cover_the_gap` returned `False` whenever `_floor_busy()`, which is precisely when the
holes are, because the floor is held across a render for ~44 s of wall clock. Fixed in
#1157: a held floor is not a talking mouth, and after `FLOOR_QUIET_SECONDS` the bank
speaks into it without taking the floor.

`ENGINE_BUDGET` was 3 and `prep_limit = capacity − 2`, so the whole station banked
audio on ONE slot: **76 of 87 prepared rounds held no audio at all** — about fifty
minutes of radio sitting on the shelf as text that still had to be rendered live, in
the hole. Now 5.

Related: [gold-freeze-1157](gold-freeze-1157.md), [repertoire-dead-air-lcd](repertoire-dead-air-lcd.md), [floor-and-paced-air](floor-and-paced-air.md).
