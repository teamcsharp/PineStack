"""[show-doctor:reply] the rescue's chat answer says what the tree found and did.

"Make sure that I'm able to ask the LLM what happened to the DJs and they're
able to fix this." Asked in the app, "What happened to the DJs?", "where are
the DJs?", "fix the DJs" reach #827's rescue, whose reply was only "On it.
Running the full triage ..." - the findings went to the speaker afterwards.
The show doctor runs FIRST now (it is quick: no network), its words lead the
reply, and the deep repair rides behind it as before.

Usage (ON THE HOST): python3 tools/show_doctor_reply_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[show-doctor:reply]"

EDITS = [
    ("run first",
     '''    if is_radio_rescue(user_text):
        async def _rescue() -> None:
            try:
                try:
                    _doc = await show_doctor()                       # [show-doctor:rescue]
                except Exception:  # noqa: BLE001
                    _doc = ""
''',
     '''    if is_radio_rescue(user_text):
        try:
            _doc_now = await show_doctor()                           # [show-doctor:reply] first, and fast
        except Exception:  # noqa: BLE001
            _doc_now = ""

        async def _rescue() -> None:
            try:
                _doc = _doc_now                                       # [show-doctor:rescue]
'''),
    ("reply",
     '''        fire_and_forget(_rescue())
        feature_meta["system_status_used"] = True
        return ("On it. Running the full triage''',
     '''        fire_and_forget(_rescue())
        feature_meta["system_status_used"] = True
        return ((_doc_now + " ") if _doc_now else "") + ("On it. Running the full triage'''),
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
    shutil.copy(path, "/tmp/app.py.bak-show-doctor-reply")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
