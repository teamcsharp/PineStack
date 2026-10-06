"""What the tube's players actually receive: the last N clips the desk's tube was handed, fetched through the
gain road exactly as the page fetches them, and measured. Plus the gains book's coverage of the pinned folder.
docker exec -i spark-agent python3 - [N] < cliplevel.py"""
import json, os, re, subprocess, sys, time, urllib.request, collections, statistics, sqlite3
FF = "/usr/local/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2"
KEY = os.environ.get("SPARK_AGENT_API_KEY", "")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 14
lines = open("/app/data/sfx_display_receipts.jsonl", "rb").read()[-2500000:].decode("utf-8", "replace").splitlines()[1:]
rows = []
for l in lines:
    try: rows.append(json.loads(l))
    except Exception: pass
tube = [d for d in rows if d.get("kind") == "receipt" and d.get("surface") == "tube"]
print("tube receipts read:", len(tube))
print("outcomes (last 400):", collections.Counter((d.get("addr"), d.get("outcome"), d.get("reason")) for d in tube[-400:]).most_common(12))
now = time.time()
recent = [d for d in tube if now - float(d.get("rx") or 0) < 7200]
print("by hour, outcome:", collections.Counter((time.strftime("%H", time.localtime(float(d.get("rx") or 0))), d.get("outcome")) for d in recent).most_common(12))
ids = []
for d in reversed(tube):
    s = d.get("sfx")
    if s and s not in ids: ids.append(s)
    if len(ids) >= N: break
levels = []; hows = collections.Counter()
for sid in ids:
    req = urllib.request.Request("http://127.0.0.1:8096/sfx/" + sid, headers={"Authorization": "Bearer " + KEY})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            how = r.headers.get("x-pine-gain-how"); db = r.headers.get("x-pine-gain-db"); ct = r.headers.get("content-type")
            data = r.read()
    except Exception as e:
        print("  %s fetch failed: %s" % (sid, e)); continue
    path = "/tmp/cl_clip.bin"
    open(path, "wb").write(data)
    err = subprocess.run([FF, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True, timeout=180).stderr
    m = re.search(r"I:\s+(-?[0-9.]+) LUFS", err)
    i = float(m.group(1)) if m else None
    if i is not None: levels.append(i)
    hows[how] += 1
    print("  %s how=%-9s gain=%6s  I=%6s  fetched in %4.1fs  %5d KB  %s" % (sid, how, db, ("%.1f" % i) if i is not None else "?", time.time() - t0, len(data) // 1024, (ct or "")[:16]))
if levels:
    print("served clips n=%d median %.1f min %.1f max %.1f spread %.1f LU; how: %s" % (len(levels), statistics.median(levels), min(levels), max(levels), max(levels) - min(levels), dict(hows)))
# the gains book and the pinned folder
try:
    book = json.load(open("/app/data/sfx_gains.json"))
    entries = book.get("clips") if isinstance(book, dict) and isinstance(book.get("clips"), dict) else book
    print("gains book entries:", len(entries), "top-level keys:", list(book.keys())[:8] if isinstance(book, dict) else type(book).__name__)
    sample_key = next(iter(entries)); print("sample entry:", sample_key, json.dumps(entries[sample_key])[:200])
    pin = json.load(open("/app/data/sfx_folder_pin.json"))
    con = sqlite3.connect("file:/app/data/sfx_clips.db?mode=ro", uri=True)
    sids = [r[0] for r in con.execute("SELECT sid FROM clips WHERE playable=1 AND video=1 AND substr(path,1,?)=?", (len(pin["path"]) + 1, pin["path"] + "/"))]
    have = sum(1 for s in sids if s in entries)
    print("pinned folder %s: %d playable videos, %d with a gain entry (%.0f%%)" % (pin["name"], len(sids), have, 100.0 * have / max(1, len(sids))))
except Exception as e:
    print("gains book:", e)
    for cand in os.listdir("/app/data"):
        if "gain" in cand: print("  candidate:", cand)
