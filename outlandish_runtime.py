"""[outlandish] The meter, the audit log, the dispute and the SFX Guy's reaction,
wired into the station (installed by app.py after System 3; every hook the
station calls is reached through globals().get(), so a failed install leaves
the air exactly as it was).

Hooks it exports into the station's namespace:
  outlandish_note_row(row)            the air log's writer thread: every sounded row
  outlandish_react_clip(text, who, meta, road) -> Path|None   the round's assembly loop
  outlandish_react_between(e, track)  a chapter: after the opener, before the reply
  outlandish_prime_chapter(stamp, opening)  a line's exchange: the reply rows re-rolled
                                      with the dispute odds once the opener's words are known
  outlandish_hold_roll(reason)        the pipeline is behind: HOLDBANTER1's aside
  outlandish_measure(text)            the reading, cached
Routes:
  GET  /api/outlandish?hours=&min=&format=json|csv&limit=   the review list (+ export)
  GET  /api/outlandish/line/{line_id}  one line's reading and its reaction
  POST /api/outlandish/score {text}    read-only: what the meter makes of any words
  GET  /api/sfxguy/reactions           his repertoire: sizes, recent reactions
  GET  /api/sfxguy/reactions/shortlist?category=
  POST /api/sfxguy/reactions/mark {line_id|sid, category}   file a clip as a reaction
It never filters, softens, blocks or rewrites a word.
"""
from __future__ import annotations

import asyncio
import collections
import csv
import io
import json
import os
import queue
import random
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import outlandish
import sfx_repertoire

RING = 8000
JSONL_MAX = 24 * 1024 * 1024
FOLLOW_TTL = 90.0
HOLD_REST = float(os.getenv("PINE_HOLD_ASIDE_REST", "180"))
BACKFILL_PER_HOUR = int(os.getenv("PINE_SFXREACT_BACKFILL_PER_HOUR", "20000"))
TAG_TICK = 60.0
SEATS_SPOKEN = ("dj", "cohost", "third", "caller", "caller2", "guest", "manager", "drop", "sfxguy", "host")


