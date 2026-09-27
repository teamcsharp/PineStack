"""Three faults in the single-line roads, measured 2026-09-27 ([s3-line-fix]).

1. THE LEDGER NEVER GOT A SINGLE LINE'S STAMP. script_ledger_catch_up asked
   _s3_line_stamp_of(one) twice in one expression - once to test it, once
   for the value - and the function POPS the stamp dj_speak remembered for
   the id, so the second call returned None and script_ledger_commit dropped
   the non-dict. Of the last 3,000 ledger rows every one of the 2,144 stamps
   belonged to a round row; no intro, interjection or station ID carried
   one, so /api/system3/line could never link a single line to its node.
   Asked once now.

2. THE RUNNING ORDER WAS SPOKEN. A single line's node hands dj_line its
   sheet (" 1  D  - shouts the station's name like it is the only station
   there is ..."), and four times in the air log the model returned that
   row as the line: "D shouts the station's name like it is the only
   station there is". The banked beat writer has had this check since
   #1462 (_beat_speaks_direction); the single-line door had none. A line
   that speaks its own direction is written again once, without the sheet
   (the feeling still rides perf_directive); if that too echoes, the line
   is withheld and the log says so.

3. THE NODE SAT IN THE WRONG SEAT. plan_line took the leg's seat over the
   speaker's (`leg.get("seat") or seats[0] if seats else "A"` binds as
   `(leg or seats[0]) if seats else "A"`): the dj's station ID was planned
   as seat D, a cohost's send-off as seat A, so the emotion rolled for the
   wrong participant and the sheet named the wrong seat. The seat the door
   passed in (the speaker) wins; the leg's seat is the default for a road
   that names none.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes
app.py and system3.py (LF, byte IO). ON THE HOST.
"""
import sys
from pathlib import Path

APP = [
    ('              # [s3-roads] and its System 3 node, when it has one\n'
     '              **({"system3": _s3_line_stamp_of(one)}\n'
     '                 if _s3_line_stamp_of(one) else {})}\n',
     '              # [s3-roads] and its System 3 node, when it has one - asked ONCE:\n'
     '              # the stamp is popped on read, so a second ask returned None and\n'
     '              # no single line ever reached the ledger stamped [s3-line-fix]\n'
     '              **({"system3": _st} if (_st := _s3_line_stamp_of(one)) else {})}\n'),
    ('def _beat_speaks_direction(text: str, row: dict[str, Any]) -> bool:\n',
     'def _sheet_speaks_direction(text: str, sheet: str) -> str:\n'
     '    """[s3-line-fix] The running-order row a single line echoed, or "".\n'
     '\n'
     '    Measured 2026-09-27: four aired station IDs read "D shouts the station\'s\n'
     '    name like it is the only station there is" - the node\'s own sheet row,\n'
     '    returned as the line. The same test as #1462\'s _beat_speaks_direction:\n'
     '    the row\'s first clause, twelve characters or more, inside the words."""\n'
     '    def words(value: Any) -> str:\n'
     '        return " ".join(re.findall(r"[a-z0-9\']+", str(value or "").casefold()))\n'
     '    said = words(text)\n'
     '    if not said:\n'
     '        return ""\n'
     '    for m in re.finditer(r"(?m)^\\s*\\d+\\s+[A-E]\\s+[-\\u2013\\u2014]\\s*(.+?)\\s*$", str(sheet or "")):\n'
     '        core = words(re.split(r"[,.;\\[]", m.group(1), 1)[0])\n'
     '        if len(core) >= 12 and core in said:\n'
     '            return m.group(0).strip()\n'
     '    return ""\n'
     '\n'
     '\n'
     'def _beat_speaks_direction(text: str, row: dict[str, Any]) -> bool:\n'),
    ('        spoken = spoken_text(await _floor_lend(\n'
     '            f"a {kind} line from {who} (back from its write)",\n'
     '            dj_line(kind, track, extra, seed,\n'
     '                    direct=perf_directive(vec) + weather_directive(who)\n'
     '                    + note + ("\\n\\n" + _s3_sheet if _s3_sheet else ""))))\n'
     '        if not by_hand:\n',
     '        spoken = spoken_text(await _floor_lend(\n'
     '            f"a {kind} line from {who} (back from its write)",\n'
     '            dj_line(kind, track, extra, seed,\n'
     '                    direct=perf_directive(vec) + weather_directive(who)\n'
     '                    + note + ("\\n\\n" + _s3_sheet if _s3_sheet else ""))))\n'
     '        # [s3-line-fix] a line that speaks its own running-order row is not\n'
     '        # a line: written again once without the sheet (the feeling still\n'
     '        # rides perf_directive); if that echoes too, withheld and said so\n'
     '        _echoed = _sheet_speaks_direction(spoken, _s3_sheet) if _s3_sheet else ""\n'
     '        if _echoed:\n'
     '            pipeline_log("system3", "a %s line from %s spoke its running-order row - written again "\n'
     '                                    "without the sheet" % (kind, who), extra=_echoed[:200])\n'
     '            spoken = spoken_text(await _floor_lend(\n'
     '                f"a {kind} line from {who} (written again)",\n'
     '                dj_line(kind, track, extra, seed,\n'
     '                        direct=perf_directive(vec) + weather_directive(who) + note)))\n'
     '            if _sheet_speaks_direction(spoken, _s3_sheet):\n'
     '                pipeline_log("drop", "a %s line from %s spoke its running-order row twice - withheld"\n'
     '                             % (kind, who), extra=spoken[:200])\n'
     '                return ""\n'
     '        if not by_hand:\n'),
]

ENGINE = [
    ('    for leg in legs[:want]:\n'
     '        seat = str(leg.get("seat") or seats[0] if seats else "A")\n',
     '    for leg in legs[:want]:\n'
     '        # [s3-line-fix] the speaker the door passed in is the node\'s seat;\n'
     '        # the leg\'s seat is the default for a road that names none. (This\n'
     '        # read `(leg or seats[0]) if seats else "A"`: the dj\'s station ID\n'
     '        # was planned as seat D and its sheet said so - on air, four times.)\n'
     '        seat = str((seats[0] if seats else "") or leg.get("seat") or "A")\n'),
]


def patch(path, edits):
    text = Path(path).read_bytes().decode("utf-8")
    assert "\r\n" not in text[:100000], path + " is CRLF - stop"
    todo = 0
    for old, new in edits:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:90]))
            return None
        text = text.replace(old, new)
        todo += 1
    return text, todo


def main(argv):
    apply = "--apply" in argv
    out = {}
    for path, edits in (("app.py", APP), ("system3.py", ENGINE)):
        got = patch(path, edits)
        if got is None:
            return 1
        out[path] = got
    todo = sum(n for _, n in out.values())
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, n) in out.items():
        if n:
            Path(path).write_bytes(text.encode("utf-8"))
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
