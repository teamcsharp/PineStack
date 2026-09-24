"""caller_topic - the caller's subject as the SPINE of a phone call, and the
storyline as DIRECTION rather than dialogue (#1240 / #1249).

Repo path: caller_topic.py (top level, beside crystal_contract.py).

Pure functions - no station imports - so tests/test_caller_topic.py runs
without app.py, and app.py imports the pieces it needs:

    plot_act_direction    strip a typed act label ("Act 3: ...") off a direction
    plot_label_scrub      strip act labels out of a SPOKEN line ("...-Act 3; tonight")
    topic_subject         the raw call topic as a clean subject (legacy wrappers off)
    topic_nouns           the subject's content words, in order
    topic_noun_phrases    the subject's determiner phrases ("devastating log")
    second_person         "my toilet" -> "your toilet", for a host restating it
    topic_adherence       the grade: which host turns address the subject
    topic_words_dropped   which subject words a tint dropped from a line
    topic_contract_clause the prompt paragraph that makes the subject the spine
    fallback_call_script  the emergency skeleton, now about the subject

Measured before this (2026-09-21, air_log + prep_shelf): 66 of 74 aired
caller rounds since 09-19 and 38 of the last 40 shelf rows were the
emergency skeleton, whose host turns were about its own furniture ("the
loose labels") while the subject was pasted raw into two lines - with the
operator's "Act 3:" label and the prompt's "what is going on out there
right now -" prefix still on it.
"""
from __future__ import annotations

import hashlib
import re

__all__ = [
    "plot_act_direction", "plot_label_scrub", "topic_subject", "topic_nouns",
    "topic_noun_phrases", "second_person", "topic_adherence",
    "topic_words_dropped", "topic_contract_clause", "fallback_call_script",
    "SKELETON_TELL",
]

# --- act labels ---------------------------------------------------------------
_NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
              "first|second|third|fourth|fifth|sixth|final|last")
_NUM = r"(?:\d{1,2}|[ivx]{1,4}|" + _NUM_WORDS + r")"
_LABEL = r"(?:act|scene|chapter|stage|beat|episode|part)"

# A typed label at the HEAD of a direction: "Act 3: ...", "ACT II - ...",
# "Scene 2. ...", "(Act 3) ...", "Act three - ...". A number or a colon-like
# mark must follow the word, so "Part of the town..." is left alone.
_LEAD_LABEL = re.compile(
    r"^\s*[\(\[]?\s*" + _LABEL + r"\s*(?:" + _NUM +
    r"\s*(?:of\s*\d+)?\s*[\)\]]?\s*[:.\-–—]*|[:\-–—])\s*",
    re.I)

# The same label INSIDE a spoken line. An optional preposition/determiner in
# front ("in Act one", "this state of play-Act 3"), an optional "of N" / "of
# the show" behind, and a trailing colon or dash consumed so "Act 2 - the
# police" reads "the police".
_INLINE_LABEL = re.compile(
    r"(?:\b(?:in|into|during|at|by|of|for|this|that|the|our|your|tonight's)\s+)?"
    r"[\-–—]?\s*\b(?:act|scene|chapter)\s*" + _NUM +
    r"\b(?:\s+of\s+(?:\d+|the\s+(?:show|story|night|play|piece|evening)))?"
    r"\s*[:\-–—]?\s*",
    re.I)

# The wrappers the old plotline_call_want() put round the act text, and
# which the skeleton pasted into two spoken turns.
_LEGACY_WANT = re.compile(r"^\s*what is going on out there right now\s*[-–—:]\s*", re.I)
_LEGACY_TAIL = re.compile(r"\s*\(\s*act\s+\d+\s+of\s+\d+\s+of\s+\"[^\"]*\"?\s*\)?\s*$", re.I)


def _tidy(text: str) -> str:
    out = " ".join(str(text or "").split())
    out = re.sub(r"\s+([,;:.!?])", r"\1", out)          # "play ;" -> "play;"
    out = re.sub(r"([,;:])\s*(?=[,;:.!?])", "", out)      # ",;" -> ";"
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)             # "()" left behind
    out = re.sub(r"^\s*[,;:\-–—]+\s*", "", out)  # a dangling lead mark
    out = re.sub(r"\s+([,;:.!?])", r"\1", out)
    return " ".join(out.split()).strip()


