#!/usr/bin/env python3
"""#1477: how evenly loud are the clips the station actually hands out?

Fetches N clips THROUGH THE STATION - `/sfx/{id}`, the one door every
surface plays a clip through - exactly as a surface would get them, and
prints each one's EBU R128 integrated loudness (LUFS) and true peak
(dBTP), then the spread. Nothing on the station is changed by it, except
that under #1477 a clip nobody has levelled yet is levelled by the fetch,
which is what a listener's first play of it would do too.

The default set is the last 15 clips that aired (/api/sfx/history) and 15
drawn at random from the pool (siblings of those clips' folders, and the
play-count table). Save the set with --save-ids and read it back with
--ids to compare the SAME clips before and after a change:

    # inside the container (it has the key and an ffmpeg):
    docker exec spark-agent python3 /app/tools/sfx_loudness_audit.py \\
        --save-ids /app/data/sfx_audit_ids.json
    # ...restart...
    docker exec spark-agent python3 /app/tools/sfx_loudness_audit.py \\
        --ids /app/data/sfx_audit_ids.json

    # or from the host: --base http://127.0.0.1:8096, and the key from
    # --key, $SPARK_AGENT_API_KEY, or `docker exec spark-agent printenv`.

--json prints one machine-readable object instead of the table.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

TARGET = float(os.getenv("SFX_TARGET_LUFS", "-20"))
CEILING = float(os.getenv("SFX_TP_DB", "-6"))


def find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg") or ""


def find_key(given: str) -> str:
    if given:
        return given
    if os.getenv("SPARK_AGENT_API_KEY"):
        return os.environ["SPARK_AGENT_API_KEY"]
    if shutil.which("docker"):
        try:
            return subprocess.run(["docker", "exec", "spark-agent", "printenv",
                                   "SPARK_AGENT_API_KEY"], capture_output=True,
                                  text=True, timeout=20).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return ""


class Station:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.key = key

    def request(self, path: str, timeout: float = 60.0):
        req = urllib.request.Request(self.base + path)
        if self.key:
            req.add_header("Authorization", "Bearer " + self.key)
        return urllib.request.urlopen(req, timeout=timeout)

    def json(self, path: str, timeout: float = 60.0):
        with self.request(path, timeout) as got:
            return json.loads(got.read().decode("utf-8", "replace"))


def measure(ffmpeg: str, path: str) -> dict:
    run = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-i", path,
                          "-map", "0:a:0", "-af",
                          "apad=whole_dur=0.5,ebur128=peak=true:framelog=quiet",
                          "-f", "null", "-"], capture_output=True, text=True,
                         errors="replace", timeout=120)
    log = run.stderr or ""
    if run.returncode != 0:
        return {"error": "no sound track" if "matches no streams" in log
                else "ffmpeg %d" % run.returncode}
    tail = log[log.rfind("Summary:"):]
    level = re.search(r"I:\s*(-?(?:inf|[\d.]+))\s*LUFS", tail)
    peak = re.search(r"True peak:\s*Peak:\s*(-?(?:inf|[\d.]+))", tail)
    if not level:
        return {"error": "no loudness summary"}
    return {"i": float(level.group(1)),
            "tp": float(peak.group(1)) if peak else None}


def pick_ids(station: Station, aired_n: int, pool_n: int, seed: int) -> list[dict]:
    rows = station.json("/api/sfx/history?limit=200").get("rows") or []
    aired, seen = [], set()
    for row in rows:
        sid = str(row.get("id") or "")
        if sid and sid not in seen:
            seen.add(sid)
            aired.append({"id": sid, "name": str(row.get("name") or ""),
                          "from": "aired", "video": bool(row.get("video"))})
        if len(aired) >= aired_n:
            break
    pool, pool_seen = [], set(seen)
    rng = random.Random(seed)
    folders = [r["id"] for r in aired]
    rng.shuffle(folders)
    for of in folders[:6]:
        try:
            got = station.json("/api/sfx/dir?of=%s" % of)
        except Exception:  # noqa: BLE001
            continue
        for row in got.get("samples") or []:
            sid = str(row.get("id") or "")
            if sid and sid not in pool_seen and not row.get("banned"):
                pool_seen.add(sid)
                pool.append({"id": sid, "name": str(row.get("name") or ""),
                             "from": "pool", "video": bool(row.get("video"))})
    try:
        for row in station.json("/api/sfx/stats").get("samples") or []:
            sid = str(row.get("id") or "")
            if sid and sid not in pool_seen and not row.get("banned"):
                pool_seen.add(sid)
                pool.append({"id": sid, "name": str(row.get("name") or ""),
                             "from": "pool", "video": None})
    except Exception:  # noqa: BLE001
        pass
    rng.shuffle(pool)
    return aired + pool[:pool_n]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.getenv("SFX_AUDIT_BASE", "http://127.0.0.1:8096"))
    ap.add_argument("--key", default="")
    ap.add_argument("--aired", type=int, default=15)
    ap.add_argument("--pool", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1477)
    ap.add_argument("--ids", default="", help="read the clip set from this file")
    ap.add_argument("--save-ids", default="", help="write the clip set to this file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("no ffmpeg here (imageio_ffmpeg or PATH)", file=sys.stderr)
        return 2
    station = Station(args.base, find_key(args.key))
    if args.ids:
        with open(args.ids, encoding="utf-8") as handle:
            clips = json.load(handle)
    else:
        clips = pick_ids(station, args.aired, args.pool, args.seed)
    if args.save_ids:
        with open(args.save_ids, "w", encoding="utf-8") as handle:
            json.dump(clips, handle, indent=1)

    room = tempfile.mkdtemp(prefix="sfx-audit-")
    results = []
    try:
        for clip in clips:
            row = dict(clip)
            began = time.monotonic()
            try:
                with station.request("/sfx/%s" % clip["id"], timeout=90) as got:
                    body = got.read()
                    kind = got.headers.get("Content-Type", "")
                    cache = got.headers.get("Cache-Control", "")
            except urllib.error.HTTPError as exc:
                row.update(error="HTTP %d" % exc.code)
                results.append(row)
                continue
            except Exception as exc:  # noqa: BLE001
                row.update(error=type(exc).__name__)
                results.append(row)
                continue
            row["fetch_ms"] = int((time.monotonic() - began) * 1000)
            row["bytes"] = len(body)
            row["type"] = kind
            # #1420/#1477: the route gives a clip it sent AS SHOT (never
            # levelled yet, or looked at and left alone) a short cache life.
            row["as_shot"] = "max-age=60" in cache
            suffix = {"video/mp4": ".mp4", "audio/wav": ".wav", "audio/x-wav": ".wav",
                      "audio/mpeg": ".mp3", "video/webm": ".webm",
                      "video/quicktime": ".mov"}.get(kind.split(";")[0].strip(), ".bin")
            path = os.path.join(room, clip["id"] + suffix)
            with open(path, "wb") as handle:
                handle.write(body)
            row.update(measure(ffmpeg, path))
            results.append(row)
            os.unlink(path)
    finally:
        shutil.rmtree(room, ignore_errors=True)

    levels = [r["i"] for r in results if isinstance(r.get("i"), float) and r["i"] > -69]
    peaks = [r["tp"] for r in results if isinstance(r.get("tp"), float)]
    summary = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "clips": len(results), "measured": len(levels),
        "target_lufs": TARGET, "ceiling_dbtp": CEILING,
        "spread_lu": round(max(levels) - min(levels), 1) if len(levels) > 1 else None,
        "min_lufs": round(min(levels), 1) if levels else None,
        "max_lufs": round(max(levels), 1) if levels else None,
        "mean_lufs": round(statistics.fmean(levels), 1) if levels else None,
        "stdev_lu": round(statistics.pstdev(levels), 2) if len(levels) > 1 else None,
        "outside_1_5_lu": sum(1 for x in levels if abs(x - TARGET) > 1.5),
        "over_ceiling": sum(1 for x in peaks if x > CEILING + 1e-9),
        "worst_tp": round(max(peaks), 1) if peaks else None,
        "sent_as_shot": sum(1 for r in results if r.get("as_shot")),
    }
    try:
        summary["levelled"] = station.json("/api/sfx/video/mode").get("levelled")
    except Exception:  # noqa: BLE001
        summary["levelled"] = None
    if args.json:
        print(json.dumps({"summary": summary, "clips": results}, indent=1))
        return 0
    print("%-6s %-16s %-40s %8s %7s %7s %6s" % ("from", "id", "name", "LUFS", "dBTP",
                                               "fetch", "sent"))
    for r in results:
        if "i" in r:
            print("%-6s %-16s %-40s %8.1f %7s %6dms %6s" % (
                r.get("from", ""), r["id"], r.get("name", "")[:40], r["i"],
                "%.1f" % r["tp"] if r.get("tp") is not None else "-",
                r.get("fetch_ms", 0), "shot" if r.get("as_shot") else "copy"))
        else:
            print("%-6s %-16s %-40s   %s" % (r.get("from", ""), r["id"],
                                            r.get("name", "")[:40], r.get("error")))
    print("\nspread %s LU (%s .. %s LUFS), mean %s, stdev %s; %d of %d outside "
          "+-1.5 LU of %.0f; %d over %.0f dBTP (worst %s); %d sent as shot "
          "(unlevelled or left alone)"
          % (summary["spread_lu"], summary["min_lufs"], summary["max_lufs"],
             summary["mean_lufs"], summary["stdev_lu"], summary["outside_1_5_lu"],
             summary["measured"], TARGET, summary["over_ceiling"], CEILING,
             summary["worst_tp"], summary["sent_as_shot"]))
    print("station says: %s" % json.dumps(summary["levelled"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
