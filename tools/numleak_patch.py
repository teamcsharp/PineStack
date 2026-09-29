"""[num-leak] Bookkeeping numbers never reach a voice - app.py + system2_runtime.py.

2026-09-29, 12 h of air (1,444 voiced rows): six aired lines said a number nobody
meant - four running-order row numbers on the end of a turn ("...plain wrong 5",
"Shrug it off 3"), one turn reference ("the point I made in turn two"), one SFX
clip label said by the SFX guy ("26 clip-40.") that a five-line chapter then answered.
"On line 89,338: Name" is a desk marker row - never voiced (no take, 0 s).

Edits (small, anchored; the DIRECTION block is not touched):
  parse     banter_turns / gallery_turns cut row numbers in front of speaker markers
  gate      spoken_text's silent row-number regex becomes num_leak_gate(): the same
            rule plus clip labels, a clip's index before its words, and turn numbers -
            each cut written to the drop log and a technical line-review row
  prompts   _sfx_verdict is asked about the last thing a PERSON said; a board clip is
            its words, never its index, in a chapter's transcript/subject, a banked
            beat's transcript, the loose board node's context and the recap's dialogue
  teach     both output-format lines: no number before the letter; a turn's number is
            never a word to say

Needs bookkeeping_numbers.py at the repo root (copy it first).
Usage: python3 numleak_patch.py [--check|--apply] [repo_root]   (default: .)
--check exits 0 ready / 2 applied / 1 missing. Writes LF (CRLF kept if the file had it).
"""
import os
import sys
import tempfile
from pathlib import Path

APP = [
    ("parse-banter-turns",
     '''    script = re.sub(r"(^|\\s)([ABCDE])\\s*-\\s*", r"\\1\\2: ", script)
''',
     '''    script = re.sub(r"(^|\\s)([ABCDE])\\s*-\\s*", r"\\1\\2: ", script)
    # [num-leak] The running order's row numbers in front of the markers ("4 B: ...
    # 5 A: ...", folded onto one line by ask_model) are not words: cut here, where
    # they still stand before a marker, or each one ends the turn before it
    # ("...just plain wrong 5" AIRED 2026-09-29 - no full stop, so [s3-rownum] missed it).
    try:
        import bookkeeping_numbers as _bn
        script = _bn.row_numbers_cut(script)[0]
    except ImportError:
        pass
''', 1),
    ("parse-gallery-turns",
     '''    parts = _GALLERY_MARKER.split(text)
''',
     '''    try:                                        # [num-leak] a row number is not a word
        import bookkeeping_numbers as _bn
        text = _bn.row_numbers_cut(text)[0]
    except ImportError:
        pass
    parts = _GALLERY_MARKER.split(text)
''', 1),
    ("gate-spoken-text",
     '''    clean = re.sub(r"(?<=[.!?\\u2026\\"\\u201d'\\u2019)\\]])\\s+\\d{1,2}\\s*$", "", clean).strip()
''',
     '''    # [num-leak] ...and every other bookkeeping number: a clip label, a clip's index in
    # front of its words, the running order's turn numbers. Recorded, never silent.
    clean = num_leak_gate(clean)
''', 1),
    ("gate-helpers",
     '''# Why the last line did not reach the box. A silent speaker and a working
''',
     '''# [num-leak] THE LAST GATE FOR BOOKKEEPING NUMBERS (bookkeeping_numbers.py says why).
# Every cut is written down - the drop log and a technical line-review row, once per
# line - so a number taken out of a spoken line is never a silent edit.
_NUM_LEAK_SEEN: dict[str, float] = {}


def prompt_sfx_label(text: Any, board: bool = False) -> str:
    """[num-leak] A board clip as a writer may be told of it: its words, never its
    library index or file name ("a sound clip from the board ("dental plan in")").
    Any other text is itself. `board`: known to be a clip label without the glyph."""
    try:
        import bookkeeping_numbers as _bn
        return _bn.sfx_label_for_prompt(text, board)
    except Exception:  # noqa: BLE001
        return str(text or "")


def prompt_last_said(spoken: Any) -> str:
    """[num-leak] The last thing a PERSON said in a round's "who: text" list - never
    a board clip's label. "" when nobody spoke."""
    try:
        import bookkeeping_numbers as _bn
        return _bn.last_said(spoken)
    except Exception:  # noqa: BLE001
        items = list(spoken or [])
        return str(items[-1]) if items else ""


def num_leak_gate(text: Any) -> str:
    """[num-leak] `text` without the bookkeeping numbers a writer left in it."""
    text = str(text or "")
    try:
        import bookkeeping_numbers as _bn
    except Exception:  # noqa: BLE001
        return re.sub(r"(?<=[.!?\\u2026\\"\\u201d'\\u2019)\\]])\\s+\\d{1,2}\\s*$", "", text).strip()
    if not re.search(r"\\d|turn", text, re.I):
        return text
    labels: list[str] = []
    if re.search(r"\\d", text):
        try:
            _chat = _RADIO.get("chat") or []
            _tail = [_chat[i] for i in range(max(0, len(_chat) - 120), len(_chat))]
            labels = [str(r.get("text") or "") for r in _tail
                      if isinstance(r, dict) and r.get("who") == "board"]
        except Exception:  # noqa: BLE001
            labels = []
    out, hits = _bn.spoken_gate(text, labels)
    if not hits:
        return text
    key = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]
    if key not in _NUM_LEAK_SEEN:
        _NUM_LEAK_SEEN[key] = time.time()
        if len(_NUM_LEAK_SEEN) > 512:
            for old in sorted(_NUM_LEAK_SEEN, key=_NUM_LEAK_SEEN.get)[:256]:
                _NUM_LEAK_SEEN.pop(old, None)
        try:
            pipeline_log("drop", "[num-leak] a bookkeeping number was cut from a spoken line: "
                         + "; ".join(hits)[:200], extra=("%s -> %s" % (text, out))[:400])
        except Exception:  # noqa: BLE001
            pass
        try:
            line_review_capture("bookkeeping_number", text, out, reasons=hits,
                                context={"kind": "spoken", "stage": "last_gate"},
                                technical=True, disposition="rewrite")
        except Exception:  # noqa: BLE001
            pass
    return out


# Why the last line did not reach the box. A silent speaker and a working
''', 1),
    ("prompt-sfx-verdict",
     '''        asyncio.create_task(_sfx_verdict(spoken[-1]))
''',
     '''        # [num-leak] about the last thing a PERSON said: spoken[-1] was the board's
        # "board: 🔊 26 clip-40", and the SFX guy said "26 clip-40." on air (2026-09-29)
        _verdict_about = prompt_last_said(spoken)
        if _verdict_about:
            asyncio.create_task(_sfx_verdict(_verdict_about))
''', 1),
    ("prompt-loose-board",
     '''                     + str(row.get("text") or Path(str(sample)).stem))[:300])
''',
     '''                     + prompt_sfx_label(str(row.get("text") or Path(str(sample)).stem), True))[:300])  # [num-leak]
''', 1),
    ("prompt-chapter-subject",
     '''int(budget * S3_CHAPTER_WORDS_PER_SECOND), str(e.get("context") or opening)[:600]))
''',
     '''int(budget * S3_CHAPTER_WORDS_PER_SECOND), prompt_sfx_label(str(e.get("context") or opening))[:600]))  # [num-leak]
''', 1),
    ("prompt-chapter-transcript",
     '''        recent = "\\n".join("%s has just said - %s" % (m, t)
''',
     '''        recent = "\\n".join("%s has just said - %s" % (m, prompt_sfx_label(t))   # [num-leak]
''', 1),
    ("prompt-beat-transcript",
     '''            "%s has just said - %s" % (marker, text)
''',
     '''            "%s has just said - %s" % (marker, prompt_sfx_label(text))   # [num-leak]
''', 1),
    ("teach-beat-format",
     '''"the listed marker (A:, B:, C: or D:), once, at the start of the line. "''',
     '''"the listed marker (A:, B:, C: or D:), once, at the start of the line, with no number "
              "before it - a turn's number is the running order's, never a word to say. "''', 1),
    ("teach-chapter-format",
     '''"a colon, once - A: then the words, B: then the words - never two markers together. "''',
     '''"a colon, once - A: then the words, B: then the words - never two markers together, and "
                    "no number before the letter - a turn's number is the running order's, never a "
                    "word to say (no 'turn 2' in anybody's mouth). "''', 1),
]

