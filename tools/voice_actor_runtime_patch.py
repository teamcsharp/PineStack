"""[voice-actor] The write side of ctx["call_interjection"].

TARGET: system3_runtime.py

_inputs() has read ctx["call_interjection"] into graph_caller_available since
the nodeplan graph landed, and nothing anywhere ever set it: the "call in
now" road had a reader and no writer. The voice actor subpanel's dispatch
(tools/voice_actor_backend_patch.py, app.py) keeps the armed interjection;
this tool hands it to the round System 3 plans next:

  1. ARM. direct() - a live, active round (never a banked one, never a call
     road round, never a whole-message road) asks the station for the armed
     interjection (voice_actor_interjection_pending, which also retires one
     whose segment has ended: "ONE TREE PER SEGMENT"). An armed one goes on
     ctx["call_interjection"] and on the inputs - the caller's name as seat
     C, graph_caller_available true - so the recorded inputs say who was
     waiting on the line.
  2. TAKEN. After planning, a conversation whose graph walk took the call
     (voice_actor_graph_patch's diamond) and planned C turns is reported to
     the station (voice_actor_interjection_taken: dispatch -> "planned", with
     the conversation id and the turn ids) and the handle carries the
     interjection so dj_banter can put the caller's own voice on their rows.
     A plan that reached no diamond leaves it armed for the next round.

A station without the backend patch answers AttributeError here and the round
plans exactly as before.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, with tools/voice_actor_graph_patch.py and
tools/voice_actor_backend_patch.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


_ARM_OLD = ('            inputs = self._inputs(ctx)\n'
            '            config = self.config\n'
            '            started = time.perf_counter()\n')
_ARM_NEW = ('            inputs = self._inputs(ctx)\n'
            '            self._voice_actor_arm(ctx, inputs, road, mode)       # [voice-actor] "call in now"\n'
            '            config = self.config\n'
            '            started = time.perf_counter()\n')

_TAKEN_OLD = ('            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)\n'
              '            if conv.get("length_roll"):\n')
_TAKEN_NEW = ('            self._voice_actor_taken(handle, inputs)             # [voice-actor] the diamond took it\n'
              '            handle.plan_ms = round((time.perf_counter() - started) * 1000, 2)\n'
              '            if conv.get("length_roll"):\n')

_METHODS_OLD = '    def _carry_for(self, ctx):\n'
_METHODS_NEW = r'''    def _voice_actor_arm(self, ctx, inputs, road, mode):
        """[voice-actor] The write side of ctx["call_interjection"]: the caller
        the operator dispatched with "call in now", for a live active round
        planned in the segment it was dispatched into. Never raises."""
        if (mode != "active" or ctx.get("bank") or ctx.get("caller_name")
                or ctx.get("whole") or road == "caller"):
            return
        try:
            pending = self.host.voice_actor_interjection_pending(
                road, str((inputs.get("segment") or {}).get("id") or ""))
        except AttributeError:
            return                          # the station has no voice actor store
        except Exception as exc:  # noqa: BLE001
            self.fail("voice actor arm", exc)
            return
        if not isinstance(pending, dict) or not str(pending.get("name") or "").strip():
            return
        ij = {k: " ".join(str(pending.get(k) or "").split())[:400]
              for k in ("id", "caller_id", "name", "persona", "goal", "topic", "voice_id", "segment_id")}
        ij["name"] = ij["name"][:80]
        ctx["call_interjection"] = dict(ij)
        inputs["call_interjection"] = dict(ij)
        inputs["graph_caller_available"] = True
        inputs.setdefault("names", {})["C"] = ij["name"]

    def _voice_actor_taken(self, handle, inputs):
        """[voice-actor] Did this plan take the armed call at a diamond? Then the
        dispatch is planned (its conversation and C turns recorded) and the
        handle carries the caller for dj_banter. Never raises."""
        ij = inputs.get("call_interjection") if isinstance(inputs, dict) else None
        if not isinstance(ij, dict) or not handle or not handle.active:
            return
        conv = handle.conv
        took = conv.get("call_interjection")
        c_turns = [t for t in conv.get("turns") or [] if t.get("speaker") == "C"]
        if not isinstance(took, dict) or took.get("id") != ij.get("id") or not c_turns:
            return
        handle.interjection = dict(ij, node=str(took.get("node") or ""))
        try:
            self.host.voice_actor_interjection_taken(
                ij["id"], handle.id, [str(t.get("turn_id") or "") for t in c_turns],
                str(took.get("node") or ""))
        except Exception as exc:  # noqa: BLE001
            self.fail("voice actor taken", exc)

    def _carry_for(self, ctx):
'''

EDITS = [
    ("va-rt-arm", _ARM_OLD, _ARM_NEW, 1),
    ("va-rt-taken", _TAKEN_OLD, _TAKEN_NEW, 1),
    ("va-rt-methods", _METHODS_OLD, _METHODS_NEW, 1),
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
    target = next((a for a in argv if not a.startswith("--")), "system3_runtime.py")
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
