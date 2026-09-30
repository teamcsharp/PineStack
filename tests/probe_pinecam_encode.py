"""[pinecam-config] the recordings preset re-encodes: 8 s of the live segment at 480 wide."""
import time

import app

seg = sorted(app.pinelink_clips_dir().glob("2026-*.mp4"))[-1]
lo = app.pinelink_segment_epoch(seg.stem) + 10
got = app.pinelink_cut_span(lo, lo + 8)
src = app.PINELINK_CUTS / got["name"]
real = app.pinecam_config_read
app.pinecam_config_read = lambda: dict(real(), rec_size="480", rec_quality="small")
t = time.time()
out = app.pinecam_encode(src)
print("encoded", out.name, out.stat().st_size, "bytes in %.1f s" % (time.time() - t),
      "from", src.stat().st_size, "- duration", app._media_duration_probe(out))
out.unlink()
src.unlink()
