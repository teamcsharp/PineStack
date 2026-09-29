#!/usr/bin/env python3
"""[h3-speak] system3_tables.py: the H3SPEAK node on the road register (not in the config hash)."""

# ---- the patch contract (marker-idempotent) --------------------------------
# --check PATH  exit 0 ready (every edit ready or applied, at least one ready),
#               2 applied (every edit applied), 1 missing (an anchor is gone).
# --apply PATH  applies the ready edits in order, writes LF atomically; exit 0
#               on success, 2 when there was nothing to do, 1 when missing.
# An edit is APPLIED when its marker (a line only its inserted text has) is in
# the file, READY when its anchor occurs exactly once, else MISSING.
import os
import sys
import tempfile


def state_of(text, edit):
    if edit["marker"] in text:
        return "applied"
    n = text.count(edit["anchor"])
    return "ready" if n == 1 else ("missing (anchor x%d)" % n)


def apply_one(text, edit):
    if edit["kind"] == "replace":
        return text.replace(edit["anchor"], edit["text"], 1)
    if edit["kind"] == "before":
        return text.replace(edit["anchor"], edit["text"] + edit["anchor"], 1)
    if edit["kind"] == "after":
        return text.replace(edit["anchor"], edit["anchor"] + edit["text"], 1)
    raise ValueError(edit["kind"])


def run(edits, argv):
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply PATH" % argv[0])
        return 1
    mode, path = argv[1], argv[2]
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    text = text.replace("\r\n", "\n")
    states = []
    work = text
    for e in edits:                     # sequential: a later anchor may sit in an earlier edit's text
        st = state_of(work, e)
        states.append(st)
        print("  %-10s %s" % (st.split(" ")[0], e["name"]) + ("" if st in ("ready", "applied") else "  <- " + st))
        if st == "ready":
            work = apply_one(work, e)
    if any(s not in ("ready", "applied") for s in states):
        print("MISSING: %d of %d edits" % (sum(1 for s in states if s not in ("ready", "applied")), len(edits)))
        return 1
    if all(s == "applied" for s in states):
        print("APPLIED: all %d edits" % len(edits))
        return 2
    if mode == "--check":
        print("READY: %d to apply, %d applied" % (states.count("ready"), states.count("applied")))
        return 0
    for e in edits:
        if e["marker"] not in work:
            print("apply failed: %s did not land" % e["name"])
            return 1
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".h3speak.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(work)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("applied %d edits -> %s" % (states.count("ready"), path))
    return 0


EDITS = [{'anchor': '     "what": "a stored or produced spot: the ad book\'s rows are the Rolodex, the pick is a '
            'recorded draw"},\n'
            ']\n',
  'kind': 'replace',
  'marker': '    {"id": "h3_speak", "label": "H3 video dialogue (H3SPEAK)", "shape": "node",',
  'name': 'ROAD_REGISTER: the H3SPEAK node',
  'text': '     "what": "a stored or produced spot: the ad book\'s rows are the Rolodex, the pick is a '
          'recorded draw"},\n'
          '    # [h3-speak] the words the people in the hourly H3 video say\n'
          '    {"id": "h3_speak", "label": "H3 video dialogue (H3SPEAK)", "shape": "node",\n'
          '     "writer": "h3_hourly_render -> h3_speak_gather / h3_speak_take (app.py)",\n'
          '     "hook": "the dice door: POOLS1 h3.speak_lean / h3.speak_count / h3.speak_forced; "\n'
          '             "picks h3.speak_line / h3.speak_sentences / h3.speak_doc",\n'
          '     "what": "the hourly H3 video\'s spoken line: a line or monologue a person was heard saying '
          'on air "\n'
          '             "(leaned on by its feeling), then 1-3 whole sentences of it that fit the clip - a '
          'Speakerbox "\n'
          '             "document when no aired line passes, the FORCED line when nothing does"},\n'
          ']\n'}]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
