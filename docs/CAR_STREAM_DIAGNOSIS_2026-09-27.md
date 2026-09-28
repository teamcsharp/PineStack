# The car road: why the broadcast and the Pine Cam choke on the phone, and what to do

Measured 2026-09-27 11:00-12:45 CDT. Read-only investigation plus one build: the DIAG button on the tune page (#1471). The full agent report follows this summary.

## Verdict

1. **The phone is not on Tailscale.** The iPhone peer `iphone184` has been offline on the tailnet since 2026-09-13. The car therefore arrives through the public Funnel (`https://lilspark.tail1fec29.ts.net`): phone -> Tailscale ingress (New York) -> DERP relay `nyc` -> the DGX (no direct path; that peer has carried 1.3 GB). Every request pays that relay.
2. **The relay leg is slow and bimodal.** From this PC (same internet, no cellular leg): /healthz through the funnel 0.37-0.60 s most of the time, spikes to 0.85 s and 1.54 s, and one cluster of 2.1-3.4 s per request with 7 KB/s throughput (below the 8 KB/s the audio needs); LAN 7 ms. From the DGX the agent measured a 70 KB HLS segment at median 2.6-2.8 s, p90 4.2 s, max 7.4 s on a warm connection in three of four runs. A 4 s segment plus a ~1 s playlist fetch against a 12 s cushion drains whenever two cycles run slow. That is the choke.
3. **The station adds cold starts.** A new HLS lane waits for three segments before the first playlist answers: 12.5-13.4 s measured, paid on every join, every slider move (a new lane), every container restart (three in 72 h) and the mixer's own linger exit. The mixer thread fell 4.5 s and 8.0 s behind real time under the station's GIL load.
4. **The camera "1 in 20 frames" is arithmetic.** The tune page paces JPEG frames at 1.6x the fetch time, capped at 4 s; through the funnel one 38-41 KB frame took 4.9-6.3 s, so the page sits at the 4 s cap: 0.2-0.25 fps.
5. **The page competes with itself.** On the stream road it still pulls ~34 kbit/s of background (chat-heavy `/api/dj?lean=1` 27.5 KB every 8 s, gallery 48 KB every 20 s, artwork 74 KB per track, video 1 KB every 2.5 s), ~75 kbit/s with the camera, on the same connection as a 140 kbit/s audio lane.
6. **Programme holes are a separate fault.** 778 dead-air gaps in 24 h, 4.27 h dead (17.8%): mid-round holes, page joins, pantry misses; event-loop stalls are 12% of the dead seconds. The car hears these as silence, not stutter.
7. **Not the problem:** the DGX's internet (35 Mbit/s up, 130-150 Mbit/s down, 13-15 ms to the WAN, 0% loss), its Wi-Fi hop (power save is now off), CPU headroom (70% idle on 20 cores).

## Built today: the DIAG button (#1471)

`frontend/car-diag.js`, served at `/car-diag.js` and loaded by the tune page. From page load it keeps a 10-minute ring (one sample per 5 s: road, HLS/mp3, buffer ahead, playhead advance ratio, waiting/stalled/error counts, visibility, battery, connection info where the browser exposes it, resource timings, position once granted). One tap: 5x RTT, a 256 KB throughput fetch, 3x the newest HLS segment, the playlist, a position fix with speed, an optional note (skipped in the driving layout), then `POST /api/car/report?t=` which stores `data/car_reports/<stamp>_<addr>.json` with the station's own state attached (stream/mixer counters, pulse stalls, 15-minute gap log, camera state, listener roster, tailnet peers when a snapshot exists) and files a Pine Box report in the inbox with a one-line summary. A card on the page shows the numbers. `GET /api/car/reports` (house auth) lists them. Verified through the public door and in a headless browser; a real iPhone tap is the remaining test.

## Recommendations, ranked

- **R1. Put the iPhone back on Tailscale (no code).** Open the Tailscale app, sign in, connect. The same https link then resolves through MagicDNS to the DGX directly over WireGuard (the DGX has UPnP and public IPv6, so a direct path is likely): cellular latency only, no New York relay. Trap: a link minted with `base: "tailscale"` points at the full-app port 8096 and puts the page on the clock-chaser road; keep the https funnel hostname, which `tailscale serve` answers on the tailnet as well.
- **R2. Prime new HLS lanes with a 30 s cushion** (from the mixer's PCM backlog), add `#EXT-X-START:TIME-OFFSET=-30` and `#EXT-X-INDEPENDENT-SEGMENTS`, keep the default lane warm from boot and exempt it from the reaper, so no join ever waits 12 s and the player starts with 30 s in hand.
- **R3. An adaptive master playlist** (48/64/96/128 kbit/s AAC) so iOS drops to 48k on a weak cell instead of stalling; keep 4 s segments (2 s would double the per-request overhead).
- **R4. Page diet on the stream road:** a small camera JPEG (424 px, ~10 KB) paced at 1 s, `lean=2` without the chat tail, slider debounce 1.5 s, visibility handling.
- **R5. Real camera video on the tailnet only:** a 424x240 @ 15 fps 350 kbit/s x264 HLS lane from the same ffmpeg (0.3 core), token-gated, `<video playsinline muted>` on the page. The funnel cannot carry any video lane; the tailnet can.
- **R6.** Move the `sfx_history_rows` read off the event loop (4.7 s stall) and find the two hot uvicorn threads with py-spy.
- **R8.** A per-token HLS ledger under `data/` exposed in `/api/stream/state`; today the state endpoint reports zero listeners while an HLS lane is live and the door keeps no access log.

---

# Car listening: why the radio chokes and the Pine Cam shows 1 frame in 20

Measured 2026-09-27 11:14-11:36 MDT from the DGX (`ssh ehm_eckx@10.89.1.246`). Read-only: nothing changed, nothing restarted (the container WAS restarted at 11:19:44 by someone else mid-investigation; noted where it matters). Token used: the newest live listener link in `data/shares.json`, tag `4f60aab2` (expires 1790656618) - no minting needed. Scripts and raw outputs beside this file: `car-timing.sh/.out`, `car-hlsloop.py/.out`, `car-proto.py/.out`, `car-proto2.out`.

## 0. The one-paragraph answer

The car arrives over Tailscale **Funnel**, and Funnel is a DERP-relayed TCP proxy (ingress node in NYC; DGX <-> nyc DERP 45-47 ms; "direct connection not established"). Measured from the DGX itself, with no cellular leg at all, that path costs about **1 s per request plus 25-50 KB/s** most of the time (3 of 4 runs), with **2-7 s connection-setup outliers** on 30-55 % of fresh connections. The audio is 4 s HLS segments of 70 KB behind a cushion of only ~12 s (3 segments) that also **cold-starts for 12.5 s** on every join, every slider move and every restart. Two slow cycles in a row (playlist ~1 s + segment ~2.6 s median, p90 4.2 s) drain that cushion: that is the choke. The camera is a 38-41 KB JPEG per frame paced at 1.6x its own fetch time; through the funnel a frame takes 4.9-6.3 s, so the pace pins at its 4 s cap = 0.2-0.25 fps = "1 in 20". The DGX's own uplink (35 Mbps up, 13 ms RTT, 0 % loss) and its TLS terminator (33 ms fresh, 0.5 ms warm) are not the problem. Underneath all of it the programme itself is silent 17.8 % of the time (778 gaps, 4.27 h dead in 24 h), which the car hears as dead air whatever the transport does. The cleanest fix is to take the iPhone off the funnel (Tailscale app on: the SAME https link then resolves to 100.74.95.59 via MagicDNS and rides WireGuard direct) and to give the HLS road a primed 30 s cushion so stalls become latency instead of silence.

## 1. Per-leg numbers

### 1a. Road facts (`tailscale status --json`, `tailscale netcheck`, `tailscale ping`)
- iPhone peer `localhost` (iOS, 100.92.208.88): offline, last seen 2026-09-13 15:02 UTC (14 d). So the car uses the funnel.
- Funnel ingress actually carrying traffic: `funnel-ingress-node fd7a:...:625f:d761`, relay `nyc`, rx 108.8 MB / tx 1.30 GB, last handshake 11:13:45 today. `tailscale ping -c 5` -> "pong via DERP(nyc) in 45-47 ms ... direct connection not established" (funnel ingress nodes never go direct).
- DGX netcheck: UDP yes, IPv4 99.51.188.74, IPv6 yes, PortMapping UPnP, nearest DERP dfw 19.1 ms; nyc 49.5 ms.
- `tailscale serve status`: `https://lilspark.tail1fec29.ts.net (Funnel on) |-- / proxy http://127.0.0.1:8097`. Tailscale 1.102.2. tailscaled at 0.1 % CPU.

### 1b. Same URLs, three doors (`car-timing.sh`: `curl -w`, fresh connection each; bytes and seconds)

| request | funnel https://lilspark... | door 127.0.0.1:8097 | tailnet 100.74.95.59:8096 (from the DGX itself) |
|---|---|---|---|
| /tune/<token> 115,234 B | ttfb 0.41, total 0.60 | 0.004 | 0.009 |
| /stream.m3u8 (lane COLD) | **ttfb 12.48** (437 B, 3 segs) | 0.005 (1,691 B, warm) | 0.004 |
| /hls/.../segNNNNN.ts ~70 KB x3 | 0.45 / 0.45 / 0.47 (tls 0.25-0.29) | 0.003-0.004 | 0.002-0.009 |
| /stream.mp3 first 5 s | 506,190 B | 570,514 B | 567,588 B |
| /stream.mp3 15 s | 715,590 B = 47.7 KB/s | 710,113 B | 709,318 B |
| /api/stream/state 962 B | 0.78 (tls 0.62) | 0.009 | 0.002 |
| /api/dj (no lean) 445 KB | 6.63 (tls 2.56) | 0.012 | 0.013 |
| /api/dj/video 909 B | 0.73 | 0.010 | 0.011 |
| /api/radio/clock 362 B | 0.42 | 0.015 | 0.002 |
| /api/pinelink/frame.jpg 40,400 B | **6.29 (tls 3.39, ttfb 4.94)** | 0.003 | 0.002 |
| /api/pinelink/mine 103 B | 4.89 (tls 4.24) | 0.003 | 0.004 |
| /manifest.webmanifest 786 B | 0.36 | 0.002 | 0.001 |
| /api/pinelink/live/index.m3u8 | **404** (not allowlisted) | 404 | 200, 256 B |

Burst: the 30 s mp3 join burst (480 KB at 128k) arrives inside the first 5 s on every door (506-570 KB in 5 s); the funnel carried ~100 KB/s in that burst. Steady state is 16 KB/s.

### 1c. Funnel connection setup is bimodal (`curl` x10 fresh, /manifest.webmanifest, HTTP/2 negotiated)
TLS 0.25-0.26 s on 5 of 10; **2.02 / 2.11 / 2.61 / 4.05 / 4.11 / 4.41 s** on the other 5 -> TTFB 0.35 s vs 2.4-5.8 s. Retransmit-shaped (1 s / 3 s RTO steps).

### 1d. The DGX's own TLS terminator is innocent (`curl --resolve lilspark.tail1fec29.ts.net:443:100.74.95.59`: bypasses ingress+DERP, still tailscaled's TLS + proxy)
fresh x6: total 0.032-0.043 s (tls 0.030-0.036); warm x6 on one connection: 0.44-0.66 ms. Every extra millisecond above that is the DERP/ingress leg.

### 1e. A player's life through the funnel on a warm connection (`car-hlsloop.py`: HTTP/1.1 keep-alive, one playlist + the newest segment every 4 s)
- Run 1 11:24-11:25 (60 s, 14 cycles): playlist min/med/p90/max 0.47 / 0.99 / 1.17 / 1.43 s; **segment 1.60 / 2.78 / 4.15 / 7.35 s** (69-70 KB each). 0 errors.
- Run 2 11:30-11:31 (`car-proto.py`, interleaved): warm segment 0.19-0.33 s (med 0.20) - the fast regime; in the SAME minute fresh-connection h2 fetches hit 3.87 / 7.40 / 4.01 / 5.57 s on 4 of 9, fresh HTTP/1.1 1.47 / 2.26 s on 2 of 9.
- Run 3 11:33-11:35 (`car-proto2.out`): warm segment 1.72-3.85 s (med 2.57); playlist 0.78-1.76 s (the first one 13.39 s = the lane had been reaped and cold-started again); fresh HTTP/1.1 med 4.98 s (5 of 9 at 5.0-6.4 s); fresh h2 med 0.53 s (3 of 9 at 3.9-6.0 s).
- Warm h2 clock fetches (348 B) at 11:22: 0.93 / 1.01 / 1.02 / 0.98 / 1.01 / 1.46 / 0.93 s each.
Reading: in 3 of 4 runs a 4 s segment costs a median 2.6-2.8 s and a p90 of ~4 s, plus ~1 s for the playlist. That is at the segment length before the phone's own radio adds anything. Bulk throughput on the same path minutes later was 450-650 KB/s (4x tune page on one connection), so this is not a bandwidth cap; it is per-request latency/queuing on the relayed TCP, varying by the minute.

### 1f. DGX uplink and Wi-Fi (`iw dev wlP9s9 link`, `iw ... station dump`, `ping`, Cloudflare)
- Wi-Fi TacoNet 5180 MHz, -61 dBm, HE 80 MHz, tx 864.8 Mbit/s, **power save: off** (it was on when last checked), tx retries 37,948,558 / 620,695,459 pkts = 6.1 %, tx failed 17.
- `ping -c 20 -i 0.3 1.1.1.1`: 0 % loss, 12.0/13.0/15.6 ms, mdev 0.85. Gateway 10.89.1.1: 1.3/6.2/19.6 ms, mdev 5.8 (Wi-Fi jitter, small).
- `curl https://speed.cloudflare.com/__down?bytes=25000000`: 25 MB in 1.33 s = 18.7 MB/s (150 Mbps). `POST speed.cloudflare.com/__up` 5 MB: 1.14 s = 4.38 MB/s (**35 Mbps up**). No speedtest-cli/fast/iperf3 installed. The uplink is not the constraint.

### 1g. Box load (`top -bn1`, `docker top spark-agent -eLo pid,tid,pcpu,comm`)
20 cores, load 8.8-10.4, 69.7 % idle (~14 cores free); RAM 124.6 GB with 79 GB used; swap 48 GB, 4.4 GB used (the box HAS swap now). uvicorn at 109 % CPU: threads at 49.7 %, 26.7 %, main 24.9 %, a dozen at 3-7 %. Also python3 109 %, two python at 100 %, llama-server 100 %. The mixer thread shares the GIL with that 109 %: `behind_worst` 4.53 s in the 57-min window before the restart and **7.97 s** within 151 s after the linger restart.

## 2. Listener evidence

- `GET /api/stream/state` (key): `listeners 0, rates {}, listener_rows [], recent_sessions []` at 11:16 and again at 11:33; holes 0, starve_waits 2 (76 ms), underruns 0, padded 0, encoder_restarts 0, reanchors 0, join_burst_s 30. `up_seconds 151.7` vs `produced_seconds 662.9` at 11:33: the mixer thread exits on the 180 s linger and restarts on the next request (`station_stream.py _serve()`, the top-of-loop `break`; its `finally:` clears every HLS lane).
- `GET /api/radio/listeners`: the PineTab (owns air), the desktop app, "a web page". No phone.
- `docker logs spark-agent --since 72h`: 3 container starts ("listener door on :8097"), the only `[stream]` line is "mixer warm" x3; **0** lines mention `stream.m3u8` or `/hls/` (the public door runs `access_log=False`). No source addresses anywhere.
- The only trace of real sessions is the HLS spool in the container's /tmp (`docker exec spark-agent find /tmp -path '*pinebox-hls*' -printf '%TT %s %h %f'`; container clock = host + 1 h): `hls128-m8-100-60` 11:19:01-11:19:41 host (music 8 / DJ 100 / SFX 60, 11 segments = ~40 s, cut by the 11:19:44 restart), and **`hls96-m20-100-60` from 11:35:11 host, live as this was written** (96k, personal mix) - an HLS listener that the state endpoint reports as `listeners: 0`. Personal-mix lanes are only ever created by an HLS-native player (Safari/iOS).
- `data/gap_log.jsonl` last 24 h (778 rows, `seconds` summed): mid-round hole 373 gaps / 4,615 s; page join 212 / 3,899 s; pantry miss on a banked round 140 / 4,029 s; **event-loop stall 27 / 1,828 s** (3.5 % of gaps, 11.9 % of dead seconds); page render 26 / 1,006 s. Total **15,376 dead s = 4.27 h = 17.8 % of the day**; per hour 12-55 gaps, 175-1,519 s (worst 09-26 14h: 1,519 s).
- `/api/pulse`: at +5 min after the restart 1 stall, 4.72 s, `sfx_history_rows (app.py:80493)` <- `_sfx_video_played_load (82353)` <- `sfx_video_cooldown_state (82600)` <- `sfx_video_mode_state (82894)` <- `sfx_video_mode_get_api (app.py:164743)`; at +15 min 0 stalls. (The first pulse call at 11:19 got "connection refused" - the restart.)
- **Diagnostics gap:** there is no per-listener HLS ledger. `StationStream.hls()` only bumps `asked_at`; `sessions`/`listener_rows` cover mp3 sinks only, live in memory, and die with the process. Nothing records segment request times, bytes, token or source address, so "was the car connected, on which road, and did it fall behind" cannot be answered after the fact today.

## 3. The page as a player (RADIO_PAGE_HTML, app.py 248515-251172)

- Road: `wantsHls()` = `canPlayType("application/vnd.apple.mpegurl")` (250591) -> `/stream.m3u8` else `/stream.mp3` (250625). `initMode()` defaults to stream when `AWAY` (came through the door, 250655-250665); a link on :8096 sets AWAY=false and defaults to the clock-chaser "live" road.
- Element (250696-250709): `new Audio()`, `preload="none"`, `playsinline`, appended to body; `onended`/`onerror` -> `streamRecover`; `stalled`/`waiting` deliberately do NOT reconnect. Watchdog (250758): every 5 s, reconnect only if `currentTime` has not moved for 40 s. `streamRecover` (250785): backoff 0.5 s x 2^n capped 15 s, forever. No `visibilitychange`/`pagehide` handler anywhere; iOS throttles these timers when locked (the native HLS player keeps going; recovery gets slower).
- Personal mix (250600-250616): any slider move -> `refreshPersonalMix` (180 ms debounce) -> `startStream()` -> a NEW lane key `(rate, mix)` -> `station_stream_hls` waits for 3 segments -> **12.5 s of silence per slider move** (measured cold playlists 12.48 s and 13.39 s).
- MediaSession (250803-250840): metadata + artwork (`now.art` 73,738 B per track change), play/pause/stop, seek handlers nulled. Manifest carries the token (`/manifest.webmanifest?t=`), standalone, start_url `/tune/<token>`; `initCar()` auto-enables the driving layout when standalone on a phone-sized screen.
- Build watch: `pineReloadOrDefer` (249325) defers a reload while playing; fine.
- Periodic fetches on the stream road (sizes via the door with `curl`/urllib; intervals from the page):

| fetch | interval | size | KB/s |
|---|---|---|---|
| `/api/dj?lean=1&listener=` (pollLoop 251023) | 8 s | 27,486 B (chat tail = 21,169 B, 20 rows) | 3.44 |
| `/api/dj/video?lag=&hls=1` (tvPoll 251004) | 2.5 s | 964 B | 0.39 |
| `/api/radio/clock?listener=` (clockLoop 251027) | 15 s | 366 B | 0.02 |
| `/api/pinelink/mine` (251164) | 15 s | 103 B | 0.01 |
| gallery `/api/generations/image/<n>?w=480` (249617) | 20 s when >=2 images (today 1) | 48,078 B (w=640: 74,240) | up to 2.4 |
| HLS playlist | 4 s | 1,806 B | 0.45 |
| HLS segment (128k AAC in TS) | 4 s | 69,184-70,688 B | 17.5 (= 140 kbps) |
| camera JPEG | paced (below) | 37,900-40,914 B | 8-10 on the funnel; 156 on LAN |

Background without the camera ~4.3 KB/s (34 kbps) = 25 % of the audio; with the camera on the funnel ~13 KB/s = 75 % of the audio, ~1.4 requests/s, all multiplexed on the same HTTP/2 connection as the segments (a 40 KB frame and a 48 KB gallery picture share the pipe with the 70 KB segment).
- Camera draw loop (251101-251140): one frame in flight; `paceMs = clamp(250..4000, 0.5*pace + 0.8*took)` converges on **1.6 x fetch time**. LAN 250 ms -> 4 fps = 156 KB/s (1.25 Mbps). Funnel measured 4.9-6.3 s per frame (tls 3.4 s + ttfb) -> pace pinned at the 4 s cap -> **0.2-0.25 fps** = "1 in 20". `frame.jpg` on disk is rewritten every 250-267 ms (`stat -c %.3Y` cadence .002/.268/.501/.768...), 848x480 q6 = 38,052 B; re-encoded at 424w: q6 12,275 B, q8 9,937 B, q10 8,618 B; 320w q8 6,598 B (`ffmpeg -i frame.jpg -vf scale=424:-2 -q:v N` on the current frame).

## 4. HLS/encoder tuning room (station_stream.py)

- `_HlsEncoder.start()`: `-c:a aac -b:a {rate}k -f hls -hls_time 4 -hls_list_size 15 -hls_flags delete_segments+omit_endlist+independent_segments -hls_segment_type mpegts -hls_allow_cache 0`. Rates snap to (32, 48, 64, 96, 128, 192). `HLS_START_SEGMENTS 3`, `LINGER_SECONDS 180`, `JOIN_BURST_SECONDS 30` (mp3 only: `hls()` sets `enc.prime = []` "start every HLS lane at its live edge" - the #1244 decision). No `STREAM_*` env overrides in the container.
- Playlist on disk: `#EXT-X-VERSION:6`, `#EXT-X-ALLOW-CACHE:NO`, `#EXT-X-TARGETDURATION:4`, `#EXT-X-MEDIA-SEQUENCE`; **no `EXT-X-INDEPENDENT-SEGMENTS`** (ffmpeg omits it for audio-only despite the flag) and **no `EXT-X-PROGRAM-DATE-TIME`** (flag `program_date_time` not set). Segments cut on time (3.99-4.02 s).
- Join: a new lane waits for 3 segments (12 s) before the first playlist is returned (app.py 151056-151059, up to 15 s then 503). Safari starts a live playlist 3 target durations from the end (RFC 8216 6.3.3), so the cushion at join is ~12 s minus fetch latency, and it stays ~12 s because segments arrive at real time; the 15-segment window (60 s) is only ever used for recovery, never as read-ahead. On the funnel that cushion is eaten by: one 4.7 s loop stall (segment reads are inline on the loop), one 8 s mixer lag, or two slow cycles.
- Segment length: with ~1 s per request on this road, 2 s segments would spend half of every cycle in overhead (2 requests per 2 s); 4 s is right, 6 s acceptable with a bigger cushion. What is missing is the cushion, not shorter segments.
- ABR: an `EXT-X-STREAM-INF` master with 48k/64k/96k/128k AAC-LC variants (`CODECS="mp4a.40.2"`) would let AVPlayer step down on a weak cell; at 48k a segment is ~26 KB, 2.7x faster through the same relay. ffmpeg can emit aligned variants from one process (`-var_stream_map "a:0 a:1 a:2" -master_pl_name master.m3u8`); separate lanes started in the same mixer tick are aligned to 100 ms. Personal mixes multiply lanes (3 encoders per mix; each ~2 % of a core).
- Cold-start math: 30 s of PCM primed into a fresh lane is encoded by ffmpeg in well under a second, so 3 (or 7) segments exist before the first playlist request returns.

## 5. The camera in the car - three roads costed

Funnel, measured: ~1 s/request + 25-50 KB/s in the slow regime. Tailnet direct: assume 0.5 s RTT, 2-5 Mbps (250-625 KB/s) cellular.

| road | (a) JPEG poll today (848x480 q6, 38-41 KB) | (b) existing H.264 HLS `/api/pinelink/live` (848x480@30 High, 2 s x 6, 427 KB/seg = **1.71 Mbps**) | (c) low lane 424x240@15 350 kbps (88 KB per 2 s seg) |
|---|---|---|---|
| funnel | 4.9-6.3 s/frame measured -> 0.2 fps, 8-10 KB/s | 9-17 s per 2 s segment: impossible | 2.8-4.5 s per 2 s segment: not sustainable |
| tailnet direct 2-5 Mbps | 0.56-0.66 s/frame -> pace 0.9-1.05 s -> ~1 fps, 40 KB/s (320 kbps); with a 424w q8 frame (9.9 KB): ~1.2 fps at 12 KB/s | 1.2-2.2 s per 2 s: OK at 5 Mbps, marginal at 2; 6-8 s latency; 214 KB/s | 0.65-0.85 s per 2 s: comfortable; 15 fps; ~6 s latency; 44 KB/s |
| public door | allowlisted (`/api/pinelink/frame.jpg`, gated by `pinelink_viewer_ok(t)`; mode is "all" today - `mine` says show:true for a link minted with camera:false) | **not allowlisted (404 via 8097)** and `pinelink_live_api` (135236) takes no `?t=` (read auth only) | needs a new route + allowlist entry |
| CPU | nil | nil (stream copy) | x264 veryfast 424x240x15 ~0.2-0.3 core; 14 cores idle |

Verdict: video for the car only makes sense on the tailnet road; on the funnel the honest budget is one small JPEG (~10 KB) every 1-2 s.

## 6. Tailnet direct instead of the funnel

- What has to happen on the phone: open Tailscale, sign in, VPN on (the peer has been offline since 09-13). Then MagicDNS resolves `lilspark.tail1fec29.ts.net` to 100.74.95.59, and `tailscale serve` answers the **same https URL** on the tailnet (config above: `/ proxy http://127.0.0.1:8097`), TLS terminated by the DGX (measured 33 ms fresh / 0.5 ms warm), over WireGuard direct (UPnP + IPv6 on the DGX; a cellular NAT usually still goes direct via the DGX's mapped port) or, worst case, DERP dfw (19 ms from the DGX) - still no ingress TCP proxy and no NYC. Nothing to mint: the existing car link keeps working and takes the direct path whenever the app is on and the funnel when it is off. The page still lands on the door -> `x-pinebox-public` -> AWAY=true -> stream road; https preserved -> PWA/MediaSession unchanged.
- Trap: `POST /api/share {"base":"tailscale"}` (kinds are `lan`, `host`, `tailscale` x2, `funnel`; app.py 14355-14380) mints `http://100.74.95.59:8096/tune/...` = plain http on the FULL app port -> AWAY=false -> defaults to the clock-chaser road unless "Car stream" is picked and saved in localStorage. Prefer the https MagicDNS URL. (`for:` naming a device not on the tailnet is downgraded to funnel, 150331.)
- Secure context: the page uses Web Audio (`listenerGain`) only on the mp3 road, sessionStorage/localStorage, MediaSession, `<audio playsinline>`; none of those require https in Safari. A manifest with `display: standalone` is honoured more reliably from https. The https tailnet route side-steps the question.
- On the move: WireGuard roams across address changes (a cellular IPv6 change re-keys the peer, the tunnel itself sees no TCP reset); the inner TCP still dies, HLS recovers in one segment as designed.
- Verify from the DGX: `tailscale status` (iOS peer online, `curaddr` set, relay empty), `tailscale ping 100.92.208.88` ("direct" not "via DERP").
- Expected effect: per-request cost from ~1 s + outliers to cellular RTT (50-150 ms); segment 2.6 s -> 0.2-0.4 s; camera 0.2 fps -> 1 fps (JPEG) or 15 fps (low lane).

## 7. Mechanism, as the evidence supports it

1. **Transport (dominant for "chokes" and "1 in 20").** The funnel is a relayed TCP proxy with ~1 s per request and 25-50 KB/s in its usual regime, plus 2-7 s handshake outliers on 30-55 % of fresh connections - measured from the DGX with no cellular leg. 4 s segments against a ~12 s cushion cannot absorb that.
2. **Station-side cushion killers.** Cold lane 12.5 s on every join/slider/restart (3 container restarts in 72 h plus the mixer thread's own linger exit); mixer `behind_worst` 4.5-8 s (GIL; uvicorn at 109 %); loop stalls 1.5-5 s a few per 10 min with segment reads inline on the loop. Each alone can empty a 12 s cushion; on a good road the player would merely go quiet once; on the funnel it compounds.
3. **Page behaviour.** ~34 kbps of background polling (75 kbps with the camera) on the same h2 connection as the audio; 40 KB camera frames and 48 KB gallery pictures interleaved with 70 KB segments; slider moves rebuild the lane; no visibility handling; `/api/dj?lean=1` still ships a 21 KB chat tail every 8 s.
4. **Programme holes.** 17.8 % of the day is dead air by the station's own log (mid-round hole, page join, pantry miss; event-loop stall is 12 % of dead seconds). The car hears these as silence identical to a transport stall; the button must tell them apart.

## 8. Ranked recommendations

R1 (biggest, no code): **iPhone on Tailscale.** Sign the phone in, VPN on; keep using the existing https link. Verify with `tailscale status`/`tailscale ping`. Expect segment fetches ~0.2-0.4 s, no 2-7 s handshakes, a usable camera. If the app must stay off, everything below still helps but the ~1 s/request floor stays.

R2 (station): **give the HLS road a primed 30 s cushion and no cold start.**
- `station_stream.py StationStream.hls()` (the `enc.prime = []` line): prime new lanes from the last 30 s. Keep bed and voice separately (`_pcm_burst` -> `_bed_burst` + `_voice_burst` with the sfx flag) so the prime is mixed per lane with `_mixed_program(bed, voice, sfx, hls.mix)`; ffmpeg cuts 7 segments in <1 s -> first playlist ~1 s instead of 12.5 s (`HLS_START_SEGMENTS` stays 3).
- `app.py station_stream_hls` (151065-151075, the rewrite loop): insert `#EXT-X-START:TIME-OFFSET=-30,PRECISE=NO` after `#EXT-X-MEDIA-SEQUENCE` (RFC 8216 4.3.5.2; the playlist is already VERSION 6) so Safari starts 30 s behind live with a 30 s cushion, and add `#EXT-X-INDEPENDENT-SEGMENTS`. Return `burst_s: 30` for `hls=1` in `/api/dj/video` so the #1244 lag model (`tvBurst`) keeps the picture in step.
- `station_stream.py _HlsEncoder.start()`: add `program_date_time` to `-hls_flags` (lets the phone compute true latency).
- Warm default lane from boot beside `STATION_STREAM.ensure_running()` (app.py 150916): `STATION_STREAM.hls(STREAM_BITRATE, (100,100,100))`; exempt that lane from the reaper (`_serve()` loop `for hkey, hls in list(self._hls.items())`) and from the linger `break`, or make the `finally:` keep lanes when the thread only lingered.
Expected: joins start in ~1-2 s through the funnel instead of 13-15 s; a 5 s stall or an 8 s mixer lag or three slow cycles become latency, not silence.

R3 (station): **bitrate ladder.** `/stream.m3u8?abr=1` returns a master with `#EXT-X-STREAM-INF:BANDWIDTH=56000|72000|104000|140000,CODECS="mp4a.40.2"` -> 48k/64k/96k/128k lanes started in the same mixer tick (or one ffmpeg with `-var_stream_map "a:0 a:1 a:2 a:3" -master_pl_name master.m3u8`). At 48k a segment is ~26 KB. Keep 4 s segments. Page: request `abr=1` when `streamMode && wantsHls()`.

R4 (page, `RADIO_PAGE_HTML`): (i) camera on the road: ask for a small frame (`/api/pinelink/frame.jpg?w=424` -> a new ffmpeg output in `tools/pinelink.py ffmpeg_cmd()`: `-map 0:v -vf fps=2,scale=424:-2 -q:v 8 -f image2 -update 1 -y frame_small.jpg`, ~10 KB) and raise the pace floor to 1000 ms while `streamMode`; (ii) `/api/dj?lean=1` -> a `lean=2` that drops the chat ring on the road (27.5 KB -> ~6 KB every 8 s); (iii) slider debounce 180 ms -> 1500 ms and rely on R2 so a move costs ~1 s; (iv) `visibilitychange`/`pagehide`: pause polls, never `streamRecover` from a throttled timer, re-arm on return; (v) show the road on the page (the server echoes the client address in `/api/stream/state?t=`: 100.x = tailnet, else funnel).

R5 (camera video, tailnet only): a fifth ffmpeg output in `tools/pinelink.py ffmpeg_cmd()` (584-650): `-map 0:v -c:v libx264 -preset veryfast -tune zerolatency -profile:v baseline -pix_fmt yuv420p -vf scale=424:-2,fps=15 -b:v 350k -maxrate 400k -bufsize 700k -g 30 -keyint_min 30 -sc_threshold 0 -f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+omit_endlist+independent_segments -hls_segment_filename LIVE/low/seg%05d.ts LIVE/low/index.m3u8`; a new route `/api/pinelink/cam/{name}` taking `?t=` via `pinelink_viewer_ok(t)` (134868), added to `_PUBLIC_GET_PREFIX` (app.py 150648); page: `<video playsinline muted autoplay>` with the m3u8 when `wantsHls()`, JPEG otherwise. ~0.3 core. Only worth it once R1 is in place.

R6 (station stalls): `sfx_history_rows (app.py:80493)` reached from `sfx_video_mode_get_api (164743)` is a 4.7 s synchronous read on the loop - `to_thread` it; find the 50 % and 27 % threads in the uvicorn process (`py-spy dump --pid <pid>` from the host) - they are what puts the mixer 8 s behind.

R7 (programme): the 4.27 h/day of holes is a separate track already covered in the project's notes; for the car it only matters that the button can label them.

R8 (diagnostics, station side): an HLS ledger keyed by token: timestamp, path, bytes, source address (X-Forwarded-For through the funnel), served-in time - appended by `station_stream_hls` and `station_stream_hls_segment`, exposed in `/api/stream/state` as `hls_rows`/`recent_hls_sessions`, persisted under `data/` so a restart does not erase the car. Today HLS listeners are literally `listeners: 0`.

## 9. What the phone-side button should be able to prove (10-min ring)

Safari does not expose AVPlayer's own segment fetches to the page (Resource Timing does not see native HLS loads), so the button must probe beside the player and read the element:
- every 1 s: `radio.currentTime`, `buffered.end - currentTime` (cushion), `readyState`, `paused`, and every `waiting`/`stalled`/`playing`/`error` event with a timestamp -> stall count, stall seconds, playhead rate (wall vs currentTime; <1.0 = choking).
- every 4 s: a timed `fetch` of the latest listed segment (`/stream.m3u8` then one `/hls/...`) and a 100 B `/api/radio/clock` -> per-request RTT and throughput as the phone sees them; fresh vs reused connection is not observable, so also log the first-request time after any >30 s idle.
- road: `location.host` + what the server echoes for the client address (100.x = tailnet, public IP = funnel); `document.visibilityState`; `navigator.onLine`; Geolocation (speed/position, with permission) to correlate with towers; battery is not available on iOS Safari.
- station overlay: `/api/stream/state` `behind_worst`/`holes`/`hls_rows`, `/api/pulse` stalls, container restarts, and the gap_log rows for the same minutes, so every stall on the phone is attributed to one of: funnel request >4 s (transport), cushion drained after a station stall (station), programme hole (silence with a healthy playhead), or reconnect after an address change (error -> recover).

## 10. What could not be measured from here, and how the button closes it

- The cellular leg itself: its RTT, loss, throughput and address changes; the funnel ingress -> phone TCP behaviour; how iOS reuses connections (h2 vs new). Only the phone can measure these (the probe fetches above).
- AVPlayer's real buffer policy and start offset on this playlist (the ~12 s figure follows the HLS spec; `buffered` readings on the phone will confirm) and whether it honours `EXT-X-START` here.
- Whether the slow regime seen from the DGX (3 of 4 runs) is the regime the phone sees at the same minute - the button's per-segment timings laid over a DGX-side funnel probe (`car-hlsloop.py`) answers that.
- Which hop the ingress/DERP slowness lives on (DGX -> nyc DERP over Wi-Fi + AT&T vs the ingress node itself): the tailnet-direct experiment (R1) is the control.


---

# Outcome (built 2026-09-27, 13:00-14:55 CDT)

**The phone's first DIAG report explains the "slow" it described.** Filed 12:54 from the iPhone on the tailnet (`xff` 100.92.208.88; the page's hostname guess called it "funnel"): RTT 7-24 ms, 19 Mbit/s throughput, HLS segment 403 ms, yet 20 s after the page loaded the playhead had never advanced and the first playlist took 4.0 s. That is the HLS cold start (12.5-13.4 s before a new lane answered), not the link. Note: "It being slow".

**Built and verified live:**

| Item | What changed | Measured |
|---|---|---|
| R2 cushion (#1473) | New HLS lanes are primed from the mixer's 30 s PCM backlog; the default lane is kept warm from boot and exempt from the reaper and the mixer's linger exit; a dead lane restarts with `#EXT-X-DISCONTINUITY` and keeps its old segments | first playlist 12.5-13.4 s -> **0.66-0.71 s**; 28 s of audio on disk in 1.3 s; `start_offset_s` 30 |
| R3 ABR (#1473) | One ffmpeg per lane writes 48/64/96/128 kbit/s AAC-LC variants with aligned segments and a master; `/stream.m3u8` serves the master (`?abr=0` or `?br=` for one variant); variant playlists get `#EXT-X-INDEPENDENT-SEGMENTS` + `#EXT-X-START:TIME-OFFSET=-min(30, window)` | 4 variants, segment N identical start time in all four; continuity probe 60 s: 25 segments, 0 gaps, 0 errors (single variant and ABR walk) |
| R8 ledger (#1473/#1475) | `hls_note` per playlist/segment keyed by the token's last 12 chars (never the whole token), `data/hls_ledger.jsonl` via a daemon writer, rotated at 5 MB; `state()` gains `hls`, `hls_listeners` (stalls = >6 s gap while active, dropouts = silent >=20 s), `mp3_listeners`, `hls_active`; `GET /api/stream/hls_ledger?token_tail=` | live: 53 segments, 66 playlists, 0 dropouts on the test token |
| R4/R5 camera (#1474/#1475) | pinelink writes `frame_small.jpg` (424 px, ~10 KB, 2/s) and a 424x240 15 fps 350 kbit/s x264 HLS lane (`data/pinelink/low/`); `frame.jpg?w=424` serves the small one; new `/api/pinelink/low/{name}` (token-gated, camera tick required through the door); the tune page shows the camera as a muted inline `<video>` on the low lane on tailnet/LAN/house roads, else the small JPEG paced >= 1 s on the stream road | ffmpeg +5-7% of one core for both; segment 2.000 s, 30 frames, ~370 kbit/s |
| R4 page diet (#1475) | HLS asks for the master (no `br`), quality changes no longer restart the stream, slider debounce 180 ms -> 1500 ms, camera fetches and the video poll stop while the tab is hidden | - |
| Road told by the server (#1475) | `const ROAD` from the socket peer / first X-Forwarded-For hop (100./fd7a: = tailnet, 10.89./192.168./127./::1 = lan, else funnel through the door); on the glass and in the DIAG ring; `road_seen` on the report card | the 12:54 phone report now reads tailnet |
| R6 (#1475) | `/api/sfx/video_mode` handler moved to a thread (`sfx_video_mode_state` -> `sfx_history_rows`, `sfx_db_counts`) | 2.31 s stall before; 43-75 ms after, absent from the pulse |
| DIAG dot (#1471b) | drag to place (remembered), double-tap hides, returns only in drive mode | headless-verified |
| Rolodex (#1472) | lines roll their recorded reels and d100s before the words appear; a tap replays roll by roll with each result's line, then the words assemble | headless-verified: 14 lines, 50 drums/dice, 5-roll replay 6.6 s |

**Also found and fixed:** a full-scope link opened through the public door sent its key as a header the door strips, so every token-guarded route answered 401 on that page (`const GUEST = AWAY || ...`).

**Not verified live:** the camera went off the air at 14:34 (its own Wi-Fi stopped beaconing; the same fault as 14:06-14:21), so the low lane and small still were measured during 155 s of live run but the phone's `<video>` road has not been seen on a real iPhone. Whether Safari honours `#EXT-X-START` (the lag model assumes 30 s) is the next DIAG tap's question.

**Incident during the build:** `/stream.m3u8` answered 500 from 14:29:48 to 14:40:49 because the container restarted while `station_stream.py` was mid-edit; the mp3 road served throughout. Fixed by a restart once the file was complete.


---

# Evening: the first drive, the black box, and the blast (2026-09-27, 16:45-20:30 CDT)

## What the first real drive showed (read from three DIAG taps and the HLS ledger)
- The only failure was 15:39-15:40: the phone opened the station inside the 11-minute outage caused by the afternoon build, retried six times, and was then locked; iOS suspends a page whose audio is not playing, so nothing retried for 20 minutes.
- From the 16:00 reload the stream was seamless: playhead at exactly real time in every 5 s sample, 20-25 s buffered, the adaptive stream at 128 kbit/s, segments served in 0-8 ms and fetched in 75-125 ms.
- At 16:02:52 Tailscale dropped on the phone and it continued on the Funnel via T-Mobile without a gap.
- Safari honours `#EXT-X-START`: it started ~22-25 s behind the newest segment.
- The DIAG summaries were wrong: iOS fires `stalled` about once per 5 s while its buffer is full (not audible), and the 5-minute window included samples restored from the failed session.

## Built (#1476-#1478), all live
| Item | What it does | Verified |
|---|---|---|
| Restart-proof HLS (#1476, `station_stream.py`) | persistent spool `data/hls_spool`; a lane resumes across process restarts with its media sequence continuing and a discontinuity at the join; the lanes listeners were on are rewarmed at boot; `hls_ensure` lets the player's own variant reload restart a lane; 45 s start offset for away listeners, 80 s window | 34/34 restart simulations on both ffmpeg builds; a player asking for a missing lane gets it in 0.26 s |
| Black box (#1476, `frontend/car-diag.js` 1476.1) | continuous telemetry every 30 s and on trouble, offline queue, beacon on pagehide; corrected stall/freeze accounting; station-told road with a TAILNET/FUNNEL badge; RTT and position timeline; hands-free 8 s voice note on the DIAG tap in drive mode | headless: queue, road changes, restored rows excluded, voice note posted |
| Station intake (#1476, `app.py`) | `POST /api/car/telemetry` -> `data/car_sessions/<date>_<sid>.jsonl` with the station's view; automatic Pine report on real trouble (1 per 10 min); `POST /api/car/voice` -> whisper transcript onto the report and the inbox item; `data/boot_log.jsonl`; `/api/car/sessions`, `/api/car/boots`; `tools/car_timeline.py latest` | live: batches, auto-report, a real spoken sentence transcribed, timeline, boots |
| The page keeps listening (#1476, tune page) | reconnect backoff capped at 8 s and never stops; wake-recover on online/visible/pageshow; a failed tune-in call can never stop the stream; every attempt and steering-wheel press marked | served page parses |
| No spike on reload (#1477, panel) | a level gate per AudioContext born at 0; gain nodes born at the stored level; sliders restored before any playback; elements started early play at 0 and ramp | headless: old panel peaked +10.7 dB over the stored music level on reload, new never exceeds it; on the tablet the gate held 4 s then faded in |
| Even SFX and video (#1477) | EBU R128 integrated loudness to -20 LUFS, true peak <= -6 dBTP, picture copied; levelled when picked for air, never served raw unless levelling fails within 3 s | same 30 clips: spread 20.6 LU -> 0.9 LU, 27 -> 0 outside +/-1.5 LU, 9 -> 0 peaks over -6 dBTP; `raw_served` 0 |
| Drag (#1478, `sfx-tv.js`/`.css`) | the SFX TV set declares `touch-action: none` (the browser was cancelling the drag as a scroll 22 ms in, caught by a passive probe on the operator's own drag) and keeps a drag across clip hand-overs; a `wallBox` name clash that threw on every touch is fixed | headless: old stops after 3 moves, new follows through hand-overs; installed on the tablet |

## The blast
The operator (headphones on the PineTab) was blasted at restarts: a panel reload played through a direct analyser -> speakers connection and a GainNode born at 1.0, with slider defaults 100/160 read before the stored 29/47 were restored. Separately the SFX board served unlevelled clips raw at up to -10.8 LUFS every 20-30 s. Both fixed above. The operator's levels (music 29, voice 47, SFX 100, video 100) are deliberate and unchanged. Restarts and tablet installs now lower the tablet to 6 first (volume-down key presses; `cmd media_session volume --set` does nothing on this GSI) and restore 20 after the panel settles.

## Open
- One live survival test (a player walking HLS through a real container restart) rides on the next restart.
- The tune page (`RADIO_PAGE_HTML`) and the kiosk's `sfx-tv.js`/`pine-meters.js` audio graphs are not behind the new level gate; the tablet's gate opens by its 4 s fallback because the kiosk's audio law does not signal it.
- Real iPhone checks still to do on a drive: MediaRecorder voice notes, the audio-session resume after a note, the TAILNET/FUNNEL badge.
