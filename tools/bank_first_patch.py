#!/usr/bin/env python3
"""[bank-first] Bank first, everywhere it fits. 2026-10-06.

"Make sure there is nothing in the cupboard that sits there and gets no play."
The operator's answer to which door: "Bank first, everywhere it fits" - every
slot takes a banked round of its kind before live writing, and the out-of-turn
door opens to every road, banter and the gazette review included, in talk gaps.

Measured on the live station at 12:40 (the kitchen had been banking all
morning): 361 finished rounds never heard, 304 of them past the 2 h dial, the
oldest 23 h 53 m; the sweep had walked 36 times and aired NOTHING. Its own
reasons, read through /api/cupboard/unheard and the code:

  1. The pantry lifecycle (mode "air") owns the sweep's pick, and its
     `compatible()` admits a row only INSIDE its road's own entry. The sweep's
     own rule - past the dial, on an open road, go out of turn - had been
     silently replaced with "inside its entry only", so it answered "nothing
     unheard is past the dial and airable" while 304 rounds were.
  2. The out-of-turn list (RESCUE_ROADS_OPEN) shut gazette_review (50 rows)
     and banter; mixtape too. unheard_pick walked `shelf_rows(kind)`, and
     banter's rows live in the LARDER, so even an open banter road found none.
  3. A banter row the lifecycle DID pick went to the shelf door, which
     answered "the shelf would not give up the row that was picked" (7 times).
     The larder had no transport the sweep or the rescue could use.
  4. The running-order window for a gazette review slot answered "banter"
     (SCHED_PREP_KIND maps the slot to the banter writer), so a banked
     gazette_review round was never "in turn" even during its own slot, and
     the live slot wrote a fresh one every time.
  5. The mixtape intro (a tape every Nth record, not a scheduled slot) never
     looked at its shelf: 10 ready intros, 10 unheard.
  6. The dial: two hours before a finished round may go out of turn.

What changes:
  - RESCUE_ROADS_OPEN adds gazette_review and banter (not mixtape: its intro
    belongs to a tape that is on; not supercut_react: it answers one supercut).
  - unheard_pick walks road_source(kind), the one door that knows the larder.
  - larder_round_air(): banter's out-of-turn transport - the live road's own
    larder bookkeeping (aired, innings, retire-or-rest, save) then _banter_air.
    The sweep and the dead-air rescue use it; dead_air_stock counts banter.
  - unheard_out_of_turn(kind): the sweep passes rescue=True whenever the pick
    is outside its road's entry, lifecycle or not.
  - PantryLifecycle.out_of_turn(): the lifecycle's pick admits a never-aired
    row past the dial on an open road, outside its entry.
  - _ready_slot_window answers the slot's own kind when that is the kind asked.
  - dj_mixtape_intro takes a banked intro for this tape (one naming its title,
    else one naming no tape) through the shelf door; mixtape_pick prefers a tape
    that has one.
  - The gazette review wrapper takes a banked review of the current edition
    through the shelf door before writing.
  - CUPBOARD_UNHEARD_HOURS default 2 -> 0.25 (env PINE_UNHEARD_HOURS and the
    orchestrator's unheard_hours still win; the 120 s floor stands).

Usage:  bank_first_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        bank_first_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# ----------------------------------------------------------------- app.py
ROADS_OLD = '''RESCUE_ROADS_OPEN = ("manager", "gallery", "news", "caller",
                     "ad", "station_id")
'''
ROADS_NEW = '''RESCUE_ROADS_OPEN = ("manager", "gallery", "news", "caller",
                     "ad", "station_id",
                     # [bank-first] "nothing in the cupboard that sits there and gets no play": the
                     # gazette review and banter go out of turn too. Not mixtape - its intro belongs to
                     # the tape that is on - and not supercut_react, which answers one supercut.
                     "gazette_review", "banter")
'''

PICK_OLD = '''            for row in shelf_rows(kind):
                if not isinstance(row, dict) or not row_unaired(row):
                    continue
                age = now - float(row.get("at") or now)
                if age <= after or age <= best[2]:
                    continue
'''
PICK_NEW = '''            for row in road_source(kind):                      # [bank-first] the larder is banter's shelf
                if not isinstance(row, dict) or not row_unaired(row):
                    continue
                age = now - float(row.get("at") or now)
                if age <= after or age <= best[2]:
                    continue
'''

SWEEP_OLD = '''    if kind == "ad" and str(row.get("produced") or ""):
        said = await _unheard_until_handoff(
            _unheard_produced_ad_air(
                row, force=urgent, on_handoff=account_handoff), handed, row)
    else:
        said = await _unheard_until_handoff(
            _ready_shelf_air(
                kind, _RADIO.get("now"), rescue=not bool(_pantry_lifecycle() and _pantry_lifecycle().enabled), pick=row, force=urgent,
                on_handoff=account_handoff), handed, row)
'''
SWEEP_NEW = '''    if kind == "ad" and str(row.get("produced") or ""):
        said = await _unheard_until_handoff(
            _unheard_produced_ad_air(
                row, force=urgent, on_handoff=account_handoff), handed, row)
    elif kind == "banter":
        # [bank-first] the larder's own transport: a banter row handed to the shelf door was refused
        # ("the shelf would not give up the row that was picked") because its shelf is the larder.
        said = await _unheard_until_handoff(
            larder_round_air(row, _RADIO.get("now"), on_handoff=account_handoff), handed, row)
    else:
        said = await _unheard_until_handoff(
            _ready_shelf_air(
                kind, _RADIO.get("now"), rescue=unheard_out_of_turn(kind), pick=row, force=urgent,
                on_handoff=account_handoff), handed, row)
'''

SWEEP_DEF_OLD = '''async def unheard_stock_air(force: bool = False) -> str:
'''
SWEEP_DEF_NEW = '''def unheard_out_of_turn(kind: str) -> bool:
    """[bank-first] Is a round of this road going out OUTSIDE its own entry? Then it
    takes the rescue door (no running-order window), lifecycle or not.

    With the lifecycle on, the sweep passed rescue=False so a bound round would
    honour its occurrence - right inside the entry, wrong for the sweep's own
    out-of-turn pick, which the window then refused as "standing on somebody
    else's slot"."""
    lifecycle = _pantry_lifecycle()
    if not (lifecycle and lifecycle.enabled):
        return True
    try:
        window = _ready_slot_window(kind) or {}
        return str(window.get("kind") or "") != str(kind)
    except Exception:  # noqa: BLE001
        return True


