#!/usr/bin/env python3
"""Make the burst road take its clip windows from the round's ASSEMBLED cue
map, and fall back to today's rescale when it does not prove out.

    docs/notes/speaker-recording-and-script-assembly.md, section 4:

        The current stream path rescales estimated cue windows to fit the
        finished duration. Replace that approximation with cue positions
        derived from actual edited sample counts.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_cue_map_windows_patch.py --check     # anchors only
    python tools/_cue_map_windows_patch.py             # apply
    python tools/_cue_map_windows_patch.py --revert

Idempotent: applying twice is a no-op and says so.  Every anchor is matched
against the current text of the file, exactly, and a single missing or
duplicated anchor aborts the whole patch without writing a byte.  The file
is written back LF-only, which is how `app.py` is stored, and the result is
compiled before it reaches the disk that serves the station.

WHY THE RESCALE CANNOT BE RIGHT
-------------------------------

`scale = _made / _ours` stretches the whole span of a burst to fit the
duration the mixer actually produced.  That correction is a SCALE, and the
errors it corrects are not scales.  Measured over 915 shadow-produced
rounds on this station (2026-09-15 .. 2026-09-21,
`data/script_production/rounds.jsonl`):

    mix_latency_frames    120 in every single round, latency_measured=True
    mix_residual_frames   0 in 343 of them, within +/-3 in 887 of 915

120 frames at 24 kHz is 5 ms: the limiter's lookahead, a CONSTANT delay.  A
constant multiplied by a scale factor is wrong at the head and wrong at the
tail, and no tuning of the factor fixes it.  The same ledger measured the
cost: measured and estimated cue positions differ by 16 ms in the median
round, 41 ms at p95, and 1.20 s in the worst one seen.

WHAT IT CHANGES
---------------

Three module-level helpers beside the rest of the production glue, and four
edits inside `_speak_turns_floorless`:

  1. HELPERS.  `production_cue_map`, `production_cue_beats` and
     `production_cue_windows`.  Pure, and they refuse rather than guess.
  2. BEATS (both mix sites).  The seam beats come from the map when the
     round was assembled with one, laid onto `seg` BY `seg_ix` so a ring, a
     hang-up or a sting keeps the beat it was drawn.  This is #778's rule
     one step earlier: the mixer and the timeline must be built out of the
     same numbers, or the file that airs is not the file that was measured
     and edit 3 correctly refuses to describe it.
  3. ADOPT.  Before the rescale.  Guarded, and the guards are named in
     `production_cue_windows`.
  4. TAIL.  `clip_tail` - what a per-line download leaves off - comes from
     the map's own pause when the map was adopted, unscaled, because
     nothing was scaled.

WHAT IT DOES NOT CHANGE
-----------------------

Everything, when the switch at `<data>/script_production/mode` is `off` or
`shadow`: a round that was not produced carries no `cue_map`, every helper
returns empty, and the rescale runs exactly as it does today.

2026-09-21: rewritten before first application.  The version written on
2026-09-15 joined cues to rows by `row["id"]` - the script ledger's
per-airing line id - and the frozen occurrence ids in a cue map are not
those, so that join could never have matched.  Rows carry the frozen
identity at `row["production"]["occurrence_id"]`, and that is the join.
The old version also compared the map's whole-file duration against the
finished burst; a call opens with a ring and closes with a hang-up which
are in the file and not in the map, so the comparison here is against
`body_frames`, the part both roads agree is the conversation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1337"          # this patch's tag in the source


# --------------------------------------------------------------------------
# 1. THE HELPERS, beside the rest of the production glue.
# --------------------------------------------------------------------------

HELPERS_ANCHOR = """def _production_remember(references: Any) -> None:
"""

HELPERS_NEW = '''# --- the measured cue map, on air (#1337) ---
#
# Section 4 of `docs/notes/speaker-recording-and-script-assembly.md`:
# "Replace that approximation with cue positions derived from actual edited
# sample counts." The approximation is `scale = _made / _ours` in
# `_speak_turns_floorless`, and what is wrong with it is not its tuning:
# the errors it corrects are a CONSTANT 120-frame limiter delay and a
# loudness-pass residual inside +/-3 frames, measured in every one of the
# 915 shadow-produced rounds this station has recorded. A constant
# multiplied by a scale factor is wrong at the head and wrong at the tail.
#
# `conversation_assembly.assemble_conversation` renders each strip through
# this mixer's own leg and reads the frame count off the result, so its cue
# positions are integer sample counts of audio that was actually produced.
# When a round carries such a map, these three functions are how it reaches
# the air - and how it is refused when it does not describe the file that
# was actually built.
CUE_MAP_BODY_TOLERANCE = 0.03     # seconds; the loudness pass's own residual


def production_cue_map(ready_meta: Any) -> dict[str, Any]:
    """The MEASURED cue map this round was assembled with, or {}.

    Present only on a round the producer made with the switch at `on`. In
    `off` and `shadow` there is no such key and every road below this one
    is untouched, which is the whole point of the switch."""
    try:
        got = dict((ready_meta or {}).get("cue_map") or {})
    except Exception:  # noqa: BLE001
        return {}
    if not got.get("cues"):
        return {}
    # "`derivation` is `measured`. Any other value must be treated as an
    # estimate" - and an estimate is what this road already has.
    if str(got.get("derivation") or "") != "measured":
        return {}
    return got


def production_cue_beats(ready_meta: Any, seg_ix: Any,
                         count: int) -> list[float] | None:
    """The seam beats the assembler MEASURED this round with, laid onto
    `seg`; None when this round was not assembled.

    #778 one step earlier: the mixer and the timeline must be built out of
    the same numbers. The assembler already mixed these strips with these
    beats and wrote down where every line lands; drawing fresh ones here
    would build a different file, and `production_cue_windows` would then
    correctly refuse to describe it.

    Laid BY `seg_ix` - a turn's index in `seg` - because a burst can carry
    a ring at the head, a hang-up at the tail and a sting in the middle,
    and none of those is a line in anybody's script. They keep the beat
    they were drawn."""
    cue_map = production_cue_map(ready_meta)
    if not cue_map:
        return None
    drawn = [float(b) for b in ((cue_map.get("mix") or {}).get("beats") or [])]
    if not drawn:
        return None
    out = concat_beats(int(count))
    for row, index in enumerate(list(seg_ix or [])):
        try:
            slot = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= slot < len(out) and row < len(drawn):
            out[slot] = float(drawn[row])
    return out


def production_cue_windows(ready_meta: Any, rows: Any, made_seconds: float,
                           start_at: float = 0.0) -> tuple[Any, str]:
    """This burst's windows, from measured sample counts - or (None, why).

    Returns one dict per row, in the burst's own order, carrying `from`,
    `until`, the separate `speech_end_s`, and the map's own `clip_tail`.

    EVERY GUARD HAS TO HOLD, and a map that does not prove out is not
    half-used - the round falls back whole:

      * the map says it was MEASURED, and it has cues;
      * every turn in the burst carries a frozen occurrence id;
      * the burst's occurrence ids ARE the map's `sequence`, in order.
        That is the note's own acceptance line - "The final cue sequence
        must equal the frozen script sequence" - and it is also #1330's
        lesson, that two lists of the same shape wrongly paired is a
        silent fault which lights one line and sounds another;
      * the body the map describes is the body the mixer just produced,
        inside the loudness pass's own residual. A ring and a hang-up are
        in the finished file and not in the map, which is why this compares
        `body_frames` and not the whole duration."""
    cue_map = production_cue_map(ready_meta)
    if not cue_map:
        return None, ""
    try:
        rows = list(rows or [])
        if not rows:
            return None, "the burst carries no turns"
        cues = {str(cue.get("occurrence_id") or ""): cue
                for cue in (cue_map.get("cues") or [])}
        wanted = [str(dict((row or {}).get("production") or {}).get(
            "occurrence_id") or "") for row in rows]
        if not all(wanted):
            return None, "a turn in this burst carries no frozen occurrence id"
        sequence = [str(name) for name in (cue_map.get("sequence") or [])]
        if wanted != sequence:
            return None, ("the burst's %d line(s) are not the map's sequence "
                          "of %d" % (len(wanted), len(sequence)))
        if any(name not in cues for name in wanted):
            return None, "an occurrence in the sequence has no cue"
        rate = float(cue_map.get("sample_rate") or 0.0)
        body = (float(cue_map.get("body_frames") or 0.0) / rate) if rate else 0.0
        if body <= 0.0:
            return None, "the map does not say how long its body is"
        made = float(made_seconds or 0.0)
        if abs(body - made) > CUE_MAP_BODY_TOLERANCE:
            return None, ("the map's body is %.3fs and the mixer produced "
                          "%.3fs" % (body, made))
        out: list[dict[str, Any]] = []
        for name in wanted:
            cue = cues[name]
            out.append({
                "from": float(start_at) + float(cue.get("start_seconds") or 0.0),
                "until": float(start_at) + float(cue.get("cue_end_seconds") or 0.0),
                # "Retain separate speech-end and cue-end positions so an
                # inserted pause does not falsely start the next line."
                "speech_end_s": (float(start_at)
                                 + float(cue.get("speech_end_seconds") or 0.0)),
                "clip_tail": float(cue.get("pause_seconds") or 0.0)})
        return out, ""
    except Exception as exc:  # noqa: BLE001
        return None, "the map could not be read (%s)" % type(exc).__name__


# --- the measured cue map, on air (#1337) --- end
def _production_remember(references: Any) -> None:
'''


# --------------------------------------------------------------------------
# 2. BEATS, at both mix sites.
# --------------------------------------------------------------------------

BEATS_ANCHOR = """            beats = concat_beats(len(seg))
            try:
                mixed = (await asyncio.to_thread(
                            _call_concat_blocking, seg,
                            bool(dj_settings().get("stream_texture")), beats)
                         if len(seg) >= 2 else None)
