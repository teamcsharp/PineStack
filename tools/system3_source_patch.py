"""[s3-source] The initiator node's pinned SOURCE reaches the banter seed.

The operator: "Initiator overrides: topic/event, source item, who opens and
mood, first act." The node's `source` (a speakbox document) is read through
system3_pinned_source (system3_runtime.py [s3-source]) just before the round
settles its material; the pinned document's passage becomes the seed and a
seed the dice drew rides along in the spread.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("banter-source",
     '    dropped = {} if (angle or seed) else (\n        drop_bombshell() if s3_chance("banter.bombshell"',
     '    # [s3-source] THE OPERATOR PINNED THIS ROUND\'S SOURCE on System 3\'s initiator\n    # node: the round opens from that speakbox document, whatever the dice\n    # above drew (a seed they drew still rides along as spread material).\n    _s3_src = ""\n    if globals().get("system3_pinned_source") and not caller_name and not own_material and not exchange:\n        try:\n            _s3_src = str(globals()["system3_pinned_source"](str(road or "banter")) or "")\n        except Exception:  # noqa: BLE001\n            _s3_src = ""\n    if _s3_src:\n        _pinned = await speakbox_quote(most=6, cap=700, only=_s3_src)\n        if _pinned and str(_pinned.get("text") or "").strip():\n            if seed and str(seed.get("text") or "").strip():\n                spread.append(seed)\n            seed = _pinned\n            pipeline_log("system3", "the round opens from the source pinned on its initiator node",\n                         extra=_s3_src[:160])\n        else:\n            pipeline_log("system3", "the source pinned on the initiator node gave no passage - the dice\'s draw stands",\n                         extra=_s3_src[:160])\n    dropped = {} if (angle or seed) else (\n        drop_bombshell() if s3_chance("banter.bombshell"', 1),
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
