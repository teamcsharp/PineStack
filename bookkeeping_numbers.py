"""[num-leak] A BOOKKEEPING NUMBER IS NOT A WORD.

2026-09-29, the operator: "why are these people speaking numbers in their messages".
Measured over 12 h of air (1,444 voiced rows): six lines said a number nobody meant.

- ROW NUMBERS. The running order lists its turns "4  B  - ..."; the writer kept the
  numbers ("4 B: ...\\n5 A: ..."), ask_model folded the newlines, and the split left
  each row's number on the END of the turn before it: "...just plain wrong 5",
  "...at all 6", "...you idiot 7", "Shrug it off 3" - all aired. [s3-rownum] cut a
  number after a finished sentence or on a line of its own; these had neither.
  row_numbers_cut() takes them at the parse, where they still sit in front of a
  speaker marker: always at the start of a line, and inline when they run in order.
- TURN REFERENCES. The rows say "Return to your point in turn 2": "the actual point
  I made in turn two" aired.
- CLIP LABELS. A board clip is labelled by its library index ("🔊 26 clip-40",
  "🔊 25 dental plan in"). The SFX guy was asked for a verdict "about" the last row,
  which was the board's; he said "26 clip-40." and a five-line chapter answered it.
  sfx_label_for_prompt() is what a writer may be told about a clip: its words, never
  its index or file name.

spoken_gate() is the narrow last gate at the one door every spoken line passes
(app.spoken_text): it rewrites what is certainly bookkeeping and says what it did.
A number the scene holds ("63 degrees", "$6,000", "six to seven minutes", "call 911",
"Ocean's 11", "gate 7 is open") is never touched.

Pure functions, no station state: app.py and system2_runtime.py call in.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

SFX_GLYPH = "\U0001F50A"
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten", "eleven", "twelve")
_NUMWORD = "(?:%s)" % "|".join(NUMBER_WORDS)

# A speaker marker as banter_turns reads one (a slash may stand before it; "A:3" is a time).
_MARK = r"[/\\|]*[ABCDE][ \t]*:(?!\d)"
# A row number standing in front of a marker: at the start, after a new line, or inline.
_ROW_BEFORE_MARK = re.compile(r"(^|\n|[ \t]+)[ \t]*(\d{1,3})[.)]?[ \t]+(?=" + _MARK + ")")

# [s3-rownum]'s own rule, kept: a bare 1-2 digit number after the last finished sentence.
_TAIL_AFTER_SENTENCE = re.compile(r"(?<=[.!?…\"”'’)\]])\s+(\d{1,2})\s*$")
# "in turn two", "from turn 4", "back in turn 3" - the running order's numbering said aloud.
_TURN_REF = re.compile(r"\b(?:back\s+)?(?:in|from|at|since)\s+turn\s+(?:\d{1,2}|%s)\b" % _NUMWORD, re.I)
# "Turn 1 is ..." - a turn numbered in digits is never how a person says it.
_TURN_DIGIT = re.compile(r"\bturns?\s+\d{1,2}\b", re.I)
# A library clip label with no words of its own: "26 clip-40" / "577 clip-2" anywhere,
# "731 clip" only where the sentence stops ("a 30 clip magazine" is a magazine).
_CLIP_LABEL = re.compile(r"(?:%s\s*)?\b\d{1,6}\s+clip(?:-\d{1,4}\b|(?=\s*(?:[.!?,;:\"”]|$)))\.?"
                         % SFX_GLYPH, re.I)
# A board label's words must be this distinctive before its index is cut from a line
# ("🔊 7 sensors" must never take the 7 out of "the hottest of 7 sensors").
LABEL_MIN_WORDS, LABEL_MIN_CHARS = 2, 8
_MEDIA_EXT = re.compile(r"\.(?:mp4|mp3|wav|ogg|m4a|webm|flac)\b", re.I)
_BOARD_PREFIX = re.compile(r"^\s*board\s*:\s*", re.I)


# --- the parse ---------------------------------------------------------------------

def row_numbers_cut(script: Any) -> tuple[str, list[int]]:
    """`script` without the running order's row numbers in front of its speaker
    markers, and the numbers cut. A number that opens a line before a marker is a
    row label (no dialogue starts before its own marker); one inline ("...wrong 5 A:")
    is cut when it runs in order with a neighbour (4, 5, 6 ...). A lone inline number
    ("I'll take 2 B: ...") is left: it could be the sentence's own."""
    s = str(script or "")
    found = list(_ROW_BEFORE_MARK.finditer(s))
    if not found:
        return s, []
    nums = [int(m.group(2)) for m in found]
    cut: list[int] = []
    for i, m in enumerate(found):
        opens_line = m.group(1) in ("", "\n")
        in_order = ((i > 0 and nums[i - 1] + 1 == nums[i])
                    or (i + 1 < len(found) and nums[i + 1] == nums[i] + 1))
        if opens_line or in_order:
            cut.append(i)
    if not cut:
        return s, []
    out, last = [], 0
    for i in cut:
        m = found[i]
        out.append(s[last:m.start()])
        out.append(m.group(1))            # the whitespace before the number stays
        last = m.end()
    out.append(s[last:])
    return "".join(out), [nums[i] for i in cut]


