# -*- coding: utf-8 -*-
"""sfx_match - [#1251] the SFX guy's clips, matched LOOSELY to the dialogue.

Repo path: spark-agent/sfx_match.py (a sibling of app.py, imported by it
behind a guard - a missing module only switches the matcher off).

"i want to add a special mode to the sfx guy and endless video mode to have
 him play clips appropriate to the statements being said on the radio ...
 not word for word but loosely ... either via the noun, verb, or context.
 The goal will be to still be able to play the video seamlessly no matter
 what."

WHAT THE LIBRARY ACTUALLY HOLDS (measured 2026-09-21 on data/sfx_clips.db):
307,402 playable clips; 217,458 of them are named "NNN clip" or "NNN clip-K"
and carry no words at all; 89,944 carry the first two to four words of the
clip's own transcript ("1065 dying for some", "1148 boo I hate", "37
Austria. As a"). The FOLDER names carry the source - simp, koth, dbz,
chappelle, rasslin, casino - which is context, not words. So the matcher
scores two things: the words a clip's NAME shares with the line (strong
evidence, weighted by how rare the word is across the library), and the
THEME of the clip's folder (weak evidence, a glossary below plus what the
local model adds one folder at a time, kept in data/sfx_keywords.json).

This module is PURE: no station imports, no I/O, nothing that can block.
app.py hands it rows off the clip book and the line being said; it hands
back a ranked, explained choice. app.py applies the station's own rules to
the survivors (bans, weights, the folder pin, the unrepeated rings, the
endless set's hour cooldown) and falls back to the ordinary random draw
whenever nothing scores above the strength floor - so no road ever stalls.

Tested by tests/test_sfx_match_1251.py over real clip names.
"""
from __future__ import annotations

import array
import math
import random
import re
from typing import Any, Iterable

VERSION = 1

# --- the dial ----------------------------------------------------------------
#
# A candidate's score is the sum of the weights of the words it shares with
# the line (about 1.0 for a common word, up to 2.5 for a rare one) plus a
# capped bonus for its folder's theme. The strength dial (0-100) sets the
# floor a match must clear to beat the random draw:
#
#   0    0.75  any loose connection wins - even the folder's theme alone
#   35   1.54  the default: one fairly uncommon word out of the line, or two
#              common ones, in the clip's name
#   100  3.00  two rare words, or three common ones
STRENGTH_FLOOR = 0.75
STRENGTH_SPAN = 2.25
FOLDER_HIT = 0.8            # per folder keyword the line touches
FOLDER_CAP = 1.6            # a folder can never outscore a real word match
CTX_SCALE = 0.5             # a topic/plot word is worth half a spoken one
UNSEEN_WEIGHT = 1.6         # a word the library has never named (keyword only)
WEIGHT_MIN, WEIGHT_MAX = 0.6, 2.5
POSTINGS_CAP = 4000         # a very common word is sampled, not walked whole
FOLDER_SAMPLE = 24          # folder-only candidates drawn per themed folder


def threshold(strength: Any) -> float:
    try:
        k = max(0, min(100, int(strength)))
    except (TypeError, ValueError):
        k = 35
    return round(STRENGTH_FLOOR + STRENGTH_SPAN * (k / 100.0), 3)


# --- words -------------------------------------------------------------------

STOP = frozenset("""
a about above after again against ago all almost along already also although
always am among an and another any anybody anyone anything anyway anywhere are
aren't around as at away back be became because become been before behind
being below beside besides between beyond both but by came can can't cannot
come comes coming could couldn't did didn't do does doesn't doing don't done
down during each either else enough even ever every everybody everyone
everything everywhere few for from further get gets getting give given gives
giving go goes going gone gonna got gotta had hadn't has hasn't have haven't
having he he'd he'll he's her here here's hers herself him himself his how
how's however i i'd i'll i'm i've if in inside instead into is isn't it it's
its itself just keep kept kind kinda know knew known knows last later least
less let let's lets like likely little look looked looking looks lot lots
made make makes making many may maybe me mean means meant might mine more
most mostly much must mustn't my myself near need needs never new next no
nobody none nor not nothing now nowhere of off often oh ok okay on once one
ones only onto or other others otherwise ought our ours ourselves out over
own pretty put puts quite rather really right said same saw say saying says
see seen seem seemed seems shall shan't she she'd she'll she's should
shouldn't since so some somebody someone something sometimes somewhere soon
still such sure take taken takes taking tell than that that's the their
theirs them themselves then there there's these they they'd they'll they're
they've thing things think thinks this those though thought through thus till
to told too took toward towards under until up upon us use used using very
wanna want wanted wants was wasn't way ways we we'd we'll we're we've well
went were weren't what what's whatever when when's whenever where where's
whether which while who who's whoever whole whom whose why why's will with
within without won't would wouldn't yeah yep yes yet you you'd you'll you're
you've your yours yourself yourselves
ah uh um hmm hey huh yo ya nah alright okey wow whoa oops ugh
guy guys man dude bro buddy folks people person god gosh damn hell heck
stuff thing things time times day days today tonight night morning week year
years minute minutes second seconds hour hours moment
good bad great big little old new nice fine cool real really actually
literally basically totally probably definitely absolutely exactly maybe
first second third two three four five six seven eight nine ten hundred
thousand million
clip clips laughter applause music inaudible unknown untitled audio video
sound sounds mp3 mp4 wav
""".split())

