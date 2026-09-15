#!/usr/bin/env python3
"""Make `_speak_turns_floorless` take its clip windows from a supplied cue
map, and fall back to today's rescale when there is not one.

    docs/notes/speaker-recording-and-script-assembly.md, section 4:

        The current stream path rescales estimated cue windows to fit the
        finished duration (app.py:83945 onward). Replace that approximation
        with cue positions derived from actual edited sample counts.

NOT RUN BY ITS AUTHOR.  `app.py` is owned by another agent and every change
to it is applied by the caller.  Run this from the repo root:

    python tools/_cue_map_windows_patch.py --check     # anchors only
    python tools/_cue_map_windows_patch.py             # apply
    python tools/_cue_map_windows_patch.py --revert

Idempotent: applying twice is a no-op and says so.  Every anchor is matched
against the current text of the file, exactly, and a single missing or
duplicated anchor aborts the whole patch without writing a byte.  The file
is written back LF-only, which is how `app.py` is stored.

WHAT IT CHANGES
---------------

Four edits, all inside the coalesced-burst branch of
`_speak_turns_floorless`:

  1. BEATS.  The seam beats are drawn from the cue map when one is
     supplied, instead of freshly at random.  This is #778's rule applied
     one step earlier: the mixer and the timeline must be built out of the
     same numbers.  Without this the re-mix is a different file from the
     one the assembler measured, and edit 3 correctly refuses it.
  2. ADOPT.  Before the rescale, try the supplied cue map.  It is adopted
     only if it names every row by id AND its own duration agrees with the
     finished clip.  `_cue_exact` records the outcome.
  3. RESCALE.  Guarded by `not _cue_exact`.  With no cue map, or a cue map
     that did not prove out, today's behaviour is untouched.
  4. TAIL.  `clip_tail` (what a download leaves off) comes from the cue
     map's own pause when the map was adopted, unscaled — because nothing
     was scaled.

WHERE THE CUE MAP COMES FROM
----------------------------

`ready_meta`, which is `dict(ready_takes[0].get("round") or {})`.  A
prepared round that was assembled by `conversation_assembly.py` carries its
cue map at `round["cue_map"]`.  Anything else on air — a fresh round, a
rescue, an interject — has no such key and is unaffected.

Cues are matched to rows BY ID, never by position: #1330's lesson is that
two lists of the same shape, wrongly paired, is a silent fault.  If any row
lacks a cue the whole round falls back, rather than mixing two timelines.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1337"          # this patch's tag in the source


# --------------------------------------------------------------------------
# 1. BEATS: drawn from the cue map when one was supplied.
# --------------------------------------------------------------------------

BEATS_ANCHOR = """            beats = concat_beats(len(seg))
            try:
                mixed = (await asyncio.to_thread(
                            _call_concat_blocking, seg,
                            bool(dj_settings().get("stream_texture")), beats)
                         if len(seg) >= 2 else None)
"""

BEATS_NEW = """            # #1337: WHEN THE ROUND WAS ASSEMBLED, THE BEATS ARE ITS
            # BEATS. #778's rule one step earlier: the mixer and the
            # timeline must be built out of the same numbers. The
            # assembler already measured this round with these beats and
            # wrote down where every line lands; drawing fresh ones here
            # would produce a different file and the cue map below would
            # correctly refuse to describe it.
            beats = concat_beats(len(seg))
            _cue_map = dict((ready_meta or {}).get("cue_map") or {})
            _cue_beats = list(((_cue_map.get("mix") or {}).get("beats")
                               or []))
            if _cue_beats and len(_cue_beats) == len(seg):
                beats = [float(_b) for _b in _cue_beats]
            try:
                mixed = (await asyncio.to_thread(
                            _call_concat_blocking, seg,
                            bool(dj_settings().get("stream_texture")), beats)
                         if len(seg) >= 2 else None)
"""


# --------------------------------------------------------------------------
# 2. ADOPT: the cue map, before the rescale that it replaces.
# --------------------------------------------------------------------------

ADOPT_ANCHOR = """                _hang_real = (seg_real_seconds(hang_secs, 0.0,
                                               _tail_at(len(seg) - 1))
                              if hang_secs and _welded else hang_secs)
                _made = (length - _ring_real - _hang_real
                         - (box_tail_seconds() if _welded else 0.0))
                _ours = offset - _ring_real
                if rows and _ours > 0.5 and _made > 0.5:
