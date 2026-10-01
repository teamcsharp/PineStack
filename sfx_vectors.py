"""THE SFX GUY'S VECTOR SECTION - the clip and dialogue index other projects
can query, back up and carry away (docs/SFX_vector_reuse.md).

Operator, 2026-09-27: "I need the vector database / crystal being stored by
the SFX guy for dialogue and mp4 / mp3 paths to be accessible and able to be
reused ... sync and connect dialogue and relevant mp4s by lexical, semantic,
action, situation, emotional, intent, theme / topic, metaphorical similarity,
visual / style fit ... an external system to be able to connect and locate
items quickly ... backed up and quarantined, redeployed and reused in another
project if needed where pathing can be correct and all the connections are
restored ... sectioned, isolated, maintained and a direct path that can be
preserved and compressed for backup."

This module is the section. It has NO station imports: the same file runs
inside spark-agent (sfx_vectors_runtime.py wires it to the clip book, the
speech bank and the station's embedder) and on its own, from a backup, in
another project (`python sfx_vectors.py --root <dir> query "..."`).

One directory holds everything:

    <root>/sfx_vectors.sqlite3   clips, their vectors, facet tags, dialogue, FTS
    <root>/facets.json           the categorisation: one editable anchor set
                                 per facet (the description each tag is embedded from)
    <root>/manifest.json         schema, embed model, dims, the ROOTS this
                                 deployment resolves paths against, counts

Paths are stored as (root name, relative path): "samples" is the clip share
(/samples in the container), "made" the station's own clips (data/sfx),
"voice" the rendered takes (data/voice_media). Restoring a backup somewhere
else is a matter of naming the roots again in the manifest - nothing inside
the rows changes. Vectors are float32 unit vectors from nomic-embed-text
(768 dims) so similarity is a dot product; numpy is used when present and
pure Python when it is not.

How each facet is reached:

    lexical      the words in the file name, the transcript (`said`) and the
                 thumbnail tags (`seen_desc`): SQLite FTS5, bm25 ranked
    semantic     the clip's text embedded; a query's text embedded; cosine
    action, situation, emotional, intent, theme, metaphor, visual
                 ANCHORS: every tag of a facet has a short description; the
                 description is embedded once; a clip is tagged with the
                 anchors its own vector sits closest to (above a floor). The
                 anchor set is data (facets.json), so a project can widen or
                 rename the categories and re-tag without touching code.

A query mixes the three: `score = semantic + lexical + facets`, each part
reported in `why`, so a caller can see what made a clip win.
"""
from __future__ import annotations

import array
import io
import json
import math
import os
import re
import sqlite3
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = 3
DIMS = 768
EMBED_MODEL = "nomic-embed-text"
FLOOR = 0.42          # an anchor closer than this is a tag; below it is noise
TAGS_PER_FACET = 3
ANCHOR_FACETS = ("action", "situation", "emotional", "intent", "theme", "metaphor", "visual")
FACETS = ("lexical", "semantic") + ANCHOR_FACETS
_WORD = re.compile(r"[a-z][a-z']+")

try:  # numpy makes the cosine over hundreds of thousands of clips a blink
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None


