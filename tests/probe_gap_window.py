"""What the pipeline said during a gap (run in the container): the station's own
pipeline ring over /api, filtered to a time window (host-clock HH:MM:SS args)."""
import json
import os
import sys
import time
import urllib.request

H = {"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")}
lo_s, hi_s = sys.argv[1], sys.argv[2]
day = time.strftime("%Y-%m-%d")
lo = time.mktime(time.strptime(day + " " + lo_s, "%Y-%m-%d %H:%M:%S")) + 3600   # host CST -> container CDT
hi = time.mktime(time.strptime(day + " " + hi_s, "%Y-%m-%d %H:%M:%S")) + 3600
for path in ("/api/pipeline?limit=2000", "/api/pipeline/log?limit=2000", "/api/dj/pipeline?limit=2000"):
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8096" + path, headers=H), timeout=30))
    except Exception as exc:  # noqa: BLE001
        print(path, exc)
        continue
    rows = d if isinstance(d, list) else (d.get("rows") or d.get("log") or d.get("items") or d.get("events") or [])
    print("from", path, len(rows))
    for r in rows:
        t = float(r.get("at") or r.get("ts") or r.get("t") or 0)
        if lo <= t <= hi:
            print(time.strftime("%H:%M:%S", time.localtime(t - 3600)), str(r.get("stage") or r.get("kind") or "")[:10],
                  str(r.get("text") or r.get("msg") or r.get("message") or "")[:150])
    break
