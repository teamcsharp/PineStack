---
name: voice-fidelity-engine
description: "How voice clone quality is measured in this stack, and the duration confound that invalidates naive comparisons"
metadata: 
  node_type: memory
  type: project
  originSessionId: a8169767-f9f9-4abf-896b-3271212da841
  modified: 2026-08-15T18:05:07.990Z
---

There is a **fidelity engine** in voice-lab (`~/pinevoice-stack/voice-lab/app.py`,
bind-mounted → edit + `docker restart voice-lab`, no rebuild): `POST /verify` and
`POST /reference/score`, using `pyannote/wespeaker-voxceleb-resnet34-LM` already
cached under `voice-lab-data/hf`. Harness scripts live in `~/voicefid/`.

**IDENTITY COSINE IS NOT COMPARABLE ACROSS CLIP LENGTHS.** This is the single most
important calibration fact and it invalidated an earlier conclusion. Scoring a
slice of a speaker's own REAL audio against their full reference:

| slice | 0.6 s | 1.0 s | 1.5 s | 3.0 s | 6.0 s |
|---|---|---|---|---|---|
| identity | 0.350 | 0.488 | 0.581 | 0.724 | 0.835 |

Renders average 3.3–3.7 s, so the **duration-matched ceiling is ~0.75**, not the
0.75–0.86 that long same-human comparisons suggest. Always compare like-for-like
durations, and never read a short render's low score as poor cloning.

Other calibration, all measured:
- A **vocos round-trip costs only 0.014** (0.9858). The "the scorer is reacting to
  vocoder artefacts" hypothesis is dead — do not revive it.
- 24k→8k→24k costs 0.21; first-half vs second-half of one reference is 0.76.
- Cosine is a TRACKING metric, never a per-render gate: a render that babbles past
  the text scores HIGHER. Per-render sampling sd ≈ 0.048, so **n≥5**.
- The pass/fail signal is the **whisper read-back**: language_probability > 0.97,
  avg_logprob > −0.45, compression_ratio < 1.5, plus seconds-per-character.
- `splithalf` (first half vs second half of a reference) is the best contamination
  detector — below ~0.4 means more than one person is in there.

**Engine comparison, n=59 paired voices, seed-matched (2026-08-15):**
- Pooled: XTTS 0.4883 ± 0.0134, F5-TTS 0.5199 ± 0.0156 → +0.0315, t(58)=1.81,
  p=0.076. **A null on the pooled number.**
- But it averages opposites. **Long copy (67–68 char probes): F5 +0.1192,
  t=7.36, p=7.3e-10, F5 wins 52/59.** Short probe (12 chars): F5 −0.2546,
  because F5 renders it in 0.63 s — below the metric's floor.
- Against the duration-matched ~0.75 ceiling, XTTS reaches 73% and F5 89% on
  long copy. XTTS is better on CER (0.055 vs 0.151) and short text.

See [xtts-clone-server](xtts-clone-server.md), [f5-tts-server](f5-tts-server.md), [spark-agent-environment](spark-agent-environment.md).
