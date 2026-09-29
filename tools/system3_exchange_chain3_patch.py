"""[s3-chain3] app.py: the shelf's repair prompt names the speaker markers one at
a time. "using only the listed A:/B:/C:/D: marker" taught the small writer the
token "A:/B:" ([s3-slash], the same cure its tools/turn_edge_slash_patch.py gives
the phone rewrite and the banter beat prompts). One edit, inside the
[s3-chain2] shelf text; ship the reconciled tools/system3_exchange_chain_patch.py
and tools/system3_exchange_chain2_patch.py with it (their stored text carries
this wording), so all three --check 2 afterwards.
--check exits 0 ready / 2 applied / 1 anchors missing; --apply idempotent, atomic, LF.
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('repair-prompt-markers-one-at-a-time',
     '                     "immediately above it." % (why, k + 1) if why else "")\n                  + "\\nOutput exactly one line per listed turn using only the listed A:/B:/C:/D: marker. "\n                    "No preface, labels, markdown or stage directions.")\n        raw = await ask_model(prompt, limit=min(2800, max(900, 450 * len(rows))), spice=0.45, num_ctx=16384,\n',
     '                     "immediately above it." % (why, k + 1) if why else "")\n                  + "\\nOutput exactly one line per listed turn. Start each line with its speaker\'s letter and "\n                    "a colon, once - A: then the words, B: then the words - never two markers together. "\n                    "No preface, labels, markdown or stage directions.")   # [s3-slash] one marker at a time\n        raw = await ask_model(prompt, limit=min(2800, max(900, 450 * len(rows))), spice=0.45, num_ctx=16384,\n',
     1),
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
    target = next((a for a in argv if not a.startswith("--")), "app.py")
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