IRREGULAR = {
    "men": "man", "women": "woman", "children": "child", "mice": "mouse",
    "feet": "foot", "teeth": "tooth", "geese": "goose", "wolves": "wolf",
    "knives": "knife", "wives": "wife", "lives": "life", "leaves": "leaf",
    "ran": "run", "running": "run", "sang": "sing", "sung": "sing",
    "ate": "eat", "eaten": "eat", "drank": "drink", "drunk": "drink",
    "drove": "drive", "driven": "drive", "fought": "fight", "bought": "buy",
    "caught": "catch", "taught": "teach", "broke": "break", "broken": "break",
    "stole": "steal", "stolen": "steal", "threw": "throw", "thrown": "throw",
    "wore": "wear", "worn": "wear", "flew": "fly", "flown": "fly",
    "died": "die", "dying": "die", "dies": "die", "lying": "lie", "lied": "lie",
    "spoke": "speak", "spoken": "speak", "swore": "swear", "sworn": "swear",
    "shot": "shoot", "slept": "sleep", "fell": "fall", "fallen": "fall",
    "rode": "ride", "ridden": "ride", "wrote": "write", "written": "write",
    "sold": "sell", "paid": "pay", "lost": "lose", "won": "win", "hit": "hit",
    "children's": "child", "cops": "cop", "police": "cop", "policeman": "cop",
    "kids": "kid", "kiddo": "kid", "babies": "baby", "cars": "car",
    "dogs": "dog", "doggy": "dog", "cats": "cat", "kitty": "cat",
    "mom": "mother", "momma": "mother", "mama": "mother", "moms": "mother",
    "dad": "father", "daddy": "father", "dads": "father", "pops": "father",
    "trash": "garbage", "rubbish": "garbage", "bin": "garbage",
    "raccoons": "raccoon", "booze": "alcohol", "liquor": "alcohol",
    "beers": "beer", "cash": "money", "bucks": "money", "dollars": "money",
    "dollar": "money", "phones": "phone", "telephone": "phone",
    "tv": "television", "telly": "television", "movies": "movie",
    "film": "movie", "films": "movie", "cinema": "movie",
    "wrestle": "wrestling", "wrestler": "wrestling", "wrestlers": "wrestling",
    "cartoons": "cartoon", "anime": "cartoon", "toons": "cartoon",
}

_WORD = re.compile(r"[a-z][a-z']*")
_NAME_JUNK = re.compile(r"^\s*(?:\d+\s*)?clip(?:[-_ ]?\d+)?\s*$", re.I)
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


def _undouble(w: str) -> str:
    """runn -> run, hitt -> hit; never ll, ss, ff, zz (fall, kiss, stuff, buzz)."""
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsfz":
        return w[:-1]
    return w


def _keep(before: str, after: str) -> str:
    """A rule that would leave under three letters is not applied."""
    return after if len(after) >= 3 else before


