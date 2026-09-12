---
name: dead-air-and-staleness-measurement
description: "How to measure where the station's dead air and repetition actually are (gap_log/air_log fields), and the four causes found on 2026-09-09"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5f5cd731-6b4f-4e84-be9c-2e804640a125
  modified: 2026-09-09T19:08:40.810Z
---

Before turning any pacing knob, measure. Two files answer everything, off the loop:

- `data/gap_log.jsonl` — one row per closed silence. Fields: `seconds`, `boundary`
  (round/page/line), `cause`, `round` ({kind,label,sheet,live_only,banked}),
  `takes` ({live,shelf,live_ms}), `stall_s`, `stall_top` (the blocking frames),
  `paused_seconds`. **`takes.live == 0` on a gap proves the hole was not TTS.**
- `data/air_log.jsonl` — one row per aired line with `air_at` + `seconds`, so
  line-to-line silence and a same-day repeat census both come straight out of it.
- `data/loop_stalls.json` — the stall hunter's sampled record (`top` frames).

Drop outlier gaps (a wedge shows up as many rows all closed at the same instant)
before reading the steady state.

**2026-09-09, 18.2 h window:** 6.5 h silence, 3.2 h steady-state, 361 holes,
median 23.8 s. 73% of line-to-line gaps were already under 1 s — 12% of gaps
carried 5.2 h. Four causes, all fixed in #1158:

1. `elif caller_name:` in the page-span chain was **unreachable** behind two
   `_all_hit` arms, so a fully banked call over 150 s was paged in eights —
   136 page-join holes, median 20.7 s, zero live takes, 111 of them callers.
   Lesson: an `elif` written as documentation of a rule is not the rule.
2. `gold_fill_gap` fired ONE bar per hole (116 of 134 runs were a single 6.8 s
   bar) while the bank held 514 bars / 67 min / 282 never fired. Now a run.
3. `CONCAT_BEAT` 140–330 ms after every utterance → halved to 70–180.
4. **57% of everything spoken was a repeat** — the back-channel pool was only
   **7 listening rows + 1 surprise per voice** (`PHRASES` in `response_bank.py`);
   the 125 `topic` rows need a two-anchor keyword match and almost never fire.
   `take()`'s LRU rotation was never the fault; the pool was.

Bar length is capped in TWO places, and the obvious one is not the binding one:
rule 3 of the tint prompt (`crystal_prompts.py`) and **`_room`** in `crystal_turn`
(`_lo/_hi` around app.py:86014), which becomes the literal "Output budget: at most
N characters" in the prompt AND the token budget (`limit // 2 + 64`). On a tint,
`max_tokens` ignores `settings["max_tokens"]` entirely. `budget_plan`'s `factor`
is a different thing — it sets batching and the OVERSIZED threshold, so raising it
pushes ordinary turns onto the one-visit-per-turn road the deep lane cannot pay for.

Known-failing tests here that are NOT yours: 9 crystal/prompt-learning tests fail
on Windows `PermissionError [WinError 32]` unlinking `learning.sqlite3`, and
`test_sfx_pool_warm` needs the long TEMP path (see [spark-agent-environment](spark-agent-environment.md)).

Related: [floor-and-paced-air](floor-and-paced-air.md), [repertoire-dead-air-lcd](repertoire-dead-air-lcd.md),
[render-is-slower-than-speech](render-is-slower-than-speech.md), [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md),
[gold-freeze-1157](gold-freeze-1157.md), [tint-yields-to-air](tint-yields-to-air.md).