"""

ADOPT_NEW = '''                _hang_real = (seg_real_seconds(hang_secs, 0.0,
                                               _tail_at(len(seg) - 1))
                              if hang_secs and _welded else hang_secs)
                _made = (length - _ring_real - _hang_real
                         - (box_tail_seconds() if _welded else 0.0))
                _ours = offset - _ring_real
                # #1337: THE MEASURED TIMELINE, WHEN THERE IS ONE.
                #
                # Everything above this line is an ESTIMATE. Each clip was
                # measured as it sits on disk and `seg_real_seconds` guessed
                # what the mixer's silenceremove leg would take off the end
                # of it. The rescale below then stretches the whole span to
                # fit the finished duration, because the sum never lands.
                #
                # That correction is a SCALE, and the errors it corrects are
                # not scales. Measured on this station's own mixer:
                # the per-input legs and the concat are frame-exact;
                # `loudnorm` adds about three frames of LENGTH; `alimiter`
                # delays everything by 120 frames - its 5 ms attack
                # lookahead - and changes no length at all. A constant
                # delay multiplied by a scale factor is wrong at the head
                # and wrong at the tail, and no tuning of the factor fixes
                # it.
                #
                # `conversation_assembly.assemble_conversation` renders each
                # strip through the mixer's own leg and reads the frame
                # count off the result, so its cue positions are integer
                # sample counts of audio that was actually produced. When
                # this round carries such a map, use it.
                #
                # Adopted only when it PROVES OUT: a cue for every row, by
                # ID (#1330 - two lists the same shape, wrongly paired, is
                # a silent fault), and its own duration agreeing with the
                # clip that was actually built. A map that does not prove
                # out is not half-used; the round falls back whole.
                _cue_exact = False
                try:
                    _cue_map = dict((ready_meta or {}).get("cue_map") or {})
                    _cues = {str(_c.get("occurrence_id") or ""): _c
                             for _c in (_cue_map.get("cues") or [])}
                    _claim = float(_cue_map.get("seconds") or 0.0)
                    _fits = (bool(rows) and bool(_cues) and _claim > 0.5
                             and abs(_claim - length) <= 0.03
                             and all(str(_r.get("id") or "") in _cues
                                     for _r in rows))
                    if _fits:
                        for _r in rows:
                            _c = _cues[str(_r.get("id"))]
                            _r["from"] = float(_c.get("start_seconds") or 0.0)
                            _r["until"] = float(
                                _c.get("cue_end_seconds") or 0.0)
                            _r["speech_until"] = float(
                                _c.get("speech_end_seconds") or 0.0)
                            _r["cue_tail"] = float(
                                _c.get("pause_seconds") or 0.0)
                        _cue_exact = True
                        for _r2, _e2 in zip(rows, _entries):
                            air_at_set(
                                _e2, _est0 + float(_r2.get("from") or 0))
                        pipeline_log(
                            "voice", "the round aired on its assembled cue "
                            f"map - {len(rows)} measured windows, no "
                            "rescale (#1337)")
                    elif _cue_map:
                        pipeline_log(
                            "drop", "a supplied cue map did not match the "
                            f"finished burst ({_claim:.2f}s vs "
                            f"{length:.2f}s) - falling back to the "
                            "estimated windows (#1337)")
                except Exception:  # noqa: BLE001
                    _cue_exact = False   # a cue map never costs the air a beat
                if rows and not _cue_exact and _ours > 0.5 and _made > 0.5:
'''


# --------------------------------------------------------------------------
# 3. TAIL: the download's cut point, from the map when it was adopted.
# --------------------------------------------------------------------------

TAIL_ANCHOR = """                    _bscale = ((_made / _ours)
                               if (rows and _ours > 0.5 and _made > 0.5)
                               else 1.0)
                    for _ri, (_r3, _e3) in enumerate(zip(rows, _entries)):
                        _sx3 = seg_ix[_ri] if _ri < len(seg_ix) else -1
                        _beat3 = (beats[_sx3] if 0 <= _sx3 < len(beats)
                                  else 0.0)
"""

TAIL_NEW = """                    # #1337: nothing was scaled when the windows came off
                    # a measured cue map, so the download's cut point is
                    # not scaled either - it is the map's own pause.
                    _bscale = ((_made / _ours)
                               if (rows and not _cue_exact
                                   and _ours > 0.5 and _made > 0.5)
                               else 1.0)
                    for _ri, (_r3, _e3) in enumerate(zip(rows, _entries)):
                        _sx3 = seg_ix[_ri] if _ri < len(seg_ix) else -1
                        _beat3 = (beats[_sx3] if 0 <= _sx3 < len(beats)
                                  else 0.0)
                        if _cue_exact:
                            _beat3 = float(_r3.get("cue_tail") or 0.0)
"""


EDITS = [("beats drawn from the cue map", BEATS_ANCHOR, BEATS_NEW),
         ("cue map adopted before the rescale", ADOPT_ANCHOR, ADOPT_NEW),
         ("download tail from the cue map", TAIL_ANCHOR, TAIL_NEW)]


def load(path: Path) -> str:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        raise SystemExit(f"{path} contains CRLF; this file is LF-only "
                         "and the patch refuses to normalise it silently")
    return raw.decode("utf-8")


def report(text: str) -> tuple[int, list[str]]:
    """How many edits are already in, and what is wrong with the rest."""
    applied = text.count(MARK)
    trouble: list[str] = []
    for name, anchor, new in EDITS:
        if new in text:
            continue
        found = text.count(anchor)
        if found != 1:
            trouble.append(f"{name}: anchor found {found} times, expected 1")
    return applied, trouble


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
        path.write_bytes(out.encode("utf-8"))
        print(f"reverted {undone} edit(s) in {path}")
        return 0

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

    _applied, trouble = report(text)
    for name, anchor, _new in EDITS:
        found = text.count(anchor)
        print(f"  anchor {found}x  {name}")
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
    # Prove the result still parses BEFORE it reaches the disk that serves
    # the station.  A file that does not compile is dead air.
    try:
        compile(out, str(path), "exec")
    except SyntaxError as exc:
        print(f"the patched file does not parse ({exc}); nothing written",
              file=sys.stderr)
        return 1
    path.write_bytes(out.encode("utf-8"))
    print(f"applied {len(EDITS)} edits to {path}")
    print("the container must be restarted by its owner for this to take "
          "effect; this script does not restart anything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
