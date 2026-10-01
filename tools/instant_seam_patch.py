"""[reply-gap:instant] a 0 s pause lays no pad at the seam.

2026-09-30, the operator: "Allow me to be able to set the pause between replies
as low as zero ... back to back seamless." reply_gap.py now allows 0. The
welded round's graph pads every seam with `apad=pad_dur=<beat>`; apad with no
length pads FOREVER, so a 0 beat must not lean on how pad_dur=0 is read - the
filter is simply left out and the next clip follows the trimmed sliver.

Usage (ON THE HOST): python3 tools/instant_seam_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[reply-gap:instant]"

OLD = '''            _beat = (beats[i] if beats is not None and i < len(beats)
                     else round(random.uniform(*CONCAT_BEAT), 3))
            _leg += f",apad=pad_dur={_beat}"
'''
NEW = '''            _beat = (beats[i] if beats is not None and i < len(beats)
                     else round(random.uniform(*CONCAT_BEAT), 3))
            if float(_beat or 0) > 0:      # [reply-gap:instant] 0 = no seam at all
                _leg += f",apad=pad_dur={_beat}"
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-instant-seam")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
