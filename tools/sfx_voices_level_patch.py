#!/usr/bin/env python3
"""[sfx-voices] Clips with a picture arrive at the voices' level. 2026-10-06.

"The videos are still coming in with an inconsistent level." Measured, not guessed:
  - the DJ renders in voice_media: median -13.5 LUFS, 22 files within 3.8 LU;
  - the SFX guy's sting slices: median -12.4 LUFS, within 3.7 LU;
  - the clips with a picture, fetched through the gain road as the page fetches them:
    median -17.8 LUFS, within 3.4 LU - each road is level with itself, and the clips sit
    four to five dB UNDER the voices. A -6 dBTP ceiling (SFX_TP_DB) caps the lift at
    ceiling - true peak + 1.5, and speech-shaped clips with a 12-16 dB crest cannot reach
    -16 under it, let alone the voices' -13.5 (loudnorm TP -1.5).
Two changes. The target becomes -14 LUFS and the ceiling -2 dBTP, the voices' own headroom.
And the gain is computed when the clip is REQUESTED, from the measurement in the book
(i, tp), not read back from the book: the measurement is the fact and the gain is policy,
so the new target reaches the 22,932 clips already measured without measuring one again.

Usage:  sfx_voices_level_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        sfx_voices_level_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET_OLD = '''SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-16"))
SFX_TP_DB = float(os.getenv("SFX_TP_DB", "-6"))
'''
TARGET_NEW = '''# [sfx-voices] -14 LUFS and a -2 dBTP ceiling: the DJ renders measure -13.5 LUFS (loudnorm
# TP -1.5) and the sting slices -12.4; under a -6 dBTP ceiling the clips landed at -17.8,
# four to five dB under the voices - the "whispers". The ceiling is the voices' own headroom.
SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-14"))
SFX_TP_DB = float(os.getenv("SFX_TP_DB", "-2"))
'''
NOW_OLD = '''def sfx_gain_db(heard: dict[str, Any]) -> float:
'''
NOW_NEW = '''def sfx_gain_now(got: dict[str, Any] | None) -> dict[str, Any] | None:
    """[sfx-voices] The entry to stream with: its gain computed NOW from the measurement
    in the book (i, tp) and the target of this moment. The measurement is the fact and
    the gain is policy, so a new target reaches every clip already measured without
    measuring one again; closer than SFX_GAIN_MIN_DB to the target, the clip goes out as
    it is. An entry without a measurement keeps whatever gain it was given."""
    if not isinstance(got, dict):
        return None
    if got.get("i") is None:
        return got
    db = sfx_gain_db(got)
    out = dict(got)
    out["db"] = db if abs(db) >= SFX_GAIN_MIN_DB else None
    return out


def sfx_gain_db(heard: dict[str, Any]) -> float:
'''
ROUTE_OLD = '''            _gain = await asyncio.to_thread(sfx_gain_known, raw)
        except Exception:  # noqa: BLE001
            _gain = None
        if _gain and _gain.get("db") is not None:
'''
ROUTE_NEW = '''            _gain = sfx_gain_now(await asyncio.to_thread(sfx_gain_known, raw))   # [sfx-voices] the gain of this moment
        except Exception:  # noqa: BLE001
            _gain = None
        if _gain and _gain.get("db") is not None:
'''
APP = [
    ("the target and the ceiling are the voices' own", TARGET_OLD, TARGET_NEW, 'SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-14"))', 1),
    ("the gain is computed at request time", NOW_OLD, NOW_NEW, "def sfx_gain_now(got: dict[str, Any] | None) -> dict[str, Any] | None:", 1),
    ("the clip route asks for the gain of this moment", ROUTE_OLD, ROUTE_NEW, "_gain = sfx_gain_now(await asyncio.to_thread(sfx_gain_known, raw))", 1),
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
        tmp = path.with_name(path.name + ".sfxvoices.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
