---
name: pulse-library-and-firmware-down
description: "#1156 (2026-09-02): the radio outage was a CIFS-over-Wi-Fi crawl + sync saves starving the loop (watchdog restart storm) plus a Nabu whose firmware was down; what the pulse sentinel, the hot shelf, the wire-detail probe and the new cures give the orchestrator"
metadata: 
  node_type: memory
  type: project
  originSessionId: 18a0971b-fb8c-41e5-a752-37ea37c56147
  modified: 2026-09-02T12:31:04.203Z
---

**The 2026-09-02 outage, measured (do not re-derive):**
- lilspark is **Wi-Fi only** (`enP7s7` DOWN, everything on `wlP9s9`, 5GHz
  -61dBm but 18% tx retries). Both the Nabu and the exbox music share
  ride that hop. The CIFS TCP session to exbox sat at `cwnd:3`
  (`ss -tni 'dport = :445'`), 1.5MB retransmitted, 360k out-of-order:
  the share crawled at **40-100 KB/s**, a `stat` took 28s, `dd` of 2MB 38s.
- Every SYNC touch of that mount on the loop was a deaf window: py-spy
  burst named `track_tags` (mutagen open from `/api/music/track`, 29s),
  `_pantry_save` (13.5MB `prep_shelf.json` dumps per save), `_larder_save`,
  `_media_prune` (4.5k stats per clip written), `_load_vectors` (doom mind
  625MB), `said_rows`/`banned_words` (JSON load per call). Watchdog:
  7 restarts + a spent budget in one night = "the radio is dead".
- **C `json.loads`/`dumps` HOLD THE GIL** - `asyncio.to_thread` does NOT
  unblock the loop for big JSON. Fix is: coalescing flusher threads for
  the saves (fewer dumps), and never parsing a big store for a count.
- The Nabu was in the **firmware-down shape**: ping OK, 6053/80/3232 all
  REFUSED. HA restarts and the restart button cannot reach it; the old
  ladder burned the whole 4/day HA-restart budget on it. It rebooted by
  itself ~20 min later and came up on **.161** while `SATELLITE_HOST`
  (env) still says .205 and a stranger at .205 answers RST.
- After a restart the desktop app's main process re-asserts its own
  selectors (routing came back box/box/box after I had set both) - the
  operator's app pick is the law; tell the user to pick "both" in the app.

**What the orchestrator has now (#1156, deployed 2026-09-02):**
- **Pulse sentinel**: heartbeat task + daemon thread sampling
  `sys._current_frames()` when the loop is >1.5s late; ledger
  `data/loop_stalls.json`, `GET /api/pulse`, census service
  `station-pulse` (sick when a stall >=8s = the watchdog's probe), diagnose
  rung "The station's own pulse", `dj_state.pulse`, fingerprint
  `pulse:stalled` -> cure `name_the_blocker` (names frames, needs code).
- **Library road**: `data/music_hot/` hot shelf (<=40 records), `/music/{id}`
  serves the local copy first, `records_warmer` copies coming + request/queue
  heads every 30s, copy timing feeds `_LIBRARY` speed; `dj_next_track`
  swaps to a hot record when the share is slow (never a `_TRACK_TALK`-owned
  one); `GET /api/library`, `POST /api/library/warm`, census `music-library`,
  diagnose rung, fingerprint `library:slow` -> cure `hot_records`.
- **Wire detail**: `_wire_probe_detail()` (SATELLITE_HOST first, a
  LISTENING 6053 anywhere wins), `nabu_firmware_down()`, `wire_reading()`;
  `box_triage` firmware branch -> `_route_around_box()` (voice AND music to
  'both', remembered in `_FAILOVER`) + `_box_vigil` (returns only on 6053
  OPEN, waits for the entity, restores routing incl. music) +
  `_page_operator_power_cycle()` (note_action + notifications bell, 30-min
  throttle); `_nabu_link_ladder` stands down instead of restarting HA;
  dialogue/onair watchdogs stand down while `_FAILOVER`; fingerprint
  `device:firmware_down` -> cure `route_around_box`; diagnose rung "The
  device on the wire" + power-cycle steps; `dj_state.box.wire/firmware_down`.
- `REPAIR_SEED` rows now MERGE into an existing `repair_learned.json`
  (before, new seeds never entered a populated ledger).
- **Vector sidecars** `vectors.meta.json` next to each store (counts,
  per_file, mtimes, dim): `_vector_chunks_n()` for count-only readers,
  lazy `speakbox_reindex` (no parse when mtimes match). Build them
  offline with the recipe: docker cp a script that json.loads each store
  and writes the meta, `docker exec spark-agent python3 /tmp/build_vec_meta.py`
  (596MB doom parsed in 6s in its own process, zero loop impact).

**How to apply:** when "the radio is dead" starts with watchdog restarts,
read `/api/pulse` first - it names the blocker without SSH. When the Nabu is
"unavailable", read `/api/pinebox/wire`: 6053 open = HA-side wedge (ladder),
all refused = power cycle (the station already routed around it), dark =
power/Wi-Fi. The real hardware fix is plugging lilspark into Ethernet.
Verified after deploy: healthz 1-50ms through boot, `/api/crystals` 12ms
(was a 11.4s stall), records playing from the hot shelf, wire reads
"healthy at .161". See [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md),
[pinebox-broadcast-debugging](pinebox-broadcast-debugging.md), [public-broadcast-road](public-broadcast-road.md).
