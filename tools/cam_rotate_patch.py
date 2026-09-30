"""[cam-rotate] the station's words for a Pine Cam that keeps five files.

2026-09-30, the operator: "Set the amount of pine cam videos being cached to
a maximum of five ... a rotating stock of five that are being recorded. And
then I'll just extract the clip if I want it, or tell it to export it, but
otherwise only five videos max."

tools/pinelink.py owns the rotation (trim_old keeps the newest keep_segments
files, at every start and every 30 s while recording). This teaches the
station what it now holds: /api/pinecam/storage says how many files are
kept and how far back they reach, a cut outside that says so instead of
"two days", and a spoken export asked for more than is kept says what it
will take.

Usage (ON THE HOST): python3 tools/cam_rotate_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[cam-rotate]"

EDITS = [
    ("cut words",
     '''                "say": "nothing kept covers that span - the footage only "
                       "goes back two days"}
''',
     '''                "say": "nothing kept covers that span - the Pine Cam keeps "
                       "only its newest %d five-minute files" % pinecam_keep_segments()}   # [cam-rotate]
'''),
    ("cut doc",
     '''    that is still kept, which is two days.
''',
     '''    that is still kept - the newest keep_segments five-minute files ([cam-rotate]).
'''),
    ("storage",
     '''            "dest": pinecam_export_dest(), "clips_host": share_path_of(pinelink_clips_dir())}
''',
     '''            "dest": pinecam_export_dest(), "clips_host": share_path_of(pinelink_clips_dir()),
            "keep_segments": pinecam_keep_segments(),                      # [cam-rotate]
            "keep_say": "The Pine Cam keeps only its newest %d five-minute files (about %d minutes); "
                        "older footage is deleted as it records. Export a clip to keep it."
                        % (pinecam_keep_segments(), 5 * pinecam_keep_segments())}
'''),
    ("keep helper",
     '''def pinecam_storage() -> dict[str, Any]:
''',
     '''def pinecam_keep_segments() -> int:
    """[cam-rotate] the footage files tools/pinelink.py keeps (its KEEP_SEGMENTS,
    or pinelink_pref.json keep_segments) - read the same way it reads it."""
    try:
        n = int(pinelink_prefs_read().get("keep_segments") or 5)
    except Exception:  # noqa: BLE001
        n = 5
    return max(2, min(n, 576))


def pinecam_storage() -> dict[str, Any]:
'''),
    ("export words",
     '''    if stale > 120:                       # the camera stopped: its last minutes
        hi = newest
''',
     '''    if stale > 120:                       # the camera stopped: its last minutes
        hi = newest
    try:                                                    # [cam-rotate]
        oldest = min((pinelink_segment_epoch(p.stem) or hi) for p in pinelink_clips_dir().glob("*.mp4")
                     if _PINECAM_SEGMENT.match(p.name))
    except Exception:  # noqa: BLE001
        oldest = hi - want
    short = hi - oldest < want - 30
'''),
    ("export short",
     '''    if asked > want:
        words += "A cut holds at most %s, so that is what it will take. " % _screen_export_minutes(PINELINK_CUT_MOST)
''',
     '''    if asked > want:
        words += "A cut holds at most %s, so that is what it will take. " % _screen_export_minutes(PINELINK_CUT_MOST)
    if short:                                               # [cam-rotate]
        words += ("The Pine Cam only keeps its newest %d files, so it can give about %d minutes. "
                  % (pinecam_keep_segments(), int((hi - oldest) // 60)))
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-cam-rotate")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
