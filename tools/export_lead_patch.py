"""[export-lead] a spoken screen order survives the Nabu's ears and the air.

2026-09-30, the operator: "I'm trying to tell the LLM to export the last 5
minutes of the pine tab display and it failed ... I need to be able to
export the screen effortlessly." What the Nabu actually delivered:

  "export the last three minutes of KindTab"              -> an AUDIO cut
  "Export the last three minutes of Pine Tab Radio.  I heard what you
   said. Go ahead. The image announces complete."          -> the chat model
  "export the last minute of part-time broadcast  I'm still big for ..."
                                                           -> the chat model

1. The Nabu keeps listening after the order and hears the broadcast. The
   #1154 residue rule (more than three leftover words = somebody else's
   sentence) threw those orders away. A screen order that LEADS the
   utterance - nothing but pleasantries before the verb, the screen named
   right after the window - is the operator's, whatever the air adds after.
2. The ears: "Pine Tap", "KindTab", "part-time" are the PineTab.
3. A failed parse fell to the chat model, which answered "I'm on it ...
   sending it straight to the Pine Box desk" and did nothing. An utterance
   that opens as an export order and still cannot be read now gets an
   honest answer: nothing was exported, what was heard, what to say.

Usage (ON THE HOST): python3 tools/export_lead_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[export-lead]"

EDITS = [
    ("ears",
     '''    r"pine\\s*ta[bp](?:let)?|pineta[bp]|tablet|"   # [screen-export-claim] "tap": the Nabu's ear
''',
     '''    r"(?:pine|kind|pint|pain|paint|pie|part|find|mind|fine)[\\s-]*(?:ta[bp]|tub|time)(?:let)?|tablet|"   # [export-lead] "Pine Tap", "KindTab", "part-time"
'''),
    ("lead",
     '''    left = [w for w in residue.split() if w not in _EXPORT_FILLER]
    if len(left) > 3:
        return None
    if unit.startswith(("sentence", "line", "piece", "bit", "exchange",
''',
     '''    left = [w for w in residue.split() if w not in _EXPORT_FILLER]
    if len(left) > 3:
        # [export-lead] the Nabu hears the air after the order: a screen order
        # that LEADS the utterance, the screen named right after the window,
        # is the operator's whatever follows it.
        _scr = _EXPORT_SCREEN_RX.search(lowered, got.end())
        _lead = [w for w in re.findall(r"[a-z']+", lowered[:got.start()]) if w not in _EXPORT_FILLER]
        if not (_scr and _scr.start() - got.end() <= 3 and not _lead):
            return None
    if unit.startswith(("sentence", "line", "piece", "bit", "exchange",
'''),
    ("near miss",
     '''def parse_paper_command(text: str) -> str:
''',
     '''# [export-lead] an utterance that OPENS as an export order but cannot be read.
# It must never reach the chat model, which answers "I'm on it" and does nothing.
_EXPORT_NEAR_RX = re.compile(
    r"^\\W*(?:(?:please|hey|ok|okay|yo|so|can you|could you|would you)\\W+)*"
    r"(?:export|save out|save|cut|clip|grab|record out)\\b.{0,40}?\\b(?:last|past|previous)\\b"
    r".{0,30}?\\b(?:seconds?|secs?|minutes?|mins?|hours?)\\b")


def export_near_miss(text: str) -> str:
    """[export-lead] what to SAY when an export order could not be read, or ''."""
    lowered = " ".join(str(text or "").lower().split())
    if not lowered or not _EXPORT_NEAR_RX.search(lowered) or parse_export_command(text):
        return ""
    heard = re.split(r"(?<=[.!?])\\s+", " ".join(str(text).split()))[0]
    if len(heard) > 140:
        heard = heard[:140].rsplit(" ", 1)[0] + " ..."
    return ("I heard an export order but could not tell what to cut, so nothing was exported. "
            "I heard: \\"%s\\". Say \\"export the last five minutes of the pine tab\\" for the tablet's "
            "screen, \\"... of the pine cam\\" for the camera, \\"... of the pine app\\" for the desk, "
            "or \\"... of the broadcast\\" for the audio." % heard)


def parse_paper_command(text: str) -> str:
'''),
    ("dispatch",
     '''        said = await export_command_run(export_cmd, settings)
        return said, {**feature_meta, "model": "cutter"}
''',
     '''        said = await export_command_run(export_cmd, settings)
        return said, {**feature_meta, "model": "cutter"}
    elif export_near_miss(user_text):                        # [export-lead] never the chat model
        feature_meta["export_command"] = True
        return export_near_miss(user_text), {**feature_meta, "model": "cutter"}
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
    shutil.copy(path, "/tmp/app.py.bak-export-lead")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
