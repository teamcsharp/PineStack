---
name: audio-owner-and-the-play-switch
description: "Why no page makes a sound: the #1008 solo gate, the #1161 terminals table, the play switch - and #1332, the owner that polls but never listens"
metadata:
  type: project
---

**"No audio" on the pages is almost never the pipeline.** The chain:

1. `pineSoloGate(clock)` in the page JS gags EVERY audio/video element
   when `clock.audio_owner` is set and is not this page's
   `pineListenerId()`. One owner sounds; everyone else mutes.
2. `audio_owner()` resolves the owner. It used to be a bare listener id -
   and ids are minted per page load (`sessionStorage.pbfmListener`), so a
   reload orphaned the air and gagged the WHOLE HOUSE until the 90s
   `AUDIO_OWNER_LIFE` lease expired (#1185).
3. `terminals` in settings.json (#1161) is the per-DEVICE table:
   `{name, play, addr, listener, fallback, music/voice/reply}`. **`play`
   is the out-loud switch.** It was stored, written by the panel, and read
   by NOTHING until #1185.
4. #1187: a `play=false` device may not keep, recover, or be given the
   air. Holding the exclusive while refusing to sound silences everything -
   but it is **not** the only combination that does. See 5.
5. #1332: there is a SECOND combination - a device with `play=true`,
   polling normally, that acknowledges NOTHING. #1187 asks whether a
   device is SET to play out loud; it never asks whether it does.
   Measured live: a freshly launched desktop held the exclusive with
   `play=on`, polled steadily so the stopped-polling test (#1208) passed,
   and did not appear in the ack ledger at all - while two tablets that
   had played **52 and 50 clips** sat muted **75 and 74 times each**
   waiting for it. **Polling is not consuming, and the gate was reading
   the wrong one.**

**The #1332 cure.** `OWNER_DEAF_SECONDS = 75` of unbroken ownership with
zero acknowledgments drops the exclusive. Two corrections the measurement
forced:

- The run is timed from when the owner **CHANGED**, not from its last
  claim. The page re-claims every few seconds - this is what triangulate
  means by *"it re-gags itself"* - and anchored on the claim the threshold
  was never reached.
- Dropping was not enough on its own: the page re-claimed on its next
  poll, so the claim door now refuses it for `OWNER_DEAF_REST = 300s`.
  **A cure undone faster than it can be noticed is a cure nobody has.**

Also caught before shipping: the helper read `ev["who"]` from ack rows
that key it `listener_id`. It would have matched nothing and returned True
for EVERY owner - a check that can only ever print one answer.

**Diagnosing, in order:**
- `GET /api/radio/listeners` - the roster with `addr` per listener and
  `owns_air`. This is how you map an opaque id to a device.
- `GET /api/settings` -> `terminals` - **check `play` first.** On
  2026-09-11 the whole "no audio from the pine tab" was `pinetab
  play=false` after the operator flipped it; the code was correct.
- `GET /api/broadcast/health` - now reports `gagged` (the owner stopped
  polling, #1208) and `solo_gagged` (triangulate's: the owner is polling
  fine but muting the house). **Two different faults that wore the same
  word.** `solo_gagged` is computed only when nothing has been heard for
  60s, because at 30s it read True with the station audible.
- `/api/dj` -> `playback.deliveries[].listeners[id]` for the per-listener
  `audible_volume`/`muted`. **TRAP: several deliveries are in flight at
  once and each holds that listener's last report FOR THAT DELIVERY.**
  Picking `deliveries[0]` reads a stale snapshot and looks like flapping -
  take the NEWEST report across all deliveries (or use
  `playback.events`), or you will report a mute war that is not there.
- `POST /api/radio/solo {"listener": id}` hands the air over;
  `{"clear": true}` releases it. A `play=false` target is refused with
  `refused`/`why`.

Volume 0 with `muted:false` is usually a gap between clips, not a fault.
Browser autoplay refusal shows as `started:false` + "play() failed because
the user didn't interact with the document first".

See [pinebox-broadcast-debugging](pinebox-broadcast-debugging.md) (the BOX route, a different road),
[floor-and-paced-air](floor-and-paced-air.md) (#1147 the shell unmute war).
