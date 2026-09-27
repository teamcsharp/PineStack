"""The switches for the systems that cut lines (operator, 2026-09-27: "I
want to be able to see why they're being cut and to toggle that reason and
to be able to toggle off the system that's cutting those lines. We
shouldn't be cutting any lines.")

Three standing policies in the orchestrator's own policy book, turned
through its own door (POST /api/orchestrator/policy {"does": ...}), each
read at the one place that makes its cut:

  cut:on|off       talk_cut          a round cut at a turn boundary when
                                     something urgent takes the floor, and
                                     the turn cap that ends a long round
                                     ("round cut mid-flight")
  withdraw:on|off  overrun_withdraw  a finished round refused at hand-over
                                     because it no longer fits its entry
                                     ("the banter round runs 146s and its
                                     entry has 100s left")
  bound:on|off     record_bound      a line about a record withdrawn, or
                                     cut, because its record moved on
                                     (#1237)

Every switch reads True when unset, so applying this changes nothing on
air until a switch is turned. Idempotent: --check exits 0 when every edit
can apply, 2 when already applied, 1 when an anchor is missing; --apply
writes the file. Run it ON THE HOST (see the deploy notes): app.py over
the share is slow and a parallel session may be writing it.

    cat tools/cut_switches_patch.py | ssh HOST 'cd ~/pinevoice-stack/spark-agent && python3 - --apply app.py'
"""
import sys

MARK = "# [cut-switches]"
ON = 'orch_policy("{key}", True) is not False'

EDITS = [
    ("verbs",
     '''        elif verb == "thin":
            _ORCH["policy"]["thin_road"] = {''',
     '''        elif verb == "cut":
            # [cut-switches] 2026-09-27: "We shouldn't be cutting any
            # lines." The talk-cut and the turn cap end a round mid-flight.
            _want = str(arg or "on") != "off"
            _ORCH["policy"]["talk_cut"] = {"value": bool(_want), "at": time.time()}
            said = ("a round may be cut at a turn boundary when something urgent takes "
                    "the floor, and at the turn cap" if _want else
                    "no round is cut mid-flight - every written turn is spoken")
        elif verb == "withdraw":
            # [cut-switches] a finished round that no longer fits its entry.
            _want = str(arg or "on") != "off"
            _ORCH["policy"]["overrun_withdraw"] = {"value": bool(_want), "at": time.time()}
            said = ("a finished round that no longer fits its entry is withdrawn at "
                    "hand-over" if _want else
                    "a finished round airs even when it runs past its entry - the "
                    "sheet waits for it")
        elif verb == "bound":
            # [cut-switches] #1237: a line about a record whose record moved on.
            _want = str(arg or "on") != "off"
            _ORCH["policy"]["record_bound"] = {"value": bool(_want), "at": time.time()}
            said = ("a line about a record is withdrawn when its record has moved on"
                    if _want else
                    "a line about a record airs even when its record has moved on")
        elif verb == "thin":
            _ORCH["policy"]["thin_road"] = {'''),
    ("talk-cut",
     '''    can_cut = not bool(caller_name) and not whole
    for at in order:
        item = playlist[at]
        if (not caller_name and not whole and content_turns_spoken >= limit
                and not item.get("listening_response")):
            break''',
     '''    can_cut = (not bool(caller_name) and not whole
               and orch_policy("talk_cut", True) is not False)   # [cut-switches]
    for at in order:
        item = playlist[at]
        if (not caller_name and not whole and content_turns_spoken >= limit
                and not item.get("listening_response")
                and orch_policy("talk_cut", True) is not False):   # [cut-switches]
            break'''),
    ("talk-cut-rearm",
     '''        can_cut = (bool(item["turn_end"]) and not caller_name and not whole
                   and not item.get("continuation_response"))''',
     '''        can_cut = (bool(item["turn_end"]) and not caller_name and not whole
                   and not item.get("continuation_response")
                   and orch_policy("talk_cut", True) is not False)   # [cut-switches]'''),
    ("withdraw-page",
     '''                            or not _scheduled_first_handoff_fits(
                                ready_meta, ready_takes, _handoff_seconds,
                                start_at=_pstart, exclude_key=_pl_key)''',
     '''                            or (not _scheduled_first_handoff_fits(
                                ready_meta, ready_takes, _handoff_seconds,
                                start_at=_pstart, exclude_key=_pl_key)
                                and orch_policy("overrun_withdraw", True) is not False)   # [cut-switches]'''),
    ("withdraw-box",
     '''                                 or not _scheduled_first_handoff_fits(
                                     ready_meta, ready_takes, _handoff_seconds,
                                     exclude_key=_pl_key)''',
     '''                                 or (not _scheduled_first_handoff_fits(
                                     ready_meta, ready_takes, _handoff_seconds,
                                     exclude_key=_pl_key)
                                     and orch_policy("overrun_withdraw", True) is not False)   # [cut-switches]'''),
    ("bound-write",
     '''    if bound:
        _bound_ok, _bound_why = record_bound_check(
            bound, bound_part, live=not bool(line))''',
     '''    if bound and orch_policy("record_bound", True) is not False:   # [cut-switches]
        _bound_ok, _bound_why = record_bound_check(
            bound, bound_part, live=not bool(line))'''),
    ("bound-air",
     '''    if bound:
        _bound_ok, _bound_why = record_bound_check(
            bound, bound_part, float((clip or {}).get("seconds") or 0))''',
     '''    if bound and orch_policy("record_bound", True) is not False:   # [cut-switches]
        _bound_ok, _bound_why = record_bound_check(
            bound, bound_part, float((clip or {}).get("seconds") or 0))'''),
    ("bound-cut",
     '''    tid = (str((track or {}).get("id") or "")
           if isinstance(track, dict) else "")
    if not tid:
        return 0
    try:
        ids = record_binding.cut_ids(_RECORD_BOUND_LINES, tid, time.time())''',
     '''    tid = (str((track or {}).get("id") or "")
           if isinstance(track, dict) else "")
    if not tid or orch_policy("record_bound", True) is False:   # [cut-switches]
        return 0
    try:
        ids = record_binding.cut_ids(_RECORD_BOUND_LINES, tid, time.time())'''),
]

