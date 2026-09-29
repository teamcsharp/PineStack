"""[s3-chain] system3_runtime.py half of the exchange handoff (steps 2-3).

  1. chapter-plan    System3Runtime.line_chapter(stamp) tells "no chapter here"
                     apart from "unknown": a known conversation that is not a
                     line road's graph (a round's own turn, a road whose graph
                     the operator switched off, a plan under three turns)
                     answers {"chapter": False, ...}; a chapter's plan carries
                     its road, turn ids and the planned seconds per turn (the
                     reply budget). Unknown (left the recent cache) is None.
  2. chapter-rows    each committed turn's stamp is its own: its turn id and
                     its place in the chapter (turn i of n).
  3. chapter-state   System3Runtime.line_chapter_state(stamp, state, why):
                     where the exchange stands on the prepared shelf (waiting,
                     prepared, aired, partial, expired) - recorded on the
                     conversation so a plan that has not aired says why.
  4. chapter-export  namespace system3_line_chapter_state.

--check exits 0 ready / 2 applied / 1 anchors missing; --apply is idempotent,
asserts every anchor, writes LF atomically.
TARGET: system3_runtime.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("chapter-plan",
     '        planned = conv.get("turns") or []\n'
     '        if not conv.get("graph_structure") or len(planned) < 3:\n'
     '            return None\n'
     '        if written is None:\n'
     '            return {"sheet": str((conv.get("plan") or {}).get("sheet") or ""),\n'
     '                    "turns": len(planned), "seats": [t["speaker"] for t in planned],\n',
     '        planned = conv.get("turns") or []\n'
     '        road = str((conv.get("identity") or {}).get("road_kind") or "")\n'
     '        if (road not in system3_tables.LINE_ROADS or not conv.get("graph_structure")\n'
     '                or len(planned) < 3):\n'
     '            # [s3-chain] known, and not a chapter: a round\'s own turn, a line road\n'
     '            # whose graph the operator switched off, or a plan under three turns\n'
     '            return ({"chapter": False, "road": road, "turns": len(planned)}\n'
     '                    if written is None else None)\n'
     '        if written is None:\n'
     '            return {"chapter": True, "road": road,                                   # [s3-chain]\n'
     '                    "turn_ids": [t["turn_id"] for t in planned],\n'
     '                    "seconds": [float(t.get("planned_seconds") or 0) for t in planned],\n'
     '                    "estimated_seconds": float((conv.get("graph_profile") or {}).get("estimated_seconds") or 0),\n'
     '                    "sheet": str((conv.get("plan") or {}).get("sheet") or ""),\n'
     '                    "turns": len(planned), "seats": [t["speaker"] for t in planned],\n',
     1),
    ("chapter-rows",
     '                 "text": rows[i][1], "stamp": dict(stamp, turn_id=t["turn_id"])}\n'
     '                for i, t in enumerate(planned)]\n',
     '                 "text": rows[i][1],\n'
     '                 # [s3-chain] each turn\'s own stamp: its node and its place\n'
     '                 "stamp": dict(stamp, turn_id=t["turn_id"], chapter_turn=i, chapter_of=len(planned))}\n'
     '                for i, t in enumerate(planned)]\n'
     '\n'
     '    def line_chapter_state(self, stamp, state, why="", extra=None):\n'
     '        """[s3-chain] Where a line road\'s exchange stands on the prepared shelf\n'
     '        (waiting, prepared, aired, partial, expired), recorded on the\n'
     '        conversation: a planned chapter that has not aired says why."""\n'
     '        try:\n'
     '            conv = self.recent.get(str((stamp or {}).get("conversation_id") or ""))\n'
     '            if not conv:\n'
     '                return\n'
     '            conv["chapter_state"] = dict(extra or {}, state=str(state), why=str(why or "")[:300],\n'
     '                                         at=time.time())\n'
     '            if state in ("aired", "partial", "expired", "stale"):\n'
     '                conv["status"] = "chapter_" + str(state)\n'
     '            self.remember(conv)\n'
     '            self.persist(conv)\n'
     '            self._flow(conv, "chapter %s%s" % (state, (": " + str(why)[:160]) if why else ""))\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("chapter state", exc)\n',
     1),
    ("chapter-export",
     '    namespace["system3_line_chapter"] = rt.line_chapter\n',
     '    namespace["system3_line_chapter"] = rt.line_chapter\n'
     '    namespace["system3_line_chapter_state"] = rt.line_chapter_state      # [s3-chain]\n',
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