def plot_act_direction(act) -> str:
    """The act as DIRECTION: the operator's own label taken off the front.

    "Act 3: the whole world collapses into handpanners." ->
    "the whole world collapses into handpanners."
    """
    text = " ".join(str(act or "").split())
    for _ in range(2):                          # "Act 3: Scene 1: ..."
        new = _LEAD_LABEL.sub("", text, count=1)
        if new == text:
            break
        text = new
    return text.strip()


def plot_label_scrub(text) -> str:
    """Take act labels out of a SPOKEN line, tidying the seam.

    "What made you call about this state of play-Act 3; tonight the whole
    world collapses" -> "What made you call about this state of play;
    tonight the whole world collapses".  Never touches the speaker markers
    ("A: ", "C: "): the label needs the WORD act/scene/chapter.
    """
    raw = str(text or "")
    if not raw or not re.search(r"\b(?:act|scene|chapter)\b", raw, re.I):
        return raw
    lines = raw.split("\n")
    out = []
    for line in lines:
        if not re.search(r"\b(?:act|scene|chapter)\b", line, re.I):
            out.append(line)
            continue
        made = _LEGACY_TAIL.sub("", line)
        made = _INLINE_LABEL.sub(" ", made)
        made = _tidy(made)
        # A marker that lost its text ("B: ") is left as it was, not empty.
        if re.fullmatch(r"\s*[A-E]\s*:\s*", made or "") or not made.strip():
            out.append(line)
        else:
            out.append(made)
    return "\n".join(out)


def topic_subject(topic, cap: int = 240) -> str:
    """The raw call topic as a clean subject: legacy wrappers and act labels
    off, whitespace folded, capped."""
    text = " ".join(str(topic or "").split())
    text = _LEGACY_WANT.sub("", text)
    text = _LEGACY_TAIL.sub("", text)
    text = plot_act_direction(text)
    text = plot_label_scrub(text)
    text = text.strip().strip("\"'")
    return text[:cap].strip()


# --- words ---------------------------------------------------------------------
_STOP = frozenset("""
a an the and or but nor so yet if then than that this these those there here
it its it's he she they them their theirs him his her hers we us our ours you
your yours i me my mine myself yourself himself herself itself who whom whose
what which when where why how is am are was were be been being have has had
having do does did doing done will would shall should can could may might must
not no nor never none nothing just only very really quite rather too also even
still yet again ever always often sometimes about above after again against
all any both each few more most other some such own same into onto out over
under up down off on in at to for of with from by as until while before during
through between because although though unless whether either neither around
across along toward towards without within upon like unlike get got gets
getting gonna going go goes went gone come comes came coming make makes made
making take takes took taking say says said saying know knows knew known think
thinks thought want wants wanted need needs needed let lets see sees saw seen
look looks looked put puts thing things something someone somebody anything
anyone everything everyone nobody everybody one ones two three okay ok oh hey
hi hello yes yeah yep nope wow well right now tonight today yesterday tomorrow
back way ways lot lots kind sort bit much many little big new old good bad
""".split())

_LIGHT_TRIM = frozenset("""
is was are were be been being and or but that which who whom when where in on
at to for of with by from into out up down over under as than then so if
broke broken used left had has have did does do gets got get went goes go
comes came come is isn't wasn't aren't
""".split())


def _stem(word: str) -> str:
    w = str(word or "").lower().strip("'")
    if w.endswith("'s"):
        w = w[:-2]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("es") and not w.endswith(("ses", "xes", "zes", "ches", "shes")):
        w = w[:-1]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


def _words(text) -> list:
    return re.findall(r"[a-z][a-z']*", str(text or "").lower())


def topic_nouns(topic, most: int = 16) -> list:
    """The subject's content words, in order, deduplicated by stem."""
    seen = set()
    out = []
    for w in _words(topic_subject(topic, cap=600) if topic else ""):
        w = w.strip("'")
        if len(w) < 3 or w in _STOP:
            continue
        s = _stem(w)
        if s in seen:
            continue
        seen.add(s)
        out.append(w)
        if len(out) >= most:
            break
    return out


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)):
        return True
    return False


def _mentions(said, stems) -> bool:
    for w in _words(said):
        s = _stem(w)
        if any(_same(s, t) for t in stems):
            return True
    return False


