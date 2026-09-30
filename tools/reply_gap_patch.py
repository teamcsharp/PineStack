"""[reply-gap] The pause between replies: a slider, a roulette range, a roll.

2026-09-30, the operator: "put a slider here for adjusting the space between dj
replies and the sfx guy replies ... 1 second between replies ... up to possibly
10 seconds ... as low as .2 seconds ... a 2nd slider for a roulette RNG roll
after each reply ... a toggle to enable roulette rolls ... Show the rolling dice
here ... Have the orchestrator understand and take the slider into
consideration for the segment planning as well."

  app.py   imports reply_gap.py (the settings, the roll, the seams, the cue-map
           retime) and hooks it where the pause is DECIDED - the beats the
           burst road draws for the mixer (#778) - plus the two other joins
           of whole replies (a line + its stings, the resume reel), the page
           ledger's wait into the next page, the stream_now rows the panel's
           dice read, the segment budget, the fit checks and the stock price;
           installs GET/POST /api/reply-gap.
  script-page.js / script-page.css (any number of copies, byte-identical):
           the two sliders, the toggle and the dice square on the Script
           view's toolbar.

Usage (app.py ON THE HOST - never across the share):
    python3 tools/reply_gap_patch.py --check app.py
    python3 tools/reply_gap_patch.py --apply app.py
    python3 tools/reply_gap_patch.py --apply-js desktop/renderer/script-page.js ...
    python3 tools/reply_gap_patch.py --apply-css desktop/renderer/script-page.css ...
--check exits 0 ready, 2 already applied, 1 anchors missing (named).
Every anchor is asserted unique; LF only; written atomically."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

MARK = "[reply-gap]"

# --------------------------------------------------------------------- app.py

HELPERS_AT = '''# #1205: the mixer's own reading of "how much silence is on the end of
'''
HELPERS = '''# [reply-gap] THE PAUSE BETWEEN REPLIES (reply_gap.py). The operator's two
# sliders and roulette toggle on the Script view: the silence after every
# reply - DJ to DJ, DJ to the SFX Guy, the SFX Guy to a DJ - is `gap` (0.2 -
# 10 s, default 1), or, rolling, a System 3 roll in gap +/- range. It enters
# where the pause is decided: the beats drawn for the mixer (#778). A chunk of
# one speaker's turn and a listening response keep CONCAT_BEAT - that is a
# breath inside a reply, not the space between two. The planners ask
# reply_gap_seam(), the expected pause, so the segment is budgeted as its
# lines plus (N - 1) pauses.
try:
    import reply_gap as _reply_gap
    _reply_gap.bind(globals())
except Exception as _rg_exc:  # noqa: BLE001
    _reply_gap = None
    print("the reply gap did not load: %s: %s" % (type(_rg_exc).__name__, _rg_exc))


def reply_gap_seam() -> float:
    """[reply-gap] What one seam between two replies costs the air: the
    operator's pause (the expected one when it rolls), never under the beat."""
    try:
        if _reply_gap is not None:
            return max(max(CONCAT_BEAT), float(_reply_gap.expected_gap()))
    except Exception:  # noqa: BLE001
        pass
    return max(CONCAT_BEAT)


def reply_gap_stock_extra(clips: int) -> float:
    """[reply-gap] A finished round is priced off its clips as they sit on
    disk, welded tail and all (CONCAT_TAIL); on air each seam is the trimmed
    sliver plus the pause. This is the difference, for `clips` joined clips."""
    n = max(0, int(clips or 0))
    if n < 2:
        return 0.0
    return (n - 1) * (reply_gap_seam() - max(0.0, CONCAT_TAIL - CONCAT_KEEP))


def reply_gap_beats(count: int, meta: Any = None, road: str = "") -> list[float]:
    """[reply-gap] Beats for a join where every seam is a reply (a line and the
    stings answering it; the resume reel of whole lines)."""
    beats = concat_beats(count)
    if _reply_gap is None:
        return beats
    try:
        return _reply_gap.plain(count, meta=meta, road=road, base=beats)
    except Exception:  # noqa: BLE001
        return beats


