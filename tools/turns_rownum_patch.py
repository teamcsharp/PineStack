"""[s3-rownum] [s3-heading] What the writer returns is not all words: the row
numbers, the prompt's own headers and the segment's name printed as a heading
never reach a voice.

Measured on the host (ledger 2026-09-28 11:18Z, script_ledger.jsonl + air_log):
- ROW NUMBERS: 394 of 11,023 lines in 24 h (3.57%) ended in a stray running-order
  row number after the sentence - 362 of them HEARD ("...It's nothing to worry
  about. 5", "Cat. 6", "...graphics from the Pine Box gallery) 7"); by road banter
  236, gallery 102, gold 34, manager 14, news 8. The running order numbers its rows
  ("11  A  - ...") and the writer sometimes keeps the number: "10 A: ... 11 B: ..."
  split into turns leaves each row's number on the END of the turn before it.
- PROMPT HEADERS: 4 lines in 48 h, all heard, ended "... TONIGHT'S TEMPERS : 1" -
  the writer echoing the sheet's own header (banter 2; the gold bank re-aired 2).
- HEADINGS: 4 lines in 48 h, all heard, all single lines: three station IDs and an
  ad read opened on the on-air segment's name - "Call with banter A man's cat
  dragged someone into the sewer ..." (its brief, SCHEDULE #843: THE SEGMENT IS
  CALLED "Call with banter"), "Different news story You know, ...", "Painting
  selling The speakerbox opens ...", "Ad read Listen up folks, ...".

- writer_turn_clean(text, headings=()), one helper for every place the writer's
  output becomes a turn or a line: System 3's scaffold door (system3_scaffold_strip,
  installed by edit_scaffold_runtime.py) when it is there; a leading heading that
  is one of `headings`; a line that is only a number; a bare 1-2 digit number after
  the last sentence. A number the sentence holds ("gate 7 is open", "Ocean's 11",
  "call 911", "How many? 12.") never follows a finished sentence bare, and stays.
- writer_headings(*labels): the names a heading could be - what the brief on air
  called the segment (THE SEGMENT IS CALLED "...", THIS ROUND IS THE "..." ENTRY)
  and the road / round labels handed in. A heading goes only when a new sentence
  starts right after it (any case; ':' '-' a dash or a new line between); a
  one-word name only with that separator. "Welcome back to Call with banter!"
  never starts with the name, and stays.
- banter_turns - every round: banter, gallery, manager, news, recap, memo, calls -
  cleans each turn with it; gallery_turns (the sale check) too, so a row number is
  no longer read as a price.
- dj_line - the writer of every advert, station ID, intro, outro, request,
  interject and reply - cleans its line with it, headings included, before the
  second (crystal) pass. (Not in dj_speak: the lines after the write there are
  tools/single_line_fixes_patch.py's own text.)
- spoken_text, the one door every spoken line passes through, drops a bare 1-2
  digit number after the line's last sentence (belt and braces).
- gold_note banks no bar whose words the parse would now cut: its take says them.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("rownum-helper",
     r'''def banter_turns(script: str, caller_name: str = "",
                 caller2_name: str = "") -> list[tuple[str, str]]:
''',
     r'''# [s3-rownum] WHAT THE WRITER RETURNS IS NOT ALL WORDS. The running order numbers
# its rows and the writer sometimes keeps the number: "10 A: ... 11 B: ..." left
# each row's number on the END of the turn before it, and the station said it - 394
# of 11,023 ledger lines in a day (3.57%), 362 of them heard ("...It's nothing to
# worry about. 5", "Cat. 6", "...in here. 11"). A bare 1-2 digit number after the
# last sentence is that row number; a line that is only a number is never
# dialogue; and a writer prompt's own header echoed into the words ("TONIGHT'S
# TEMPERS : 1") is cut by System 3's scaffold door, which knows every label it
# writes into a prompt. A number the sentence holds ("gate 7 is open", "Ocean's
# 11", "call 911", "How many? 12.") is never bare after a finished sentence, and stays.
_ROW_NUMBER_TAIL = re.compile(r"(?<=[.!?\u2026\"\u201d'\u2019)\]])\s+\d{1,2}\s*$")
_ROW_NUMBER_LINE = re.compile(r"(?m)^[ \t]*\d{1,3}[.)]?[ \t]*$")
# [s3-heading] A SEGMENT'S NAME PRINTED AS A HEADING IS NOT A WORD. 2026-09-28, a
# station ID aired "Call with banter A man's cat dragged someone into the sewer, ..."
# - its brief (SCHEDULE #843) said THE SEGMENT IS CALLED "Call with banter", the
# writer printed the name as a heading and the line joined it (4 single lines in 48
# h, all heard). A leading heading that is one of the round's names - any case,
# ':' '-' a dash or a new line after it - goes when a new sentence starts right
# after it; a one-word name only with that separator ("News: The ..." goes, "Call
# Dill now" stays). "Welcome back to Call with banter!" does not start with it.
_HEADING_OPEN = r"^[ \t*_#>\"\u201c'\u2018]*"
_HEADING_CLOSE = r"[*_\"\u201d'\u2019]*"
_HEADING_SEP = r"(?:[ \t]*[:\-\u2013\u2014][ \t\n]*|[ \t]*\n[ \t\n]*)"
_HEADING_NEXT = r"(?=[\"\u201c\u2018'*_]*[A-Z0-9])"
_HEADING_NOT = {"caller", "host", "the host", "co-host", "cohost", "the co-host", "dj", "third", "guest"}
_HEADING_RX: dict[tuple[str, ...], Any] = {}


def writer_headings(*labels: Any) -> tuple[str, ...]:
    """[s3-heading] The names the writer of the round being written now could
    print as a heading: what the brief on air called the segment and its entry,
    and the road / round labels handed in. Longest first."""
    names: list[str] = []
    try:
        brief = str(_schedule_prompt_clause() or "")
        names += re.findall(r'THE SEGMENT IS CALLED "([^"\n]{2,80})"', brief)
        names += re.findall(r'THIS ROUND IS THE "([^"\n]{2,80})" ENTRY', brief)
    except Exception:  # noqa: BLE001
        pass
    for lab in labels:
        names.append(str(lab or "").replace("_", " "))
    out: list[str] = []
    for name in names:
        name = " ".join(str(name).split()).strip(" .:-")
        if (len(name) >= 3 and name.casefold() not in _HEADING_NOT
                and name.casefold() not in {x.casefold() for x in out}):
            out.append(name)
    return tuple(sorted(out, key=len, reverse=True))


def _heading_cut(text: str, names: Any) -> str:
    key = tuple(str(n) for n in (names or ()) if str(n or "").strip())
    if not key:
        return text
    rx = _HEADING_RX.get(key)
    if rx is None:
        alts = []
        for name in key:
            words = name.split()
            core = r"[ \t]+".join(re.escape(w) for w in words)
            sep = _HEADING_SEP if len(words) < 2 else r"(?:%s|[ \t]+)" % _HEADING_SEP
            alts.append(r"(?i:%s)%s%s" % (core, _HEADING_CLOSE, sep))
        rx = re.compile(_HEADING_OPEN + r"(?:%s)" % "|".join(alts) + _HEADING_NEXT)
        if len(_HEADING_RX) > 32:
            _HEADING_RX.clear()
        _HEADING_RX[key] = rx
    return rx.sub("", text, count=1)


def writer_turn_clean(text: Any, headings: Any = ()) -> str:
    """One turn (or one single line) of the writer's output, as it may be said.
    `headings`: the names a leading heading could be (writer_headings())."""
    out = str(text or "")
    cut = globals().get("system3_scaffold_strip")
    if callable(cut) and out.strip():
        try:
            out = str(cut(out))
        except Exception:  # noqa: BLE001
            pass
    if headings:
        try:
            out = _heading_cut(out, headings)
        except Exception:  # noqa: BLE001
            pass
    out = _ROW_NUMBER_LINE.sub("", out).strip()
    return _ROW_NUMBER_TAIL.sub("", out).strip()


def banter_turns(script: str, caller_name: str = "",
                 caller2_name: str = "") -> list[tuple[str, str]]:
''', 1),
    ("rownum-banter-turns",
     r'''    turns = [(parts[i].upper(), parts[i + 1].strip())
             for i in range(1, len(parts) - 1, 2)]
''',
     r'''    turns = [(parts[i].upper(), writer_turn_clean(parts[i + 1]))   # [s3-rownum]
             for i in range(1, len(parts) - 1, 2)]
''', 1),
    ("rownum-gallery-turns",
     r'''        body = str(parts[i + 1] or "").strip()
        if body:
            turns.append(body)
''',
     r'''        body = writer_turn_clean(parts[i + 1])     # [s3-rownum] a row number is not a price
        if body:
            turns.append(body)
''', 1),
    ("rownum-line-writer",
     r'''        if answer:
            # #1038: THE SECOND PASS, on the road that writes most of the
''',
     r'''        # [s3-rownum] [s3-heading] THE WRITER'S LINE IS PARSED LIKE A ROUND'S TURNS:
        # a running-order row number, an echoed prompt header and the segment's
        # name printed as a heading ("Call with banter A man's cat ..." - a station
        # ID, 2026-09-28) never reach the voice, on every line this writer returns
        if answer:
            answer = writer_turn_clean(answer, writer_headings(kind))
        if answer:
            # #1038: THE SECOND PASS, on the road that writes most of the
''', 1),
    ("rownum-spoken-text",
     r'''    clean = strip_banned(clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    # #870: the English rule, at the one door every spoken line uses.
    return english_only(clean)
''',
     r'''    clean = strip_banned(clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    # [s3-rownum] belt and braces: a running-order row number left after the last
    # sentence ("...in here. 11") is never said, whichever road wrote the line
    clean = re.sub(r"(?<=[.!?\u2026\"\u201d'\u2019)\]])\s+\d{1,2}\s*$", "", clean).strip()
    # #870: the English rule, at the one door every spoken line uses.
    return english_only(clean)
''', 1),
    ("rownum-gold-note",
     r'''        if not text or not name or not rap_rhyme_evidence(text).get("ok"):
            return False
        key = hashlib.sha1(text.lower().encode("utf-8", "ignore")).hexdigest()[:16]
''',
     r'''        if not text or not name or not rap_rhyme_evidence(text).get("ok"):
            return False
        if writer_turn_clean(text) != text:
            return False    # [s3-rownum] its take says a row number or a prompt header
        key = hashlib.sha1(text.lower().encode("utf-8", "ignore")).hexdigest()[:16]
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
