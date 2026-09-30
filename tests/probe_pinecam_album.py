"""[pinecam-config] the album hook on a synthetic 10 s cut of the live footage.
dest "" = nothing is couriered; the album mp4 is removed afterwards."""
import time

import app

row = {"event": "probe", "index": 99, "start": time.time() - 40, "seconds": 10.0,
       "folder": "probe", "mix": "probe_mix_99.mp3", "input": "probe_in_99.mp3"}
t = time.time()
got = app.pinecam_album_cut(row, "")
print("album hook", got.get("ok"), got.get("name"), got.get("why", ""), "waited", got.get("waited"),
      "in %.1f s" % (time.time() - t))
if got.get("name"):
    p = app.PINELINK_CUTS / got["name"]
    print("  file", p.name, p.stat().st_size, "bytes, duration", app._media_duration_probe(p))
    rec = app.pinecam_recordings()
    print("  listed as", [x["kind"] for x in rec["items"] if x["name"] == p.name])
    p.unlink()
rec = app.pinecam_recordings()
print("broken", sum(1 for x in rec["items"] if x.get("broken")), "of", rec["count"],
      [x["name"] for x in rec["items"] if x.get("broken")][:6])
