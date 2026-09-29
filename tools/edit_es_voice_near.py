"""[es-near] es_voice.py gains the words the engine reads (emotion engine step 4)
and the reference a take was made with (step 2b).

  * unmark(text): the writer's forgiving micro-grammar resolved - [emph]word[/emph]
    becomes the word in CAPS (the written form of emphasis), [beat] an em-dash -
    and markup that is never speech dropped: an *action* in asterisks or
    parentheses (*laughs*, (sighs)) goes whole instead of being read out as a
    word, a *word* in asterisks is emphasis (CAPS), [..] {..} <tag> go. Text with
    no markup comes back as it was, byte for byte.
  * speakable(text, engine, flatten): what one engine is handed. XTTS keeps at
    most three CAPS words as emphasis (the longest; acronyms never count) and
    never sees an ellipsis or an em-dash (the station's _xtts_sanitize is the
    flattener, as today), and a sentence longer than 220 characters is cut at a
    clause break (the XTTS tokenizer truncates past 250). F5 NEVER sees a CAPS
    word (it spells them letter by letter - its own README) except a real
    acronym, which it should spell. Any other engine: markup only.
  * baked_ref(stamp): which reference file baked a take (clip["es"]["ref"] or
    ["native"]["ref"]), None when the stamp predates the record.

numpy-free, stdlib re only. Every function returns its input untouched on any
failure. Marker-idempotent: --check exits 0 ready / 2 already applied / 1 the
file is not the one this was cut against; --apply appends the region, LF only,
atomically.

    python3 tools/edit_es_voice_near.py [--apply] [es_voice.py]
"""
import os
import sys
import tempfile
from pathlib import Path

MARKER = "# --- [es-near] THE WORDS THE ENGINE READS"
TAIL = "def hold_crest(raw, crest_in, tol=0.2):"

