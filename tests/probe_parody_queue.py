"""The parody stinger queue, as the station reports it (run in the container)."""
import json
import os
import urllib.request

req = urllib.request.Request("http://127.0.0.1:8096/api/comfy/workshop/parody-queue",
                             headers={"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")})
d = json.load(urllib.request.urlopen(req, timeout=30))
print("keys", list(d))
for k, v in d.items():
    if isinstance(v, list):
        for r in v[:5]:
            body = r.get("body") if isinstance(r.get("body"), dict) else {}
            print(k, json.dumps({x: r.get(x) for x in ("id", "status", "note", "error", "prompt_id", "attempts")}),
                  body.get("source_type", ""), str(body.get("source", ""))[:40])
    elif not isinstance(v, dict):
        print(k, v)
