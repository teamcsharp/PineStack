"""[h3-slots] The {slots} an hourly H3 prompt may hold, and what each becomes.

"I want to make variants of the system where they're doing ads where MX mix
tapes are playing as the music and they're putting on concerts for it. or
performing it using {mxtape} ... or {fordtape} for tapes by general Ford. Or we
do clips where they battle but they are in different arenas based on pine box
gallery images ... {videos} ... uses videos from the pine box gallery or
{sfxclip} to use an sfx clip at random in roulette ... If I use something like
SFX clip / video bracketed i want there to be a tv or billboard or computer
monitor ... showing the clip ... {convograph} ... presenting conversational
flowchart graphs of real conversations ... {gazette} ... insert the pine box
gazette into the prompt" (the operator, 2026-10-01).

Pure: the catalogue the editor's autocomplete reads (CATALOGUE), the pattern
that finds a named slot, and the phrase each slot becomes once app.py has
gathered its shelf and System 3 has rolled the pick. A named slot may carry one
digit ({arena}, {arena2}): each spelling is its own roll, so two fighters stand
in two arenas.
"""
from __future__ import annotations

import re
from typing import Any

# name -> (what the editor shows, the tooltip, an example of what it becomes)
CATALOGUE: tuple[tuple[str, str, str], ...] = (
    ("conversation", "The hour's talk: whole sentences rolled from what was said on air (or a Speakerbox "
                     "document when nothing whole was said).", "We never sleep at Pine Box FM."),
    ("record", "The record on air when the hour is made: title and artist.", "Moonlight Drive The Doors"),
    ("goal", "The brief, filled - only in a road direction (clip, gallery, host).", ""),
    ("station", "The station's name.", "Pine Box FM"),
    ("hour", "The time the hour is made, HH:MM.", "21:05"),
    ("speakerbox", "A sentence rolled out of a rolled Speakerbox document.", ""),
    ("mxtape", "An MX mixtape by Ehm Eckx, rolled from the tape folder - the music the scene plays to "
               "(a concert, a performance, a dance).", 'the MX mixtape "MX tape · August 4" by Ehm Eckx'),
    ("fordtape", "A tape by General Ford, rolled from the General Ford folder (setting fordtape_folder, "
                 "default samples_grabbed/user/ford on the share, subfolders included).", 'the tape "Night Shift" by General Ford'),
    ("videos", "A Pine Box gallery video, shown on a rolled screen in the scene (a TV, a billboard, a "
               "monitor, a jumbotron...).", 'an old CRT television playing the Pine Box gallery video "lighthouse"'),
    ("sfxclip", "An SFX clip rolled at random from the clip library, shown on a rolled screen in the scene, "
                "with what the clip contains.", 'a computer monitor playing the clip "dog on a skateboard"'),
    ("convograph", "A flowchart of a REAL conversation System 3 made: its road, topic, the dice it rolled "
                   "and who won - for people to present and argue about.",
     'a flowchart of a real Pine Box conversation on the caller road ...'),
    ("gazette", "The Pine Box Gazette: a rolled recent edition's front page, its headline and deck, as a "
                "prop or the scene's subject.", 'the Pine Box Gazette, its front page headline reading "..."'),
    ("arena", "An arena built from a rolled Pine Box gallery picture. Use {arena} and {arena2} for two "
              "different arenas.", 'an arena built from the Pine Box gallery picture "neon forest"'),
    ("a|b|c", "One of the options you write between the bars, rolled.", "{funny|grim|tender}"),
)
NAMED = ("mxtape", "fordtape", "videos", "sfxclip", "convograph", "gazette", "arena")
SLOT = re.compile(r"\{((%s)(\d?))\}" % "|".join(NAMED))

SCREENS = (
    "an old CRT television on a rolling cart",
    "a giant roadside billboard screen",
    "a computer monitor on a cluttered desk",
    "a stadium jumbotron",
    "a phone held up to the camera",
    "a retro arcade cabinet screen",
    "a projector screen pulled down behind them",
)


def tokens(*texts: Any) -> list[str]:
    """Every named slot spelled in the texts ("arena", "arena2"), first seen first."""
    out: list[str] = []
    for t in texts:
        for m in SLOT.finditer(str(t or "")):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out


def base(token: str) -> str:
    m = re.fullmatch(r"(%s)\d?" % "|".join(NAMED), str(token or ""))
    return m.group(1) if m else ""