def larder_oldest_ready() -> dict[str, Any] | None:
    """[bank-first] The longest-waiting never-aired banter round that can air now."""
    best, age, now = None, -1.0, time.time()
    for e in _LARDER:
        if not isinstance(e, dict) or id(e) in _READY_SHELF_BUSY or not row_unaired(e):
            continue
        if not dialogue_row_ready("banter", e):
            continue
        waited = now - float(e.get("at") or now)
        if waited > age:
            best, age = e, waited
    return best


async def larder_round_air(entry: dict[str, Any], track: dict[str, Any] | None = None,
                           on_handoff: Any = None) -> list[str]:
    """[bank-first] Put ONE banked banter round on the air out of turn.

    The live banter road serves off the larder with this bookkeeping (aired,
    innings, retire or rest at the end, save) and then _banter_air; the sweep
    and the dead-air rescue had no such door - banter is the road with the
    most material and the only one whose shelf is the larder."""
    try:
        at = next(i for i, e in enumerate(_LARDER) if e is entry)
    except StopIteration:
        return _banter_no("the larder round left the shelf before it could air")
    if not dialogue_row_ready("banter", entry):
        return _banter_no("the larder round is not ready to air")
    at, replay = larder_reair_gate(at)
    entry = _LARDER[at] if at >= 0 else None
    if not isinstance(entry, dict):
        return _banter_no("the re-air gate kept the larder round off")
    if replay:
        entry["_s3_replay"] = replay
    else:
        entry.pop("_s3_replay", None)
    entry["aired_at"] = time.time()
    entry["aired"] = int(entry.get("aired") or 0) + 1
    entry["used_by"] = stock_used_by()                                   # #1068
    entry["expires_at"] = stock_expires_at("banter", entry)
    if repeat_safe("banter", entry):
        if (int(entry["aired"]) < row_innings("banter", entry)
                or not retire_may("banter", entry,
                                  "its innings are used (%d airings)" % int(entry["aired"]))):
            _LARDER[:] = _LARDER[:at] + _LARDER[at + 1:] + [entry]
        else:
            _LARDER.pop(at)
    elif retire_may("banter", entry, "not safe to repeat: it names the hour it was made"):
        _LARDER.pop(at)
    else:
        _LARDER[:] = _LARDER[:at] + _LARDER[at + 1:] + [entry]
    try:
        _INVENTORY_PLAN["at"] = 0.0
        _COMMITS["at"] = 0.0
    except Exception:  # noqa: BLE001
        pass
    _larder_save()
    pipeline_log("air", "a banked banter round goes out of turn off the larder "
                        "(%d left) [bank-first]" % len(_LARDER))
    gap_round_flag("banked")                                             # #1022
    return await _banter_air(entry, track, on_handoff=on_handoff)


async def unheard_stock_air(force: bool = False) -> str:
'''

RESCUE_OLD = '''        try:
            said = await _ready_shelf_air(kind, _RADIO.get("now"),
                                          rescue=True)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", "the %s cupboard refused the rescue: %s"
