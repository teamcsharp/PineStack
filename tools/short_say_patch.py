r"""[short-say] the Nabu says an export in one short sentence, and a place by its
last folder.

2026-09-30, the operator: "why is the LLM's reply so long?" and "When it
comes to reading file names, just have the LLM tell me the last folder of
the file name. They don't have to read me the whole path." The screen, Pine
Cam and audio-cut replies read out \\10.89.1.125\QuickSwap\PineBoxRecordings
and the whole file name, character by character, on the speaker.

Usage (ON THE HOST): python3 tools/short_say_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[short-say]"

EDITS = [
    ("helper",
     r'''def export_cam_request(cmd: dict[str, Any]) -> str:
''',
     r'''def spoken_folder(path: str) -> str:
    """[short-say] a place as the Nabu says it: the last folder, never the path."""
    p = str(path or "").replace("\\", "/").rstrip("/")
    return p.rsplit("/", 1)[-1] or p


def export_cam_request(cmd: dict[str, Any]) -> str:
'''),
    ("screen words",
     r'''    words = "Exporting the last %s of %s%s. " % (
        _screen_export_minutes(want), SCREEN_EXPORT_NAMES[target],
        " with its sound" if target == "tab" else "")
    if asked > hold:
        words += "It only keeps the last %s, so that is what it will cut. " % _screen_export_minutes(hold)
    who = "The tablet" if target == "tab" else "The Pine Box app"
    if dest:
        words += ("%s cuts it from its replay ring and the Pine Box desk carries it to %s "
                  "as %s." % (who, dest, name))
    else:
        words += ("%s cuts it from its replay ring; no export folder is set, so it stays in "
                  "data/exports as %s." % (who, name))
    return words
''',
     r'''    words = "Exporting the last %s of %s to %s." % (                 # [short-say]
        _screen_export_minutes(want), "the PineTab" if target == "tab" else "the Pine Box app",
        spoken_folder(dest) if dest else "the station's exports")
    if asked > hold:
        words += " It only keeps the last %s." % _screen_export_minutes(hold)
    return words
'''),
    ("cam words",
     r'''    words = "Exporting the last %s of the Pine Cam's footage. " % mins
    if asked > want:
        words += "A cut holds at most %s, so that is what it will take. " % _screen_export_minutes(PINELINK_CUT_MOST)
    if short:                                               # [cam-rotate]
        words += ("The Pine Cam only keeps its newest %d files, so it can give about %d minutes. "
                  % (pinecam_keep_segments(), int((hi - oldest) // 60)))
    if stale > 120:
        words += ("The camera stopped recording %d minutes ago, so it is the last %s before that. "
                  % (int(stale // 60), mins))
    if dest:
        words += "The Pine Box desk carries it to %s as %s." % (dest, name)
    else:
        words += "No export folder is set, so it stays with the Pine Cam's cuts."
    return words
''',
     r'''    words = "Exporting the last %s of the Pine Cam to %s." % (          # [short-say]
        mins, spoken_folder(dest) if dest else "its cuts")
    if short:                                               # [cam-rotate]
        words += " It only keeps about %d minutes." % int((hi - oldest) // 60)
    elif asked > want:
        words += " A cut holds at most %s." % _screen_export_minutes(PINELINK_CUT_MOST)
    if stale > 120:
        words += " The camera stopped %d minutes ago." % int(stale // 60)
    return words
'''),
    ("audio where",
     r'''    where = export_desk_dir() or export_host_words(export_dir_path())   # #1114
''',
     r'''    where = (spoken_folder(export_desk_dir()) if export_desk_dir()      # #1114 [short-say]
             else export_host_words(export_dir_path()))
'''),
    ("near miss",
     r'''    return ("I heard an export order but could not tell what to cut, so nothing was exported. "
            "I heard: \"%s\". Say \"export the last five minutes of the pine tab\" for the tablet's "
            "screen, \"... of the pine cam\" for the camera, \"... of the pine app\" for the desk, "
            "or \"... of the broadcast\" for the audio." % heard)
''',
     r'''    return ("I couldn't tell what to export, so nothing was exported. I heard: \"%s\". "   # [short-say]
            "Say: export the last five minutes of the pine tab - or the pine cam, the pine app, "
            "or the broadcast." % heard)
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
    shutil.copy(path, "/tmp/app.py.bak-short-say")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