# --- what a writer may be told about a board clip ------------------------------------

def is_sfx_label(text: Any) -> bool:
    """A board row's words ("🔊 29 I don't know", "board: 🔊 26 clip-40")."""
    s = _BOARD_PREFIX.sub("", str(text or ""))
    return s.lstrip().startswith(SFX_GLYPH)


def sfx_label_words(text: Any) -> str:
    """The words of a clip label without its library index, glyph or file type:
    "🔊 25 dental plan in" -> "dental plan in"; "🔊 26 clip-40" -> ""."""
    s = _BOARD_PREFIX.sub("", str(text or "")).replace(SFX_GLYPH, " ")
    s = _MEDIA_EXT.sub("", s)
    s = re.sub(r"^\s*\d{1,6}\b[ \t]*", "", s)
    s = re.sub(r"^\s*clip(?:-\d{1,4})?\b\.?\s*$", "", s, flags=re.I)
    return " ".join(s.split()).strip(" .-_")


def sfx_label_for_prompt(text: Any, board: bool = False) -> str:
    """A clip as a writer may hear of it: its words, never its index or file name.
    Any other text comes back as it is. `board`: the text is known to be a clip's
    label even without the glyph (a file stem such as "26 clip-40")."""
    s = str(text or "")
    if not (board or is_sfx_label(s)):
        return s
    words = sfx_label_words(s)
    return ('a sound clip from the board ("%s")' % words) if words else "a sound clip from the board"


def last_said(spoken: Iterable[Any]) -> str:
    """The last thing a PERSON said in a round's "who: text" list - a board clip's
    label is not a thing anybody said. "" when nobody spoke."""
    for item in reversed(list(spoken or [])):
        s = str(item or "")
        who, sep, words = s.partition(":")
        if sep and who.strip().lower() in ("board", "sfx"):
            continue
        if is_sfx_label(words if sep else s) or is_sfx_label(s):
            continue
        if s.strip():
            return s
    return ""


# --- the last gate -------------------------------------------------------------------

def _tidy(s: str) -> str:
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;:])(?=[,.;:!?])", "", s)
    s = s.strip()
    return "" if not re.search(r"[^\W_]", s) else s


def spoken_gate(text: Any, board_labels: Iterable[Any] = ()) -> tuple[str, list[str]]:
    """`text` as it may be said, and what was cut (empty when nothing was).
    Narrow: a row number after the last sentence, a clip label, a board clip's index
    in front of its own words, and the running order's turn numbering."""
    before = str(text or "")
    s = before
    hits: list[str] = []
    if re.search(r"\d", s):
        m = _TAIL_AFTER_SENTENCE.search(s)
        if m:
            hits.append("row number %s after the last sentence" % m.group(1))
            s = s[:m.start()]
        for label in board_labels or ():
            words = sfx_label_words(label)
            idx = re.match(r"\s*(?:board\s*:\s*)?%s?\s*(\d{1,6})\b" % SFX_GLYPH, str(label or ""))
            if not (idx and len(words.split()) >= LABEL_MIN_WORDS and len(words) >= LABEL_MIN_CHARS):
                continue
            rx = re.compile(r"(?:%s\s*)?\b%s\s+(?=%s)" % (SFX_GLYPH, idx.group(1), re.escape(words)), re.I)
            if rx.search(s):
                hits.append("clip index %s in front of %r" % (idx.group(1), words[:40]))
                s = rx.sub("", s)
        for m in list(_CLIP_LABEL.finditer(s)):
            hits.append("clip label %r" % m.group(0).strip())
        s = _CLIP_LABEL.sub(" ", s)
    if re.search(r"turn", s, re.I):
        for m in list(_TURN_REF.finditer(s)):
            hits.append("turn number %r" % m.group(0))
        s = _TURN_REF.sub("earlier", s)
        for m in list(_TURN_DIGIT.finditer(s)):
            hits.append("turn number %r" % m.group(0))
        s = _TURN_DIGIT.sub("earlier", s)
    if not hits:
        return before, []
    return _tidy(s), hits