_DET_PHRASE = re.compile(
    r"\b(?:the|a|an|my|your|his|her|their|our|this|that|some|every)\s+"
    r"((?:[a-z][a-z'\-]*\s+){0,1}[a-z][a-z'\-]*)", re.I)


def topic_noun_phrases(topic, most: int = 6) -> list:
    """Determiner phrases out of the subject - the things a host can name:
    "A man broke in and used my toilet. He left a devastating log." ->
    ["man", "toilet", "devastating log"]."""
    subject = topic_subject(topic, cap=600)
    out = []
    seen = set()
    for m in _DET_PHRASE.finditer(subject):
        words = [w for w in m.group(1).lower().split() if w]
        kept = []
        for w in words:
            if w in _LIGHT_TRIM or w in _STOP or len(w) < 3:
                break
            kept.append(w)
        if not kept:
            continue
        phrase = " ".join(kept)
        key = _stem(kept[-1])
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= most:
            break
    if not out:
        out = topic_nouns(subject)[:3]
    return out


_FIRST_PERSON = re.compile(r"\b(am i|i am|i'm|i've|i'd|i'll|i was|my|mine|myself|me|i)\b", re.I)
_FLIP = {"am i": "are you", "i am": "you are", "i'm": "you're", "i've": "you've",
         "i'd": "you'd", "i'll": "you'll", "i was": "you were", "my": "your",
         "mine": "yours", "myself": "yourself", "me": "you", "i": "you"}


def second_person(text) -> str:
    """"A man broke in and used my toilet" -> "A man broke in and used your
    toilet": the caller's subject as a HOST says it back to them."""
    def flip(m):
        got = m.group(1)
        new = _FLIP.get(got.lower(), got)
        if got[:1].isupper():
            new = new[:1].upper() + new[1:]
        return new
    return _FIRST_PERSON.sub(flip, str(text or ""))


def _is_first_person(text) -> bool:
    return bool(re.search(r"\b(i|i'm|i've|i'd|i'll|my|me|mine|myself)\b", str(text or ""), re.I))


def _first_sentence(text) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    return (parts[0] if parts else "").strip()


def _lower_lead(text) -> str:
    """"A man broke in" -> "a man broke in", so a host can say "So a man
    broke in...". A word in capitals (an acronym) is left alone."""
    t = str(text or "")
    if len(t) > 1 and t[0].isupper() and (t[1] == " " or t[1].islower()):
        return t[0].lower() + t[1:]
    return t


# --- the grade --------------------------------------------------------------------
HOST_MARKERS = ("A", "B", "D")
CALLER_MARKERS = ("C", "E")


def topic_adherence(turns, topic, hosts=HOST_MARKERS, callers=CALLER_MARKERS) -> dict:
    """Which host turns address what the caller rang about.

    Counted over the host turns AFTER the caller first STATES the subject
    (or after their first turn when they never do), the sign-off excluded:
    answering the phone, greeting the caller and saying goodbye are
    protocol, not conversation. A turn addresses the subject when it
    carries one of the subject's content words, by stem. Cheap - no model -
    and it names the turns that wandered, so a regeneration can be told
    exactly what to fix.
    """
    turns = [(str(m or "").upper(), str(t or "")) for m, t in (turns or [])]
    nouns = topic_nouns(topic)
    stems = [_stem(n) for n in nouns]
    out = {"checked": bool(stems), "ok": True, "nouns": nouns[:12], "score": 1.0,
           "host_turns": 0, "addressing": 0, "caller_states": True,
           "faults": [], "wandering": []}
    if not stems:
        return out
    first_caller = next((i for i, (m, _t) in enumerate(turns) if m in callers), -1)
    stated_at = next((i for i, (m, t) in enumerate(turns)
                      if m in callers and _mentions(t, stems)), -1)
    start = stated_at if stated_at >= 0 else first_caller
    host_after = [(i, t) for i, (m, t) in enumerate(turns)
                  if m in hosts and i > start]
    if host_after and host_after[-1][0] == len(turns) - 1 and len(host_after) > 1:
        host_after = host_after[:-1]                    # the sign-off
    addressing = [i for i, t in host_after if _mentions(t, stems)]
    caller_states = stated_at >= 0
    n, k = len(host_after), len(addressing)
    score = (k / n) if n else 0.0
    need = 1 if n <= 2 else 2
    ok = bool(caller_states and n > 0 and k >= need and score >= 0.5)
    faults = []
    if not caller_states:
        faults.append("the caller never states what they rang about (%s)"
                      % ", ".join(nouns[:5]))
    if n and k < need:
        faults.append("the hosts never address the caller's subject (%s) - "
                      "%d of %d host turns" % (", ".join(nouns[:5]), k, n))
    elif n and score < 0.5:
        faults.append("only %d of %d host turns address the caller's subject (%s)"
                      % (k, n, ", ".join(nouns[:5])))
    out.update({"ok": ok, "score": round(score, 2), "host_turns": n, "addressing": k,
                "caller_states": caller_states, "faults": faults,
                "wandering": [i for i, _t in host_after if i not in addressing][:12]})
    return out


