#!/usr/bin/env python3
"""A LIVE burst that neither road carried must give its commitment back too.

`_speak_turns_floorless` ends each burst with:

    if ready_takes is not None and not (page_delivery or (to_box and played_ok)):
        _burst_withdraw(_entries, "neither the page nor the box took the clip")

The `ready_takes is not None` is deliberate and belongs to the FEED: a live
round's rows are handled elsewhere. The admission gate does not care which
kind of round it was. A committed occurrence that neither road carried is a
position held open for audio nobody heard, and with ordering enforced it
stands in front of every line behind it.

MEASURED, ten minutes after #1338-#1340 went live and the sfx lane was
enforced: one live burst - 20 lines, 137 s of audio, all 20 feed rows still
reading `prepared` - left standing `admitted` for thirteen minutes, and
every one of the 24 out-of-order refusals in that window named it.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_burst_live_withdraw_patch.py --check
    python tools/_burst_live_withdraw_patch.py
    python tools/_burst_live_withdraw_patch.py --revert

REQUIRES `_admission_reach_patch.py` (admission_withdraw) and
`_burst_withdraw_admission_patch.py` (`_round_occurrence`).

It changes NOTHING about the feed: the withdrawal below it keeps its own
condition, and this only takes back the commitment.

Not covered here, and named rather than papered over: an exception raised
between the admit and the transports leaves the occurrence standing until
the next restart, where `broadcast_admission.resume` withdraws it with
`STRANDED_WHY`. Wrapping the whole delivery in a try/finally is a bigger
change to the busiest function in the file than this evidence justifies.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1341"
NEEDS = ("def admission_withdraw(", "_round_occurrence")


ANCHOR = """                if ready_takes is not None and not (page_delivery or (to_box and played_ok)):
                    _burst_withdraw(_entries, "neither the page nor the box took the clip")   # 2026-09-14
"""

NEW = '''                # #1341: AND THE COMMITMENT COMES BACK ON A LIVE ROUND TOO.
                # The withdrawal below is limited to prepared rounds on
                # purpose - that is a rule about the FEED - but the gate
                # does not care which kind it was. Measured: one live burst
                # of 20 lines stood admitted for thirteen minutes with all
                # twenty of its feed rows still reading `prepared`, and
                # every out-of-order refusal in that window named it.
                if not (page_delivery or (to_box and played_ok)):
                    admission_withdraw(
                        _round_occurrence,
                        "neither the page nor the box took the clip")
                if ready_takes is not None and not (page_delivery or (to_box and played_ok)):
                    _burst_withdraw(_entries, "neither the page nor the box took the clip")   # 2026-09-14
'''


EDITS = [("a live burst gives its commitment back", ANCHOR, NEW)]


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

    for needed in NEEDS:
        if needed not in text:
            print(f"{needed} is not in app.py - apply the earlier admission "
                  "patches first", file=sys.stderr)
            return 1

    already = [name for name, _a, new in EDITS if new in text]
    if len(already) == len(EDITS):
        print("already applied; nothing to do")
        return 0

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
