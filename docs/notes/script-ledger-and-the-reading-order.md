---
name: script-ledger-and-the-reading-order
description: "#1330-#1339: the script is now a DOCUMENT - data/script_ledger.jsonl, (block, ord) written once - not an hour reconstructed from air_log by a timestamp eight paths rewrite; and half the spoken lines were never in it"
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

**How to read it.** Everything that has been heard carries `block`/`ord`
(#1339, below), so the position is no longer the signal - the **`scripted`**
flag is. `true` means the booth wrote the line down before it was audible;
`false` means the station reached for it and the ledger caught it once it
had aired. That is what tells you which roads are authored and which are
still being inserted by the air.

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

**#1339: half the spoken lines had no place in the document.** The ledger
is written from the booth, and the booth is not where half the air comes
from. Measured on one live hour: **194 of 399 dialogue rows carried no
`(block, ord)`** - 151 gold bars, 33 of the SFX guy's quips, 9 adverts -
and every one of them had aired. They are minted by the fill and rescue
roads and appended straight to the ring, so `script_ledger_commit` never
saw them and the screenplay could only order them by raw `air_at`.

That is what "the script jumps around" actually was. Dropped into a
ledgered conversation they push its own turns apart: conversation b90
opened at element 14 with turn 0, and its turn 2 did not appear until
element 39 - **24 elements of other material between two consecutive
turns.**

They cannot be written down before they are audible, because nothing knows
they are coming. So they are committed as soon as they have been **HEARD**
- one block each, in air order, by `script_ledger_catch_up` from
`airlog_keeper`, the hook whose own docstring calls it *"the one hook that
catches all twenty-five ring append sites"*. Patching the roads one at a
time would have missed the next one somebody adds. A one-row block is
contiguous by construction, so it can never split anything. They are
marked **`scripted: false`**, because a reader is entitled to know which
lines were planned and which the station reached for.

After: **100% of dialogue rows placed** over the last three minutes, block
runs reading `b126/0..5` and `b166/0,2,3,4,6,7,9,10,11,13`, with the
stings landing exactly in the `ord` gaps they punctuate.

**The lesson matters more than the fix: the metric said it was fine.**
Three counters watched that document and all three read clean for fifteen
minutes while it was wrong.

- **"0 backward pairs" was true BY CONSTRUCTION.** #1336b rewrites every
  element's stamp ascending *after* the sort, so nothing downstream of it
  can ever measure backwards. The check was reading its own output.
- **The other two ranged only over rows the ledger knew** - and every row
  it knew was in perfect order. The fault lived entirely in the rows they
  could not see, which is exactly the set that made it a fault.

What found it was dumping the actual sequence and reading it. **A meter
built out of the thing it is measuring cannot fail, and a meter that
cannot fail is not evidence.** Before trusting a clean number, ask what
input would make it dirty.

**#1337: and do not re-sort an hour the ledger knows nothing about.** The
merge was gated on `if _ord:`, and `_ord` is the whole 48-hour ledger, not
the hour being composed. So it was true for every compose, including hours
predating the ledger entirely, and it keyed every row on raw `air_at` with
the list position only a third tiebreak. But #1259, #1265 and #1299
express their results **as positions in that list**: re-sorting on
`air_at` discards all three. Those hours reverted to the combed order
those passes exist to repair - and then the monotone sweep painted clean
ascending stamps over the top, so they measured perfectly. The gate is now
the hour actually having ledger rows; an hour the ledger does not cover is
left exactly as the repair passes built it.