def dialogue_topic_adherence(turns, topic) -> dict:
    """Grade an ordinary studio conversation against its active subject.

    Unlike ``topic_adherence`` this has no caller protocol. It asks three
    simple continuity questions: does the opening name the subject, do at
    least half the spoken turns keep touching it, and does the exchange ever
    wander for three turns in a row. That catches a toilet conversation that
    abruptly becomes one about broth without requiring every sentence to
    repeat the same noun.
    """
    clean = [(str(marker or "").upper(), " ".join(str(text or "").split()))
             for marker, text in (turns or []) if str(text or "").strip()]
    nouns = topic_nouns(topic)
    stems = [_stem(noun) for noun in nouns]
    out = {"checked": bool(stems), "ok": True, "nouns": nouns[:12],
           "score": 1.0, "turns": len(clean), "addressing": len(clean),
           "opening": True, "faults": [], "wandering": []}
    if not stems or not clean:
        return out
    hits = [_mentions(text, stems) for _marker, text in clean]
    opening = any(hits[:min(2, len(hits))])
    addressing = sum(1 for hit in hits if hit)
    score = addressing / len(hits)
    wandering = []
    run = []
    for index, hit in enumerate(hits):
        if hit:
            run = []
        else:
            run.append(index)
            if len(run) >= 3:
                wandering.extend(run[-1:])
    need = max(1, (len(hits) + 1) // 2)
    ok = bool(opening and addressing >= need and not wandering)
    faults = []
    if not opening:
        faults.append("the opening does not establish the active subject (%s)"
                      % ", ".join(nouns[:5]))
    if addressing < need:
        faults.append("only %d of %d turns address the active subject (%s)"
                      % (addressing, len(hits), ", ".join(nouns[:5])))
    if wandering:
        faults.append("the conversation leaves the subject for three or more consecutive turns")
    out.update({"ok": ok, "score": round(score, 2),
                "addressing": addressing, "opening": opening,
                "faults": faults, "wandering": wandering[:12]})
    return out


def topic_words_dropped(source, candidate, nouns) -> list:
    """The subject words a rewrite dropped: present in the source line, absent
    from the candidate (by stem). For the tint's contract."""
    src = {_stem(w) for w in _words(source)}
    dst = {_stem(w) for w in _words(candidate)}
    dropped = []
    for n in (nouns or []):
        s = _stem(str(n))
        if not s:
            continue
        in_src = any(_same(s, w) for w in src)
        in_dst = any(_same(s, w) for w in dst)
        if in_src and not in_dst:
            dropped.append(str(n))
    return dropped


# --- the prompt ----------------------------------------------------------------------
def topic_contract_clause(topic, caller_name: str = "") -> str:
    """The paragraph that makes the caller's subject the spine of the round.

    Rides in the caller angle (dj_caller), the one-shot rewrite prompt
    (dj_banter) and, in slot form, _schedule_clause - so the legacy chain
    and System2's per-slot brief both carry it."""
    subject = topic_subject(topic)
    if not subject:
        return ""
    nouns = topic_nouns(subject)[:8]
    name = str(caller_name or "").strip() or "the caller"
    return (
        " THE SUBJECT OF THIS CALL, AND THE SPINE OF THE WHOLE ROUND (#1249): "
        + subject + (" " if subject.endswith((".", "!", "?")) else ". ")
        + name + " rang about THAT and nothing else, and says so in their own "
        "words right after the greeting. From then on EVERY host turn is about "
        "it - name it (" + ", ".join(nouns) + "), ask what happened next, argue "
        "with it, top it, take it further - and the co-host answers what "
        + name + " just said about it, never something else. No host turn "
        "wanders onto another subject until the sign-off. Nobody on this call "
        "says 'act one', 'act two', 'act three', 'scene', 'chapter', 'storyline' "
        "or 'plot' - they are living it, not reading it (#1240).")


# --- the emergency skeleton -----------------------------------------------------------
# The line every skeleton carries, so a round can be told apart from a
# model-written one without a flag travelling with it.
SKELETON_TELL = "that is the part I cannot shake"

_PLACES = (
    "the all-night laundromat while the dryers shake the wall",
    "a parked car behind the grocery store with rain on the roof",
    "the loading dock at work while the last truck idles",
    "a kitchen with the refrigerator clicking on and off",
    "the bus shelter by the courthouse under a broken light",
    "a garage where an old box fan keeps changing speed",
    "the apartment stairwell because everybody else is asleep",
    "a motel walkway with the ice machine grinding behind me",
)
# The incident and the object are paired BY INDEX - obj = _OBJECTS[
# incident_at] below - because selecting them apart produced "a
# dashboard incident followed by a host inexplicably asking about a warm
# handrail". So the two tuples must stay the same length and in the same
# order: entry N of one is entry N of the other. [#1386]
_INCIDENTS = (
    "the metal table got warm enough that my paper receipt curled",
    "the dashboard display blinked twice and the radio lost its clock",
    "a stack of shipping labels lifted as if the room had taken a breath",
    "the magnets slid down the refrigerator door one by one",
    "the light above me dimmed whenever the warm air rolled through",
    "the fan changed pitch and pushed a hot-paper smell across the room",
    "the handrail felt warm even though nobody had touched it",
    "the ice machine stopped, coughed once, and started blowing warm air",
    "the door handle went tacky, like it had been held all day",
    "the meter box outside started humming in a key it has never used",
    "the window sweated on the inside while the night was dry",
    "the vending machine flickered every time somebody walked past it",
    "the coin return was warm and there had been no coins in it",
    "the radiator ticked in threes and it is not even switched on",
    "a stack of cardboard went damp from the bottom up with no water near it",
    "the strip light buzzed louder whenever anyone stopped talking",
    "the escalator stalled and started again with nobody on it",
    "the freezer door clouded over from the outside",
    "the manhole cover outside sat loose and it rocked when the air moved",
    "the smoke alarm chirped once an hour and the battery is new",
)
_OBJECTS = ("curled receipt", "blinking clock", "loose labels",
            "sliding magnets", "dimming light", "box fan",
            "warm handrail", "broken ice machine",
            # [#1386] the deck was EIGHT, picked round-robin, and it
            # showed: 909 of 5,951 gold bars carried one of these eight
            # nouns, spread almost perfectly evenly (166/153/125/124/
            # 124/115/112/102) - the fingerprint of a modulo, not of
            # speech. On air it was one frame with the noun swapped:
            # "warm handrail is the part", "box fan is the part",
            # "dimming light is the part". Banning "handrail" removed
            # one of eight and the other seven kept running.
            "tacky door handle", "humming meter box", "sweating window",
            "flickering vending machine", "warm coin return",
            "ticking radiator", "damp cardboard", "buzzing strip light",
            "stalled escalator", "clouded freezer door",
            "loose manhole cover", "chirping smoke alarm")
_LANDINGS = (
    "I wanted somebody else to hear the detail before I talked myself out of it",
    "I needed to know whether that sounds ordinary from inside your booth",
    "I called because the little physical detail is harder to dismiss than a theory",
    "I figured the station discussing it should have one report from outside the room",
    "I wanted the story on the record while I could still describe it exactly",
    "I needed a human voice to tell me whether to laugh or unplug something",
    "I thought you might recognize the pattern before it happens somewhere else",
    "I called because hearing it repeated back makes it either real or ridiculous",
)


def fallback_call_script(caller_name: str, topic: str = "",
                         speakerbox_text: str = "", line: str = "") -> str:
    """#805's guarantee, rewritten for #1249: when the model's call write
    dies, THIS airs - and now it is about what the caller rang about.

    The caller states the subject in their own words; every host turn after
    the greeting names a piece of it; the skeleton's own furniture (the
    incident, the object, the landing) stays the caller's private detail
    rather than the thing the hosts respond to. Same stable seed, same
    places/incidents/landings tables, so the novelty gate sees the same
    spread it always did. No act label, no prompt wrapper, ever reaches a
    spoken line (#1240)."""
    name = " ".join(str(caller_name or "").split()) or "the caller"
    subject = topic_subject(topic, cap=320)
    texture = " ".join(str(speakerbox_text or "").split()).strip(' "')
    _sentences = re.split(r"(?<=[.!?])\s+", texture)
    texture = " ".join(_sentences[:2])[:320].rstrip().rstrip(".!?;:,")
    seed = int(hashlib.sha1(
        f"{name}|{subject[:160]}|{texture}".encode("utf-8", "ignore")).hexdigest(), 16)
    at = seed % len(_PLACES)
    incident_at = (seed // len(_PLACES)) % len(_INCIDENTS)
    incident = _INCIDENTS[incident_at]
    obj = _OBJECTS[incident_at]
    landing = _LANDINGS[(seed // 17) % len(_LANDINGS)]
    line_ref = "The request line"

    phrases = topic_noun_phrases(subject) if subject else []
    p_last = phrases[-1] if phrases else "detail"
    p_first = phrases[0] if phrases else p_last
    if subject:
        lead = _first_sentence(subject).rstrip(".!?")
        lead2 = _lower_lead(second_person(lead))
        said_subject = subject if subject.endswith((".", "!", "?")) else subject + "."
        if _is_first_person(subject):
            states = said_subject
        else:
            states = "Here is what is happening where I am: " + _lower_lead(said_subject)
    else:
        lead2 = "what you rang about"
        states = "I rang about what the station has been talking about tonight."

    # Repeat a bounded phrase from the actual pivot. The old four-character
    # filter erased every distinctive word in short, ordinary seeds such as
    # "You go out to eat a lot, too", then substituted an unrelated prop.
    # The contract quite correctly refused that as no caller-to-host handoff.
    texture_words = re.findall(r"[A-Za-z0-9']+", texture)
    texture_anchor = " ".join(texture_words[:10]) or obj
    if texture:
        source_turn = (
            f"B: The {obj} made you check twice, and the {p_last} - "
            f"{SKELETON_TELL}. You said you brought another thought with "
            "you; what is it?\n"
            f"C: The other thing turning in my head is this: {texture}. It "
            f"changes how I read the {p_last}, because it gives us a second "
            "subject instead of one more symptom.\n"
            f"B: You said \"{texture_anchor}\". That opens the call up, but the "
            f"{p_last} - still the story: if we follow it, we do not end on "
            f"the {obj}; it is the door back into the {p_first}.\n")
    else:
        source_turn = (
            f"B: The {p_last} - {SKELETON_TELL}. What did it make you think "
            "was happening?\n"
            f"C: It made me think the detail was evidence rather than scenery, "
            f"and that the {p_last} deserved a real answer from the booth.\n"
            f"B: That changes it. The {p_last}: that is the door into the "
            "point, not a loose detail we can thank you for and abandon.\n")
    return (
        f"A: {line_ref} is ringing. Pine Box FM, you're live; go ahead.\n"
        f"C: Hi, this is {name}, calling from {_PLACES[at]}.\n"
        f"B: {name}, good to have you. What made you call tonight?\n"
        f"C: {states} It stopped being an abstract worry when {incident}; "
        "that was the moment it became something happening in my own room.\n"
        f"A: When the {obj} made you stop, what came first? Say the {p_last} "
        f"part again slowly, {name}, because I want it exactly as it happened.\n"
        f"C: I moved closer, checked it twice, and wrote down the time. The "
        f"{obj} made me look, and then there it was: the {p_last}. "
        "Nothing dramatic happened after that, which made it feel more "
        "specific rather than less.\n"
        + source_turn
        + f"C: That resolves why I called: {landing}. You followed the "
        f"{p_last} into the point instead of talking past me, and I am ready "
        "to leave it there.\n"
        f"A: Thank you for calling, {name}. Stay with Pine Box FM; we're "
        f"taking the {p_last} back to the music.")
