import sys, time, json, collections
sys.path.insert(0, "/app")
import app

now = time.time()

# what the screenplay shows for this hour
import asyncio
key = app.screenplay_hour_key(now)
lo, hi = app.screenplay_hour_span(key)
d = asyncio.run(app.screenplay_hour(lo, hi, key, True))
# THE SAME WINDOW THE SCREENPLAY COVERS, or the previous hour's rows
# count as missing and the number is meaningless.
hi_now = min(hi, now)
rows = app.airlog_rows(lo, hi_now + 1.0, quiet=False)
print("window %s  %.0f min of it elapsed" % (key, (hi_now - lo) / 60.0))
print("aired rows in that window:", len(rows))
els = d.get("elements") or []
shown = set()
for e in els:
    for f in ("line", "id"):
        v = e.get(f)
        if v: shown.add(str(v))
print("screenplay elements:", len(els), " ids shown:", len(shown))

missing = collections.Counter()
missing_ex = {}
present = collections.Counter()
for r in rows:
    txt = str(r.get("text") or "").strip()
    if not txt:
        continue
    rid = str(r.get("id") or "")
    kind = str(r.get("kind") or "?")
    who = str(r.get("who") or "?")
    tag = "%s/%s" % (kind, who)
    if rid and rid in shown:
        present[tag] += 1
    else:
        missing[tag] += 1
        missing_ex.setdefault(tag, txt[:70])

print()
print("--- SPOKEN ROWS THE SCRIPT DOES NOT SHOW (kind/who) ---")
for k, v in missing.most_common(18):
    print("  %-26s %4d   e.g. %s" % (k, v, missing_ex.get(k, "")))
print()
print("--- shown ---")
for k, v in present.most_common(10):
    print("  %-26s %4d" % (k, v))
tot_m, tot_p = sum(missing.values()), sum(present.values())
print()
print("missing %d of %d rows with text (%.1f%%)" % (
    tot_m, tot_m + tot_p, 100.0 * tot_m / max(1, tot_m + tot_p)))