"""

BEATS_NEW = """            # #1337: WHEN THE ROUND WAS ASSEMBLED, THESE ARE ITS BEATS.
            # The assembler measured this round with them and wrote down
            # where every line lands; drawing fresh ones here would build a
            # different file, and the cue map below would refuse it.
            beats = (production_cue_beats(ready_meta, seg_ix, len(seg))
                     or concat_beats(len(seg)))
            try:
                mixed = (await asyncio.to_thread(
                            _call_concat_blocking, seg,
                            bool(dj_settings().get("stream_texture")), beats)
                         if len(seg) >= 2 else None)
"""

REMIX_ANCHOR = """                    _sfx_meta = {}
                    beats = concat_beats(len(seg))
"""

REMIX_NEW = """                    _sfx_meta = {}
                    # #1337: the SFX rows have just been taken back out, so
                    # this re-mix is the one that can actually match an
                    # assembled map - the round is its scripted lines and
                    # nothing else.
                    beats = (production_cue_beats(ready_meta, seg_ix, len(seg))
                             or concat_beats(len(seg)))
"""


# --------------------------------------------------------------------------
# 3. ADOPT: the measured windows, before the rescale they replace.
# --------------------------------------------------------------------------

ADOPT_ANCHOR = """                _ours = offset - _ring_real
                if rows and _ours > 0.5 and _made > 0.5:
