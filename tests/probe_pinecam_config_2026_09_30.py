"""[pinecam-config] a live probe, run in the container against the real footage:
the span cutter on the host's clock ([seg-tz]), a thumbnail, the recordings preset,
and a recording resolving as an H3 reference. Nothing is couriered or rendered.

    docker exec -w /app -e PYTHONPATH=/app spark-agent python tests/probe_pinecam_config_2026_09_30.py
"""

import time

import app

now = time.time()
seg_at = [(app.pinelink_segment_epoch(p.stem), p.name) for p in sorted(app.pinelink_clips_dir().glob("*.mp4"))]
seg_at = [x for x in seg_at if x[0]]
print("newest segment", seg_at[-1][1], "starts", round(now - seg_at[-1][0]), "s ago (under 300 = on the host's clock)")
closed = seg_at[-1]                  # [cam-fmp4] the segment still being written
lo = closed[0] + 20
got = app.pinelink_cut_span(lo, lo + 8)
print("cut 8 s from the last closed segment:", got.get("ok"), got.get("name"), got.get("bytes"), got.get("say", ""))
if got.get("ok"):
    p = app.PINELINK_CUTS / got["name"]
    print("  duration", app._media_duration_probe(p))
    th = app.pinecam_thumb(got["name"])
    print("thumb", th, th.stat().st_size if th else None)
    path, kind = app.workshop_source_path("pinecam", got["name"])
    print("H3 source", path.name, kind)
    ref = app.workshop_reference_video(path, 0.5)
    print("H3 reference clip bytes", len(ref))
    cfg = app.pinecam_config_read()
    print("recordings preset", cfg["rec_size"], "->", app.pinecam_encode(p).name)
    p.unlink()
    if th:
        th.unlink()
print("export dest", app.pinecam_export_dest())
print("album hook present", callable(getattr(app, "pinecam_album_cut", None)))
