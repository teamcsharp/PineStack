---
name: f5-tts-server
description: "The F5-TTS engine on lilspark — where it lives, how to launch it, and the reference-clipping trap"
metadata: 
  node_type: memory
  type: project
  originSessionId: a8169767-f9f9-4abf-896b-3271212da841
  modified: 2026-08-19T02:22:51.780Z
---

**#835 (2026-08-18, 0c8b658) — WHY the cast kept living on F5**: the
ACTUAL router is `dj_settings()["clone_engine"]` — the #726 library-wide
override — and it was pinned to 'f5' in data/settings.json, making f5
rung 1 in voice_render_any for EVERY clone regardless of health or
per-voice meta (all cast metas say xtts). Cleared 2026-08-18 via PUT
/api/settings (dj.clone_engine=""). CAUTION: `/api/dj/settings` GET does
NOT expose it — read data/settings.json dj block directly; my earlier
API probe false-negatived. Fourth cause, also fixed: spark-agent's own `xtts_idle_clock` (5-min ticks,
XTTS_IDLE_UNLOAD=1800) kills a READY xtts when `_XTTS_LAST_USED` is
30 min stale — but that baseline only advances on a successful xtts
render, so after ANY downtime every revived XTTS was terminated within
one tick of coming ready, before the first render found it (observed:
deploy→ready→killed cycles at 15:17/15:48/16:23/16:53/17:33/18:54,
pressure.log "idle clock: xtts silent Nm — unloaded"). Fix: xtts_health
stamps _XTTS_LAST_USED on the down→ready transition ("XTTS is back —
idle clock resets (#835)" in the gpu pipeline log). Diagnosis probes:
`latents_cached` in :8770/health is a render counter (0 = no render has
ever reached this boot); the lookahead pipeline event "pre-rendering
the next line - f5 - cohost" tells you the ENGINE PICKED per line.

**#831/#832 (2026-08-18, 3d129e7) — Suno ground truth + voice quality**:
Lyrics: `suno_catalog_refresh()` pulls ALL @mx1001 sheets (556) from
`studio-api.prod.suno.com/api/profiles/{handle}?playlists_sort_by=upvote_count&clips_sort_by=created_at&page=N`
(20/page, no auth, lyrics inline at clips[].metadata.prompt; cache
data/suno_lyrics.json; POST /api/lyrics/suno). Ladder: suno → tags →
sidecars → whisper; thin pages self-upgrade (body < 0.6×sheet+200).
Audit findings (agent, full report in session 7606… tasks/a21c…):
voice-lab whisper = BASE on CPU-int8 (ctranslate2 aarch64 has no CUDA)
+ Silero VAD eats sung vocals + no separation + 180–5200Hz bandpass
cripples it; median 77% timeline coverage. Phase-2 (unbuilt): demucs
4.0.1 (NOT 4.1 — sphn has no aarch64 wheel) + RMS-VAD from the stem →
faster-whisper large-v2 clip_timestamps, vad_filter=False (arXiv
2506.15514). ALSO: extraction loops need `await asyncio.sleep(0)` per
track or the skip-existing sweep starves the event loop (#831).
Voice: pitch trick (asetrate) clamped ±2 semitones — bigger shifts =
"modulating underwater" (#832). Cast reference_f5.wav = REAL first
11.5s of each original (synthetic clone-of-clone made F5 renders sound
processed); ONLY laura keeps the synthetic (her real sample is the
house pitch). fx_rate parked at 0.05.

**#816 (2026-08-18, be135c3) — REFERENCE BLEED, the house that F5 sold**:
F5 renders by CONTINUING its reference; when alignment slips the
reference's own words air. The laura/Skip clone sample (vl_bc2c0710) is a
17s REAL-ESTATE PITCH — "come see this house today" aired for hours in her
voice while all renders rode F5. Ref-cache pairing was verified correct;
the leak is inherent to the model. Fixes: `_f5_synthesize` prefers a
per-voice `reference_f5.wav` (+.txt) when present — laura's is 9.1s of
neutral station copy cut FROM HER OWN XTTS CLONE (clone-of-clone; the
pattern for any voice whose sample contains distinctive speech). ALSO:
every cast reference exceeds F5's 12s clip (14.5–65s!) — the server
whisper-pairs the clip correctly, but distinctive content in the first 12s
will bleed. XTTS OOM-kill loop: loading XTTS's 23G needs ~40G+ transient
headroom on the GB10 — terminate f5 + unload the ollama writer first, or
the load dies silently (NVRM Out of memory in dmesg, nothing in the app
log; "listening" prints but "model ready" never follows).

**#811 (2026-08-18, commit 574ad36) — the drowning-tails trap**: F5 fed
>~300 chars in ONE /synthesize call garbles the clip's TAIL (underwater
mush) — duration alignment vs the ≤12s reference slides on long inputs.
The upstream splitters (VOICE_MAX_CHARS 800, sentence_chunks 300) never
protected the F5 road; measured bad calls were 548–688 chars whole.
`_f5_synthesize` now sentence-chunks past 300 (cap 280) and `_wav_stitch`s
the 24kHz WAVs with a 120ms breath. Proof line: "f5 stitched N sentence
pieces (#811)". With XTTS idle-offloaded (#797) MOST clone renders ride
F5, so this affects the whole cast. Secondary underwater source if ears
still complain: the echo/room FX rack (fx_rate 0.15, depth fx_min/fx_max
20–60) rings ~1s of decaying repeats after the last word on ~15% of lines.

A second cloning engine runs beside XTTS: **`~/reachy-gateway/f5_tts_server.py` on
port 8772**, same contract as `voice_clone_server.py` (`POST {text,
reference_audio, language, opts}` → 16-bit mono WAV; errors-as-HTTP-200;
`X-Synth-Ms`). Venv at `~/f5tts/.venv` (uv, cu130 index), launcher `~/f5tts/f5_up`:

    setsid --fork bash -c "exec ~/f5tts/f5_up >> ~/f5tts/logs/f5_tts.log 2>&1"

Not wired into spark-agent — `voice_engine_for()` / `synthesize()` is the seam if
it ever should be.

**The trap that makes or breaks it:** F5 hard-clips the reference to **≤12 s** and
extrapolates output duration from the reference's seconds-per-character ratio. A
mismatched `ref_text` gives a proportional duration error (250-char text on a 12 s
clip rendered 2.85 s instead of 11.38 s). So the reference must be pre-clipped and
the transcript must match it exactly. `~/f5tts/refcache/f5_ref_prep.py` does this
for all voices and caches `sha1(ref) → (clip, text)`.

Two things that bite:
- **`data/voices/*/transcript.json` is UNUSABLE as `ref_text`** — its timestamps are
  on the *source media* timeline (160–780 s) while `reference.wav` is a 22–30 s
  montage built by `_reference_pieces`. Transcribe the clip itself instead.
- Pick the **densest 12 s window, not the first** — several references open on
  applause or silence, which leaves a few words and wrecks the ratio.
- **HF hub hangs on this box** (Xet): `WhisperModel()` blocks forever, and the
  1.35 GB checkpoint moved 28 KB in 15 min. `HF_HUB_OFFLINE=1` and
  `HF_HUB_DISABLE_XET=1` fix both and are baked into the scripts.

fp16 is stable for F5 on sm_121 (~530 renders, no device-side assert) — unlike
XTTS, whose fp16 GPT sampling poisons the CUDA context. Use `nfe_step=16`: it
costs only −0.004 identity for 1.7× the speed.

For what it scores, and why the pooled number misleads, see
[voice-fidelity-engine](voice-fidelity-engine.md). IndexTTS2 is also viable here (needs no transcript, has
emotion vectors, truncates refs to 15 s, and `duration_factor` only exists in
IndexTTS-2.5).