"""

ADOPT_NEW = '''                _ours = offset - _ring_real
                # #1337: THE MEASURED TIMELINE, WHEN THERE IS ONE.
                #
                # Everything above this line is an ESTIMATE: each clip was
                # measured as it sits on disk and `seg_real_seconds` guessed
                # what the mixer's silenceremove leg would take off the end
                # of it. The rescale below then stretches the whole span to
                # fit, because the sum never lands - and what it corrects is
                # a CONSTANT 120-frame limiter delay plus a residual inside
                # +/-3 frames, neither of which is a scale.
                #
                # A round the producer assembled carries integer sample
                # counts of audio that was actually produced. Adopted only
                # when it proves out, whole, or not at all.
                _cue_exact = False
                _cue_windows, _cue_why = production_cue_windows(
                    ready_meta, rows, _made, _ring_real)
                if _cue_windows:
                    for _rw, _cw in zip(rows, _cue_windows):
                        _rw.update(_cw)
                    _cue_exact = True
                    # #830: the page-routed estimate must agree with the
                    # timeline that is actually airing, measured or scaled.
                    for _r2, _e2 in zip(rows, _entries):
                        air_at_set(_e2, _est0 + float(_r2.get("from") or 0))
                    pipeline_log(
                        "voice", "the round aired on its own assembled cue "
                        "map - %d measured windows, no rescale (#1337)"
                        % len(rows))
                elif _cue_why:
                    pipeline_log(
                        "drop", "a supplied cue map was not used: %s - the "
                        "estimated windows stand (#1337)" % _cue_why)
                if rows and not _cue_exact and _ours > 0.5 and _made > 0.5:
'''


# --------------------------------------------------------------------------
# 4. TAIL: the download's cut point, from the map when it was adopted.
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
                    # a measured cue map, so the download's cut point is not
                    # scaled either - it is the map's own pause.
                    _bscale = ((_made / _ours)
                               if (rows and not _cue_exact
                                   and _ours > 0.5 and _made > 0.5)
                               else 1.0)
                    for _ri, (_r3, _e3) in enumerate(zip(rows, _entries)):
                        _sx3 = seg_ix[_ri] if _ri < len(seg_ix) else -1
                        _beat3 = (beats[_sx3] if 0 <= _sx3 < len(beats)
                                  else 0.0)
                        if _cue_exact:
                            _beat3 = float(_r3.get("clip_tail") or 0.0)
"""


EDITS = [("the cue-map helpers", HELPERS_ANCHOR, HELPERS_NEW),
         ("beats from the cue map", BEATS_ANCHOR, BEATS_NEW),
         ("beats from the cue map on the re-mix", REMIX_ANCHOR, REMIX_NEW),
         ("the measured windows adopted before the rescale",
          ADOPT_ANCHOR, ADOPT_NEW),
         ("the download tail from the cue map", TAIL_ANCHOR, TAIL_NEW)]


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
    # Prove the result still parses BEFORE it reaches the disk that serves
    # the station. A file that does not compile is dead air.
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