S2 = [
    ("prompt-recap-dialogue",
     '''                                if row.get("aired") in ("box", "stream", "both") and float(row.get("air_at") or 0) >= hour_start][-30:]
''',
     '''                                if row.get("aired") in ("box", "stream", "both") and float(row.get("air_at") or 0) >= hour_start][-30:]
                    for _o in observed:   # [num-leak] a board clip is its words, never its library index
                        if _o.get("who") == "board" and callable(getattr(h, "prompt_sfx_label", None)):
                            _o["text"] = h.prompt_sfx_label(str(_o.get("text") or ""), True)
''', 1),
]

TARGETS = [("app.py", APP), ("system2_runtime.py", S2)]
MODULE = "bookkeeping_numbers.py"


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def read(path):
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" in raw)


def check_all(root):
    applied, total, missing = 0, 0, []
    if not (root / MODULE).is_file():
        missing.append("%s is not at the repo root (copy it first)" % MODULE)
    for name, edits in TARGETS:
        path = root / name
        if not path.is_file():
            missing.append("%s: no such file" % name)
            total += len(edits)
            continue
        text, _crlf = read(path)
        for ename, old, new, count in edits:
            total += 1
            st = state_of(text, old, new, count)
            if st == "applied":
                applied += 1
            elif st != "ready":
                missing.append("%s %s (%s)" % (name, ename, st))
    return applied, total, missing


def apply_all(root):
    applied, total, missing = check_all(root)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == total:
        return 2
    for name, edits in TARGETS:
        path = root / name
        text, crlf = read(path)
        before = text
        for ename, old, new, count in edits:
            if state_of(text, old, new, count) == "applied":
                continue
            assert text.count(old) == count, "%s %s: anchor found %d times" % (name, ename, text.count(old))
            text = text.replace(old, new)
        if text == before:
            continue
        assert "\r" not in text
        data = (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    return 0


def main(argv):
    root = Path(next((a for a in argv if not a.startswith("--")), "."))
    if "--apply" in argv:
        code = apply_all(root)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    applied, total, missing = check_all(root)
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
