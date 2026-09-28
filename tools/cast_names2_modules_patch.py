"""[cast-names] director.py names the SFX guy in the segment shape it writes.

The "sfx" beat said "the SFX guy puts something over the top of it". It says
"Sam, the SFX guy, puts something over the top of it" now - the name read at
clause time from app.py's cast_name (tools/cast_names2_patch.py hands it over
as director.CAST_NAME), so a renamed or rolled SFX guy is named too. Until
app.py has handed it over, or if it fails, he is Sam.

Same contract as the app.py tools: EDITS (name, old, new, count); --check
exits 0 ready / 2 applied / 1 missing; --apply is idempotent and atomic, LF.
    python tools/cast_names2_modules_patch.py director.py --apply
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("director-cast-hook",
     'DIRECTOR_BEAT_TYPES = {\n',
     '# [cast-names] who the SFX guy is. app.py hands this module its cast_name\n'
     '# (director.CAST_NAME = cast_name); until it has - or if it fails - he is\n'
     '# Sam. Read when a clause is written, so a rename reaches the next one.\n'
     'CAST_NAME: Any = None\n'
     '\n'
     '\n'
     'def _cast(role: str, default: str) -> str:\n'
     '    fn = CAST_NAME\n'
     '    try:\n'
     '        got = fn(role) if callable(fn) else ""\n'
     '    except Exception:  # noqa: BLE001 - a name is never worth a clause\n'
     '        got = ""\n'
     '    return str(got or default)\n'
     '\n'
     '\n'
     'def director_beat_words(what: str) -> str:\n'
     '    """[cast-names] A beat as the writing room reads it: the SFX guy by\n'
     '    his name."""\n'
     '    words = DIRECTOR_BEAT_TYPES.get(what, what)\n'
     '    return words.replace("{sfx}", _cast("sfxguy", "Sam")) if "{sfx}" in words else words\n'
     '\n'
     '\n'
     'DIRECTOR_BEAT_TYPES = {\n', 1),
    ("director-cast-sfx-beat",
     '    "sfx": "the SFX guy puts something over the top of it",\n',
     '    "sfx": "{sfx}, the SFX guy, puts something over the top of it",   # [cast-names]\n', 1),
    ("director-cast-clause",
     '                at, DIRECTOR_BEAT_TYPES.get(what, what),\n',
     '                at, director_beat_words(what),   # [cast-names] the SFX guy by name\n', 1),
    ("director-cast-graph",
     '            "types": dict(DIRECTOR_BEAT_TYPES),\n',
     '            "types": {k: director_beat_words(k) for k in DIRECTOR_BEAT_TYPES},   # [cast-names]\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "director.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
