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
    ("activeplot", "The active radio plot: title and current act, without future spoilers.", ""),
    ("topic", "A rolled topic from the station topic bank, for dialogue inspiration.", ""),
    ("speakerbox", "A sentence rolled out of a rolled Speakerbox document.", ""),
    ("book", "A real EPUB or PDF title rolled from the station library. All book fields in this generation use this title; {book:Title or library ID} binds one explicitly.", "A Test Book"),
    ("booktopic", "A subject from the selected book's metadata, an actual chapter heading, or a phrase from the selected passage. Used alone, it first rolls a source book.", "The River Garden"),
    ("bookchapter", "The selected book's actual EPUB chapter or PDF outline title. A PDF without chapter metadata reports its source page instead.", "Chapter Two: The River Garden"),
    ("booksegment", "A bounded passage of consecutive source sentences from the selected book, for discussion rather than a whole chapter reading.", "The river fed the garden. They shared the harvest."),
    ("booksentence", "One exact, complete short sentence from the selected book passage (up to 35 words).", "They shared the harvest."),
    ("booksentences", "Up to three consecutive complete source sentences from that passage, up to 100 words total, for brief quotations.", "The river fed the garden. They shared the harvest."),
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
    ("gazette", "The latest Pine Box Gazette: roll a section, then an article inside it; use the article text "
                "in prompts or dialogue.", 'the Pine Box Gazette, section "news", article "...": ...'),
    ("arena", "An arena built from a rolled Pine Box gallery picture. Use {arena} and {arena2} for two "
              "different arenas.", 'an arena built from the Pine Box gallery picture "neon forest"'),
    # [h3-feature] "the technical overview prompt to grab a feature randomly from the
    # release log ... I'm expecting to see {feature} and {releaselog} indicating a
    # roulette roll" (the operator, 2026-10-01). One roll serves both, and the
    # technical overview's pitch presents the same feature.
    ("feature", "A feature of the station, rolled by System 3 from the release log (the changelog's tagged "
                "features): its name in plain words. A technical-overview hour pitches this same feature. "
                "{feature2} rolls a second one.",
     'the Pine Box feature "One press builds, signs, installs and reopens the PineTab" [tablet-update-ask]'),
    ("releaselog", "The release-log entry of the rolled {feature}: its commits, when they landed, their size and "
                   "what the first one changed - the nuances to pitch. {releaselog2} goes with {feature2}.",
     'the release log of [tablet-update-ask] (1 commit, +46/-12 lines): 60e37c0 "One press builds..." - ...'),
    ("a|b|c", "One of the options you write between the bars, rolled.", "{funny|grim|tender}"),
)
NAMED = ("mxtape", "fordtape", "videos", "sfxclip", "convograph", "gazette", "arena", "feature", "releaselog", "book", "booktopic", "bookchapter", "booksegment", "booksentence", "booksentences")
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


def _feature_subject(f: dict[str, Any]) -> str:
    first = (f.get("commits") or [{}])[0] if isinstance(f, dict) else {}
    return quote(first.get("subject") or (f or {}).get("tag") or "something new", 110).rstrip(".")


def feature(f: dict[str, Any]) -> str:
    """[h3-feature] A release-log feature (h3_overview.features), named."""
    return 'the Pine Box feature "%s" [%s]' % (_feature_subject(f), quote(f.get("tag"), 40))


def _first_sentence(body: Any, most: int = 180) -> str:
    """The commit's first sentence of its own: list bullets taken off, and a
    paragraph that opens by quoting the operator passed over for the next."""
    paras = [p for p in re.split(r"\n\s*\n", str(body or "")) if p.strip()]
    keep = []
    for p in paras:
        lines = [re.sub(r"^\s*[-*]\s+", "", ln) for ln in p.splitlines()
                 if ln.strip() and not re.match(r"\s*(Co-Authored-By|Signed-off-by)\b", ln, re.I)]
        text = " ".join(" ".join(lines).split())
        if text and text[0] not in "\"'“‘(":
            keep = [text]
            break
        if text and not keep:
            keep = [text]
    text = keep[0] if keep else ""
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = (m.group(1) if m else text)
    return out if len(out) <= most else out[:most].rsplit(" ", 1)[0] + "..."


def releaselog(f: dict[str, Any], most_commits: int = 3) -> str:
    """[h3-feature] The release-log entry of a feature: its commits (id, when,
    subject), its size and the first commit's opening sentence."""
    commits = list(f.get("commits") or [])
    head = "the release log of [%s] (%d commit%s, +%d/-%d lines)" % (
        quote(f.get("tag"), 40), len(commits), "" if len(commits) == 1 else "s",
        int(f.get("insertions") or 0), int(f.get("deletions") or 0))
    rows = []
    for c in commits[:most_commits]:
        when = quote(c.get("at"), 24)
        rows.append('%s%s "%s"' % (quote(c.get("commit"), 10), (" " + when) if when else "",
                                   quote(c.get("subject"), 90).rstrip(".")))
    out = head + (": " + "; ".join(rows) if rows else "")
    said = _first_sentence(commits[0].get("body")) if commits else ""
    if said:
        out += " - " + quote(said, 180)
    return out


def catalogue() -> list[dict[str, str]]:
    """What the editor's autocomplete offers: {slot, says, example}."""
    return [{"slot": "{%s}" % n, "name": n, "says": s, "example": e} for n, s, e in CATALOGUE]
