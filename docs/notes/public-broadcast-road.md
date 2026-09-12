---
name: public-broadcast-road
description: "#1149: the funnel/tune listener path — music ?br= road, retime anchor, listener unpause, public door allowlist; the stall hunter and what it caught"
metadata: 
  node_type: memory
  type: project
  originSessionId: 21948932-a31d-4dd3-9e25-119ba26127d8
  modified: 2026-08-27T17:57:41.742Z
---

**The remote listening path (mapped 2026-08-27, #1149):** share links mint
on the Tailscale **Funnel** base `https://lilspark.tail1fec29.ts.net`
(funnel → `127.0.0.1:8097`, the **public listener door** #687 — a second
uvicorn IN THE SAME PROCESS wrapping the app in `PublicListenerGate`:
deny-by-default allowlist, Authorization stripped, `x-pinebox-public: 1`).
Same process = same event loop = **every loop stall hits every remote
listener**. Music library rides a CIFS mount off exbox
(`//exbox.local/quickswap/Music/iTunes`) — cold opens measured 4.4s TTFB
even on LAN; funnel adds ~2s TTFB per fresh request.

**#1149 invariants (do not undo):**
- `/music/{id}?br=` serves a cached stereo 44.1k mp3 from LOCAL disk
  (`data/music_lo/`, `_music_low_encode_soon`, shares `_LOW_GATE`/
  `_LOW_JOBS`); #1147 sticky-miss (`_LOW_MISSED["music:{id}|{rate}"]`,
  sliding 900s) so a range continuation never flips codec mid-src; each
  br-serve warms `_RADIO["coming"]` + queue/requests head at that rate.
  The tune page stamps `clipUrl()` on the RECORD src too (was voice-only).
- tune-page `retime()`: target from **window-min anchor** (8-sample
  window; anchor = landing_time − reported_position; transit only ever
  inflates it, so min ≈ truth) — never from per-response stamps. Hard
  seek: ≥8s apart AND (`audio.buffered` covers target, or drift >20s);
  else rate-nudge. `clockPoll` single-flight + newest-answer-wins.
- **Listener unpause**: `POST /api/radio/unpause` (`require_listen_auth`,
  in `_PUBLIC_POST`) — wake-ONLY; pause via the door stays 404. Tune page
  shows the paused state + green "▶ Unpause the broadcast" button
  (`paintPaused`/`wake()`); `sync()` reads `state.paused` (it used to
  fight clockPoll: 3s play vs 1.5s pause = the "stochastic" car bursts).
- `voicePrefetch` 20s AbortController; voiceNext hands the element the
  network URL after 8s instead of waiting on a blob (streams partial).
- /tape and /sfx range branches use `_range_stream` (both read the whole
  window into RAM before — a phone opens `bytes=0-` = 100MB in RAM).
- Public door uvicorn: `timeout_keep_alive=75`.

**Stall hunter** (`~/stall_hunt.sh` on lilspark → `/tmp/stall_hunt.log`,
kill by `kill $(pgrep -f stall_hunt)` — NOT `pkill -f` from an ssh whose
own cmdline matches): polls healthz per 2s, py-spy dumps container pid 56
on >2.5s. 2026-08-27 it caught healthz 3–8s EVERY ~60s; named blockers →
fixed in #1149: `_chunk_save` (4000-row json dump on the loop; write now
on a thread under `_CHUNK_WRITE_LOCK`) and the per-poll walk under
`dialogue_flow_state` (→ `_dialogue_flow_state_fresh` + 3s `_FLOW_MEMO`).
Addendum (4dee819): `system_stats()` shells to nvidia-smi — both async
call sites now `asyncio.to_thread` it. Remaining known sync-on-loop tail
(caught at boot only, unfixed): `chunk_rank`'s regex walk under
`crystal_stanzas`, `speakbox_all`'s glob under the minds endpoint, and
`prep_board` (per #1142).

Verified live through the funnel: mint link → tune page carries the wake
button → POST unpause with bare listen token flips paused→playing (clock
confirms) → re-paused with operator key. br=96 miss serves original with
`no-store` + kicks encode + warms up-next; warmed track then serves
`audio/mpeg` at ~1/3 the bytes. See [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md),
[floor-and-paced-air](floor-and-paced-air.md), [pinevoice-deploy-paths](pinevoice-deploy-paths.md).
