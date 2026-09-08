# The retirement desk (2026-09-08)

The operator's rule, the evening of 2026-09-08:

> Whenever rhyming rhetoric as a result of our tinting is pending deletion or is being set up for
> deletion, I want Pinebox to show me a notification so I can go in and approve it. So basically all
> the files that we are deleting from the cupboard, I want approval to choose whether or not they are
> getting removed. I want to be able to check by default whether or not they are removed and I want to
> be able to set the rules for objects of that type and how they are handled and how long they remain
> along with seeing timers for each and every item indicating how long its life is.

## 1. One gate on every deletion road

Every road that lets go of a cupboard item now asks `retire_may(kind, row, why)` first:

| road | why the desk is told |
|---|---|
| the larder keeper's prune (every 3 s) and the restore from disk | *past the larder's freshness (90 min) at N min* / *the contract moved (cast, crystal or plot act)* – one rule, `larder_prune_why` |
| `larder_trim` (both appends and the restore) | *the larder is over its cap of N* / *the repertoire is over its 80-row ceiling* |
| the burn on take | *its innings are used (N airings)* / *not safe to repeat: it names the hour it was made* |
| `shelf_take`'s burnt skip, the failed-take rebind, the shelf burn sweep, `alt_shelf_trim` | through `resort_may_drop(kind, row, keep, why)` – *past the 24-hour burn horizon on the shelf*, *shed after a failed take*, *the shelf burn sweep*, *the shelf is over its cap* |

The desk's answer: **yes** when the kind's rule does not ask, or the operator said remove; **no** while
the operator has not answered, or said keep and the extended life is still running. A row the desk keeps
stays exactly where it was (an aired, un-repeatable round rests at the end of the larder and is never
offered while it waits). Each store keeps a hard ceiling – twice the larder's cap plus the repertoire,
twice a shelf's cap – so an unanswered desk cannot grow a store without end; a removal the ceiling
forced is written down as *forced*.

## 2. The rules by type

Per kind (`data/retire_rules.json`, edited on the desk): **ask** – *rhymed items only* (the default),
*everything*, or *never* (delete as before; the default for news and station IDs); **keep hours** – how
long a rhymed item of that kind lives (96 by default; 0 for news, which dies with its stories) – this is
now the span `tinted_keep_until` stamps; **airings** – the innings a kept item gets (12 by default).
The fixed clocks underneath (plain rows' 90 min / 24 h / 72 h, the 3-hour rest, callers' re-air window)
are shown beside each rule so the type's whole handling is readable in one row.

## 3. The decisions

- **Remove**: the item leaves its store this instant (larder or shelf) and the decision is remembered –
  a row that came back by another road would go without asking again.
- **Keep** (+24 h, +the rule's hours, +7 d): `keep_until` is extended, and an item past its innings is
  handed a fresh set (`innings_extra`), so it is offered again after its rest. When the extension lapses
  the desk asks again, as a new arrival.
- Bulk: *Remove all waiting* / *Keep all waiting*.
- An item that left by another road while waiting (aired out, purged) is marked *gone* and drops off
  the queue.

## 4. Where the notification shows

- **Pine Box** (desktop): a card at bottom-left – *N rounds wait for your decision before leaving the
  cupboard* – with *Open the desk* (an app window on `/cupboard/retire`, added to main.js's same-origin
  carve-out) and a standing badge *⏳ Retirement desk (N)* while anything waits.
- **The panel**: the ⏳ tray button carries the count (from `/api/dj` → `dialogue_flow.retire`) and opens
  the desk on its own tab.
- **The LCD**: the paused cupboard page counts the waiting rounds in its title and marks each one; the
  idle line on the dialogue page says *N rounds wait for your decision at the retirement desk*.
- **The action log**: a line at most every five minutes while something waits.

## 5. The timers

Every item carries `life_left` – seconds until it stops being offered (its keep if rhymed, else its
stock clock), counting down live on the desk page; the cupboard state (`/api/cupboard`, the LCD paused
page) shows *⏳ 71h 12m · 1/12 airings* on every round. The desk's inventory tab lists every larder
entry and shelf row with type, stage, airings, rest left, age, life, keep-until and decision, filterable
to rhymed / waiting / aired, with *Remove now* and *Keep* on each.

## 6. The wipe of 13:54 CST, and the road the desk had missed

At 13:41 the repertoire held 22 rhymed, aired, resting banter rounds. At 13:54:47 the larder was
written to disk with **zero** rows, and the desk's ledger had never been written – so the rows never
reached the desk **[V]**. The road was `dialogue_row_viable`: a round whose *writing contract* no longer
matches – and the contract (`_larder_profile_signature`) carries the crystal **and the plot's act**
(#862, #907) – is "not viable", and both larder append sites rebound the larder to viable rows only,
silently. Every act rolling over deleted the whole rhymed larder **[V by code; the 13:54 moment I]**.

Fixed the same evening: a rhymed round inside its keep **is current** (`_larder_current` returns
True for it – its world is in its words already; the desk decides when it goes); both append sites go
through `larder_rebind_viable`, which asks the desk about every row that is not viable (why: *off
brief*, *the contract moved*, *struck out*, *no script*) and logs what went; a row waiting on the desk
holds its clips in the pantry; **Keep** on a row whose contract moved re-binds it to today's
contract; the desk's inventory shows *· the contract moved* on the stage; the restore logs how many
rounds came back and how many were let go. The 22 rounds of 13:54 are gone – their clips may still be
in the pantry for a day, but nothing points at them.

## 7. Endpoints and files

- `GET /cupboard/retire` – the desk (authenticates itself; `?key=` when autofill is off).
- `GET /api/retire` – everything; `?summary=1` – `{pending, seq, newest_at, rhymed}`.
- `POST /api/retire/decide` – `{ids: [...], action: "remove"|"keep", extend_hours}`.
- `POST /api/retire/rules` – `{kind, ask, keep_hours, innings}`.
- `data/retire_ledger.json` (pending and the last 240 decisions), `data/retire_rules.json`.
- Pinned by `tests/test_retire_desk_2026_09_08.py` (11 tests) and the LCD agent tests.
