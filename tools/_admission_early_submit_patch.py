#!/usr/bin/env python3
"""Every producer that puts audio on the air commits it first.

    docs/notes/admission-and-playout-2026-09-15.md, "What remains":

        Early submit for the other 29 producers. They are all *gated*, and
        the census names them; only the burst road *submits ahead*. Each
        one that gets an early submit moves from `would_refuse:unadmitted`
        to `admitted`, and step 2 of the procedure is what says which ones
        matter.

This is step 2 answered.  Nineteen hours of the observe-mode census named
exactly five producers between the gate and enforcement:

    lane     producer                unadmitted dispatches
    speech   _dj_speak_floorless     9,192  (+209 on the station lane)
    sfx      dj_sting                4,505
    speech   _air_produced_ad          353
    speech   page_recovery_start        79
    speech   dj_upstairs_page           45
    sfx      sfx_video_cue_api          11
    sfx      dj_sfx_play                 1

`_dj_speak_floorless` is done by `_admission_reach_patch.py` (#1338).  This
patch is the other six, and after it the whole census should be producers
committing before they dispatch.

Run from the repo root (or with --file pointing at the deployed copy):

    python tools/_admission_early_submit_patch.py --check
    python tools/_admission_early_submit_patch.py
    python tools/_admission_early_submit_patch.py --revert

REQUIRES `_admission_reach_patch.py` to be applied first: every edit here
calls `admission_admit_line`, which that patch installs.  The check refuses
if it is not there.

WHAT AN EARLY SUBMIT IS, AND IS NOT
-----------------------------------

It is `admission_admit_line(clip, ...)` immediately before the first
transport call, once every veto above it has passed.  The gate then finds
a claim instead of an unadmitted dispatch, and `enforce` on that lane stops
being an instruction to go silent.

It is NOT a second gate and it does not stop anything: the helper returns
"" on any refusal and the road carries on exactly as it did.  Two roads -
the sting and the produced ad - can decide AFTER committing that nothing
will carry the audio; those two withdraw what they committed, so the
script keeps a marked hole instead of a line that stands in front of every
line behind it for ever.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = "app.py"
MARK = "#1339"
NEEDS = "def admission_admit_line("


# --------------------------------------------------------------------------
# 1. dj_sting - 4,505 of them, the whole sfx lane.
# --------------------------------------------------------------------------

STING_ANCHOR = """    _sting_started = time.monotonic()
"""

STING_NEW = '''    # --- broadcast admission (#1339) ---
    # COMMITTED BEFORE EITHER TRANSPORT. Every veto - the cadence, the
    # rest between clips, the pick itself - is above this line, and the
    # sample is chosen, so this is the first moment the gate can be told
    # what is about to go out. 4,505 stings reached it the other way
    # round in nineteen hours, and `enforce sfx` would have refused every
    # one of them.
    #
    # `seconds` is deliberately not measured here: the sample lives on
    # the share and the gate reads the length off the header of the file
    # it resolves, which is the levelled copy on local disk.
    _sting_occurrence = admission_admit_line(
        {"path": f"/sfx/{key}", "sig": signature},
        who=who, kind="sfx", text=sample.stem, name=sample.stem,
        line_id=key, producer="dj_sting")
    # --- broadcast admission (#1339) --- end
    _sting_started = time.monotonic()
'''

STING_WITHDRAW_ANCHOR = """    else:
        pipeline_log("drop", f"sting {sample.stem} never sounded (#738)")
