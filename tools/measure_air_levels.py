"""MEASURE THE AIR. Record N seconds of the broadcast stream, read its short-term loudness second by
second, and lay the air log over it: what level did the SFX stings, the DJs' lines and the records
actually go out at? Runs inside the container:  docker exec -i spark-agent python3 - SECONDS < airlevel.py"""
import json, os, re, subprocess, sys, time, statistics
FF = "/usr/local/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2"
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 240
KEY = os.environ.get("SPARK_AGENT_API_KEY", "")
url = "http://127.0.0.1:8096/stream.mp3"
t0 = time.time()
cmd = [FF, "-hide_banner", "-nostats", "-headers", "Authorization: Bearer %s\r\n" % KEY, "-i", url, "-t", str(SECONDS), "-af", "ebur128", "-f", "null", "-"]
err = subprocess.run(cmd, capture_output=True, text=True, timeout=SECONDS + 90).stderr
rows = [(float(a), float(b)) for a, b in re.findall(r"\bt:\s*([0-9.]+)\s+TARGET:[^M]*M:\s*(-?[0-9.]+)", err)]
if not rows:
    print("no loudness lines; ffmpeg said:", err[-600:]); sys.exit(1)
print("recorded %.0f s of /stream.mp3 from %s" % (rows[-1][0], time.strftime("%H:%M:%S", time.localtime(t0))))
# the air log for the same window
air = []
with open("/app/data/air_log.jsonl", "rb") as f:
    f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 4_000_000))
    for line in f.read().decode("utf-8", "replace").splitlines()[1:]:
        try: d = json.loads(line)
        except Exception: continue
        at = d.get("air_at") or 0
        if t0 - 5 <= at <= t0 + SECONDS + 5:
            air.append(d)
print("air log entries in the window:", len(air))
def level_between(a, b):
    vals = [m for t, m in rows if a <= t <= b and m > -60]
    return statistics.median(vals) if vals else None
by_kind = {}
for d in sorted(air, key=lambda d: d.get("air_at") or 0):
    start = (d.get("air_at") or 0) - t0
    dur = float(d.get("seconds") or 0) or 3.0
    lv = level_between(start + 0.3, start + dur)
    if lv is None: continue
    kind = d.get("kind") or "?"
    by_kind.setdefault(kind, []).append(lv)
    print("  %6.1fs %-6s %-6s %5.1fs  M=%6.1f LUFS  %s" % (start, kind, (d.get("who") or "")[:6], dur, lv, (d.get("text") or "")[:60].replace("\n", " ")))
for kind, vals in by_kind.items():
    print("%-8s n=%2d  median %.1f  min %.1f  max %.1f  spread %.1f LU" % (kind, len(vals), statistics.median(vals), min(vals), max(vals), max(vals) - min(vals)))
allv = [m for t, m in rows if m > -60]
print("whole window: median %.1f LUFS, 10th pct %.1f, 90th pct %.1f" % (statistics.median(allv), sorted(allv)[len(allv)//10], sorted(allv)[len(allv)*9//10]))
