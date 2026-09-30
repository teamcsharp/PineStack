"""[whole-words] live: roll labels in the newest System 3 conversations, over the
station's own API (run on the host: python3 tests/probe_whole_labels.py)."""
import json
import urllib.request

B = "http://127.0.0.1:8096"
KEY = ""
try:
    KEY = json.load(open("/home/ehm_eckx/pinevoice-stack/spark-agent/data/settings.json")).get("api_key", "")
except Exception:  # noqa: BLE001
    pass


def get(path):
    req = urllib.request.Request(B + path, headers={"Authorization": "Bearer " + KEY} if KEY else {})
    return json.load(urllib.request.urlopen(req, timeout=30))


lst = get("/api/system3/conversations")
rows = lst.get("conversations") if isinstance(lst, dict) else lst
rows = rows or []
total = whole = cut90 = 0
examples = []
for r in rows[:12]:
    cid = r.get("id") or r.get("conversation_id") if isinstance(r, dict) else r
    try:
        conv = get("/api/system3/conversation/" + str(cid))
    except Exception:  # noqa: BLE001
        continue
    for ev in conv.get("decision_events") or []:
        for st in ev.get("stages") or []:
            for c in st.get("candidates") or []:
                lab = str(c.get("label") or "")
                total += 1
                if len(lab) > 90:
                    whole += 1
                    if len(examples) < 2:
                        examples.append(lab)
                elif len(lab) == 90:
                    cut90 += 1
print("conversations", len(rows[:12]), "candidate labels", total, "- longer than 90 (whole):", whole,
      "- exactly 90 (the old cut):", cut90)
for e in examples:
    print("  e.g.", e)