"""

STING_WITHDRAW_NEW = '''    else:
        # #1339: and it was committed a moment ago, so take it back. The
        # position stands and the script keeps the hole, marked "never
        # sounded" - which is the same thing #738 says in the log, said
        # where the committed sequence can see it.
        admission_withdraw(_sting_occurrence, "the sting never sounded")
        pipeline_log("drop", f"sting {sample.stem} never sounded (#738)")
'''


# --------------------------------------------------------------------------
# 1b. _dj_speak_floorless's OTHER dispatch - the box was busy, the clip is
#     held for replay, and in `both` mode the page carries it anyway.
# --------------------------------------------------------------------------

HELD_ANCHOR = """            if voice_to == "both":
                page_delivery = page_feed_append({
                    "url": f"{clip['path']}?t={clip['sig']}",
"""

HELD_NEW = """            # #1339: THE SECOND DOOR OUT OF THIS FUNCTION. #1338 commits
            # the line on the ordinary road; this is the road taken when
            # the box was answering someone, and in `both` mode the page
            # carries the line live while the box keeps its copy on the
            # hold shelf. It is a broadcast, so it is committed too - and
            # the held copy's own replay later is a second dispatch and
            # gets a second occurrence, which is the audit's rule for the
            # same audio played twice.
            if voice_to == "both":
                _line_occurrence = admission_admit_line(
                    clip, who=who, kind=kind, text=spoken, name=name,
                    line_id=line_id,
                    rows=((_sfx_stream.get("rows") or [])
                          if _sfx_stream else None),
                    length=float(_sfx_stream.get("length") or 0),
                    producer="_dj_speak_floorless")
                page_delivery = page_feed_append({
                    "url": f"{clip['path']}?t={clip['sig']}",
"""


# --------------------------------------------------------------------------
# 2. dj_sfx_play - the operator's own button.
# --------------------------------------------------------------------------

SFX_PLAY_ANCHOR = """    key = sfx_id(path)
    signature = media_sign(key)
    page_feed_append({                  # #1147: honest broadcast stamp
"""

SFX_PLAY_NEW = '''    key = sfx_id(path)
    signature = media_sign(key)
    # #1339: the button that proves the wiring proves this part of it too.
    admission_admit_line({"path": f"/sfx/{key}", "sig": signature},
                         who="board", kind="sfx", text=path.stem,
                         name=path.stem, line_id=key, producer="dj_sfx_play")
    page_feed_append({                  # #1147: honest broadcast stamp
'''


# --------------------------------------------------------------------------
# 3. sfx_video_cue_api - a picture is broadcast too.
# --------------------------------------------------------------------------

VIDEO_CUE_ANCHOR = """    try:
        page_feed_append(dict(clip))
"""

VIDEO_CUE_NEW = '''    # #1339: a clip with a picture goes out on the set, and the set is
    # broadcast. `seconds` is already known here - the book pick carries
    # it - so the cue covers the real length rather than a guess.
    admission_admit_line({"path": f"/sfx/{key}", "sig": signature},
                         who="board", kind="sfx", text=pick.stem,
                         name=pick.stem, line_id=key, length=float(seconds),
                         producer="sfx_video_cue_api")
    try:
        page_feed_append(dict(clip))
'''


# --------------------------------------------------------------------------
# 4. _air_produced_ad - a finished spot, and it can end up carried by
#    nobody, which is exactly why it withdraws.
# --------------------------------------------------------------------------

AD_ANCHOR = '''    page_delivery = ""
    box_played = False
    try:
'''

AD_NEW = '''    page_delivery = ""
    box_played = False
    # --- broadcast admission (#1339) ---
    # The spot is one finished audio object and it exists on disk - that
    # was checked at the top of this function - so the gate can name it
    # before either road is asked to carry it.
    _ad_occurrence = admission_admit_line(
        {"path": path, "sig": sig}, who="dj", kind="ad",
        text=str(entry.get("text") or label), name=label,
        line_id=str(booth_row.get("id") or ""), producer="_air_produced_ad")
    # --- broadcast admission (#1339) --- end
    try:
'''

AD_WITHDRAW_ANCHOR = '''    finally:
        if not (page_delivery or box_played) and _RADIO.get("ad_now") is this_ad_now:
'''

AD_WITHDRAW_NEW = '''    finally:
        # #1339: nobody carried it. The break did not happen, and the
        # committed sequence has to say so rather than hold a position
        # open for a spot that is not coming.
        if not (page_delivery or box_played):
            admission_withdraw(_ad_occurrence,
                               "neither transport carried the spot")
        if not (page_delivery or box_played) and _RADIO.get("ad_now") is this_ad_now:
'''


# --------------------------------------------------------------------------
# 5. dj_upstairs_page - always carried by one road or the other.
# --------------------------------------------------------------------------

UPSTAIRS_ANCHOR = """    # (c) PLAY IT — the point of the whole request is that you hear him.
    to = _RADIO.get("voice_to") or "box"
"""

UPSTAIRS_NEW = '''    # #1339: committed before (c). Whichever way `voice_to` is set, one
    # of the two roads below carries it, so there is no withdrawal here -
    # the only way this one does not air is an exception, and an
    # exception leaves the occurrence admitted and visible, which is the
    # honest record of what happened.
    admission_admit_line({"path": path, "sig": sig}, who="board",
                         kind="upstairs", text=str(made.get("text") or ""),
                         name="upstairs", line_id=str(made.get("id") or ""),
                         producer="dj_upstairs_page")
    # (c) PLAY IT — the point of the whole request is that you hear him.
    to = _RADIO.get("voice_to") or "box"
'''


# --------------------------------------------------------------------------
# 6. page_recovery_start - the FIFO that survives a deploy.
# --------------------------------------------------------------------------

RECOVERY_ANCHOR = """            delivery = page_feed_append(clip)
"""

RECOVERY_NEW = '''            # #1339: a preserved delivery is being broadcast again, and
            # it is a NEW occurrence - the audit's reusable-sample rule.
            # A clip whose media did not survive the restart cannot be
            # named and is not admitted; the append below still runs, and
            # the census records it as it always did.
            _rec_url = str(clip.get("url") or "")
            _rec_rows = ((clip.get("stream") or {}).get("rows") or None)
            _rec_len = float((clip.get("stream") or {}).get("length") or 0.0)
            if _rec_rows and _rec_len <= 0:
                # A preserved burst knows where its turns are even when
                # nobody wrote down how long the whole file was; the last
                # cue's end IS that length, and a cue sheet running past
                # the end of its audio is refused rather than trimmed.
                _rec_len = max((float(r.get("until") or 0.0)
                                for r in _rec_rows if isinstance(r, dict)),
                               default=0.0)
            admission_admit_line(
                {"path": _rec_url.split("?")[0],
                 "sig": (_rec_url.split("?t=", 1)[1].split("&")[0]
                         if "?t=" in _rec_url else "")},
                who=str(clip.get("who") or ""),
                kind=str(clip.get("kind") or ""),
                text=str(clip.get("text") or ""),
                line_id=str(clip.get("row_id") or clip.get("delivery_id") or ""),
                rows=_rec_rows, length=_rec_len,
                producer="page_recovery_start")
            delivery = page_feed_append(clip)
'''


EDITS = [("the held-and-paged line commits too", HELD_ANCHOR, HELD_NEW),
         ("dj_sting commits before it dispatches", STING_ANCHOR, STING_NEW),
         ("...and withdraws a sting that never sounded",
          STING_WITHDRAW_ANCHOR, STING_WITHDRAW_NEW),
         ("dj_sfx_play commits", SFX_PLAY_ANCHOR, SFX_PLAY_NEW),
         ("sfx_video_cue_api commits", VIDEO_CUE_ANCHOR, VIDEO_CUE_NEW),
         ("_air_produced_ad commits", AD_ANCHOR, AD_NEW),
         ("...and withdraws a spot nobody carried",
          AD_WITHDRAW_ANCHOR, AD_WITHDRAW_NEW),
         ("dj_upstairs_page commits", UPSTAIRS_ANCHOR, UPSTAIRS_NEW),
         ("page_recovery_start commits each preserved delivery",
          RECOVERY_ANCHOR, RECOVERY_NEW)]


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
        print("admission_admit_line is not in app.py - apply "
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
