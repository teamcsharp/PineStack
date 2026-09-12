---
name: answerable-orchestrator-asks
description: "#1181: the operator's answers land but are discarded - prefer vs drive, short-horizon roads, and a pin with no door"
metadata:
  type: project
---

**"I'm always telling the orchestrator this, but I never see the settings
take place."** The answers were NEVER the problem - check the policy book
first (`data/orchestrator_policy.json`, and the answered ask in
`data/orchestrator_asks.json` carries a `did` string per pick saying what
the station thought it applied). On 2026-09-11 all three picks were
there, stamped, confirmed. Four things downstream threw them away:

1. **`prefer:` is PROTECTION, `drive:` is BUILD ORDER.** Four of
   prefer_road's five readers keep a road off the postpone ladder
   (`slot_postpone`), exclude it from giving way, or refuse to convert it
   to ballast (`ballast_swap`). Only `slot_needs()` touches order. The
   ask "Should I build these ahead...?" fired `prefer:` and `orch_apply`
   replied "...is **protected** first". **When a question is about
   building, check which verb it emits.**
2. **Short-horizon roads cannot be stocked ahead and are not faulty for
   it.** `PREP_SHORT_HORIZON` (#1181) names them; today that is `news`
   alone. #925: "one bulletin at a time, never a backlog", and
   `shelf_full("news")` returns True whenever `news_want_seconds() <= 0`
   so the planner never picks work that would only refuse itself. News
   showing `held 0.0` against thousands owed is its RESTING STATE.
   Never read it as a shortage, and never ask the operator to fix it.
3. **`drive_road` outranks everything and had no door.** Set to
   `track_talk` and still pinned 5 h later; no ask emitted a `drive:`
   verb, and `orch_apply` is reachable only from `api_orch_asks_answer`
   (needs an OPEN ask). Clear it with
   `POST /api/orchestrator/policy {"does":"drive:none"}` (#1178).
   #1181 adds the handles: "No - keep the running order's order" now
   emits `drive:none`, and the six-hourly check asks about a standing
   pin FIRST.
4. **The drive only applied while paused** - the hoist sat inside
   `if radio_paused():` in `prep_plan`, carried along with #1130's
   shortfall re-sort. Now hoisted either way; the shortfall sort stays
   paused-only.

Read the live picture with `GET /api/orchestrator/logic` - it carries
`policy`, `order`, `roads` (owed/held/uncovered per road), `plan_why`,
`paused`. There is no `/api/orchestrator` or `/api/director/why`;
`/api/director/state` is the VOICE director, a different desk.

**#1182 - THE ROUTINE BANK, same two faults plus one.** "Which road would
you like more of?" also fired `prefer:` (build language, protection verb)
AND offered a FIXED THREE - banter and callers among them, the two
deepest shelves on the station. `orch_behind_roads()` now draws the
options from what is actually short, deepest first, minus CANNOT_PREPARE,
minus PREP_SHORT_HORIZON, minus anything not on **PREP_BOARD** (which has
no `banter` - the drive hoist can only reorder roads on the board, so
`drive:banter` would be another dead answer). "When a phone call is due
and none is prepared?" wrote the STATION-WIDE `when_empty`/`repeats_hard`
- reworded to say "on any road". And `random.sample(bank, 3)` drew three
of six whatever the hour looked like; each entry carries a `when` now and
the routine ask is not raised at all when nothing applies. Only the
ballast and tint dials are unconditional.

**Rule of thumb for any new ask:** the question's WORDS must match what
the verb writes, the verb's key must have a reader that changes
behaviour, and the question must only be raised when its answer would
change something now.

See [orchestrator-dead-wiring](orchestrator-dead-wiring.md) (ask "called / runs / changes
anything"), [which-pile-a-road-lives-on](which-pile-a-road-lives-on.md), [quota-outranks-the-sheet](quota-outranks-the-sheet.md).
