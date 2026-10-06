"""The FILES behind the last airings, measured in place: each sting's slice of its voice_media WAV and each
DJ line's render. Integrated loudness (ebur128 I) per file, so file level and mix level can be told apart.
docker exec -i spark-agent python3 - [N] < filelevel.py"""
import json, subprocess, re, os, sys, statistics, collections, time
FF = "/usr/local/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 24
MEDIA = "/app/data/voice_media"
raw = open("/app/data/air_log.jsonl", "rb").read()[-6000000:].decode("utf-8", "replace").splitlines()[1:]
rows = {"sfx": [], "call": []}
seen = set()
for line in reversed(raw):
    try: d = json.loads(line)
    except Exception: continue
    k = d.get("kind")
    if k not in rows or d.get("id") in seen or not d.get("air_at"): continue
    seen.add(d.get("id"))
    if len(rows[k]) < N: rows[k].append(d)
    if all(len(v) >= N for v in rows.values()): break

def measure(path, start=None, until=None):
    cmd = [FF, "-hide_banner", "-nostats"]
    if start is not None: cmd += ["-ss", "%.3f" % start]
    if until is not None: cmd += ["-to", "%.3f" % until]
    cmd += ["-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    try:
        err = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stderr
    except Exception as e:
        return None, None
    m = re.search(r"I:\s+(-?[0-9.]+) LUFS", err)
    p = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", err)
    return (float(m.group(1)) if m else None), (float(p.group(1)) if p else None)

keys_seen = collections.Counter()
for kind in ("sfx", "call"):
    print("== %s: last %d airings ==" % (kind, len(rows[kind])))
    levels = []
    for d in reversed(rows[kind]):
        for k in d: keys_seen[k] += 1
        name = d.get("clip_media") or d.get("media") or ""
        path = os.path.join(MEDIA, name) if name else ""
        if not name or not os.path.exists(path):
            print("  %s %-7s no file (%s)  %s" % (time.strftime("%H:%M:%S", time.localtime(d["air_at"])), d.get("who", "")[:7], name[:40], (d.get("text") or "")[:40]))
            continue
        a, b = d.get("clip_from"), d.get("clip_until")
        i, pk = measure(path, float(a) if a is not None else None, float(b) if b is not None else None)
        whole = measure(path)[0] if a is not None else i
        if i is not None: levels.append(i)
        print("  %s %-7s I=%6s  peak=%6s  whole=%6s  %5.1fs  %s" % (time.strftime("%H:%M:%S", time.localtime(d["air_at"])), d.get("who", "")[:7], "%.1f" % i if i is not None else "?", "%.1f" % pk if pk is not None else "?", "%.1f" % whole if whole is not None else "?", float(d.get("seconds") or 0), (d.get("text") or "")[:44]))
    if levels:
        print("  %s files n=%d median %.1f min %.1f max %.1f spread %.1f LU" % (kind, len(levels), statistics.median(levels), min(levels), max(levels), max(levels) - min(levels)))
print("row keys:", [k for k, _ in keys_seen.most_common(40)])
