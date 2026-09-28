"""[s3-bank] The SFX Guy's banked lines air only when the roulette brings one up.

Operator, 2026-09-28: "i dont want these banked lines unless they come up in a
roulette" and "the point of making everything go on system 3 is to have no
dialogue hit the station unless it is scripted via the RNG roulette system".
sfxguy_ready_pick (both his roads: the cadence after a host turn and the
dead-air fill) asks System 3 first (sfxguy.bank_line, a STATION1 row the desk
can dial), then lets the roulette pick the take (sfxguy.bank_take) and rests a
line SFXGUY_BANK_REST_S. Needs sfx_speech_bank.py's `chooser` (same batch).
With System 3's dice off the bank is exactly as it was.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("bank-roulette",
     'def sfxguy_ready_pick(context: str = "", voice: str = "") -> dict[str, Any] | None:\n    """Reserve one already recorded whole line for the strict saved-take path."""\n    current = str(dj_settings().get("drop_voice") or "")\n    if not current or (voice and voice != current):\n        return None\n    try:\n        _profile = _sfxguy_ready_profile()               # #1394: once\n        row = _SFX_READY_BANK.pick(context, current, _profile,\n                                  lambda item: _sfxguy_ready_valid(item, current, _profile))\n',
     '# [s3-bank] "i dont want these banked lines unless they come up in a roulette"\n# - "the point of making everything go on system 3 is to have no dialogue hit\n# the station unless it is scripted via the RNG roulette system" (operator,\n# 2026-09-28). The SFX Guy\'s speech bank is stock, not a System 3\n# conversation, and its own ranking (best keyword match, then least recent,\n# resting a line three MINUTES) put 165 distinct lines on air 3,613 times - the\n# top ones 50 to 69 times each. While System 3\'s dice are live a banked line\n# airs only when the roulette brings one up, the take is the roulette\'s pick\n# among the rested ones, and a line rests hours, not minutes.\nSFXGUY_BANK_ODDS = float(os.getenv("SFXGUY_BANK_ODDS", "0.2"))\nSFXGUY_BANK_REST_S = float(os.getenv("SFXGUY_BANK_REST_S", "21600"))\n\n\ndef _sfxguy_bank_roll(takes: list[dict[str, Any]]) -> int:\n    """Which of his rested banked lines: System 3\'s roll, the ones that answer\n    the moment weighing more."""\n    return s3_weighted("sfxguy.bank_take", [str(t.get("text") or "")[:80] for t in takes],\n                       [1.0 + 2.0 * float(t.get("overlap") or 0) for t in takes],\n                       "which of the SFX Guy\'s banked lines")\n\n\ndef sfxguy_ready_pick(context: str = "", voice: str = "") -> dict[str, Any] | None:\n    """Reserve one already recorded whole line for the strict saved-take path."""\n    current = str(dj_settings().get("drop_voice") or "")\n    if not current or (voice and voice != current):\n        return None\n    _rolled = _s3_dice_live()                                          # [s3-bank]\n    if _rolled and not s3_chance("sfxguy.bank_line", SFXGUY_BANK_ODDS,\n                                 "one of the SFX Guy\'s banked lines comes up (otherwise nothing banked airs)"):\n        return None\n    try:\n        _profile = _sfxguy_ready_profile()               # #1394: once\n        row = _SFX_READY_BANK.pick(context, current, _profile,\n                                  lambda item: _sfxguy_ready_valid(item, current, _profile),\n                                  **({"cooldown": SFXGUY_BANK_REST_S, "chooser": _sfxguy_bank_roll}\n                                     if _rolled else {}))\n', 1),
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
