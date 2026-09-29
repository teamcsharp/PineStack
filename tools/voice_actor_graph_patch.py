"""[voice-actor] "Call in now": the dispatched caller takes the NEXT diamond.

TARGET: system3.py

The operator's decision (2026-09-28): "call in now" = a call-interjection
node injected into the CURRENT segment's executed tree at the next diamond
(the nodeplan graph's call machinery); ONE TREE PER SEGMENT; every step
recorded rolls.

The graph already carries the call diamond (call_gate: call .12 /
expand_one .88 -> call -> call_reply -> call_followup -> call_return), and
plan_graph already executes call nodes whenever inputs.graph_caller_available
- which system3_runtime reads from ctx["call_interjection"], a key nothing
ever wrote. tools/voice_actor_runtime_patch.py is that writer; this tool is
the graph half:

  1. THE DIAMOND TAKES THE CALL. At a branch whose outgoing edges include a
     call node, a conversation whose inputs carry a dispatched interjection
     (and has not taken it yet) sets the wheel so the call edge wins. It is
     still ONE recorded draw on the round's own stream: every edge stays on
     the wheel with its flow weight as the base, the effective weights are
     the dispatch's, and the reason ("operator dispatch - call in now: NAME
     joins at this diamond") is on the draw. conv["call_interjection"] marks
     where it was taken, so it is taken once.
  2. THE WRITER KNOWS WHO RANG. The call nodes of that conversation carry
     the caller's name, persona, goal and the operator's topic in their
     protocol, beside the node's own "joins a live discussion of ..." brief.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, with tools/voice_actor_runtime_patch.py and
tools/voice_actor_backend_patch.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


_HELPERS_OLD = 'def plan_graph(conv, config, graph_raw, until=None, inputs=None, road="banter"):\n'
_HELPERS_NEW = r'''def voice_actor_diamond(conv, inputs, outgoing, by_id, current):
    """[voice-actor] "Call in now": the operator dispatched a caller into this
    segment's tree, and the FIRST diamond with an edge into a call node takes
    the call. Returns the reason the wheel was set (it is recorded on the
    draw), or "" when this diamond rolls as the graph says. The conversation
    is marked where the call was taken, so it is taken once."""
    ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
    if not isinstance(ij, dict) or not ij.get("id") or conv.get("call_interjection"):
        return ""
    if not any((by_id.get(edge["to"]) or {}).get("type") == "call" for edge in outgoing):
        return ""
    name = " ".join(str(ij.get("name") or "a caller").split())[:80]
    conv["call_interjection"] = {"id": str(ij.get("id") or "")[:40], "node": str(current),
                                 "caller": name, "at_turn": len(conv.get("turns") or [])}
    return "operator dispatch - call in now: %s joins at this diamond" % name


def voice_actor_call_brief(conv, inputs):
    """[voice-actor] Who the dispatched caller is, for the writer, on the call
    nodes of the conversation that took them; "" anywhere else."""
    took = conv.get("call_interjection")
    ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
    if (not isinstance(took, dict) or not isinstance(ij, dict)
            or str(ij.get("id") or "")[:40] != took.get("id")):
        return ""
    said = lambda key, most: " ".join(str(ij.get(key) or "").split())[:most].rstrip(". ")
    out = " This caller is %s, put through by the operator." % json.dumps(said("name", 80) or "the caller")
    if said("persona", 300):
        out += " Who they are: %s." % said("persona", 300)
    if said("goal", 300):
        out += " What they want: %s." % said("goal", 300)
    if said("topic", 300):
        out += " They ring about: %s." % said("topic", 300)
    return out


def plan_graph(conv, config, graph_raw, until=None, inputs=None, road="banter"):
'''

_BRANCH_OLD = (
    '            weights = [edge["weight"] for edge in outgoing]\n'
    '            pick = pick_index(weights, draw["u"])\n'
    '            rows = [{"id": edge["to"], "label": edge["label"] or by_id[edge["to"]]["label"],\n'
    '                     "base": edge["weight"], "weight": edge["weight"], "why": ["outgoing flow weight"]}\n'
    '                    for edge in outgoing]\n'
    '            record("branch", rows, pick, draw, {"node": current})\n')
_BRANCH_NEW = (
    '            weights = [edge["weight"] for edge in outgoing]\n'
    '            # [voice-actor] "call in now": a caller the operator dispatched into\n'
    '            # this segment takes the first diamond with a way into a call. Still\n'
    '            # ONE recorded draw - every edge on the wheel, its flow weight the base,\n'
    '            # the dispatch the effective weight, and the reason on the draw.\n'
    '            _va_why = voice_actor_diamond(conv, inputs, outgoing, by_id, current)\n'
    '            if _va_why:\n'
    '                weights = [1.0 if by_id[edge["to"]]["type"] == "call" else 0.0 for edge in outgoing]\n'
    '            pick = pick_index(weights, draw["u"])\n'
    '            rows = [{"id": edge["to"], "label": edge["label"] or by_id[edge["to"]]["label"],\n'
    '                     "base": edge["weight"], "weight": weights[i],\n'
    '                     "why": ["outgoing flow weight"] + ([_va_why] if _va_why else [])}\n'
    '                    for i, edge in enumerate(outgoing)]\n'
    '            record("branch", rows, pick, draw, {"node": current, **({"dispatch": conv["call_interjection"]["id"]}\n'
    '                                                                   if _va_why else {})})\n')

_BRIEF_OLD = '                                         % (json.dumps(topic), ", ".join(heard) or "the hosts"))\n'
_BRIEF_NEW = ('                                         % (json.dumps(topic), ", ".join(heard) or "the hosts"))\n'
              '                    turn["protocol"] += voice_actor_call_brief(conv, inputs)   # [voice-actor] who rang\n')

EDITS = [
    ("va-graph-helpers", _HELPERS_OLD, _HELPERS_NEW, 1),
    ("va-graph-diamond", _BRANCH_OLD, _BRANCH_NEW, 1),
    ("va-graph-brief", _BRIEF_OLD, _BRIEF_NEW, 1),
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
    target = next((a for a in argv if not a.startswith("--")), "system3.py")
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