def tidy(name: Any, most: int = 60) -> str:
    """A file stem as words: "2026-08-04_neon-forest_00012" -> "neon forest"."""
    s = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", str(name or ""))
    s = re.sub(r"\d{4}[-_.]\d{2}[-_.]\d{2}(?:[-_T]\d{2,6})*", " ", s)      # a date stamp
    s = re.sub(r"[_\-.]+", " ", s)
    s = re.sub(r"\b\d{4,}\b|\b\d{1,2}\b(?=\s*$)", " ", s)
    s = " ".join(s.split())
    return s[:most].strip() or "untitled"


def tape_title(stem: Any) -> str:
    """A tape's file stem as its title: "26-PHOTON_3(1)" -> "Photon",
    "SOLARPIZZA_2" -> "Solarpizza", "27-QRHAVOC-02" -> "Qrhavoc"."""
    s = str(stem or "")
    s = re.sub(r"\(\d+\)$", "", s).strip()
    s = re.sub(r"^\d{1,3}[-_ ]+", "", s)
    s = re.sub(r"[-_ ]+\d{1,3}$", "", s)
    s = " ".join(re.sub(r"[_\-.]+", " ", s).split())
    return s.title()[:60]


def quote(text: Any, most: int = 80) -> str:
    return " ".join(str(text or "").replace('"', "'").split())[:most]


def mxtape(title: str) -> str:
    return 'the MX mixtape "%s" by Ehm Eckx' % quote(title)


def fordtape(title: str) -> str:
    return 'the tape "%s" by General Ford' % quote(title)


def video(screen: str, name: str) -> str:
    return '%s playing the Pine Box gallery video "%s"' % (screen, quote(tidy(name)))


def sfxclip(screen: str, row: dict[str, Any]) -> str:
    name = quote(tidy(row.get("name")))
    seen = quote(row.get("seen_desc"), 160)
    said = quote(row.get("said"), 100)
    out = '%s playing the clip "%s"' % (screen, name)
    if seen:
        out += ", which shows %s" % seen.rstrip(".")
    elif said:
        out += ', in which someone says "%s"' % said
    return out


def gazette(edition: dict[str, Any]) -> str:
    head = quote(edition.get("headline"), 120)
    deck = quote(edition.get("deck"), 160)
    out = "the Pine Box Gazette"
    if head:
        out += ', its front page headline reading "%s"' % head
    if deck:
        out += " (%s)" % deck.rstrip(".")
    return out


def arena(name: str) -> str:
    return 'an arena built from the Pine Box gallery picture "%s"' % quote(tidy(name))


def convograph(flow: dict[str, Any], most: int = 4) -> str:
    """A real conversation's flowchart, told: its road and topic, the rolls it
    made (what won, at what odds) and how it ended."""
    nodes = [n for n in flow.get("nodes") or [] if isinstance(n, dict)]
    start = next((n for n in nodes if n.get("type") == "start"), {})
    rolls = []
    for n in nodes:
        if n.get("type") != "decision" or not n.get("winner") or int(n.get("of") or 0) < 2:
            continue
        w = n["winner"]
        p = w.get("p")
        rolls.append('%s rolled "%s"%s over %d others' % (
            str(n.get("family") or "a die").lower(), quote(w.get("label"), 50),
            " at %d%%" % round(float(p) * 100) if isinstance(p, (int, float)) else "", int(n.get("of")) - 1))
        if len(rolls) >= most:
            break
    end = next((n for n in reversed(nodes) if n.get("type") == "end"), {})
    out = "a flowchart of a real Pine Box conversation (#%s) on the %s road" % (
        str(flow.get("key") or "")[:8], flow.get("road") or "banter")
    if start.get("topic"):
        out += ' about "%s"' % quote(start["topic"], 90)
    if rolls:
        out += ": " + "; ".join(rolls)
    turns = (flow.get("counts") or {}).get("turns")
    if turns:
        out += "; %d turns" % int(turns)
    if end.get("label"):
        out += ", %s" % end["label"]
    return out


def catalogue() -> list[dict[str, str]]:
    """What the editor's autocomplete offers: {slot, says, example}."""
    return [{"slot": "{%s}" % n, "name": n, "says": s, "example": e} for n, s, e in CATALOGUE]
