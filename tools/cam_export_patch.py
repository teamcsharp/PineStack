"""[cam-export] "export the last X minutes of the pine cam".

2026-09-30, the operator: "If i ask for the pinecam recording then ill get it"
- and, asked whether to build the spoken order: "yes do that". Before this
"... of the pine cam" fell through the screen words to the AUDIO talk cut.

Every piece of the road already existed: the link keeps its footage as
five-minute fragmented segments (readable while written, [cam-fmp4]);
pinelink_cut_span(lo, hi) is the record button's own cut across them;
pinecam_encode applies the recordings preset; courier_add(..., "pinecam")
carries it to pinecam_export_dest() (PineBoxRecordings\\PineCam) exactly as
the Recordings tab's export button does. This is only the order: the screen
words learn the camera, and the runner cuts behind the reply.

Usage (ON THE HOST): python3 tools/cam_export_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[cam-export]"

EDITS = [
    ("camera words",
     '''    r"pine\\s*ta[bp](?:let)?|pineta[bp]|tablet|"   # [screen-export-claim] "tap": the Nabu's ear
''',
     '''    r"pine\\s*ta[bp](?:let)?|pineta[bp]|tablet|"   # [screen-export-claim] "tap": the Nabu's ear
    r"pine\\s*(?:cam(?:era)?|can)|pinecam|camera|cam|"   # [cam-export] the Pine Cam's footage
'''),
    ("camera target",
     '''    return "app" if re.search(r"\\bapp\\b|desk", said) else "tab"
''',
     '''    if re.search(r"cam|\\bcan\\b", said):                  # [cam-export]
        return "cam"
    return "app" if re.search(r"\\bapp\\b|desk", said) else "tab"
'''),
    ("runner",
     '''    if cmd.get("screen"):                                    # [screen-export]
        return export_screen_request(cmd)
''',
     '''    if cmd.get("screen") == "cam":                           # [cam-export]
        return export_cam_request(cmd)
    if cmd.get("screen"):                                    # [screen-export]
        return export_screen_request(cmd)
'''),
    ("cam request",
     '''def export_screen_request(cmd: dict[str, Any]) -> str:
''',
     '''def export_cam_request(cmd: dict[str, Any]) -> str:
    """[cam-export] "export the last X minutes of the pine cam": the window cut
    out of the footage the link keeps (the record button's own cut), in the
    recordings preset, carried to PineBoxRecordings\\\\PineCam like the
    Recordings tab's export. The cut runs behind the reply (#1153 pattern)."""
    asked = int(cmd.get("seconds") or 60)
    want = int(max(10, min(asked, PINELINK_CUT_MOST)))
    hi = time.time()
    try:
        newest = max((p.stat().st_mtime for p in pinelink_clips_dir().glob("*.mp4")
                      if _PINECAM_SEGMENT.match(p.name)), default=0.0)
    except Exception:  # noqa: BLE001
        newest = 0.0
    if not newest:
        return "The Pine Cam has no footage kept, so there is nothing to export."
    stale = hi - newest
    if stale > 120:                       # the camera stopped: its last minutes
        hi = newest
    mins = _screen_export_minutes(want)
    name = "pinecam-last-%s-%s.mp4" % (("%dmin" % (want // 60)) if want % 60 == 0 else ("%ds" % want),
                                       time.strftime("%Y%m%d-%H%M%S"))
    dest = pinecam_export_dest()

    async def _go() -> None:
        try:
            got = await asyncio.to_thread(pinelink_cut_span, hi - want, hi)
            if not got.get("ok"):
                note_action("the Pine Cam export did not finish: %s" % (got.get("say") or "no reason given"))
                return
            path = await asyncio.to_thread(pinecam_encode, PINELINK_CUTS / got["name"])
            if dest:
                await asyncio.to_thread(courier_add, path, dest, "pinecam", name=name)
                note_action("exported %s of the Pine Cam as %s - the desk carries it to %s" % (mins, name, dest))
            else:
                note_action("exported %s of the Pine Cam - no export folder, kept as %s" % (mins, path.name))
        except Exception as exc:  # noqa: BLE001
            note_action("the Pine Cam export did not finish: %s" % str(exc)[:160])

    fire_and_forget(_go())
    pipeline_log("air", "spoken: export the last %ss of the Pine Cam (%s)" % (want, name))
    words = "Exporting the last %s of the Pine Cam's footage. " % mins
    if asked > want:
        words += "A cut holds at most %s, so that is what it will take. " % _screen_export_minutes(PINELINK_CUT_MOST)
    if stale > 120:
        words += ("The camera stopped recording %d minutes ago, so it is the last %s before that. "
                  % (int(stale // 60), mins))
    if dest:
        words += "The Pine Box desk carries it to %s as %s." % (dest, name)
    else:
        words += "No export folder is set, so it stays with the Pine Cam's cuts."
    return words


def export_screen_request(cmd: dict[str, Any]) -> str:
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
    shutil.copy(path, "/tmp/app.py.bak-cam-export")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
