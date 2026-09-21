#!/usr/bin/env python3
"""A round the station refused is not on the air - and now the committed
sequence hears that too.

`_burst_withdraw`'s own docstring is the whole argument:

    "2026-09-14: A ROUND THE STATION REFUSED IS NOT ON THE AIR. ... So a
     refusal now WITHDRAWS its rows - state `withdrawn`, the reason on the
     row - and records the reason where the shelf's own verdict picks it
     up, so the station can say which it was instead of that it happened."

It withdraws them from the FEED.  The admission gate, which had been told
about the round a few lines earlier, was never told it had been refused.

Measured on this station 2026-09-21: 674 occurrences standing `admitted`
and never dispatched, every single one of them from
`_speak_turns_floorless`, the oldest at position 16 and four days old - and
together they were the whole of the gate's 2,584 out-of-order refusals.
Ordering could never have been enforced while they stood there.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_burst_withdraw_admission_patch.py --check
    python tools/_burst_withdraw_admission_patch.py
    python tools/_burst_withdraw_admission_patch.py --revert

REQUIRES `_admission_reach_patch.py`, which installs `admission_withdraw`.

TWO EDITS

  1. The admit call site keeps what it committed, and stamps it on every
     row of the round.  That id on the feed row is also the reference the
     script report was missing - the audit's "Motion records moving DOM
     indices and shortened IDs without document revision or playback
     occurrence".
  2. `_burst_withdraw` takes it back.  Withdrawal is a no-op once the
     occurrence has been dispatched, so a round that was refused AFTER it
     started going out keeps its honest record.

The other half of this - occurrences stranded by a restart rather than by
a refusal - is in `broadcast_admission.resume`, where a commitment left
standing by a player that no longer exists is withdrawn with
`STRANDED_WHY`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1340"
NEEDS = "def admission_withdraw("


ADMIT_ANCHOR = """                admission_admit_round(one, rows, length,
                                      producer="_speak_turns_floorless")
"""

ADMIT_NEW = '''                _round_occurrence = admission_admit_round(
                    one, rows, length, producer="_speak_turns_floorless")
                # #1340: AND ON EVERY ROW OF THE ROUND, so a refusal one
                # layer up can find what it has to take back - and so the
                # feed row, the booth and the incident capture can all name
                # the playback occurrence this line belongs to, which is
                # the reference the script report was missing.
                for _e4 in _entries:
                    try:
                        _e4["admission_occurrence"] = _round_occurrence
                    except Exception:  # noqa: BLE001
                        pass
'''


WITHDRAW_ANCHOR = """    n = 0
    sid = ""
    kind = ""
    for e in entries or []:
"""

WITHDRAW_NEW = '''    # #1340: THE COMMITTED SEQUENCE HEARS IT TOO.
    #
    # Everything below takes the round back out of the FEED. The admission
    # gate had been told about it a few lines before the hand-over and was
    # never told it had been refused, so it went on holding a position for
    # a round that was not coming - 674 of them when this was written, and
    # every out-of-order refusal on the station traced to one.
    #
    # The position stands and the script keeps the hole, marked, which is
    # exactly what this function does to the rows.
    try:
        _held = ""
        for e in entries or []:
            if isinstance(e, dict) and e.get("admission_occurrence"):
                _held = str(e["admission_occurrence"])
                break
        if _held:
            admission_withdraw(_held, why)
    except Exception:  # noqa: BLE001
        pass                    # a refusal is never worth an exception
    n = 0
    sid = ""
    kind = ""
    for e in entries or []:
'''


EDITS = [("the round keeps what it committed", ADMIT_ANCHOR, ADMIT_NEW),
         ("a refused round is withdrawn from the committed sequence",
          WITHDRAW_ANCHOR, WITHDRAW_NEW)]


def load(path: Path) -> str:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise SystemExit(f"{path} contains CRLF; this file is LF-only "
                         "and the patch refuses to normalise it silently")
    return raw.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify anchors, write nothing")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--file", default=TARGET)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"no {path}; run this from the repo root", file=sys.stderr)
        return 2
    text = load(path)

    if args.revert:
        out, undone = text, 0
        for name, anchor, new in EDITS:
            if new in out:
                out = out.replace(new, anchor, 1)
                undone += 1
                print(f"  reverted: {name}")
        if not undone:
            print("nothing to revert")
            return 0
        compile(out, str(path), "exec")
        path.write_bytes(out.encode("utf-8"))
        print(f"reverted {undone} edit(s) in {path}")
        return 0

    if NEEDS not in text:
        print("admission_withdraw is not in app.py - apply "
              "tools/_admission_reach_patch.py first", file=sys.stderr)
        return 1

    already = [name for name, _a, new in EDITS if new in text]
    if len(already) == len(EDITS):
        print("already applied; nothing to do")
        return 0
    if already:
        print("PARTIALLY applied - refusing to continue:", file=sys.stderr)
        for name in already:
            print(f"  present: {name}", file=sys.stderr)
        print("  run --revert first", file=sys.stderr)
        return 1

    trouble = []
    for name, anchor, _new in EDITS:
        found = text.count(anchor)
        print(f"  anchor {found}x  {name}")
        if found != 1:
            trouble.append(f"{name}: anchor found {found} times, expected 1")
    if trouble:
        print("ANCHORS DO NOT MATCH - app.py has moved under this patch:",
              file=sys.stderr)
        for line in trouble:
            print("  " + line, file=sys.stderr)
        return 1
    if args.check:
        print("all anchors matched exactly once; --check wrote nothing")
        return 0

    out = text
    for _name, anchor, new in EDITS:
        out = out.replace(anchor, new, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as exc:
        print(f"the patched file does not parse ({exc}); nothing written",
              file=sys.stderr)
        return 1
    path.write_bytes(out.encode("utf-8"))
    print(f"applied {len(EDITS)} edits to {path}")
    print("the container must be restarted for this to take effect; this "
          "script does not restart anything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
