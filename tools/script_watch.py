#!/usr/bin/env python3
"""tools/script_watch.py - WATCH THE SCRIPT VIEW UNFOLD, READ ONLY.

"Check and watch the script view, making sure that the script view is going
from entry to entry and it's unfolding showing how everything's going
according to the way that our decision trees are unfolding for each
segment."                                                 - the operator, 09-29

Records, for N minutes, the four things the Script view is made of:

  ledger   data/script_ledger.jsonl - each script entry as it is WRITTEN,
           with its (block, ord), segment, seat and System 3 turn;
  air      data/air_log.jsonl - each line as it is published / heard;
  now      GET /api/dj stream_now + speaking_now - the position the Script
           view is handed (PineStationFeed interpolates `now` from it);
  view     GET /api/screenplay/{hour} - the page the Script view paints
           (scene headings with their slot, dialogue rows with block/ord);
  tree     GET /api/script/segment/{occ}/decision-tree - System 3's walk of
           the segment, re-fetched as it grows.

then compares them and prints a short verdict, one line per divergence class
with example line ids. Nothing is written anywhere but --out.

    python3 tools/script_watch.py --minutes 45           # record + verdict
    python3 tools/script_watch.py --analyze watch.jsonl  # verdict of a recording

Runs in the container (data at /app/data, station at 127.0.0.1:8096, key from
SPARK_AGENT_API_KEY) or on the host (--data ~/pinevoice-stack/spark-agent/data
--key ...). Exit 0 = clean, 1 = divergences found, 2 = could not watch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HEARD = ("stream",)               # an air-log state that means the ear got it
TREE_EVERY = 20.0
VIEW_EVERY = 30.0
DJ_EVERY = 2.0
DIR_EVERY = 45.0
# reported, never counted against the script: by design (#1339 catch-up, bank.reair)
INFO = ("re_aired", "unscripted_flag", "insert_out_of_place", "filed_after_heard")
SEAT_OF = {"dj": "A", "host": "A", "cohost": "B", "third": "D", "caller": "C", "caller2": "E"}
GRACE = 240.0                     # a scripted row not heard this long after its block's last hearing = skipped


# --------------------------------------------------------------------------- record
class Station:
    def __init__(self, base: str, key: str) -> None:
        self.base, self.key = base.rstrip("/"), key

    def get(self, path: str, timeout: float = 25.0) -> Any:
        req = urllib.request.Request(self.base + path, headers={"Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))


class Tail:
    """New rows of a jsonl that is appended to AND rewritten in place (the ledger's
    hourly prune truncates and rewrites it): every read re-reads the last `window`
    bytes and hands back the rows whose key was not handed back before. A byte
    offset loses rows the moment the file is rewritten under it (measured: nine
    rows of one block, 09-29)."""

    def __init__(self, path: Path, back: int = 0, window: int = 900_000,
                 key: Any = None) -> None:
        self.path, self.window = path, max(window, back)
        self.key = key or (lambda d: (d.get("block"), d.get("ord"), d.get("line_id")))
        self.seen: set = set()
        self.sig: tuple = ()
        self.first = True
        self.back = back

    def read(self) -> list[dict[str, Any]]:
        try:
            st = self.path.stat()
        except OSError:
            return []
        sig = (st.st_size, st.st_mtime_ns, getattr(st, "st_ino", 0))
        if sig == self.sig:
            return []
        self.sig = sig
        span = self.back if self.first else self.window
        with open(self.path, "rb") as fh:
            fh.seek(max(0, st.st_size - span))
            data = fh.read()
        lines = data.split(b"\n")
        if st.st_size > span:
            lines = lines[1:]
        out = []
        for ln in lines:
            try:
                d = json.loads(ln)
            except ValueError:
                continue                   # a partial last line: taken whole next time
            if not isinstance(d, dict):
                continue
            k = self.key(d)
            if k in self.seen:
                continue
            self.seen.add(k)
            out.append(d)
        self.first = False
        return out


def ledger_brief(d: dict[str, Any]) -> dict[str, Any]:
    seg = d.get("segment") if isinstance(d.get("segment"), dict) else {}
    s3 = d.get("system3") if isinstance(d.get("system3"), dict) else {}
    rep = s3.get("replay") if isinstance(s3.get("replay"), dict) else None
    return {"block": d.get("block"), "ord": d.get("ord"), "at": d.get("at"), "line_id": d.get("line_id"),
            "sid": d.get("sid"), "who": d.get("who"), "kind": d.get("kind"), "turn": d.get("turn"),
            "round": d.get("round"), "scripted": d.get("scripted"), "cue": d.get("cue"),
            "seg": seg.get("id"), "seg_label": seg.get("label"), "seg_kind": seg.get("kind"),
            "seg_start": seg.get("start"), "seg_ends": seg.get("ends"),
            "conv": s3.get("conversation_id"), "turn_id": s3.get("turn_id"),
            "listening": bool(s3.get("listening")),     # a back-channel stamped to the turn it answers
            "replay": ({"airing": rep.get("airing"), "first_aired": rep.get("first_aired")} if rep else None),
            "text": str(d.get("text") or "")[:90]}


RANK = {"": 0, "page": 1, "analysis": 1, "published": 2, "stream": 3}


def air_merge(old: dict[str, Any] | None, b: dict[str, Any]) -> dict[str, Any]:
    """The air log appends a row per state; one line's rows fold into its furthest state."""
    if not old:
        return dict(b)
    out = dict(old)
    if RANK.get(str(b.get("aired") or ""), 1) >= RANK.get(str(old.get("aired") or ""), 1):
        out.update({k: v for k, v in b.items() if v is not None})
    if old.get("heard") and b.get("heard"):
        out["heard"] = min(float(old["heard"]), float(b["heard"]))
    return out


