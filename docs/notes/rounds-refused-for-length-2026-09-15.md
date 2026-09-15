# Rounds refused for length, measured

Date: 2026-09-15, 01:00-02:00. Status: measured on the live station after the
refusal reasons became legible. This note does not change scheduling; it
states the numbers and the choice they put in front of the operator.

## What the station now says out loud

Until 2026-09-14 a round that was written, voiced and then turned away at
hand-over left its lines in the feed as `prepared`, with an estimated clock
that kept running. Measured over four hours that evening: 1,466 such rows,
of which 25 were ever heard; 57 of the 58 rounds that entered the feed that
way never aired at all. The script page laid them out as planned lines, the
rounds that did air threaded between them in the ledger's order, and the
operator read it as "lines skipped" and "this segment is out of order"
(inbox #1136, #1137).

Those rows are now WITHDRAWN at the moment of refusal and each one carries
the reason. The reasons are no longer a shrug:

| rows | what the station said |
| --- | --- |
| 32 | the gallery round runs 196s and its entry has 92s left (45s grace) - the round is longer than the time the sheet gives it |
| 19 | the caller round runs 126s and its entry has 0s left (45s grace) |
| 30 | the hand-off was refused: the caller's own check said no |

## The shape of the hour

The sheet itself is sound. Eighteen entries, sixty minutes exactly, and the
work the roads ask for sums to 2,665 seconds - forty-four minutes - with
records filling the rest.

What is not sound is where the clock stands relative to the material. At
01:46, forty-six minutes into the hour, `/api/system2/binding` reported
every entry up to the fourteenth already past its deadline, and for each one
`would_fit: 0`. The cupboard at that moment held 112 finished gallery rounds,
144 caller rounds, 90 adverts and 48 banter rounds - 441 candidates - and not
one of them could be placed. The reason each gave was its own length against
the room left in an entry whose clock had run on while the room was quiet.

That is a loop, and it feeds itself: material is refused, the room goes
quiet, the quiet pushes the sheet further ahead of the material, and the next
round is refused by a larger margin.

## The escape hatch, and why it is not enough

A round may ignore the running order when the room has gone silent or when
it is overdue past the dial (`unheard_free`, `_ready_shelf_air`'s `rescue`).
On 2026-09-14 that exemption was granted at the shelf and then quietly
withdrawn one door later: `_speak_turns_floorless` re-ran `_ready_round_fits`
with no slot of its own, read whichever entry the clock happened to be
standing on, and refused. The first ten minutes after refusals learned to
speak produced forty-one withdrawn rows, every one of them saying "the sheet
is on the news entry, not gallery". That is fixed - the free road is now
honoured through the hand-off - and the standing consumer does air a round
when it walks.

It walks every 420 seconds and airs one round. Against a cupboard of 160
unheard rounds, 77 of them overdue and the oldest waiting two days and ten
hours, one round per seven minutes does not drain anything.

## The choice

This is a production decision and it belongs to the operator.

1. **Write to the entry.** Give each road a target length taken from its own
   entry on the sheet, so a four-minute painting entry is written to about
   three and a half minutes rather than to 196 seconds against a 92-second
   remainder. Cheapest to do, and it does not touch the running order.
2. **Give the round the whole entry.** Choose and finalise the material
   BEFORE the entry opens, which is exactly what the admission gate in
   `docs/sequential-script-playout-audit-2026-09-14.md` exists to do: commit
   the occurrence and its cue sheet ahead of the reader, so a round is never
   measured against the remains of its own slot.
3. **Let the cupboard answer the quiet faster.** Raise how often the standing
   consumer may air an overdue round while the room is silent. It treats the
   symptom and will not stop the sheet drifting ahead of the material.

The second is the architecture already agreed. The first is worth doing
anyway, because a round that does not fit its own entry is a writing fault
whatever the sequencer later does about it.

## What improved tonight, measured

Dead air per hour, from the gap log: 1,026s in the 20:00 hour; 445s in the
21:00 hour; 198s in six gaps by 01:52. The event-loop stalls behind much of
it were two synchronous reads on the loop - a library search that walked all
36,234 tracks once per line of a round, and a pantry gauge read many times a
tick. Both answer from a memo now, and the ten-minute stall window fell from
19 stalls and 40.3s blocked to 3 stalls and 6.3s.

Related: [ghost rounds withdrawn](ghost-rounds-withdrawn.md),
[the cupboard must be heard](cupboard-must-be-heard.md),
[binding and the hour shape](binding-and-the-hour-shape.md).
