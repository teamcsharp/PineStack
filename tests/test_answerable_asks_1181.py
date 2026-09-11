# -*- coding: utf-8 -*-
"""Exercise the #1181 code paths out of app.py with stubs.

Pulls the real source of orch_routine_questions() and the road_empty
question block out of the patched file and runs them, so the assertions
are against the shipped code rather than a paraphrase of it."""
import ast
import io
import random
import sys

SRC = sys.argv[1]
s = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(s)
lines = s.split("\n")


def func_src(name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise SystemExit("no function %s" % name)


# ---- stubs the extracted code needs ----------------------------------
SHELF_LABEL = {"news": "a news bulletin", "ad": "an advert",
               "gallery": "a painting round", "caller": "a phone call",
               "manager": "a message from upstairs",
               "track_talk": "track talk", "banter": "banter"}
PREP_SHORT_HORIZON = {}
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and getattr(
            node.targets[0], "id", "") == "PREP_SHORT_HORIZON":
        PREP_SHORT_HORIZON = ast.literal_eval(node.value)

_POLICY = {}


def orch_policy(key, fallback=None):
    return _POLICY.get(key, fallback)


def _opt(face, does, note=""):
    return {"face": face, "does": does, "note": note}


ns = {"SHELF_LABEL": SHELF_LABEL, "orch_policy": orch_policy, "_opt": _opt,
      "random": random, "Any": object, "PREP_SHORT_HORIZON": PREP_SHORT_HORIZON}
exec(func_src("orch_routine_questions"), ns)
routine = ns["orch_routine_questions"]

fails = []


def check(label, cond, detail=""):
    print("  %-58s %s" % (label, "PASS" if cond else "FAIL " + detail))
    if not cond:
        fails.append(label)


print("PREP_SHORT_HORIZON =", list(PREP_SHORT_HORIZON))
check("news is named short-horizon", "news" in PREP_SHORT_HORIZON)

print("\n-- orch_routine_questions with NO pin standing --")
_POLICY.clear()
for _ in range(12):
    qs = routine()
    assert len(qs) == 3
    drives = [o["does"] for q in qs for o in q["options"]
              if str(o["does"]).startswith("drive:")]
check("no pin -> 3 questions, no drive verb offered",
      all(not str(o["does"]).startswith("drive:")
          for _ in range(12) for q in routine() for o in q["options"]))

print("\n-- orch_routine_questions WITH a pin standing --")
_POLICY["drive_road"] = "track_talk"
seen_clear = 0
for _ in range(12):
    qs = routine()
    if len(qs) != 3:
        fails.append("pin: wrong question count")
    first = qs[0]
    if "still being built ahead" not in first["ask"]:
        fails.append("pin: not asked first")
    if any(o["does"] == "drive:none" for o in first["options"]):
        seen_clear += 1
check("pin standing -> asked FIRST, every time", not fails)
check("pin question always offers drive:none", seen_clear == 12,
      "saw %d/12" % seen_clear)
qs = routine()
print("     ask :", qs[0]["ask"])
for o in qs[0]["options"]:
    print("       %-36s -> %s" % (o["face"], o["does"]))

print("\n-- the road_empty question block --")
import textwrap
_lo = next(i for i, ln in enumerate(lines)
           if "_buildable = [k for k in empty if k not" in ln)
_hi = next(i for i, ln in enumerate(lines)
           if 'out = orch_raise("road_empty", _why, "soon", _questions)' in ln)
blk = textwrap.dedent("\n".join(lines[_lo:_hi]))
BLK = compile(blk, "<road_empty>", "exec")


def road_empty(empty):
    """Run the real block with `empty` supplied."""
    names = ", ".join(SHELF_LABEL.get(k, k) for k in empty[:4])
    loc = {"empty": empty, "names": names, "SHELF_LABEL": SHELF_LABEL,
           "PREP_SHORT_HORIZON": PREP_SHORT_HORIZON, "_opt": _opt}
    exec(BLK, loc)
    return loc["_questions"], loc["_why"]


for label, empty in (("only news (short-horizon)", ["news"]),
                     ("news + gallery", ["news", "gallery"]),
                     ("gallery + ad", ["gallery", "ad"])):
    qs, why = road_empty(empty)
    asks = [q["ask"][:44] for q in qs]
    build = [q for q in qs if "build these ahead" in q["ask"]]
    verbs = [o["does"] for q in build for o in q["options"]]
    print("\n  empty=%s" % empty)
    print("    questions      : %d %s" % (len(qs), asks))
    print("    build-ahead    : %s" % (verbs or "NOT ASKED"))
    print("    why tail       : ...%s" % why[-135:])
    if empty == ["news"]:
        check("only short-horizon -> build-ahead NOT asked", not build)
        check("only short-horizon -> says it is not waiting on an answer",
              "not waiting on an answer" in why)
        check("only short-horizon -> the live/skip question still asked",
              any("comes round" in q["ask"] for q in qs))
    else:
        check("%s -> build-ahead asked" % label, bool(build))
        check("%s -> fires drive: not prefer:" % label,
              any(v.startswith("drive:") for v in verbs)
              and not any(v.startswith("prefer:") and "slot" not in v
                          for v in verbs))
        check("%s -> drives a BUILDABLE road, never news" % label,
              not any(v == "drive:news" for v in verbs))
        check("%s -> 'No' clears the pin" % label, "drive:none" in verbs)

print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILURES",
                                len(fails)))
sys.exit(1 if fails else 0)
