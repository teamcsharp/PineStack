# Pine Cam on the PineTab: why it stutters, and the road to a smooth stream

Measured 2026-09-27 06:00-07:20 CDT. Read-only: nothing was changed by this work. Note that a second, parallel session restarted the station container at 07:06:30 CDT and reinstalled the kiosk APK at 07:09:31 while the connection benchmark ran; the numbers below marked "run 2" are from the clean re-run.

## 1. Verdict

1. **The tablet never plays the video.** The camera reaches the station as a steady 30 fps H.264 848x480 HLS stream (~1.67 Mbps, keyframe every 0.5 s). The tablet's Pine Cam box (`pine-cam.js`) sets `<img src=/api/pinelink/frame.jpg?c=...>` every 250 ms. Four stills a second is the design ceiling of today's road.
2. **Even the four stills do not arrive cleanly.** Over 20 s on the live tablet: 79 stills requested, 65 loaded, 14 abandoned (the next `src` write cancels a load still in flight). Gaps between displayed frames: median 260 ms, p90 435 ms, max 2,652 ms. Fetch time median 47 ms, p90 213 ms; 6% of polls at the station take longer than the 250 ms period because the station's event loop stalls 1.6-5.1 s, 2-4 times per 10 minutes.
3. **The page renders at 6 fps with its main thread 97% busy, camera box open or closed.** So no change inside the page can make the picture smooth; the WebView's ceiling on this tablet is ~12 fps for anything. The kiosk's native SurfaceView player (PineVideoWall / ExoPlayer) is the only road to a full-rate picture.
4. **Frames are genuinely lost only on the camera's own radio hop** (2.4 GHz channel 1, 9 neighbouring APs, rx MCS 4): 0.0%, 0.7% and 3.4% missing per 5-minute clip, in ~20 s bursts with holes up to 4.3 s. Nothing downstream can restore those; every road will show a held frame during a burst.
5. **The tablet-station connection is healthy at the radio layer but churns at the HTTP layer.** Tablet: -51 dBm, ch 36, 0 disconnects/roams in 26 h. The station's :8096 uvicorn keeps connections alive for only 5 s (the :8097 public door already uses 75 s), so every poller re-opens sockets continuously (5-6 TIME-WAIT per 30 s from the tablet alone; CLOSE_WAIT sockets held in the kiosk's OkHttp pool). The DGX itself is on Wi-Fi (wlP9s9, -61 dBm with a 9 dB chain imbalance, power save ON, 4.7% retries) while its RTL8127 10 GbE port sits unplugged; the DGX hop has worse jitter than the tablet hop.
6. **The tablet is starved:** kiosk ~200% + WebView renderer ~155% CPU, load average 28 on 8 cores, 72-633 MB free RAM with 560 MB swap in use, an always-on `screenrecord` + hardware encoder (~35% of a core) for the screen ring.

## 2. Recommended changes, ranked

