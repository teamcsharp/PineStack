---
name: audio-owner-and-the-play-switch
description: "Why no page makes a sound: the #1008 solo gate, the #1161 terminals table, and the play switch"
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
   air. Holding the exclusive while refusing to sound is the one
   combination that silences everything.

**Diagnosing, in order:**
- `GET /api/radio/listeners` - the roster with `addr` per listener and
  `owns_air`. This is how you map an opaque id to a device.
- `GET /api/settings` -> `terminals` - **check `play` first.** On
  2026-09-11 the whole "no audio from the pine tab" was `pinetab
  play=false` after the operator flipped it; the code was correct.
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
