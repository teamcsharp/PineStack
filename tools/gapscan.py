import json, time, collections
now = time.time()
rows = []
for ln in open("/app/data/gap_log.jsonl", encoding="utf-8"):
    ln = ln.strip()
    if not ln: continue
    try: rows.append(json.loads(ln))
    except Exception: pass
rows = [r for r in rows if isinstance(r.get("at"), (int, float))]
print("--- DEAD AIR IN 10-MIN BUCKETS, last 3h (newest last) ---")
print("    bucket      n   dead_s   %win   biggest cause")
for b in range(17, -1, -1):
    lo, hi = now - (b+1)*600, now - b*600
    sel = [r for r in rows if lo <= r["at"] < hi]
    if not sel:
        print("  -%3dmin   (nothing logged)" % ((b+1)*10)); continue
    tot = sum(float(r.get("seconds") or 0) for r in sel)
    c = collections.Counter()
    for r in sel: c[str(r.get("cause") or "?")] += float(r.get("seconds") or 0)
    top = c.most_common(1)[0]
    print("  -%3dmin  %3d  %7.1f  %5.1f%%   %s %.0fs" % (
        (b+1)*10, len(sel), tot, 100.0*tot/600, top[0], top[1]))
