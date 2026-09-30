"""[cam-fmp4] the Pine Cam's kept footage survives a restart, and can be cut while
it is still being written.

The five-minute segments were plain mp4: the index (moov) is written when a
segment closes, so the segment a restart interrupts is unreadable for good -
measured 2026-09-30: 05-28-12 (48 MB) and 05-32-42 (32 MB), both cut short by a
link restart, answer "moov atom not found". A new Wi-Fi adaptor is a restart.
Now the segments are fragmented mp4 (empty moov, a fragment per keyframe): every
second on disk is readable - after a kill, and while it is being written.

The span cutter also kept a failed, near-empty output under the span's name and
then handed it back as "reused" the next time; it now removes it. The album
cut's mp4 tries at once, and waits for the next segment only when the cut comes
out empty (a plain segment from before this change, still open).

Usage (ON THE HOST): python3 tools/cam_fmp4_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[cam-fmp4]"
FRAG = "movflags=+frag_keyframe+empty_moov+default_base_moof"

LINK = [
    ('''        ("[f=segment:segment_time=%d:reset_timestamps=1:strftime=1]%s"
''', '''        # [cam-fmp4] fragmented: readable while written, and after any kill
        ("[f=segment:segment_time=%d:reset_timestamps=1:strftime=1"
         ":segment_format_options=''' + FRAG + ''']%s"
''', 1),
    ('''        "-reset_timestamps", "1", "-strftime", "1",
''', '''        "-reset_timestamps", "1", "-strftime", "1",
        "-segment_format_options", "''' + FRAG + '''",   # [cam-fmp4]
''', 1),
]

APP = [
    ('''    out = PINELINK_CUTS / ("cut_%d_%d.mp4" % (int(lo), int(hi)))
    if out.is_file():
        return {"ok": True, "name": out.name, "reused": True,
''', '''    out = PINELINK_CUTS / ("cut_%d_%d.mp4" % (int(lo), int(hi)))
    if out.is_file() and out.stat().st_size >= 1024:    # [cam-fmp4] never a failed one
        return {"ok": True, "name": out.name, "reused": True,
''', 1),
    ('''    if not out.is_file() or out.stat().st_size < 1024:
        return {"ok": False,
                "say": "the cut came out empty - the span may fall in a "
                       "gap between recordings"}
''', '''    if not out.is_file() or out.stat().st_size < 1024:
        try:
            out.unlink()                                  # [cam-fmp4] not kept to be "reused"
        except OSError:
            pass
        return {"ok": False,
                "say": "the cut came out empty - the span may fall in a "
                       "gap between recordings"}
''', 1),
    ('''    waited = 0.0
    while not _closed() and waited < 720:
        time.sleep(15)
        waited += 15
    parts = []
''', '''    waited = 3.0
    time.sleep(3)                  # [cam-fmp4] the span's last fragment reaches the disk
    parts = []
''', 1),
    ('''        got = pinelink_cut_span(a, b)
        if not got.get("ok"):
            out["why"] = str(got.get("say") or "the cut failed")
            continue
''', '''        got = pinelink_cut_span(a, b)
        while not got.get("ok") and waited < 720:        # [cam-fmp4] a plain segment still open
            if _closed():
                got = pinelink_cut_span(a, b)
                break
            time.sleep(15)
            waited += 15
        if not got.get("ok"):
            out["why"] = str(got.get("say") or "the cut failed")
            continue
''', 1),
]


def patch(path, edits, mode):
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-cam-fmp4" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/tools/pinelink.py", LINK, mode)
    patch(ROOT + "/app.py", APP, mode)
