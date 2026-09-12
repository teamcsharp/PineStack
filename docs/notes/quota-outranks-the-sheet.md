---
name: quota-outranks-the-sheet
description: caller_per_hour 10 vs 4 caller entries on the sheet - a deficit that can never close, so calls pre-empt every other entry and the manager never airs
metadata:
  type: project
---

2026-09-10 evening. "I want the manager sending messages downstairs often"
— measured, the manager had aired **zero lines** across an entire feed
window while `upstairs_per_hour` was 6 and its entry read `commit=ready`
with 120s bound. The memo entry came round at 20:19, fired, and produced
nothing.

**The cause is the CALL QUOTA outranking the running order.**

    caller_per_hour = 10        the canonical hour carries 4 caller entries

A deficit that can never close. And being behind is what makes a quota
pre-empt: the log says it outright —

    (#1073) a phone call had to be covered - owed 4 now,
            and it goes before the running order asks again

So calls take the manager's slot, every hour, forever. Measured in one
rolling hour: **81 call lines aired and 0 manager lines** — and all 81
were the SAME caller (Junebug).

`quota_sheet_room` (#977) exists to bound exactly this and its docstring
names the damage in advance: *"the counter sat permanently behind, and
being permanently behind is one of the things that forces the preparer
onto the dearest road on the board — a deficit that could never be closed,
spending real engine time every hour trying."* It did not hold here; the
dial was simply set past what the sheet can supply. **Set the dial to the
number of entries the sheet actually carries.**

This also explains the preparer never leaving the caller road (nine
samples over 47 minutes, all `caller`) — which is why banter was never
written and #1174's multi-document spread went untested.

**THE OTHER CONSTRAINT, measured the same evening:** `gemma4:31b` runs at
a median of **32s working and 149s waiting — 75% of every model call is
queue**, with 45 jobs deferred. Per-model admission caps are tint 4 /
station 2 on `OLLAMA_LANES=1`. The caps are a deliberate WAITING DEPTH
(#1080: a shallower cap made 70 of 148 asks bounce), so do not "fix" them
without re-reading that note — the station is compute-bound, and two
concurrent 31b calls were measured at 0.96x.

**METHOD WARNING, learned the hard way three times in one evening:** do
not score System2 slots with `s.get("ready_seconds")` — that field does
not exist on slot dicts and everything reads as bare. The authoritative
coverage answer is `/api/director/why/<kind>` → `entries[].commit`
(`ready` / `fresh` / `recording` / `cut`). Likewise `/api/system2/status`
`inventory` is a dict of COUNTS, not a list. And `published` IS an airing
(the page route) — counting only box/stream reads a healthy show as
silent.

See [which-pile-a-road-lives-on](which-pile-a-road-lives-on.md), [running-order-vs-clocks](running-order-vs-clocks.md),
[repetition-on-air-measured](repetition-on-air-measured.md).
