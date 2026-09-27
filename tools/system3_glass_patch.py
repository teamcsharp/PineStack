"""System 3 and the orchestrator: the round's length is a roll, the record
link binds the words it returns, and the glass reads the dice of the line
on air (that part lives in system3_runtime: GET /api/system3/now).

Operator, 2026-09-27: "make sure the orchestrator and the popup is
connected and understanding how to coordinate and work with system3 and
scheduling segments and making sure dialogue length and banter exchanges
are long and exponential enough to encompass the time segments ... I want
the popup orchestrator windows showing RNG and rolodex information and I
want glyphy reactive to the dice / roulette results."

app.py edits ([s3-glass]):
  LENGTH      a free round's turn count was random.randint(banter_min_lines,
              banter_max_lines) - the dial's random. dj_banter now tells
              System 3 that the count was a roll (and the range); System 3
              rolls it (LENGTH event, recorded, replayable) and the round
              takes System 3's count. A round the slot on air or System 2
              sized keeps that size: a budget is an obligation, not a roll.
  RECORD LINK the words track_talk_write RETURNS are bound to its node - the
              deterministic fallback included - never the raw answer alone
              (the first two links after the roads patch read "dropped").

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes
LF atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("length-roll",
     '    if lines <= 0:\n'
     '        lines = random.randint(dj["banter_min_lines"], dj["banter_max_lines"])\n',
     '    _lines_rolled, _lines_base = False, 0     # [s3-glass] the dial\'s random stood here\n'
     '    if lines <= 0:\n'
     '        lines = random.randint(dj["banter_min_lines"], dj["banter_max_lines"])\n'
     '        _lines_rolled, _lines_base = True, int(lines)\n', 1),
    ("length-slot",
     '            if _budget.get("lines"):\n'
     '                lines = max(4, min(int(_budget["lines"]),\n'
     '                                   int(dj.get("banter_max_lines") or 22)))\n',
     '            if _budget.get("lines"):\n'
     '                lines = max(4, min(int(_budget["lines"]),\n'
     '                                   int(dj.get("banter_max_lines") or 22)))\n'
     '                _lines_rolled = False          # [s3-glass] the slot decided, not the dice\n', 1),
    ("length-kwargs",
     '                    road=str(road or ""), whole=bool(whole))   # [s3-roads]\n',
     '                    road=str(road or ""), whole=bool(whole),   # [s3-roads]\n'
     '                    lines_rolled=bool(_lines_rolled), lines_base=int(_lines_base),   # [s3-glass]\n'
     '                    lines_min=int(dj.get("banter_min_lines") or 4),\n'
     '                    lines_max=int(dj.get("banter_max_lines") or 22))\n', 1),
    ("length-owns",
     '        _s3_owns = bool(_s3 is not None and _s3.active and _s3.sheet)\n',
     '        _s3_owns = bool(_s3 is not None and _s3.active and _s3.sheet)\n'
     '        if _s3_owns and int(getattr(_s3, "turns", 0) or 0) > 0:\n'
     '            # [s3-glass] a free round\'s length is System 3\'s roll\n'
     '            lines = int(_s3.turns)\n'
     '            _judge_lines = min(int(_judge_lines), lines)\n', 1),
    ("link-bind",
     '    except Exception:  # noqa: BLE001\n'
     '        answer = ""\n'
     '    if _s3l is not None:                                      # [s3-roads]\n'
     '        if globals().get("system3_bind_line"):\n'
     '            globals()["system3_bind_line"](_s3l, answer)\n'
     '        if isinstance(track, dict):\n'
     '            track["_s3_line_" + str(part)] = dict(_s3l.stamp)\n'
     '    if track_talk_text_report(answer, track, part).get("ok"):\n'
     '        return answer\n',
     '    except Exception:  # noqa: BLE001\n'
     '        answer = ""\n'
     '\n'
     '    def _s3_bound(_text: str) -> str:\n'
     '        # [s3-glass] the words the road RETURNS are the ones bound to the\n'
     '        # node - the fallback link included - never the raw answer alone\n'
     '        if _s3l is not None:\n'
     '            if globals().get("system3_bind_line"):\n'
     '                globals()["system3_bind_line"](_s3l, _text)\n'
     '            if isinstance(track, dict):\n'
     '                track["_s3_line_" + str(part)] = dict(_s3l.stamp)\n'
     '        return _text\n'
     '    if track_talk_text_report(answer, track, part).get("ok"):\n'
     '        return _s3_bound(answer)\n', 1),
    ("link-bind-intro",
     '    if part == "intro":\n'
     '        return (f"{identity} is coming into focus now. Listen for the shape "\n'
     '                "of the arrangement as it opens, and let the record take the "\n'
     '                "room from here.")\n',
     '    if part == "intro":\n'
     '        return _s3_bound(f"{identity} is coming into focus now. Listen for the shape "\n'
     '                         "of the arrangement as it opens, and let the record take the "\n'
     '                         "room from here.")\n', 1),
    ("link-bind-outro",
     '    return (f"That was {identity}, holding its character all the way through. "\n'
     '            "Keep that last turn in mind while the station moves cleanly into "\n'
     '            "what comes next.")\n',
     '    return _s3_bound(f"That was {identity}, holding its character all the way through. "\n'
     '                     "Keep that last turn in mind while the station moves cleanly into "\n'
     '                     "what comes next.")\n', 1),
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