REGION = r'''
# --- [es-near] THE WORDS THE ENGINE READS (emotion engine step 4) -----------------
#
# Neither clone engine has a tag vocabulary: a bracketed direction is read aloud
# as words. XTTS loops on ellipses and em-dashes inside its sentence splitter,
# truncates a sentence past 250 characters, and hears one to three CAPS words as
# emphasis; F5 spells a CAPS word letter by letter (its own README) and takes its
# pauses from commas and spaces. The writer may emit a forgiving micro-grammar -
# [emph]word[/emph] and [beat] - resolved here; unmarked text is untouched.

import re as _re

CAPS_EMPHASIS_MAX = 3                    # XTTS: this many CAPS words stay emphasis
XTTS_SENTENCE_MAX = 220                  # XTTS: a longer sentence is cut at a clause
# Real acronyms are spelled by both engines, and should be: never emphasis, never lowered.
ACRONYMS = frozenset((
    "DJ DJS FM AM TV UK USA EU UN NASA FBI CIA NFL NBA NHL MLB BBC CNN NPR CEO CEOS AI "
    "OK UFO UFOS DNA VIP VIPS ASAP LOL OMG GPS ATM SUV RV NYC HQ IQ DMV CD CDS DVD USB "
    "PDF URL RSVP FAQ ETA").split())

_ACTION = _re.compile(
    r"^(?:(?:he|she|they|i|we|you|[a-z]+ly|long|short|dramatic|awkward|little|small|big|"
    r"nervous|quiet|soft|brief|another|a)\s+){0,2}"
    r"(?:laugh\w*|chuckl\w*|giggl\w*|snicker\w*|cackl\w*|sigh\w*|gasp\w*|groan\w*|grunt\w*|"
    r"sniff\w*|sob|sobs|sobbing|cough\w*|clear\w*\s+(?:\w+\s+)?throat|paus\w*|beat|"
    r"grin\w*|smil\w*|smirk\w*|shrug\w*|wink\w*|nod|nods|nodding|whisper\w*|shout\w*|"
    r"yell\w*|mutter\w*|mumbl\w*|scoff\w*|snort\w*|cry|cries|crying|inhal\w*|exhal\w*|"
    r"breath|breathe|breathes|breathing|clap|claps|clapping|hum|hums|humming|sing|sings|"
    r"singing|stammer\w*|gulp\w*|winc\w*|eye[\s-]?roll\w*|rolls?\s+(?:\w+\s+)?eyes|"
    r"sarcastic\w*|deadpan|softly|quietly|loudly|excitedly|nervously|angrily|sadly|"
    r"happily|dramatically|mocking\w*)"
    r"(?:\W.*)?$", _re.I | _re.S)
_EMPH = _re.compile(r"\[(?:emph|emphasis|stress)\]\s*([^\[\]]{1,60}?)\s*\[/(?:emph|emphasis|stress)\]", _re.I)
_BEAT = _re.compile(r"\s*\[(?:beat|pause)\]\s*", _re.I)
_STARRED = _re.compile(r"(?<![\w*])(\*{1,2}|_{1,2})(?=\S)([^*_\n]{1,60}?)(?<=\S)\1(?![\w*])")
_BRACKETED = _re.compile(r"\[[^\[\]\n]{0,80}\]|\{[^{}\n]{0,80}\}|</?[A-Za-z][^<>\n]{0,60}>")
_PAREN = _re.compile(r"\(([^()\n]{1,60})\)")
_CAPSWORD = _re.compile(r"\b[A-Z][A-Z']*[A-Z]\b")


def _is_action(words):
    w = " ".join(str(words or "").split())
    return bool(w) and len(w.split()) <= 6 and bool(_ACTION.match(w))


def _caps(phrase):
    """A marked phrase as emphasis: its words of three letters or more in CAPS
    (one to CAPS_EMPHASIS_MAX words; a longer phrase stays as written)."""
    words = str(phrase or "").split()
    if not words or len(words) > CAPS_EMPHASIS_MAX:
        return " ".join(words)
    return " ".join(w.upper() if sum(c.isalpha() for c in w) >= 3 else w for w in words)


def unmark(text):
    """The written line with its markup resolved (see the module notes above);
    the line itself when it carries none."""
    raw = str(text or "")
    try:
        if not any(c in raw for c in "[*_{<"):
            return raw
        t = _EMPH.sub(lambda m: _caps(m.group(1)), raw)
        beat = [False]

        def _beat(_m):
            beat[0] = True
            return " — "
        t = _BEAT.sub(_beat, t)

        def _star(m):
            inner = m.group(2).strip()
            if _is_action(inner):
                return " "
            return _caps(inner) if len(inner.split()) == 1 else inner
        t = _STARRED.sub(_star, t)
        t = _BRACKETED.sub(" ", t)
        if t == raw:
            return raw
        if beat[0]:                                   # a beat at either end is no beat
            t = _re.sub(r"^[\s—]+|[\s—]+$", "", t)
        t = _re.sub(r"[ \t]{2,}", " ", t)
        t = _re.sub(r" +([,.;:!?])", r"\1", t)
        return t.strip()
    except Exception:  # noqa: BLE001
        return raw


def _sentence_start(text, at):
    i = at - 1
    while i >= 0 and text[i] in " \t\n\"'“‘(":
        i -= 1
    return i < 0 or text[i] in ".!?"


def _decap(word, first):
    w = word.lower()
    if w == "i" or w.startswith("i'"):
        w = "I" + w[1:]
    return w[:1].upper() + w[1:] if first else w


def caps_for(text, engine):
    """CAPS words as `engine` should see them: XTTS keeps the CAPS_EMPHASIS_MAX
    longest of three letters or more (the rest lowered); F5 keeps none; an
    acronym is never touched; any other engine gets the text as it is."""
    t = str(text or "")
    try:
        if engine not in ("xtts", "f5"):
            return t
        hits = [m for m in _CAPSWORD.finditer(t) if m.group(0).replace("'", "") not in ACRONYMS]
        if not hits:
            return t
        keep = set()
        if engine == "xtts":
            emph = [m for m in hits if sum(c.isalpha() for c in m.group(0)) >= 3]
            keep = {m.start() for m in sorted(emph, key=lambda m: (-len(m.group(0)), m.start()))[:CAPS_EMPHASIS_MAX]}
        out, pos = [], 0
        for m in hits:
            if m.start() in keep:
                continue
            out.append(t[pos:m.start()])
            out.append(_decap(m.group(0), _sentence_start(t, m.start())))
            pos = m.end()
        out.append(t[pos:])
        return "".join(out)
    except Exception:  # noqa: BLE001
        return t


def presplit(text, cap=XTTS_SENTENCE_MAX, floor=60):
    """Every sentence longer than `cap` characters cut into sentences at its last
    clause break (", " "; " ": ") before the cap and past `floor`; a sentence with
    no such break is left for the engine's own splitter."""
    t = str(text or "")
    try:
        if len(t) <= cap:
            return t
        out = []
        for s in _re.split(r"(?<=[.!?])\s+", t):
            while len(s) > cap:
                cut = max(s.rfind(", ", 0, cap), s.rfind("; ", 0, cap), s.rfind(": ", 0, cap))
                if cut < floor:
                    break
                out.append(s[:cut].rstrip(",;: ") + ".")
                s = s[cut + 2:].lstrip()
                s = s[:1].upper() + s[1:]
            if s:
                out.append(s)
        return " ".join(out)
    except Exception:  # noqa: BLE001
        return t


def speakable(text, engine, flatten=None):
    """The words `engine` is handed for a line: markup resolved (unmark), action
    parentheses dropped, CAPS as the engine should see them (caps_for), then the
    station's flattener (`flatten`, its _xtts_sanitize: plain ASCII, no ellipsis
    or em-dash) and, for XTTS, sentences cut to XTTS_SENTENCE_MAX. On any failure:
    the flattener on the line as written, which is what it was."""
    raw = str(text or "")
    try:
        t = unmark(raw)
        t = _PAREN.sub(lambda m: " " if _is_action(m.group(1)) else m.group(0), t)
        t = caps_for(t, engine)
        if flatten is not None:
            t = flatten(t)
            t = _re.sub(r"\s+([,.;:!?])", r"\1", t)    # "Well , I" (a flattened dash) reads "Well, I"
        if engine == "xtts":
            t = presplit(t)
        return t
    except Exception:  # noqa: BLE001
        return flatten(raw) if flatten is not None else raw


# --- [es-near] which reference baked a take (emotion engine step 2b) ----------------

def baked_ref(stamp):
    """The reference file (its stem: "reference", "reference_f5", later
    "reference_<family>") a take's ES stamp says it was made with, from `ref` or
    `native.ref`; None when the take predates the record (a match for anything)."""
    if not isinstance(stamp, dict):
        return None
    got = stamp.get("ref")
    if got is None and isinstance(stamp.get("native"), dict):
        got = stamp["native"].get("ref")
    return None if got is None else str(got)
'''


def main(argv):
    do_apply = "--apply" in argv
    target = Path(next((a for a in argv if not a.startswith("--")), "es_voice.py"))
    text = target.read_bytes().decode("utf-8")
    if "\r" in text:
        print("es_voice.py is expected LF-only")
        return 1
    if MARKER in text:
        print("already applied")
        return 2
    if TAIL not in text or "def crest_db(raw):" not in text:
        print("missing: hold_crest / crest_db (the wave C es_voice.py this was cut against)")
        return 1
    if not do_apply:
        print("ready")
        return 0
    out = text.rstrip("\n") + "\n\n" + REGION.strip("\n") + "\n"
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    os.replace(tmp, target)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