def reply_gap_burst(beats: list[float], seg_ix: list[int], turn_ix: list[int],
                    transcript: list, items: list, meta: Any = None,
                    carry: bool = False) -> tuple[list[float], dict[Any, Any]]:
    """[reply-gap] A burst's beats with every reply seam set to its pause
    (rolled once each when the roulette is on, a System 3 roll with its
    receipt), and a produced round's measured cue map moved to match, so
    #1337 still adopts it. Returns (beats, notes); notes feed the rows the
    panel's dice read and the wait into the next page."""
    if _reply_gap is None:
        return beats, {}
    try:
        got, notes = _reply_gap.burst(beats, seg_ix, turn_ix, transcript, items,
                                      meta=meta, carry=bool(carry))
        _reply_gap.retime_for_burst(meta, got, seg_ix, turn_ix, items)
        return got, notes
    except Exception as exc:  # noqa: BLE001
        try:
            pipeline_log("drop", "the reply gap could not set this round's pauses - "
                         "its own beats stand", extra="%r" % (exc,))
        except Exception:  # noqa: BLE001
            pass
        return beats, {}


def reply_gap_rows(rows: list, seg_ix: list[int], notes: Any) -> None:
    """[reply-gap] Each row a pause follows carries it (`gap`), for the dice."""
    try:
        if _reply_gap is not None and notes:
            _reply_gap.stamp_rows(rows, seg_ix, notes)
    except Exception:  # noqa: BLE001
        pass


def reply_gap_carry(notes: Any, length: Any, rows: list) -> float:
    """[reply-gap] How much longer a paged round's next page waits, so the
    pause into it is the pause that was picked."""
    try:
        if _reply_gap is not None and notes:
            return float(_reply_gap.carry_seconds(notes, length, rows))
    except Exception:  # noqa: BLE001
        pass
    return 0.0


