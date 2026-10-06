#!/usr/bin/env python3
"""[pin-sampler] The folder pin reaches the sampler. 2026-10-06.

"That loaded up a video from the wrong directory." The pin promised "every sting and every endless
clip comes from bloodin", and the roll on the tube read "sampler - 4cht". Measured on the air log:
in the pinned hour 61 stings came from bloodin and 21 from ten other folders, the 4cht one among
them. The cause is one memo: the sampler's draw sets (_sting_draw_sets) are built from
_SFX_POOL_CACHE, the worker's walk of the whole library, filtered by bans and weights only - the
pin lives in sfx_all() (_sfx_pinned), which this road never calls. The draw sets now pass through
_sfx_pinned, and the pin prefix is part of the memo's signature, so a new pin recomputes them at
once. An empty pinned subset still falls back to everything - a pin never silences the station.

Usage:  sfx_pin_sampler_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_pin_sampler_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SIG_OLD = '''    sig = (_SFX_POOL_AT[0], len(_SFX_POOL_CACHE),
           _sfx_file_sig(SFX_BANS_PATH), _sfx_file_sig(SFX_WEIGHTS_PATH),
           _sfx_file_sig(SFX_GLUE_PATH))            # [#1243]
    if _STING_DRAW_MEMO.get("sig") == sig:
'''
SIG_NEW = '''    sig = (_SFX_POOL_AT[0], len(_SFX_POOL_CACHE),
           _sfx_file_sig(SFX_BANS_PATH), _sfx_file_sig(SFX_WEIGHTS_PATH),
           _sfx_file_sig(SFX_GLUE_PATH),            # [#1243]
           sfx_pin_prefix())                        # [pin-sampler] a new pin is a new pool
    if _STING_DRAW_MEMO.get("sig") == sig:
'''
POOL_OLD = '''    pool = [p for p in _SFX_POOL_CACHE if sfx_id(p) not in banned]
    if weights:
'''
POOL_NEW = '''    # [pin-sampler] the folder pin ("every sting ... comes from X") reaches this road too: the
    # memo is built from _SFX_POOL_CACHE, the walk of the whole library, and the pin lived only
    # in sfx_all(), so a pinned hour still drew stings from everywhere (61 of 82 pinned, measured).
    # _sfx_pinned keeps the pinned subset and falls back to everything when it is empty.
    pool = _sfx_pinned([p for p in _SFX_POOL_CACHE if sfx_id(p) not in banned])
    if weights:
'''
APP = [
    ("the pin is part of the draw sets' signature", SIG_OLD, SIG_NEW, "sfx_pin_prefix())                        # [pin-sampler] a new pin is a new pool", 1),
    ("the draw sets pass through the pin", POOL_OLD, POOL_NEW, "pool = _sfx_pinned([p for p in _SFX_POOL_CACHE if sfx_id(p) not in banned])", 1),
]
EDITS = {"app.py": APP}


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
            print("%-46s (not in this tree - skipped)" % name[-46:])
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
            print("%-46s %-48s %s" % (name[-46:], label, state))
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
        tmp = path.with_name(path.name + ".pinsampler.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
