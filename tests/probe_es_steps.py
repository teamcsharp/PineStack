"""[es-every-turn] which steps of the live System 3 structure draw no ES (their
turns air flat) - read over the station API (run in the container)."""
import json
import os
import urllib.request

H = {"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")}
cfg = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8096/api/system3/config", headers=H), timeout=30))
config = cfg.get("config") if isinstance(cfg.get("config"), dict) else cfg
st = config.get("structure") or {}
print("structure keys", list(st)[:20])


def families(draws):
    return [d.get("family") for d in (draws or [])]


def walk(name, steps):
    for i, s in enumerate(steps or []):
        fam = families(s.get("draws"))
        print("  %-22s step %-2d %-18s ES:%s  %s" % (name, i, str(s.get("label") or s.get("id") or s.get("speaker") or "")[:18],
                                                  "yes" if "ES" in fam else "NO ", fam))


for key, val in st.items():
    if isinstance(val, list) and val and isinstance(val[0], dict) and "draws" in val[0]:
        walk(key, val)
    elif isinstance(val, dict) and "draws" in val:
        walk(key, [val])
    elif isinstance(val, dict):
        for k2, v2 in val.items():
            if isinstance(v2, list) and v2 and isinstance(v2[0], dict) and "draws" in v2[0]:
                walk(key + "." + k2, v2)
