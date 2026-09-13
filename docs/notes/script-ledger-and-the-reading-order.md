---
name: script-ledger-and-the-reading-order
description: "#1330/#1333: the script is now a DOCUMENT - data/script_ledger.jsonl, (block, ord) written once at commit - not an hour reconstructed from air_log by a timestamp eight paths rewrite"
metadata:
  type: project
---

2026-09-13 (#1330). **There was no script document.** `screenplay_compose`
rebuilt the hour from `air_log.jsonl` on every poll, ordered it by
`air_at` - a field eight separate paths rewrite - and then ran four
corrective passes over the result. The earlier tickets had already
measured what that costs:

- **104 of 129** re-appended ids had `air_at` move, median **88s**.
- Reading one hour twice, **45s apart**, put **83 of 468** elements in a
  different order.
- **52 of 1,055** elements ran backwards, with the SFX guy in both of the
  biggest pairs.
- #1259 said it outright: **"air_at cannot order a script."**

**The cure is a ledger, not a better estimator.**
`data/script_ledger.jsonl` is append-only. `(block, ord)` is assigned
**once**, at commit, and never rewritten. It is committed from
`_speak_turns_floorless` at the point where the running order is final but
nothing is audible yet. It carries the same line ids the ring goes out
with, so a panel can match `speaking_now.id` to a script row **by
identity** - the join `director_find_script` previously had to fake with a
substring search that failed on short lines and on retired rounds.

**The SFX guy is IN the ledger**, at the position he was rolled into. His
cadence and his random roll always happened at assembly time; it was
simply never recorded anywhere, which is why he kept turning up as one
half of the worst out-of-order pair.

**#1333 - a block is not an instant.** The first cut anchored a whole
block at its earliest time, so anything that happened DURING a round
sorted to the far side of it. Measured: **15 backward pairs in 365**,
worst **93.3s**, and every single one the same shape - `dialogue (in a
block) -> action (unledgered)`. Now each row keeps its own stamp, made
monotone across the block by `max(own stamp, previous + 0.001)`. After:
**0 backward pairs in 558 elements, 0 ord inversions, 23 of 23 SFX rows
inside their conversation, 47 unledgered events now inside a block.**

**How to read it.** An element carrying `block`/`ord` was **scripted**.
One without - a rescue sting, an emergency filler, a record, an advert, a
call - **was not**, and keeps its clock slot. That absence is a signal,
not a gap: it tells you which roads are authored and which are still being
inserted by the air.

**The measurement that matters**, over 12 minutes of live air: **28 of 28
distinct aired lines were already in the script at the moment they started
airing**, median **0.0s**. The document leads the broadcast, which is the
whole point of it.

See ),
[running-order-vs-clocks](running-order-vs-clocks.md) (the clocks this replaces),
[which-pile-a-road-lives-on](which-pile-a-road-lives-on.md) (which roads are authored ahead),
[audio-owner-and-the-play-switch](audio-owner-and-the-play-switch.md) (what makes a scripted line inaudible anyway).

**#1336: and one conversation at a time.** Monotone rows fixed the reader
being thrown backwards; it did not stop two blocks whose time spans OVERLAP
from being shuffled into each other. Measured: 14 of 37 neighbouring blocks
overlapped, rendering as `55 56 56 55 56 55 57 56 57` - three conversations
shredded together a line at a time, every stamp ascending, and unreadable.
Only one thing airs at once, so an overlap is a stamping artefact. Blocks
are laid out one after another and the monotone walk runs across the whole
document rather than restarting per block. Where that moved a row, the
element carries `air_at` with the stamp it arrived with - its presence is
the signal that the row is not where its own clock said it was.

Final state, live: **0 backward pairs, 0 blocks re-entered, 0 order
inversions, 38 of 38 SFX rows inside their conversation.**
