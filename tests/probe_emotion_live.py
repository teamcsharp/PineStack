"""Is the emotion engine modulating the audio? The last voiced lines, as
/api/emotion/state recorded them: how many carried an ES block, how far from
neutral it was, and whether the DSP stage ran on them (run in the container)."""
import json
import os
import time
import urllib.request

req = urllib.request.Request("http://127.0.0.1:8096/api/emotion/state",
                             headers={"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")})
d = json.load(urllib.request.urlopen(req, timeout=30))
tasks = d.get("tasks") or []
print("keys", list(d)[:12], "tasks", len(tasks))
now = time.time()
es_n = neutral = shaped = 0
engines = {}
for t in tasks:
    es = t.get("es") or {}
    engines[t.get("engine")] = engines.get(t.get("engine"), 0) + 1
    if es:
        es_n += 1
        off = {k: v for k, v in es.items() if isinstance(v, (int, float)) and
               abs(float(v) - (1.0 if k in ("tempo", "range", "pause") else 0.0)) > 0.004}
        if not off:
            neutral += 1
    if t.get("status") in ("done", "shaped") or t.get("shaped_key") or t.get("key"):
        shaped += 1
print("engines", engines, "| with an ES block", es_n, "| of those neutral", neutral, "| shaped", shaped)
for t in tasks[:6]:
    print(json.dumps({k: t.get(k) for k in ("at", "speaker", "engine", "status", "es", "dsp_ms", "emotion", "label")},
                     default=str)[:400])