# cut:off stops the AUTOMATIC cuts; a cut the operator asks for (Next,
# Previous, a mixtape, the dice, the manager's break-in button) still lands.
# Each of those stamps _TALK_CUT_OP, and the talk-cut gate lets a cut
# through for 90 s after it.
OP = "or time.time() - _TALK_CUT_OP[0] < 90"
EDITS += [
    ("op-state",
     '''_TALK_CUT = [0]
''',
     '''_TALK_CUT = [0]
_TALK_CUT_OP = [0.0]   # [cut-switches] when the operator last asked for a cut
'''),
    ("op-gate",
     '''    can_cut = (not bool(caller_name) and not whole
               and orch_policy("talk_cut", True) is not False)   # [cut-switches]''',
     '''    can_cut = (not bool(caller_name) and not whole
               and (orch_policy("talk_cut", True) is not False
                    %s))   # [cut-switches]''' % OP),
    ("op-gate-rearm",
     '''                   and not item.get("continuation_response")
                   and orch_policy("talk_cut", True) is not False)   # [cut-switches]''',
     '''                   and not item.get("continuation_response")
                   and (orch_policy("talk_cut", True) is not False
                        %s))   # [cut-switches]''' % OP),
    ("op-next",
     '''    _RADIO["call_cooldown"] = time.time() + 120
    _TALK_CUT[0] += 1
    dj_skip()''',
     '''    _RADIO["call_cooldown"] = time.time() + 120
    _TALK_CUT[0] += 1
    _TALK_CUT_OP[0] = time.time()   # [cut-switches] the operator asked
    dj_skip()'''),
    ("op-prev",
     '''            _RADIO["requests"].insert(0, full)
            _TALK_CUT[0] += 1
            dj_skip()''',
     '''            _RADIO["requests"].insert(0, full)
            _TALK_CUT[0] += 1
            _TALK_CUT_OP[0] = time.time()   # [cut-switches] the operator asked
            dj_skip()'''),
    ("op-mixtape",
     '''    _TALK_CUT[0] += 1                   # cut any round mid-flight''',
     '''    _TALK_CUT[0] += 1                   # cut any round mid-flight
    _TALK_CUT_OP[0] = time.time()   # [cut-switches] the operator asked'''),
    ("op-dice",
     '''    _TALK_CUT[0] += 1                   # the stage is taken, mid-line if need be''',
     '''    _TALK_CUT[0] += 1                   # the stage is taken, mid-line if need be
    _TALK_CUT_OP[0] = time.time()   # [cut-switches] the operator asked'''),
    ("op-breakin",
     '''        # this one carries it through.
        _TALK_CUT[0] += 1
        return {"ok": False, "asked": True, **manager_break_state(),''',
     '''        # this one carries it through.
        _TALK_CUT[0] += 1
        _TALK_CUT_OP[0] = time.time()   # [cut-switches] the operator asked
        return {"ok": False, "asked": True, **manager_break_state(),'''),
]


def done_flags(text):
    """An edit is done when its result is in the file - or when a LATER edit
    rewrote that result (the operator gates rewrite the first talk-cut
    gates) and is itself done."""
    done = [False] * len(EDITS)
    for i in range(len(EDITS) - 1, -1, -1):
        _name, _old, new = EDITS[i]
        if new in text:
            done[i] = True
            continue
        done[i] = any(done[j] and EDITS[j][1] in new for j in range(i + 1, len(EDITS)))
    return done


def check(text):
    done = done_flags(text)
    missing = []
    for i, (name, old, _new) in enumerate(EDITS):
        if done[i] or text.count(old) == 1:
            continue
        # produced by an earlier edit of this same run
        if any(not done[k] and old in EDITS[k][2] for k in range(i)):
            continue
        missing.append(name)
    return sum(done), missing


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = "--apply" if "--apply" in sys.argv else "--check"
    path = args[0] if args else "app.py"
    raw = open(path, "rb").read().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(EDITS):
        print("already applied (%d edits)" % applied)
        return 2
    if missing:
        print("anchors missing or not unique: " + ", ".join(missing))
        return 1
    done = done_flags(text)
    for i, (name, old, new) in enumerate(EDITS):
        if done[i]:
            continue
        text = text.replace(old, new, 1)
    if mode != "--apply":
        print("ready: %d edits" % (len(EDITS) - applied))
        return 0
    import ast
    ast.parse(text)
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    print("applied %d edits" % (len(EDITS) - applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())
