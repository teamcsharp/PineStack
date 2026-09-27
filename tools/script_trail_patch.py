"""The script view's jumps: an unheard row hangs where #1308 trailed it,
not on its estimate ([#1308c]); a jump to air from a tap is the
operator's, not a fault ([#1309]).

Measured 2026-09-27 from the inbox's own captures (#1288-#1309, all
"Script diagnostic capture"):

  #1306  "8 line(s) standing between the first and last marked element
          were never put out (prepared x8); the mark steps over them and
          that step is the jump" - the pane moved 2138 px.
  #1301  "the highlighted identity moved to an earlier element ... the
          script pane moved by as much as 18402 px".

Cause: #1308 trails every unheard row past the floor of what was heard
(`_e["at"] = _floor + 1.0 + step`), and #1218 A1's P1.3 then hung every
row off the spine by `screenplay_when_heard(row)` - which, for a row
NOBODY HAS HEARD, returns its air_at ESTIMATE. A banked round whose
planned slot had passed was bisected into the middle of the heard spine
by that estimate; the mark stepped over it (#1306) and, when the round
finally aired, jumped back up to it (#1301). The hanger now takes the
trailed stamp for an unheard row, so banked work sits under the live
line until it is heard, and is then already where its hearing puts it.

#1309's "moved automatically by 1067 px; owner jump-to-air:live strip"
was the operator's own tap on the live strip (record 21: follow false ->
true, lit line brought from -851 px to 250 px). The analyser counts a
jump-to-air from a tap as an observation, never a fault.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. Two files: app.py and script_diagnostics.py. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = {
    "app.py": [
        ("unheard-hangs-where-it-trailed",
         '        _raw_of[_ix] = (screenplay_when_heard(_row)\n'
         '                        or float(_e.get("at") or 0))\n',
     '        # [#1308c] AN UNHEARD ROW HANGS WHERE #1308 TRAILED IT. For a row\n'
     '        # nobody has heard, screenplay_when_heard() is its air_at\n'
     '        # ESTIMATE, and a banked round whose planned slot had passed was\n'
     '        # bisected into the middle of the heard spine by it: the mark\n'
     '        # stepped over eight lines nobody said (#1306, 2138 px) and, when\n'
     '        # the round aired, jumped back up to them (#1301, 18402 px). The\n'
     '        # trailed stamp keeps banked work under the live line until it\n'
     "        # is heard - and once heard, the ear's stamp is that same tail.\n"
     '        _raw = ((screenplay_when_heard(_row) if screenplay_was_heard(_row)\n'
     '                 else float(_e.get("at") or 0))\n'
     '                or float(_e.get("at") or 0))\n'
     '        # [#1315] A ROW THE EAR HAS PLACED KEEPS THAT SLOT until the ledger\n'
     '        # files it. Before the ear speaks, the estimate may still move the row\n'
     '        # (that is the region at or below the live line); a re-ack afterwards\n'
     '        # used to reindex every row above the reader. (block, ord) overrules.\n'
     '        _lid = str(_row.get("id") or "")\n'
     '        if _lid and line_heard_at(_row) > 0:            # the EAR has spoken\n'
     '            _raw = _HANGER_SLOT.setdefault(_lid, _raw)\n'
     '            if len(_HANGER_SLOT) > 6000:\n'
     '                for _k in list(_HANGER_SLOT)[:2000]:\n'
     '                    _HANGER_SLOT.pop(_k, None)\n'
     '        _raw_of[_ix] = _raw\n', 1),
    ],
    "script_diagnostics.py": [
        ("a-tap-is-not-a-fault",
         "                    and owner and not any(word in owner.lower()\n"
         "                                          for word in ('user', 'wheel', 'touch', 'drag'))):\n",
         "                    and owner and not any(word in owner.lower()\n"
         "                                          for word in OPERATOR_SCROLL_OWNERS)):\n", 1),
        ("the-operator's-own-owners",
         "def analyze_capture(",
         "# [#1309] Scroll owners that are the operator's own doing: a wheel or a\n"
         "# finger, and a jump to air asked for by a tap (the live strip, a feed\n"
         "# detail's button, the segment navigator, a cue). The pane moving under\n"
         "# those is what was asked for, never a fault. 'jump-to-air:live cue\n"
         "# window' is not here: the cue window can call it on its own.\n"
         "OPERATOR_SCROLL_OWNERS = ('user', 'wheel', 'touch', 'drag',\n"
         "                          'jump-to-air:live strip', 'jump-to-air:feed detail',\n"
         "                          'jump-to-air:segment navigator', 'jump-to-air:image analysis',\n"
         "                          'jump-to-air:readiness', 'jump-to-air:current cue',\n"
         "                          'jump-to-air:control')\n"
         "\n"
         "\n"
         "def analyze_capture(", 1),
    ],
}


def plan(name):
    return list(EDITS.get(Path(name).name, []))


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(name, text):
    applied, missing = 0, []
    for label, old, new, count in plan(name):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (label, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(path.name, text)
    if applied == len(plan(path.name)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for label, old, new, count in plan(path.name):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    targets = [a for a in argv if not a.startswith("--")] or ["app.py", "script_diagnostics.py"]
    worst = 0
    for target in targets:
        if not plan(target):
            print(target, ": nothing planned for this file")
            worst = max(worst, 1)
            continue
        if "--apply" in argv:
            code = apply(target)
            print(target, {0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        else:
            text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
            applied, missing = check(target, text)
            if missing:
                for m in missing:
                    print("missing:", m)
                code = 1
            elif applied == len(plan(target)):
                print(target, "already applied")
                code = 2
            else:
                print(target, "ready")
                code = 0
        worst = code if code == 1 or worst == 1 else max(worst, code)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
