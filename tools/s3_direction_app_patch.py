#!/usr/bin/env python3
"""[s3-direction] Three station blocks that fought the rolled feeling in the writer's prompt.

MEASURED 2026-09-29 (the exact prompts of 770 aired lines):
  1. dj_banter's one-call prompt says "Play it straight and let the specifics be
     the joke - mock outrage, raised eyebrows" in 363 prompts, the very rounds
     whose running order rolls fury, panic, delight. Under System 3 (_s3_owns) it
     now says each line is played as big as its DIRECTION FOR THIS LINE; off
     System 3 it is word for word what it was.
  2. The accent directive ("... and no interjection noises - no grunts, moans,
     hums or throat sounds") reached 348 prompts; the small writer read it as "no
     interjections" (0.3-1.4% of its lines carried a '!'). It now says a spoken
     exclamation is words, not a noise. The grunts, moans and hums stay out.
  3. The single-line road (dj_speak) adds perf_directive(vec) - the ES voice
     block read back as prose - so an "aversion, hard" line that the row told to
     SHOUT the station's name was also told "Write the delivery slow and
     deliberate, low energy, half switched off". A vector that carries an ES row
     now writes nothing there: the row's DIRECTION FOR THIS LINE says how. (The
     prompt-blocks door could switch `perf` off, but the live blocks section
     holds a kind its validator refuses - event_facts "claimed" - so a PUT of
     that section would 400; this is the narrower cure.)

Target: app.py under the repo root given (default "."). --check 0 ready /
2 applied / 1 missing or partial; --apply idempotent (markers), atomic, keeps the
file's line endings. ON THE HOST.
"""
import sys

APP = "app.py"

EDITS = [
    (APP, "banter-play-it-straight",
     '            f"{_pb(\'angle\', angle)}. Name the actual thing you are talking about. Play it "   # [s3-blocks]\n'
     '            "straight and let the specifics be the joke — mock outrage, "\n'
     '            "raised eyebrows, \'can you believe what he asked us for\'. "\n',
     '            f"{_pb(\'angle\', angle)}. Name the actual thing you are talking about. Play it "   # [s3-blocks]\n'
     '            + ("as BIG as each line\'s DIRECTION FOR THIS LINE says - the rolled feeling, over the top, "\n'
     '               "in the words themselves. " if _s3_owns else   # [s3-direction] the roll, not a register\n'
     '               "straight and let the specifics be the joke — mock outrage, "\n'
     '               "raised eyebrows, \'can you believe what he asked us for\'. ") + ""\n',
     '# [s3-direction] the roll, not a register\n'),

    (APP, "accent-interjections",
     '            "noises — no grunts, moans, hums or throat sounds in the text.\\n")\n',
     '            "noises — no grunts, moans, hums or throat sounds in the text. "\n'
     '            "A spoken exclamation is words, not a noise: \'Oh, come on!\', \'What?!\', "\n'
     '            "\'No way!\' are fine.\\n")                                          # [s3-direction]\n',
     '"\'No way!\' are fine.\\n")                                          # [s3-direction]\n'),

    (APP, "perf-yields-to-es",
     '    (and through its text, the TTS prosody) actually hears."""\n'
     '    if not vec:\n'
     '        return ""\n',
     '    (and through its text, the TTS prosody) actually hears."""\n'
     '    if not vec or vec.get("es"):   # [s3-direction] a rolled feeling: its DIRECTION FOR THIS LINE says how\n'
     '        return ""\n',
     '# [s3-direction] a rolled feeling: its DIRECTION FOR THIS LINE says how\n'),
]

# --- the edit engine (shared by the s3_direction_* tools) ---
import os
import tempfile
from pathlib import Path


def _load(root, rel):
    raw = (Path(root) / rel).read_bytes().decode("utf-8")
    crlf = raw.count("\r\n") > raw.count("\n") // 2 and "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _state(text, anchor, marker):
    m = text.count(marker)
    if m == 1:
        return "applied", ""
    a = text.count(anchor)
    if m == 0 and a == 1:
        return "ready", ""
    return "missing", "marker %d time(s), anchor %d time(s) (want 1)" % (m, a)


def check(root, edits, quiet=False):
    files = {}
    for e in edits:
        if e[0] not in files:
            files[e[0]] = _load(root, e[0])
    states = []
    for rel, name, anchor, new, marker in edits:
        st, why = _state(files[rel][0], anchor, marker)
        states.append((rel, name, st, why))
        if not quiet:
            print("%-8s %s: %s %s" % (st, rel, name, why))
    return states, files


def verdict(states):
    kinds = {s[2] for s in states}
    if kinds == {"ready"}:
        return 0
    if kinds == {"applied"}:
        return 2
    return 1


def apply(root, edits):
    states, files = check(root, edits, quiet=True)
    if verdict(states) == 2:
        print("already applied (%d edits)" % len(states))
        return 2
    if any(s[2] == "missing" for s in states):
        for s in states:
            print("%-8s %s: %s %s" % (s[2], s[0], s[1], s[3]))
        return 1
    texts = {rel: files[rel][0] for rel in files}
    for (rel, name, anchor, new, marker), (_r, _n, st, _w) in zip(edits, states):
        if st == "applied":
            continue
        assert texts[rel].count(anchor) == 1, name
        texts[rel] = texts[rel].replace(anchor, new, 1)
        assert texts[rel].count(marker) == 1, "%s: marker not unique after the edit" % name
    for rel, text in texts.items():
        path = Path(root) / rel
        out = text.replace("\n", "\r\n") if files[rel][1] else text
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(out.encode("utf-8"))
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, path)
    states, _f = check(root, edits, quiet=True)
    if verdict(states) != 2:
        print("apply did not leave every edit applied")
        return 1
    print("applied %d edits" % len(edits))
    return 0


def main(argv, edits, doc):
    args = [a for a in argv if not a.startswith("--")]
    root = args[0] if args else "."
    if "--apply" in argv:
        return apply(root, edits)
    if "--check" in argv:
        states, _f = check(root, edits)
        return verdict(states)
    print(doc)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], EDITS, __doc__))