# --- the default categorisation -------------------------------------------------
# Each anchor is (tag, the sentence it is embedded from). Short, concrete,
# spoken-clip flavoured: the clips are seconds of people talking, shouting,
# singing and falling over, so the descriptions say what such a clip sounds
# and looks like, not what a dictionary says.
DEFAULT_FACETS: dict[str, dict[str, Any]] = {
    "action": {"description": "what is physically happening in the clip", "anchors": [
        ("fighting", "people fighting, punching, wrestling, a brawl breaking out"),
        ("running", "someone running, chasing or being chased, sprinting away"),
        ("falling", "someone falls over, trips, slips, crashes to the ground"),
        ("dancing", "dancing, moving to music, a dance move, shaking"),
        ("eating", "eating, chewing, biting into food, a meal, drinking"),
        ("driving", "driving a car, at the wheel, traffic, a road trip"),
        ("screaming", "screaming, yelling at the top of the voice, a shriek"),
        ("laughing", "laughing hard, giggling, cracking up, hysterics"),
        ("crying", "crying, sobbing, tears, breaking down"),
        ("singing", "singing a song, a tune, humming, a performance"),
        ("cooking", "cooking, frying, a kitchen, preparing food"),
        ("arguing", "an argument, two people shouting over each other, bickering"),
        ("celebrating", "cheering, celebrating a win, applause, a toast"),
        ("sneaking", "sneaking around, hiding, whispering, tiptoeing"),
        ("explaining", "someone explaining something slowly and carefully, a lecture"),
        ("refusing", "refusing, saying no, walking away, shutting it down"),
        ("threatening", "a threat, a warning delivered with menace, intimidation"),
        ("apologising", "an apology, saying sorry, begging forgiveness"),
    ]},
    "situation": {"description": "where and in what circumstance", "anchors": [
        ("party", "at a party, a crowd having a good time, music playing"),
        ("car", "inside a car, on the road, a passenger seat, a dashboard"),
        ("kitchen", "in a kitchen or at a table with food"),
        ("stage", "on stage in front of an audience, a performance, a microphone"),
        ("classroom", "a classroom, a teacher, students, a lesson"),
        ("work", "at work, an office, a boss, a meeting, a job"),
        ("court", "in court, a judge, a trial, a lawyer, being sentenced"),
        ("phone", "on the phone, a phone call, a voicemail, a text message"),
        ("doctor", "at the doctor or the hospital, a diagnosis, medicine"),
        ("store", "in a shop or store, buying something, a cashier, a customer"),
        ("home", "at home on the couch, a living room, a bedroom, family at home"),
        ("street", "out on the street, a sidewalk, a city corner, strangers"),
        ("outdoors", "outdoors in nature, a field, a forest, a beach, weather"),
        ("night", "late at night, in the dark, a club, a bar, after hours"),
        ("crowd", "a big crowd, a stadium, a protest, a public event"),
        ("alone", "somebody alone talking to the camera, a confession, a vlog"),
        ("interview", "an interview, a podcast, a host asking a guest questions"),
        ("news", "a news broadcast, a reporter, breaking news, a press conference"),
    ]},
    "emotional": {"description": "the feeling carried by the clip", "anchors": [
        ("joy", "happy, delighted, joyful, thrilled"),
        ("anger", "angry, furious, outraged, losing their temper"),
        ("fear", "scared, terrified, panicking, dread"),
        ("sadness", "sad, heartbroken, mourning, disappointed"),
        ("surprise", "shocked, astonished, did not see it coming"),
        ("disgust", "disgusted, grossed out, revolted"),
        ("calm", "calm, relaxed, soothing, at peace"),
        ("excitement", "excited, hyped, pumped up, buzzing"),
        ("embarrassment", "embarrassed, awkward, cringing, humiliated"),
        ("pride", "proud, smug, boasting, triumphant"),
        ("boredom", "bored, unimpressed, tired of it, deadpan"),
        ("tenderness", "tender, loving, affectionate, gentle"),
        ("contempt", "contempt, sneering, looking down on someone, mocking"),
        ("anxiety", "anxious, nervous, worried, on edge"),
        ("confusion", "confused, baffled, lost, does not understand"),
        ("determination", "determined, defiant, not backing down"),
    ]},
    "intent": {"description": "what the speaker is trying to do", "anchors": [
        ("mock", "mocking someone, making fun of them, ridicule"),
        ("warn", "warning someone, telling them to stop before it is too late"),
        ("brag", "bragging, showing off, boasting about money or success"),
        ("confess", "confessing, admitting something, coming clean"),
        ("persuade", "persuading, selling, convincing someone to agree"),
        ("comfort", "comforting someone, reassuring, it will be okay"),
        ("challenge", "challenging someone, daring them, calling them out"),
        ("celebrate", "celebrating, congratulating, cheering someone on"),
        ("complain", "complaining, whining, ranting about something unfair"),
        ("flirt", "flirting, a pick-up line, being seductive"),
        ("deny", "denying it, it was not me, refusing to admit anything"),
        ("explain", "explaining how something works, teaching, instructing"),
        ("threaten", "threatening, intimidating, promising harm"),
        ("apologise", "apologising, saying sorry, asking for forgiveness"),
        ("joke", "telling a joke, a punchline, a bit, comedy"),
        ("demand", "demanding, ordering someone to do something now"),
        ("question", "asking a pointed question, interrogating, wanting answers"),
    ]},
    "theme": {"description": "what it is about", "anchors": [
        ("money", "money, being broke, rich, bills, cash, a deal"),
        ("food", "food, a meal, snacks, being hungry, a restaurant"),
        ("love", "love, romance, a relationship, a breakup, dating"),
        ("family", "family, parents, mom, dad, kids, siblings"),
        ("work", "a job, a boss, getting fired, a career, the office"),
        ("crime", "crime, police, getting arrested, stealing, prison"),
        ("politics", "politics, the government, an election, a politician"),
        ("sport", "sports, a game, a team, winning and losing, athletes"),
        ("technology", "technology, phones, computers, the internet, apps"),
        ("music", "music, a song, an artist, a concert, a beat"),
        ("religion", "religion, church, god, prayer, faith"),
        ("health", "health, sickness, the body, exercise, a diet"),
        ("school", "school, exams, homework, teachers, college"),
        ("animals", "animals, pets, a dog, a cat, wildlife"),
        ("cars", "cars, driving, engines, a crash, the road"),
        ("drugs", "drugs, drinking, being drunk or high, addiction"),
        ("death", "death, dying, a funeral, losing someone"),
        ("weather", "weather, rain, storms, heat, snow, the season"),
        ("internet", "internet culture, memes, going viral, social media, streamers"),
    ]},
    "metaphor": {"description": "the figure the moment stands for", "anchors": [
        ("falling_apart", "everything falling apart at once, a collapse, it all comes down"),
        ("going_in_circles", "going round in circles, getting nowhere, the same thing again"),
        ("hitting_a_wall", "hitting a wall, stuck, cannot go any further"),
        ("house_of_cards", "a fragile plan about to topple, a house of cards"),
        ("last_straw", "the last straw, the moment somebody finally snaps"),
        ("burning_bridges", "burning bridges, cutting people off, no way back"),
        ("eggshells", "walking on eggshells, tiptoeing around someone's temper"),
        ("sinking_ship", "a sinking ship, everyone abandoning a lost cause"),
        ("fish_out_of_water", "a fish out of water, completely out of place"),
        ("elephant_in_the_room", "the elephant in the room, the thing nobody will say"),
        ("can_of_worms", "opening a can of worms, a small question that unleashes chaos"),
        ("train_wreck", "a train wreck you cannot look away from, a disaster unfolding"),
        ("david_and_goliath", "the little guy against the giant, an underdog"),
        ("wolf_in_sheeps_clothing", "a wolf in sheep's clothing, a smiling betrayal"),
        ("calm_before_the_storm", "the calm before the storm, something bad is coming"),
        ("light_at_the_end", "light at the end of the tunnel, hope after a long struggle"),
    ]},
    "visual": {"description": "how it looks and is shot", "anchors": [
        ("dark_grainy", "dark, grainy, low light, shot at night on a phone"),
        ("bright_sunny", "bright daylight, sunny, outdoors, saturated colour"),
        ("closeup_face", "a close-up of a face talking straight into the camera"),
        ("wide_shot", "a wide shot, a whole room or street in frame, people far away"),
        ("cartoon", "a cartoon, animated, drawn characters"),
        ("black_and_white", "black and white footage, old film, a vintage look"),
        ("neon", "neon lights, a club, coloured lights, a glowing screen"),
        ("shaky_handheld", "shaky handheld phone footage, someone filming in a hurry"),
        ("slow_motion", "slow motion, a dramatic replay"),
        ("text_on_screen", "captions or text on the screen, a meme format, subtitles"),
        ("crowd_scene", "a crowd of people in the shot, a stadium, a street full"),
        ("nature", "nature, trees, water, animals, a landscape"),
        ("tv_studio", "a television studio, a talk show set, a news desk"),
        ("game_footage", "video game footage, a screen recording, a stream overlay"),
        ("stage_lights", "stage lighting, a spotlight, a concert, a performance"),
    ]},
}


