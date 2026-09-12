---
name: why-the-feed-shows-fragments
description: The booth feed shows "pieces" because dj_start() wipes _RADIO["chat"] on every self-restart, and dead air from a stalling box triggers those restarts
metadata:
  type: project
---

2026-09-10. "I'm seeing just pieces of the feed appear… I want the feed
to be a gradually executing play." PROVEN, with the chain end to end:

1. **The satellite stalls.** `clip cut short: 0s of 115s reached the room`
   / `satellite is reachable but stalling`. Whole rounds are held.
2. **Dead air accumulates**, gold bars cover it (that is what sounds
   fragmentary on the box).
3. **Three strikes and the show restarts itself** — `dead air held through
   two kicks — restarting the whole show` → `dj_start()`.
4. **`dj_start()` sets `"chat": []`.** THE BOOTH FEED IS WIPED.
5. So the feed only ever holds the minutes since the last wipe. Measured:
   at 20:35 it held a rolling hour (59 call lines); at 20:38, after a
   restart, **39 rows spanning 3.0 minutes**.

So the fragments are a FEED-HISTORY artefact of restarts, not lines being
lost. The Script view (#1167, `/api/director/aired`) reads the air log and
therefore survives restarts — it is the right surface for "the play in
order".

**Also: ~64% of `prepared` rows in the booth feed are BANKED shelf/larder
material**, not queued-for-air. The feed mixes the cupboard with the
broadcast, which makes a healthy show read as broken. Verified by matching
feed text against prep_shelf.json + larder.json.

**A process restart also wipes it.** `docker inspect` showed 23 restarts
in a day (most were deploys). Exit code 0, never OOM — memory sits at
2.9 GB of 121 GB.

The station is compute-bound, not broken: `gemma4:31b` median 32s working
/ 149s waiting (75% queue), 45 jobs deferred.

See [quota-outranks-the-sheet](quota-outranks-the-sheet.md), [repetition-on-air-measured](repetition-on-air-measured.md),
[pinebox-broadcast-debugging](pinebox-broadcast-debugging.md).
