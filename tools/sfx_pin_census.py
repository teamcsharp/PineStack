"""Folders the SFX airings came from since the pin was set, joined to the clip book by sid.
docker exec -i spark-agent python3 - < aircensus2.py"""
import json, time, collections, sqlite3, glob
from pathlib import Path
pin = json.loads(Path("/app/data/sfx_folder_pin.json").read_text())
since = float(pin.get("at") or 0)
print("pin:", json.dumps(pin), "set", time.strftime("%H:%M:%S", time.localtime(since)))
dbs = [p for p in glob.glob("/app/data/*.db") + glob.glob("/app/data/*.sqlite*") + glob.glob("/app/data/sfx*/*.db")]
print("db files:", dbs[:8])
book = {}
for db in dbs:
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        cols = [r[1] for r in con.execute("PRAGMA table_info(clips)")]
        if "sid" in cols and "path" in cols:
            for sid, path in con.execute("SELECT sid, path FROM clips"):
                book[str(sid)] = str(path)
            print("clips table in", db, "rows", len(book), "cols", cols[:14])
    except Exception as e:
        pass
rows = []
with open("/app/data/air_log.jsonl", "rb") as f:
    f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 8000000))
    for line in f.read().decode("utf-8", "replace").splitlines()[1:]:
        try: d = json.loads(line)
        except Exception: continue
        if (d.get("air_at") or 0) >= since and d.get("kind") == "sfx": rows.append(d)
seen = {}
for d in rows:
    seen.setdefault(d.get("id"), d)
folders = collections.Counter(); unknown = 0; rounds = collections.Counter()
timeline = []
for d in seen.values():
    sid = str(d.get("sid") or "")
    path = book.get(sid)
    if not path:
        unknown += 1; folder = "(sid not in book)"
    else:
        folder = str(Path(path).parent).replace(pin["path"], "[PIN]") if path.startswith(pin["path"] + "/") else Path(path).parent.name
    folders[folder] += 1; rounds[d.get("round")] += 1
    timeline.append((d.get("air_at"), folder, (d.get("text") or "")[:30], d.get("round")))
print("distinct sfx airings since the pin:", len(seen), "sid unknown:", unknown)
print("folders:", folders.most_common(14))
print("rounds:", rounds.most_common(8))
for at, folder, text, rnd in sorted(timeline)[-16:]:
    print("  ", time.strftime("%H:%M:%S", time.localtime(at)), "%-32s" % folder[:32], rnd, text)
