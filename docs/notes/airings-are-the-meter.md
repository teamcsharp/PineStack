---
name: airings-are-the-meter
description: Operator's standing rule - work expires by AIRINGS, not by time; an item with 0 airings has no time expiry at all (news excepted)
metadata:
  type: feedback
---

2026-09-11, operator, on seeing the retirement desk show rows at **0/18
airings** with expiry counters (2h 52m, 12h 2m):

> "these clips that never played should not be expiring without playing.
>  Lines should expire primarily by airings before time is relevant. I am
>  seeing lines expire that were never played"

**Why:** the station spends its scarcest resource - one serialised model,
75% of every call spent queueing - to write, tint and record a round.
Throwing that away unheard destroys the only thing the pause was for. The
code already half-agreed with him: `stock_expires_at` argues in its own
comments that *"a verified round nobody has heard yet is the station's
best stock, not its oldest rubbish"* (#1074) and *"old unheard work is an
argument for AIRING it, not for throwing it away"* (#1075) - and then put
a three-day clock on it anyway.

**How to apply:** #1180 - in `stock_expires_at`, an item with no
`aired_at` and no `aired` count returns 0.0 (no expiry). Once it has
aired, every existing clock applies unchanged: the repeat window, the
96-hour rhymed keep, the innings cap.

**NEWS IS THE EXCEPTION** and must stay one: a bulletin is about something
that happened, so an unread one is not best stock, it is wrong.
`NEWS_PREP_LIFE` governs it, above the unheard check.

**The shelf is still bounded without the clock** - `shelf_cap` per road,
`alt_shelf_trim`'s ceiling at twice it, the retirement desk. The other two
deletion roads already honoured this rule (`resort_may_drop` returns False
on `row_unaired`; `cupboard_rotate` goes through it), so `stock_expires_at`
was the only door aging unheard work out.

Measured after: every road `expired=0`; the caller shelf grew 94 rows/83
ready -> 105/93 instead of shrinking.

Related standing rule, same spirit: [gold-freeze-1157](gold-freeze-1157.md) - a rhymed line is
not deleted unasked.
