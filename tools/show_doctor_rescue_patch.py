"""[show-doctor:rescue] the station's own rescue (#827) walks the new tree too.

"where are the DJs?" was answered by #827's rescue - the deep repair ladder
(the show, Home Assistant, the satellite, the music player, the wire, the
voice director, both engines) - before the show doctor could hear it. That
ladder knows none of today's faults: no owner of the air, lines nobody hears,
station IDs hiding a silent show. Whichever words the operator uses, the
spoken verdict now starts with what show_doctor() found and did.

Usage (ON THE HOST): python3 tools/show_doctor_rescue_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[show-doctor:rescue]"

OLD = '''        async def _rescue() -> None:
            try:
                got = await _deep_repair("spoken rescue (#827)")
'''
NEW = '''        async def _rescue() -> None:
            try:
                try:
                    _doc = await show_doctor()                       # [show-doctor:rescue]
                except Exception:  # noqa: BLE001
                    _doc = ""
                got = await _deep_repair("spoken rescue (#827)")
'''
OLD2 = '''                await home_assistant_say(line[:400], plain=True)'''
NEW2 = '''                if _doc and not _doc.startswith("The show is on and being heard"):   # [show-doctor:rescue]
                    line = _doc + " " + line
                await home_assistant_say(line[:400], plain=True)'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "rescue anchor %d" % src.count(OLD)
    i = src.index(OLD)
    j = src.index(OLD2, i)
    assert j - i < 2000, "say anchor too far"
    out = src[:i] + NEW + src[i + len(OLD):j + 0]
    out = src[:i] + NEW + src[i + len(OLD):j] + NEW2 + src[j + len(OLD2):]
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (2 edits)")
        return
    shutil.copy(path, "/tmp/app.py.bak-show-doctor-rescue")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