def air_brief(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": d.get("id"), "aired": d.get("aired"), "air_at": d.get("air_at"),
            "heard": d.get("heard_ack_at"), "by": d.get("heard_ack_by"), "kind": d.get("kind"),
            "who": d.get("who"), "sid": d.get("sid"), "turn": d.get("turn"), "round": d.get("round"),
            "rtk": str(d.get("repeat_text_key") or "")[:16], "text": str(d.get("text") or "")[:90]}


def tree_brief(t: dict[str, Any]) -> dict[str, Any]:
    rounds = []
    for r in t.get("rounds") or []:
        els = []
        for e in r.get("elements") or []:
            if e.get("type") == "stage":
                ln = e.get("line") or {}
                els.append({"t": "s", "turn_id": e.get("turn_id"), "index": e.get("index"), "node": e.get("node"),
                            "speaker": e.get("speaker"), "state": e.get("state"), "line_id": ln.get("line_id"),
                            "line_ids": ln.get("line_ids"), "block": ln.get("block"), "ord": ln.get("ord"),
                            "seg": (ln.get("segment") or {}).get("id") if isinstance(ln.get("segment"), dict) else ln.get("segment")})
            else:
                els.append({"t": "d", "node": e.get("node"), "taken": (e.get("taken") or {}).get("id"),
                            "not_taken": e.get("not_taken")})
        rounds.append({"conv": r.get("conversation_id"), "source": r.get("source"), "road": r.get("road"),
                       "status": r.get("status"), "gone": r.get("gone"), "elements": els,
                       "counts": r.get("counts"), "notes": r.get("notes")})
    return {"segment_id": t.get("segment_id"), "entry": t.get("entry"), "registered": t.get("registered"),
            "rounds": rounds, "unmatched": t.get("unmatched"), "more": t.get("more")}


def view_brief(p: dict[str, Any]) -> dict[str, Any]:
    els = []
    for e in p.get("elements") or []:
        ty = e.get("type")
        if ty == "scene":
            els.append({"t": "scene", "id": e.get("id"), "text": e.get("text"), "at": e.get("at"),
                        "round": e.get("round"), "slot": e.get("slot")})
        elif ty in ("dialogue", "action") and e.get("line"):
            els.append({"t": ty[0], "line": e.get("line"), "block": e.get("block"), "ord": e.get("ord"),
                        "at": e.get("at"), "aired": e.get("aired"), "who": e.get("who"),
                        "kind": e.get("kind") or e.get("tag"), "replay": e.get("replay"), "seg": e.get("seg")})
    return {"hour_key": p.get("hour_key"), "title": p.get("title"), "at": p.get("at"),
            "since": p.get("since"), "until": p.get("until"), "elements": els}


def digest(x: Any) -> str:
    return hashlib.sha1(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:12]