class OutlandishRuntime:
    def __init__(self, ns: dict[str, Any]):
        self.ns = ns
        self.lock = threading.RLock()
        self.ring: collections.deque = collections.deque(maxlen=RING)
        self.by_line: collections.OrderedDict = collections.OrderedDict()
        self.by_text: collections.OrderedDict = collections.OrderedDict()
        self.reactions: collections.deque = collections.deque(maxlen=400)
        self.holds: collections.deque = collections.deque(maxlen=200)
        self.pending_links: collections.deque = collections.deque(maxlen=2000)
        self.tag_q: queue.Queue = queue.Queue(maxsize=5000)
        self.model_q: collections.deque = collections.deque(maxlen=300)
        self.follow_cache: dict[str, tuple[float, Any]] = {}
        self.metrics = collections.Counter()
        self.cost = {"rule_ms": 0.0, "rule_n": 0, "model_ms": 0.0, "model_n": 0, "model_skipped_busy": 0,
                     "react_ms": 0.0, "react_n": 0, "tag_ms": 0.0, "tag_n": 0}
        self.last_hold = 0.0
        self.stop = threading.Event()
        dp = ns.get("data_path")
        self.jsonl = Path(dp("outlandish.jsonl")) if callable(dp) else Path("outlandish.jsonl")
        self.rep = sfx_repertoire.Repertoire(str(dp("sfxguy_reactions.db")) if callable(dp) else "sfxguy_reactions.db")
        self.thread: threading.Thread | None = None

    # --- the station's pieces -----------------------------------------------------
    def rt(self):
        fn = self.ns.get("_system3")
        try:
            return fn() if callable(fn) else None
        except Exception:  # noqa: BLE001
            return None

    def config(self) -> dict[str, Any]:
        rt = self.rt()
        return rt.config if rt is not None and isinstance(getattr(rt, "config", None), dict) else {}

    def table(self, tid: str) -> dict[str, Any] | None:
        return outlandish.table_of(self.config(), tid)

    def meter(self) -> dict[str, Any]:
        return self.table("OUTLANDISH1") or outlandish.OUTLANDISH1

    def thresholds(self) -> dict[str, float]:
        return outlandish.thresholds(self.meter())

    def log(self, kind: str, text: str, extra: str = "") -> None:
        fn = self.ns.get("pipeline_log")
        try:
            if callable(fn):
                fn(kind, text, extra=extra)
        except Exception:  # noqa: BLE001
            pass

    # --- the reading --------------------------------------------------------------
    def measure(self, text: Any) -> dict[str, Any]:
        key = outlandish.text_key(text)
        meter = self.meter()
        ver = "%s:%s" % (meter.get("version"), id(meter))
        with self.lock:
            hit = self.by_text.get(key)
            if hit is not None and hit[0] == ver:
                self.by_text.move_to_end(key)
                return hit[1]
        got = outlandish.score(text, meter)
        with self.lock:
            self.cost["rule_ms"] += float(got.get("rule_ms") or 0)
            self.cost["rule_n"] += 1
            self.by_text[key] = (ver, got)
            while len(self.by_text) > 4000:
                self.by_text.popitem(last=False)
        return got

    def _stamp_of(self, line_id: str) -> dict[str, Any]:
        held = self.ns.get("_S3_LINE_BY_ID")
        got = held.get(line_id) if isinstance(held, dict) else None
        return got if isinstance(got, dict) else {}

    def note_row(self, row: dict[str, Any]) -> None:
        """The air log's writer thread, for every sounded row: score a spoken
        line (once per line id), tag an aired clip into the repertoire."""
        try:
            lid = str(row.get("id") or "")
            who = str(row.get("who") or "")
            if not lid:
                return
            if who == "board" or str(row.get("kind") or "") == "sfx":
                sid = str(row.get("sfx") or "")
                if sid:
                    self._tag_later({"sid": sid, "source": "air"})
                return
            text = " ".join(str(row.get("text") or "").split())
            if not text or who in ("analysis",) or str(row.get("kind") or "") in ("marker",):
                return
            with self.lock:
                if lid in self.by_line:
                    return
            res = self.measure(text)
            stamp = self._stamp_of(lid)
            entry = {"line_id": lid, "code": "#" + lid[:6], "at": float(row.get("air_at") or time.time()),
                     "who": who, "road": str(row.get("round") or row.get("kind") or ""),
                     "kind": str(row.get("kind") or ""), "text": text[:600], "score": res["score"],
                     "level": res["level"], "tags": res["tags"], "cues": res["cues"][:10],
                     "conversation_id": str(stamp.get("conversation_id") or ""),
                     "turn_id": str(stamp.get("turn_id") or ""), "reaction": None}
            with self.lock:
                self.by_line[lid] = entry
                while len(self.by_line) > RING:
                    self.by_line.popitem(last=False)
                self.ring.append(entry)
                self.metrics["scored"] += 1
                self.metrics["level:" + res["level"]] += 1
                rx = next((r for r in reversed(self.reactions)
                           if r.get("text_key") == outlandish.text_key(text) and time.time() - r["at"] < 900), None)
                if rx:
                    entry["reaction"] = {k: rx.get(k) for k in ("category", "label", "clip", "source", "react")}
            self._append(entry)
            self._record(entry, res)
            th = self.thresholds()
            if res["score"] >= th["audit"]:
                self._audit(entry, res)
            share = outlandish.dial(self.meter(), "model_pass", 0.0, "/5")
            if share > 0 and res["score"] >= outlandish.dial(self.meter(), "model_min", 20):
                self.model_q.append(lid)
        except Exception as exc:  # noqa: BLE001
            self.metrics["note_errors"] += 1
            self._last_error = "%s: %s" % (type(exc).__name__, exc)

    def _append(self, entry: dict[str, Any]) -> None:
        try:
            if self.jsonl.exists() and self.jsonl.stat().st_size > JSONL_MAX:
                self.jsonl.replace(self.jsonl.with_suffix(".jsonl.1"))
            with self.jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            self.metrics["jsonl_errors"] += 1

    def _record(self, entry: dict[str, Any], res: dict[str, Any]) -> None:
        """The reading as a MEASURE record on the line's conversation (the
        roll tiles and the feed dice read it). A line the ledger has not
        linked yet is retried for twenty minutes."""
        cid = entry.get("conversation_id")
        rt = self.rt()
        if not cid:
            self.pending_links.append((time.time(), entry["line_id"], res))
            return
        if rt is None:
            return
        ev = outlandish.measure_event(res, cid, entry.get("turn_id", ""), entry["line_id"], entry["who"], entry["text"],
                                      entry["at"])
        try:
            rt.observe_later(cid, "MEASURE", ev, entry.get("turn_id", ""))
            self.metrics["recorded"] += 1
        except Exception:  # noqa: BLE001
            self.metrics["record_errors"] += 1

    def _link_pending(self) -> None:
        rt = self.rt()
        if rt is None or not self.pending_links:
            return
        keep = []
        while self.pending_links:
            at, lid, res = self.pending_links.popleft()
            try:
                got = rt.store.line(lid)
            except Exception:  # noqa: BLE001
                got = None
            if got and got.get("conversation_id"):
                with self.lock:
                    entry = self.by_line.get(lid)
                    if entry is not None:
                        entry["conversation_id"] = got["conversation_id"]
                        entry["turn_id"] = str(got.get("turn_id") or "")
                if entry is not None:
                    self._record(entry, res)
            elif time.time() - at < 1200:
                keep.append((at, lid, res))
        self.pending_links.extend(keep)

    def _audit(self, entry: dict[str, Any], res: dict[str, Any]) -> None:
        """The AUDIT line and its history: the station flow journal."""
        fn = self.ns.get("station_flow_event")
        if not callable(fn):
            return
        th = self.thresholds()
        status = "high" if res["score"] >= th["react"] else "audit"
        name = entry["who"]
        summary = "%s %s %s: %s" % (outlandish.headline(res), entry["code"], name, entry["text"][:140])
        try:
            fn("outlandish", status, summary,
               {"line_id": entry["line_id"], "code": entry["code"], "who": entry["who"], "road": entry["road"],
                "score": res["score"], "tags": res["tags"], "cues": [c["label"] + ": " + c["match"] for c in res["cues"][:6]],
                "text": entry["text"][:400], "conversation_id": entry.get("conversation_id"),
                "turn_id": entry.get("turn_id"), "kind": "outlandish"},
               trace_id=str(entry.get("conversation_id") or ""))
            self.metrics["audited"] += 1
        except Exception:  # noqa: BLE001
            self.metrics["audit_errors"] += 1

    # --- the dispute that followed ------------------------------------------------------
    def follow_for(self, entry: dict[str, Any]) -> dict[str, Any]:
        rt = self.rt()
        cid = entry.get("conversation_id")
        if rt is None or not cid:
            return {"state": "none", "why": "not linked to a System 3 conversation yet"}
        hit = self.follow_cache.get(cid)
        if hit is None or time.time() - hit[0] > FOLLOW_TTL:
            try:
                conv = rt.store.conversation(cid)
            except Exception:  # noqa: BLE001
                conv = None
            hit = (time.time(), conv)
            self.follow_cache[cid] = hit
            if len(self.follow_cache) > 400:
                for k in list(self.follow_cache)[:200]:
                    self.follow_cache.pop(k, None)
        conv = hit[1]
        if not conv:
            return {"state": "none", "why": "its conversation is past retention"}
        turns = conv.get("turns") or []
        tid = entry.get("turn_id")
        idx = next((i for i, t in enumerate(turns) if t.get("turn_id") == tid), -1)
        if idx < 0:
            return {"state": "none", "why": "the line is not one of its conversation's planned turns"}
        aired = {str(x.get("turn_id")) for x in conv.get("lines") or [] if x.get("turn_id")}
        return outlandish.follow_of(turns, idx, aired)

    def review(self, hours: float = 6.0, minimum: float = -1, limit: int = 500, follow: bool = True) -> dict[str, Any]:
        since = time.time() - max(0.05, float(hours)) * 3600.0
        th = self.thresholds()
        floor = th["audit"] if minimum is None or float(minimum) < 0 else float(minimum)
        with self.lock:
            rows = [dict(e) for e in self.ring if float(e.get("at") or 0) >= since]
        if rows and float(rows[0]["at"]) > since + 60:
            rows = self._from_file(since, float(rows[0]["at"])) + rows
        dist = collections.Counter(min(9, int(r["score"]) // 10) for r in rows)
        tags = collections.Counter(t for r in rows if r["score"] >= floor for t in r.get("tags") or [])
        items = sorted((r for r in rows if r["score"] >= floor), key=lambda r: -float(r["at"]))[:max(1, int(limit))]
        fstat = collections.Counter()
        for r in items:
            if follow:
                f = self.follow_for(r)
                r["follow"] = f.get("state")
                r["follow_why"] = f.get("why")
                fstat[f.get("state")] += 1
        return {"hours": hours, "since": since, "thresholds": th, "floor": floor, "lines": len(rows),
                "count": len(items), "distribution": {"%d-%d" % (k * 10, 100 if k == 9 else k * 10 + 9): dist.get(k, 0)
                                                     for k in range(10)},
                "by_tag": dict(tags.most_common()), "follow": dict(fstat), "items": items,
                "cost": self.cost_view()}

    def _from_file(self, since: float, until: float) -> list[dict[str, Any]]:
        out = []
        for path in (self.jsonl.with_suffix(".jsonl.1"), self.jsonl):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for ln in fh:
                        try:
                            r = json.loads(ln)
                        except ValueError:
                            continue
                        if since <= float(r.get("at") or 0) < until:
                            out.append(r)
            except OSError:
                continue
        seen, uniq = set(), []
        for r in out:
            if r.get("line_id") in seen:
                continue
            seen.add(r.get("line_id"))
            uniq.append(r)
        return uniq

    def cost_view(self) -> dict[str, Any]:
        c = dict(self.cost)
        c["rule_us_per_line"] = round(c["rule_ms"] * 1000.0 / max(1, c["rule_n"]), 1)
        c["model_ms_per_call"] = round(c["model_ms"] / max(1, c["model_n"]), 1)
        c["react_ms_per_roll"] = round(c["react_ms"] / max(1, c["react_n"]), 2)
        c["tag_ms_per_clip"] = round(c["tag_ms"] / max(1, c["tag_n"]), 2)
        return c

    # --- the SFX Guy's reaction ------------------------------------------------------------
    def _refused(self, path: Any) -> str:
        fn = self.ns.get("sfx_clip_refusal")
        try:
            return str(fn(path) or "") if callable(fn) else ""
        except Exception:  # noqa: BLE001
            return ""

    def _used(self, sid: str) -> bool:
        fn = self.ns.get("norepeat_sfx_used")
        try:
            return bool(fn(sid)) if callable(fn) else False
        except Exception:  # noqa: BLE001
            return False

    def candidates(self, plan: dict[str, Any], table: dict[str, Any]) -> list[dict[str, Any]]:
        """His shortlist for the rolled topic, then the clip search over the
        whole library for its words when the shortlist runs thin. MP4-only is
        honoured, the day's heard clips are struck, the station's filter
        refuses what it refuses. Clips the search finds are filed into his
        repertoire (so it grows)."""
        mp4 = False
        try:
            mp4 = bool(self.ns["sfx_mp4_only"]())
        except Exception:  # noqa: BLE001
            mp4 = False
        most = max(4, int(outlandish.dial(table, "shortlist", 24)))
        max_s = outlandish.dial(table, "max_seconds", 8)
        short = self.rep.shortlist(plan["category"], most=most, video_only=mp4, max_seconds=max_s,
                                   used=self._used, refused=self._refused)
        cands = [{"id": c["sid"], "label": str(c["name"])[:80], "weight": c["weight"], "why": c["why"],
                  "path": c["path"], "source": c["source"], "sid": c["sid"], "seconds": c["seconds"]} for c in short]
        if len(cands) >= most:
            return cands
        score_fn, rows_fn, sid_fn = (self.ns.get("sfx_match_score"), self.ns.get("sfx_match_rows"),
                                     self.ns.get("sfx_id"))
        if not (callable(score_fn) and callable(rows_fn) and callable(sid_fn)):
            return cands
        try:
            found = score_fn(" ".join(plan.get("words") or [plan.get("label") or ""]), "",
                             video=(True if mp4 else None), limit=most)
            rows = rows_fn(found, most)
        except Exception:  # noqa: BLE001
            rows = []
        have = {c["sid"] for c in cands}
        top = max([float(getattr(r[2], "score", 0) or 0) for r in rows] or [1.0]) or 1.0
        for path, secs, cand in rows:
            try:
                sid = str(sid_fn(Path(str(path))))
            except Exception:  # noqa: BLE001
                continue
            if not sid or sid in have or self._used(sid) or self._refused(path) or (max_s and float(secs or 0) > max_s):
                continue
            have.add(sid)
            words = []
            try:
                words = cand.words("line")[:4]
            except Exception:  # noqa: BLE001
                words = []
            w = round(0.5 * max(0.05, float(getattr(cand, "score", 0) or 0) / top), 4)
            cands.append({"id": sid, "label": Path(str(path)).stem[:80], "weight": w, "path": str(path), "sid": sid,
                          "source": "the clip search", "seconds": secs,
                          "why": ["the clip search: " + ", ".join(words)] if words else ["the clip search"]})
            self._tag_later({"sid": sid, "path": str(path), "seconds": secs, "source": "matcher",
                             "extra": [(plan["category"], 0.5, ["the clip search found it for %s" % plan.get("label")])]})
            if len(cands) >= most:
                break
        return cands

    def _react(self, text: str, cid: str = "", turn_id: str = "", line_id: str = "") -> tuple[dict[str, Any] | None,
                                                                                              dict[str, Any], dict]:
        t0 = time.perf_counter()
        res = self.measure(text)
        th = self.thresholds()
        if res["score"] < th["react"]:
            return None, res, {}
        table = self.table("SFXREACT1")
        if table is None:
            return None, res, {}
        rnd = random.SystemRandom()
        plan = outlandish.react_plan(res, table, rnd.random(), rnd.random(), self.meter())
        clip = None
        if plan.get("react"):
            cands = self.candidates(plan, table)
            if cands:
                k, stage = outlandish.clip_stage(cands, rnd.random())
                if k >= 0:
                    clip = dict(cands[k], stage=stage, name=cands[k]["label"], index=k + 1, of=len(cands))
            else:
                plan["why"] = "no %s clip is fresh today (MP4-only %s)" % (plan.get("label"), "on" if self._mp4() else "off")
        ev = outlandish.react_event(plan, res, cid, turn_id, line_id, clip, table_id=str(table.get("id")))
        rt = self.rt()
        if rt is not None and cid:
            try:
                rt.observe_later(cid, "SFXREACT", ev, turn_id)
            except Exception:  # noqa: BLE001
                pass
        row = {"at": time.time(), "text_key": outlandish.text_key(text), "text": text[:200], "score": res["score"],
               "tags": res["tags"], "react": bool(plan.get("react")), "category": plan.get("category"),
               "label": plan.get("label"), "clip": (clip or {}).get("path"), "source": (clip or {}).get("source"),
               "odds": plan.get("odds"), "why": plan.get("why", ""), "conversation_id": cid, "turn_id": turn_id}
        with self.lock:
            self.reactions.append(row)
            self.cost["react_ms"] += (time.perf_counter() - t0) * 1000.0
            self.cost["react_n"] += 1
            self.metrics["react:" + ("clip" if clip else "pass")] += 1
            for e in reversed(self.ring):
                if e.get("reaction") is None and outlandish.text_key(e.get("text")) == row["text_key"]:
                    e["reaction"] = {k: row.get(k) for k in ("category", "label", "clip", "source", "react")}
                    break
        if clip:
            try:
                self.rep.played(clip["sid"])
            except Exception:  # noqa: BLE001
                pass
            note = self.ns.get("_sfx_roll_note")
            if callable(note):
                try:
                    cstage = plan["stages"][-1] if plan.get("stages") else {}
                    note(Path(clip["path"]), "reaction",
                         {"label": plan.get("label"), "dice": (cstage.get("draw") or {}).get("dice"),
                          "index": cstage.get("selected_index"), "of": cstage.get("of")},
                         {"label": clip["name"], "dice": (clip["stage"].get("draw") or {}).get("dice"),
                          "index": clip["index"], "of": clip["of"]}, 1)
                except Exception:  # noqa: BLE001
                    pass
            self.log("air", "[outlandish] the SFX Guy reacts (%s, score %d): %s from %s"
                     % (plan.get("label"), res["score"], Path(clip["path"]).stem[:60], clip.get("source")))
        return clip, res, plan

    def _mp4(self) -> bool:
        try:
            return bool(self.ns["sfx_mp4_only"]())
        except Exception:  # noqa: BLE001
            return False

    def react_clip(self, text: Any, who: str = "", meta: Any = None, road: str = "round") -> Path | None:
        """The round's assembly loop, right after a turn: the reaction clip to
        drop between it and the next turn, or None."""
        try:
            text = " ".join(str(text or "").split())
            if not text:
                return None
            if self.measure(text)["score"] < self.thresholds()["react"]:
                return None
            cid, turn_id = "", ""
            rt = self.rt()
            if rt is not None and isinstance(meta, dict):
                try:
                    cid, i = rt._turn_of(meta, text, who)
                    if i is not None:
                        turn_id = str(((((meta.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
                                       .get("turn_id")) or "")
                except Exception:  # noqa: BLE001
                    cid = str(((meta or {}).get("system3") or {}).get("conversation_id") or "")
            clip, _res, _plan = self._react(text, str(cid or ""), turn_id)
            return Path(clip["path"]) if clip else None
        except Exception as exc:  # noqa: BLE001
            self._last_error = "react: %s: %s" % (type(exc).__name__, exc)
            return None

    async def react_between(self, e: dict[str, Any], track: Any = None) -> bool:
        """A line's exchange: after the opener aired, before its first reply."""
        opening = " ".join(str(e.get("opening") or "").split())
        if not opening or self.measure(opening)["score"] < self.thresholds()["react"]:
            return False
        rows = e.get("rows") or []
        stamp = (rows[0].get("stamp") if rows and isinstance(rows[0], dict) else None) or e.get("stamp") or {}
        clip, _res, _plan = self._react(opening, str(stamp.get("conversation_id") or ""),
                                        str(stamp.get("turn_id") or ""))
        if not clip:
            return False
        sting = self.ns.get("dj_sting")
        radio = self.ns.get("_RADIO") or {}
        if not callable(sting):
            return False
        try:
            got = await sting((radio.get("voice_to") or "box") in ("box", "both"), after=opening, who="sfxguy",
                              force=True, sample=Path(clip["path"]))
            return bool(got)
        except Exception:  # noqa: BLE001
            return False

    # --- the chapter's reply rows, re-rolled once the opener is known --------------------
    def prime_chapter(self, stamp: Any, opening: str) -> dict[str, Any] | None:
        """A line road's exchange is planned before its opener's words are
        final. Once they are: the opener is observed (its reading recorded as
        a MEASURE decision on its turn) and, when it scores at the dispute
        threshold, the replies are decided again from turn 2 - the next seat's
        RS/IRS rows weighing up by OUTDISPUTE1. Structure only: no word is
        touched."""
        rt = self.rt()
        if rt is None or not isinstance(stamp, dict) or not opening:
            return None
        cid = str(stamp.get("conversation_id") or "")
        conv = rt.recent.get(cid) if hasattr(rt, "recent") else None
        if not conv or len(conv.get("turns") or []) < 2 or conv["turns"][0].get("text"):
            return None
        if not outlandish.has_table(rt.config, "OUTLANDISH1"):
            return None
        res = self.measure(opening)
        if res["score"] < self.thresholds()["dispute"]:
            return {"primed": False, "score": res["score"]}
        import system3                                   # the engine, already loaded by System 3
        try:
            system3.observe(conv, 0, opening)
            system3.replan(conv, rt.config, 1, until=len(conv["turns"]) or None)
            conv["outlandish_primed"] = {"score": res["score"], "tags": res["tags"], "at": time.time()}
            rt.remember(conv)
            rt.persist(conv)
            self.metrics["primed"] += 1
            return {"primed": True, "score": res["score"], "turns": len(conv["turns"])}
        except Exception as exc:  # noqa: BLE001
            self._last_error = "prime: %s: %s" % (type(exc).__name__, exc)
            return None

    # --- the holding moment ----------------------------------------------------------------
    def hold_roll(self, reason: str = "") -> dict[str, Any] | None:
        table = self.table("HOLDBANTER1")
        if table is None or time.time() - self.last_hold < HOLD_REST:
            return None
        self.last_hold = time.time()
        rnd = random.SystemRandom()
        plan = outlandish.hold_plan(table, rnd.random(), rnd.random(), rnd.random(), rnd.random())
        row = {"at": time.time(), "reason": reason, "aside": plan.get("aside"), "subject": plan.get("subject"),
               "item": plan.get("item"), "seat": plan.get("seat"), "who": plan.get("who"), "stages": plan["stages"]}
        self.holds.append(row)
        self.metrics["hold:" + ("aside" if plan.get("aside") else "sfx")] += 1
        fn = self.ns.get("station_flow_event")
        if callable(fn):
            try:
                fn("watchdog", "hold", "HOLDBANTER1: %s (%s)" % (
                    ("an aside - " + str(plan.get("item")) + " from " + str(plan.get("who"))) if plan.get("aside")
                    else "the SFX Guy's time-buyers alone", reason[:80]), {"hold": row, "kind": "hold"})
            except Exception:  # noqa: BLE001
                pass
        if plan.get("aside"):
            ff = self.ns.get("fire_and_forget")
            if callable(ff):
                ff(self._aside(plan, row))
        return plan

    async def _aside(self, plan: dict[str, Any], row: dict[str, Any]) -> None:
        speak = self.ns.get("dj_speak")
        if not callable(speak):
            return
        said = ""
        try:
            said = await speak("aside", None, extra=outlandish.hold_direction(plan), who=str(plan.get("who") or "dj"))
        except Exception as exc:  # noqa: BLE001
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
        row["said"] = str(said or "")[:300]
        if not said:
            return
        radio = self.ns.get("_RADIO") or {}
        lid = ""
        for c in reversed((radio.get("chat") or [])[-30:]):
            if str(c.get("text") or "") == str(said):
                lid = str(c.get("id") or "")
                break
        stamp = self._stamp_of(lid) if lid else {}
        rt = self.rt()
        if rt is not None and stamp.get("conversation_id"):
            ev = {"schema": "system3-measure/1", "kind": "observation", "family": "HOLD",
                  "event_id": "%s:h:%s" % (stamp["conversation_id"], lid), "conversation_id": stamp["conversation_id"],
                  "turn_id": str(stamp.get("turn_id") or ""), "line_id": lid, "lines": [lid], "at": time.time(),
                  "stages": plan["stages"], "rng": (plan["stages"][1].get("draw") if len(plan["stages"]) > 1
                                                    else plan["stages"][0].get("draw")),
                  "selected": {"table": "HOLDBANTER1", "id": plan.get("item"), "label": "an aside: %s (%s)" % (
                      plan.get("item"), plan.get("who")), "category": plan.get("subject")},
                  "meta": {"why": "the pipeline was behind: the hosts' aside instead of a holding line"}}
            try:
                rt.observe_later(stamp["conversation_id"], "HOLD", ev, str(stamp.get("turn_id") or ""))
            except Exception:  # noqa: BLE001
                pass

    # --- votes and marks -------------------------------------------------------------------
    def _clip_of_line(self, line_id: str) -> tuple[str, str]:
        fn = self.ns.get("sfx_id_of_line")
        if not callable(fn):
            return "", "the station cannot name the clip"
        try:
            return fn(line_id)
        except Exception as exc:  # noqa: BLE001
            return "", str(exc)

    def _clip_facts(self, sid: str) -> dict[str, Any]:
        fn = self.ns.get("sfx_by_id")
        path = None
        try:
            path = fn(sid) if callable(fn) else None
        except Exception:  # noqa: BLE001
            path = None
        if path is None:
            return {}
        p = Path(str(path))
        secs = None
        try:
            secs = float(self.ns["sfx_seconds"](p))
        except Exception:  # noqa: BLE001
            secs = None
        return {"path": str(p), "name": p.stem, "seconds": secs, "video": self._is_video(p)}

    def _is_video(self, p: Path) -> bool:
        fn = self.ns.get("sfx_is_video")
        try:
            return bool(fn(p)) if callable(fn) else p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv")
        except Exception:  # noqa: BLE001
            return p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv")

    def clip_vote(self, line_id: str, vote: str) -> dict[str, Any]:
        """An up/down vote on a CLIP's line: into his repertoire (a reaction he
        was marked with weighs up there too) and into the general picks (the
        per-clip dial, #645: +0.5 an upvote up to 4, halved by a downvote)."""
        sid, why = self._clip_of_line(line_id)
        if not sid:
            return {}
        facts = self._clip_facts(sid)
        got = self.rep.vote(sid, vote, line_id=line_id, path=facts.get("path", ""), name=facts.get("name", ""),
                            seconds=facts.get("seconds"), video=facts.get("video"))
        general = None
        try:
            weights = self.ns["sfx_weights"]()
            now = float(weights.get(sid, 1.0))
            if vote == "up":
                general = min(4.0, now + 0.5)
            elif vote == "down":
                general = max(0.25, now * 0.5)
            if general is not None and abs(general - now) > 1e-6:
                self.ns["sfx_set_weight"](sid, general)
        except Exception:  # noqa: BLE001
            general = None
        if facts:
            self._tag_later({"sid": sid, "path": facts.get("path"), "seconds": facts.get("seconds"), "source": "vote"})
        return {"sfxguy": {"sid": sid, "votes": {"up": got.get("up"), "down": got.get("down")},
                           "marked": got.get("marked"), "reaction_weight": got.get("factor"),
                           "general_weight": general}}

    def mark(self, sid: str = "", line_id: str = "", category: str = "") -> dict[str, Any]:
        if not sid and line_id:
            sid, why = self._clip_of_line(line_id)
            if not sid:
                return {"ok": False, "why": why}
        facts = self._clip_facts(sid)
        got = self.rep.mark(sid, category, path=facts.get("path", ""), name=facts.get("name", ""),
                            seconds=facts.get("seconds"), video=facts.get("video"), line_id=line_id)
        if got.get("ok") and facts:
            self._tag_later({"sid": sid, "path": facts.get("path"), "seconds": facts.get("seconds"), "source": "air"})
        return dict(got, clip=facts.get("name"))

    # --- the slow worker: links, tags, backfill, the model pass ------------------------------
    def _tag_later(self, job: dict[str, Any]) -> None:
        try:
            self.tag_q.put_nowait(job)
        except queue.Full:
            self.metrics["tag_dropped"] += 1

    def _comfy_busy(self) -> bool:
        last = self.ns.get("_COMFY_LAST_USED")
        try:
            if last and time.time() - float(last[0] or 0) < 180:
                return True
        except Exception:  # noqa: BLE001
            pass
        url = str(self.ns.get("COMFYUI_URL") or "")
        if not url:
            return False
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/queue", timeout=3) as r:
                q = json.loads(r.read().decode("utf-8") or "{}")
            return bool(q.get("queue_running") or q.get("queue_pending"))
        except Exception:  # noqa: BLE001
            return False

    def _tag_one(self, job: dict[str, Any]) -> None:
        t0 = time.perf_counter()
        sid = str(job.get("sid") or "")
        path = job.get("path")
        facts = {} if path else self._clip_facts(sid)
        path = path or facts.get("path")
        if not sid or not path:
            return
        p = Path(str(path))
        said = ""
        secs = job.get("seconds") if job.get("seconds") is not None else facts.get("seconds")
        self.rep.note_clip(sid, str(p), p.stem, p.parent.name, secs, self._is_video(p),
                           said, source=str(job.get("source") or "air"), extra=job.get("extra") or ())
        with self.lock:
            self.cost["tag_ms"] += (time.perf_counter() - t0) * 1000.0
            self.cost["tag_n"] += 1

    def worker(self) -> None:
        """Niced, one job at a time, never while ComfyUI is rendering."""
        try:
            os.nice(10)
        except Exception:  # noqa: BLE001
            pass
        budget, hour = 0, int(time.time() // 3600)
        clips_db = ""
        dp = self.ns.get("data_path")
        if callable(dp):
            clips_db = str(dp("sfx_clips.db"))
        while not self.stop.is_set():
            try:
                self._link_pending()
                n = 0
                while n < 50 and not self.stop.is_set():
                    try:
                        job = self.tag_q.get_nowait()
                    except queue.Empty:
                        break
                    self._tag_one(job)
                    n += 1
                if int(time.time() // 3600) != hour:
                    hour, budget = int(time.time() // 3600), 0
                per_tick = max(1, int(BACKFILL_PER_HOUR * TAG_TICK / 3600.0))
                if (clips_db and budget < BACKFILL_PER_HOUR and os.path.exists(clips_db)
                        and not self._comfy_busy()):
                    got = self.rep.backfill(clips_db, cap=per_tick, stop=self.stop.is_set)
                    budget += int(got.get("read") or 0)
                    self.metrics["backfill_read"] += int(got.get("read") or 0)
                    self.metrics["backfill_filed"] += int(got.get("filed") or 0)
            except Exception as exc:  # noqa: BLE001
                self._last_error = "worker: %s: %s" % (type(exc).__name__, exc)
            self.stop.wait(TAG_TICK)

    async def model_loop(self) -> None:
        """The optional model pass: lowest priority, only while the model gate
        is completely idle and nothing is being written; never holds a lane a
        station call is waiting for. Off while the model_pass dial is 0."""
        while True:
            await asyncio.sleep(4.0)
            try:
                share = outlandish.dial(self.meter(), "model_pass", 0.0, "/5")
                if share <= 0 or not self.model_q:
                    if share <= 0:
                        self.model_q.clear()
                    continue
                cap = int(outlandish.dial(self.meter(), "model_per_hour", 60))
                if self.metrics["model_hour"] != int(time.time() // 3600):
                    self.metrics["model_hour"] = int(time.time() // 3600)
                    self.metrics["model_this_hour"] = 0
                if self.metrics["model_this_hour"] >= cap:
                    continue
                gate, jobs = self.ns.get("_OLLAMA_GATE"), self.ns.get("_OLLAMA_JOBS")
                lanes = int(self.ns.get("OLLAMA_LANES") or 1)
                if (jobs or gate is None or gate.locked()
                        or getattr(gate, "_value", 0) < 2 * lanes or getattr(gate, "_waiters", None)):
                    self.cost["model_skipped_busy"] += 1
                    continue
                lid = self.model_q.popleft()
                entry = self.by_line.get(lid)
                if not entry:
                    continue
                t0 = time.perf_counter()
                reply = await asyncio.to_thread(self._ask_model, entry["text"])
                ms = (time.perf_counter() - t0) * 1000.0
                self.metrics["model_this_hour"] += 1
                self.cost["model_ms"] += ms
                self.cost["model_n"] += 1
                got = outlandish.parse_model(reply)
                if not got:
                    continue
                got["ms"] = round(ms, 1)
                res = outlandish.score(entry["text"], self.meter(), model=got)
                was = entry["score"]
                entry.update(score=res["score"], level=res["level"], tags=res["tags"], model=res.get("model"))
                self._append(dict(entry, update="model"))
                if was < self.thresholds()["audit"] <= res["score"]:
                    self._audit(entry, res)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = "model: %s: %s" % (type(exc).__name__, exc)

    def _ask_model(self, text: str) -> str:
        url = str(self.ns.get("OLLAMA_URL") or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        model = os.getenv("PINE_OUTLANDISH_MODEL", "")
        if not model:
            try:
                model = str(self.ns["load_settings"]().get("model") or "")
            except Exception:  # noqa: BLE001
                model = ""
        body = json.dumps({"model": model, "prompt": outlandish.model_prompt(text), "stream": False,
                           "options": {"num_predict": 48, "temperature": 0}, "format": "json",
                           "keep_alive": "5m"}).encode("utf-8")
        req = urllib.request.Request(url + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return str(json.loads(r.read().decode("utf-8") or "{}").get("response") or "")

    def status(self) -> dict[str, Any]:
        return {"metrics": dict(self.metrics), "cost": self.cost_view(), "thresholds": self.thresholds(),
                "ring": len(self.ring), "pending_links": len(self.pending_links), "tag_queue": self.tag_q.qsize(),
                "model_queue": len(self.model_q), "error": getattr(self, "_last_error", "")}


def csv_of(items: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "aired_utc", "who", "road", "score", "level", "tags", "cues", "follow", "reaction",
                "text", "line_id", "conversation_id", "turn_id"])
    for r in items:
        rx = r.get("reaction") or {}
        w.writerow([r.get("code"), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(r.get("at") or 0))),
                    r.get("who"), r.get("road"), r.get("score"), r.get("level"), "|".join(r.get("tags") or []),
                    "|".join("%s: %s" % (c.get("label"), c.get("match")) for c in r.get("cues") or []),
                    r.get("follow", ""), (rx.get("label") or "") if isinstance(rx, dict) else "",
                    r.get("text"), r.get("line_id"), r.get("conversation_id"), r.get("turn_id")])
    return buf.getvalue()


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import Response

    globals()["Request"] = Request          # the routes' annotations are strings (future annotations)
    globals()["Header"] = Header
    orr = OutlandishRuntime(namespace)
    namespace["_OUTLANDISH"] = orr
    namespace["outlandish_note_row"] = orr.note_row
    namespace["outlandish_react_clip"] = orr.react_clip
    namespace["outlandish_react_between"] = orr.react_between
    namespace["outlandish_prime_chapter"] = orr.prime_chapter
    namespace["outlandish_hold_roll"] = orr.hold_roll
    namespace["outlandish_measure"] = orr.measure

    # an up/down vote on a clip's line teaches the SFX Guy (his repertoire and the general picks)
    _vote = namespace.get("line_vote_apply")
    if callable(_vote) and not getattr(_vote, "_outlandish", False):
        def line_vote_apply(line_id, vote):
            got = _vote(line_id, vote)
            try:
                more = orr.clip_vote(line_id, vote)
                if more and isinstance(got, dict):
                    got = dict(got, **more)
                    sx = more.get("sfxguy") or {}
                    got["say"] = "; ".join(x for x in (str(got.get("say") or ""), "the SFX Guy files it: %s" % (
                        "weighed up in his picks%s" % (" and as a %s reaction" % sx["marked"] if sx.get("marked") else "")
                        if vote == "up" else "weighed down in his picks" if vote == "down" else "vote taken back"))
                        if x and x != "noted")
            except Exception:  # noqa: BLE001
                pass
            return got
        line_vote_apply._outlandish = True
        namespace["line_vote_apply"] = line_vote_apply

    require_auth = namespace.get("require_auth")
    require_read = namespace.get("require_read_auth") or require_auth

    @app.get("/api/outlandish")
    async def outlandish_list(hours: float = 6.0, min: float = -1, limit: int = 500, format: str = "json",
                              follow: int = 1, authorization: str | None = Header(default=None)):
        """The review list: every aired line at or above the audit threshold
        (or `min`) in the last `hours`, with its #code, seat, words, score,
        tags, cues, the dispute that followed and the SFX Guy's reaction.
        format=csv exports it; format=json (default) also carries the score
        distribution, the tags and the meter's cost."""
        require_read(authorization)
        got = await asyncio.to_thread(orr.review, max(0.05, min_(hours, 72.0)), min, max(1, min_(int(limit), 5000)),
                                      bool(follow))
        if str(format).lower() == "csv":
            return Response(csv_of(got["items"]), media_type="text/csv",
                            headers={"Content-Disposition": "attachment; filename=outlandish-%dh.csv" % int(hours)})
        if str(format).lower() == "download":
            return Response(json.dumps(got, default=str, indent=1), media_type="application/json",
                            headers={"Content-Disposition": "attachment; filename=outlandish-%dh.json" % int(hours)})
        return got

    @app.get("/api/outlandish/status")
    async def outlandish_status(authorization: str | None = Header(default=None)):
        require_read(authorization)
        return orr.status()

    @app.get("/api/outlandish/line/{line_id}")
    async def outlandish_line(line_id: str, authorization: str | None = Header(default=None)):
        require_read(authorization)
        e = orr.by_line.get(line_id)
        if not e:
            raise HTTPException(404, "the meter has no reading for %s (older than its ring, or not a spoken line)" % line_id)
        out = dict(e)
        out["follow"] = await asyncio.to_thread(orr.follow_for, e)
        return out

    @app.post("/api/outlandish/score")
    async def outlandish_score(request: Request, authorization: str | None = Header(default=None)):
        require_read(authorization)
        raw = await request.json()
        text = str((raw or {}).get("text") or "")[:4000]
        res = outlandish.score(text, orr.meter())
        return {"reading": res, "headline": outlandish.headline(res), "thresholds": orr.thresholds(),
                "dispute_boost": outlandish.dispute_boost(res["score"], orr.table("OUTDISPUTE1"))}

    @app.get("/api/sfxguy/reactions")
    async def sfxguy_reactions(authorization: str | None = Header(default=None)):
        require_read(authorization)
        stats = await asyncio.to_thread(orr.rep.stats)
        return {"repertoire": stats, "recent": list(orr.reactions)[-40:][::-1], "holds": list(orr.holds)[-20:][::-1],
                "categories": list(sfx_repertoire.CATEGORIES), "status": orr.status()}

    @app.get("/api/sfxguy/reactions/shortlist")
    async def sfxguy_shortlist(category: str = "gasp", most: int = 24, authorization: str | None = Header(default=None)):
        require_read(authorization)
        return {"category": category, "mp4_only": orr._mp4(),
                "clips": await asyncio.to_thread(orr.rep.shortlist, category, max(1, min_(int(most), 100)), orr._mp4(),
                                                 0.0, orr._used, orr._refused)}

    @app.post("/api/sfxguy/reactions/mark")
    async def sfxguy_mark(request: Request, authorization: str | None = Header(default=None)):
        require_auth(authorization)
        raw = await request.json()
        raw = raw if isinstance(raw, dict) else {}
        got = await asyncio.to_thread(orr.mark, str(raw.get("sid") or raw.get("id") or ""),
                                      str(raw.get("line_id") or ""), str(raw.get("category") or ""))
        if not got.get("ok"):
            raise HTTPException(400, got.get("why") or "the clip could not be filed")
        return got

    @app.on_event("startup")
    async def start_outlandish():
        orr.thread = threading.Thread(target=orr.worker, name="outlandish:tagger", daemon=True)
        orr.thread.start()
        asyncio.create_task(orr.model_loop(), name="outlandish:model")

    @app.on_event("shutdown")
    async def stop_outlandish():
        orr.stop.set()

    return orr


def min_(a, b):
    return a if a < b else b
