# -*- coding: utf-8 -*-
"""#1181/#1182: the orchestrator only asks what it can act on.

Pulls the REAL source of the question builders out of app.py and runs it
against stubs, so every assertion is against shipped code rather than a
paraphrase of it."""
import ast
import io
import random
import sys
import textwrap
from pathlib import Path

_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
SRC = str(_arg if _arg and _arg.is_file()
          else Path(__file__).resolve().parents[1] / "app.py")
s = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(s)
lines = s.split("\n")


def func_src(name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise SystemExit("no function %s" % name)


def const(name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise SystemExit("no constant %s" % name)


PREP_SHORT_HORIZON = const("PREP_SHORT_HORIZON")
PREP_BOARD = const("PREP_BOARD")
CANNOT_PREPARE = const("CANNOT_PREPARE")
SHELF_LABEL = {"news": "a news bulletin", "ad": "an advert",
               "gallery": "a painting round", "caller": "a phone call",
               "manager": "a message from upstairs",
               "track_talk": "track talk", "station_id": "a station ID",
               "banter": "banter"}

_POLICY, _NEEDS, _STATE = {}, {}, {"paused": False, "cover": 99., "target": 1.}


def orch_policy(key, fallback=None):
    return _POLICY.get(key, fallback)


def hour_needs_now():
    return _NEEDS


def radio_paused():
    return _STATE["paused"]


def prepared_seconds():
    return _STATE["cover"]


def prepare_target_seconds():
    return _STATE["target"]


def _opt(face, does, note=""):
    return {"face": face, "does": does, "note": note}


ns = dict(globals())
ns["Any"] = object
exec(func_src("orch_behind_roads"), ns)
exec(func_src("orch_routine_questions"), ns)
behind_roads, routine = ns["orch_behind_roads"], ns["orch_routine_questions"]

fails = []


def check(label, cond, detail=""):
    print("  %-62s %s" % (label, "PASS" if cond else "FAIL " + detail))
    if not cond:
        fails.append(label)


def needs(**kw):
    """kw: road=(owed, held)"""
    _NEEDS.clear()
    _NEEDS.update({k: {"owed": v[0], "held": v[1]} for k, v in kw.items()})


def verbs(qs, frag):
    return [o["does"] for q in qs if frag in q["ask"] for o in q["options"]]


print("PREP_SHORT_HORIZON =", list(PREP_SHORT_HORIZON))
check("news is named short-horizon", "news" in PREP_SHORT_HORIZON)

# ---------------------------------------------------------------- #1181
print("\n== #1181 the road_empty ask ==")
_lo = next(i for i, ln in enumerate(lines)
           if "_buildable = [k for k in empty if k not" in ln)
_hi = next(i for i, ln in enumerate(lines)
           if 'out = orch_raise("road_empty", _why, "soon", _questions)' in ln)
BLK = compile(textwrap.dedent("\n".join(lines[_lo:_hi])), "<road_empty>", "exec")


def road_empty(empty):
    names = ", ".join(SHELF_LABEL.get(k, k) for k in empty[:4])
    loc = {"empty": empty, "names": names, "SHELF_LABEL": SHELF_LABEL,
           "PREP_SHORT_HORIZON": PREP_SHORT_HORIZON, "_opt": _opt}
    exec(BLK, loc)
    return loc["_questions"], loc["_why"]


qs, why = road_empty(["news"])
check("only short-horizon empty -> build-ahead NOT asked",
      not [q for q in qs if "build these ahead" in q["ask"]])
check("only short-horizon empty -> says it is not waiting on an answer",
      "not waiting on an answer" in why)
check("only short-horizon empty -> entry question still asked",
      any("comes round" in q["ask"] for q in qs))

qs, _ = road_empty(["news", "gallery"])
v = verbs(qs, "build these ahead")
check("news+gallery -> drives gallery, never news", "drive:gallery" in v
      and "drive:news" not in v, str(v))
check("news+gallery -> 'No' clears the pin", "drive:none" in v)
check("news+gallery -> no bare prefer: on a build question",
      not [x for x in v if x.startswith("prefer:") and "slot" not in x], str(v))

# ---------------------------------------------------------------- #1182
print("\n== #1182 orch_behind_roads ==")
needs(caller=(4500, 9367), banter=(1440, 8053), news=(2160, 0),
      gallery=(2160, 4089), ad=(2160, 1435), track_talk=(720, 0))
b = behind_roads(3)
print("     behind:", b)
# ad is 725s short, track_talk 720s - so ad leads, and nothing else on
# the board is short at all.
check("deepest shortfall first, and only what is short",
      b == ["ad", "track_talk"], str(b))
check("most= caps the list", len(behind_roads(1)) == 1
      and behind_roads(1) == ["ad"], str(behind_roads(1)))
check("a covered road is never 'behind'", "caller" not in b and
      "gallery" not in b, str(b))
check("short-horizon news is never 'behind'", "news" not in b, str(b))
check("banter is excluded - not on the preparer's board", "banter" not in b,
      str(b))

needs(caller=(4500, 9367), gallery=(2160, 4089))
check("nothing short -> no roads behind", behind_roads(3) == [])

print("\n== #1182 the routine bank only asks what applies ==")
_POLICY.clear()
needs(caller=(4500, 9367), gallery=(2160, 4089))   # all covered
_STATE.update(paused=False, cover=99.0, target=1.0)  # studio busy
qs = routine()
asks = [q["ask"][:46] for q in qs]
print("     all covered, studio busy ->", len(qs), asks)
check("all covered + busy -> only the two always-live dials", len(qs) == 2)
check("  ...no 'which road would you like more of'",
      not any("more of" in q["ask"] for q in qs))
check("  ...no 'nothing is prepared' question",
      not any("nothing is prepared" in q["ask"] for q in qs))
check("  ...no repeat-rest question while nothing repeats",
      not any("repeat be allowed back" in q["ask"] for q in qs))
check("  ...no build-ahead question with no idle studio",
      not any("build ahead" in q["ask"] for q in qs))

_STATE.update(paused=True)
qs = routine()
check("paused -> the build-ahead question comes back",
      any("build ahead" in q["ask"] for q in qs), str([q["ask"][:40] for q in qs]))

_POLICY["repeats_hard"] = True
_STATE.update(paused=False, cover=99.0, target=1.0)
qs = routine()
check("repeats allowed under-rested -> the rest question comes back",
      any("repeat be allowed back" in q["ask"] for q in qs))

print("\n== #1182 'which road would you like more of' ==")
_POLICY.clear()
needs(ad=(2160, 100), track_talk=(720, 0), caller=(4500, 9367),
      news=(2160, 0), banter=(1440, 8053))
for _ in range(25):
    qs = routine()
    more = [q for q in qs if "more of" in q["ask"]]
    if not more:
        continue
    v = [o["does"] for o in more[0]["options"]]
    if any(x.startswith("prefer:") for x in v):
        fails.append("more-of still fires prefer:")
    if "drive:news" in v:
        fails.append("more-of offers short-horizon news")
    if "drive:caller" in v:
        fails.append("more-of offers a covered road")
    if "drive:banter" in v:
        fails.append("more-of offers a road not on the board")
    if "drive:none" not in v:
        fails.append("more-of cannot be taken back")
check("'more of' fires drive:, only behind+buildable roads, always clearable",
      not fails, "; ".join(sorted(set(fails))[:3]))
qs = routine()
while not [q for q in qs if "more of" in q["ask"]]:
    qs = routine()
more = [q for q in qs if "more of" in q["ask"]][0]
print("     ask :", more["ask"])
for o in more["options"]:
    print("       %-30s -> %s" % (o["face"], o["does"]))

print("\n== #1182 the phone-call question says its real scope ==")
check("no question names one road while setting a station-wide rule",
      not any("phone call is due" in q["ask"]
              for _ in range(25) for q in routine()))
needs(ad=(2160, 100))
found = ""
for _ in range(40):
    for q in routine():
        if "nothing is prepared" in q["ask"]:
            found = q["ask"]
check("the station-wide empty-entry question says 'on any road'",
      "on any road" in found, found[:70])
print("     ask :", found)

print("\n== #1181 a standing pin is always answerable ==")
_POLICY["drive_road"] = "track_talk"
seen = 0
for _ in range(12):
    qs = routine()
    if "still being built ahead" not in qs[0]["ask"]:
        fails.append("pin not asked first")
    if any(o["does"] == "drive:none" for o in qs[0]["options"]):
        seen += 1
check("pin standing -> asked FIRST and always clearable", seen == 12,
      "%d/12" % seen)
print("     ask :", routine()[0]["ask"])

print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILURES",
                                len(fails)))
if __name__ == "__main__":
    sys.exit(1 if fails else 0)
