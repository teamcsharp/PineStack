import sys
sys.path.insert(0, "/app")
import app
pool = app.sfx_all()
banned = app.sfx_bans()
gap = [p for p in pool if app.sfx_short(p) and app.sfx_id(p) not in banned
       and not (app.sfx_is_video(p) and app.sfx_is_silent(p))]
vid = [p for p in gap if app.sfx_is_video(p)]
print("gap-filler pool now :", len(gap))
print("  of which video    :", len(vid))
print("draws (10 tries):")
hits = 0
for i in range(10):
    p = app._sfx_any()
    if p is None: print("   none"); continue
    v = app.sfx_is_video(p)
    if v: hits += 1
    print("   %-5s %s" % ("VIDEO" if v else "audio", str(p)[-56:]))
print("video drawn %d/10 (expected ~%.0f%%)" % (hits, 100.0*len(vid)/max(1,len(gap))))