def record(args: argparse.Namespace) -> Path:
    data = Path(args.data)
    st = Station(args.base, args.key)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fh = open(out, "a", encoding="utf-8")

    def emit(kind: str, body: Any) -> None:
        fh.write(json.dumps({"k": kind, "t": round(time.time(), 3), "b": body}, default=str) + "\n")
        fh.flush()

    led = Tail(data / "script_ledger.jsonl", back=args.back_bytes)
    air_path = data / "air_log.jsonl"
    air_seen: dict[str, tuple] = {}
    air_rows: dict[str, dict[str, Any]] = {}
    air_mtime = 0.0
    last = {"dj": "", "tree": {}, "view": "", "tree_at": 0.0, "view_at": 0.0, "dj_beat": 0.0}
    segs: dict[str, float] = {}         # segment id -> last time a row for it was seen
    now_seg = ""
    entries: dict[str, tuple[float, float]] = {}
    end = time.time() + args.minutes * 60.0
    emit("start", {"minutes": args.minutes, "base": args.base, "data": str(data)})
    # prime the air log so only CHANGES are recorded (the tail window is 900 kB)
    try:
        with open(air_path, "rb") as f:
            f.seek(max(0, air_path.stat().st_size - 900_000))
            for ln in f.read().split(b"\n")[1:]:
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("id"):
                    m = air_rows[str(d["id"])] = air_merge(air_rows.get(str(d["id"])), air_brief(d))
                    air_seen[str(d["id"])] = (m["aired"], m["air_at"], m["heard"])
        for m in air_rows.values():
            emit("air0", m)
        air_mtime = air_path.stat().st_mtime
    except OSError:
        pass
    id_to_seg: dict[str, str] = {}
    while time.time() < end:
        t0 = time.time()
        backlog = led.first
        for d in led.read():
            b = ledger_brief(d)
            if backlog:
                b["backlog"] = True        # written before the watch began: its write time is unknown
            emit("ledger", b)
            if b["seg"]:
                segs[b["seg"]] = t0
                id_to_seg[str(b["line_id"])] = b["seg"]
        try:
            m = air_path.stat().st_mtime
            if m != air_mtime:
                air_mtime = m
                fresh: dict[str, dict[str, Any]] = {}
                with open(air_path, "rb") as f:
                    f.seek(max(0, air_path.stat().st_size - 900_000))
                    for ln in f.read().split(b"\n")[1:]:
                        try:
                            d = json.loads(ln)
                        except ValueError:
                            continue
                        if isinstance(d, dict) and d.get("id"):
                            fresh[str(d["id"])] = air_merge(fresh.get(str(d["id"])), air_brief(d))
                for lid, b in fresh.items():
                    b = air_rows[lid] = air_merge(air_rows.get(lid), b)
                    sig = (b["aired"], b["air_at"], b["heard"])
                    if air_seen.get(lid) != sig:
                        air_seen[lid] = sig
                        emit("air", b)
        except OSError:
            pass
        try:
            dj = st.get("/api/dj", timeout=10.0)
            sn = dj.get("stream_now") or {}
            sp = dj.get("speaking_now") or {}
            body = {"stream_now": {"at": sn.get("at"), "length": sn.get("length"),
                                   "rows": [{"id": r.get("id"), "from": r.get("from"), "until": r.get("until"),
                                             "kind": r.get("kind"), "who": r.get("who"), "aired": r.get("aired")}
                                            for r in sn.get("rows") or []]} if sn else None,
                    "speaking_now": {"id": sp.get("id"), "kind": sp.get("kind"), "who": sp.get("who"),
                                     "ts": sp.get("ts")} if sp else None,
                    "paused": dj.get("paused"), "server_ms": dj.get("server_ms"),
                    "talk_next_in": dj.get("talk_next_in")}
            dg = digest({k: body[k] for k in ("stream_now", "speaking_now", "paused")})
            if dg != last["dj"] or t0 - last["dj_beat"] > 30:
                last["dj"], last["dj_beat"] = dg, t0
                emit("now", body)
            sid = (sp or {}).get("id")
            if sid and str(sid) in id_to_seg:
                now_seg = id_to_seg[str(sid)]
        except Exception as exc:  # noqa: BLE001
            emit("error", {"what": "dj", "err": "%s: %s" % (type(exc).__name__, exc)})
        if t0 - last.get("dir_at", 0.0) > DIR_EVERY:
            last["dir_at"] = t0
            try:
                dr = st.get("/api/director", timeout=40.0)
                body = [{k: x.get(k) for k in ("occurrence", "ordinal", "kind", "label", "start", "deadline", "state")}
                        for x in dr.get("entries") or []]
                dg = digest(body)
                if dg != last.get("dir"):
                    last["dir"] = dg
                    emit("director", {"hour": dr.get("hour"), "entries": body})
                for x in body:
                    if x.get("start") and x.get("deadline"):
                        entries[str(x.get("occurrence"))] = (float(x["start"]), float(x["deadline"]))
            except Exception as exc:  # noqa: BLE001
                emit("error", {"what": "director", "err": "%s: %s" % (type(exc).__name__, exc)})
        if t0 - last["tree_at"] > TREE_EVERY:
            last["tree_at"] = t0
            want = [s for s, at in sorted(segs.items(), key=lambda kv: -kv[1]) if t0 - at < 900][:2]
            if now_seg and now_seg not in want:
                want.append(now_seg)
            # and the entries on air now and just before: the trees a hearing is judged against
            for occ, (a0, a1) in entries.items():
                if a0 - 5 <= t0 < a1 + 300 and occ not in want:
                    want.append(occ)
            for sg in want:
                try:
                    tr = tree_brief(st.get("/api/script/segment/%s/decision-tree" % urllib.request.quote(sg, safe=""), timeout=40.0))
                    dg = digest(tr)
                    if last["tree"].get(sg) != dg:
                        last["tree"][sg] = dg
                        emit("tree", tr)
                except Exception as exc:  # noqa: BLE001
                    emit("error", {"what": "tree", "seg": sg, "err": "%s: %s" % (type(exc).__name__, exc)})
        if t0 - last["view_at"] > VIEW_EVERY:
            last["view_at"] = t0
            try:
                idx = st.get("/api/screenplay")
                hours = idx.get("hours") or []
                for h in hours[:1]:
                    vb = view_brief(st.get("/api/screenplay/%s" % h.get("key"), timeout=40.0))
                    dg = digest(vb)
                    if dg != last["view"]:
                        last["view"] = dg
                        emit("view", vb)
            except Exception as exc:  # noqa: BLE001
                emit("error", {"what": "view", "err": "%s: %s" % (type(exc).__name__, exc)})
        time.sleep(max(0.2, DJ_EVERY - (time.time() - t0)))
    emit("end", {})
    fh.close()
    return out


