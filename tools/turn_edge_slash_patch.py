"""[s3-slash] A slash or a speaker marker at the front of a turn is not a word:
the writer is no longer taught "A:/B:", the parser that owns the markers takes
the whole marker run, and the last gates before a voice and before the script
row take the edge off whatever road the line came by.

Measured on the host (2026-09-29 04:30Z; script_ledger.jsonl 48 h, the model
calls in prompt_history.sqlite3, the stores under data/):
- 104 aired lines in 48 h opened on "/" (83 "/text", 21 "/B: text"), all since
  2026-09-28 13:51Z, 70 + 21 of them in the last 12 h: manager 52, recap 14, news 9,
  banter 11, gallery 4, gold interject 9 (one bar fired 8 times), ad 4, intro 1.
  Operator 2026-09-28 ~23:00 local: SKIP "/Out of hand? Are you kidding me?...",
  DILL "/B: every pause is a calculated opportunity...".
- THE WRITER WAS TOLD THE MARKER IS "A:/B:". The phone/radio rewrite asks
  "Return only A:/B: dialogue" and the banter beat "the listed A:/B:/C:/D: marker";
  gemma4:e2b copied the token: "A:/B: text", "B:/text" (writing 41 calls, banter
  beat 17, writers room 6, turn rewrite 1 in 60 h). The same small model doubles
  a marker too: "A: A: Well, maybe ..." (banter beat, 09-27; 4 lines re-aired
  from the gallery bank in the last 12 h as "A: Well ...", "B: Manage ...").
- THE SPLIT LEFT IT ON. banter_turns splits on "(?:^|\\s)([ABCDE])\\s*:\\s*": "A:"
  is taken and "/B: text" is the turn ("/" is not the white space a marker needs
  before it; in "A: A: text" the first marker's \\s* eats the space the second
  needs). spoken_text kept the "/" and the "B:", the chunker keyed the pantry on
  it, and XTTS's sanitiser turns "/" into a space but still reads the "B".
- STORED BANKS hold it (repaired by tools/turn_edge_slash_store_repair.py):
  manager_memos 8, prep_shelf 182 fields, larder 59, pantry 94, gold_bars 2,
  said_lines 75, system3_chapter_shelf 2.

The edits:
- turn_edge_clean(text, markers=True): the edge of ONE turn - never its middle -
  loses every leading slash, pipe or backslash and every speaker marker it opens
  on ("A:/B: ", "/B: ", "A: A: "). markers=False takes a marker only where a slash
  stands before it (text that may still be a whole "A: ... B: ..." script).
- banter_turns (every parsed turn of every round: banter, gallery, manager, news,
  recap, memo, calls, the beats, the [s3-chain] replies) cleans each turn's edge
  after [s3-rownum]'s writer_turn_clean (its text is left verbatim so its --check
  still reads applied).
- banter_turns splits on " /B:" too, so a slash before a marker starts the turn.
- spoken_text (the one door every spoken line uses) takes a slashed edge.
- voice_generate (every engine render) takes the edge off the words sent to the
  engine, the way it already turns a dangling dash into an ellipsis.
- script_ledger_commit (the script row, and System 3's register fed from the same
  rows) and airlog_row_from (the durable feed) write a speaking seat's line
  without its edge (a board / sfx / host row is written as it is).
- the two prompts that taught the token name the markers one at a time.

The [s3-chain] reply writer (tools/system3_exchange_chain*_patch.py) parses with
banter_turns, so it is cleaned through this road; its own prompt line
"using only the listed A:/B:/C:/D: marker" is left to it (not an anchor here).

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("slash-helper",
     r'''def spoken_text(line: str) -> str:
''',
     r'''# [s3-slash] A SLASH OR A SPEAKER MARKER AT THE FRONT OF A TURN IS NOT A WORD.
# 2026-09-28/29: 104 aired lines in 48 h opened on "/" - "/Out of hand? Are you
# kidding me?", "/B: every pause is a calculated opportunity ..." - on the manager,
# recap, news, banter, gallery, gold and ad roads. The writer had been TOLD the
# marker was "A:/B:" ("Return only A:/B: dialogue", "the listed A:/B:/C:/D:
# marker") and the small model copied it - "A:/B: text", "B:/text" - or doubled a
# marker - "A: A: text". The split took "A:" and left "/B: text" (a "/" is not the
# white space a marker needs before it, and in "A: A:" the first marker eats it),
# and XTTS's sanitiser drops the "/" but reads the "B". The EDGE of a turn - never
# its middle - loses every slash, pipe or backslash and every marker it opens on.
_TURN_EDGE = re.compile(r"^(?:\s*[/\\|]+|\s*[ABCDE]\s*:(?!\d))+\s*")
_TURN_EDGE_SLASH = re.compile(r"^\s*(?:[/\\|]+\s*(?:[ABCDE]\s*:(?!\d)\s*)?)+")
TURN_EDGE_SEATS = ("dj", "cohost", "third", "caller", "caller2", "guest")


def turn_edge_clean(text: Any, markers: bool = True) -> str:
    """[s3-slash] One turn or one line without the stray edge on its front: a run
    of slashes / pipes / backslashes and (`markers`) the speaker markers the writer
    left there ("A:/B: ", "/B: ", "A: A: "). markers=False takes a marker only
    where a slash stands before it - for text that may still be a whole script."""
    s = str(text or "")
    m = (_TURN_EDGE if markers else _TURN_EDGE_SLASH).match(s)
    return s[m.end():] if m and m.end() else s


def turn_edge_row_text(row: Any) -> str:
    """[s3-slash] A script / feed row's words: a speaking seat's line without its
    edge (a clip label, a board cue or a marker row is written as it is)."""
    text = str((row or {}).get("text") or "")
    if str((row or {}).get("who") or "") not in TURN_EDGE_SEATS:
        return text
    return turn_edge_clean(text) or text


def turn_edge_rows(rows: Any) -> Any:
    """[s3-slash] Script rows as they are written down: a speaking seat's row
    whose line opens on an edge is copied without it; every other row is itself."""
    out = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("text"):
            text = turn_edge_row_text(row)
            if text != row.get("text"):
                row = dict(row, text=text)
        out.append(row)
    return out


def spoken_text(line: str) -> str:
''', 1),
    ("slash-turns",
     r'''             for i in range(1, len(parts) - 1, 2)]
    # A model's repeated A is still A's text. Responses are explicit separate
''',
     r'''             for i in range(1, len(parts) - 1, 2)]
    # [s3-slash] the edge of every turn: "/B: ...", "A: A: ...", "B:/..." is the words
    turns = [(m, turn_edge_clean(x).strip()) for m, x in turns]
    # A model's repeated A is still A's text. Responses are explicit separate
''', 1),
    ("slash-split",
     r'''    parts = re.split(r"(?:^|\s)([ABCDE])\s*:\s*", " " + script,
''',
     r'''    # [s3-slash] " /B:" is a marker too: a slash before it no longer hides it
    parts = re.split(r"(?:^|\s)[/\\|]*([ABCDE])\s*:\s*", " " + script,
''', 1),
    ("slash-spoken-text",
     r'''    clean = SPOKEN_NOISE.sub(" ", _pb_unmark(str(line or "")))
    clean = re.sub(r"https?://\S+", "", clean)
''',
     r'''    clean = SPOKEN_NOISE.sub(" ", _pb_unmark(str(line or "")))
    clean = re.sub(r"https?://\S+", "", clean)
    # [s3-slash] a slash (and a marker behind it) on the front is never said
    clean = turn_edge_clean(clean, markers=False)
''', 1),
    ("slash-voice",
     r'''    text = re.sub(r"[—–-]+\s*$", "…", text)
''',
     r'''    text = re.sub(r"[—–-]+\s*$", "…", text)
    # [s3-slash] ...and never a slash or a speaker marker on its front: whatever
    # road the words came by, the engine is not handed "/B: every pause ..."
    text = turn_edge_clean(text) or text
''', 1),
    ("slash-ledger",
     r'''    out: list[str] = []
    for ord_, row in enumerate(rows):
        out.append(json.dumps({
''',
     r'''    out: list[str] = []
    # [s3-slash] a speaking seat's line is written down without a slash or a speaker
    # marker on its front, whichever road it came by (System 3's register too)
    rows = turn_edge_rows(rows)
    for ord_, row in enumerate(rows):
        out.append(json.dumps({
''', 1),
    ("slash-airlog",
     r'''        "text": " ".join(str(entry.get("text") or "").split())[:600],
''',
     r'''        "text": " ".join(turn_edge_row_text(entry).split())[:600],      # [s3-slash]
''', 1),
    ("slash-prompt-beat",
     r'''              "the listed A:/B:/C:/D: marker. No preface, labels, markdown, stage "
''',
     r'''              "the listed marker (A:, B:, C: or D:), once, at the start of the line. "   # [s3-slash]
              "No preface, labels, markdown, stage "
''', 1),
    ("slash-prompt-rewrite",
     r'''                + "Return only A:/B"
                + ("/C" if caller_name else "/D" if _system2_budget and dj.get("third_name") else "") + ": dialogue. Keep its "
''',
     r'''                + "Return only dialogue lines, each opening on ONE speaker marker - A: or B:"   # [s3-slash]
                + (" or C:" if caller_name else " or D:" if _system2_budget and dj.get("third_name") else "") + ". Keep its "
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
