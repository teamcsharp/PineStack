"""[s3-reair-copy] app.py: a banked round the copy gate refuses at re-air is
RETIRED - recorded once as a mark in data/reair_ineligible.json (by, why, road,
at) - and never aired. The round itself stays in its store untouched; setting
"allow": true on its mark restores it to the roulette (reair_gate.refusal reads
the mark). Every re-air road (the shelf walk, the larder's serve, the prepared
round, the finished call, the continuity pairs) asks bank_reair_refusal first,
so this is the one door. Needs tools/reair_copy_gate_patch.py (reair_gate.py)
for the refusal itself; either order runs (this only acts on its reason text).

  1. retire-hook     _reair_copy_retire(): the mark, off the loop, once per round,
                     registered as reair_gate.RETIRE_HOOK - the gate calls it the
                     first time it refuses a round for a copy (anchored outside the
                     [s3-banks-roll] block, whose stored text holds bank_reair_refusal).

--check exits 0 ready / 2 applied / 1 anchors missing; --apply idempotent,
atomic, LF.
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("retire-hook",
     'def repeat_window() -> float:\n',
     '''_REAIR_COPY_RETIRED: set[str] = set()
_REAIR_COPY_LOCK = RLock()


def _reair_copy_retire(keys: list[str], why: str) -> None:
    """[s3-reair-copy] A banked round the copy gate refused when it was drawn for
    re-air is RETIRED: one mark in data/reair_ineligible.json (who retired it,
    why, when), written off the loop, once per round. The round stays in its
    store untouched; set "allow": true on the mark to restore it to the roulette.
    reair_gate.content_refusal calls this (RETIRE_HOOK) the first time it refuses."""
    key = next((str(k) for k in keys or () if ":" in str(k)), "")
    if not key or key in _REAIR_COPY_RETIRED:
        return
    _REAIR_COPY_RETIRED.add(key)

    def job() -> None:
        try:
            import reair_gate
            with _REAIR_COPY_LOCK:
                marks = reair_gate.load_marks(REAIR_MARKS_PATH)
                if key in marks:
                    return
                marks[key] = {"why": str(why)[:300], "by": "the copy gate at re-air [s3-reair-copy]",
                              "at": round(time.time(), 3),
                              "restore": "set \\"allow\\": true on this mark to put it back on the roulette"}
                reair_gate.save_marks(REAIR_MARKS_PATH, marks, by="app.py [s3-reair-copy]")
            pipeline_log("air", ("a banked round was RETIRED at re-air - %s" % why)[:200], extra=key)
        except Exception as exc:  # noqa: BLE001 - the refusal stands; only the record failed
            pipeline_log("air", "a re-air retirement could not be recorded",
                         extra=("%s %s: %s" % (key, type(exc).__name__, exc))[:200])
    try:
        asyncio.get_running_loop()
        fire_and_forget(asyncio.to_thread(job))
    except RuntimeError:
        job()


try:                                                    # [s3-reair-copy] the gate reports its retirements
    import reair_gate as _reair_gate_mod
    _reair_gate_mod.RETIRE_HOOK = _reair_copy_retire
except Exception:  # noqa: BLE001 - no gate module, nothing to retire
    pass


def repeat_window() -> float:
''', 1),
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