# --------------------------------------------------------------------------- analyze
def load(path: Path) -> list[dict[str, Any]]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def entry_at(entries: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    """The hour entry whose window holds `t` (the director's running order)."""
    for x in entries:
        try:
            if float(x.get("start") or 0) <= t < float(x.get("deadline") or 0):
                return x
        except (TypeError, ValueError):
            continue
    return None


def lis_keep(keys: list[Any]) -> set[int]:
    """Indexes of one longest strictly ascending subsequence of `keys`."""
    import bisect
    tails: list[Any] = []
    tidx: list[int] = []
    prev = [-1] * len(keys)
    for i, k in enumerate(keys):
        j = bisect.bisect_left(tails, k)
        if j == len(tails):
            tails.append(k)
            tidx.append(i)
        else:
            tails[j], tidx[j] = k, i
        prev[i] = tidx[j - 1] if j > 0 else -1
    out: set[int] = set()
    i = tidx[-1] if tidx else -1
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out


def analyze(events: list[dict[str, Any]], fill: list[dict[str, Any]] | None = None,
            air_fill: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`fill`: ledger rows read from the file afterwards, for rows the recording
    missed (their write time is unknown, so they are never judged "late")."""
    t_start = next((e["t"] for e in events if e["k"] == "start"), events[0]["t"] if events else 0)
    t_end = max((e["t"] for e in events), default=t_start)
    ledger: dict[str, dict[str, Any]] = {}          # line_id -> brief + seen
    for e in events:
        if e["k"] == "ledger" and e["b"].get("line_id"):
            b = dict(e["b"], seen=None if e["b"].get("backlog") or e["t"] <= t_start + 1 else e["t"])
            ledger.setdefault(str(b["line_id"]), b)
    for d in fill or []:
        if d.get("line_id") and str(d["line_id"]) not in ledger:
            ledger[str(d["line_id"])] = dict(ledger_brief(d), seen=None, filled=True)
    air: dict[str, dict[str, Any]] = {}             # id -> latest brief + first seen per state
    before: dict[str, dict[str, Any]] = {}          # the air log as it stood at the start
    for e in events:
        if e["k"] == "air0":
            before[str(e["b"]["id"])] = e["b"]
    for d in air_fill or []:
        if d.get("id"):
            before[str(d["id"])] = air_merge(before.get(str(d["id"])), air_brief(d))
    for e in events:
        if e["k"] != "air":
            continue
        b = e["b"]
        a = air.setdefault(str(b["id"]), {"states": {}, "first": e["t"]})
        a.update({k: v for k, v in b.items() if v is not None})
        a["states"].setdefault(str(b.get("aired")), e["t"])
    # sounding: from stream_now, each row's start on the server clock
    sounded: dict[str, list[float]] = {}
    batches: list[dict[str, Any]] = []
    seen_batch: set = set()
    speaking: list[tuple[float, str]] = []
    for e in events:
        if e["k"] != "now":
            continue
        sn = e["b"].get("stream_now") or {}
        bkey = tuple(str(r.get("id")) for r in sn.get("rows") or []) if sn else ()
        if bkey and bkey not in seen_batch and sn.get("at"):
            seen_batch.add(bkey)
            batches.append(dict(sn, seen=e["t"]))
            for r in sn.get("rows") or []:
                sounded.setdefault(str(r["id"]), []).append(float(sn["at"]) + float(r.get("from") or 0))
        sp = e["b"].get("speaking_now") or {}
        speaking.append((e["t"], str(sp.get("id") or "")))
    # per line: when did the ear get it
    heard: dict[str, float] = {}
    for lid, a in air.items():
        if a.get("heard"):
            heard[lid] = float(a["heard"])
        elif "stream" in a["states"] and a.get("air_at"):
            heard[lid] = float(a["air_at"])
    for lid, ts in sounded.items():
        heard.setdefault(lid, min(ts))
    heard_all = dict(heard)
    for lid, b in before.items():
        if lid not in heard_all and (b.get("heard") or b.get("aired") == "stream"):
            heard_all[lid] = float(b.get("heard") or b.get("air_at") or 0)
    heard = {k: v for k, v in heard.items() if t_start - 5 <= v <= t_end + 5}
    F: dict[str, list[Any]] = {c: [] for c in (
        "out_of_order", "insert_out_of_place", "skipped", "duplicated", "re_aired", "aired_unscripted", "written_after_air", "filed_after_heard",
        "unscripted_flag", "tree_missing_stage", "tree_wrong_state", "tree_order_or_speaker",
        "view_stalled", "heard_without_position", "view_missing_line", "view_order", "segment_title", "segment_filed")}
    director: list[dict[str, Any]] = []
    for e in events:
        if e["k"] == "director":
            have = {x.get("occurrence") for x in director}
            director.extend(x for x in e["b"].get("entries") or [] if x.get("occurrence") not in have)
    # 1. order: heard sequence of ledgered lines must be ascending (block, ord). The
    # lines OUTSIDE the longest ascending run are the ones out of place (one early
    # line does not make every later line "late").
    seq = sorted(((t, lid) for lid, t in heard.items() if lid in ledger), key=lambda x: x[0])
    keys = [(ledger[lid]["block"], ledger[lid]["ord"]) for _t, lid in seq]
    keep = lis_keep(keys)
    for j, (t, lid) in enumerate(seq):
        if j in keep:
            continue
        prev = seq[j - 1][1] if j else ""
        # a line nothing wrote down in advance (scripted: false) is numbered when it is
        # HEARD (#1339), after rounds written ahead of it: an insert, not a scripted jump
        cls = "insert_out_of_place" if ledger[lid].get("scripted") is False else "out_of_order"
        F[cls].append({"line": lid, "key": keys[j], "kind": ledger[lid]["kind"],
                                  "round": ledger[lid]["round"], "scripted": ledger[lid].get("scripted"),
                                  "after": prev, "after_key": keys[j - 1] if j else None,
                                  "filed_minus_heard_s": round(float(ledger[lid].get("at") or 0) - t, 1)})
    # 2. skipped: a written row whose block had later rows heard, never heard itself
    by_block: dict[Any, list[dict[str, Any]]] = {}
    for lid, b in ledger.items():
        by_block.setdefault(b["block"], []).append(b)
    for blk, rows in by_block.items():
        rows.sort(key=lambda r: r["ord"])
        heard_ords = [r["ord"] for r in rows if r["line_id"] in heard_all]
        if not any(r["line_id"] in heard for r in rows):
            continue
        last_h = max(heard_all[r["line_id"]] for r in rows if r["line_id"] in heard_all)
        for r in rows:
            if r["line_id"] not in heard_all and r["ord"] < max(heard_ords) and t_end - last_h > 5:
                st = (air.get(r["line_id"]) or {}).get("aired")
                F["skipped"].append({"line": r["line_id"], "block": blk, "ord": r["ord"], "kind": r["kind"],
                                     "who": r["who"], "air_state": st, "text": r["text"][:50]})
    # 3. duplicated: a line id sounded in two batches
    for lid, ts in sounded.items():
        uniq = sorted(set(round(x, 1) for x in ts))
        if len(uniq) > 1 and uniq[-1] - uniq[0] > 5:
            F["duplicated"].append({"line": lid, "times": uniq})
    # 3b. re-aired: a ledgered replay round, or the same words heard twice in the window
    for lid, b in ledger.items():
        if b.get("replay") and lid in heard:
            F["re_aired"].append({"line": lid, "block": b["block"], "airing": b["replay"].get("airing"),
                                  "conv": b.get("conv"), "text": b["text"][:50]})
    # 4. unscripted / late rows
    for lid, t in heard.items():
        a = air.get(lid) or {}
        if lid not in ledger:
            if a.get("first", 0) >= t_start + 60 or lid in sounded:
                F["aired_unscripted"].append({"line": lid, "kind": a.get("kind"), "who": a.get("who"),
                                              "round": a.get("round"), "text": str(a.get("text") or "")[:50]})
        else:
            b = ledger[lid]
            wrote = b["seen"] if b["seen"] is not None else float(b.get("at") or 0)
            if wrote > t + 2 or (b.get("at") and float(b["at"]) > t + 2):
                F["filed_after_heard" if b.get("scripted") is False else "written_after_air"].append({"line": lid, "late_s": round(max(wrote, float(b.get("at") or 0)) - t, 1),
                                               "kind": b["kind"], "scripted": b.get("scripted")})
            if b.get("scripted") is False:
                F["unscripted_flag"].append({"line": lid, "kind": b["kind"], "block": b["block"]})
    # 5. the tree vs the script and the air (latest tree per segment)
    trees: dict[str, dict[str, Any]] = {}
    for e in events:
        if e["k"] == "tree":
            trees[str(e["b"]["segment_id"])] = dict(e["b"], seen=e["t"])
    stage_of: dict[str, tuple[str, dict[str, Any], int, str]] = {}
    for sg, tr in trees.items():
        for r in tr.get("rounds") or []:
            pos = 0
            for el in r.get("elements") or []:
                if el["t"] == "s":
                    pos += 1
                    for x in (el.get("line_ids") or ([el["line_id"]] if el.get("line_id") else [])):
                        stage_of[str(x)] = (sg, el, pos, str(r.get("conv")))
    tree_snaps: dict[str, list[tuple[float, set]]] = {}
    for e in events:
        if e["k"] == "tree":
            ids = set()
            for r in e["b"].get("rounds") or []:
                for el in r.get("elements") or []:
                    if el["t"] == "s":
                        ids.update(str(x) for x in (el.get("line_ids") or ([el["line_id"]] if el.get("line_id") else [])))
            tree_snaps.setdefault(str(e["b"]["segment_id"]), []).append((e["t"], ids))
    for lid, t in heard.items():
        b = ledger.get(lid)
        if not b or not b.get("turn_id") or b["kind"] != "dialogue":
            continue
        onair = entry_at(director, t)
        occ = str((onair or {}).get("occurrence") or "")
        # judged against a tree of the entry it went out in, drawn at least 30 s after it was heard
        snaps = [ids for at, ids in tree_snaps.get(occ, []) if at > t + 30]
        if not onair or not snaps:
            continue
        if lid not in snaps[-1]:
            where = [sg for sg, lst in tree_snaps.items() if lst and lid in lst[-1][1]]
            F["tree_missing_stage"].append({"line": lid, "went_out_in": occ, "went_out_label": onair.get("label"),
                                            "filed": b.get("seg"), "in_tree_of": where,
                                            "conv": b.get("conv"), "replay": bool(b.get("replay"))})
            continue
        _sg, el, pos, conv = stage_of.get(lid, (None, {}, 0, ""))
        if el and heard[lid] < trees.get(occ, {}).get("seen", 0) - 30 and el.get("state") != "aired":
            F["tree_wrong_state"].append({"line": lid, "seg": occ, "tree_state": el.get("state"), "turn_id": el.get("turn_id")})
        who = str(b.get("who") or "")
        spk = str((el or {}).get("speaker") or "")
        seat = SEAT_OF.get(who, who)
        if spk and who and spk != seat and spk != who and not b.get("listening") \
                and not (spk == "C" and who in ("third", "caller", "caller2")):
            F["tree_order_or_speaker"].append({"line": lid, "why": "speaker", "tree": spk, "script": who})
    # turn order: inside one conversation the tree's stage order must follow the script's (block, ord)
    for sg, tr in trees.items():
        for r in tr.get("rounds") or []:
            keys = []
            for el in r.get("elements") or []:
                if el["t"] == "s" and el.get("line_id") and str(el["line_id"]) in ledger:
                    b = ledger[str(el["line_id"])]
                    keys.append(((b["block"], b["ord"]), el["line_id"]))
            for (k1, l1), (k2, l2) in zip(keys, keys[1:]):
                if k2 < k1:
                    F["tree_order_or_speaker"].append({"line": l2, "why": "order", "tree_after": l1,
                                                       "script": [k1, k2], "conv": r.get("conv")})
    # 6. the view: every heard ledgered line must be on the page, in (block, ord) order; the position must move
    views = [e for e in events if e["k"] == "view"]
    last_of: dict[str, dict[str, Any]] = {}
    for e in views:
        last_of[str(e["b"].get("hour_key"))] = e       # the latest page of each hour
        if not e["b"].get("since"):                    # an older recording: the hour from its first element
            ats = [float(x["at"]) for x in e["b"]["elements"] if x.get("at")]
            if ats:
                e["b"]["since"] = min(ats) // 3600 * 3600
                e["b"]["until"] = e["b"]["since"] + 3600
    page_lines: dict[str, float] = {}
    for e in last_of.values():
        for el in e["b"]["elements"]:
            if el["t"] in ("d", "a") and el.get("line"):
                page_lines.setdefault(str(el["line"]), e["t"])
    newest = max((e["t"] for e in views), default=0)
    for lid, t in heard.items():
        # judged only when a page drawn at least a minute after the hearing could hold it
        if lid in ledger and lid not in page_lines and any(
                e["t"] > t + 60 and (not e["b"].get("since") or e["b"]["since"] <= t < e["b"]["until"])
                for e in last_of.values()) and t < newest - 60:
            F["view_missing_line"].append({"line": lid, "kind": ledger[lid]["kind"], "block": ledger[lid]["block"]})
    for hk, lastv in sorted(last_of.items(), key=lambda kv: kv[1]["t"]):
        on_page = {}
        for i, el in enumerate(lastv["b"]["elements"]):
            if el["t"] in ("d", "a") and el.get("line"):
                on_page.setdefault(str(el["line"]), (i, el))
        # the page must read in the order the ear heard it (3 s of stamp slack)
        seqp = [(i, el) for i, el in sorted(on_page.values(), key=lambda x: x[0]) if str(el["line"]) in heard]
        for (i1, e1), (i2, e2) in zip(seqp, seqp[1:]):
            h1, h2 = heard[str(e1["line"])], heard[str(e2["line"])]
            if h2 < h1 - 3:
                F["view_order"].append({"line": e2["line"], "heard_s_before_line_above": round(h1 - h2, 1),
                                        "above": e1["line"], "kind": e2.get("kind"), "above_kind": e1.get("kind")})
        # 7. titles: a scene heading must name the hour entry that was on air when it was heard
        scene, first = None, None
        for el in lastv["b"]["elements"] + [{"t": "scene"}]:
            if el["t"] == "scene":
                if scene is not None and first is not None:
                    onair = entry_at(director, first[1])
                    slot = scene.get("slot") or {}
                    named = {slot.get("id"), (slot.get("aired_in") or {}).get("id")}   # [seg-aired-in]
                    if onair and onair.get("occurrence") not in named:
                        F["segment_title"].append({"line": first[0], "scene": scene.get("text"),
                                                   "slot": slot.get("label"), "slot_how": slot.get("how"),
                                                   "slot_id": slot.get("id"), "on_air": onair.get("label"),
                                                   "on_air_id": onair.get("occurrence")})
                scene, first = el, None
                continue
            if scene is not None and first is None and el["t"] in ("d", "a") and str(el.get("line")) in heard:
                first = (el["line"], heard[str(el["line"])])
    # 8. filing: the segment a heard line is filed under (ledger + System 3's register) must be the one on air
    for lid, t in heard.items():
        b = ledger.get(lid)
        onair = entry_at(director, t)
        if not b or not onair:
            continue
        if b.get("seg") != onair.get("occurrence"):
            F["segment_filed"].append({"line": lid, "filed": b.get("seg"), "filed_label": b.get("seg_label"),
                                       "on_air": onair.get("occurrence"), "on_air_label": onair.get("label"),
                                       "heard_minus_filed_s": round(t - float(b.get("at") or t), 1),
                                       "kind": b.get("kind"), "replay": bool(b.get("replay"))})
    # a line the ear got that the Script view was never given a place for: no stream_now
    # row and no speaking_now named it while the watch was polling (every 2 s)
    placed = set(sounded) | {sid for _t, sid in speaking if sid}
    polled = sorted(e["t"] for e in events if e["k"] == "now")
    for lid, t in heard.items():
        a = air.get(lid) or {}
        if lid in placed or not polled or not (polled[0] + 2 < t < polled[-1] - 10):
            continue
        F["heard_without_position"].append({"line": lid, "kind": a.get("kind") or (ledger.get(lid) or {}).get("kind"),
                                            "by": a.get("by"), "heard": round(t, 1),
                                            "text": str(a.get("text") or "")[:50]})
    # stalls: the clock outran every stream_now batch while the air log recorded hearings
    batches.sort(key=lambda b: float(b["at"]))
    covered = [(float(b["at"]), float(b["at"]) + float(b.get("length") or 0)) for b in batches]
    heard_times = sorted(heard.values())
    for (a0, a1), (b0, _b1) in zip(covered, covered[1:]):
        if b0 - a1 > 8:
            inside = [t for t in heard_times if a1 + 1 < t < b0 - 1]
            if inside:
                F["view_stalled"].append({"from": round(a1, 1), "to": round(b0, 1), "gap_s": round(b0 - a1, 1),
                                          "heard_inside": len(inside)})
    counts = {k: len(v) for k, v in F.items()}
    segs = sorted({b["seg"] for b in ledger.values() if b.get("seg")})
    return {"window": [t_start, t_end], "minutes": round((t_end - t_start) / 60.0, 1),
            "ledger_rows": len(ledger), "heard": len(heard), "batches": len(batches),
            "segments": segs, "trees": {k: len(v.get("rounds") or []) for k, v in trees.items()},
            "views": len(views), "counts": counts, "flags": F}


def verdict(rep: dict[str, Any], examples: int = 3) -> str:
    lines = ["script watch: %.1f min, %d rows written, %d lines heard, %d stream batches, %d segments %s"
             % (rep["minutes"], rep["ledger_rows"], rep["heard"], rep["batches"], len(rep["segments"]),
                rep["segments"])]
    for k, n in rep["counts"].items():
        ex = rep["flags"][k][:examples]
        lines.append("  %-22s %4d  %s" % (k, n, json.dumps(ex, default=str)[:400] if n else ""))
    bad = sum(n for k, n in rep["counts"].items() if k not in INFO)
    lines.append("VERDICT: %s" % ("the script unfolded entry to entry" if not bad else "%d divergences" % bad))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--data", default="/app/data" if Path("/app/data").is_dir() else "data")
    ap.add_argument("--base", default=os.environ.get("SPARK_AGENT_URL", "http://127.0.0.1:8096"))
    ap.add_argument("--key", default=os.environ.get("SPARK_AGENT_API_KEY", ""))
    ap.add_argument("--out", default="/tmp/script_watch/watch-%d.jsonl" % int(time.time()))
    ap.add_argument("--back-bytes", type=int, default=400_000, help="ledger read-back at start")
    ap.add_argument("--analyze", default="", help="skip recording; judge this recording")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    ap.add_argument("--fill-air", default="", help="with --fill: the air log, for hearings before the window")
    ap.add_argument("--fill", default="", help="with --analyze: a ledger file to fill rows the recording missed")
    a = ap.parse_args(argv)
    try:
        path = Path(a.analyze) if a.analyze else record(a)
        fill = []
        if a.fill:
            ev = load(path)
            lo = min((e["t"] for e in ev), default=0) - 3600
            fill = [d for d in load(Path(a.fill)) if float(d.get("at") or 0) >= lo]
            air_fill = load(Path(a.fill_air)) if a.fill_air else []
            rep = analyze(ev, fill, air_fill)
        else:
            rep = analyze(load(path))
    except Exception as exc:  # noqa: BLE001
        print("script watch could not run: %s: %s" % (type(exc).__name__, exc))
        return 2
    print(json.dumps(rep, indent=1, default=str) if a.json else verdict(rep))
    print("recording: %s" % path)
    return 1 if sum(n for k, n in rep["counts"].items() if k not in INFO) else 0


if __name__ == "__main__":
    sys.exit(main())
