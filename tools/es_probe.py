#!/usr/bin/env python3
"""[es-probe] The science-table meter (emotion engine step 1): does a performed
take move the way the master table of emotional prosody says it should?

Per take against the SAME script's neutral take: F0 mean shift (st, the
station's own es_voice.f0_track), F0 spread ratio, articulation rate ratio
(speech time with the pauses taken out), pause proportion (quiet runs > 120 ms,
the perf_pause_stretch detector), speech RMS (dB) and spectral tilt (energy
below vs above 1 kHz, dB - the PE1000 axis of Banse & Scherer). Each category's
signs on F0 / rate / energy are checked against the master table.

Two passes:

  --dsp <dir of plain wavs>     RUNS NOW, offline: the station's own perf_apply
                                (read from app.py, never imported) performs each
                                plain take at every ES category's block (v1 = ES1,
                                v2 = ES1_V2) at intensity 1.0 and 0.5 through
                                system3.voice_intent; the DSP layer's own table.
  --render --voices vl_a,vl_b   AT THE DECLARED WINDOW ONLY (--window): seeded XTTS
                                renders of the probe script per voice x category x
                                intensity x seed (n >= 5) on 127.0.0.1:8770 with the
                                ES engine opts, then perf_apply, then the same meter.
                                Touches no store, no pantry, no air; refuses without
                                --window, and while an H3 render is running (#1285).

    python3 tools/es_probe.py --dsp proof/takes [--app app.py] [--json out.json]
    python3 tools/es_probe.py --render --window --voices vl_... [--seeds 5]

numpy + stdlib (+ imageio-ffmpeg for perf_apply's chain, as the station)."""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import es_voice  # noqa: E402

# master-table direction per station category on (F0 mean, rate, energy): see
# tests/test_es_v2.py MASTER for the rows each category is held to.
MASTER = {"surprise": (1, 1, 1), "anger": (1, 1, 1), "fear": (1, 1, 1), "sadness": (-1, -1, -1),
          "joy": (1, 1, 1), "disgust": (-1, -1, -1), "interest": (0, 1, 1), "social": (-1, -1, -1),
          "low_arousal": (-1, -1, -1)}
# a neutral-semantics probe script (the hard case, per the corpora) - one line
PROBE_TEXT = ("The van was parked outside the station again this morning, and nobody has "
              "said a word about who left it there.")
HEADS = ("def _pitch_chain(", "def _ffmpeg_af(", "def perf_dsp_chain(", "def perf_pause_stretch(",
         "def perf_apply(", "def _level_rms(")


def _top_level(text, head):
    i = text.find("\n" + head) + 1
    if not i:
        raise SystemExit("app.py has no %r" % head)
    out = [text[i:text.index("\n", i) + 1]]
    j = i + len(out[0])
    while j < len(text):
        k = text.index("\n", j) + 1
        line = text[j:k]
        if line.strip() and not line[0].isspace() and not line.startswith((")", "}", "]")):
            break
        out.append(line)
        j = k
    return "".join(out)


def station(app_path):
    """perf_apply and _level_rms as the station runs them (read, never imported)."""
    text = Path(app_path).read_text(encoding="utf-8")
    ns = {"re": re, "Any": Any, "Path": Path, "_es_voice": es_voice}
    exec(compile("".join(_top_level(text, h) for h in HEADS), str(app_path), "exec"), ns)
    return ns


# --- the meter -------------------------------------------------------------------

def measure(raw):
    x, params = es_voice._read(raw)
    sr = params.framerate
    body = len(x)
    while body > 0 and x[body - 1] == 0.0:
        body -= 1
    x = x[:body]
    w = max(1, int(sr * 0.02))
    n = len(x) // w
    fr = x[:n * w].reshape(n, w)
    rms = np.sqrt((fr * fr).mean(1))
    quiet = rms * 32768 < 260                      # perf_pause_stretch's detector
    speech_frames = int((~quiet).sum())
    pause = 0
    i = 0
    while i < n:                                   # interior quiet runs > 120 ms are pauses
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= 6 and i > 0 and j < n:
                pause += j - i
            i = j
        else:
            i += 1
    _t, f0 = es_voice.f0_track(x, sr)
    v = f0[f0 > 0]
    st = 12 * np.log2(v) if len(v) else np.array([0.0])
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2 if len(x) else np.zeros(2)
    f = np.fft.rfftfreq(len(x), 1.0 / sr) if len(x) else np.zeros(2)
    lo, hi = spec[(f > 50) & (f < 1000)].sum(), spec[(f >= 1000) & (f < 5000)].sum()
    sp = fr[~quiet] if speech_frames else fr
    return {"f0_st": float(np.median(st)), "f0_sd_st": float(np.std(st)),
            "speech_s": speech_frames * 0.02, "pause_prop": pause / max(1, n),
            "rms_db": 20 * math.log10(max(1e-9, float(np.sqrt((sp * sp).mean())))),
            "tilt_db": 10 * math.log10(max(1e-12, lo) / max(1e-12, hi))}


def delta(take, neutral):
    return {"f0_st": round(take["f0_st"] - neutral["f0_st"], 2),
            "f0_sd_ratio": round(take["f0_sd_st"] / max(1e-6, neutral["f0_sd_st"]), 3),
            "rate_ratio": round(neutral["speech_s"] / max(1e-6, take["speech_s"]), 3),
            "pause_prop": round(take["pause_prop"] - neutral["pause_prop"], 3),
            "rms_db": round(take["rms_db"] - neutral["rms_db"], 2),
            "brightness_db": round(neutral["tilt_db"] - take["tilt_db"], 2)}   # + = more energy above 1 kHz


def sign(v, eps):
    return 0 if abs(v) <= eps else (1 if v > 0 else -1)


