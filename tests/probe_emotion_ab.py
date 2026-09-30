"""Raw take vs shaped take for the last voiced lines: duration and median pitch,
so "is it modulating" is measured on the audio itself (run in the container)."""
import io
import json
import os
import urllib.request
import wave

import numpy as np

import es_voice

req = urllib.request.Request("http://127.0.0.1:8096/api/emotion/state",
                             headers={"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")})
d = json.load(urllib.request.urlopen(req, timeout=30))
tasks = d.get("tasks") or []
print("task keys:", sorted(tasks[0].keys()) if tasks else None)
print("without ES:", [(t.get("speaker"), t.get("line", "")[:14], t.get("road") or t.get("kind")) for t in tasks if not t.get("es")][:9])
media = "/app/data/voice_media" if os.path.isdir("/app/data/voice_media") else "/app/data/media"


def load(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
        if w.getnchannels() == 2:
            x = x.reshape(-1, 2).mean(axis=1)
    return x / 32768.0, sr


def med_f0(x, sr):
    try:
        f0 = es_voice.f0_track(x, sr)
        f0 = np.asarray(f0[0] if isinstance(f0, tuple) else f0, dtype=float)
        f0 = f0[np.isfinite(f0) & (f0 > 0)]
        return float(np.median(f0)) if f0.size else None
    except Exception as exc:  # noqa: BLE001
        return "f0 err %s" % exc


for t in [t for t in tasks if t.get("es")][:5]:
    raw = t.get("raw_path") or t.get("raw") or ""
    shp = t.get("final") or ""
    rp = raw if raw.startswith("/") else os.path.join(media, raw)
    sp = shp if shp.startswith("/") else os.path.join(media, shp)
    if not (os.path.isfile(rp) and os.path.isfile(sp)):
        print("missing", rp, sp)
        continue
    try:
        a, sra = load(rp)
        b, srb = load(sp)
    except Exception as exc:  # noqa: BLE001
        print("read", exc)
        continue
    fa, fb = med_f0(a, sra), med_f0(b, srb)
    st = (12 * np.log2(fb / fa)) if isinstance(fa, float) and isinstance(fb, float) and fa > 0 else None
    print("by_es %s | es tempo %.3f pitch %+.2f | raw %.2fs -> shaped %.2fs (x%.3f) | median f0 %s -> %s (%s st)" % (
        t.get("shaped_by_es"), t["es"].get("tempo", 1), t["es"].get("pitch", 0), len(a) / sra, len(b) / srb, (len(b) / srb) / (len(a) / sra),
        "%.1f" % fa if isinstance(fa, float) else fa, "%.1f" % fb if isinstance(fb, float) else fb,
        "%+.2f" % st if st is not None else "?"))