# --- vectors ---------------------------------------------------------------------
def unit(vec: Iterable[float]) -> list[float]:
    v = [float(x) for x in vec]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def pack(vec: Iterable[float]) -> bytes:
    a = array.array("f", [float(x) for x in vec])
    return a.tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(bytes(blob or b""))
    return list(a)


def dot(a: Iterable[float], b: Iterable[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def fake_embedder(dims: int = DIMS) -> Callable[[list[str]], list[list[float]]]:
    """A deterministic stand-in for tests and dry runs: a text's vector is
    the sum of hashed unit vectors of its words, so texts sharing words
    sit close together. Never used on the station's own data."""
    import hashlib

    def one(text: str) -> list[float]:
        v = [0.0] * dims
        for w in _WORD.findall(str(text or "").lower()):
            h = hashlib.sha256(w.encode("utf-8")).digest()
            for i in range(0, min(len(h), 24), 3):
                v[(h[i] * 256 + h[i + 1]) % dims] += 1.0 if h[i + 2] % 2 else -1.0
        if not any(v):
            v[0] = 1.0
        return unit(v)

    return lambda texts: [one(t) for t in texts]


# --- the store ---------------------------------------------------------------------
class Store:
    """One section directory. Every method is synchronous and touches disk:
    call it from a worker, never from an event loop."""

    def __init__(self, root: Any, roots: dict[str, str] | None = None, embed_model: str = EMBED_MODEL,
                 dims: int = DIMS):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "sfx_vectors.sqlite3"
        self.facets_path = self.root / "facets.json"
        self.manifest_path = self.root / "manifest.json"
        self.con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.con.execute("pragma journal_mode=wal")
        self.con.execute("pragma synchronous=normal")
        self._schema()
        self.manifest = self._load_manifest(roots, embed_model, dims)
        self.facets = self._load_facets()
        self._matrix = None            # (sids, numpy float32 matrix) cache for the cosine
        self._matrix_n = -1

    # -- files --
    def _schema(self) -> None:
        c = self.con
        c.executescript("""
        create table if not exists clips(
            sid text primary key, root text not null, rel_path text not null, name text, folder text,
            video integer not null default 0, seconds real, said text, seen_desc text, tokens text,
            source_mtime real, updated real, embedded_at real, tagged_at real,
            aired integer not null default 0, last_aired real);
        create index if not exists clips_todo on clips(embedded_at, tagged_at);
        create index if not exists clips_root on clips(root, rel_path);
        create table if not exists clip_vec(sid text primary key, vec blob not null);
        create table if not exists facet_tags(sid text not null, facet text not null, tag text not null,
            weight real not null, how text, primary key(sid, facet, tag));
        create index if not exists facet_tags_by_tag on facet_tags(facet, tag, weight);
        create table if not exists anchor_vec(facet text not null, tag text not null, text text not null,
            vec blob not null, primary key(facet, tag));
        create table if not exists dialogue(
            id text primary key, kind text not null, who text, voice text, text text not null, about text,
            clip_sid text, root text, rel_path text, at real, updated real, embedded_at real);
        create table if not exists dialogue_vec(id text primary key, vec blob not null);
        create virtual table if not exists clips_fts using fts5(sid unindexed, name, said, seen_desc, tags,
            tokenize='porter unicode61');
        create virtual table if not exists dialogue_fts using fts5(id unindexed, text, about,
            tokenize='porter unicode61');
        """)
        c.commit()

    def _load_manifest(self, roots, embed_model, dims) -> dict[str, Any]:
        m: dict[str, Any] = {}
        if self.manifest_path.is_file():
            try:
                m = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                m = {}
        m.setdefault("schema", SCHEMA)
        m.setdefault("created", time.time())
        m.setdefault("embed_model", embed_model)
        m.setdefault("dims", int(dims))
        m.setdefault("roots", {})
        if roots:
            m["roots"].update({k: str(v) for k, v in roots.items()})
        m.setdefault("facets", list(FACETS))
        self._save_manifest(m)
        return m

    def _save_manifest(self, m: dict[str, Any] | None = None) -> None:
        m = m or self.manifest
        m["updated"] = time.time()
        m["counts"] = self.counts() if self.con else m.get("counts", {})
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    def _load_facets(self) -> dict[str, dict[str, Any]]:
        if self.facets_path.is_file():
            try:
                got = json.loads(self.facets_path.read_text(encoding="utf-8"))
                if isinstance(got, dict) and got:
                    return {k: {"description": str(v.get("description") or ""),
                                "anchors": [(str(a[0]), str(a[1])) for a in v.get("anchors") or [] if len(a) >= 2]}
                            for k, v in got.items() if isinstance(v, dict)}
            except Exception:  # noqa: BLE001
                pass
        facets = {k: {"description": v["description"], "anchors": list(v["anchors"])} for k, v in DEFAULT_FACETS.items()}
        self.save_facets(facets)
        return facets

    def save_facets(self, facets: dict[str, dict[str, Any]]) -> None:
        clean = {}
        for facet, spec in facets.items():
            anchors = [(str(a[0]).strip(), str(a[1]).strip()) for a in (spec.get("anchors") or []) if len(a) >= 2 and str(a[0]).strip()]
            if not anchors:
                continue
            clean[str(facet)] = {"description": str(spec.get("description") or ""), "anchors": anchors}
        tmp = self.facets_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
        os.replace(tmp, self.facets_path)
        self.facets = clean
        self.manifest["facets"] = list(FACETS[:2]) + [f for f in clean]

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:  # noqa: BLE001
            pass

    # -- paths --
    def split_path(self, path: Any) -> tuple[str, str]:
        """(root name, relative path) for an absolute path, by the longest
        matching root; ("other", the path itself) when none matches."""
        p = str(path or "").replace("\\", "/")
        best = ("", "")
        for name, base in (self.manifest.get("roots") or {}).items():
            b = str(base).replace("\\", "/").rstrip("/")
            if b and (p == b or p.startswith(b + "/")) and len(b) > len(best[1]):
                best = (name, b)
        if not best[0]:
            return "other", p
        return best[0], p[len(best[1]):].lstrip("/")

    def resolve(self, root: str, rel_path: str) -> str:
        base = str((self.manifest.get("roots") or {}).get(root) or "")
        if not base:
            return rel_path if root == "other" else ""
        return base.rstrip("/").rstrip("\\") + "/" + str(rel_path).lstrip("/")

    # -- clips --
    def upsert_clips(self, rows: Iterable[dict[str, Any]]) -> int:
        """rows: {sid, path (absolute), name, folder, video, seconds, said,
        seen_desc, mtime}. A row whose text changed loses its embedding and
        tags (they are made again by the keeper); an unchanged row is kept."""
        n = 0
        now = time.time()
        cur = self.con.cursor()
        for r in rows:
            sid = str(r.get("sid") or "")
            if not sid:
                continue
            root, rel = self.split_path(r.get("path"))
            name = " ".join(str(r.get("name") or Path(rel).stem).split())
            said = " ".join(str(r.get("said") or "").split())
            seen = " ".join(str(r.get("seen_desc") or "").split())
            toks = " ".join(sorted(set(_WORD.findall((name + " " + said + " " + seen).lower()))))
            old = cur.execute("select tokens, root, rel_path from clips where sid=?", (sid,)).fetchone()
            same_text = bool(old and old[0] == toks)
            cur.execute("""insert into clips(sid, root, rel_path, name, folder, video, seconds, said, seen_desc, tokens,
                                             source_mtime, updated, embedded_at, tagged_at)
                           values(?,?,?,?,?,?,?,?,?,?,?,?,null,null)
                           on conflict(sid) do update set root=excluded.root, rel_path=excluded.rel_path,
                             name=excluded.name, folder=excluded.folder, video=excluded.video, seconds=excluded.seconds,
                             said=excluded.said, seen_desc=excluded.seen_desc, tokens=excluded.tokens,
                             source_mtime=excluded.source_mtime, updated=excluded.updated,
                             embedded_at=case when ? then clips.embedded_at else null end,
                             tagged_at=case when ? then clips.tagged_at else null end""",
                        (sid, root, rel, name, str(r.get("folder") or ""), 1 if r.get("video") else 0,
                         float(r.get("seconds") or 0), said, seen, toks, float(r.get("mtime") or 0), now,
                         same_text, same_text))
            if not same_text:
                cur.execute("delete from clip_vec where sid=?", (sid,))
                # [sfx-library] a tag the operator wrote outlives a change of the words
                cur.execute("delete from facet_tags where sid=? and coalesce(how,'') <> 'operator'", (sid,))
                kept = " ".join(t for (t,) in cur.execute("select tag from facet_tags where sid=?", (sid,)))
                cur.execute("delete from clips_fts where sid=?", (sid,))
                cur.execute("insert into clips_fts(sid, name, said, seen_desc, tags) values(?,?,?,?,?)",
                            (sid, name, said, seen, kept))
                self._matrix = None
            n += 1
        self.con.commit()
        return n

    def note_aired(self, sids_at: Iterable[tuple[str, float]]) -> int:
        cur = self.con.cursor()
        n = 0
        for sid, at in sids_at:
            cur.execute("update clips set aired=aired+1, last_aired=max(coalesce(last_aired,0), ?) where sid=?",
                        (float(at or 0), str(sid)))
            n += cur.rowcount
        self.con.commit()
        return n

    def clip_text(self, row: dict[str, Any]) -> str:
        parts = [str(row.get("name") or ""), str(row.get("said") or ""), str(row.get("seen_desc") or "")]
        folder = str(row.get("folder") or "")
        return " | ".join(x for x in parts if x) + ((" | " + folder) if folder else "")

    def clips_to_embed(self, limit: int = 96) -> list[dict[str, Any]]:
        """The next clips worth a vector: aired ones first, then the wordy
        ones (a transcript or thumbnail tags), then the rest."""
        cur = self.con.execute("""select sid, name, folder, said, seen_desc from clips
                                  where embedded_at is null
                                  order by aired desc,
                                           (case when coalesce(said,'')<>'' or coalesce(seen_desc,'')<>'' then 0 else 1 end),
                                           updated desc limit ?""", (int(limit),))
        cols = ("sid", "name", "folder", "said", "seen_desc")
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def put_clip_vectors(self, sids: list[str], vecs: list[list[float]]) -> int:
        cur = self.con.cursor()
        now = time.time()
        n = 0
        for sid, vec in zip(sids, vecs):
            if not vec or len(vec) != int(self.manifest.get("dims") or DIMS):
                continue
            cur.execute("insert or replace into clip_vec(sid, vec) values(?,?)", (sid, pack(unit(vec))))
            cur.execute("update clips set embedded_at=? where sid=?", (now, sid))
            n += 1
        self.con.commit()
        self._matrix = None
        return n

    # -- anchors and tags --
    def anchors_to_embed(self) -> list[tuple[str, str, str]]:
        have = {(f, t) for f, t in self.con.execute("select facet, tag from anchor_vec")}
        out = []
        for facet, spec in self.facets.items():
            for tag, text in spec["anchors"]:
                if (facet, tag) not in have:
                    out.append((facet, tag, text))
        return out

    def put_anchor_vectors(self, triples: list[tuple[str, str, str]], vecs: list[list[float]]) -> int:
        cur = self.con.cursor()
        n = 0
        for (facet, tag, text), vec in zip(triples, vecs):
            if not vec:
                continue
            cur.execute("insert or replace into anchor_vec(facet, tag, text, vec) values(?,?,?,?)",
                        (facet, tag, text, pack(unit(vec))))
            n += 1
        self.con.commit()
        return n

    def anchors(self) -> dict[str, list[tuple[str, list[float]]]]:
        out: dict[str, list[tuple[str, list[float]]]] = {}
        for facet, tag, blob in self.con.execute("select facet, tag, vec from anchor_vec"):
            if facet in self.facets and any(tag == a[0] for a in self.facets[facet]["anchors"]):
                out.setdefault(facet, []).append((tag, unpack(blob)))
        return out

    def tag_clips(self, limit: int = 400, floor: float = FLOOR, per_facet: int = TAGS_PER_FACET) -> int:
        """Tag embedded, untagged clips against the anchors: per facet the
        closest anchors above the floor. Pure arithmetic, no model."""
        anchors = self.anchors()
        if not anchors:
            return 0
        rows = self.con.execute("""select c.sid, v.vec from clips c join clip_vec v on v.sid=c.sid
                                   where c.tagged_at is null limit ?""", (int(limit),)).fetchall()
        cur = self.con.cursor()
        now = time.time()
        n = 0
        for sid, blob in rows:
            vec = unpack(blob)
            tags: list[tuple[str, str, float]] = []
            for facet, items in anchors.items():
                scored = sorted(((dot(vec, av), tag) for tag, av in items), reverse=True)[:per_facet]
                for s, tag in scored:
                    if s >= floor:
                        tags.append((facet, tag, round(s, 4)))
            # [sfx-library] the keeper re-tags its own; the operator's tags stand
            cur.execute("delete from facet_tags where sid=? and coalesce(how,'') <> 'operator'", (sid,))
            for facet, tag, w in tags:
                cur.execute("insert into facet_tags(sid, facet, tag, weight, how) values(?,?,?,?,?) "
                            "on conflict(sid, facet, tag) do nothing",
                            (sid, facet, tag, w, "anchor cosine"))
            every = " ".join(t for (t,) in cur.execute("select tag from facet_tags where sid=?", (sid,)))
            cur.execute("update clips_fts set tags=? where sid=?", (every, sid))
            cur.execute("update clips set tagged_at=? where sid=?", (now, sid))
            n += 1
        self.con.commit()
        return n

    def retag_all(self) -> None:
        """After the anchor set changes: every clip is tagged again by the keeper."""
        self.con.execute("update clips set tagged_at=null")
        self.con.execute("delete from anchor_vec where not exists (select 1 from clips)")  # no-op guard
        self.con.commit()

    def refresh_anchors(self) -> None:
        """Anchors whose description changed are embedded again; ones no
        longer in the facets are dropped."""
        keep = {(f, a[0]): a[1] for f, spec in self.facets.items() for a in spec["anchors"]}
        cur = self.con.cursor()
        for facet, tag, text in cur.execute("select facet, tag, text from anchor_vec").fetchall():
            if (facet, tag) not in keep or keep[(facet, tag)] != text:
                cur.execute("delete from anchor_vec where facet=? and tag=?", (facet, tag))
        self.con.commit()

    # -- dialogue --
    def upsert_dialogue(self, rows: Iterable[dict[str, Any]]) -> int:
        """rows: {id, kind (take|quip|aired), who, voice, text, about, clip_sid, path, at}."""
        n = 0
        now = time.time()
        cur = self.con.cursor()
        for r in rows:
            rid = str(r.get("id") or "")
            text = " ".join(str(r.get("text") or "").split())
            if not rid or not text:
                continue
            root, rel = self.split_path(r.get("path")) if r.get("path") else ("", "")
            old = cur.execute("select text from dialogue where id=?", (rid,)).fetchone()
            same = bool(old and old[0] == text)
            cur.execute("""insert into dialogue(id, kind, who, voice, text, about, clip_sid, root, rel_path, at, updated, embedded_at)
                           values(?,?,?,?,?,?,?,?,?,?,?,null)
                           on conflict(id) do update set kind=excluded.kind, who=excluded.who, voice=excluded.voice,
                             text=excluded.text, about=excluded.about, clip_sid=excluded.clip_sid, root=excluded.root,
                             rel_path=excluded.rel_path, at=excluded.at, updated=excluded.updated,
                             embedded_at=case when ? then dialogue.embedded_at else null end""",
                        (rid, str(r.get("kind") or "take"), str(r.get("who") or ""), str(r.get("voice") or ""), text,
                         " ".join(str(r.get("about") or "").split()), str(r.get("clip_sid") or ""), root, rel,
                         float(r.get("at") or 0), now, same))
            if not same:
                cur.execute("delete from dialogue_vec where id=?", (rid,))
                cur.execute("delete from dialogue_fts where id=?", (rid,))
                cur.execute("insert into dialogue_fts(id, text, about) values(?,?,?)", (rid, text, " ".join(str(r.get("about") or "").split())))
            n += 1
        self.con.commit()
        return n

    def dialogue_to_embed(self, limit: int = 96) -> list[dict[str, Any]]:
        cur = self.con.execute("select id, text, about from dialogue where embedded_at is null order by updated desc limit ?", (int(limit),))
        return [{"id": a, "text": b, "about": c} for a, b, c in cur.fetchall()]

    def put_dialogue_vectors(self, ids: list[str], vecs: list[list[float]]) -> int:
        cur = self.con.cursor()
        now = time.time()
        n = 0
        for rid, vec in zip(ids, vecs):
            if not vec:
                continue
            cur.execute("insert or replace into dialogue_vec(id, vec) values(?,?)", (rid, pack(unit(vec))))
            cur.execute("update dialogue set embedded_at=? where id=?", (now, rid))
            n += 1
        self.con.commit()
        return n

    # -- counts --
    def counts(self) -> dict[str, int]:
        q = lambda sql: int(self.con.execute(sql).fetchone()[0])  # noqa: E731
        try:
            return {"clips": q("select count(*) from clips"), "clips_embedded": q("select count(*) from clip_vec"),
                    "clips_tagged": q("select count(*) from clips where tagged_at is not null"),
                    "tags": q("select count(*) from facet_tags"), "anchors": q("select count(*) from anchor_vec"),
                    "dialogue": q("select count(*) from dialogue"), "dialogue_embedded": q("select count(*) from dialogue_vec")}
        except Exception:  # noqa: BLE001
            return {}

    # -- search --
    def _load_matrix(self):
        n = int(self.con.execute("select count(*) from clip_vec").fetchone()[0])
        if self._matrix is not None and self._matrix_n == n:
            return self._matrix
        sids: list[str] = []
        if _np is not None:
            blobs = []
            for sid, blob in self.con.execute("select sid, vec from clip_vec"):
                sids.append(sid)
                blobs.append(blob)
            dims = int(self.manifest.get("dims") or DIMS)
            mat = (_np.frombuffer(b"".join(blobs), dtype=_np.float32).reshape(len(blobs), dims)
                   if blobs else _np.zeros((0, dims), dtype=_np.float32))
            self._matrix = (sids, mat.astype(_np.float16))
        else:
            vecs = []
            for sid, blob in self.con.execute("select sid, vec from clip_vec"):
                sids.append(sid)
                vecs.append(unpack(blob))
            self._matrix = (sids, vecs)
        self._matrix_n = n
        return self._matrix

    def semantic(self, qvec: list[float], k: int = 40, video: bool | None = None) -> list[tuple[str, float]]:
        sids, mat = self._load_matrix()
        if not sids:
            return []
        if _np is not None:
            q = _np.asarray(qvec, dtype=_np.float32)
            scores = mat.astype(_np.float32) @ q if len(sids) < 200000 else (mat @ q.astype(_np.float16)).astype(_np.float32)
            top = _np.argpartition(-scores, min(k * 3, len(sids) - 1))[:k * 3] if len(sids) > k * 3 else _np.arange(len(sids))
            got = sorted(((float(scores[i]), sids[i]) for i in top), reverse=True)
        else:
            got = sorted(((dot(qvec, v), s) for s, v in zip(sids, mat)), reverse=True)[:k * 3]
        out = []
        for s, sid in got:
            if video is not None:
                row = self.con.execute("select video from clips where sid=?", (sid,)).fetchone()
                if row is None or bool(row[0]) != bool(video):
                    continue
            out.append((sid, s))
            if len(out) >= k:
                break
        return out

    def lexical(self, text: str, k: int = 40) -> list[tuple[str, float]]:
        words = [w for w in _WORD.findall(str(text or "").lower()) if len(w) > 2]
        if not words:
            return []
        q = " OR ".join('"%s"' % w.replace('"', "") for w in dict.fromkeys(words))
        try:
            rows = self.con.execute("select sid, bm25(clips_fts) from clips_fts where clips_fts match ? order by bm25(clips_fts) limit ?",
                                    (q, int(k))).fetchall()
        except sqlite3.OperationalError:
            return []
        if not rows:
            return []
        worst = max(abs(float(r[1])) for r in rows) or 1.0
        return [(str(r[0]), min(1.0, abs(float(r[1])) / worst)) for r in rows]

    def tags_for_query(self, qvec: list[float], per_facet: int = 2, floor: float = FLOOR) -> dict[str, list[tuple[str, float]]]:
        """The anchors a query text sits closest to: what a caller's words
        mean in this categorisation (its mood, its intent, its situation)."""
        out: dict[str, list[tuple[str, float]]] = {}
        for facet, items in self.anchors().items():
            scored = sorted(((dot(qvec, av), tag) for tag, av in items), reverse=True)[:per_facet]
            hits = [(tag, round(s, 4)) for s, tag in scored if s >= floor]
            if hits:
                out[facet] = hits
        return out

    def query(self, text: str = "", embed: Callable[[list[str]], list[list[float]]] | None = None,
              facets: dict[str, list[str]] | None = None, video: bool | None = None, k: int = 12,
              weights: dict[str, float] | None = None, max_seconds: float = 0.0) -> dict[str, Any]:
        """Recommendations for words (any of: a line just said, a mood, an
        intent, a theme, a situation), with the path each resolves to here
        and why it won. `facets` narrows or boosts by tag, e.g.
        {"emotional": ["anger"], "visual": ["closeup_face"]}."""
        w = {"semantic": 1.0, "lexical": 0.6, "facet": 0.5, "aired": 0.05}
        w.update(weights or {})
        text = " ".join(str(text or "").split())
        scores: dict[str, dict[str, float]] = {}
        qtags: dict[str, list[tuple[str, float]]] = {}
        qvec: list[float] = []
        if text and embed is not None:
            try:
                got = embed([text])
                qvec = unit(got[0]) if got and got[0] else []
            except Exception:  # noqa: BLE001
                qvec = []
        if qvec:
            for sid, s in self.semantic(qvec, k=max(k * 4, 40), video=video):
                scores.setdefault(sid, {})["semantic"] = s
            qtags = self.tags_for_query(qvec)
        if text:
            for sid, s in self.lexical(text, k=max(k * 4, 40)):
                scores.setdefault(sid, {})["lexical"] = s
        want_tags: dict[str, set[str]] = {f: set(t) for f, t in (facets or {}).items() if t}
        for facet, hits in qtags.items():
            want_tags.setdefault(facet, set()).update(t for t, _s in hits)
        if want_tags and not scores:
            # tags alone: the clips carrying the asked tags
            for facet, tags in want_tags.items():
                for tag in tags:
                    for sid, wgt in self.con.execute("select sid, weight from facet_tags where facet=? and tag=? order by weight desc limit ?",
                                                     (facet, tag, int(k * 8))):
                        scores.setdefault(sid, {})["facet"] = scores.get(sid, {}).get("facet", 0.0) + float(wgt)
        elif want_tags:
            for sid in list(scores):
                got = 0.0
                for facet, tag, wgt in self.con.execute("select facet, tag, weight from facet_tags where sid=?", (sid,)):
                    if tag in want_tags.get(facet, ()):
                        got += float(wgt)
                if got:
                    scores[sid]["facet"] = got
            if facets:   # an explicit filter: a clip missing every asked tag is out
                asked = {(f, t) for f, ts in facets.items() for t in ts}
                for sid in list(scores):
                    have = {(f, t) for f, t, _w in self.con.execute("select facet, tag, weight from facet_tags where sid=?", (sid,))}
                    if not (have & asked):
                        scores.pop(sid, None)
        out = []
        for sid, parts in scores.items():
            row = self.con.execute("select root, rel_path, name, folder, video, seconds, said, seen_desc, aired from clips where sid=?", (sid,)).fetchone()
            if not row:
                continue
            root, rel, name, folder, is_video, seconds, said, seen, aired = row
            if video is not None and bool(is_video) != bool(video):
                continue
            if max_seconds and float(seconds or 0) > max_seconds:
                continue
            total = sum(w.get(kind, 0.0) * val for kind, val in parts.items()) + w["aired"] * min(5, int(aired or 0))
            tags = {}
            for facet, tag, wgt in self.con.execute("select facet, tag, weight from facet_tags where sid=? order by weight desc", (sid,)):
                tags.setdefault(facet, []).append([tag, round(float(wgt), 3)])
            out.append({"sid": sid, "score": round(total, 4), "why": {kk: round(v, 4) for kk, v in parts.items()},
                        "path": self.resolve(root, rel), "root": root, "rel_path": rel, "name": name, "folder": folder,
                        "video": bool(is_video), "seconds": round(float(seconds or 0), 2), "aired": int(aired or 0),
                        "said": (said or "")[:300], "seen_desc": (seen or "")[:200], "facets": tags})
        out.sort(key=lambda r: -r["score"])
        return {"query": text, "asked": {"facets": facets or {}, "video": video, "k": k, "max_seconds": max_seconds},
                "query_tags": {f: [[t, s] for t, s in hits] for f, hits in qtags.items()},
                "embedded": bool(qvec), "results": out[:k], "considered": len(scores),
                "counts": self.counts(), "roots": dict(self.manifest.get("roots") or {})}

    def clip(self, sid: str) -> dict[str, Any] | None:
        row = self.con.execute("select root, rel_path, name, folder, video, seconds, said, seen_desc, aired, last_aired, embedded_at, tagged_at from clips where sid=?", (sid,)).fetchone()
        if not row:
            return None
        root, rel, name, folder, is_video, seconds, said, seen, aired, last_aired, emb, tagged = row
        tags = {}
        for facet, tag, wgt in self.con.execute("select facet, tag, weight from facet_tags where sid=? order by weight desc", (sid,)):
            tags.setdefault(facet, []).append([tag, round(float(wgt), 3)])
        lines = [{"id": i, "kind": kd, "who": who, "text": t} for i, kd, who, t in
                 self.con.execute("select id, kind, who, text from dialogue where clip_sid=? limit 20", (sid,))]
        return {"sid": sid, "path": self.resolve(root, rel), "root": root, "rel_path": rel, "name": name, "folder": folder,
                "video": bool(is_video), "seconds": seconds, "said": said, "seen_desc": seen, "aired": aired,
                "last_aired": last_aired, "embedded": bool(emb), "tagged": bool(tagged), "facets": tags, "dialogue": lines}

    # -- backup, quarantine, restore --
    def backup(self, dest_dir: Any, label: str = "backup", extra_files: dict[str, bytes] | None = None) -> Path:
        """One compressed tarball holding the whole section: a consistent
        copy of the database (VACUUM INTO), facets.json, manifest.json and
        any extra files the caller adds (the crystal exports). A backup
        labelled `quarantine` is the same file kept apart: the keeper never
        reads or writes a backup."""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        name = "sfx_vectors-%s-%s.tar.gz" % (label, stamp)
        out = dest / name
        snap = self.root / ("snapshot-%s.sqlite3" % stamp)
        self.con.execute("pragma wal_checkpoint(TRUNCATE)")
        self.con.execute("vacuum into ?", (str(snap),))
        self._save_manifest()
        try:
            with tarfile.open(str(out), "w:gz") as tar:
                tar.add(str(snap), arcname="sfx_vectors/sfx_vectors.sqlite3")
                tar.add(str(self.facets_path), arcname="sfx_vectors/facets.json")
                tar.add(str(self.manifest_path), arcname="sfx_vectors/manifest.json")
                for rel, data in (extra_files or {}).items():
                    info = tarfile.TarInfo("sfx_vectors/" + str(rel).lstrip("/"))
                    info.size = len(data)
                    info.mtime = int(time.time())
                    tar.addfile(info, io.BytesIO(data))
        finally:
            try:
                snap.unlink()
            except OSError:
                pass
        return out

    @staticmethod
    def restore(tarball: Any, root: Any, roots: dict[str, str] | None = None) -> "Store":
        """Unpack a backup into `root` (which must be empty or absent) and
        name the roots this deployment resolves paths against. Everything
        else - vectors, tags, dialogue, the connections between them -
        comes back untouched."""
        root = Path(root)
        if root.exists() and any(root.iterdir()):
            raise ValueError("restore into an empty directory: %s is not empty" % root)
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(tarball), "r:gz") as tar:
            for member in tar.getmembers():
                target = member.name
                if not target.startswith("sfx_vectors/") or ".." in target:
                    continue
                member.name = target[len("sfx_vectors/"):]
                if not member.name:
                    continue
                tar.extract(member, path=str(root))
        store = Store(root, roots=roots)
        store.manifest["restored_from"] = str(Path(tarball).name)
        store.manifest["restored_at"] = time.time()
        store._save_manifest()
        return store


# --- standalone use ----------------------------------------------------------------
def ollama_embedder(url: str = "http://127.0.0.1:11434", model: str = EMBED_MODEL) -> Callable[[list[str]], list[list[float]]]:
    """The same embedder the station uses, for a project that has Ollama
    and nomic-embed-text but not spark-agent."""
    import urllib.request

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), 48):
            part = texts[start:start + 48]
            body = json.dumps({"model": model, "input": part}).encode("utf-8")
            req = urllib.request.Request(url.rstrip("/") + "/api/embed", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                got = json.loads(r.read().decode("utf-8"))
            out.extend(unit(v) for v in got.get("embeddings") or [])
        return out

    return embed


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="the SFX Guy's vector section, on its own")
    ap.add_argument("--root", default="sfx_vectors", help="the section directory")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--fake-embed", action="store_true", help="a deterministic stand-in embedder (tests, dry runs)")
    sub = ap.add_subparsers(dest="cmd")
    q = sub.add_parser("query"); q.add_argument("text"); q.add_argument("-k", type=int, default=10)
    q.add_argument("--video", choices=["yes", "no"]); q.add_argument("--facet", action="append", default=[], help="facet:tag, repeatable")
    sub.add_parser("manifest")
    sub.add_parser("facets")
    b = sub.add_parser("backup"); b.add_argument("dest"); b.add_argument("--label", default="backup")
    r = sub.add_parser("restore"); r.add_argument("tarball"); r.add_argument("--into", required=True)
    r.add_argument("--root-map", action="append", default=[], help="name=/absolute/path, repeatable")
    c = sub.add_parser("clip"); c.add_argument("sid")
    t = sub.add_parser("tag"); t.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args(argv)
    if args.cmd == "restore":
        roots = dict(kv.split("=", 1) for kv in args.root_map if "=" in kv)
        st = Store.restore(args.tarball, args.into, roots=roots)
        print(json.dumps({"restored": str(st.root), "roots": st.manifest.get("roots"), "counts": st.counts()}, indent=1))
        return 0
    st = Store(args.root)
    embed = fake_embedder() if args.fake_embed else ollama_embedder(args.ollama, st.manifest.get("embed_model") or EMBED_MODEL)
    if args.cmd == "query":
        facets: dict[str, list[str]] = {}
        for f in args.facet:
            if ":" in f:
                a, b_ = f.split(":", 1)
                facets.setdefault(a, []).append(b_)
        video = None if not args.video else (args.video == "yes")
        print(json.dumps(st.query(args.text, embed=embed, facets=facets or None, video=video, k=args.k), indent=1))
    elif args.cmd == "manifest":
        st._save_manifest()
        print(json.dumps(st.manifest, indent=1, sort_keys=True))
    elif args.cmd == "facets":
        print(json.dumps(st.facets, indent=1))
    elif args.cmd == "backup":
        print(st.backup(args.dest, label=args.label))
    elif args.cmd == "clip":
        print(json.dumps(st.clip(args.sid), indent=1))
    elif args.cmd == "tag":
        todo = st.anchors_to_embed()
        if todo:
            st.put_anchor_vectors(todo, embed([t[2] for t in todo]))
        print({"tagged": st.tag_clips(limit=args.limit)})
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
