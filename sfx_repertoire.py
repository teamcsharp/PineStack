"""[sfxreact] THE SFX GUY'S REACTION REPERTOIRE - his own database of clips he
knows are reactions (gasp, boo, record scratch, "what?!", uproar, sad trombone,
cringe, laugh, fail, victory, rimshot, crickets - the same topics SFXREACT1
rolls), each with a confidence, its source and the tagger's reasons.

The operator, 2026-09-29: "let's have him categorizing that in his database so
he knows and has a quick repertoire of sfx reactions that expands with time. A
lot of clips are perfect for reactions that are random video game moments and
micro moments. If I upvote a clip, have him internalize that for usage with
reactions if it is marked as such, and in general."

- A cheap classifier (no model): the filename and folder, the transcript words
  (`said`), the length (micro moments under ~3 s are strong candidates), an
  optional loudness/onset probe, and video-game-sounding folders or names.
- It grows: clips are tagged as they air, as the clip search finds them for a
  reaction, and by a slow backfill over data/sfx_clips.db (a cursor, a cap).
- Votes teach it: an upvote weighs a clip up (x1.6 a vote, at most x4), a
  downvote down (x0.35 a vote); the operator's "mark as reaction" files it
  under a category at full confidence, and a marked + upvoted clip is the
  strongest candidate there is.
- The shortlist is one indexed query per roll: the reaction roll picks from a
  ready list instead of searching 390,000 clips.

Its own file (data/sfxguy_reactions.db), WAL, one lock; never touches
sfx_clips.db except to READ the backfill batch.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import subprocess
import threading
import time
from typing import Any, Callable, Iterable

CATEGORIES = ("gasp", "boo", "record_scratch", "what", "uproar", "sad_trombone", "cringe", "laugh", "fail",
              "victory", "rimshot", "crickets")

# words that file a clip under a category, by where they are found
KEYWORDS = {
    "gasp": ["gasp", "gasps", "oh my god", "omg", "oh my gosh", "oh no", "shocked", "no way", "whoa", "woah",
             "holy", "surprise", "surprised", "jaw drop"],
    "boo": ["boo", "booing", "boos", "hiss", "jeer", "jeers", "heckle"],
    "record_scratch": ["record scratch", "scratch", "scratches", "vinyl", "needle", "rewind", "freeze frame"],
    "what": ["what", "wait what", "huh", "excuse me", "say what", "are you serious", "wtf", "what the",
             "come again", "you what"],
    "uproar": ["crowd", "uproar", "riot", "audience", "chaos", "screaming", "outrage", "mob", "stadium"],
    "sad_trombone": ["trombone", "wah wah", "womp", "sad", "sad horn", "price is right lose"],
    "cringe": ["cringe", "awkward", "yikes", "oof", "eww", "ew", "gross", "disgusting", "nope"],
    "laugh": ["laugh", "laughing", "laughs", "haha", "hahaha", "lol", "giggle", "chuckle", "laugh track",
              "sitcom", "lmao"],
    "fail": ["fail", "failed", "game over", "you died", "wasted", "error", "buzzer", "wrong", "mission failed",
             "death sound", "oof", "dead", "bruh"],
    "victory": ["victory", "win", "winner", "level up", "achievement", "fanfare", "mission complete",
                "you win", "applause", "tada", "ta da", "success", "coin"],
    "rimshot": ["rimshot", "ba dum", "badum", "ba dum tss", "drum roll", "drumroll", "snare hit"],
    "crickets": ["crickets", "cricket", "silence", "tumbleweed", "dead air"],
}
GAME = re.compile(r"\b(game|gaming|gamer|arcade|8[- ]?bit|16[- ]?bit|retro|nintendo|mario|zelda|sonic|pac-?man|"
                  r"minecraft|fortnite|roblox|gta|dark souls|elden|pokemon|sega|atari|metal gear|halo|doom|"
                  r"street fighter|mortal kombat|tetris|smash|sfx|meme|memes)\b", re.I)
GAME_LEAN = {"fail": 0.18, "victory": 0.18, "what": 0.08, "gasp": 0.06, "record_scratch": 0.05}
# everyday words that only mean a reaction when they are (nearly) all the clip is
SHORT_ONLY = frozenset({"what", "dead", "win", "coin", "sad", "holy", "wrong", "error", "huh", "nope", "ew",
                        "oof", "success", "crowd", "audience", "silence", "scratch", "drum roll", "surprise"})

MIN_CONF = 0.35
MARK_CONF = 1.0


def _norm(text: Any) -> str:
    s = str(text or "").lower()
    s = re.sub(r"[_\-.]+", " ", s)
    s = re.sub(r"^\d+\s+", "", s)                  # the grab folder's running numbers
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", s).split())


def _has(hay: str, word: str) -> bool:
    return re.search(r"(?:^| )" + re.escape(word) + r"(?: |$)", hay) is not None


def classify(name: Any = "", folder: Any = "", said: Any = "", seconds: Any = None, video: Any = None,
             loud: dict[str, Any] | None = None) -> list[tuple[str, float, list[str]]]:
    """[(category, confidence, reasons)] for one clip, best first. Pure."""
    nm, fd, sd = _norm(name), _norm(folder), _norm(said)
    short_nm, short_sd = len(nm.split()) <= 3, len(sd.split()) <= 3
    try:
        secs = float(seconds) if seconds is not None else None
    except (TypeError, ValueError):
        secs = None
    if secs is not None and secs > 20:
        return []
    out: dict[str, tuple[float, list[str]]] = {}
    for cat, words in KEYWORDS.items():
        conf, why = 0.0, []
        for w in words:
            if w in SHORT_ONLY and not short_nm and not (sd and short_sd and _has(sd, w)):
                continue
            if _has(nm, w) or _has(fd, w):
                conf = conf + 0.1 if conf else (0.55 if len(nm.split()) <= 4 else 0.45)
                why.append("named \"%s\"" % w)
            elif sd and (_has(" ".join(sd.split()[:4]), w) or (len(sd.split()) <= 8 and _has(sd, w))):
                conf = conf + 0.1 if conf else 0.45        # a transcript hit counts at its start, or in a short one
                why.append("says \"%s\"" % w)
        if conf:
            out[cat] = (min(0.95, conf), why[:4])
    gamey = bool(GAME.search(" ".join((str(name or ""), str(folder or "")))))
    if gamey:
        for cat, lean in GAME_LEAN.items():
            conf, why = out.get(cat, (0.0, []))
            if conf or cat in ("fail", "victory"):
                out[cat] = (min(0.95, (conf or 0.2) + lean), why + ["a video-game moment"])
    if secs is not None:
        for cat in list(out):
            conf, why = out[cat]
            if secs < 3.0:
                out[cat] = (min(0.97, conf + 0.15), why + ["a micro moment (%.1f s)" % secs])
            elif secs < 6.0:
                out[cat] = (min(0.95, conf + 0.05), why + ["short (%.1f s)" % secs])
            elif secs > 12.0:
                out[cat] = (conf - 0.3, why + ["long for a reaction (%.0f s)" % secs])
    if isinstance(loud, dict) and loud.get("crest") is not None:
        try:
            crest, onset = float(loud.get("crest") or 0), float(loud.get("onset_ms") or 9999)
            if crest >= 12 and onset <= 200:
                for cat in ("gasp", "record_scratch", "rimshot", "what", "fail"):
                    if cat in out:
                        conf, why = out[cat]
                        out[cat] = (min(0.97, conf + 0.08), why + ["a hard onset (crest %.0f dB)" % crest])
        except (TypeError, ValueError):
            pass
    rows = [(c, round(v[0], 3), v[1]) for c, v in out.items() if v[0] >= MIN_CONF]
    rows.sort(key=lambda r: -r[1])
    return rows


def loud_probe(path: str, ffmpeg: str = "ffmpeg", timeout: float = 6.0) -> dict[str, Any] | None:
    """The first 3 s of a clip: its peak-to-RMS crest (dB) and when it first
    gets loud (ms). One ffmpeg, niced, bounded; None when it cannot say."""
    try:
        cmd = ["nice", "-n", "15", ffmpeg, "-hide_banner", "-nostats", "-t", "3", "-i", str(path), "-vn",
               "-af", "astats=metadata=1:reset=0,silencedetect=n=-35dB:d=0.05", "-f", "null", "-"]
        got = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        err = got.stderr or ""
        pk = re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", err)
        rms = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", err)
        if not pk or not rms or "inf" in (pk[-1] + rms[-1]):
            return None
        ends = re.findall(r"silence_end:\s*([\d.]+)", err)
        onset = float(ends[0]) * 1000.0 if ends else 0.0
        return {"crest": round(float(pk[-1]) - float(rms[-1]), 1), "onset_ms": round(onset, 0)}
    except Exception:  # noqa: BLE001
        return None


class Repertoire:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS clips(sid TEXT PRIMARY KEY, path TEXT, name TEXT, folder TEXT, seconds REAL,
        video INTEGER NOT NULL DEFAULT 0, said TEXT, tagged_at REAL, source TEXT, plays INTEGER NOT NULL DEFAULT 0,
        last_play REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS tags(sid TEXT NOT NULL, category TEXT NOT NULL, conf REAL NOT NULL,
        source TEXT NOT NULL, reasons TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(sid, category, source));
    CREATE INDEX IF NOT EXISTS tags_cat ON tags(category, conf);
    CREATE TABLE IF NOT EXISTS votes(sid TEXT PRIMARY KEY, up INTEGER NOT NULL DEFAULT 0,
        down INTEGER NOT NULL DEFAULT 0, marked TEXT NOT NULL DEFAULT '', at REAL NOT NULL, line_id TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """

    def __init__(self, path: str):
        self.path = str(path)
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(self.SCHEMA)
        self.db.commit()

    # --- writing ---------------------------------------------------------------
    def _meta(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _meta_set(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, json.dumps(value)))

    def note_clip(self, sid: str, path: str = "", name: str = "", folder: str = "", seconds: Any = None,
                  video: Any = None, said: str = "", source: str = "air", loud: dict[str, Any] | None = None,
                  extra: Iterable[tuple[str, float, list[str]]] = ()) -> list[tuple[str, float, list[str]]]:
        """Classify one clip and file it (its tags from `source` replace that
        source's earlier tags). Returns what it was filed under."""
        sid = str(sid or "")
        if not sid:
            return []
        rows = classify(name or os.path.splitext(os.path.basename(str(path or "")))[0],
                        folder or os.path.basename(os.path.dirname(str(path or ""))), said, seconds, video, loud)
        rows = list(rows) + [r for r in extra or () if r and r[0] in CATEGORIES]
        now = time.time()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO clips(sid,path,name,folder,seconds,video,said,tagged_at,source) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(sid) DO UPDATE SET path=COALESCE(NULLIF(excluded.path,''),path), "
                "name=COALESCE(NULLIF(excluded.name,''),name), folder=COALESCE(NULLIF(excluded.folder,''),folder), "
                "seconds=COALESCE(excluded.seconds,seconds), video=excluded.video, "
                "said=COALESCE(NULLIF(excluded.said,''),said), tagged_at=excluded.tagged_at",
                (sid, str(path or ""), str(name or ""), str(folder or ""),
                 float(seconds) if seconds is not None else None, 1 if video else 0, str(said or "")[:400], now,
                 source))
            self.db.execute("DELETE FROM tags WHERE sid=? AND source=?", (sid, source))
            self.db.executemany("INSERT OR REPLACE INTO tags(sid,category,conf,source,reasons,at) VALUES(?,?,?,?,?,?)",
                                [(sid, c, float(v), source, json.dumps(w), now) for c, v, w in rows])
        return rows

    def vote(self, sid: str, vote: str, line_id: str = "", path: str = "", name: str = "",
             seconds: Any = None, video: Any = None) -> dict[str, Any]:
        """up / down / none (none takes the last vote back)."""
        sid = str(sid or "")
        if not sid:
            return {"ok": False, "why": "no clip"}
        now = time.time()
        with self.lock, self.db:
            if path or name:
                self.db.execute("INSERT OR IGNORE INTO clips(sid,path,name,seconds,video,tagged_at,source) "
                                "VALUES(?,?,?,?,?,?,?)", (sid, str(path or ""), str(name or ""),
                                                          float(seconds) if seconds is not None else None,
                                                          1 if video else 0, now, "vote"))
            row = self.db.execute("SELECT up, down, marked FROM votes WHERE sid=?", (sid,)).fetchone()
            up, down, marked = (row or (0, 0, ""))
            if vote == "up":
                up, down = up + 1, max(0, down - 1) if down else 0
            elif vote == "down":
                down, up = down + 1, max(0, up - 1) if up else 0
            elif vote == "none":
                up, down = max(0, up - 1), max(0, down - 1)
            self.db.execute("INSERT OR REPLACE INTO votes(sid,up,down,marked,at,line_id) VALUES(?,?,?,?,?,?)",
                            (sid, int(up), int(down), str(marked or ""), now, str(line_id or "")))
        return {"ok": True, "sid": sid, "up": up, "down": down, "marked": marked,
                "factor": round(self.vote_factor(up, down), 3)}

    def mark(self, sid: str, category: str, path: str = "", name: str = "", seconds: Any = None,
             video: Any = None, line_id: str = "") -> dict[str, Any]:
        """The operator files a clip as a reaction ('' un-files it)."""
        sid, category = str(sid or ""), str(category or "")
        if category and category not in CATEGORIES:
            return {"ok": False, "why": "category must be one of " + ", ".join(CATEGORIES)}
        now = time.time()
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO clips(sid,path,name,seconds,video,tagged_at,source) "
                            "VALUES(?,?,?,?,?,?,?)", (sid, str(path or ""), str(name or ""),
                                                      float(seconds) if seconds is not None else None,
                                                      1 if video else 0, now, "operator"))
            row = self.db.execute("SELECT up, down FROM votes WHERE sid=?", (sid,)).fetchone()
            up, down = (row or (0, 0))
            self.db.execute("INSERT OR REPLACE INTO votes(sid,up,down,marked,at,line_id) VALUES(?,?,?,?,?,?)",
                            (sid, int(up), int(down), category, now, str(line_id or "")))
            self.db.execute("DELETE FROM tags WHERE sid=? AND source='operator'", (sid,))
            if category:
                self.db.execute("INSERT OR REPLACE INTO tags(sid,category,conf,source,reasons,at) VALUES(?,?,?,?,?,?)",
                                (sid, category, MARK_CONF, "operator", json.dumps(["you marked it as a reaction"]), now))
        return {"ok": True, "sid": sid, "marked": category, "up": up, "down": down}

    def played(self, sid: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE clips SET plays=plays+1, last_play=? WHERE sid=?", (time.time(), str(sid or "")))

    # --- reading ---------------------------------------------------------------
    @staticmethod
    def vote_factor(up: int, down: int) -> float:
        return min(4.0, 1.0 + 0.6 * max(0, int(up or 0))) * (0.35 ** max(0, int(down or 0)))

    def of(self, sid: str) -> dict[str, Any]:
        with self.lock:
            c = self.db.execute("SELECT path,name,folder,seconds,video,plays FROM clips WHERE sid=?", (sid,)).fetchone()
            v = self.db.execute("SELECT up,down,marked FROM votes WHERE sid=?", (sid,)).fetchone()
            t = self.db.execute("SELECT category,conf,source,reasons FROM tags WHERE sid=? ORDER BY conf DESC",
                                (sid,)).fetchall()
        return {"sid": sid, "clip": dict(zip(("path", "name", "folder", "seconds", "video", "plays"), c)) if c else None,
                "votes": dict(zip(("up", "down", "marked"), v)) if v else {"up": 0, "down": 0, "marked": ""},
                "tags": [{"category": a, "conf": b, "source": s, "reasons": json.loads(r)} for a, b, s, r in t]}

    def shortlist(self, category: str, most: int = 24, video_only: bool = False, max_seconds: float = 0.0,
                  used: Callable[[str], bool] | None = None, refused: Callable[[str], str] | None = None,
                  now: float | None = None) -> list[dict[str, Any]]:
        """His ready list for one reaction: [{sid, path, name, seconds, video,
        weight, conf, source, why}], weighted by fit x votes x freshness, the
        day's heard clips struck (`used`), and anything the station's filter
        refuses (`refused` returns the rule, "" when it may air)."""
        now = float(now or time.time())
        sql = ("SELECT t.sid, MAX(t.conf), GROUP_CONCAT(t.source), c.path, c.name, c.seconds, c.video, c.plays, "
               "c.last_play, COALESCE(v.up,0), COALESCE(v.down,0), COALESCE(v.marked,''), "
               "(SELECT reasons FROM tags x WHERE x.sid=t.sid AND x.category=t.category ORDER BY conf DESC LIMIT 1) "
               "FROM tags t JOIN clips c ON c.sid=t.sid LEFT JOIN votes v ON v.sid=t.sid "
               "WHERE t.category=? AND c.path != ''")
        args: list[Any] = [category]
        if video_only:
            sql += " AND c.video=1"
        if max_seconds:
            sql += " AND (c.seconds IS NULL OR c.seconds <= ?)"
            args.append(float(max_seconds))
        sql += " GROUP BY t.sid ORDER BY MAX(t.conf) DESC LIMIT ?"
        args.append(max(10, int(most) * 6))
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        out = []
        for sid, conf, sources, path, name, secs, vid, plays, last, up, down, marked, reasons in rows:
            if used is not None and used(sid):
                continue
            if refused is not None:
                why = refused(path)
                if why:
                    continue
            f_vote = self.vote_factor(up, down)
            f_mark = 3.0 if marked == category else 1.0
            age = (now - float(last or 0)) / 3600.0 if last else 1e6
            f_fresh = 1.0 if age > 72 else max(0.3, 1.0 - 0.5 * math.exp(-age / 24.0) - 0.05 * min(6, int(plays or 0)))
            w = float(conf) ** 2 * f_vote * f_mark * f_fresh          # the better fit dominates the draw
            if w <= 0:
                continue
            src = "your mark" if marked == category else ("your upvotes" if up else str(sources or "").split(",")[0])
            why = []
            try:
                why = list(json.loads(reasons or "[]"))[:3]
            except (TypeError, ValueError):
                why = []
            if up:
                why.append("upvoted x%.1f" % f_vote)
            if down:
                why.append("downvoted x%.2f" % f_vote)
            if marked == category:
                why.append("marked %s x3" % category)
            out.append({"sid": sid, "path": path, "name": name or os.path.basename(str(path)), "seconds": secs,
                        "video": bool(vid), "weight": round(w, 4), "conf": conf, "source": src, "why": why})
        out.sort(key=lambda r: -r["weight"])
        return out[:max(1, int(most))]

    def stats(self) -> dict[str, Any]:
        with self.lock:
            by_cat = dict(self.db.execute("SELECT category, COUNT(DISTINCT sid) FROM tags GROUP BY category").fetchall())
            by_src = dict(self.db.execute("SELECT source, COUNT(DISTINCT sid) FROM tags GROUP BY source").fetchall())
            clips = self.db.execute("SELECT COUNT(DISTINCT sid) FROM tags").fetchone()[0]
            video = self.db.execute("SELECT COUNT(DISTINCT t.sid) FROM tags t JOIN clips c ON c.sid=t.sid "
                                    "WHERE c.video=1").fetchone()[0]
            micro = self.db.execute("SELECT COUNT(DISTINCT t.sid) FROM tags t JOIN clips c ON c.sid=t.sid "
                                    "WHERE c.seconds < 3").fetchone()[0]
            up = self.db.execute("SELECT COUNT(*) FROM votes WHERE up > 0").fetchone()[0]
            down = self.db.execute("SELECT COUNT(*) FROM votes WHERE down > 0").fetchone()[0]
            marked = self.db.execute("SELECT COUNT(*) FROM votes WHERE marked != ''").fetchone()[0]
            from_up = self.db.execute("SELECT COUNT(DISTINCT t.sid) FROM tags t JOIN votes v ON v.sid=t.sid "
                                      "WHERE v.up > 0").fetchone()[0]
            cursor = self._meta("backfill_rowid", 0)
            scanned = self._meta("backfill_scanned", 0)
        return {"clips": clips, "video": video, "micro": micro, "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
                "by_source": by_src, "upvoted": up, "downvoted": down, "marked": marked,
                "reactions_from_upvotes": from_up, "backfill": {"rowid": cursor, "scanned": scanned}}

    # --- the slow backfill -----------------------------------------------------------
    def backfill(self, clips_db: str, cap: int = 200, probe: Callable[[str], Any] | None = None,
                 stop: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Read the next batch of the clip book after the remembered rowid and
        file whatever classifies. At most `cap` clips READ; `probe` (the
        loudness probe) only for micro clips that already classified."""
        t0 = time.perf_counter()
        with self.lock:
            cursor = int(self._meta("backfill_rowid", 0) or 0)
        try:
            src = sqlite3.connect("file:%s?mode=ro" % clips_db, uri=True, timeout=5)
            rows = src.execute("SELECT rowid, path, sid, name, folder, video, seconds, said FROM clips "
                               "WHERE rowid > ? AND playable=1 ORDER BY rowid LIMIT ?", (cursor, int(cap))).fetchall()
            top = src.execute("SELECT MAX(rowid) FROM clips").fetchone()[0] or 0
            src.close()
        except sqlite3.Error as exc:
            return {"ok": False, "why": "the clip book could not be read: %s" % exc}
        filed, probed = 0, 0
        last = cursor
        for rowid, path, sid, name, folder, video, secs, said in rows:
            if stop is not None and stop():
                break
            last = rowid
            got = classify(name, folder, said, secs, video)
            if not got:
                continue
            loud = None
            if probe is not None and secs is not None and float(secs) < 3.0:
                loud = probe(path)
                probed += 1
            self.note_clip(sid, path, name, folder, secs, video, said or "", source="backfill", loud=loud)
            filed += 1
        wrapped = False
        if len(rows) < int(cap) and last >= top:
            last, wrapped = 0, True                     # round again later: new clips land at the end
        with self.lock, self.db:
            self._meta_set("backfill_rowid", int(last))
            self._meta_set("backfill_scanned", int(self._meta("backfill_scanned", 0) or 0) + len(rows))
        return {"ok": True, "read": len(rows), "filed": filed, "probed": probed, "cursor": last, "wrapped": wrapped,
                "ms": round((time.perf_counter() - t0) * 1000.0, 1)}

    def close(self) -> None:
        with self.lock:
            self.db.close()
