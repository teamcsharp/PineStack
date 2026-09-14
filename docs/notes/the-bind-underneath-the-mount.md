# The bind underneath the mount

*2026-09-14. Why the station played no clips, why the camera could not join, and why the dead air is not the script's fault.*

Three faults were found in one day, and none of them was where the symptom pointed.

## 1. `/samples` was empty inside the container and full on the host

The video button said "still warming" for ever. The SFX guy played nothing. Every reader in the station answered "no samples", which is indistinguishable from an empty library.

The share was fine. On the host, `/home/ehm_eckx/samples` was `dev=122` — the CIFS filesystem — with 44 entries and 32,367 video clips. Inside the container, `/samples` was `dev=66306`: the host's *root disk*. The container was looking at the empty directory **underneath** the mount, not the mount itself.

A Docker bind is `rprivate`: it is resolved when the container is **created**, and a mount that appears on the host afterwards never propagates in. `docker compose restart` does not re-create the container, so restarting — the obvious thing, and the thing the ladder does — could never have fixed it. Only `docker compose up -d --force-recreate spark-agent` can.

**The tell**, now printed by `GET /api/sfx/doctor`: the device id of `SFX_ROOT` against the device id of the station's own data directory. Same device = stale bind. (#1361)

## 2. The clip book (#1362)

Four earlier attempts (#1303c, #1306c, #1306d, #1311, #1321) were all a memo in RAM in front of the same share walk, so every restart put the operator back at "still warming", and the walk had to finish before anything was drawable. The walk was also dying silently — `except Exception: pass` around the whole thread.

`data/sfx_clips.db` is a SQLite book of every clip: path, length, playable. The indexer writes it on its own thread, commits **per folder**, and is started at boot. A tap is one indexed read on a reader connection of its own, with no lock and no stat — the share is never touched on the tap road.

Measured, with the indexer running: `/healthz` 5–15 ms, the tap 11–25 ms on eleven of twelve. The book survived every restart (39,808 rows, 20,724 video clips ready *before* any walk). Two things had to be found by measuring rather than reasoning: `ORDER BY RANDOM()` was replaced by a random rowid walk, which returned the **same clip four times in ten** (rows are written a folder at a time, so the first clip after each run of audio wins) — now COUNT + OFFSET, uniform; and the length lookup keyed the ledger by `path:mtime`, which is a stat on CIFS — now the book hands the length over with the path.

## 3. The ARP table was full

The camera was on and the spare radio associated with it, then timed out authenticating three tries running. The doctor said "the radio is fine — the camera is out of range". dmesg was flooding `neighbour: arp_cache: neighbor table overflow!`.

1,019 entries against a `gc_thresh3` of 1,024, five Docker bridges holding ~250 each. A kernel that cannot record a new neighbour cannot finish an ARP exchange with a device it has just met. Raising the thresholds (`tools/99-pine-neigh.conf`) let the collector run: 1,019 → 23. It was 1,107 an hour later — above the old ceiling — so the headroom was not optional. The doctor now asks this **first**, because it is the one fault where radio and camera are both healthy and the join still fails. (#1359)

The chipset then needed a USB re-bind, not a reseat — "Reset radio" does it through the host bridge (`pinelink-kick.path`), since there is no `systemctl` in the container and the old Connect button could never have worked.

## 4. The dead air is a blocked loop, not a thin script

The operator's model was that the hour has holes because the scripts are not dense enough. `GET /api/deadair` (#1368) reads the gap log and says which of two opposite faults an hour was:

```
kind=stall  dead=31318s  stall=29001s  stall_share=93%  gaps=582
last clean hour: 2026-09-14 09:00  dead 1978s = 55% of it
top blocking functions:  sfx_id 9405s · <genexpr> 6005s · publish 4322s ·
  pantry_get 3922s · prompt_learning_observe 3798s · _dj_speak_floorless 2785s
```

Three independent readings agree (my two-day pass: 91%; the inbox agent's 24 h: 93%; the route: 93%). A blocked loop cannot speak a line it has, cannot start a clip it has, and cannot be cured by writing more material for it not to play. The cure is taking the named functions off the loop; `sfx_id` and `<genexpr>` are pure and memoised and stand in for the loops draining them (their own notes say so). That work is next.

## Two rules that came out of it

- **Measure the rival explanation before shipping the obvious fix.** Every one of these had an obvious cure that would have done nothing.
- **Patch `app.py` on the host, in one process.** A full read over the SMB share takes ~120 s; the same read on the DGX takes 0.02 s. An agent that read the file, restarted the station, and wrote it back clobbered #1362c. `ssh … 'python3 - app.py' < patch.py` closes the window.