def stem(word: Any) -> str:
    """One deterministic key per word family: make/makes/making -> mak,
    raccoon/raccoons -> raccoon, trash/trashed/trashes -> garbag (via the
    irregular table). Equality is the only thing it is used for, so a stem
    need not be a word. Empty for a stop word or a number. Idempotent on
    its own output (tested), so a stored keyword may be stemmed again."""
    w = str(word or "").lower().strip("'")
    if w.endswith("'s"):
        w = w[:-2]
    w = w.replace("'", "")
    if len(w) < 3 or w.isdigit() or w in STOP:
        return ""
    w = IRREGULAR.get(w, w)
    if w in STOP:
        return ""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 5 and w.endswith("ing"):
        w = _keep(w, _undouble(w[:-3]))
    elif len(w) > 4 and w.endswith("ed"):
        w = _keep(w, _undouble(w[:-2]))
    elif len(w) > 4 and w.endswith("es") and (w[-3] in "sxz" or w.endswith(("ches", "shes"))):
        w = _keep(w, w[:-2])
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = _keep(w, w[:-1])
    if len(w) > 4 and w.endswith("ly"):
        w = _keep(w, w[:-2])
    # The irregular table once more, so a stripped form that is itself a
    # key (trashed -> trash -> garbage) lands where the plain word lands,
    # and the trailing-e rule LAST so both roads end on the same key.
    w = IRREGULAR.get(w, w)
    if len(w) > 3 and w.endswith("e"):
        w = _keep(w, w[:-1])
    if len(w) < 3 or w in STOP:
        return ""
    return w


def tokens(text: Any) -> dict[str, str]:
    """stem -> the surface word it was first seen as, in order of appearance."""
    out: dict[str, str] = {}
    for raw in _WORD.findall(str(text or "").lower()):
        if raw in STOP:
            continue
        s = stem(raw)
        if s and s not in out:
            out[s] = raw.strip("'")
    return out


def is_bare_name(name: Any) -> bool:
    """'1965 clip', '58 clip-27' - a name with nothing in it to match."""
    return bool(_NAME_JUNK.match(str(name or "")))


def folder_name_tokens(name: Any) -> list[str]:
    """10hrTIKtok -> [tiktok]; IASIP_1 -> [iasip]; 'it crowd' -> [crowd]."""
    parts = re.split(r"[^A-Za-z0-9]+", _CAMEL.sub(" ", str(name or "")))
    out: list[str] = []
    for p in parts:
        s = stem(p.lower())
        if s and s not in out:
            out.append(s)
    return out


# --- the folder glossary ----------------------------------------------------
#
# The names of the folders the library holds today, and the themes a host's
# sentence might touch that would make one of their clips fit. A guess is
# harmless: a folder hit is capped well under a real word match, and the
# local model replaces these one folder at a time (see app.py's keeper).
FOLDER_GLOSSARY: dict[str, str] = {
    "10hrtiktok": "tiktok phone viral dance meme internet teenager scroll",
    "ttok": "tiktok phone viral dance meme internet teenager scroll",
    "vine": "vine meme viral internet phone six seconds prank",
    "yt": "youtube video internet channel subscribe",
    "tuber": "youtube youtuber vlog subscribe influencer camera",
    "iasip_1": "philadelphia bar pub drunk scheme gang paddy beer irish",
    "iasip_2": "philadelphia bar pub drunk scheme gang paddy beer irish",
    "ias": "philadelphia bar pub drunk scheme gang paddy beer irish",
    "adamcurtis": "documentary history politics power government britain dream system empire",
    "amerdad": "cartoon cia spy alien roger family suburb patriot fish",
    "aswim": "cartoon adult swim absurd late night weird bump",
    "casino": "vegas casino gamble money cards dice mafia mob chips bet",
    "chappelle": "comedy sketch standup dave rick james prince crack",
    "consp": "conspiracy alien government secret illuminati ufo cover-up plot moon landing",
    "crackpot": "crackpot crazy theory rant nonsense weird",
    "crunk": "party club hip hop rap drink shout lil jon",
    "daria": "sarcasm high school teenager cynical cartoon sick sad world",
    "dbz": "dragon ball goku vegeta saiyan power level fight scream cartoon",
    "deadwood": "western saloon gold whiskey cowboy sheriff frontier swearing",
    "dexter": "serial killer blood miami knife murder dark",
    "drma": "drama argument crying fight",
    "fguy": "cartoon family peter stewie brian dog quagmire chicken fight",
    "genie": "genie wish lamp magic aladdin",
    "hellsing": "vampire alucard cartoon blood gun church",
    "hix": "comedy standup rant marketing drugs government bill hicks",
    "inliving": "sketch comedy homey clown fire marshal fly girls nineties",
    "it crowd": "computer internet nerd basement office turn it off and on again",
    "koth": "propane texas lawn beer alley cartoon hank dale dang",
    "ktony": "comedy podcast standup roast open mic bucket austin",
    "madv": "sketch comedy mad tv stuart swan",
    "mandwebb": "british sketch comedy snooker numberwang baddies",
    "mberry": "british actor voice toast theatre matt berry",
    "moon": "moon space night astronaut lunar rocket",
    "msho": "sketch comedy absurd bob david mr show",
    "mwc": "married children al bundy shoes couch family sitcom",
    "patrice": "comedy standup women relationships radio black phillip",
    "peele": "sketch comedy key peele obama substitute teacher valet",
    "peep": "british flat awkward mark jez croydon peep show",
    "quote": "quote saying wisdom",
    "rasslin": "wrestling ring champion belt suplex promo hulk macho man",
    "roast": "roast insult burn jokes comedy central",
    "sfx site": "sound effect boom crash bang",
    "simp": "cartoon springfield homer bart marge lisa donut duff nuclear doh",
    "sora": "artificial intelligence generated surreal video dream",
    "stanford": "university lecture professor science study research",
    "svalley": "startup tech app code investor silicon valley compression",
    "tate": "hustle bugatti matrix alpha rich money escape",
    "toast": "actor voice over theatre british clem fandango",
    "tony": "mafia therapy jersey family gabagool waste management",
    "trae": "southern redneck rant politics comedy",
    "walkoff": "walk leave storm out argument",
    "charlie": "charlie",
    "chris": "chris",
    "bobby": "bobby",
    "caleb": "money debt budget finance credit broke",
    "nniles": "frasier seattle radio psychiatrist wine opera snob",
    "elgra": "",
    "trags": "tragedy",
    "rest": "rest sleep",
    "clips": "",
    "clipz": "",
    "random": "",
}


