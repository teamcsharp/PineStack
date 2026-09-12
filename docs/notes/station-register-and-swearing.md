---
name: station-register-and-swearing
description: "nothing in the code blocks swearing — no filter, no stop list holds one; the operator's own curse prompt is wired to the CHAT agent, and the tint prompt never asked for a register"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1ccc38-da47-4616-a4bb-8dd39813b3f3
  modified: 2026-09-09T06:45:22.806Z
---

The operator asked for the hosts to "cuss more and use swears and language like the
crystal". An audit of **31 gates** between the crystal and the microphone (2026-09-09)
found **no profanity filter anywhere**: `profan`, `swear`, `curse`, `censor`,
`blocklist`, `vulgar`, `slur`, `family_friendly` return **zero hits** across every
`work/*.py`. Not one swear appears in `_RAP_STOP`, `_TINT_EVAL_STOP`,
`crystal_contract._DEFAULT_STOP`, `pine_rhyme.FUNCTION` or `FURNITURE`. `looks_english`
actively *helps* (it whitelists `ain't gonna gotta y'all`). `_xtts_sanitize` and piper
pass profanity through verbatim.

**It was blocked in exactly two places, both prompt text, zero model asks:**

1. **The operator's own instruction was landing on the wrong layer.** `settings["prompts"][0]`
   is `{"name": "jerk4", "prompt": "Curse excessively and talk in hip hop allegory and
   rhyme."}` with `active_prompt: 0` — but since **#983** that string governs the **Pine
   chat agent only**. The station reads `radio_prompt_overrides["station_system"]`, which
   is absent from the dict with `radio_prompt_enabled["station_system"]: false`, so
   `station_disposition_text()` and `dj_disposition()` both return `''`. **Anything the
   operator writes in the chat prompt box does not reach the air.**
2. **`crystal_prompts._register` was paper-only** (`if kind != "paper": return ""`), so a
   spoken bar got no register line at all. Measured across 199 tint turns the deep model
   proposed a swear **zero times** — never refused, never written. Fixed in #1157.

**Measured gap** (per 1,000 tokens): crystal lexicon 14.8 profane / 13.6 slang; the air
0.96 / 3.6; the **gold bars are the cleanest thing on the station at 0.69**, and under
the tint hold specifically **0.00 over 199 candidate turns**. The harder the crystal is
applied, the more sanitised the output got. Contractions are NOT the gap (air 26-30/k vs
the crystal sample's 29.6/k); `-in'` elision is (gold bars 0.12/k vs 8.6/k), because
`alpha_only` in `pine_rhyme.options_for` drops every apostrophe candidate.

**The grader does not care.** Ten bars in the crystal's register with its profanity vs
clean twins differing only in the swear: **7/10 pass vs 7/10**, zero divergences, and all
three failures were rhyme faults on both sides. Twice the swear was the better craft
(`shit/legit` is a CMUdict perfect pair; the clean twin fell to a near reading).

**Where the line goes:** coarse is in; the rule is **aimed at the situation vs aimed at a
person or a group**. Slurs stay out — `nigga/niggas` is the crystal's 4th-commonest
register word and the station's largest single gap, and a synthetic host with a cloned
voice has no standing to say it. The prompt states that rule rather than chilling the
whole register.

**Do not touch `strip_banned` / `banned_words_clause`** (`app.py` ~21071): the only
word-removal engine in the codebase, operator-owned, per-word with an expiry clock,
currently empty. It is the escape hatch that takes one word off the air in ten seconds
without a deploy — exactly what a register change needs.

Related: [tint-yields-to-air](tint-yields-to-air.md), [gold-freeze-1157](gold-freeze-1157.md), [voice-director](voice-director.md).
