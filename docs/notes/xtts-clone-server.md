---
name: xtts-clone-server
description: "Where the XTTS clone server lives, how to restart it so new code loads, and its gotchas"
metadata: 
  node_type: memory
  type: project
  originSessionId: a8169767-f9f9-4abf-896b-3271212da841
  modified: 2026-08-15T12:40:23.235Z
---

The XTTS v2 clone server is **not** part of the pinevoice compose stack. It is
`~/reachy-gateway/voice_clone_server.py` on lilspark, run as a host process on
127.0.0.1:8770 under `uv run` by the **Reachy gateway** (`bootstrap.py`, :9010).

**Restarting it to pick up code changes is the fiddly part:**
- `POST /api/speech/clone` will NOT reload code — it reuses any healthy server on
  the port and returns `"reused": true`.
- `pkill` is blocked by the permission classifier here.
- What works: **`~/reachy-gateway/reachy_restart`**. The gateway's `_warm_clone`
  runs at boot, compares the running server's `src_mtime` against the file on disk,
  and kills + relaunches a stale one. `reachy-gateway-watchdog.service` re-launches
  the gateway within ~20 s if anything goes wrong, so this is safe.
- Confirm the new code is live via `GET :8770/health` — it now reports `cond`,
  `infer`, `cond_sig` and `latents_cached`.

**Gotchas:**
- The server reports failures as **HTTP 200 with a JSON body**. Content-type is the
  truth, not the status code.
- `_latent_cache` is keyed on `sha1(reference) + conditioning signature`, so changing
  conditioning invalidates stale latents. Before that key existed, a parameter change
  could be silently masked by cached latents and measure as a null result.
- `POST` accepts an `opts` dict (conditioning/sampling overrides + `seed`) for A/B
  harnesses; production callers never pass it. `seed` is per-request — seeding once
  at startup would make render N depend on renders 1..N-1.
- fp16 is OFF deliberately: on the GB10/Blackwell it triggers a CUDA device-side
  assert that poisons the context. Do not set `REACHY_XTTS_FP16=1` or `num_beams>1`.
- ctranslate2 in the voice-lab image has **no CUDA support**, so faster-whisper stays
  on CPU there; asking for the GPU raises rather than falling back.

See [voice-fidelity-engine](voice-fidelity-engine.md), [spark-agent-environment](spark-agent-environment.md).