def folder_seed_keywords(folder: Any) -> list[str]:
    """The glossary's words plus the folder's own name, stemmed, unique."""
    name = str(folder or "")
    out: list[str] = []
    for s in folder_name_tokens(name):
        if s not in out:
            out.append(s)
    for stem_ in tokens(FOLDER_GLOSSARY.get(name.lower(), "")):
        if stem_ not in out:
            out.append(stem_)
    return out


def parse_keywords(answer: Any, most: int = 10) -> list[str]:
    """The local model's comma list -> stems. Defensive: a chatty answer
    still yields its words; an empty or refusing one yields []."""
    text = str(answer or "")
    text = re.sub(r"(?i)keywords?\s*:", " ", text)
    out: list[str] = []
    for piece in re.split(r"[,\n;/]+", text):
        for s in tokens(piece):
            if s not in out:
                out.append(s)
            if len(out) >= most:
                return out
    return out


def keyword_prompt(folder: Any, samples: Iterable[Any]) -> str:
    names = [str(s or "").strip() for s in samples if str(s or "").strip()]
    shown = "; ".join(n[:60] for n in names[:8]) or "(the names carry no words)"
    return (
        "A radio station's sound-effects man keeps a folder of short clips "
        f"named \"{str(folder or '')[:60]}\". Some of the clips in it are "
        f"named after their first words: {shown}. In ONE line, list up to "
        "eight lowercase keywords - nouns, verbs and themes a radio host's "
        "sentence might contain that these clips would suit: the show or "
        "person they come from, its characters, its subjects, its mood. "
        "Comma-separated, no explanations, no numbers.")


# --- the index ----------------------------------------------------------------

class Cand:
    __slots__ = ("ix", "rowid", "fid", "folder", "score", "hits")

    def __init__(self, ix: int, rowid: int, fid: int, folder: str,
                 score: float, hits: list[tuple[str, str]]):
        self.ix, self.rowid, self.fid, self.folder = ix, rowid, fid, folder
        self.score, self.hits = score, hits

    def words(self, kind: str) -> list[str]:
        out: list[str] = []
        for surface, k in self.hits:
            if k == kind and surface not in out:
                out.append(surface)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"rowid": self.rowid, "folder": self.folder,
                "score": round(self.score, 2),
                "line": self.words("line"), "context": self.words("context"),
                "folder_words": self.words("folder")}


