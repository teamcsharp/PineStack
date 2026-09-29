#!/usr/bin/env python3
"""[es-roads] The emotion engine's coverage meter: over the last N aired voice
lines (dj, cohost, caller, caller2, third), how many takes carried an
ES-shaped performance, per road, and how big the applied deltas were.

READ-ONLY. Reads data/screenplay_lines.jsonl (the air record), and for rows
aired before the [es-roads] stamp existed, reconstructs the answer from what
the station kept:

  stamp   row["perf"]["es"] (es_roads_patch): the road that shaped the take,
          the ES table/category/item/intensity, the voice block, whether the
          take audio carries it (baked) - or {"road", "none": why}.
  legacy  no stamp. The take is traced by its media file (air_log -> the
          pantry's and the sting cache's clip["es"], stamped by voice_generate
          since [s3-es-voice]) or, for a take made ahead, by its words and
          voice on the pantry shelf. "untraced" = neither kept the take.
  intent  (both) System 3's own record: the line's turn (system3.sqlite3
          `lines`, opened read-only) and whether that turn's ES row carried a
          voice - i.e. whether the take SHOULD have been shaped.

    python3 tools/es_coverage.py [--data data] [--n 400] [--json out.json]

Run it in the container (docker exec spark-agent python3 ...) or on a copy of
data/. It writes nothing but --json.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import statistics
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEATS = ("dj", "cohost", "caller", "caller2", "third")
KEYS = ("tempo", "pitch", "range", "energy", "pause", "temp")
NEUTRAL = {"tempo": 1.0, "pitch": 0.0, "range": 1.0, "energy": 0.0, "pause": 1.0, "temp": 0.0}
MULT = ("tempo", "range", "pause")


def tail_lines(path, limit_bytes):
    """The last `limit_bytes` of a JSONL file, whole lines only."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with open(path, "rb") as fh:
        fh.seek(max(0, size - limit_bytes))
        blob = fh.read()
    if size > limit_bytes:
        blob = blob.split(b"\n", 1)[-1]
    out = []
    for line in blob.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def words(text):
    return " ".join(re.findall(r"[a-z0-9']+", str(text or "").lower()))


def media_name(path):
    return str(path or "").rsplit("/", 1)[-1].split("?")[0]


def take_index(data):
    """media file -> clip es block ({} = a take without one), and
    (voice, words) -> es block, off the pantry and the sting cache."""
    by_media, by_words = {}, {}
    for name in ("pantry.json", "render_replay.json"):
        try:
            store = json.loads((data / name).read_text())
        except Exception:  # noqa: BLE001
            continue
        for val in store.values() if isinstance(store, dict) else []:
            if not isinstance(val, dict):
                continue
            clip = val.get("clip") if isinstance(val.get("clip"), dict) else val
            es = clip.get("es") if isinstance(clip.get("es"), dict) else {}
            m = media_name(clip.get("path"))
            if m:
                by_media[m] = es
            if val.get("text") and (val.get("voice") or clip.get("voice")):
                by_words[(str(val.get("voice") or clip.get("voice")), words(val["text"]))] = es
    return by_media, by_words


class Intent:
    """System 3's record of the line's turn, read-only and lazily."""

    def __init__(self, path):
        self.db = None
        self.convs = {}
        try:
            if path.is_file():
                self.db = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
        except Exception:  # noqa: BLE001
            self.db = None

    def turn(self, line_id):
        if self.db is None or not line_id:
            return None
        try:
            got = self.db.execute("SELECT conversation_id, turn_id FROM lines WHERE line_id=?",
                                  (line_id,)).fetchone()
            if not got:
                return None
            cid, tid = got
            if cid not in self.convs:
                row = self.db.execute("SELECT body, mode FROM conversations WHERE id=?", (cid,)).fetchone()
                conv = json.loads(zlib.decompress(row[0]).decode("utf-8")) if row else None
                self.convs[cid] = ({"mode": (row[1] if row else None) or (conv or {}).get("mode"),
                                    "turns": {str(t.get("turn_id")): t for t in (conv or {}).get("turns") or []}}
                                   if conv else None)
            conv = self.convs[cid]
            if not conv:
                return None
            t = conv["turns"].get(str(tid))
            if t is None:
                return {"mode": conv["mode"], "found": False}
            perf = t.get("performance") or {}
            if not perf.get("voice") and t.get("split_of"):
                perf = (conv["turns"].get(str(t.get("split_of"))) or {}).get("performance") or perf
            return {"mode": conv["mode"], "found": True, "voice": isinstance(perf.get("voice"), dict)
                    and bool(perf.get("voice")), "intensity": perf.get("intensity"),
                    "label": perf.get("emotion"), "category": perf.get("family")}
        except Exception:  # noqa: BLE001
            return None


