#!/usr/bin/env python3
"""Make the admission gate able to NAME the audio it gates, and make the
station's busiest producer of broadcast audio commit before it dispatches.

    docs/notes/speaker-recording-and-script-assembly.md, section 4:

        Verify the complete final artifact before admission. Playback must
        not write, record, choose a replacement, or reconstruct the line
        sequence as it airs.

    docs/notes/admission-and-playout-2026-09-15.md, "What remains":

        Early submit for the other 29 producers. They are all *gated*, and
        the census names them; only the burst road *submits ahead*.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_admission_reach_patch.py --check     # anchors only
    python tools/_admission_reach_patch.py             # apply
    python tools/_admission_reach_patch.py --revert

Idempotent, anchored exactly once each, compiled before it is written.

WHAT THE CENSUS SAID
--------------------

Nineteen hours of observe mode, `data/broadcast_admission/ledger.jsonl`,
58,676 rows:

    would_refuse:unadmitted   14,394   enforcement would have gagged these
    admission_refused          4,991   the gate could not name the audio
    would_refuse:out_of_order   2,584

and, by producer:

    _dj_speak_floorless   9,137 unadmitted   (the speech lane)
    dj_sting              4,514 unadmitted, and 4,512 of the 4,991
                          admission refusals: "the final audio is not
                          available at 65d26c4e1827c8d7"

That second number is not a missing file.  `/sfx/{key}` names a sample by
its ID and serves it through `sfx_levelled`; the gate's resolver only knew
how to turn a path into a file.  So the entire SFX lane - every sting the
station played - was unnameable, and `enforce sfx` would have silenced all
of it.  398 more were produced ads under `/ads-audio/`, 34 upstairs pages
under `/upstairs-audio/`.  The remaining 82 are a recovery fixture called
`test.wav` which genuinely does not exist, and those stay refused: "an
occurrence that cannot name its audio is not an occurrence".

WHAT IT CHANGES
---------------

  1. `sfx_levelled_name`, split out of `sfx_levelled`, so the levelled
     copy's name can be asked for without making one.  #1420's lesson is
     that the levels must not live in two places; this keeps one spelling.
  2. `_admission_resolve` learns the three routes that name audio by
     something other than a filename: `/sfx/`, `/ads-audio/`,
     `/upstairs-audio/`.  The SFX road takes only the free way back from
     an id to its path (#1307's reverse map) - never `sfx_by_id`, whose
     other roads end in a walk of the share, because this runs on the
     event loop.
  3. `admission_admit_line` / `admission_withdraw` beside
     `admission_admit_round`.
  4. `_dj_speak_floorless` admits its line BEFORE either transport is
     touched, and withdraws it again if it turns out that neither will
     carry it.  A committed occurrence that never airs is a hole in the
     script, and a hole that nobody marked is worse than one that is.

NONE OF THIS ENFORCES ANYTHING.  The mode file is untouched: the gate stays
in whatever mode it is in, and every number above is a census reading that
should move once this is deployed.  That is the measurement the
observe-to-enforce procedure asks for in its step 2.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1338"


# --------------------------------------------------------------------------
# 1. The levelled copy's NAME, without making one.
# --------------------------------------------------------------------------

LEVELNAME_ANCHOR = """    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return path
    vol = box_gain()             # stings track the box-volume slider too (#573)
    out = SFX_LEVELLED / f"{sfx_id(path)}-v2-v{int(round(vol * 20))}-{stamp}.wav"
    if out.exists():
        return out
"""

LEVELNAME_NEW = """    vol = box_gain()             # stings track the box-volume slider too (#573)
    out = sfx_levelled_name(path, vol)
    if out is None:
        return path
    if out.exists():
        return out
