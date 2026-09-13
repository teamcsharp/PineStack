import sys, time, asyncio, collections
sys.path.insert(0, "/app")
import app
now = time.time()
key = app.screenplay_hour_key(now)
lo, hi = app.screenplay_hour_span(key)
d = asyncio.run(app.screenplay_hour(lo, hi, key, True))
els = d.get("elements") or []
HEARD = set(app.AIR_AT_HEARD)
by_seg = collections.OrderedDict()
for e in els:
    if e.get("type") != "dialogue": continue
    by_seg.setdefault(str(e.get("seg") or ""), []).append(e)
passed = tot = 0
for seg, rows in by_seg.items():
    last = -1
    for i, r in enumerate(rows):
        if str(r.get("aired") or "") in HEARD: last = i
    for i, r in enumerate(rows):
        if i < last:
            tot += 1
            if str(r.get("aired") or "") not in HEARD: passed += 1
print("hour", key, "dialogue", sum(len(v) for v in by_seg.values()))
print("lines the air went PAST inside a segment: %d of %d (%.1f%%)   [before: 10/51 = 19.6%%]"
      % (passed, tot, 100.0*passed/max(1,tot)))
# and does the aired sequence run forward in time now?
aired = [float(e.get("at") or 0) for e in els
         if e.get("type") == "dialogue" and str(e.get("aired") or "") in HEARD]
back = sum(1 for i in range(1, len(aired)) if aired[i] < aired[i-1] - 0.001)
print("aired lines out of time order: %d of %d" % (back, max(0, len(aired)-1)))
