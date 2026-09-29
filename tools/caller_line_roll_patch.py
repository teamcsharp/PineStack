#!/usr/bin/env python3
"""[s3-line-no] The caller's line number is a roll off a System 3 table.

"Keep 'name the line: line N', but N must come from a roulette roll - a random
line number drawn on a System 3 table and recorded - not a fixed id"
(operator, 2026-09-29).

Before: call_line_no() = 1 + int(s3_roll("call.line_number") * 98837) - a
recorded number, but its range was a constant no one could edit.

After:
  * POOLS1 `call.line_number` is the switchboard: rows are bands ("1-9",
    "10-99", "100-999", "1000-9999", "10000-98837") or single numbers ("42").
    Tabled the first time a call rings; add a number, re-weight a band or
    switch one off in the Tables editor. System 3 picks the row (a recorded
    pick, "band 3 of 5"), then rolls the number inside it (call.line_in_band,
    a recorded roll). Both are the round's first events (the dice door's rolls
    are absorbed into the call's conversation when it is planned), so why_line
    and the Rolodex show them. The prompt still says "NAME THE LINE: line N".
  * A PREPARED call's air card and its call_ended record now say the line the
    call was WRITTEN on (entry["call"]["line"]) instead of rolling a new number
    that did not match what the host said.
  * The answer-the-line turn's example greeting is rolled off POOLS1
    `call.answer_example` (editable), and the writer is told to answer in its
    own words - under the 24-hour rule one fixed greeting could air once a day.

    python3 tools/caller_line_roll_patch.py --check | --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_patchlib import Edit, run  # noqa: E402

A = "app.py"

# The old call_line_no is system3_dice_patch's text and stays as it is: the
# table's call_line_no is defined after it (the name is looked up per call) and
# falls back to it if the table ever fails.
LINENO_ANCHOR = "def call_line_say(number: int) -> str:\n"
LINENO_NEW = '''# [s3-line-no] THE SWITCHBOARD IS A TABLE. Its rows are bands ("a-b") or single
# numbers ("n"); POOLS1 call.line_number, tabled the first time a call rings,
# weighted and switchable on the desk. One recorded pick chooses the row, one
# recorded roll the number inside it.
_call_line_no_flat = call_line_no
CALL_LINE_BANDS = ("1-9", "10-99", "100-999", "1000-9999", "10000-%d" % CALL_LINES)
CALL_LINE_LABEL = "which switchboard band (or number) a caller rings in on - add a number, weight a band"
_CALL_LINE_LAST: dict[str, Any] = {}


def _call_band(row: Any) -> tuple[int, int]:
    """A desk row as a range: "a-b", "n", or anything else -> the whole board."""
    try:
        s = "".join(str(row or "").replace(",", "").split())
        if "-" in s:
            a, b = s.split("-", 1)
            lo, hi = int(a), int(b)
        else:
            lo = hi = int(s)
        lo, hi = max(1, min(lo, hi)), max(1, max(lo, hi))
        return lo, hi
    except (TypeError, ValueError):
        return 1, CALL_LINES


def call_line_no() -> int:
    """Which line this caller came in on: a row of the switchboard table
    (call.line_number, a recorded pick), then the number inside it
    (call.line_in_band, a recorded roll). [s3-line-no]"""
    try:
        rows = s3_pool("call.line_number", CALL_LINE_BANDS, CALL_LINE_LABEL) or list(CALL_LINE_BANDS)
        k = _S3Dice("call.line_number", CALL_LINE_LABEL).pick("call.line_number", rows)
        row = rows[k if 0 <= k < len(rows) else 0]
        lo, hi = _call_band(row)
        u = s3_roll("call.line_in_band", "which line inside the switchboard band the caller is on")
        n = lo + min(hi - lo, int(float(u) * (hi - lo + 1)))
        _CALL_LINE_LAST.clear()
        _CALL_LINE_LAST.update(n=n, row=str(row), at=round(time.time(), 3),
                               band=_s3_spin_roll("call.line_number"), inside=_s3_spin_roll("call.line_in_band"))
        return n
    except Exception:  # noqa: BLE001 - the phone still rings
        return _call_line_no_flat()


def _prep_line_said(call: Any) -> str:
    """[s3-line-no] The line a PREPARED call was written on (its host names it
    in the recording), else a fresh roll."""
    got = str((call or {}).get("line") or "") if isinstance(call, dict) else ""
    return got or call_line_say(call_line_no())


'''

CARD_ANCHOR = '''                         "text": f"On {call_line_say(call_line_no())}: "
                                 f"{_prep_who}"
'''
CARD_NEW = '''                         "text": f"On {_prep_line_said(_prep_meta)}: "   # [s3-line-no:card]
                                 f"{_prep_who}"
'''

ENDED_ANCHOR = '''                               call_line_say(call_line_no()), _prep_began,
'''
ENDED_NEW = '''                               _prep_line_said(_prep_entry.get("call")), _prep_began,   # [s3-line-no:ended]
'''

ANSWER_ANCHOR = '''    out.append(" 1  A  - ANSWER THE RINGING LINE. Say the word \\"line\\" or "
               "\\"call\\" out loud - \\"the request line is ringing, you're "
               "live, go ahead\\". You do NOT know who this is: do not say "
               "any name.")
'''
ANSWER_NEW = '''    # [s3-line-no:answer] the example greeting is a roll off the desk
    # (call.answer_example) and the host answers in their own words - one
    # fixed greeting said word for word could air only once a day.
    try:
        _ans = s3_choice("call.answer_example", (
            "the request line is ringing, you're live, go ahead",
            "we've got a line lit up - you're on the air",
            "phones are going, you're live on the request line",
            "caller, you're on, talk to me",
            "line's open and you're live - go",
            "the board's lit up, you're on the air, speak up",
        ), "the example greeting a host is shown for answering the request line (said in their own words)")
    except Exception:  # noqa: BLE001
        _ans = "the request line is ringing, you're live, go ahead"
    out.append(" 1  A  - ANSWER THE RINGING LINE. Say the word \\"line\\" or "
               "\\"call\\" out loud, in your own words - something like \\"%s\\". "
               "You do NOT know who this is: do not say any name." % _ans)
'''

EDITS = [
    Edit("call_line_no table", A, LINENO_ANCHOR, LINENO_NEW, "[s3-line-no] THE SWITCHBOARD IS A TABLE", "before"),
    Edit("prepared card", A, CARD_ANCHOR, CARD_NEW, "[s3-line-no:card]", "replace"),
    Edit("prepared ended", A, ENDED_ANCHOR, ENDED_NEW, "[s3-line-no:ended]", "replace"),
    Edit("answer example", A, ANSWER_ANCHOR, ANSWER_NEW, "[s3-line-no:answer]", "replace"),
]

if __name__ == "__main__":
    sys.exit(run("caller_line_roll_patch", EDITS))