def verdict(cid, d):
    got = (sign(d["f0_st"], 0.15), sign(d["rate_ratio"] - 1, 0.01), sign(d["brightness_db"], 0.15))
    want = MASTER[cid]
    return {"signs": got, "want": want, "right": sum(g == w for g, w in zip(got, want)),
            "opposite": [k for k, g, w in zip(("f0", "rate", "energy"), got, want) if g * w < 0]}


def _mean(rows):
    return {k: round(float(np.mean([r[k] for r in rows])), 3) for k in rows[0]}


# --- the DSP pass (runs now) ---------------------------------------------------------

def dsp_pass(takes_dir, app_path):
    import system3
    import system3_tables
    st = station(app_path)
    editions = {"v1": system3_tables.ES1}
    if hasattr(system3_tables, "ES1_V2"):
        editions["v2"] = system3_tables.ES1_V2
    takes = sorted(Path(takes_dir).glob("*.wav"))
    if not takes:
        raise SystemExit("no wavs in %s" % takes_dir)
    out = {}
    for ed, table in editions.items():
        for cat in table["categories"]:
            cid = cat["id"]
            for level in (1.0, 0.5):
                block = system3.voice_intent(cat["voice"], level)
                vec = {"pace": block.get("tempo", 1.0), "range": block.get("range", 1.0),
                       "energy": block.get("energy", 0.0), "pause_scale": block.get("pause", 1.0),
                       "es": {"pitch": block.get("pitch", 0.0)}}
                rows = []
                for take in takes:
                    body, _pad = es_voice.split_tail(take.read_bytes())
                    plain = measure(st["_level_rms"](body, 5200))
                    done = measure(st["_level_rms"](st["perf_apply"](body, dict(vec)), 5200))
                    rows.append(delta(done, plain))
                d = _mean(rows)
                out.setdefault(ed, {}).setdefault(cid, {})[str(level)] = {"delta": d, **verdict(cid, d)}
    summary = {}
    for ed, cats in out.items():
        full = [cats[c]["1.0"] for c in cats]
        mono = sum(abs(cats[c]["0.5"]["delta"]["f0_st"]) <= abs(cats[c]["1.0"]["delta"]["f0_st"]) + 0.05
                   and abs(cats[c]["0.5"]["delta"]["rate_ratio"] - 1) <= abs(cats[c]["1.0"]["delta"]["rate_ratio"] - 1) + 0.005
                   for c in cats)
        summary[ed] = {"categories_all_three_right": sum(v["right"] == 3 for v in full),
                       "categories_with_an_opposite": sum(bool(v["opposite"]) for v in full),
                       "intensity_monotone": mono, "of": len(full)}
    return {"pass": "dsp", "takes": [t.name for t in takes], "summary": summary, "cells": out}


# --- the render pass (the declared window only) ----------------------------------------

def _h3_busy():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=3) as r:
            q = json.loads(r.read().decode())
        return bool(q.get("queue_running"))
    except Exception:  # noqa: BLE001
        return False


def render_pass(voices, seeds, app_path, data_dir):
    import system3
    import system3_tables
    if _h3_busy():
        raise SystemExit("an H3/ComfyUI render is running - not while it is (#1285)")
    st = station(app_path)
    table = getattr(system3_tables, "ES1_V2", system3_tables.ES1)
    out = {}
    for vid in voices:
        ref = Path(data_dir) / "voices" / vid / "reference.wav"
        b64 = base64.b64encode(ref.read_bytes()).decode()

        def say(opts, seed):
            body = json.dumps({"text": PROBE_TEXT, "reference_audio": b64, "language": "en",
                               "seed": seed, "opts": opts}).encode()
            req = urllib.request.Request("http://127.0.0.1:8770/synthesize", body,
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                if not r.headers.get("content-type", "").startswith("audio/"):
                    raise RuntimeError("XTTS refused: %s" % r.read()[:200])
                return r.read()
        neutral = {s: measure(st["_level_rms"](es_voice.split_tail(say({}, s))[0], 5200)) for s in range(seeds)}
        for cat in table["categories"]:
            for level in (1.0, 0.5):
                block = system3.voice_intent(cat["voice"], level)
                opts, native = es_voice.engine_opts(block, "xtts")
                vec = {"pace": block.get("tempo", 1.0), "range": block.get("range", 1.0),
                       "energy": block.get("energy", 0.0), "pause_scale": block.get("pause", 1.0),
                       "es": {"pitch": block.get("pitch", 0.0)},
                       "es_native_tempo": native.get("tempo", 1.0)}
                rows = []
                for s in range(seeds):
                    raw = es_voice.split_tail(say(opts, s))[0]
                    rows.append(delta(measure(st["_level_rms"](st["perf_apply"](raw, dict(vec)), 5200)), neutral[s]))
                d = _mean(rows)
                out.setdefault(vid, {}).setdefault(cat["id"], {})[str(level)] = {"delta": d, **verdict(cat["id"], d)}
    return {"pass": "render", "voices": voices, "seeds": seeds, "text": PROBE_TEXT, "cells": out}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsp")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--window", action="store_true", help="the declared bench window is open")
    ap.add_argument("--voices", default="")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--app", default=str(ROOT / "app.py"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    if a.dsp:
        got = dsp_pass(a.dsp, a.app)
    elif a.render:
        if not a.window:
            raise SystemExit("the render pass runs only at the declared window (--window)")
        got = render_pass([v for v in a.voices.split(",") if v], max(5, a.seeds), a.app, a.data)
    else:
        ap.error("--dsp DIR or --render --window")
    text = json.dumps(got, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(json.dumps(got.get("summary") or {k: v for k, v in got.items() if k != "cells"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
