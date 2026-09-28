"""[s3-events] A call System 3's roulette ENDS keeps its ending.

Operator, 2026-09-27: "I want to see people get emotional randomly, excited,
win prizes, get angry, deal with messages from upstairs, lose the call, go on
a tangent from the speakerbox ... customers get interrupted by random
background activities and I want that ... as a thing that can happen to end
the call."

System 3's EVENT tables (CALLEVENT1) roll what happens on a call; an ending
(the line lost, the caller pulled away by what is going on around them, a
caller hanging up) cuts the plan on that turn and a host reacts to the dead
line. The station's call contract (call_flow_report) refuses a call with no
spoken sign-off and no caller landing it second to last - exactly the calls
the operator asked to hear. So:

  ended-kwarg / ended-legs   call_flow_report(ended=...) waives the sign-off
                             and the landing for a call the roulette ended,
                             and says so in the report
  (the mark)                 System 3's runtime sets call_meta["ended"] when it
                             plans the call short (dj_banter hands it the very
                             dict); entries copy call_meta, so every later
                             regrade sees it - no edit inside the base tool's
                             stored call block
  site-*                     every gate that grades a call passes it on

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("ended-kwarg",
     r'''                     plot: dict[str, Any] | None = None,
                     soft_quality: bool = False) -> dict[str, Any]:
    """Machine-check conversation, theme, tint fidelity and novelty.
''',
     r'''                     plot: dict[str, Any] | None = None,
                     soft_quality: bool = False,
                     ended: str = "") -> dict[str, Any]:
    """Machine-check conversation, theme, tint fidelity and novelty.

    [s3-events] `ended`: the call was planned by System 3 to END EARLY (the
    line lost, the caller pulled away by the background, a hang-up) - the
    roulette's own happening, recorded as an EVENT. Such a call has no
    spoken sign-off and the caller never lands it; both legs are waived and
    the report says why. Every other leg still binds.
''', 1),
    ("ended-legs",
     r'''    if not closed:
        faults.append("a host does not give the call a clear spoken sign-off")
    if not resolved:
        faults.append("the caller does not resolve the exchange immediately "
                      "before the host signs off")
''',
     r'''    if not closed and not ended:          # [s3-events] a call the roulette ended has no sign-off
        faults.append("a host does not give the call a clear spoken sign-off")
    if not resolved and not ended:
        faults.append("the caller does not resolve the exchange immediately "
                      "before the host signs off")
''', 1),
    ("ended-report",
     r'''    report = {
        "ok": not faults, "turns": len(turns), "soft_faults": soft,
''',
     r'''    report = {
        "ok": not faults, "turns": len(turns), "soft_faults": soft,
        "ended": str(ended or ""),                                    # [s3-events]
''', 1),
    ("angle-ended",
     r'''        _one_call_prompt = (
''',
     r'''        # [s3-events] the roulette ended this call early: the angle's own ending (the
        # caller landing it, a host signing off) gives way to the running order's
        if caller_name and isinstance(call_meta, dict) and call_meta.get("ended"):
            _a = str(angle or "")
            if " By the end, " in _a and "Then back to the music. " in _a:
                _a_head, _sep, _a_rest = _a.partition(" By the end, ")
                _a = _a_head + " " + _a_rest.split("Then back to the music. ", 1)[1]
            angle = (_a + " WHATEVER IS SAID ABOVE ABOUT HOW THIS CALL ENDS, IT ENDS EARLY: the running "
                     "order says on which turn and how - the caller never lands it and nobody signs them off.")
        _one_call_prompt = (
''', 1),
    ("site-banter",
     r'''        _call_report = call_flow_report(
            script, caller_name, caller2_name,
''',
     r'''        _call_report = call_flow_report(
            script, caller_name, caller2_name,
            ended=str((call_meta or {}).get("ended") or ""),          # [s3-events]
''', 1),
    ("site-rewrite",
     r'''                _rw_report = call_flow_report(
                    rewritten, caller_name, caller2_name,
''',
     r'''                _rw_report = call_flow_report(
                    rewritten, caller_name, caller2_name,
                    ended=str((call_meta or {}).get("ended") or ""),  # [s3-events]
''', 1),
    ("site-regrade",
     r'''    report = call_flow_report(
        active, caller_name, caller2_name,
        include_shelf=include_shelf,
''',
     r'''    report = call_flow_report(
        active, caller_name, caller2_name,
        include_shelf=include_shelf,
        ended=str(meta.get("ended") or ""),                           # [s3-events]
''', 1),
    ("site-live",
     r'''            meta["flow"] = call_flow_report(
                clean, str(_CALL_LIVE.get("who") or ""),
''',
     r'''            meta["flow"] = call_flow_report(
                clean, str(_CALL_LIVE.get("who") or ""),
                ended=str(meta.get("ended") or ""),                   # [s3-events]
''', 1),
    ("site-review",
     r'''        return call_flow_report(
            active, str(ctx.get("caller_name") or ""),
            str(ctx.get("caller2_name") or ""),
''',
     r'''        return call_flow_report(
            active, str(ctx.get("caller_name") or ""),
            str(ctx.get("caller2_name") or ""),
            ended=str(meta.get("ended") or ""),                       # [s3-events]
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