"""

LEVELNAME_DEF_ANCHOR = """def sfx_levelled(path: Path) -> Path:
"""

LEVELNAME_DEF_NEW = '''def sfx_levelled_name(path: Path, vol: float | None = None) -> Path | None:
    """WHERE this sample's levelled copy lives - or would, if it were made.

    Never makes one, never reads the sample, and never decides whether the
    clip should be levelled at all: that is `sfx_levelled`'s judgement and
    this is only its arithmetic. None means even the name cannot be
    answered, because the sample is not on the share any more.

    Split out (#1338) because the admission gate has to identify the bytes
    the box is ABOUT TO BE HANDED, on the event loop, without doing the
    levelling itself. It is one function rather than two spellings of the
    same filename for the reason #1420 was written: the levels had lived
    in two places and the two had drifted."""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    if vol is None:
        vol = box_gain()
    return SFX_LEVELLED / f"{sfx_id(path)}-v2-v{int(round(vol * 20))}-{stamp}.wav"


def sfx_levelled(path: Path) -> Path:
'''


# --------------------------------------------------------------------------
# 2. The resolver: the routes that name audio by something else.
# --------------------------------------------------------------------------

RESOLVE_ANCHOR = """        for room in (VOICE_MEDIA_DIR, data_path("sfx"), data_path("tape")):
            guess = room / key
            if guess.is_file():
                return guess
        return None
"""

RESOLVE_NEW = '''        for room in (VOICE_MEDIA_DIR, data_path("sfx"), data_path("tape")):
            guess = room / key
            if guess.is_file():
                return guess
        # #1338: THE ROUTES THAT NAME AUDIO BY SOMETHING OTHER THAN A FILE.
        #
        # `/sfx/{key}` is a sample named by its id, and it is the whole of
        # the sfx lane's traffic: 4,512 of the gate's 4,991 refusals in
        # nineteen hours were "the final audio is not available" about a
        # sting that played perfectly well. `/ads-audio/` and
        # `/upstairs-audio/` are durable mp3s kept outside /media.
        #
        # ONLY THE FREE WAY BACK. `sfx_by_id`'s other roads end in a walk
        # of the CIFS share and this runs on the event loop; #1307 already
        # keeps id -> path as a dict, written at the moment the id is
        # minted, so an id that exists can always be looked up here.
        if raw.startswith("/sfx/") and re.fullmatch(r"[a-f0-9]{16}", key):
            known = str(_SFX_ID_REVERSE.get(key) or "")
            if not known:
                return None
            sample = Path(known)
            # WHAT THE BOX IS ACTUALLY HANDED. `/sfx/{key}` serves the
            # levelled copy when there is one, not the sample as it sits
            # on the share - so that is the file whose bytes this names.
            # Cache-only: making one here would put a wave decode on the
            # event loop for every sting the station plays.
            try:
                levelled = sfx_levelled_name(sample)
            except Exception:  # noqa: BLE001
                levelled = None
            if levelled is not None and levelled.is_file():
                return levelled
            return sample if sample.is_file() else None
        for prefix, room in (("/ads-audio/", PRODUCED_ADS_DIR),
                             ("/upstairs-audio/", UPSTAIRS_AUDIO_DIR)):
            if raw.startswith(prefix):
                guess = room / raw.removeprefix(prefix)
                return guess if guess.is_file() else None
        return None
'''


# --------------------------------------------------------------------------
# 3. Admitting ONE LINE, and taking it back.
# --------------------------------------------------------------------------

ADMIT_LINE_ANCHOR = """def admission_state(limit: int = 40) -> dict[str, Any]:
"""

ADMIT_LINE_NEW = '''def admission_admit_line(clip: Any, *, who: str = "", kind: str = "",
                         text: str = "", name: str = "", line_id: str = "",
                         rows: Any = None, length: float = 0.0,
                         producer: str = "") -> str:
    """ADMIT ONE SPOKEN LINE, with its cue sheet, BEFORE either transport
    is touched. Returns the occurrence id, or "" - and never raises.

    `_dj_speak_floorless` is this station's busiest producer of broadcast
    audio and it had no submission of its own: 9,137 of its dispatches in
    nineteen hours reached the gate as `unadmitted` and were written into
    the census after the fact. A census of what happened is not a committed
    sequence, and that difference is the whole reason the gate could not be
    enforced on the speech lane.

    A line with SFX welded into it already HAS a cue sheet - the stream's
    own rows, the very numbers the booth marker is driven off - and it is
    used as it stands. A plain line is one cue covering the whole file,
    which is the honest shape: there is nothing inside it to point at."""
    controller = admission_controller()
    if controller is None or _admission_module is None or not clip:
        return ""
    try:
        path = str((clip or {}).get("path") or "")
        if not path:
            return ""
        seconds = float(length or 0.0)
        if seconds <= 0:
            seconds = float((clip or {}).get("seconds") or 0.0)
        if seconds <= 0:
            # Off the wav header itself - 64 bytes, no ffprobe, no decode.
            seconds = float(_admission_module.audio_seconds_hint(
                path, _admission_resolve) or 0.0)
        cues = [row for row in (rows or []) if isinstance(row, dict)]
        if not cues:
            cues = [{"id": str(line_id or ""), "who": str(who or ""),
                     "name": str(name or ""), "kind": str(kind or ""),
                     "text": str(text or ""), "from": 0.0,
                     "until": max(0.05, seconds)}]
        candidate = _admission_module.welded_round_candidate(
            path=path, sig=str((clip or {}).get("sig") or ""),
            rows=cues, length=max(0.05, seconds),
            producer=producer or _admission_producer(2),
            lane=_admission_lane(path, kind),
            label=str((clip or {}).get("label") or "")[:120])
        record = controller.admit(candidate)
        return str(record.get("occurrence_id") or "")
    except Exception as exc:  # noqa: BLE001
        # A line that cannot be admitted is NOT stopped here: in observe
        # mode the transports record it as an unadmitted dispatch, which is
        # exactly the measurement this road exists to move.
        try:
            pipeline_log("air", "a line could not be admitted",
                         extra="%r" % (exc,))
        except Exception:  # noqa: BLE001
            pass
        return ""


def admission_withdraw(occurrence_id: str, why: str) -> bool:
    """Take back a committed occurrence that is not going to air after all.

    Its POSITION stands and the script keeps the hole, marked. An admitted
    occurrence that is never dispatched and never withdrawn is worse than
    either: with ordering enforced it stands in front of every line behind
    it for ever."""
    if not occurrence_id:
        return False
    controller = admission_controller()
    if controller is None:
        return False
    try:
        return bool(controller.withdraw(str(occurrence_id), str(why)))
    except Exception:  # noqa: BLE001
        return False


def admission_state(limit: int = 40) -> dict[str, Any]:
'''


# --------------------------------------------------------------------------
# 4. The busiest producer commits first.
# --------------------------------------------------------------------------

PAGED_ANCHOR = """    paged = False
    if page_carries_live(voice_to, to_box, box_down):          # #1118
"""

PAGED_NEW = '''    # --- broadcast admission (#1338) ---
    # ADMITTED BEFORE EITHER TRANSPORT IS TOUCHED. Every veto is above this
    # line - the repeat check, the tint gate, the render itself - so this is
    # the first moment the audit's precondition holds: the final audio
    # exists and its cue offsets are known, before anything is committed.
    #
    # When a sting is welded into the line, the stream's rows ARE the cue
    # sheet; the marker in the booth is already driven off them.
    _line_occurrence = ""
    if clip:
        _line_occurrence = admission_admit_line(
            clip, who=who, kind=kind, text=spoken, name=name,
            line_id=line_id,
            rows=((_sfx_stream.get("rows") or []) if _sfx_stream else None),
            length=float((_sfx_stream or {}).get("length") or 0.0),
            producer="_dj_speak_floorless")
    # --- broadcast admission (#1338) --- end
    paged = False
    if page_carries_live(voice_to, to_box, box_down):          # #1118
'''

WITHDRAW_ANCHOR = """                      "DJ voice rendered to nothing for the page feed")

    # #776: this used to sleep for the length of the clip so the browser