class ClipIndex:
    """Every playable clip as a few bytes, and an inverted index over the
    words in the wordy names. Built on a thread off the clip book; scored
    in a millisecond or two on the pick's own thread."""

    def __init__(self) -> None:
        self.rowids = array.array("q")
        self.fids = array.array("h")
        self.video = bytearray()
        self.secs = array.array("f")
        self.post: dict[str, array.array] = {}
        self.df: dict[str, int] = {}
        self.folders: list[str] = []
        self.folder_ix: dict[str, int] = {}
        self.folder_entries: dict[int, array.array] = {}
        self.folder_keywords: dict[int, list[str]] = {}
        self.folder_post: dict[str, list[int]] = {}
        self.wordy = 0
        self.clips = 0
        self.built_at = 0.0

    # -- building --
    def build(self, rows: Iterable[tuple[Any, Any, Any, Any, Any]],
              folder_keywords: dict[str, Iterable[str]] | None = None,
              nap: Any = None, nap_every: int = 2000) -> "ClipIndex":
        """rows: (rowid, name, folder, video, seconds). `nap()` is called
        every `nap_every` rows so a daemon thread hands the GIL back."""
        post: dict[str, list[int]] = {}
        entries: dict[int, list[int]] = {}
        n = 0
        for rowid, name, folder, is_video, seconds in rows:
            folder = str(folder or "")
            fid = self.folder_ix.get(folder)
            if fid is None:
                fid = len(self.folders)
                self.folders.append(folder)
                self.folder_ix[folder] = fid
                entries[fid] = []
            ix = n
            n += 1
            self.rowids.append(int(rowid))
            self.fids.append(fid)
            self.video.append(1 if is_video else 0)
            try:
                self.secs.append(float(seconds or 0))
            except (TypeError, ValueError):
                self.secs.append(0.0)
            entries[fid].append(ix)
            nm = str(name or "")
            if not is_bare_name(nm):
                toks = tokens(nm)
                if toks:
                    self.wordy += 1
                for t in toks:
                    post.setdefault(t, []).append(ix)
            if nap is not None and n % nap_every == 0:
                try:
                    nap()
                except Exception:  # noqa: BLE001
                    pass
        self.clips = n
        self.post = {t: array.array("i", v) for t, v in post.items()}
        self.df = {t: len(v) for t, v in post.items()}
        self.folder_entries = {f: array.array("i", v) for f, v in entries.items()}
        for fid, folder in enumerate(self.folders):
            given = list((folder_keywords or {}).get(folder) or [])
            self.set_folder_keywords(folder, given or folder_seed_keywords(folder))
        return self

    def set_folder_keywords(self, folder: str, keywords: Iterable[str]) -> None:
        """Replace one folder's theme words. Accepts stems (what
        folder_seed_keywords / parse_keywords hand back - stem() is
        idempotent) or raw words and phrases, which are tokenised."""
        fid = self.folder_ix.get(str(folder or ""))
        if fid is None:
            return
        stems: list[str] = []
        for k in keywords or []:
            for s2 in tokens(k):
                if s2 not in stems:
                    stems.append(s2)
        for s in self.folder_keywords.get(fid) or []:
            got = self.folder_post.get(s)
            if got and fid in got:
                got.remove(fid)
                if not got:
                    del self.folder_post[s]
        self.folder_keywords[fid] = stems
        for s in stems:
            lst = self.folder_post.setdefault(s, [])
            if fid not in lst:
                lst.append(fid)

    def folder_names(self) -> list[str]:
        return list(self.folders)

    # -- scoring --
    def weight(self, tok: str) -> float:
        df = self.df.get(tok)
        if not df:
            return UNSEEN_WEIGHT
        w = 0.5 * math.log10(max(1, self.wordy) / float(df))
        return max(WEIGHT_MIN, min(WEIGHT_MAX, w))

    def score(self, line: Any, ctx: Any = "", *, video: bool | None = None,
              floor: float = 0.0, cap: float = 0.0, limit: int = 48,
              sample: int = FOLDER_SAMPLE, rng: Any = random) -> list[Cand]:
        """Ranked candidates for one line (and its context), filtered by
        picture/no picture and length. No station rule is applied here."""
        q = tokens(line)
        c = {s: w for s, w in tokens(ctx).items() if s not in q} if ctx else {}
        if not q and not c:
            return []
        scores: dict[int, float] = {}
        hits: dict[int, list[tuple[str, str]]] = {}

        def walk(bag: dict[str, str], scale: float, kind: str) -> None:
            for s, surface in bag.items():
                postings = self.post.get(s)
                if not postings:
                    continue
                w = self.weight(s) * scale
                if len(postings) > POSTINGS_CAP:
                    picks = rng.sample(range(len(postings)), POSTINGS_CAP)
                    it: Iterable[int] = (postings[i] for i in picks)
                else:
                    it = postings
                for ix in it:
                    scores[ix] = scores.get(ix, 0.0) + w
                    hits.setdefault(ix, []).append((surface, kind))

        walk(q, 1.0, "line")
        if c:
            walk(c, CTX_SCALE, "context")
        # The folder's theme: capped, and only ever a bonus or a fallback.
        fsc: dict[int, float] = {}
        fhits: dict[int, list[tuple[str, str]]] = {}
        for bag, scale in ((q, 1.0), (c, CTX_SCALE)):
            for s, surface in bag.items():
                for fid in self.folder_post.get(s, ()):
                    fsc[fid] = min(FOLDER_CAP, fsc.get(fid, 0.0) + FOLDER_HIT * scale)
                    fhits.setdefault(fid, []).append((surface, "folder"))
        if fsc:
            for ix in list(scores):
                fid = self.fids[ix]
                if fid in fsc:
                    scores[ix] += fsc[fid]
                    hits[ix].extend(fhits[fid])
            for fid, fs in fsc.items():
                pool = self.folder_entries.get(fid)
                if not pool:
                    continue
                k = min(max(1, sample), len(pool))
                for j in (rng.sample(range(len(pool)), k) if k < len(pool) else range(len(pool))):
                    ix = pool[j]
                    if ix not in scores:
                        scores[ix] = fs
                        hits[ix] = list(fhits[fid])
        out: list[Cand] = []
        for ix, s in scores.items():
            if video is not None and bool(self.video[ix]) != bool(video):
                continue
            sec = self.secs[ix]
            if floor and sec < floor:
                continue
            if cap and sec > cap:
                continue
            fid = self.fids[ix]
            out.append(Cand(ix, self.rowids[ix], fid, self.folders[fid], s, hits[ix]))
        out.sort(key=lambda cand: (-cand.score, cand.rowid))
        return out[:max(1, limit)]

    def stats(self) -> dict[str, Any]:
        return {"clips": self.clips, "wordy": self.wordy, "tokens": len(self.post),
                "folders": len(self.folders),
                "folders_with_keywords": sum(1 for v in self.folder_keywords.values() if v),
                "built_at": self.built_at}


