"""[s3-echo] A running-order direction said as dialogue never airs - app.py's half.

2026-09-28, AIRED (line cb38bcc872164cf7b74b09c3736729a4, a banter round): "I can't
believe it and says so, and widens it out to the bigger picture." - its row read
"... feeling repulsion (plainly) about it: cannot believe it and says so, and widens
it out to the bigger picture." (RS2 disbelief + FL2 broaden). The station had two
checks, and both read a row's FIRST clause only ("answers what Skip just said
(..."): #1462's beat check and s3-line-fix's single-line check. The ledger, 48 h:
see edit_scaffold_engine.py's census in the report.

System 3's matcher (system3.direction_kit / direction_echo, the door
system3_direction_echo installed by edit_scaffold_runtime.py) reads every clause
of a row - its acts, its flow, its feeling, the row grammar - with the words meant
to be said left out, contractions folded and a stumble read once. Here it reaches
the station's existing gates:

- _beat_speaks_direction (#1462, the banked beat chain): a turn that says ANY
  clause of its row ends the accepted prefix, so the retry - or the next beat -
  writes that turn again (the existing rewrite gate, logged as banter_beat_echo).
- the single-line road (dj_speak): after s3-line-fix's own check and its one
  rewrite, a line that still says a direction of its sheet is WITHHELD - System 3
  records why (system3_withhold) and the drop log says so.
- a round's turns: the REPAIR roll sends a banked draft back (validate() flags it)
  and the runtime cuts a turn that still says one before the bind - both in
  edit_scaffold_runtime.py, nothing here.

Needs edit_scaffold_engine.py + edit_scaffold_runtime.py (without them the door is
absent and every check here stands down to the station's own first-clause test).

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("echo-beat-check",
     r'''    core = words(re.split(r"[,.;]", str(row.get("work") or ""), 1)[0])
    return len(core) >= 12 and core in words(text)
''',
     r'''    core = words(re.split(r"[,.;]", str(row.get("work") or ""), 1)[0])
    if len(core) >= 12 and core in words(text):
        return True
    # [s3-echo] ...and ANY other clause of the row: its act, its flow, its feeling.
    # "I can't believe it and says so, and widens it out to the bigger picture."
    # AIRED (2026-09-28) - the row's RS2 and FL2 directions, not its first clause.
    # System 3's matcher, when it is installed.
    _echo = globals().get("system3_direction_echo")
    return bool(callable(_echo) and _echo(text, str(row.get("work") or "")))
''', 1),
    ("echo-line-road",
     r'''    if not spoken or not re.search(r"[^\W_]", spoken):
        return ""
    if line_forgotten(spoken):
''',
     r'''    if not spoken or not re.search(r"[^\W_]", spoken):
        return ""
    # [s3-echo] A LINE THAT SAYS A DIRECTION OF ITS SHEET NEVER AIRS. The check above
    # (s3-line-fix) reads each row's FIRST clause and buys one rewrite; a line can
    # say any other clause - its act, its flow, its feeling. Every clause of the
    # sheet's rows, contractions folded, a stumble read once: the line is withheld,
    # System 3 records why, and the drop log says so.
    if not line and _s3_sheet and callable(globals().get("system3_direction_echo")):
        _echo_said = globals()["system3_direction_echo"](spoken, _s3_sheet)
        if _echo_said:
            pipeline_log("drop", "a %s line from %s said its running-order direction - withheld"
                         % (kind, who), extra=("%s | %s" % (_echo_said, spoken))[:300])
            if _s3_spoken_handle is not None and globals().get("system3_withhold"):
                globals()["system3_withhold"](_s3_spoken_handle, "the line said its running-order "
                                              "direction: " + _echo_said[:120], "writing")
            return ""
    if line_forgotten(spoken):
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