'''
RESCUE_NEW = '''        try:
            if kind == "banter":                                   # [bank-first] the larder's transport
                _oldest = larder_oldest_ready()
                said = await larder_round_air(_oldest, _RADIO.get("now")) if _oldest else []
            else:
                said = await _ready_shelf_air(kind, _RADIO.get("now"),
                                              rescue=True)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", "the %s cupboard refused the rescue: %s"
'''

STOCK_OLD = '''            if rows and _ready_shelf_row(kind, rescue=True) is None:
                continue
'''
STOCK_NEW = '''            if rows and kind != "banter" and _ready_shelf_row(kind, rescue=True) is None:   # [bank-first]
                continue
'''

DIAL_OLD = '''CUPBOARD_UNHEARD_HOURS = float(os.getenv("PINE_UNHEARD_HOURS", "2"))
'''
DIAL_NEW = '''CUPBOARD_UNHEARD_HOURS = float(os.getenv("PINE_UNHEARD_HOURS", "0.25"))   # [bank-first] a quarter hour, was 2 h
'''

WINDOW_OLD = '''    road = str(SCHED_PREP_KIND.get(str(slot.get("kind") or ""))
               or slot.get("kind") or "")
    occurrence = str(pos.get("occurrence") or "") or "|".join(
'''
WINDOW_NEW = '''    _slot_kind = str(slot.get("kind") or "")
    # [bank-first] a shelf keyed by the slot's own kind (gazette_review) is in turn during that slot;
    # the prep map answered "banter" for it, so its banked rounds were never in turn anywhere.
    road = (_slot_kind if _slot_kind == str(kind)
            else str(SCHED_PREP_KIND.get(_slot_kind) or _slot_kind))
    occurrence = str(pos.get("occurrence") or "") or "|".join(
'''

TAPE_OLD = '''    seed = await speakbox_quote()
    aside = (
        (" Work these lines in WORD FOR WORD as your own while you gush, "
'''
TAPE_NEW = '''    _banked = mixtape_banked_intro(tape)                   # [bank-first] the kitchen's intro for this tape first
    if _banked is not None:
        try:
            _said = await _ready_shelf_air("mixtape", tape, rescue=True, pick=_banked)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("drop", "the mixtape shelf refused its banked intro: %s" % type(exc).__name__)
            _said = []
        if _said:
            return _said
    seed = await speakbox_quote()
    aside = (
        (" Work these lines in WORD FOR WORD as your own while you gush, "
'''

TAPEPICK_OLD = '''    ready = [p for p in tapes if tape_ready(p)]
    pool = ready or tapes
'''
TAPEPICK_NEW = '''    ready = [p for p in tapes if tape_ready(p)]
    pool = ready or tapes
    try:                                                     # [bank-first] a tape with a banked intro goes first
        _with_intro = [p for p in pool if mixtape_banked_intro({"title": mixtape_title(p)}) is not None]
        if _with_intro:
            pool = _with_intro
    except Exception:  # noqa: BLE001
        pass
'''

TAPEDEF_OLD = '''def mixtape_pick() -> dict[str, Any] | None:
'''
TAPEDEF_NEW = '''def mixtape_banked_intro(tape: dict[str, Any] | None) -> dict[str, Any] | None:
    """[bank-first] A finished mixtape round on the shelf that fits this tape: one
    whose script names its title, else one that names no tape at all; oldest
    first. The intro is written around the title ("It is {title} and it goes on
    RIGHT NOW"), so a banked intro for another tape must not be read over this
    one."""
    title = str((tape or {}).get("title") or "")
    named: list[dict[str, Any]] = []
    plain: list[dict[str, Any]] = []
    for row in road_source("mixtape"):
        if not isinstance(row, dict) or id(row) in _READY_SHELF_BUSY or not row_unaired(row):
            continue
        if not dialogue_row_ready("mixtape", row):
            continue
        script = str((dialogue_entry(row) or {}).get("script") or "")
        if title and title in script:
            named.append(row)
        elif "MX tape" not in script:
            plain.append(row)
    pool = named or plain
    return min(pool, key=lambda r: float(r.get("at") or 0)) if pool else None


def mixtape_pick() -> dict[str, Any] | None:
'''

# ----------------------------------------------------------------- pantry_lifecycle.py
LIFE_PICK_OLD = '''                    or not self.call("dialogue_row_ready",kind,row,default=False) or not self.compatible(kind,row)):
                continue
'''
LIFE_PICK_NEW = '''                    or not self.call("dialogue_row_ready",kind,row,default=False)
                    or not (self.compatible(kind,row) or self.out_of_turn(kind,row))):   # [bank-first]
                continue
'''
LIFE_DEF_OLD = '''    def pick(self):
        now = self.clock(); pool = []
'''
LIFE_DEF_NEW = '''    def out_of_turn(self, kind, row):
        """[bank-first] A never-aired round past the cupboard's dial may go out OUTSIDE its entry on any
        road the station opens out of turn (RESCUE_ROADS_OPEN) - the sweep's own rule, which this pick
        had replaced with "inside its entry only": 304 overdue rounds stood while it answered
        "nothing unheard is past the dial and airable"."""
        try:
            if kind not in (self.host.get("RESCUE_ROADS_OPEN") or ()) or self.evergreen(row): return False
            if int(row.get("aired") or 0) > 0 or float(row.get("aired_at") or 0) > 0: return False
            after = float(self.call("cupboard_unheard_after", default=7200) or 7200)
            now = self.clock()
            if now - float(row.get("at") or entry_of(row).get("at") or now) <= after: return False
            return self.deadline(kind, row) > now + 30
        except Exception:
            return False
    def pick(self):
        now = self.clock(); pool = []
'''

# ----------------------------------------------------------------- gazette_review_runtime.py
GAZ_DOOR_OLD = '''            receipt = await asyncio.to_thread(runtime.receipt, occurrence)
            if not receipt:
                return []
            angle = str(kw.get("angle") or "")
'''
GAZ_DOOR_NEW = '''            receipt = await asyncio.to_thread(runtime.receipt, occurrence)
            if not receipt:
                return []
            if not kw.get("bank"):                      # [bank-first] the kitchen's review of this edition first
                banked = runtime.banked(receipt)
                door = g.get("_ready_shelf_air")
                if banked is not None and door is not None:
                    try:
                        said = await door(gazette_review.KIND, (g.get("_RADIO") or {}).get("now"), pick=banked)
                    except Exception:  # noqa: BLE001
                        said = []
                    if said:
                        return said
            angle = str(kw.get("angle") or "")
'''
GAZ_DEF_OLD = '''    async def cast(self, receipt, kw):
'''
GAZ_DEF_NEW = '''    def banked(self, receipt):
        """[bank-first] A finished review round on the shelf written for this edition, oldest first."""
        edition = str((receipt or {}).get("edition") or "")
        ready = self.g.get("dialogue_row_ready")
        busy = self.g.get("_READY_SHELF_BUSY") or set()
        best = None
        for row in list((self.g.get("_SHELF") or {}).get(gazette_review.KIND) or []):
            if not isinstance(row, dict) or id(row) in busy or row.get("aired_at") or int(row.get("aired") or 0):
                continue
            entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
            if str(((entry.get("gazette_review") or {}).get("edition")) or "") != edition:
                continue
            if callable(ready) and not ready(gazette_review.KIND, row):
                continue
            if best is None or float(row.get("at") or 0) < float(best.get("at") or 0):
                best = row
        return best

    async def cast(self, receipt, kw):
'''

EDITS = {
    "app.py": [
        ("the out-of-turn door opens to the gazette review and banter", ROADS_OLD, ROADS_NEW, 1),
        ("unheard_pick walks the larder through road_source", PICK_OLD, PICK_NEW, 1),
        ("the sweep's banter transport and the out-of-turn rescue flag", SWEEP_OLD, SWEEP_NEW, 1),
        ("unheard_out_of_turn, larder_oldest_ready, larder_round_air", SWEEP_DEF_OLD, SWEEP_DEF_NEW, 1),
        ("the dead-air rescue airs banter off the larder", RESCUE_OLD, RESCUE_NEW, 1),
        ("dead_air_stock counts banter", STOCK_OLD, STOCK_NEW, 1),
        ("the dial: a quarter hour", DIAL_OLD, DIAL_NEW, 1),
        ("the slot window answers the slot's own kind", WINDOW_OLD, WINDOW_NEW, 1),
        ("mixtape_banked_intro", TAPEDEF_OLD, TAPEDEF_NEW, 1),
        ("the mixtape intro takes its banked round first", TAPE_OLD, TAPE_NEW, 1),
        ("mixtape_pick prefers a tape with a banked intro", TAPEPICK_OLD, TAPEPICK_NEW, 1),
    ],
    "pantry_lifecycle.py": [
        ("the lifecycle's pick admits an out-of-turn row", LIFE_PICK_OLD, LIFE_PICK_NEW, 1),
        ("PantryLifecycle.out_of_turn", LIFE_DEF_OLD, LIFE_DEF_NEW, 1),
    ],
    "gazette_review_runtime.py": [
        ("the gazette review slot takes its banked round first", GAZ_DOOR_OLD, GAZ_DOOR_NEW, 1),
        ("GazetteReview.banked", GAZ_DEF_OLD, GAZ_DEF_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".bankfirst.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