"""

WITHDRAW_NEW = '''                      "DJ voice rendered to nothing for the page feed")

    # --- broadcast admission (#1338) ---
    # AND TAKEN BACK IF NOBODY IS GOING TO CARRY IT. The page declined to
    # take it and the box is not being asked, so this line is not going to
    # air; leaving it committed would stand it in front of every line
    # behind it once ordering is enforced. The position stays, marked,
    # which is #1339's rule for a withdrawn round applied to one line.
    if _line_occurrence and not paged and not to_box:
        admission_withdraw(_line_occurrence,
                           "neither transport carried the line")
        _line_occurrence = ""
    # --- broadcast admission (#1338) --- end

    # #776: this used to sleep for the length of the clip so the browser
'''


EDITS = [("the levelled copy's name, split out",
          LEVELNAME_DEF_ANCHOR, LEVELNAME_DEF_NEW),
         ("sfx_levelled reads that name", LEVELNAME_ANCHOR, LEVELNAME_NEW),
         ("the resolver learns /sfx, /ads-audio and /upstairs-audio",
          RESOLVE_ANCHOR, RESOLVE_NEW),
         ("admission_admit_line and admission_withdraw",
          ADMIT_LINE_ANCHOR, ADMIT_LINE_NEW),
         ("_dj_speak_floorless commits before it dispatches",
          PAGED_ANCHOR, PAGED_NEW),
         ("...and withdraws when nothing will carry it",
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
