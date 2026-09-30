"""[es-roads] which roads' airings carried a feeling, and why the rest did not,
over the feed's last 240 rows (run in the container)."""
import collections
import json
import os
import urllib.request

H = {"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")}
d = None
for path in ("/api/dj/state", "/api/dj", "/api/radio/state"):
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8096" + path, headers=H), timeout=30))
        if isinstance(d, dict) and d.get("chat"):
            print("from", path)
            break
    except Exception as exc:  # noqa: BLE001
        print(path, exc)
rows = (d or {}).get("chat") or []
got = collections.Counter()
why = collections.Counter()
samples = {}
for r in rows:
    es = r.get("es")
    if not isinstance(es, dict):
        continue
    road = es.get("road", "?")
    if es.get("none"):
        got[road + " - NONE"] += 1
        why[(road, es["none"])] += 1
        samples.setdefault((road, es["none"]), str(r.get("text") or "")[:70])
    else:
        got[road + " - shaped"] += 1
print("rows", len(rows), "with an es stamp", sum(got.values()))
for k, v in got.most_common():
    print("  %4d  %s" % (v, k))
print("why none:")
for (road, w), v in why.most_common():
    print("  %4d  %s: %s  | e.g. %s" % (v, road, w, samples[(road, w)]))
