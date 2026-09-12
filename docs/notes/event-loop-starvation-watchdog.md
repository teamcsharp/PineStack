---
name: event-loop-starvation-watchdog
description: Unpause silence root cause — sync stock accounting starves the event loop; host spark-agent-watchdog then docker-restarts the container; py-spy method
metadata: 
  node_type: memory
  type: project
  originSessionId: 836dcc4a-b3ed-493a-af16-86e278430ce5
  modified: 2026-08-26T07:59:40.129Z
---

Diagnosed 2026-08-26 (the "why is the broadcast slow to return after
re-enable + unpause" question).

**The mechanism, measured live:**
1. `dialogue_row_ready()` and everything above it (`pantry_ready_for`,
   `prepared_seconds`, `hour_needs`/`hour_owes`/`slot_needs`,
   `prepared_by_kind`) run SYNCHRONOUSLY on the event loop, per row over
   the whole cupboard (149 shelf rows incl. 87 callers + larder +
   track_talk). Per row: `_larder_current` → settings stat under lock,
   tint check, and for callers `call_entry_contract` →
   `call_fingerprint()` = 2 regex passes + sha256 over the full script,
   RECOMPUTED every sweep (it verifies stored vs recomputed). Per clip
   key: `_pantry_key_ready` → `Path.exists()` against a 4,501-file
   voice_media dir. Callers of these sweeps: `pantry_keeper`, `dj_state`
   (EVERY panel/app poll via `dialogue_flow_state`→`hour_needs`),
   `/api/radio/pause` (app polls it to paint the ⏸ button),
   `surplus_depth`, `ad_clock`. Also caught `_chunk_save` (ad WAV write)
   on the loop. Same regression class as #826's sting scan.
2. Result: /healthz takes 0.3–3.6s at QUIET moments, multi-second to
   30s+ during the post-unpause storm (/api/pinebox/status timed out at
   30s). The #1141-era "cupboard is allowed to be full" makes the walks
   maximal precisely after a pause (pause banks stock → resume grinds).
3. **`spark-agent-watchdog`** (host systemd timer, every 1min,
   `/usr/local/bin/spark-agent-watchdog`, journal tag
   spark-agent-watchdog): 3 probes × 8s timeout, then
   `docker restart spark-agent` (cooldown 600s, budget 3/hour). It was
   built for exactly this starvation, and it fires ~3 min after every
   unpause: measured 23:04:17 CST unpause → probes fail from 23:04:47 →
   restart 23:07:32 → SIGTERM ignored (starved loop) → SIGKILL →
   ~3–4 min boot (healthz stays deaf through startup) → catch-up storm
   → deaf again → SECOND restart at 23:20:55. The "slow broadcast
   return" IS this restart cycle plus starved clock polls.

**Why:** any per-poll walk of the full stock on the loop breaks the
station's own life-support; the watchdog converts starvation into
restarts, and restarts into minutes of silence.

**FIXED 2026-08-26, commit a7c447a (#1142)** — four memos:
`call_fingerprint` digest memoized on script text (`_CALL_FP_MEMO`);
`_pantry_key_ready` reads a 5s `_voice_media_names()` scandir snapshot;
`_larder_profile_signature` 3s memo; `pantry_ready_for` 5s +
`prepared_by_kind` 3s memos. `pantry_spoken_for` left UNCACHED on
purpose (horizon cleanup deletes off it — do not cache it later).
Measured after: healthz 1–50ms, pinebox/status 38ms, boot-to-healthy
11s. If starvation returns, `prep_board` (dialogue_row_ready per row,
un-memoed) and `_chunk_save` (sync WAV write in ad_produce's chain) are
the next known sync-on-loop spots.

**Follow-ups (2026-08-26):** #1143 (7f7c986) ported the #998
buffering-guard (`readyState < 3` → no hard seek) into the panel's
`djResync` and the shell's `syncDesktopRadio` — only the tune page had
it; symptom is the record jumping back and repeating. #1144 (fa16a29)
made pause immediate: panel `pineAirPause(on)` silences record + booth
voice elements (holds mid-word, resumes on lift; `djVoiceNext` gates on
`pineAirPaused`), `pineFmOff()` is the app-FM-switch's local half, and
renderer `pineFramesRun()` pushes both into the webviews on the click
instead of waiting for the 1.5s clock poll. djResync's no-show branch
now pauses a record it was following (FM off used to let it play out).
#1145 (b933e4f): "still playing occasionally
during pause" = TWO roads drive the panel's one music player — the
clock road was pause-honest (#1138) but `radio_state()` said
playing=bool(now) with NO paused key, and djRender's synthetic clock
call into djResync dropped the flag → each state poll (~4s) restarted
the frozen record until the next clock poll paused it. Fixed server +
panel; djResync now treats a MISSING paused flag as not-an-unpause.
LESSON: any new djResync caller must carry `paused`; any new state
surface must gate `playing` on radio_paused().
The panel voice road is TWO alternating audio elements + queue
(`djVoiceEls`, `djVoiceQueue`, `djVoiceBusy`) — deliberate presenter
overlap is `djOverlapLead` (#185/#1008, default 0). Client changes need
an app RELAUNCH (renderer.js mirrors at launch) or F5 (panel HTML).

**How to apply:**
- Fix direction: memoize per-row readiness (dirty-flag on write), trust
  the stored call fingerprint, run the sweep off-loop on a clock and
  serve cached numbers (the #826 pattern), replace per-key stats with
  one scandir set.
- Diagnosis method that worked: `docker exec spark-agent pip install
  py-spy`, then `docker exec spark-agent py-spy dump --pid 56` (uvicorn
  pid; pid 1 is the sh wrapper). Sample repeatedly; the MainThread stack
  names the blocker.
- Restart forensics: `journalctl -t spark-agent-watchdog`; docker
  `hasBeenManuallyStopped=true` + kill s15→s9 = the watchdog, NOT the
  lifeboat (its log /var/log/pinebox-lifeboat.log never shows
  spark-agent) and NOT the socket-proxy (its log had zero spark-agent
  restarts). `pinebox-mounts.sh` also restarts spark-agent but only
  after remounting a share.
- The container start command md5-guards requirements.txt, so pip is
  usually skipped on boot; the 3–4 min boot cost is the app's own
  startup work.
See [pinebox-broadcast-debugging](pinebox-broadcast-debugging.md), [hour-contract-two-truths](hour-contract-two-truths.md),
[parallel-session-commitment-ledger](parallel-session-commitment-ledger.md).
