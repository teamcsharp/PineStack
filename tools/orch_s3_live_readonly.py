"""Read-only: feed the live doors' answers to the desk's pure sensors."""
import json, os, sys, time, urllib.request
sys.path.insert(0, "/tmp/w_orch")
import orchestrator_s3 as os3
K = os.environ.get("SPARK_AGENT_API_KEY", "")
def g(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8096" + u, headers={"Authorization": "Bearer " + K}), timeout=60).read())
now = time.time()
st = g("/api/system3/status"); modes = st.get("road_modes") or {}
fs = os3.sense_origin(g("/api/system3/untraced?hours=24&limit=200"), modes)
disp = g("/api/sfx/display-audit?hours=1").get("summary")
fs += os3.sense_mp4(g("/api/sfx/mp4-only"), disp)
radio = g("/api/dj") if False else {}
fs += os3.sense_receivers(g("/api/air/receivers"), True)
gaps = []
for l in open("/app/data/gap_log.jsonl", encoding="utf-8"):
    try: gaps.append(json.loads(l))
    except ValueError: pass
fs += os3.sense_gaps(gaps, now)
rows = []
with open("/app/data/script_ledger.jsonl", "rb") as fh:
    fh.seek(0, 2); fh.seek(max(0, fh.tell() - 200000))
    for l in fh.read().decode("utf-8", "replace").splitlines()[1:]:
        try: rows.append(json.loads(l))
        except ValueError: pass
last = max(rows, key=lambda r: float(r.get("at") or 0)) if rows else None
fs += os3.sense_script(float((last or {}).get("at") or 0), last, True, False, now)
c = g("/api/system3/config")
bodies = {}
for v in c["versions"][:30]:
    bodies[v["hash"]] = g("/api/system3/config?hash=" + v["hash"])["config"]
ch = os3.table_changes(c["versions"], bodies, now - 86400)
tab = [x for x in ch if x["by"] == "the station"]
print("config versions in 24h: %d (station-tabled %d)" % (len(ch), len(tab)))
for x in ch[:6]: print("  ", x["hash"], x["note"][:70], "added", x.get("added"), "changed", x.get("changed"), "sections", x.get("sections"))
for f in sorted(fs, key=lambda f: -os3.SEVERITY[f["severity"]]):
    print("[%s] %s: %s" % (f["severity"], f["class"], f["title"]))
    print("     identify:", f["identify"][:3], "evidence:", json.dumps(f["evidence"], default=str)[:260])