def legacy_road(row):
    if int(row.get("burst") or 0) > 0:
        return "speak_turns/coalesced (legacy)"
    return "dj_speak:%s (legacy)" % (row.get("kind") or "?")


def size(block):
    """How far a voice block sits from neutral, per key (ratios as |v-1|)."""
    return {k: abs(float(block[k]) - NEUTRAL[k]) for k in KEYS if k in block}


def summarise(vals):
    if not vals:
        return None
    vals = sorted(vals)
    return {"n": len(vals), "median": round(statistics.median(vals), 3),
            "p90": round(vals[min(len(vals) - 1, int(0.9 * len(vals)))], 3), "max": round(vals[-1], 3)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    data = Path(a.data)
    rows = [r for r in tail_lines(data / "screenplay_lines.jsonl", 12_000_000)
            if r.get("who") in SEATS and (r.get("voice") or {}).get("engine")]
    rows = rows[-max(1, a.n):]
    air = {str(r.get("id")): r for r in tail_lines(data / "air_log.jsonl", 40_000_000)
           if r.get("who") in SEATS}
    by_media, by_words = take_index(data)
    intent = Intent(data / "system3.sqlite3")
    roads = collections.defaultdict(lambda: collections.Counter())
    deltas = collections.defaultdict(list)
    intensities, why_none = [], collections.Counter()
    lines = []
    for r in rows:
        stamp = (r.get("perf") or {}).get("es") if isinstance(r.get("perf"), dict) else None
        it = intent.turn(str(r.get("id") or ""))
        should = bool(it and it.get("found") and it.get("mode") == "active" and it.get("voice"))
        if isinstance(stamp, dict):
            road = str(stamp.get("road") or "?")
            block = stamp.get("voice") if isinstance(stamp.get("voice"), dict) else {}
            shaped = bool(block) and stamp.get("baked") is not False
            state = "shaped" if shaped else ("intended, not baked" if block else "none")
            if not block:
                why_none[str(stamp.get("none") or "?")[:80]] += 1
            if stamp.get("intensity") is not None:
                intensities.append(float(stamp["intensity"]))
        else:
            road = legacy_road(r)
            a_row = air.get(str(r.get("id") or "")) or {}
            block = None
            for m in (a_row.get("media"), a_row.get("clip_media")):
                if media_name(m) in by_media:
                    block = by_media[media_name(m)]
                    break
            if block is None:
                block = by_words.get((str((r.get("voice") or {}).get("voice") or ""),
                                      words(a_row.get("text") or "")))
            shaped = bool(block)
            state = "shaped" if shaped else ("untraced" if block is None else "plain take")
            block = block or {}
            if should and it.get("intensity") is not None:
                intensities.append(float(it["intensity"]))
        c = roads[road]
        c["lines"] += 1
        c[state] += 1
        c["should"] += 1 if should else 0
        c["should_and_shaped"] += 1 if (should and shaped) else 0
        if shaped:
            for k, v in size({k: v for k, v in block.items() if k in KEYS}).items():
                deltas[k].append(v)
        lines.append({"id": r.get("id"), "who": r.get("who"), "road": road, "state": state,
                      "should": should, "voice": {k: block.get(k) for k in KEYS if k in block}})
    total = collections.Counter()
    for c in roads.values():
        total.update(c)
    frac = (lambda n, d: round(n / d, 3) if d else None)
    out = {
        "lines": total["lines"], "window": [rows[0].get("at") if rows else None, rows[-1].get("at") if rows else None],
        "es_shaped_fraction": frac(total["shaped"], total["lines"]),
        "of_traced": frac(total["shaped"], total["lines"] - total["untraced"]),
        "should_have_es": total["should"],
        "should_and_shaped_fraction": frac(total["should_and_shaped"], total["should"]),
        "per_road": {road: dict(c, fraction=frac(c["shaped"], c["lines"]),
                                traced_fraction=frac(c["shaped"], c["lines"] - c["untraced"]))
                     for road, c in sorted(roads.items(), key=lambda kv: -kv[1]["lines"])},
        "applied_delta_size": {k: summarise(v) for k, v in deltas.items()},
        "intensity": summarise(intensities),
        "why_none": dict(why_none.most_common(8)),
    }
    if a.json:
        Path(a.json).write_text(json.dumps(dict(out, rows=lines), indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