### The stream (road C from the pipeline report)
- **Host, `tools/pinelink.py`:** add a 4th `-c copy` output to the same ffmpeg: `-map 0:v -c copy -f mpegts -muxdelay 0 -muxpreload 0 -mpegts_flags +resend_headers udp://127.0.0.1:18081?pkt_size=1316` (UDP to localhost cannot back-pressure the recorder); a ~120-line `TsDoor` thread keeps a 1.5 s ring of TS packets and serves `GET /live.ts` (chunked `video/mp2t`) on 10.89.1.246:8098 and the tailnet address, each client started at the last keyframe; `say()` adds `ts` and `ts_clients` to state.json (already passed through by `/api/pinelink/state`). Also `-u`/`PYTHONUNBUFFERED=1` on the unit so `~/pinelink.log` is actually written (it has not been since 09-23).
- **Kiosk:** new `video/PineCamWall.kt` lifted from `PineVideoWall.kt` (surface, observeTouch, setBox/full/window/veil/menu/hold/state, load control, watchdog) playing the TS with `ProgressiveMediaSource` + `DefaultHttpDataSource` + `DefaultLoadControl(1000, 5000, 250, 500)`, with a lag trim (speed 1.25 while buffered > 1.5 s; reconnect when > 6 s, buffering > 3 s or no movement > 2.5 s). Bridge verb `pineCam` beside `videoWall` in `PineDesktopBridge.kt`; install/teardown beside `installVideoWall()` in `MainActivity.kt`. Zero new gradle artifacts (the TS extractor is in the cached media3 1.3.1 core).
- **`pine-cam.js` (kiosk asset and desktop copy kept identical):** `open()`/`close()` send `pineCam('on', rect)` / `pineCam('off')` with the `#pineCamImg` rect x devicePixelRatio (1.25), resend after drag/resize, `menu`/`free` around the prefs/ladder sheets; the folded circle and the sidebar thumbnail stay on JPEG; the desktop and tune page are untouched.
- Expected: 30 fps, ~0.5-1.0 s glass-to-glass, immune to station loop stalls and to the WebView's 6 fps, +0 CPU on the host, 1.67 Mbps per viewer.
- Fallback A: ExoPlayer HLS on the existing segments at `-hls_time 1` served from the same :8098 door (needs `media3-exoplayer-hls` from Maven; 3-4 s latency). LL-HLS is not available in ffmpeg 6.1.1. Option D (mediamtx replacing ffmpeg as the camera's sole client) is the right road the day the desktop needs real video too, but it is untested against this LIVE555 camera.

### The connection
- **S1 (one line):** `--timeout-keep-alive 75` on the `exec uvicorn app:app --host 0.0.0.0 --port 8096` line in `~/pinevoice-stack/compose.yaml` (line 286), then recreate the container. Removes the socket churn on every road.
- **S2:** plug the DGX's enP7s7 (RTL8127 10 GbE, 4c:bb:47:7f:ca:c0) into the gateway with a DHCP reservation so 10.89.1.246 follows it; the kiosk and desk hard-code that address. Removes one wireless hop (RTT ~10-11 ms avg / 5-8 ms jitter -> ~5.5 / 3) and halves channel-36 airtime.
- **S3 (if it stays wireless):** `nmcli con modify TacoNet 802-11-wireless.powersave 2` and re-activate; check the chain-0 antenna (-70 vs -61 dBm) and whether the 3 dBm tx power `iw` reports is real.
- **Kiosk:** K1 hold a `WIFI_MODE_FULL_LOW_LATENCY` lock while foreground (none has ever been taken); K2 `LoopDoor.carry()` (`net/LoopDoor.kt:217`) connect with a 3 s timeout + keepalive + a bounded pool (today a dead station hangs each WebView request ~2 min); K3 a `ConnectivityManager` default-network callback that re-probes and reloads on the OS event instead of the 4 s timer + up to 18 s of road probing; K5 let deaf-watch count dead `<audio>` elements as strikes (cure time 90-135 s -> ~40 s). Interim before S1: `ConnectionPool(4, 4, SECONDS)` in `StationClient.kt` so OkHttp evicts idle sockets before the station does.
- **Station loop:** the stalls named by `/api/pulse` (`iterencode`, `sfx_note_play` at app.py:80677, `_speakbox_scan`) are the tail on every route; the native road sidesteps them for video but they still cost the JPEG road and every panel poll.
- **Tablet:** `logcat -G 8M` (the ring covers 2.5 min today); stop the always-on `screenrecord` when the screen ring is not needed.

The two agents' full reports follow, verbatim.

---

# Pine Cam pipeline: where the frames go, and the road to a native 30 fps stream on the PineTab

Measured 2026-09-27 05:59-06:35 host time on the DGX (lilspark), read-only. Nothing restarted, no session opened to the camera, ~275 requests to the station in total.

## 0. Summary

- The camera delivers a steady 30.0 fps, GOP 0.5 s (a keyframe every 15 frames), 848x480 H.264 High at ~1.67 Mbps. Inside the newest 6 HLS segments: 360 packets in 11.80 s, max frame gap 43 ms, 24 keyframes at exactly 0.5 s. This contradicts the earlier "44 packets / ~20 fps / irregular keyframes" sample: that sample fell inside a loss burst.
- Frames ARE lost, but on the air, before the host: whole-clip counts are 0.7%, 3.4% and 0.0% missing over three 5-minute clips; the 3.4% clip lost ~852 frames in two ~20 s bursts (max hole 4.27 s). Kernel UDP counters are clean (InErrors 0, RcvbufErrors 0 over 5,327 datagrams/30 s). Radio: -56 dBm, 2.4 GHz channel 1, rx MCS 4 (39 Mbit/s), 9 neighbouring networks, `rx drop misc` climbing 0.58/s. No downstream design can put those frames back.
- ffmpeg, the files and the station route are not where the lag comes from at the median: frame.jpg is rewritten at 4.05/s with a regular 234/266 ms alternation, 0 torn reads in 396; the station answers frame.jpg in 1.2 ms median (sequential) and HLS segments in 2-5 ms.
- The stutter the tablet sees on today's road is (1) the 4 fps JPEG cadence sampled by an unsynchronised 250 ms timer (21 of 113 consecutive polls returned the same frame = duplicates, plus skips), and (2) the station's event loop stalling: at the tablet's exact cadence, p90 = 165 ms, p99 = 600 ms, 7 of 114 polls (6%) took longer than the 250 ms period, and /api/pulse logged 4 stalls in 10 min with a worst of 5.1 s (`_speakbox_scan`). Every stall is a frozen picture on the tablet.
- Recommendation: a fourth `-c copy` output from the SAME ffmpeg (MPEG-TS over localhost UDP), fanned out by a tiny threaded HTTP server inside `tools/pinelink.py` on port 8098 (outside the station's event loop), played on the tablet by ExoPlayer's core `ProgressiveMediaSource` on a media-overlay SurfaceView that mirrors PineVideoWall's box/touch/menu contract. 30 fps, ~0.5-1.0 s glass-to-glass, zero new gradle artifacts (the TS extractor is already in the cached media3 core), zero new host binaries, the recorder and the JPEG road untouched. Fallback: ExoPlayer HLS on the existing segments (needs the `media3-exoplayer-hls` artifact from Maven; 3-4 s at 1 s segments, 6-8 s as-is).

## 1. Measurements per stage (commands and numbers)

### 1.1 Camera -> ffmpeg: source continuity

Script: `pipe-seg-analysis2.sh` (ffprobe `-show_entries packet=pts_time,dts_time,size,flags -of csv=p=0` on the newest 6 `live/seg*.ts` by mtime and on the newest complete clip). Note: ffprobe's csv column order is pts_time,dts_time,size,flags.

Newest 6 segments (seg01507-seg01512, 06:00:36-06:00:46):

| segment | pkts | span s | eff fps | gaps>45ms | gaps>100ms | max gap | keyframes | key spacing | video bytes | kbps |
|---|---|---|---|---|---|---|---|---|---|---|
| seg01507 | 60 | 1.967 | 29.99 | 0 | 0 | 36 ms | 4 | 0.5/0.5/0.5 | 410,224 | 1668 |
| seg01508 | 60 | 1.967 | 30.00 | 0 | 0 | 43 ms | 4 | 0.5/0.5/0.5 | 410,857 | 1671 |
| seg01509 | 60 | 1.967 | 29.99 | 0 | 0 | 34 ms | 4 | 0.5/0.5/0.5 | 409,982 | 1667 |
| seg01510 | 60 | 1.968 | 29.98 | 0 | 0 | 36 ms | 4 | 0.5/0.5/0.5 | 409,687 | 1665 |
| seg01511 | 60 | 1.967 | 30.00 | 0 | 0 | 35 ms | 4 | 0.5/0.5/0.5 | 409,830 | 1667 |
| seg01512 | 60 | 1.967 | 30.00 | 0 | 0 | 35 ms | 4 | 0.5/0.5/0.5 | 410,146 | 1668 |
| total | 360 | 11.80 | 29.99 | 0 | 0 | | 24 | | 2,460,726 | |

Keyframe ~27 KB, P-frame ~5.3 KB. Segment files are ~427 KB (TS overhead ~4%). `mtime - last_pts` is constant to 1 ms across all six (1790509687.095) = the segment is closed the instant the next keyframe arrives; `index.m3u8` is rewritten 0.3 ms later. The pipeline adds no buffering beyond the segment length.

Whole clips (`pipe-clip-history.sh`: `-count_packets` vs `format=duration`, expected = 30 x duration):

| clip | size | duration | packets | fps | missing |
|---|---|---|---|---|---|
| 2026-09-27_05-48-09.mp4 | 61.2 MB | 300.1 s | 8940 | 29.79 | 0.7% |
| 2026-09-27_05-53-08.mp4 | 59.6 MB | 300.4 s | 8711 | 28.99 | 3.4% |
| 2026-09-27_05-58-08.mp4 | 61.6 MB | 300.0 s | 9000 | 30.00 | 0.0% |

Full packet map of the 3.4% clip: 218 gaps > 45 ms, 89 > 100 ms, max 4.273 s, est. 852 frames missing; frames per 10 s bucket: `208, 238, 298, 299, 301, 300, 300, 299, 290, 166, 300, 297, 302, 300 ... 300` - two bursts, 05:53:08-05:53:28 and 05:54:28-05:54:48, the rest perfect. Keyframe-spacing histogram over 581 keyframes: 516 at 0.5 s; every deviation (0.1-4.6 s) lies inside a burst (a lost keyframe). Last 60 s of that clip: 1800 packets / 59.967 s = 30.00 fps, max gap 38 ms.

Decision: the camera sends a steady 30 fps; frames go missing on the radio path in bursts (RTP over UDP, no retransmission), before ffmpeg ever sees them.

### 1.2 Radio and kernel

```
nstat -az UdpInDatagrams UdpInErrors UdpRcvbufErrors   t0: 2162317 / 0 / 0     t0+30s: 2167644 / 0 / 0   (5,327 datagrams in 30 s = 178/s = the 1.67 Mbps stream)
/proc/net/snmp Udp: InErrors 0, RcvbufErrors 0, MemErrors 0
iw dev wlx984827b6b478 link/station dump/info:
  SSID H88_5c8e8bddfab1, channel 1 (2412 MHz) 20 MHz, txpower 30 dBm
  signal -56 dBm (avg -55), beacon signal avg -42, beacon loss 0, tx retries 0, tx failed 15
  rx bitrate 39.0 MBit/s MCS 4; tx bitrate 72.2 MBit/s MCS 7 short GI
  rx drop misc: 591 (t0) -> 605 (+30 s) -> 1046 (+788 s)  = 0.58/s
  power save: off; connected 768 s at 06:00:49 (associated 05:48:02)
/proc/net/wireless: retry 15, misc 591; ip -s link: 0 errors, 0 dropped
doctor (state.json): 9 nearby networks; strongest TacoNet 97, AppleNet 90, TacoNet 84, ATTbVbPtJA 84 x2
net.core.rmem_max/default = 212992 (defaults; pinelink.py records that a 4 MB buffer measured WORSE)
```

Nothing in the kernel drops; the driver's misc drops and the loss bursts are on the air (2.4 GHz channel 1 shared with at least 9 APs, rx negotiated down to MCS 4).

### 1.3 ffmpeg process and outputs

```
ffmpeg version 6.1.1-3ubuntu5+esm7 (gcc 13, Ubuntu 24.04), --enable-libx264 --enable-libsrt --enable-gnutls, no nvenc
pid 1770593: %CPU 7.3 (top: 7.0), RSS 174 MB, 76 threads, started 05:48:10
host: 20 cores, load 10.6-14.2, GPU util 68%, 121 GB RAM (46 GB available), data dir on local NVMe ext4 (/), container bind-mounts ~/pinevoice-stack/spark-agent -> /app
```

Exact running command (from `ps`): `-rtsp_transport udp -timeout 20000000 -use_wallclock_as_timestamps 1 -i rtsp://192.168.1.254:554/live` -> (1) HLS `-hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list+omit_endlist` (2) `-f segment -segment_time 300 -reset_timestamps 1 -strftime 1` mp4 (3) `-vf fps=4 -q:v 6 -f image2 -update 1 frame.jpg`.

frame.jpg cadence (`stat` every 50 ms for 20 s): 81 distinct mtimes = 4.05/s; gaps min/median/mean/max = 233/250/250/268 ms, strictly alternating 234/266 ms (fps=4 on a 33.3 ms frame grid: 7 then 8 source frames). Sizes 23-37 KB (not 10.6 KB - scene dependent or a different moment). Torn-read test: 396 reads at 20 ms spacing, 0 empty, 0 without SOI/EOI. The in-place rewrite (`-update 1`, same inode) is fast enough that the route's EOI guard never fired in this window. During a loss burst the fps filter cannot emit (no input), so mtimes bunch up - that is the "irregular 0.24/0.44/0.73 s" seen earlier.

HLS muxer capabilities (`ffmpeg -h muxer=hls`): NO `lhls` option (LL-HLS removed upstream); has `temp_file`, `split_by_time`, `independent_segments`, `program_date_time`, `hls_segment_type fmp4`, `hls_init_time`. Other muxers present: mpegts, segment, fifo, tee, rtsp, flv, dash. Protocols: http (`-listen` 0-2), tcp, udp, unix, srt, rtp.

MPEG-TS offline probe (3 s of an existing clip, `-c copy -muxdelay 0 -muxpreload 0 -f mpegts -mpegts_flags +resend_headers -pat_period 0.1`): 3,464 packets, PAT/PMT 30 times (every <=194 packets = 0.1 s), 6 packets carry the random-access indicator = 6 keyframes by ffprobe. So a late joiner gets tables within 0.1 s and can be started on the last keyframe by a one-byte check (`p[3]&0x20 && p[5]&0x40`).

### 1.4 Supervisor history

- `systemctl status pinelink`: active since 2026-09-23 16:58:49 (restart counter 1); main PID 6591 `python3 tools/pinelink.py`, child ffmpeg 1770593.
- `journalctl -u pinelink`: "No entries" (not readable without sudo). The unit appends stdout to `/home/ehm_eckx/pinelink.log`, but that file's mtime is Sep 23 16:58: python's stdout is block-buffered when it is a file, so today's "PineLink live" line has not been flushed (fix: `python3 -u` or `PYTHONUNBUFFERED=1` in the unit). The file holds 75 live / 75 dropped lines from older runs in the pre-#1250b format.
- `state.json` at 05:59: `state=live`, `stream.lives=[]`, `class=""`, `transport=udp`, `frame_age=0.2` - no drop in this run (05:48:10 -> now). The doctor ran at 05:48:06 and the radio associated at 05:48:02.
- Segment sequence: 1455-1460 at 05:59:02, 1651-1656 at 06:05:36; `append_list` continues numbering across restarts, so the run started near seg01128 (the stale seg01127 dated 09-22 14:38:59 is the previous run's last segment; seg01117 dated 09-21 22:06:48 the one before). 37 stale segments from 09-21/09-22 (~15 MB) sit in `live/` because `delete_segments` only deletes what the current playlist referenced.
- Clips: only today's exist (05-48-09, 05-53-08, 05-58-08, 06-03-08 being written); 48 h retention means the camera was off between 09-22 14:39 and 09-27 05:48.

### 1.5 Station routes (from the DGX, 127.0.0.1:8096)

`pipe-route-timing.sh` and `pipe-jitter.sh`:

| test | n | size | ms min / median / p90 / p99 / max |
|---|---|---|---|
| frame.jpg sequential | 60 | 23.2-25.9 KB | ttfb 0.4 / 1.2 / 4.7 / - / 111.6 |
| frame.jpg 2 parallel loops at 250 ms (the two `<img>` pollers) | 80 | 23.2-29.5 KB | 0.7 / 4.1 / 90.9 / - / 165.8 |
| frame.jpg 1 poller, fixed 250 ms period, 30 s | 114 | | 1.0 / 2.3 / 165.0 / 600.2 / 681.9; >100 ms: 15; >250 ms: 7 (6%); same-size consecutive: 21/113 |
| index.m3u8 | 1 | 256 B | ttfb 1103.7 (one sample, during a stall) |
| seg01651-56.ts | 6 | ~427 KB | total 2.1 / 2.3 / 3.0 / 5.4 / 101.4 |

`/api/pulse` first read: 2 stalls / 10 min, worst 1.59 s (`iterencode` in a JSON response, `sfx_note_play` 1.56 s). Second read 25 min later: 4 stalls, worst 5.09 s, 10.4 s stalled in 10 min (`_speakbox_scan` 2x 7.0 s). Docker access logs: 0 lines in 10 min - uvicorn access logging is off, so pollers cannot be counted from logs.

Route cost read from `app.py` (host copy): `pinelink_frame_api` (line 135007) is `async def`; no token -> `require_read_auth` -> `LOCK_READS` false by default (line 2188) -> no check; then sync `PINELINK_FRAME.read_bytes()` (25 KB from local NVMe, sub-ms), EOI check, `_PINELINK_LAST` memo, `Response(bytes)` with `no-store`. No locks, no census (the census runs only in `pinelink_state()`, off-loop). `pinelink_live_api` (134981): regex name check, `path.is_file()`, `FileResponse` (chunked via anyio). The route itself costs ~1 ms; the p90/p99 is the loop being busy elsewhere.

Headers: frame.jpg `content-length` present, `cache-control: no-store`, `access-control-allow-origin: *`; m3u8 served with `accept-ranges`, etag, last-modified.

### 1.6 The tablet's road, as read from code (not measured here - other agents own the tablet)

- `pine-cam.js` (kiosk asset copy md5 0950...e6ab == desktop/renderer copy on the host; the host repo's `app/src/main/assets/pine-views/pine-cam.js` is a different, older file c869...024e - the tablet runs the local build): `FRAME_MS = 250`; `paintFrame()` (line 298) sets `img.src = base()+'/api/pinelink/frame.jpg?c='+Date.now()` from `setInterval` with no onload gating, so a slow answer is simply superseded; `paintPipFrame()` (472) does the same for the sidebar card whenever the link is live, so two pollers = 8 req/s; `look()` polls `/api/pinelink/state` every 5 s; `base()` returns '' on the tablet (the document's own origin = the loopback door).
- `net/PineNet.kt` intercepts only `/vendor/` and `/api/generations/image/`; frame.jpg is NOT intercepted or transcoded - it goes through the WebView's stack to `LoopDoor` (127.0.0.1:8096, a byte pump with one upstream socket per browser connection, 32 KB reads, keep-alive preserved) and on to 10.89.1.246:8096.
- Consequences: 4 distinct frames/s at best; a free-running 250 ms timer against a 234/266 ms writer produces duplicates and skips (measured 19% duplicates even with a precise scheduler on the DGX); WebView timers on this tablet are throttled/suspended under load (memory: "PineTab timers freeze"); each station stall > 250 ms is a dropped frame, > 1 s a visible freeze; the WebView cannot present above ~12 fps anyway.

### 1.7 Alternatives already on the host

`which mediamtx go2rtc rtsp-simple-server`: none. Ports 8554/1935/8888/8889 free; 8098 free; 8096/8097/8090 in use by the station stack. Containers: spark-agent (python:3.12-slim, host network), voice-lab, HA, wyoming-*, open-webui, searxng. No GPU encoder in this ffmpeg; the design below stays `-c copy`.

## 2. Where frames are lost or delayed (stage by stage)

| stage | what happens | measured | verdict |
|---|---|---|---|
| camera -> air -> spare radio | RTP/UDP, no retransmission; 2.4 GHz ch 1, 9 neighbours, rx MCS 4 | 0-3.4% frames missing per 5 min, in bursts of ~20 s, holes up to 4.27 s; `rx drop misc` 0.58/s | the only place frames are LOST; not fixable downstream; the only lever is placement/channel of the camera AP (out of scope) |
| kernel UDP | socket buffers | InErrors 0, RcvbufErrors 0 | clean |
| ffmpeg demux/copy | wallclock pts, reorder queue | 7% CPU; 60 pkts per 2 s segment; 33.3 ms grid | clean; adds only its reorder/jitter window (unchanged by any option) |
| HLS files | segment closes on the next keyframe, playlist 0.3 ms later | 2.000 s segments, 12 s window | a standard HLS client sits 3 x target + up to 1 segment = 6-8 s behind live |
| frame.jpg | fps=4 -> JPEG in place | 4.05/s, regular, no torn reads | 250 ms quantisation = up to 250 ms age at the file |
| station route | async handler, sync 25 KB read | median 1.2-2.3 ms; p90 91-165 ms with 1-2 pollers; p99 600 ms; 6% of polls > 250 ms; loop stalls 1.6-5.1 s | the DELAY stage: not the route, the loop it runs on |
| LoopDoor + WebView fetch | loopback relay, WebView network stack | not measured here | one more hop per frame; WebView-side (parent measuring) |
| `<img>` repaint | 250 ms timer, no gating | 19% duplicates at best | 3-4 distinct fps, aliasing, timer throttling, 12 fps WebView ceiling |

The picture on today's road is therefore: at most 4 fps, ~0.3-0.6 s old, with a frame skipped on 6% of ticks and a freeze for every station stall - on top of the source's own 20 s loss bursts, which every road will show as a frozen frame.

## 3. Options for a native, low-latency stream on the tablet

Common ground for all: the tablet cannot reach 192.168.1.x; every road serves from the DGX. The native player is ExoPlayer (media3 1.3.1) on a `SurfaceView` with `setZOrderMediaOverlay(true)` exactly like `PineVideoWall.kt:93`; H.264 848x480 is hardware-decoded on the MT6768. The 30 s TCP cut is irrelevant to A/C (ffmpeg stays the camera's udp client). The gradle cache on this PC has only media3 common/container/database/datasource/decoder/exoplayer/extractor 1.3.1: `media3-exoplayer-hls`, `media3-exoplayer-rtsp`, `media3-datasource-okhttp` are NOT in `gradle/libs.versions.toml` and NOT cached, so A and D need Maven access at build time; C needs nothing new (`TsExtractor`, `FragmentedMp4Extractor`, `ProgressiveMediaSource`, `DefaultHttpDataSource` verified inside the cached AARs).

### A. ExoPlayer HLS on the existing segments

- fps 30. Latency: `HlsMediaSource` default live offset = 3 x target duration, plus up to one segment of listing delay: 6.3-8.3 s at `hls_time 2`; 3.3-4.3 s at `hls_time 1`; `hls_time 0.5` (= GOP) with `LiveConfiguration.targetOffsetMs 1500` gives ~1.8-2.3 s but then any station stall > ~1 s rebuffers (measured 2-4 stalls/10 min, 1.6-5.1 s). Through app.py, "seamless" needs >= 5-6 s of offset; below that the files must be served by something that does not share the loop.
- Robustness: same files as today; segments are complete when listed; add `temp_file` so no half-written segment is ever served; `independent_segments` for clean joins.
- Cost: none on the host; 2-4 req/s per viewer on the station.
- Touch points: `tools/pinelink.py ffmpeg_cmd()` (`-hls_time 1 -hls_list_size 6 -hls_flags delete_segments+append_list+omit_endlist+temp_file+independent_segments`; one link restart); `gradle/libs.versions.toml` + `app/build.gradle.kts:143` add `media3-exoplayer-hls`; kiosk wall class uses `HlsMediaSource.Factory(DefaultHttpDataSource.Factory())` with `MediaItem.Builder().setUri(...).setLiveConfiguration(LiveConfiguration.Builder().setTargetOffsetMs(...).build())`.

### B. LL-HLS from ffmpeg

Not available: ffmpeg 6.1.1's hls muxer has no `lhls`/partial-segment support (verified in `-h muxer=hls`). LL-HLS only comes with D.

### C. Progressive MPEG-TS over HTTP, fanned out beside ffmpeg (recommended)

- Source: a fourth output on the SAME ffmpeg: `-map 0:v -c copy -f mpegts -muxdelay 0 -muxpreload 0 -mpegts_flags +resend_headers udp://127.0.0.1:18081?pkt_size=1316`. UDP to localhost never back-pressures ffmpeg: a missing or slow reader cannot stall the recorder (an http `-listen 1` output or a FIFO would).
- Fan-out: a thread in `tools/pinelink.py` (root, host network, its own process, 20 cores idle): a UDP listener on 127.0.0.1:18081 keeps a ring of the last ~1.5 s of 188-byte packets, remembering the index of the last packet with the random-access indicator; a `ThreadingHTTPServer` bound to 10.89.1.246:8098 and 100.74.95.59:8098 (not 0.0.0.0) serves `GET /live.ts` as `video/mp2t`, chunked, `Cache-Control: no-store`, starting each client at the last keyframe (<= 0.5 s back, PAT/PMT repeat every 0.1 s anyway); per-client queue bounded to ~3 s, a client that falls further behind is dropped. `say()` adds `"ts": "http://10.89.1.246:8098/live.ts", "ts_clients": n` to state.json, which `/api/pinelink/state` already passes through unchanged. ~120 lines; ~1% of a core.
- Player: `ProgressiveMediaSource.Factory(DefaultHttpDataSource.Factory().setConnectTimeoutMs(4000).setReadTimeoutMs(8000))` + `MediaItem.fromUri(ts)`; `DefaultLoadControl.setBufferDurationsMs(1000, 5000, 250, 500)` (the wall already uses 250 ms play thresholds). ExoPlayer plays unbounded TS with unknown length as unseekable; latency = 250 ms start buffer + <= 0.5 s keyframe back-off + ~100 ms decode/present = ~0.5-1.0 s glass-to-glass after the source's own reorder window (unchanged). A lag trim in the watchdog holds it there: if `bufferedPosition - currentPosition` > 1500 ms for 2 ticks, `setPlaybackSpeed(1.25f)` until <= 600 ms (invisible on a camera feed); > 6000 ms, or BUFFERING > 3 s, or position not moving > 2.5 s -> `stop(); setMediaItem(); prepare()` (a reconnect joins at the live edge in ~0.4 s). Wallclock pts mean loss bursts do not shift the timeline, so lag does not accumulate from loss.
- Robustness: ffmpeg restart -> the flow pauses, PAT/PMT and a fresh timeline resume, the watchdog reconnects; camera loss bursts show as a frozen frame (same on every road, and the 0.5 s GOP recovers fast); LoopDoor and the WebView are not on the path at all.
- Cost: +0 ffmpeg CPU (copy), 1.67 Mbps per viewer on the tablet's Wi-Fi.
- Not exposed to the public door: :8098 is LAN/tailnet only, unauthenticated like frame.jpg is today (LOCK_READS false); if reads ever lock, `DefaultHttpDataSource.Factory().setDefaultRequestProperties(mapOf("Authorization" to "Bearer ..."))` and a token check in the fan-out.

### D. RTSP relay (mediamtx) replacing ffmpeg as the camera's sole client

- fps 30. Latency: RTSP/TCP into `media3-exoplayer-rtsp` ~0.3-0.7 s; its LL-HLS ~1.5-3 s; WebRTC/WHEP < 0.5 s in Chromium (the desktop could finally have real video without a library).
- Cost: one static Go binary + config on the host; ~2-5% of a core.
- Robustness: mediamtx reconnects to the camera itself and serves any number of readers; but the camera's ONE client slot moves to an untested stack against a LIVE555 "Nvt RTSP" server that sends no usable PTS/RTCP (ffmpeg needed `-use_wallclock_as_timestamps`); mediamtx uses RTP timestamps, which should be fine but cannot be verified without taking the slot.
- Touch points: `pinelink.py supervise()` launches mediamtx (`source: rtsp://192.168.1.254:554/live`, `rtspTransport: udp`) instead of ffmpeg and a small ffmpeg for frame.jpg from `rtsp://127.0.0.1:8554/cam`; recording either by mediamtx (`record: yes`, fMP4 5-min segments; `/api/pinelink/cut` reads them with ffmpeg unchanged) or by the frame.jpg ffmpeg (adds a hop); kiosk `media3-exoplayer-rtsp` (Maven) with `RtspMediaSource.Factory().setForceUseRtpTcp(true)`.
- Verdict: the most capable road and the right one the day the desktop needs live video too; the most new moving parts for the tablet alone.

### Comparison

| | A HLS | C progressive TS | D mediamtx |
|---|---|---|---|
| fps on the glass | 30 | 30 | 30 |
| glass-to-glass | 6-8 s as-is; 3-4 s at 1 s segments; ~2 s only off-loop | 0.5-1.0 s | 0.3-0.7 s RTSP / 1.5-3 s LL-HLS |
| immune to station loop stalls | only at >= 5 s offset | yes (own process) | yes |
| camera client changes | no | no | YES (untested) |
| new gradle artifacts | 1 (Maven) | 0 | 1 (Maven) |
| new host binaries | 0 | 0 | 1 |
| host code | ffmpeg args | ffmpeg args + ~120 lines pinelink.py | supervisor rewrite + config |
| kiosk code | wall class + bridge + JS | same | same |
| recorder risk | none | none (UDP cannot back-pressure) | recording path changes |

## 4. Recommendation and exact change points

Primary: C. Fallback: A at `hls_time 1` served by the same fan-out server (also serve `data/pinelink/live/` as static files on :8098 so the HLS road is off-loop too) - it is one `HlsMediaSource` line away once the artifact is fetched.

Host (`~/pinevoice-stack/spark-agent/tools/pinelink.py`, root unit `pinelink.service`, ExecStart unchanged):
1. `ffmpeg_cmd()` (the list ending at the frame.jpg output): add the mpegts/udp output above. One link restart (~10 s off the air) when deployed.
2. New `TsDoor` thread started at the top of `supervise()`: UDP ring + `ThreadingHTTPServer` on 10.89.1.246:8098 / 100.74.95.59:8098, `/live.ts`, keyframe-aligned start, bounded queues; `say()` gains `ts` and `ts_clients`.
3. While there: `-u` on the ExecStart or `PYTHONUNBUFFERED=1` so `~/pinelink.log` is actually written (today it is not).

Station (`app.py`): nothing required. Do NOT proxy the stream through app.py (`StreamingResponse` on the loop inherits the 1.6-5.1 s stalls). `pinelink_state()` already forwards new state.json keys.

Kiosk (`C:\_tools\pinebox-android\PineBoxKiosk`):
4. `app/src/main/java/com/pinebox/kiosk/video/PineCamWall.kt` (new, ~350 lines): from `PineVideoWall.kt` take the surface (line 93), `observeTouch` (drag/resize/tap/long-press, ~lines 175-300), `applyBox/setBox/showFullScreen/showWindowed/veil/menu/hold/state()` (330-560), `build()` with the load control (700-780), the 1 s watchdog skeleton (`watch()`); replace the playlist pump with `play(url)` (ProgressiveMediaSource) and add the lag trim + reconnect rules above; `state()` reports `lag_ms`, `reconnects`, `speed`.
5. `bridge/PineDesktopBridge.kt`: add `"pineCam"` to `ASYNC_METHODS` (beside `"videoWall"`, ~line 116); a `"pineCam" -> {...}` case copied from `"videoWall"` (line 1322) with verbs `on`(url from `/api/pinelink/state.ts`)/`off`/`hide`/`show`/`menu`/`free`/`full`/`window`/`state`, box in argument 1 as device pixels; field `@Volatile var pineCam: PineCamWall?` beside `videoWall` (line 1554).
6. `MainActivity.kt`: install beside `installVideoWall()` (1065-1121, called at 1156) with `onTap`/`onLongPress`/`onBoxChanged` evaluating `PineCam.tapPicture/holdPicture/wallBoxChanged`; `dispatchTouchEvent` line 450 also asks `pineCam?.observeTouch(ev)`; tear down with the wall at 727-735.
7. `app/src/main/assets/pine-views/pine-cam.js` and its identical twin `desktop/renderer/pine-cam.js` (keep them byte-identical; the host repo's assets copy is stale): in `open()` (306) and `close()` (315), when `root.pineDesktop && typeof root.pineDesktop.pineCam === 'function'` and the last `look()` state carried `ts`: send `pineCam('on', rect)` where rect = `#pineCamImg.getBoundingClientRect()` x `devicePixelRatio` (1.25 on this tablet - the `nativeWallRect()` pattern at sfx-tv.js:5900), stop `frameTimer` (or keep it at 1 Hz as a poster/fallback), `pineCam('off')` on close; after `drag()`/`remember()`/`place()` and on resize send the new rect; `setRound(true)` -> `pineCam('off')` and the JPEG road (a rounded SurfaceView is unverified on SDK 34); `pineCam('menu'|'free')` around the prefs/ladder sheets (sfx-tv.js:591 pattern) because no HTML can paint over the surface; export `PineCam.tapPicture` (toggle the bar/fold), `PineCam.wallBoxChanged(x,y,w,h)` (move the DOM box to the native rect and `remember()`), `PineCam.releaseHold`. The bar (PINE CAM, REC, fold, x) stays outside the surface rect, so it remains a WebView control; the sidebar card keeps the JPEG thumbnail.
8. Gradle: nothing for C. For the A fallback: `gradle/libs.versions.toml` `androidx-media3-exoplayer-hls = { module = "androidx.media3:media3-exoplayer-hls", version.ref = "media3" }`, `app/build.gradle.kts:143` `implementation(libs.androidx.media3.exoplayer.hls)`; the build machine must reach Maven once. Deploy with `deploy.sh` (platform signing).

Desktop/tune page: untouched (JPEG road stays; the desktop's Electron could later take D's WebRTC).

## 5. Risks, and what could not be measured

- Not measured (out of scope / forbidden): the tablet's own timings (WebView, LoopDoor, timer throttling - other agents); the camera's RTP sequence gaps (would need the single client slot); mediamtx against this camera; ExoPlayer's behaviour on an unbounded TS on this exact device (no adb) - the lag-trim/reconnect rules are the mitigation if it drifts; whether a SurfaceView can be clipped round on SDK 34 (keep the folded circle on JPEG).
- The air loss (0-3.4% per 5 min, 20 s bursts, holes to 4.3 s) will show on every road as a held frame; C recovers within 0.5 s of the next keyframe. Watch `rx drop misc` (0.58/s) and `tx failed`; the lever is camera/adapter placement and the crowded channel 1, not software.
- Station stalls (1.6-5.1 s, 2-4 per 10 min) remain for everything served by app.py, including the JPEG road; C avoids them by design. If :8098 is not acceptable, the same fan-out could live in a separate non-root unit reading the UDP feed - but not in app.py.
- :8098 is unauthenticated on the LAN/tailnet exactly as frame.jpg is today; bind to the two addresses, never 0.0.0.0, and never to the public door.
- Deploying the ffmpeg args costs one link restart (~10 s).
- Contradictions with the brief's earlier numbers: segments are steady 30 fps with 0.5 s keyframes (the earlier 44-packet segment was a loss burst); frame.jpg is 23-37 KB here, not 10.6 KB; frame.jpg rewrites are regular outside loss bursts; `journalctl` is not readable and `pinelink.log` is not being written, so `state.json` (last 8 lives only; empty = no drop this run) is the only live history.
- `hls_flags append_list` leaves 37 stale 09-21/09-22 segments (~15 MB) in `live/`; cosmetic.

Scripts used (scratchpad): pipe-seg-analysis2.sh, pipe-clip-history.sh, pipe-route-timing.sh, pipe-jitter.sh, pipe-ts-probe.sh, pipe-ts-probe2.sh.


---

# PineTab <-> Pine Box connection diagnosis (read-only), 2026-09-27 07:00-07:16 CDT

Two events by a parallel operator landed inside the measurement window and are NOT mine:
the station container restarted at 12:06:30Z (07:06:30 CDT, `docker inspect .State.StartedAt`)
and the kiosk APK was reinstalled at 07:09:31 (`dumpsys package lastUpdateTime`; new process
20036 at 07:10:16). Run 1 of the in-page benchmark hit the restart; every number below marked
"run 2" is from the clean re-run on the new kiosk process.

## (a) Every measured number

### Tablet radio (adb `dumpsys wifi`, mWifiInfo block)
| item | value |
|---|---|
| BSS | TacoNet 80:69:1a:1b:fe:0e, 5180 MHz (ch 36), WPA2-PSK, Wi-Fi standard 5 (802.11ac), no MLO |
| RSSI | -51 dBm (scan list says -45 for the same BSS), score 60, signal level 4 |
| link speed | tx 325 Mbps, rx 433 Mbps; max supported 433/433 = 1x1 spatial stream, 80 MHz |
| predicted tput | mLastTxKbps 12000 / mLastRxKbps 60000 |
| driver retry stats | WifiScoreReport tx_retry 0.00, tx_bad 0.00 (GSI does not report them) |
| power | `settings get global wifi_sleep_policy` = 2 (never); mPowerSaveDisableRequests 0; Wi-Fi locks acquired: 0 full-high-perf, 0 full-low-latency (ever); mSuspendOptimizationsEnabled true; "Wifi power metrics" all 0 (not reported) |
| DHCP | 10.89.1.154/24 gw 10.89.1.1, lease 86400 s, server "ecosystem.home.cisco.com" (AT&T/Cisco gateway), MAC randomised |
| scan (`cmd wifi list-scan-results`) | 14 BSSes; on 5180 MHz only TacoNet; nothing on 5200/5220/5240 (the 80 MHz block 36-48 is uncontended); other 5 GHz APs on 153/157/161 (-53..-93); TacoNet 2.4 GHz BSS ...fe:0d at -48 |
| history (105 `rec[]` rows, 09-26 04:07:57 -> 09-27 06:16:49, 26 h) | DISCONNECT 0, NETWORK_DISCONNECTION 0, ROAM 0, IP_REACHABILITY 0, assoc/auth reject 0; 23 NETWORK_CONNECTION_EVENT + 47 SUPPLICANT_STATE_CHANGE = the hourly GTK rekey at :16:49 (normal); 2 DHCP renewals (09-26 16:08:10, 09-27 04:08:10); one connection since boot, took 481 ms (`isFirstConnectionAfterBoot=true`) |

### DGX radio (ssh, `iw dev wlP9s9 link/station dump/info`, mt7925e, fw 20251210)
| item | value |
|---|---|
| AP / channel | same BSS 80:69:1a:1b:fe:0e, ch 36, 80 MHz (center 5210), DTIM 2, beacon 100 |
| signal | -61 dBm, chains [-70, -61] (9 dB imbalance); avg ack signal -66 |
| bitrate | tx 864.8 Mbit/s HE-MCS8 NSS2; rx 648-720 Mbit/s HE-MCS6-7 NSS2 |
| retries | cumulative 35,342,972 / 579,002,802 tx pkts = 6.1 %; 30-s window 4,698 / 99,358 = 4.7 % (3,311 tx pkt/s, 1,784 rx pkt/s); tx failed 17; rx drop misc 2,735; beacon loss 0; connected 306,094 s (3.5 d) |
| power save | `iw dev wlP9s9 get power_save` = **on** (`nmcli ... 802-11-wireless.powersave` = 0/default -> driver default) |
| tx power | `iw dev wlP9s9 info` reports **3.00 dBm**; `iw reg get` US allows 23 dBm on ch 36; cannot confirm from the AP side (rate control holds MCS 8, so likely a driver reporting quirk) |
| wired NIC | enP7s7 = Realtek RTL8127 10GbE (driver r8127), **link down / no carrier**, supports 1G/2.5G/5G/10G, NM state "unavailable" |
| ARP | gc_thresh1/2/3 = 1024/4096/8192; `ip -4 neigh | wc -l` = 574; tablet entry REACHABLE |
| host | loadavg 10.4 on 20 cores; `ss -ltn :8096` Recv-Q 0 / backlog 2048 (2/2048 right after the restart) |

### Path pings (0.25 s interval)
| hop | cmd | loss | min / avg / max / mdev ms |
|---|---|---|---|
| DGX -> tablet | `ping -c 60 -i 0.25 10.89.1.154` | 0/60 | 2.68 / 11.13 / 45.15 / 7.67 |
| tablet -> DGX | `ping -c 40 -i 0.25 10.89.1.246` (adb) | 0/40 | 3.66 / 10.05 / 25.36 / 5.11 |
| DGX -> gateway | `ping -c 30 -i 0.25 10.89.1.1` | 0/30 | 1.06 / 8.51 / 38.50 / 8.76 |
| tablet -> gateway | `ping -c 30 -i 0.25 10.89.1.1` (adb) | 0/30 | 2.26 / 5.46 / 17.41 / 2.90 |

The DGX's wireless hop (avg 8.5, jitter 8.8, max 38.5) is worse than the tablet's (avg 5.5, jitter 2.9, max 17.4).

### Server baseline (curl on the DGX, 10 each, `%{time_connect} %{time_starttransfer} %{time_total}`)
| route | size | connect | TTFB | total |
|---|---|---|---|---|
| /api/pinelink/frame.jpg | 23,895 B (24-27 KB, not ~10 KB) | 0.08-0.16 ms | 0.93-1.85 ms | 0.97-1.89 ms |
| /api/pinelink/live/seg01554.ts | 427,512 B | 0.09-0.15 ms | 0.77-3.5 ms (one 26 ms) | 1.8-7.3 ms (one 30 ms) |

Frame route cost (app.py:135007-135060): no auth (`LOCK_READS` default false, app.py:2188/2200), one synchronous `PINELINK_FRAME.read_bytes()` (~25 KB, local disk under /app/data) inside an `async def` = on the event loop, plus a dict update; no lock. Live route = `FileResponse` (threaded send). Both add `Access-Control-Allow-Origin: *`, neither adds `Timing-Allow-Origin`.

### In-page fetch timings over CDP (sequential, `cache:'no-store'`, all on reused connections: newConn = 0 in every run)
Run 2 (clean, 07:14:35 CDT). wall = JS-visible fetch->arrayBuffer; duration = resource-timing startTime->responseEnd; queue = startTime->requestStart; TTFB = requestStart->responseStart; body = responseStart->responseEnd. Direct (10.89.1.246) entries are cross-origin and opaque (no Timing-Allow-Origin), so only wall/duration exist for them.

| run | ok | wall med / p90 / max | duration med / p90 / max | queue med | TTFB med / p90 / max | body med | Mbit/s (wall) |
|---|---|---|---|---|---|---|---|
| loop A frame x20 | 20/20 | 162.7 / 598 / 1237 | 31.7 / 106.9 / 1160.8 | 9.8 | 12.3 / 72.5 / 1135 | 5.2 | 0.68 |
| direct frame x20 | 20/20 | 114.2 / 342.6 / 387.9 | 36.1 / 178.7 / 246.9 | - | - | - | 1.29 |
| loop seg (427 KB) x6 | 6/6 | 215.8 / 296.5 / 421 | 77.5 / 124.5 / 212 | 13.5 | 10.9 / 47.9 / 54.4 | 55.5 (= ~62 Mbit/s on the wire) | 13.9 |
| direct seg x6 | 2/6 | 92.5 / 212 / 267 | 37.4 / 132.5 / 132.6 | - | - | - | 8.7 (2 ok) |
| loop B frame x10 | 10/10 | 140.4 / 388 / 1880 | 22.6 / 78.8 / 1833 | 9.4 | 9.7 / 58.9 / 1810 | 3.3 | 0.62 |

Run 1 (07:06:51, contaminated by the 07:06:30 station restart): loop frame x40 wall med 128.5 / p90 836 / max 8378 (first ten: 243, 308, 387, 177, 724, 3755, 2048, 2347, 8378, 645 ms), TTFB med 22.6 / max 1261; direct frame x40 wall med 65.9 / p90 199 / max 429; all 16 segment fetches failed (404 "no such piece" after the restart; a cross-origin 404 has no ACAO header so it surfaces as "TypeError: Failed to fetch").
`navigator.connection`: type wifi, effectiveType 4g, downlink 10 (Chromium cap), rtt 0 (<12.5 ms bucket), saveData false.

### The panel's own traffic (resource timing, 137 s window, run 2 process)
375 requests = **2.74 req/s** (337 fetch, 15 css, 10 video, 7 audio, 6 img); 10 new TCP connections in 137 s (loopback connect 2-8.8 ms each); duration med 112 ms / p90 763 ms / max 85.9 s (a media stream). Top routes: /api/dj/voice/ack 57, /api/radio/clock 48, /api/te/feed 26, /api/dj/pipeline 26, /api/dj 19, /api/history 19, /api/dj/voice 18, /api/broadcast/health 18, /api/orchestrator/rejections 16, /api/perf 15, /api/orchestrator/asks 15. `PineDeafWatch.state()`: bridge true (297 ms), web true, strikes 0.

### Sockets and keep-alive
| where | sample (3 x 30 s) |
|---|---|
| station `ss -tan '( sport = :8096 and dst 10.89.1.154 )'` | ESTAB 9 / 7 / 8, TIME-WAIT 6 / 5 / 6, FIN-WAIT-2 2 / 2 / 1 (station is the active closer) |
| tablet loopback :8096 (`/proc/net/tcp*`, both ends of each loopback socket appear) | ESTAB 10 / 16 / 14, TIME_WAIT 6 / 8 / 15, CLOSE_WAIT 1-2, 1 LISTEN |
| tablet -> 10.89.1.246:8096 | ESTAB 8 / 9 / 11, TIME_WAIT 2 / 2 / 1, CLOSE_WAIT 2 / 4 / 1 |
| LoopDoor threads (old pid 430) | 15 `pine-loop-door` of 128 threads; 6 OkHttp Dispatcher + 3 TaskRunner |
| keep-alive probe on the host (one TCP connection, two GET /healthz) | 3 s apart -> 2 answers; **7 s apart -> 0** (connection already closed, RST) |
| uvicorn (docker exec) | 0.35.0; `Config('app:app')` defaults: **timeout_keep_alive = 5 s**, backlog 2048, limit_concurrency None, h11_max_incomplete_event_size None |
| container Cmd (`docker inspect`) | `exec uvicorn app:app --host 0.0.0.0 --port 8096 --timeout-graceful-shutdown 10` - no `--timeout-keep-alive`. The only `timeout_keep_alive=75` in app.py (line 150478) is the :8097 public door, whose comment (#1149) already names the 5 s default as "paid a fresh handshake each" poll |
| `/api/radio/listeners` | tablet listed as addr 10.89.1.154 (the relay runs on the tablet, so the station sees the real address), seen 1.3 s, since 3070 s (= kiosk process age), owns_air true |
| `/api/pulse` (07:00) | 2 stalls / 10 min, worst 1.59 s: `iterencode` (JSON encode of a big response on the loop) and `sfx_note_play` (app.py:80677) 2x 3.07 s; loads_frozen 4 |

### Tablet load (adb `top -b -n 1`, `/proc/loadavg`, `dumpsys thermalservice`)
loadavg **27.96 / 27.56 / 27.31**; CPU 800 % = 381 % user + 145 % sys + 271 % idle (~66 % busy); com.pinebox.kiosk **193 %**, WebView sandboxed renderer **154 %**, surfaceflinger 61 %, mediatek c2 codec 26 %, audio HAL 19 %, audioserver 13 %, `screenrecord --size 1340x800 --bit-rate 11792000` (shell uid) 9.6 %; RAM 3,955 MB total, 633 MB free, swap 562 MB used; cpufreq 1.8/1.8/2.0 GHz; CPU/GPU 63.5 C (second sensor set 42.8), skin 47 C, thermal status 0. logcat main ring 256 KiB = 13,014 lines spanning ~2.5 min (GPUAUX 5,543 + gralloc4 2,845 + thermal_src 712 lines).

## (b) Faults and limits, ranked (evidence attached)

1. **Station :8096 keep-alive is 5 s, so every road re-opens connections continuously.** Evidence: keep-alive probe 3 s -> 2 answers, 7 s -> 0; uvicorn Config default 5; container Cmd has no `--timeout-keep-alive`; station shows 5-6 TIME-WAIT + 1-2 FIN-WAIT-2 toward the tablet at every sample (about 6 closes/min from one client); tablet shows 1-4 CLOSE_WAIT on upstream sockets (OkHttp pool of 4 / 5 min holding sockets the station already closed: the next use hits a dead socket and reconnects, or a POST such as /api/dj/voice/ack lands on it and fails, since Chromium/OkHttp do not retry non-idempotent requests on a stale socket). The :8097 door was fixed for exactly this (#1149) and the main door was not. Cost per re-open: SYN over two wireless hops (~10 ms), a LoopDoor `Socket()` connect plus two pool threads, and a station accept.
2. **The tablet's CPU is the largest latency term the page sees.** Run 2: wall med 162.7 / 114.2 / 140.4 ms versus network duration 31.7 / 36.1 / 22.6 ms - about 100-130 ms per request is spent between Chromium's network layer and the page's JS (kiosk 193 % + renderer 154 %, loadavg 28). This also delays LoopDoor's pump threads and OkHttp's dispatcher.
3. **Station event-loop stalls make the tail.** TTFB med 12 ms but max 1135 ms (1 of 20) and 1810 ms (1 of 10); `/api/pulse` names `iterencode` 1.59 s and `sfx_note_play` 1.56 s. Baseline TTFB on the DGX itself is 1-2 ms, so the tail is server-side, not radio.
4. **The DGX's wireless hop is the worse of the two, and it is the removable one.** -61 dBm with chain 0 at -70; power save ON; gateway RTT avg 8.5 / mdev 8.8 / max 38.5 ms vs tablet 5.5 / 2.9 / 17.4; 4.7-6.1 % tx retries; every byte between tablet and station crosses the same ch-36 radio twice. RTL8127 10GbE port sits unplugged.
5. **No network-change handling in the kiosk.** grep of MainActivity.kt / PineApp.kt: no `ConnectivityManager.NetworkCallback` (Readiness.kt only reads `activeNetwork` once). After a Wi-Fi blip with the page already loaded nothing in the app reacts; recovery is Chromium's own NetworkChangeNotifier + the panel's 2.7 req/s polls + OkHttp `retryOnConnectionFailure(true)` (StationClient.kt `http`: connect 3 s / read 20 s / call 30 s). Only a MAIN-FRAME load failure is handled (MainActivity.kt:1512-1535 `onReceivedError` -> banner -> `load()` after RETRY_MS = 4000; 1436-1446 the about:blank case); each `load()` runs `reachable()` = up to 3 roads x (4 s connect, 4 s read, 6 s call, no retries; StationClient.kt `probe`) = worst 18 s before `loadUrl`. LoopDoor keeps aiming at the old base until `LoopDoor.aim()` is called from `load()` (MainActivity.kt:1339-1346).
6. **Wedged-WebView self-heal exists but is slow and narrow.** `deaf-watch.js` (APK asset pine-sampler/deaf-watch.js, injected via ViewAssets.kt:113): every 30 s compare bridge GET /api/dj/sections vs `fetch` (25 s timeout); 3 consecutive strikes with the bridge answering in <15 s -> `pineDesktop.revive({now:true})` -> Revive.kt: 5-min rest, max 3 per 30 min, `setAlarmClock` +2.5 s then `exit(0)`; measured relaunch ~4.7 s. Time-to-cure: 20 s warm-up + 3 x 30 s (+ up to 25 s probe) = 90-135 s. It tests only "fetch dead while bridge alive"; it does not look at `<audio>` error/networkState, and a Wi-Fi outage resets strikes ("not deafness"). A rail "repair button" path (RailController.kt:880-915) does the same by hand.
7. **LoopDoor.kt internals** (net/LoopDoor.kt): `Executors.newCachedThreadPool` (unbounded; 2 threads per connection + 1 accept; 15 threads seen for ~7 connections); `ServerSocket(8096, backlog 64, 127.0.0.1)`; `tcpNoDelay = true` both sides; **no connect timeout on `Socket(aim.first, aim.second)`** (line 217: kernel SYN retries, ~2 min hang per WebView request while the station or Wi-Fi is down); no SO_TIMEOUT, no SO_KEEPALIVE, no send/receive buffer sizing; pump buffer 32 KiB with `flush()` after every read; on EOF from either side both sockets are closed (no half-close relay - fine for HTTP/1.1); `JOIN_MS` 2000 on the request pump; after 12 consecutive accept failures (250 ms apart) it closes and must be re-opened by the next `load()`. Measured steady-state cost: none (loop 31.7/22.6 ms vs direct 36.1 ms median duration; loop p90 107/79 vs direct 179).
8. **No Wi-Fi lock on the tablet**: locks acquired 0/0, so the STA stays in 802.11 power save with DTIM 2 (up to ~200 ms wake latency on the downlink after an idle gap). Not the dominant term today (constant traffic keeps it awake), but the 25-45 ms ping maxima are consistent with it.
9. **History is unreadable.** logcat main ring 256 KiB fills in ~2.5 min (64 % GPUAUX/gralloc4 spam), so reconnect/revive/door events older than that are gone; why kiosk pid 430 started at 06:08:35 is unknowable now. WifiLinkLayerStats/power metrics are zero on this GSI.
10. **HLS live window is a trap for cross-origin fetches**: a segment that has rolled off returns 404 without ACAO, which a cross-origin `fetch` reports as "Failed to fetch" (run 1: 16/16, run 2: 4/6). Same-origin via LoopDoor gets an honest 404. Not a link fault; do not read those errors as network errors.
11. Assumptions that did not hold: LoopDoor does not add measurable latency; ARP pressure is absent (574 / 8192); frame.jpg is 24-27 KB not ~10 KB; the `timeout_keep_alive=75` found in app.py is the :8097 door only.

## (c) Recommendations (what to change, where, expected effect)

Station host (DGX / container):
- **S1 - `--timeout-keep-alive 75` on the :8096 uvicorn** (the `exec uvicorn ...` line in the spark-agent container command / compose file on the host; same value the :8097 door uses at app.py:150478). Expect: station TIME-WAIT toward the tablet ~6/min -> ~0; the WebView's 6 sockets and OkHttp's 4 stay warm across the 3-4 s polls; no stale-socket reconnects or lost POSTs after an idle gap; first-request-after-gap latency drops by one connection round trip (~10-20 ms over two hops). Interim kiosk-side mitigation if S1 waits: StationClient.kt `.connectionPool(okhttp3.ConnectionPool(4, 4, TimeUnit.SECONDS))` so OkHttp evicts idle sockets before the station does (removes the CLOSE_WAIT ones).
- **S2 - plug enP7s7 (RTL8127, 10GbE, 4c:bb:47:7f:ca:c0) into the gateway.** Expect: tablet<->station RTT ~10-11 ms avg / 5-8 mdev -> ~5.5 / 3 (the tablet-gateway figures); channel-36 airtime halved; the DGX's 4.7 % retries, power-save latency and 9 dB chain imbalance leave the path. Needs the station address to follow the wired NIC (DHCP reservation for that MAC, or keep 10.89.1.246 on it) - the kiosk's `cfg.base` and the desk both hard-code 10.89.1.246; docker host networking is unaffected.
- **S3 - if it stays on Wi-Fi: `nmcli con modify TacoNet 802-11-wireless.powersave 2` then re-activate the connection** (currently `0/default` -> driver ON). Expect: gateway RTT avg 8.5 -> ~2-3 ms, mdev 8.8 -> ~2, max 38 ms tail gone.
- **S4 - antenna/placement**: chain 0 is 9 dB below chain 1 (-70 vs -61); re-seat the pigtail or move the box; confirm on the AP's client page what RSSI it sees for the DGX and whether tx power really is 3 dBm (`iw dev wlP9s9 info`) - if so `iw dev wlP9s9 set txpower fixed 2000` (or a regdb fix for mt7925e) is the lever.
- **S5 - loop stalls**: `/api/pulse` names `iterencode` (JSON encode of a large response on the loop) and `sfx_note_play` (app.py:80677, via `dj_voice_ack_api` app.py:123624). Move the encode off the loop (orjson / `run_in_threadpool`) and the sfx-note disk work into `to_thread`. Expect: TTFB p90 72 -> ~15 ms, max 1.8 s -> <100 ms; the 8 s and 3.7 s fetches seen right after a restart shrink with it.
- S6 - add `Timing-Allow-Origin: *` beside `Access-Control-Allow-Origin: *` on /api/pinelink routes so direct-road timings are measurable from the page next time.

AP side (AT&T/Cisco gateway, admin UI only):
- A1 - leave ch 36 / 80 MHz: no other BSS on 5180-5240 from either radio; the block is clean.
- A2 - DTIM 2 -> 1 if the UI allows: halves power-save wake latency for both STAs.
- A3 - the 2.4 GHz TacoNet BSS (...fe:0d, -48 at the tablet) is a roam target if 5 GHz ever dips; if the gateway offers per-band SSIDs, give the tablet a 5 GHz-only SSID (no roam events in 26 h today, so low priority).
- A4 - a free LAN port for S2 is the single biggest change on this list.

Tablet side (settings, no code):
- T1 - `adb shell logcat -G 8M` (and/or `setprop log.tag.GPUAUX S`, `log.tag.gralloc4 S`) so the ring covers hours, not 2.5 min; otherwise no reconnect history can ever be read.
- T2 - stop the always-on `screenrecord` (shell uid, 9.6 % CPU + codec 26 %) when the desk's screen ring is not needed; the tablet is at ~66 % CPU with the kiosk alone at 193 %.
- T3 - the tablet's own radio needs nothing: -51 dBm, 0 disconnects/roams in 26 h, hourly rekey normal.

Kiosk code:
- **K1 - Wi-Fi low-latency lock** (MainActivity.onResume/onPause): `(getSystemService(WIFI_SERVICE) as WifiManager).createWifiLock(WifiManager.WIFI_MODE_FULL_LOW_LATENCY, "pinebox")` acquire while foreground. Evidence: 0 locks ever. Expect: STA power save off while the kiosk is on the glass; downlink ping max 25-45 -> ~10-15 ms; LoopDoor upstream connects faster.
- **K2 - LoopDoor.carry()** (net/LoopDoor.kt:217): `Socket().apply { connect(InetSocketAddress(aim.first, aim.second), 3000); keepAlive = true; tcpNoDelay = true }`; bound the pool (`ThreadPoolExecutor(0, 48, 30 s, SynchronousQueue)`) so a request burst on a starved CPU cannot fork without limit; optionally `receiveBufferSize = 256 KiB` for the 430 KB segments; keep a byte/last-activity counter per direction so `busy()` can report "open but nothing moving" (today it cannot tell wedged from quiet). Expect: while the station/Wi-Fi is down a WebView request fails in 3 s instead of hanging ~2 min, so `onReceivedError` and the 4 s retry fire promptly.
- **K3 - `ConnectivityManager.registerDefaultNetworkCallback`** in MainActivity (none exists): on `onAvailable`/`onLost`/`onCapabilitiesChanged` -> `Reach.forget()`, `app.client.reachable()`, `LoopDoor.aim(base)`; if `mainFrameFailed` or the banner is up -> `load()` now instead of waiting for RETRY_MS; if the page is up -> `evaluateJavascript("window.PineDeafWatch&&PineDeafWatch.look()")` and re-arm media elements. Expect: reconnect after a blip goes from "next 4 s timer + up to 18 s of road probing" to "on the OS event + one 1-2 s probe".
- K4 - StationClient `probe` client: for the LAN road on a callback-triggered re-probe use 1.5 s connect/read (keep 4 s for the tailnet roads) so a LAN blip re-settles in <2 s.
- K5 - deaf-watch.js: add the real symptom as a strike source - any `<audio>` with `networkState == NETWORK_NO_SOURCE`/`error` while the bridge's /api/dj says a line is airing; and let it read LoopDoor's byte counter (K2) through the bridge. Expect: cure time 90-135 s -> ~40 s, and catches the "media dead, fetch alive" variant.
- K6 - panel polling: 2.74 req/s with /api/radio/clock every ~3 s and /api/dj/voice/ack 57 in 137 s; fold the clock into the /api/dj poll and batch acks. With S1 this is 6 warm sockets doing 2.7 req/s, which is fine; without S1 it is what drives the churn.
- K7 - PineNet/StationClient already never route through LoopDoor (correct; keep it).

## (d) Not measured, and why
- AP-side view: the AT&T/Cisco gateway has no reachable admin API - per-client RSSI (the DGX's real signal at the AP), per-client retries, DTIM/beacon/band-steering config. So the 3 dBm tx-power reading on the DGX cannot be confirmed or refuted.
- Tablet driver-level PER/retries and radio sleep time: WifiLinkLayerStats and "Wifi power metrics" are all zero on this GSI; no `iw` on the tablet.
- Reconnect/revive history: logcat holds ~2.5 min; the 26 h `rec[]` log (zero disconnects) is the only history. Why kiosk pid 430 started at 06:08:35 is unknown (Revive prefs are app-private; log gone).
- DGX kernel Wi-Fi messages: `journalctl -k` unprivileged returns nothing (no sudo).
- Direct-road TTFB/connect breakdown: no Timing-Allow-Origin on the station, so cross-origin timing entries are opaque (wall and duration only).
- Sustained throughput: no iperf by rule; the only throughput figure is the segment body phase (~62 Mbit/s over 427 KB) and 13.9 Mbit/s JS-visible.
- Both benchmark runs shared the tablet with a parallel operator's station restart (12:06:30Z) and kiosk reinstall (07:09:31); run 2 is clean but the tablet was at 66 % CPU with a `screenrecord` running throughout.

Scripts: conn-cdp.mjs (CDP runner), conn-probe1.js, conn-bench.js (run 1), conn-bench2.js (run 2), conn-probe2.js; outputs conn-*.out.json, all in the scratchpad.


---

# Outcome (implemented 2026-09-27, 09:30-11:00 CDT)

**Built and verified on the live tablet:**
- `tools/pinelink.py`: 4th `-c copy` MPEG-TS output over localhost UDP; `TsDoor` fan-out on `10.89.1.246:8098` and `100.74.95.59:8098` (`/live.ts`, `/state`, `/health`), keyframe-aligned joins, 6.5 s ring; `state.json` carries `ts`; unit runs `python3 -u` so `~/pinelink.log` is written again.
- Kiosk: `video/PineCamWall.kt` (ExoPlayer progressive TS on a media-overlay SurfaceView, lag trim + reconnect watchdog), bridge verb `pineDesktop.pineCam`, `installPineCam()` in MainActivity, Wi-Fi `FULL_LOW_LATENCY` lock, default-network callback with debounced re-probe/reload, `LoopDoor.carry()` 3 s connect timeout + keepalive + bounded pool + byte counters, `StationClient` pool idle 60 s.
- `pine-cam.js` (desktop and both kiosk copies identical): hands the box rectangle to the native surface, blanks the poster while it is up, follows drags, tap = full screen, sheets retire the surface, lock/hidden hide it. **The rect scale is `screen.width x devicePixelRatio / innerWidth` (1.161 here), NOT devicePixelRatio (1.25)** - the first build placed the surface 41 px right and 16 px low and the operator saw two pictures.
- `deaf-watch.js` (desktop, `pine-views/` AND `pine-sampler/` kiosk copies - the panel runs the pine-views one): a media element stuck LOADING with no metadata for two rounds, or a MEDIA_ERR_NETWORK, counts as a strike while the bridge answers.
- Station: `--timeout-keep-alive 75` on the `:8096` uvicorn (compose.yaml) - verified: a second request on one socket 8 s later is answered; app.py: ORJSONResponse as the default response class, `sfx_note_play` disk write on a thread with the memo kept authoritative, speakbox cold scan on a thread.
- Tablet: logcat ring 8 MB.

**Measured after deploy:** native picture playing, `state: ready`, 30 fps (rendered counter +94 per 3 s), 0 dropped, 0 reconnects, lag 0.69-0.72 s, surface rect == image slot to the pixel (634,431,412x233), drag follows to the pixel, tap toggles 1340x800 full screen and back, deaf-watch reports `media {stuck 0, errors 0}`. Kiosk CPU ~220% with the player (ExoPlayer thread ~20%, decoder ~12%); the WebView renderer fell from ~155% to ~120% because the poster polls once a second instead of four times.

**Not done (permission denied to this session):** `sudo nmcli con modify TacoNet 802-11-wireless.powersave 2` and `sudo iw dev wlP9s9 set power_save off` on the DGX; plugging `enP7s7` into the gateway is physical. Nothing was committed to git in either repository.