'''

EDITS: list[tuple[str, str, str]] = [
    # (name, old, new)
    ("helpers", HELPERS_AT, HELPERS + HELPERS_AT),
    ("punctuation beats",
     '''        beats = concat_beats(len(paths))
        raw = await asyncio.wait_for(asyncio.to_thread(
''',
     '''        beats = reply_gap_beats(len(paths), road="punctuation")   # [reply-gap] a line and its stings
        raw = await asyncio.wait_for(asyncio.to_thread(
'''),
    ("reel beats",
     '''            beats = concat_beats(len(paths))
            mixed = await asyncio.to_thread(
''',
     '''            beats = reply_gap_beats(len(paths), road="reel")   # [reply-gap] whole lines, one after another
            mixed = await asyncio.to_thread(
'''),
    ("burst beats",
     '''            beats = (production_cue_beats(ready_meta, seg_ix, len(seg))
                     or concat_beats(len(seg)))
''',
     '''            beats = (production_cue_beats(ready_meta, seg_ix, len(seg))
                     or concat_beats(len(seg)))
            # [reply-gap] EVERY SEAM THAT ENDS A REPLY IS THE OPERATOR'S PAUSE -
            # drawn (or rolled, a System 3 roll with its receipt) HERE, so the
            # mixer, the timeline and a produced round's cue map are all built
            # out of the same numbers. A paged round's last line rolls the
            # pause into the next page too ("carry"; waited out below).
            beats, _rg_notes = reply_gap_burst(beats, seg_ix, turn_ix, transcript,
                                               aired_items, ready_meta,
                                               not last_batch)
'''),
    ("rows gap",
     '''                # #908: WHERE EACH TURN'S AUDIO ACTUALLY IS. The burst
''',
     '''                reply_gap_rows(rows, seg_ix, _rg_notes)      # [reply-gap] the panel's dice
                # #908: WHERE EACH TURN'S AUDIO ACTUALLY IS. The burst
'''),
    ("page carry",
     '''                    _paged_until = _pstart + max(0.0, float(length or 0))
''',
     '''                    _paged_until = (_pstart + max(0.0, float(length or 0))
                                    # [reply-gap] the pause into the next page
                                    + reply_gap_carry(_rg_notes, length, rows))
'''),
    ("stream_now gap",
     '''                      "voice": str(r.get("voice") or ""),
                      "aired": "airing"}
''',
     '''                      "voice": str(r.get("voice") or ""),
                      # [reply-gap] the pause after this reply, for the dice
                      "gap": (r.get("gap") if isinstance(r.get("gap"), dict)
                              else None),
                      "aired": "airing"}
'''),
    ("segment budget turns",
     '''    per = max(1.5, mean_turn_seconds(kind))
    turns = int(talk // per)
''',
     '''    per = max(1.5, mean_turn_seconds(kind))
    # [reply-gap] THE PAUSES ARE PART OF THE SEGMENT. N replies take their
    # speech plus (N - 1) of the operator's pauses (the expected one when it
    # rolls). `per` is the ledger's clip length, welded tail included, so the
    # tail comes off before the pause goes on: 1 s between replies costs
    # about what the old beat and tail did, 10 s costs ten seconds a turn.
    seam = reply_gap_seam()
    speech = max(1.0, per - max(0.0, CONCAT_TAIL - CONCAT_KEEP))
    turns = int((talk + seam) // (speech + seam))
'''),
    ("segment budget fields",
     '''            "turn_seconds": round(per, 2), "turns": turns,
''',
     '''            "turn_seconds": round(per, 2), "turns": turns,
            "reply_gap": round(seam, 2),                        # [reply-gap]
            "turn_air_seconds": round(speech + seam, 2),
'''),
    ("segment budget say",
     '''            "say": ("%s owns %.0fs, about %.0fs of it talk at %.1fs a turn - "
                    "%d cycle(s), %d turns"
                    % (kind or "the segment", want, talk, per, cycles,
                       lines))}
''',
     '''            "say": ("%s owns %.0fs, about %.0fs of it talk at %.1fs a turn "
                    "and %.1fs between replies - %d cycle(s), %d turns"
                    % (kind or "the segment", want, talk, per, seam, cycles,
                       lines))}
'''),
    ("fit: system2 claim",
     '''        duration = (seconds + max(0, len(lines) - 1) * max(CONCAT_BEAT)
''',
     '''        duration = (seconds + max(0, len(lines) - 1) * reply_gap_seam()   # [reply-gap]
'''),
    ("fit: cadence additions",
     '''        total = float(seconds) + sum(float(r["seconds"]) + max(CONCAT_BEAT) for r in additions)
        total += float(extra) + max(CONCAT_BEAT)
''',
     '''        total = float(seconds) + sum(float(r["seconds"]) + reply_gap_seam() for r in additions)   # [reply-gap]
        total += float(extra) + reply_gap_seam()
'''),
    ("fit: ready round",
     '''            duration += (max(0, len(takes) - 1) * max(CONCAT_BEAT)
''',
     '''            duration += (max(0, len(takes) - 1) * reply_gap_seam()   # [reply-gap]
'''),
    ("fit: burst core",
     '''                                 + max(CONCAT_BEAT) * max(0, len(batch) - 1)
''',
     '''                                 + reply_gap_seam() * max(0, len(batch) - 1)   # [reply-gap]
'''),
    ("fit: burst extras",
     '''                        _sfx_extra_seconds += _extra["seconds"] + max(CONCAT_BEAT)
''',
     '''                        _sfx_extra_seconds += _extra["seconds"] + reply_gap_seam()   # [reply-gap]
'''),
    ("stock: finished",
     '''        if not keys and row.get("produced"):
            actual = float(row.get("seconds") or 0)
        if not projected:
''',
     '''        if not keys and row.get("produced"):
            actual = float(row.get("seconds") or 0)
        # [reply-gap] a finished round airs its lines AND the pauses between them
        actual = max(0.0, actual + reply_gap_stock_extra(len(keys)))
        if not projected:
'''),
    ("stock: projected",
     '''        estimate = len(script) / 14.0 if script else 0.0
''',
     '''        estimate = len(script) / 14.0 if script else 0.0
        if script:                          # [reply-gap] ...and the pauses between its lines
            estimate += max(0, sum(1 for _ln in script.splitlines()
                                   if _ln.strip()) - 1) * reply_gap_seam()
'''),
    ("director estimate",
     '''    words = 0
    try:
        for row in (turns if turns is not None else _director_script_lines(script)):
            words += len(re.findall(r"\\w+", str((row or {}).get("text") or "")))
    except Exception:  # noqa: BLE001
        words = 0
    # Broadcast speech on this station normally lands around 145-175 wpm.
    # Use the slower end so warnings appear before a short script reaches air.
    return round(words / 2.4, 1) if words else 0.0
''',
     '''    words = 0
    lines = 0                               # [reply-gap]
    try:
        for row in (turns if turns is not None else _director_script_lines(script)):
            words += len(re.findall(r"\\w+", str((row or {}).get("text") or "")))
            lines += 1
    except Exception:  # noqa: BLE001
        words = 0
    # Broadcast speech on this station normally lands around 145-175 wpm.
    # Use the slower end so warnings appear before a short script reaches air.
    # [reply-gap] ...and the operator's pause sits between every two lines.
    return (round(words / 2.4 + max(0, lines - 1) * reply_gap_seam(), 1)
            if words else 0.0)
'''),
    ("routes",
     '''# [rounds-tree] THE SEGMENT''',
     '''# [reply-gap] THE PAUSE BETWEEN REPLIES: GET/POST /api/reply-gap (reply_gap.py),
# station-wide in data/reply_gap.json - the Script view's sliders, its roulette
# toggle and its dice read and write it, so the desk and the tablet agree.
try:
    if _reply_gap is not None:
        _reply_gap.install(app, globals())
except Exception as _rgi_exc:  # noqa: BLE001
    print("the reply gap door did not install: %s: %s" % (type(_rgi_exc).__name__, _rgi_exc))
# [rounds-tree] THE SEGMENT'''),
]


# ------------------------------------------------------------ script-page.js

JS_EDITS: list[tuple[str, str, str]] = []
CSS_EDITS: list[tuple[str, str, str]] = []
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reply_gap_patch_ui import JS_EDITS, CSS_EDITS  # noqa: E402,F811
except ImportError:
    pass


# ------------------------------------------------------------------ machinery

def _read(path: Path) -> str:
    raw = path.read_bytes().decode("utf-8")
    if "\r\n" in raw:
        raise SystemExit("%s has CRLF line endings - normalise to LF first" % path)
    return raw


def _state(text: str, edits) -> tuple[int, list[str]]:
    """0 ready, 2 applied, 1 broken (with the names)."""
    applied, missing, ready = [], [], []
    for name, old, new in edits:
        n_old, n_new = text.count(old), text.count(new)
        if n_new == 1 and (n_old == 0 or new.find(old) >= 0 and n_old == 1):
            applied.append(name)
        elif n_old == 1:
            ready.append(name)
        else:
            missing.append("%s (anchor x%d)" % (name, n_old))
    if missing:
        return 1, missing
    if applied and not ready:
        return 2, []
    if applied and ready:
        return 1, ["half applied: " + ", ".join(applied)]
    return 0, []


def _apply(text: str, edits) -> str:
    for name, old, new in edits:
        if text.count(old) != 1:
            raise SystemExit("anchor %s: found %d times" % (name, text.count(old)))
        text = text.replace(old, new, 1)
    return text


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".rgtmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    mode, paths = argv[1], [Path(p) for p in argv[2:]]
    edits = {"--check": EDITS, "--apply": EDITS, "--check-js": JS_EDITS,
             "--apply-js": JS_EDITS, "--check-css": CSS_EDITS,
             "--apply-css": CSS_EDITS}.get(mode)
    if edits is None or not edits:
        print("unknown mode (or the UI edits did not load): %s" % mode)
        return 1
    codes = []
    for path in paths:
        text = _read(path)
        code, why = _state(text, edits)
        codes.append(code)
        if mode.startswith("--check"):
            print("%s: %s%s" % (path, {0: "READY", 2: "APPLIED", 1: "BROKEN"}[code],
                                (" - " + "; ".join(why)) if why else ""))
            continue
        if code == 2:
            print("%s: already applied" % path)
            continue
        if code == 1:
            print("%s: BROKEN - %s" % (path, "; ".join(why)))
            return 1
        out = _apply(text, edits)
        if path.suffix == ".py":
            ast.parse(out)
        _write(path, out)
        print("%s: applied %d edits" % (path, len(edits)))
    if mode.startswith("--check"):
        return 1 if 1 in codes else 2 if all(c == 2 for c in codes) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
