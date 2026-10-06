#!/usr/bin/env python3
"""[sfx-sync] The squeezed clip's sound arrives WITH its picture. 2026-10-06.

"Make sure that the audio is set correct right before the video begins playing. I'm having videos
 come in and they're before the audio before it comes on."

[sfx-even] (tonight) streamed a peak-held clip through loudnorm's dynamic mode. That filter looks
three seconds ahead, and in a live stream that is three seconds of silence under the picture
before the sound arrives. The squeezed road is now the full wanted gain into the limiter, which is
what the limiter is for (the #1477 rule: the peak is held by a LIMITER, not by refusing the boost):
no lookahead beyond the limiter's 5 ms, sound and picture together from the first frame.

Usage:  sfx_squeeze_sync_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_squeeze_sync_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

OLD = '''    if squeeze > 0 and held >= squeeze:
        return "loudnorm=I=%.1f:TP=%.1f:LRA=11" % (max(-70.0, min(-5.0, target)), max(-9.0, min(0.0, ceiling))), "squeezed"
'''
NEW = '''    if squeeze > 0 and held >= squeeze:
        # [sfx-sync] the FULL wanted gain into the limiter - never loudnorm's dynamic mode, whose three
        # seconds of lookahead put the sound three seconds behind the picture on a live stream
        want_db = max(-30.0, min(24.0, target - float(level)))
        return "volume=%.2fdB,alimiter=limit=%.4f:attack=5:release=120:level=disabled" % (want_db, max(0.0625, min(1.0, limit))), "squeezed"
'''
TEST_OLD = '''        chain, how = self.ns["sfx_gain_chain"](db, {"i": -30.0, "tp": -3.0})
        self.assertEqual(how, "squeezed")
        self.assertEqual(chain, "loudnorm=I=-16.0:TP=-6.0:LRA=11")
'''
TEST_NEW = '''        chain, how = self.ns["sfx_gain_chain"](db, {"i": -30.0, "tp": -3.0})
        self.assertEqual(how, "squeezed")
        self.assertEqual(chain, "volume=14.00dB,alimiter=limit=0.4467:attack=5:release=120:level=disabled", "[sfx-sync] the full lift, the limiter holds the bangs; no lookahead")
'''
TEST2_OLD = '''        chain, how = self.ns["sfx_gain_chain"](0.0, {"i": -30.0, "tp": -3.0})
        self.assertEqual((how, chain), ("squeezed", "loudnorm=I=-11.9:TP=-1.9:LRA=11"))
'''
TEST2_NEW = '''        chain, how = self.ns["sfx_gain_chain"](0.0, {"i": -30.0, "tp": -3.0})
        self.assertEqual((how, chain), ("squeezed", "volume=18.08dB,alimiter=limit=0.7147:attack=5:release=120:level=disabled"))
'''
TEST3_OLD = '''        self.assertEqual(cmd[cmd.index("-af") + 1], "loudnorm=I=-16.0:TP=-6.0:LRA=11")
'''
TEST3_NEW = '''        self.assertEqual(cmd[cmd.index("-af") + 1], "volume=14.00dB,alimiter=limit=0.4467:attack=5:release=120:level=disabled")
'''
EDITS = {
    "app.py": [("the squeezed road is gain into the limiter", OLD, NEW, "[sfx-sync] the FULL wanted gain into the limiter", 1)],
    "tests/test_sfx_even_2026_10_05.py": [
        ("the test expects the limiter chain", TEST_OLD, TEST_NEW, "[sfx-sync] the full lift, the limiter holds the bangs; no lookahead", 1),
        ("with the box shift too", TEST2_OLD, TEST2_NEW, '"volume=18.08dB,alimiter=limit=0.7147:attack=5:release=120:level=disabled"', 1),
        ("and in the command", TEST3_OLD, TEST3_NEW, 'cmd[cmd.index("-af") + 1], "volume=14.00dB,alimiter=limit=0.4467:attack=5:release=120:level=disabled"', 1),
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
            print("%-40s (not in this tree - skipped)" % name)
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-40s %-46s %s" % (name, label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".sfxsync.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
