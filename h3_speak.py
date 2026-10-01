"""[h3-speak] The hourly H3 video's spoken dialogue: whole sentences out of a
Speakerbox document, never the chat ring's titles.

"in the comfy ui H3 system, these are being added onto my prompts and they
dont make sense as sentences ... I need the people saying sentences that make
sense. Do a roulette RNG node for H3 output where speakerbox rolls the
documents and then rolls for sentences to take and then append to the prompt
dialogue section" (operator, 2026-09-29).

The hour's {conversation} was the last three rows of the station's chat ring:
board clip titles ("105 What is that man", "390 wider system of") and status
rows ("Song analysis complete: Ring System") glued end to end, and H3 made the
people on screen say it. This module is the pure half of the fix - no station
imports, so its tests stay fast: how a document is cut into sentences, which
sentences may be spoken, which runs of them fit a clip's seconds, and the last
gate a prompt passes before it is sent. The dice (which document, how many
sentences, which ones, the FORCED line) are System 3's and live in app.py.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

WORDS_PER_SECOND = 2.2        # app.H3_AD_WORDS_PER_SECOND: the pace h3_ad_duration_plan budgets
LEAD_S = 1.25                 # ...and its first/last beat
MIN_WORDS = 4                 # "Yeah." "No idea." are not a line for a stinger
MAX_WORDS = 24                # one sentence; a caption run with no stops is longer
COUNTS = (1, 2, 3)
# [speech-gates] the rules the operator switched off (speech_gates.py fills it);
# an unfilled {slot} is always refused - it would be read out as written
OFF: set[str] = set()

PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_STAMP = re.compile(r"^\s*[\[(]?\d{1,3}:\d{2}(?::\d{2})?[\])]?\s*")
_META = ("#", "**", "![", "|", "```", "---", "*", ">")
_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")
_END = re.compile(r"[.!?][\"'”’)]*$")
_URL = re.compile(r"https?://|\bwww\.|\.(?:com|org|net|io|tv|co\.uk)\b", re.I)
_FILE = re.compile(r"\b[\w-]+\.(?:mp4|mp3|wav|m4a|flac|ogg|aac|png|jpe?g|gif|webp|md|txt|json|py|js|html?|pdf|"
                   r"mov|mkv|avi|webm|srt|vtt|csv|safetensors|onnx|zip)\b", re.I)
_STATUS = re.compile(r"\b(?:analysis|render(?:ing)?|upload(?:ed)?|download(?:ed)?|scan(?:ning)?|harvest|"
                     r"transcription|transcribe|export|import|sync|index(?:ing)?|job)\s+"
                     r"(?:complete|completed|done|failed|finished|started|queued|ready|error)\b", re.I)
_LABEL = re.compile(r"^\s*(?:source|segments|status|error|warning|note|title|by|tags?|file|clip|track|"
                    r"playing|now playing|board|feed|audit|result)\s*:", re.I)
_SPEAKER = re.compile(r"^\s*[A-Z][A-Za-z .'-]{0,24}:\s")
_MARKUP = re.compile(r"[\[\]<>{}|*#_~^=\\/@]")
_CLIPNO = re.compile(r"\bclip[-_ ]?\d+\b", re.I)
# the pattern that went to air: a number, a few words, a number ("105 What is
# that man 390 wider system of") - two board rows' titles glued together
_TITLE_RUN = re.compile(r"\b\d{2,5}\s+[A-Za-z']+(?:\s+[A-Za-z']+){0,6}\s+\d{2,5}\b")
_ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|vs|etc|No|Vol|Ch|Pt|Fig|Inc|Ltd|Co)\.$")
_NON_ASCII = re.compile(r"[^\x00-\x7f‘’“”–—… ]")
_SMALL = {"a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "by", "with", "from",
          "is", "it", "as", "vs"}


def word_cap(seconds: Any, taken: int = 0) -> int:
    """How many words the clip's seconds hold at the station's pace, less the
    words already taken (the preset's own line) - the length that keeps the
    line to ONE render (h3_ad_duration_plan splits anything longer)."""
    try:
        s = float(seconds or 0)
    except (TypeError, ValueError):
        s = 0.0
    return max(0, int((s - LEAD_S) * WORDS_PER_SECOND) - max(0, int(taken or 0)))


def split_sentences(text: Any) -> list[str]:
    """A document as its sentences, in order. A heading, a metadata line
    (**Source:**, *11 documents, combined*), a table or code row and the
    transcript's own timestamps are not speech; the speech between two
    headings runs on as one stream, so a sentence a transcript split across
    two timestamped segments comes back whole."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        flat = " ".join(" ".join(run).split())
        run.clear()
        if flat:
            out.extend(p.strip() for p in _SPLIT.split(flat) if p.strip())

    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") and not line.startswith("### ["):
            flush()                     # a new source / section: a sentence never runs across it
            continue
        if line.startswith(_META):
            continue
        line = _STAMP.sub("", line)
        if line:
            run.append(line)
    flush()
    return out


def sentence_why(sentence: Any) -> str:
    """'' when `sentence` is one whole, speakable sentence; else why not."""
    s = " ".join(str(sentence or "").split())
    if not s:
        return "empty"
    if PLACEHOLDER.search(s) or "{" in s or "}" in s:
        return "an unfilled placeholder"
    if "url" not in OFF and _URL.search(s):
        return "a web address"
    if "file" not in OFF and _FILE.search(s):
        return "a file name"
    if "status" not in OFF and (_STATUS.search(s) or _LABEL.match(s)):
        return "a status line"
    if "speaker" not in OFF and _SPEAKER.match(s):
        return "a speaker label"
    if "titles" not in OFF and (_CLIPNO.search(s) or _TITLE_RUN.search(s)):
        return "titles glued together"
    if "markup" not in OFF and _MARKUP.search(s):
        return "markup or an annotation"
    if "nonascii" not in OFF and _NON_ASCII.search(s):
        return "not plain English text"
    words = s.split()
    if "fragment" not in OFF and len(words) < MIN_WORDS:
        return "a fragment (%d words)" % len(words)
    if "too_long" not in OFF and len(words) > MAX_WORDS:
        return "too long for one breath (%d words)" % len(words)
    if "no_end" not in OFF and not _END.search(s):
        return "no sentence end"
    if "abbrev" not in OFF and _ABBREV.search(s.rstrip("\"')”’")):
        return "cut at an abbreviation"
    first = next((c for c in s if c.isalpha()), "")
    if "mid_sentence" not in OFF and (not first or not first.isupper() or not (s[0].isalpha() or s[0] in "\"'“‘")):
        return "starts mid-sentence"
    alpha = [w for w in words if any(c.isalpha() for c in w)]
    if "numbers" not in OFF and len(alpha) < MIN_WORDS:
        return "numbers, not words"
    if "numbers" not in OFF and sum(1 for w in words if any(c.isdigit() for c in w)) * 4 > len(words):
        return "numbers, not words"
    rest = [w.strip("\"'.,!?;:()") for w in alpha[1:]]
    rest = [w for w in rest if w and w.lower() not in _SMALL and w not in ("I", "I'm", "I'll", "I've", "I'd")]
    if "title" not in OFF and len(rest) >= 3 and sum(1 for w in rest if w[:1].isupper()) * 10 >= len(rest) * 6:
        return "a title"
    low = [w.lower().strip("\"'.,!?;:") for w in words]
    if "stutter" not in OFF and any(low[i] == low[i + 1] == low[i + 2] for i in range(len(low) - 2)):
        return "a stutter"
    return ""


def speech_why(line: Any) -> str:
    """'' when every sentence of a spoken line is whole; else the first reason."""
    parts = split_sentences(line)
    if not parts:
        return "no line"
    for p in parts:
        why = sentence_why(p)
        if why:
            return "%s: %r" % (why, p[:80])
    return ""


def candidates(text: Any) -> list[tuple[int, str]]:
    """(position in the document, sentence) for every sentence that may be
    spoken. Cheap regex work only - the speakable normalizer runs on the few
    sentences the dice take."""
    return [(i, s) for i, s in enumerate(split_sentences(text)) if not sentence_why(s)]


def runs(cands: list[tuple[int, str]], count: int, cap: int) -> list[list[str]]:
    """Every run of `count` sentences that stand side by side in the document
    (so they belong together) and fit `cap` words between them."""
    out: list[list[str]] = []
    n = max(1, int(count))
    for i in range(0, len(cands) - n + 1):
        chunk = cands[i:i + n]
        if chunk[-1][0] - chunk[0][0] != n - 1:
            continue
        texts = [s for _, s in chunk]
        if sum(len(s.split()) for s in texts) <= cap:
            out.append(texts)
    return out


def air_items(rows: Iterable[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    """What people said on air, as the node's shelf: every line, and every
    MONOLOGUE - a run of consecutive heard rows by one speaker in one round
    (a long read the station split, a caller holding the floor) joined back
    into one text, so a sentence split across two rows comes back whole.
    `rows` are air-log rows oldest first; an item is kept only when at least
    one of its sentences passes and fits `cap` words."""
    items: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    def close() -> None:
        if cur is None:
            return
        text = " ".join(" ".join(cur["texts"]).split())
        cands = candidates(text)
        if cands and runs(cands, 1, cap):
            items.append({"ids": list(cur["ids"]), "who": cur["who"], "name": cur["name"], "sid": cur["sid"],
                          "kind": cur["kind"], "round": cur["round"], "at": cur["at"], "last_at": cur["last_at"],
                          "turns": len(cur["ids"]), "text": text[:2400], "cands": cands})

    for row in rows:
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        at = float(row.get("air_at") or row.get("ts") or 0)
        who, name, sid = str(row.get("who") or ""), str(row.get("name") or ""), str(row.get("sid") or "")
        same = (cur is not None and who == cur["who"] and name == cur["name"]
                and (sid == cur["sid"] if (sid or cur["sid"]) else at - cur["last_at"] <= 20.0))
        if same:
            cur["ids"].append(str(row.get("id") or ""))
            cur["texts"].append(text)
            cur["last_at"] = at
            continue
        close()
        cur = {"ids": [str(row.get("id") or "")], "texts": [text], "who": who, "name": name, "sid": sid,
               "kind": str(row.get("kind") or ""), "round": str(row.get("round") or ""), "at": at, "last_at": at}
    close()
    return items


def item_weight(item: dict[str, Any], lean: str, now: float = 0.0) -> float:
    """How hard an item is leaned on in the line roll. The feeling System 3
    rolled for the line (its ES intensity, 0-1) where the line has one, else
    how the words carry it (exclamations); a monologue by its length; this
    hour's talk over older talk."""
    text = str(item.get("text") or "")
    if item.get("emotion"):
        try:
            feel = max(0.0, min(1.0, float(item.get("intensity") or 0.0)))
        except (TypeError, ValueError):
            feel = 0.0
    else:
        feel = min(0.6, 0.15 * text.count("!"))
    if lean == "an emotional line":
        w = 0.1 + 2.0 * feel
    elif lean == "a monologue":
        w = (0.25 + feel) * min(4, max(1, int(item.get("turns") or 1)))
    else:
        w = 0.25 + feel
    if now and float(item.get("last_at") or item.get("at") or 0) >= now - 3600.0:
        w *= 1.5
    return round(w, 4)


def fragment_why(text: Any) -> str:
    """'' unless `text` carries what the old assembly glued in: an unfilled
    placeholder, a status row, a file name, a clip number or two titles run
    together."""
    s = " ".join(str(text or "").split())
    m = PLACEHOLDER.search(s)
    if m:
        return "an unfilled placeholder %s" % m.group(0)
    for rx, why in ((_STATUS, "a status line"), (_FILE, "a file name"), (_CLIPNO, "a clip number"),
                    (_TITLE_RUN, "titles glued together")):
        m = rx.search(s)
        if m:
            return "%s (%r)" % (why, m.group(0)[:60])
    return ""


def gate(prompt: Any, speech: Any = "", conversation: Any = None, strict: bool = False) -> str:
    """THE LAST GATE before a prompt is sent to ComfyUI. '' to send; else why
    it is refused. Every prompt: no unfilled {placeholder}, no status row.
    `strict` (the hourly road, whose words System 3 rolled): the spoken line is
    whole sentences and the conversation slot carries none of the old
    fragments."""
    p = str(prompt or "")
    m = PLACEHOLDER.search(p)
    if m:
        return "the prompt still holds %s" % m.group(0)
    m = _STATUS.search(p)
    if m:
        return "the prompt carries a status line (%r)" % m.group(0)
    if not strict:
        return ""
    why = speech_why(speech) if str(speech or "").strip() else "no spoken line"
    if why:
        return "the spoken line is not whole sentences - " + why
    if conversation is not None:
        why = fragment_why(conversation)
        if why:
            return "the conversation slot carries " + why
    return ""


def clean_placeholders(text: Any) -> tuple[str, list[str]]:
    """The text with every {placeholder} no road filled taken out (spaces
    tidied line by line, line breaks kept), and which ones they were."""
    s = str(text or "")
    left = sorted(set(PLACEHOLDER.findall(s)))
    if not left:
        return s, []
    s = PLACEHOLDER.sub("", s)
    s = "\n".join(re.sub(r"[ \t]{2,}", " ", ln).replace(" .", ".").replace(" ,", ",").strip()
                  for ln in s.split("\n"))
    return s.strip(), left


def first_upper(text: Any) -> str:
    t = " ".join(str(text or "").split())
    return t[:1].upper() + t[1:] if t else ""


def normalize_all(texts: Iterable[str], normalize: Callable[[str], str] | None) -> list[str]:
    out = []
    for t in texts:
        n = normalize(t) if normalize else t
        out.append(first_upper(n))
    return out