BAND = 0.3                  # candidates this close to the best are peers


def peers(cands: Iterable[Cand], floor: float, band: float = BAND) -> list[Cand]:
    """The candidates that TIE with the best one, in order.

    Split out of `choose` so a caller that already owns a rotation rule -
    app.py draws every sting through `unrepeated`, which is the station's
    one recency ring and survives a restart (#1225) - can apply the
    matcher's judgement without a second, independent draw fighting it.
    Ordered input, best first; empty when nothing clears the floor, which
    is the signal to fall back to the ordinary draw."""
    above = [c for c in cands if c.score >= floor]
    if not above:
        return []
    best = above[0].score
    return [c for c in above if c.score >= best - band]


def choose(cands: Iterable[Cand], floor: float, band: float = BAND,
           rng: Any = random) -> Cand | None:
    """Among the candidates at or above the floor, a uniform draw over the
    ones within `band` of the best score - so the strongest match wins,
    and equal matches (a dozen clips all named for the same word) rotate
    instead of fossilising on one. Ordered input, best first."""
    tied = peers(cands, floor, band)
    return rng.choice(tied) if tied else None


def explain(cand: Cand | None) -> str:
    """'matched 'raccoon', 'trash'' - the line the operator reads on the
    feed row, the script's action line and the air log."""
    if cand is None:
        return ""
    def quoted(words: list[str], most: int) -> str:
        return ", ".join("'%s'" % w for w in words[:most])
    line = cand.words("line")
    ctx = cand.words("context")
    fold = cand.words("folder")
    parts: list[str] = []
    if line:
        parts.append("matched " + quoted(line, 4))
    if ctx:
        parts.append(("and the topic " if parts else "matched the topic ") + quoted(ctx, 3))
    if fold:
        parts.append(("via the %s folder (%s)" if parts else "matched the %s folder (%s)")
                     % (cand.folder or "?", quoted(fold, 3)))
    return " ".join(parts)


def read_tsv_rows(lines: Iterable[str]) -> Iterable[tuple[int, str, str, bool, float]]:
    """rowid \\t sid \\t folder \\t video \\t seconds \\t name [\\t path] - the
    dump shape tests and the replay use."""
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 6:
            continue
        try:
            yield (int(parts[0]), parts[5], parts[2], parts[3] in ("1", "True", "true"),
                   float(parts[4] or 0))
        except ValueError:
            continue
