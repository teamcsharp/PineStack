---
name: pause-gags-the-page
description: "The cure that lives in the tab: a stale pause/busy flag no server restart can reach, and the clocks that lie about it"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-12T05:45:04.593Z
---

2026-09-11/12. Two full days of "the DJs aren't playing" came down to
flags that live **inside the browser tab**, which no restart of
spark-agent can reach:

- `pineAirPaused` (panel) was only ever cleared at the BOTTOM of
  `djResync`, behind four early returns about where the RECORD plays
  (external output, a pinned track, a missing player, a clock with no
  track). Any one of them and the booth stayed gagged for the life of the
  page while the feed kept handing it clips — **received, never played,
  no errors**. Fixed #1211: the pause is read off the clock first.
  `/radio` never had this (`stationPaused = !!c.paused`, ungated), which
  is why it played through the same outage.
- `djVoiceBusy` / `voiceBusy` could stick true when the feed epoch moved
  under an in-flight clip (#1207), and `keepWhole` clips retried at the
  head forever.

**Diagnostic rules learned:**
- `heard_seconds_ago` (any listener reporting audible volume) is the only
  honest clock. `_SPOKE_AT` is the booth's, not the room's (#822, #1179,
  #1202).
- `aired: published` in the air log means HANDED TO THE PAGE, not heard.
  Measured 64 published / 1 aired in an hour while it looked healthy.
- A paused station is NOT a wedge — `page_wedge_state` said "stuck,
  nothing heard for 21644s" during a deliberate 6-hour pause. `paused.json`
  and `data/pause_log.jsonl` carry the why and the history.
- A headless panel probe shows `currentTime 0` for reasons of its own (no
  user gesture); don't read that as the user's fault. `/radio` needs its
  `#tune` clicked.

**Cures, in order of cost:** lift the pause → un-gag the page locally →
flush the feed epoch → release the exclusive → reload the page →
restart the process. See [every-fix-becomes-a-tool](every-fix-becomes-a-tool.md).

Pages now follow the box's code (#1209 build stamp) and honour an
asked-for reload (#1213 `reload_at`), so this should never again need a
human to be told "reload the tab" — but a page that predates those cannot
hear either signal, and needs one last manual reload.

**#1214 — the fault with no error anywhere (2026-09-12).** DJ audio silent
on the tablet while music played. Everything green: on, unpaused,
publishing, polling, queue filling, volume 1, no error on any element.
Found only by attaching to the tablet's WebView over adb:
`adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>` then CDP.

    fetch /api/dj        338 KB /   518 ms   652 KB/s
    fetch /media/<clip>  285 KB / 12958 ms    22 KB/s
    same clip in <audio>: readyState 0 after 15s, no error
    data: URI and /music in <audio>: load in 44/85 ms

**The event loop was frozen 13.6% of the time** (`/api/pulse`: 26 stalls,
81.7s, worst 7.8s; `read_binned`, `_load_vectors`, `prepared_seconds`).
A `FileResponse` streams 64 kB chunks with an await between each, so it
waits in every freeze; `/api/dj` is one body write. Cure: read small clips
in ONE threaded read and answer as a single body (22 → 2,637 KB/s).

**Diagnostic order for "no DJ audio" from now on:** `/api/broadcast/speed`
(times a clip + reads the stalls) BEFORE pulling any lever — flush,
release, reload and restart would all have run and failed here.
