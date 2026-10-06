#!/usr/bin/env python3
"""[unstick-all] "Unstick it now" releases the page, the floor and all four rooms. 2026-10-05, #1578.

The operator: "when i choose to unstick the station, It needs to be able to
untick all 4 rooms and release any and all locked items to unlock the
broadcast." The card's button ran one cure - the page's feed reset - which is
the cure for a page that has stopped playing, and the card it sits on says
"the dialogue is not reaching the air", which is a different fault: rows
locked in the rooms. The button then read "could not reach the station".

What this changes in app.py:
  - a new rung, "unstick" (BROADCAST_STEPS + broadcast_step, so the console,
    the orchestrator's command line and the ladder can all press it): the
    page's feed reset (bounded), the floor taken back, every `preparing` /
    `tinting` lock on a larder or shelf row released (the writing desk and
    the recording room), the recovery queue's held rounds sent back to their
    shelves (the reserve), and every cupboard hand-over, refused-row rest and
    road rest forgotten (the pantry). It says what it released, room by room.
  - POST /api/broadcast/unwedge runs that rung, answers with a short `say`
    the card can show, and never waits more than a few seconds on the health
    read behind it.

Usage:  unstick_all_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        unstick_all_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

STEP_OLD = r'''    {"key": "floor", "label": "Take the floor back",
'''
STEP_NEW = r'''    {"key": "unstick", "label": "Unstick everything",            # [unstick-all] #1578
     "say": "The page, the floor and all four rooms at once: resets the feed "
            "the page is stuck on, takes the floor back, releases every row a "
            "writer, a tint or a recording locked and never gave back, sends "
            "held recovery drafts back to their shelves, and forgets every "
            "cupboard hand-over and road rest still waiting.", "tone": "do"},
    {"key": "floor", "label": "Take the floor back",
'''

BRANCH_OLD = r'''    elif step == "floor":
        # #1331: TAKE THE FLOOR BACK.
'''
BRANCH_NEW = r'''    elif step == "unstick":
        # [unstick-all] THE PAGE, THE FLOOR AND ALL FOUR ROOMS (#1578).
        #
        # "when i choose to unstick the station, It needs to be able to untick
        # all 4 rooms and release any and all locked items to unlock the
        # broadcast." The card's button ran the page's cure alone, under a card
        # that says the dialogue is not reaching the air - which is rows locked
        # in the rooms, not a page that stopped playing. Every lock a row can
        # carry is released here, and each room says what it gave back.
        said.append("$ unstick the station: the page, the floor, all four rooms")
        _released = 0
        try:
            _got = await asyncio.wait_for(page_wedge_clear(force=True), 8.0)
            said.append("  page       %s" % (str((_got or {}).get("say") or "the feed was reset")[:150]))
            changed = True
        except asyncio.TimeoutError:
            said.append("  page       the feed reset did not answer in 8s - left to finish on its own")
        except Exception as err:  # noqa: BLE001
            said.append("  page       not reset (%s)" % type(err).__name__)
        try:
            if _floor_break("the operator unstuck the station"):
                changed = True
                _released += 1
                said.append("  floor      taken back from %s"
                            % (str(_FLOOR_OWNER.get("label") or "a round")[:80]))
            else:
                said.append("  floor      not held")
        except Exception as err:  # noqa: BLE001
            said.append("  floor      would not break (%s)" % type(err).__name__)
        _n_prep = _n_tint = 0
        try:
            for _row in list(_LARDER) + [r for _rows in list(_SHELF.values()) for r in list(_rows)]:
                for _holder in (_row, dialogue_entry(_row)):
                    if not isinstance(_holder, dict):
                        continue
                    if _holder.pop("preparing", None):
                        _n_prep += 1
                    if _holder.pop("tinting", None):
                        _n_tint += 1
        except Exception as err:  # noqa: BLE001
            said.append("  rooms      the shelves could not be walked (%s)" % type(err).__name__)
        said.append("  writing    %d row(s) released from a rewrite that never gave them back" % _n_tint)
        said.append("  recording  %d row(s) released from a recording that never gave them back" % _n_prep)
        _queued = len(_DIALOGUE_RECOVERY)
        if _queued and s3_flow_is_open():
            asyncio.create_task(dialogue_recovery_release(), name="radio:unstick-release")
            said.append("  reserve    %d held round(s) are going back to their shelves" % _queued)
        elif _queued:
            said.append("  reserve    %d round(s) are held for recovery and flow is closed "
                        "(speech gate flow.open) - left held" % _queued)
        else:
            said.append("  reserve    nothing is held for recovery")
        _n_hand = len(_UNHEARD_PENDING_HANDOFFS)
        _n_rest = len(_UNHEARD_REFUSED) + len(_UNHEARD_ROAD_OUT)
        _UNHEARD_PENDING_HANDOFFS.clear()
        _UNHEARD_REFUSED.clear()
        _UNHEARD_ROAD_OUT.clear()
        _UNHEARD_AT[0] = 0.0
        said.append("  pantry     %d hand-over(s) forgotten, %d refused row(s) and road(s) back in the rescue"
                    % (_n_hand, _n_rest))
        _released += _n_prep + _n_tint + _n_hand + _n_rest + _queued
        if _n_prep or _n_tint or _n_hand or _n_rest or _queued:
            changed = True
            try:
                _UNHEARD_MEMO.update(at=0.0, value=None)
                _INVENTORY_PLAN["at"] = 0.0
                _COMMITS["at"] = 0.0
                _larder_save()
                _pantry_save(True)
            except Exception:  # noqa: BLE001
                pass
        _UNSTICK_LAST.update(at=time.time(), released=_released, lines=list(said))
        said.append("  %d lock(s) released in all" % _released)

    elif step == "floor":
        # #1331: TAKE THE FLOOR BACK.
'''

STATE_OLD = r'''BROADCAST_STEPS: list[dict[str, str]] = [
'''
STATE_NEW = r'''_UNSTICK_LAST: dict[str, Any] = {"at": 0.0, "released": 0, "lines": []}     # [unstick-all]
BROADCAST_STEPS: list[dict[str, str]] = [
'''

ROUTE_OLD = r'''    require_auth(authorization)
    got = await page_wedge_clear(force=True)
    note_action("you asked the station to unstick the broadcast")
    return {**got, "health": (await api_broadcast_health(authorization))}
'''
ROUTE_NEW = r'''    require_auth(authorization)
    # [unstick-all] the page, the floor and all four rooms (#1578) - one rung,
    # and a `say` short enough for the card's button. The health read behind
    # it is bounded: this button once read "could not reach the station".
    got = await broadcast_step("unstick")
    note_action("you asked the station to unstick the broadcast")
    try:
        health = await asyncio.wait_for(api_broadcast_health(authorization), 4.0)
    except Exception:  # noqa: BLE001
        health = {}
    return {**got, "say": "unstuck - %d lock(s) released" % int(_UNSTICK_LAST.get("released") or 0),
            "health": health}
'''

EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [
        ("the rung's last report", STATE_OLD, STATE_NEW, "_UNSTICK_LAST: dict[str, Any] = {", 1),
        ("the rung on the ladder", STEP_OLD, STEP_NEW, '{"key": "unstick", "label": "Unstick everything",', 1),
        ("the rung itself", BRANCH_OLD, BRANCH_NEW, '    elif step == "unstick":', 1),
        ("the button runs the rung", ROUTE_OLD, ROUTE_NEW, 'got = await broadcast_step("unstick")', 1),
    ],
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise SystemExit("%s has bare carriage returns; refusing to guess" % path)
    return text, crlf


def _state(text: str, edit: tuple[str, str, str, str, int]) -> str:
    _name, old, _new, probe, count = edit
    have = text.count(probe)
    if have == count:
        return "applied"
    if have:
        return "partial (%d of %d probes)" % (have, count)
    found = text.count(old)
    return "ready" if found == count else "missing (anchor found %d, expected %d)" % (found, count)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    apply = argv[1] == "--apply"
    any_ready, any_missing = False, False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            state = _state(text, edit)
            print("%-10s %-28s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                any_ready = True
            elif state != "applied":
                any_missing = True
        plans.append((path, text, crlf, todo))
    if any_missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not any_ready:
        print("already applied")
        return 2
    if not apply:
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        if not todo:
            continue
        for _name, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _name)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _name, "probe")
        out = text.replace("\n", "\r\n") if crlf else text
        tmp = path.with_name(path.name + ".unstick.tmp")
        tmp.write_bytes(out.encode("utf-8"))
        os.replace(tmp, path)
        print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
