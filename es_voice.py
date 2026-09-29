"""[s3-es-voice] How a feeling sounds: System 3's ES roll, on the recording.

2026-09-28, the operator: "The intention is for categories to be scrolled via
RNG and then the subcategories which is fed to the LLM for direction on how to
write that particular line in the correspondence and also is fed to the
intonation engine to take place affecting the way the recording is made so they
emotionally reflect the dialogue."

The ES roll lands on a category and an item (surprise -> astonishment). Its row
in System 3's ES table carries a `voice` block - the operator's table, edited on
the Tables tab (system3_tables._ES_VOICE / _ES_ITEM_VOICE are the defaults):

    tempo   x   how fast the line is spoken (1.08 = 8% faster)
    pitch   st  where the voice's middle sits, in semitones (formants kept)
    range   x   how far the melody swings around that middle (1.3 = wider)
    energy  +-  vocal effort: brighter and pressed (+) or softer and darker (-);
                heard as colour, never as volume - every clip is still levelled
    pause   x   the gaps between phrases (1.3 = longer)
    temp    +-  the XTTS sampling temperature (livelier or steadier delivery)

System 3 scales it by the turn's intensity (system3.voice_intent) and hands it
to the station on the turn's performance. performance_vector folds it into the
line's vector (`es`), and this module turns it into sound:

  * the ENGINE's own controls where it has them (engine_opts): XTTS takes the
    temperature and the tempo as its native speed, F5 the tempo as its speed.
    What an engine did natively is not done again by the DSP (dsp_share).
  * the DSP stage (intonate + the ffmpeg chain in the station's perf_dsp_chain):
    pitch middle and range by TD-PSOLA on the take's own pulses - duration kept,
    formants kept, nothing resampled - then tempo (atempo), energy as spectral
    tilt, pauses as the station's pause stretch.

Safe bounds, always (BOUNDS): +-2 st for the middle, never more than +-2.5 st
on any single stretch, range 0.6-1.5, tempo 0.85-1.15, tilt +-3.5 dB, pause
0.7-1.5, XTTS temperature 0.55-0.80. The leveller that ends every clip
(_level_voice) is untouched, and the energy chain leaves headroom for it
instead of pushing into it, so a line never arrives louder or clipped.

numpy + stdlib only (the container has nothing else of the kind). Every
function returns its input untouched on any failure: dry beats broken."""
from __future__ import annotations

import io
import math
import wave

try:                                    # the station always has numpy; a test box may not
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

# --- the table's vocabulary --------------------------------------------------

KEYS = ("tempo", "pitch", "range", "energy", "pause", "temp")
MULT = ("tempo", "range", "pause")       # the rest add
NEUTRAL = {"tempo": 1.0, "pitch": 0.0, "range": 1.0, "energy": 0.0, "pause": 1.0, "temp": 0.0}
BOUNDS = {"tempo": (0.85, 1.15), "pitch": (-2.0, 2.0), "range": (0.6, 1.5),
          "energy": (-0.8, 0.8), "pause": (0.7, 1.5), "temp": (-0.1, 0.1)}
MAX_LOCAL_ST = 2.5                       # no stretch of the melody moves further than this
TILT_DB_PER_ENERGY = 5.0                 # energy 0.5 -> +2.5 dB above ~1.8 kHz
TILT_MAX_DB = 3.5
XTTS_TEMP = (0.55, 0.80)                 # the clone server's 0.70 default sits inside
# The native speed each clone engine may be asked for. F5 generates the line at
# its new length (clean anywhere near 1); XTTS interpolates its latents, which
# its own server notes "smears timbre" away from 1 - so it gets the narrower
# window, and the DSP carries whatever is left (dsp_tempo).
ENGINE_SPEED = {"xtts": (0.90, 1.15), "f5": (0.80, 1.25)}


def clean(block):
    """A `voice` block as the table may hold it -> numbers only, in bounds,
    unknown keys dropped; {} when nothing usable is left."""
    out = {}
    if not isinstance(block, dict):
        return out
    for k in KEYS:
        if k not in block:
            continue
        try:
            v = float(block[k])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v):
            continue
        lo, hi = BOUNDS[k]
        out[k] = round(min(hi, max(lo, v)), 3)
    return out


def is_neutral(block, eps=0.004):
    return all(abs(float((block or {}).get(k, NEUTRAL[k])) - NEUTRAL[k]) < eps for k in KEYS)


def ratio(want, baked):
    """What is still to be done to turn a take made with `baked` into one made
    with `want` (both ES blocks; {} = neutral): multiplicative keys divide,
    additive keys subtract. The temperature cannot be redone after the fact,
    so it is not in the answer."""
    want, baked = clean(want), clean(baked)
    out = {}
    for k in KEYS:
        if k == "temp":
            continue
        w = want.get(k, NEUTRAL[k])
        b = baked.get(k, NEUTRAL[k])
        out[k] = round(w / b, 4) if k in MULT else round(w - b, 4)
    return out


def split_tail(raw):
    """(the wav without its trailing digital silence, that silence in ms). The
    station ends every clip on a pad of true zeros (_level_voice's box tail);
    a re-performed take gets exactly the same pad back."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            params = w.getparams()
            frames = w.readframes(w.getnframes())
        step = params.sampwidth * params.nchannels
        end = len(frames) - len(frames) % step
        z = end
        while z >= step and not any(frames[z - step:z]):
            z -= step
        if z == end:
            return raw, 0
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setparams(params)
            w.writeframes(frames[:z])
        return out.getvalue(), int(round(1000.0 * (end - z) / step / params.framerate))
    except Exception:  # noqa: BLE001
        return raw, 0


# --- the engine's own controls -----------------------------------------------

def engine_opts(es, engine, base_speed=1.0, base_temp=0.70):
    """The `opts` a clone server takes for this line's ES block, and what the
    engine will therefore have done natively: (opts, native). XTTS: speed and
    temperature; F5: speed. Anything else: nothing (the DSP does it all)."""
    es = clean(es)
    if not es or engine not in ("xtts", "f5"):
        return {}, {}
    opts, native = {}, {}
    tempo = es.get("tempo", 1.0)
    base = float(base_speed or 1.0)
    lo, hi = ENGINE_SPEED[engine]
    speed = min(max(hi, base), max(min(lo, base), base * tempo))   # never undoes the station's own rate
    if abs(tempo - 1.0) >= 0.005 and abs(speed - base) >= 0.001:
        opts["speed"] = round(speed, 4)
        native["tempo"] = round(speed / base, 4)
    if engine == "xtts" and abs(es.get("temp", 0.0)) >= 0.005:
        lo, hi = XTTS_TEMP
        opts["temperature"] = round(min(hi, max(lo, float(base_temp) + es["temp"])), 3)
        native["temp"] = es["temp"]
    return opts, native


def dsp_tempo(es, native):
    """The part of the ES tempo the DSP still owes after the engine's own."""
    t = clean(es).get("tempo", 1.0)
    n = float((native or {}).get("tempo") or 1.0)
    return t / n if n > 0 else t


# --- wav in, wav out ---------------------------------------------------------

def _read(raw):
    with wave.open(io.BytesIO(raw), "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    if params.sampwidth != 2 or params.nchannels != 1:
        return None, params
    return np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0, params


def _write(x, params):
    y = np.clip(np.round(x * 32768.0), -32768, 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(params.framerate)
        w.writeframes(y.tobytes())
    return out.getvalue()


# --- the melody: F0 (YIN) and TD-PSOLA ---------------------------------------

def _frames(x, width, hop):
    n = 1 + max(0, (len(x) - width) // hop)
    idx = np.arange(width)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def _lowpass(x, sr, fc=1000.0):
    """Zero-phase, in one FFT of a fast length (a take's own length can be a
    slow one for the FFT: 130 ms against 4 ms, measured)."""
    nfft = 1 << int(np.ceil(np.log2(max(2, len(x)) * 1.25)))
    spec = np.fft.rfft(x, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    spec *= 1.0 / (1.0 + (f / fc) ** 8)
    return np.fft.irfft(spec, nfft)[:len(x)]


def f0_track(x, sr, fmin=55.0, fmax=500.0, hop_s=0.005, win_s=0.032, dip=0.15, cut=0.45, xl=None):
    """YIN on the voice below 1 kHz (a clone carries its reference's room; the
    fundamental stands out of it there). (frame times s, f0 Hz with 0 =
    unvoiced). A frame is voiced when its best dip is under `cut` and it sits
    within 40 dB of the loudest frame; the contour is then cleaned (octave
    slips folded back, wild frames and runs under 20 ms dropped, 5-point median)."""
    xl = _lowpass(x, sr) if xl is None else xl
    # below 1 kHz there is nothing a quarter of the rate cannot hold: analyse at
    # ~6 kHz (a quarter of the work per frame, a sixteenth of the lag products)
    q = max(1, int(sr // 6000))
    xl, sr = xl[::q], sr / q
    hop = max(1, int(round(hop_s * sr)))
    width = int(round(win_s * sr))
    tau_min = max(2, int(sr / fmax))
    tau_max = min(width - 1, int(sr / fmin) + 1)
    total = width + tau_max
    n = 1 + len(xl) // hop
    pad = np.concatenate([xl, np.zeros(total + hop)])
    fr = _frames(pad, total, hop)[:n]
    a = fr[:, :width]
    nfft = 1 << int(np.ceil(np.log2(total + width)))
    r = np.fft.irfft(np.conj(np.fft.rfft(a, nfft)) * np.fft.rfft(fr, nfft), nfft)[:, :tau_max + 1]
    cs = np.concatenate([np.zeros((n, 1)), np.cumsum(fr ** 2, axis=1)], axis=1)
    taus = np.arange(tau_max + 1)
    e0 = cs[:, width][:, None]
    d = np.maximum(e0 + (cs[:, taus + width] - cs[:, taus]) - 2 * r, 0.0)
    d[:, 0] = 0.0
    cmnd = np.ones_like(d)
    cmnd[:, 1:] = d[:, 1:] * taus[1:][None, :] / np.maximum(np.cumsum(d[:, 1:], axis=1), 1e-12)
    seg = cmnd[:, tau_min:tau_max]
    # the first dip under `dip`, walked down to its local minimum; else the global minimum
    below = seg < dip
    has = below.any(axis=1)
    first = np.where(has, np.argmax(below, axis=1), np.argmin(seg, axis=1))
    span = max(2, tau_min)
    cols = np.clip(first[:, None] + np.arange(span)[None, :], 0, seg.shape[1] - 1)
    local = seg[np.arange(n)[:, None], cols]
    j = np.where(has, cols[np.arange(n), np.argmin(local, axis=1)], first)
    best = seg[np.arange(n), j]
    t = (j + tau_min).astype(np.float64)
    ti = np.clip(j + tau_min, 1, tau_max - 1)
    y0, y1, y2 = cmnd[np.arange(n), ti - 1], cmnd[np.arange(n), ti], cmnd[np.arange(n), ti + 1]
    den = y0 - 2 * y1 + y2
    t = t + np.where(np.abs(den) > 1e-12, 0.5 * (y0 - y2) / np.where(den == 0, 1, den), 0.0)
    energy = np.sqrt(e0[:, 0] / width)
    floor = max(1e-5, float(np.max(energy)) * 10 ** (-40 / 20)) if n else 1e-5
    fc = np.where(t > 0, sr / np.maximum(t, 1e-9), 0.0)
    times = (np.arange(n) * hop + width / 2.0) / sr
    return times, _clean_f0(_voicing(fc, best, energy >= floor, cut))


def _voicing(fc, best, loud, cut, sure=0.25, step=0.15):
    """Which frames are voice, by hysteresis. The SURE frames (a deep dip) set
    the voice's own register - an octave below its median to a little over an
    octave above; a frame outside it is noise or a fricative that happened to
    ring, never a pitch. A frame with a shallower dip (under `cut`) is voice only
    when it continues a voiced neighbour smoothly (within `step` octaves)."""
    ok = loud & (fc > 0)
    conf = ok & (best < sure)
    if int(conf.sum()) < 8:
        return np.zeros_like(fc)
    lf = np.log2(np.where(fc > 0, fc, 1.0))
    ref = float(np.median(lf[conf]))
    band = (lf > ref - 1.0) & (lf < ref + 1.1)
    voiced = conf & band
    cand = ok & band & (best < cut)
    for order in (range(1, len(fc)), range(len(fc) - 2, -1, -1)):
        for i in order:
            if voiced[i] or not cand[i]:
                continue
            j = i - 1 if order.step == 1 else i + 1
            if voiced[j] and abs(lf[i] - lf[j]) < step:
                voiced[i] = True
    return np.where(voiced, fc, 0.0)


def _clean_f0(f0, min_run=4):
    f = f0.copy()
    idx = np.nonzero(f > 0)[0]
    if len(idx) > 8:
        lf = np.log2(f[idx])
        pad = np.concatenate([np.full(12, lf[0]), lf, np.full(12, lf[-1])])
        med = np.median(_frames(pad, 25, 1), axis=1)[:len(lf)]
        dev = lf - med
        slip = np.abs(np.abs(dev) - 1.0) < 0.25            # an octave slip: fold it back
        lf[slip] -= np.sign(dev[slip])
        f[idx] = 2 ** lf
        f[idx[np.abs(lf - med) > 0.6]] = 0.0               # still wild: not a pitch
    v = f > 0
    out = np.zeros_like(f)
    i, n = 0, len(f)
    while i < n:
        if not v[i]:
            i += 1
            continue
        j = i
        while j < n and v[j]:
            j += 1
        if j - i >= min_run:
            run = f[i:j]
            pad = np.concatenate([run[:1].repeat(2), run, run[-1:].repeat(2)])
            out[i:j] = np.median(_frames(pad, 5, 1), axis=1)
        i = j
    return out


def _ratio_curve(f0, mean_st, range_, hop_s=0.005, smooth_s=0.05):
    """Per frame: the pitch ratio that moves the middle by mean_st and scales
    the contour's distance from the utterance's median (log F0) by range_.
    1.0 where unvoiced; never beyond MAX_LOCAL_ST."""
    v = f0 > 0
    r = np.ones(len(f0))
    if v.sum() < 8:
        return r
    lf = np.where(v, np.log2(np.where(v, f0, 1.0)), 0.0)
    ref = float(np.median(lf[v]))
    # an unvoiced frame holds the last pitch heard (for the smoothing only)
    at = np.where(v, np.arange(len(lf)), -1)
    at = np.maximum.accumulate(at)
    held = np.where(at >= 0, lf[np.maximum(at, 0)], ref)
    k = max(1, int(round(smooth_s / hop_s)))
    padded = np.concatenate([np.full(k // 2, held[0]), held, np.full(k - 1 - k // 2, held[-1])])
    sm = np.convolve(padded, np.ones(k) / k, mode="valid")
    st = np.clip(12.0 * (range_ - 1.0) * (sm - ref) + mean_st, -MAX_LOCAL_ST, MAX_LOCAL_ST)
    r[v] = 2.0 ** (st[v] / 12.0)
    return r


def _marks(x, sr, times, f0, hop_s=0.005, unvoiced_s=0.005, lp=None):
    """Analysis pitch marks: one per glottal pulse in voiced stretches (the
    peak of the voice below 1 kHz, a period on from the last), every 5 ms elsewhere."""
    n = len(x)
    lp = _lowpass(x, sr) if lp is None else lp
    hop_s = float(times[1] - times[0]) if len(times) > 1 else hop_s
    fi = np.clip(np.round((np.arange(n) / sr - times[0]) / hop_s).astype(np.int64), 0, len(f0) - 1)
    fs = f0[fi]
    marks, voiced = [], []
    hop_u = max(1, int(round(unvoiced_s * sr)))
    i = 0
    while i < n:
        if fs[i] <= 0:
            marks.append(i)
            voiced.append(False)
            i += hop_u
            continue
        j = i
        while j < n and fs[j] > 0:
            j += 1
        T = sr / fs[i]
        t = i + int(np.argmax(lp[i:min(j, i + int(T) + 1)]))
        while t < j:
            marks.append(t)
            voiced.append(True)
            T = sr / fs[min(t, n - 1)]
            lo, hi = t + int(0.75 * T), t + int(1.25 * T) + 1
            if lo >= j:
                break
            t = lo + int(np.argmax(lp[lo:min(hi, n)]))
        i = max(j, marks[-1] + 1)
    return np.asarray(marks, dtype=np.int64), np.asarray(voiced, dtype=bool)


def _psola(x, marks, voiced, ratio_of):
    """TD-PSOLA, duration kept. Each pulse is windowed by the classic
    asymmetric Hann (rising across the gap to the previous mark, falling across
    the gap to the next), so at ratio 1 the windows sum to one and the output is
    the input; synthesis marks walk the timeline at spacing / ratio and copy the
    nearest pulse. Where pulses overlap more (pitch up) the sum is divided out."""
    n, m = len(x), len(marks)
    if m < 2:
        return x.copy()
    gaps = np.diff(marks)
    left = np.concatenate([[gaps[0]], gaps])
    right = np.concatenate([gaps, [gaps[-1]]])
    lmax = int(max(left.max(), right.max())) + 2
    xp = np.concatenate([np.zeros(lmax), x, np.zeros(lmax)])
    y = np.zeros(n + 2 * lmax)
    ws = np.zeros(n + 2 * lmax)
    cache = {}
    ts, k = float(marks[0]), 0
    while ts < n:
        while k + 1 < m and abs(marks[k + 1] - ts) <= abs(marks[k] - ts):
            k += 1
        a, b = int(left[k]), int(right[k])
        win = cache.get((a, b))
        if win is None:
            win = np.concatenate([0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a),
                                  0.5 + 0.5 * np.cos(np.pi * np.arange(b) / b)])
            cache[(a, b)] = win
        c = int(round(ts)) + lmax
        s0 = int(marks[k]) + lmax
        y[c - a:c + b] += win * xp[s0 - a:s0 + b]
        ws[c - a:c + b] += win
        ts += max(b / (ratio_of(k) if voiced[k] else 1.0), 1.0)
    return y[lmax:lmax + n] / np.maximum(ws[lmax:lmax + n], 1.0)


def intonate(raw, mean_st=0.0, range_=1.0, min_voiced=8):
    """The take's melody moved: its middle by `mean_st` semitones, its swing
    around that middle by `range_`. Duration, formants and every unvoiced sound
    are kept. Returns (wav bytes, report). Untouched when there is nothing to
    do, no numpy, not 16-bit mono, too little voice to find, or any failure."""
    try:
        mean_st = min(BOUNDS["pitch"][1], max(BOUNDS["pitch"][0], float(mean_st or 0.0)))
        range_ = min(BOUNDS["range"][1], max(BOUNDS["range"][0], float(range_ or 1.0)))
        if np is None or (abs(mean_st) < 0.05 and abs(range_ - 1.0) < 0.02):
            return raw, {"did": False, "why": "nothing to move" if np is not None else "no numpy"}
        x, params = _read(raw)
        if x is None:
            return raw, {"did": False, "why": "not 16-bit mono"}
        sr = params.framerate
        body = len(x)
        while body > 0 and x[body - 1] == 0.0:           # the tail pad stays exactly as it was
            body -= 1
        if body < int(0.2 * sr):
            return raw, {"did": False, "why": "too short"}
        xs = x[:body]
        xl = _lowpass(xs, sr)
        times, f0 = f0_track(xs, sr, xl=xl)
        if int((f0 > 0).sum()) < min_voiced:
            return raw, {"did": False, "why": "too little voice to find"}
        r = _ratio_curve(f0, mean_st, range_)
        marks, voiced = _marks(xs, sr, times, f0, lp=xl)
        hop = times[1] - times[0] if len(times) > 1 else 0.005
        fi = np.clip(np.round((marks / sr - times[0]) / hop).astype(np.int64), 0, len(r) - 1)
        rk = r[fi]
        y = _psola(xs, marks, voiced, lambda k: rk[k])
        peak_in = float(np.max(np.abs(xs))) or 1.0
        peak_out = float(np.max(np.abs(y))) or 1.0
        if peak_out > peak_in:                           # never hotter than the take was
            y *= peak_in / peak_out
        out = np.concatenate([y, x[body:]])
        v = f0 > 0
        return _write(out, params), {"did": True, "voiced": round(float(v.mean()), 3),
                                     "middle_hz": round(float(2 ** np.median(np.log2(f0[v]))), 1),
                                     "mean_st": round(mean_st, 3), "range": round(range_, 3)}
    except Exception as exc:  # noqa: BLE001
        return raw, {"did": False, "why": "%s: %s" % (type(exc).__name__, exc)}


# --- energy as colour, not volume ---------------------------------------------

def tilt_db(energy):
    try:
        e = float(energy or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(max(-TILT_MAX_DB, min(TILT_MAX_DB, TILT_DB_PER_ENERGY * e)), 2)


def energy_chain(energy):
    """The ffmpeg stages for vocal effort: 6 dB of headroom (the leveller that
    ends every clip restores the level, and nothing downstream can clip), then
    a high shelf that brightens (+) or darkens (-) the voice. "" below the
    threshold. NO compressor: the leveller caps a clip by its peak, so a denser
    take (a lower crest) would come out LOUDER than its neighbours - measured
    +0.6 to +1.1 LU on the host's voice - which is exactly the jump this must
    never make."""
    try:
        e = float(energy or 0.0)
    except (TypeError, ValueError):
        return ""
    g = tilt_db(e)
    if abs(e) < 0.02 or abs(g) < 0.1:
        return ""
    return "volume=-6dB,highshelf=f=1800:g=%.2f:t=s:w=0.5" % g


# --- the loudness the leveller will give it -------------------------------------
#
# _level_voice brings every clip to one RMS but never lets its peak past 95% of
# full scale - and for most of this station's voices the PEAK is what binds (a
# crest of 16-20 dB against the 15.5 dB the target leaves room for). So what a
# clip ends up sounding like is set by its crest factor: a performance that
# sharpens the peaks (a brighter voice, a higher melody) would come out QUIETER
# than the same line said plainly, and one that flattens them LOUDER. hold_crest
# hands the leveller back the crest the take arrived with, so the leveller gives
# the performed take the loudness it would have given the plain one.

def crest_db(raw):
    """Peak over RMS of a wav, in dB (trailing digital silence left out); None
    when it cannot be read."""
    try:
        x, _params = _read(raw)
        if x is None:
            return None
        body = len(x)
        while body > 0 and x[body - 1] == 0.0:
            body -= 1
        x = x[:body]
        rms = float(np.sqrt(np.mean(x * x))) if body else 0.0
        peak = float(np.max(np.abs(x))) if body else 0.0
        return 20.0 * math.log10(peak / rms) if rms > 0 and peak > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _sliding_min(v, w):
    """Minimum over a centred window of w samples (w odd), in O(n) (van Herk)."""
    n = len(v)
    h = w // 2
    padded = np.concatenate([np.full(h, np.inf), v, np.full(h + (-(n + 2 * h)) % w, np.inf)])
    blocks = padded.reshape(-1, w)
    fwd = np.minimum.accumulate(blocks, axis=1).ravel()
    bwd = np.minimum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].ravel()
    i = np.arange(n)
    return np.minimum(bwd[i], fwd[i + w - 1])


def _limit(x, ceiling, sr, look_ms=2.0):
    """A lookahead peak limiter with no overshoot: the gain each sample needs,
    its minimum over +-look_ms, then a box average over the same window (which
    can only stay at or under that minimum at every peak) - so the gain ramps in
    and out over ~2 x look_ms and no sample passes the ceiling."""
    w = 2 * max(1, int(round(look_ms * sr / 1000.0))) + 1
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(x), 1e-12))
    g = _sliding_min(need, w)
    k = np.ones(w) / w
    g = np.convolve(np.concatenate([np.ones(w // 2), g, np.ones(w // 2)]), k, mode="valid")
    return x * np.minimum(g, 1.0)


def hold_crest(raw, crest_in, tol=0.2):
    """The performed take with its peaks brought back to the crest it arrived
    with (crest_in, from crest_db) when the performance raised it by more than
    `tol` dB. A lower crest is left alone. Untouched on any failure."""
    try:
        if crest_in is None or np is None:
            return raw
        now = crest_db(raw)
        if now is None or now - crest_in <= tol:
            return raw
        x, params = _read(raw)
        body = len(x)
        while body > 0 and x[body - 1] == 0.0:
            body -= 1
        xs = x[:body]
        rms = float(np.sqrt(np.mean(xs * xs)))
        ceiling = rms * 10 ** (crest_in / 20.0)
        for _ in range(3):                  # the limiter lowers the RMS a hair; settle it
            ys = _limit(xs, ceiling, params.framerate)
            got = float(np.sqrt(np.mean(ys * ys)))
            if 20 * math.log10(float(np.max(np.abs(ys))) / got) <= crest_in + tol / 2:
                break
            ceiling *= 10 ** (-0.1 / 20.0)
        return _write(np.concatenate([ys, x[body:]]), params)
    except Exception:  # noqa: BLE001
        return raw

# --- [es-near] THE WORDS THE ENGINE READS (emotion engine step 4) -----------------
#
# Neither clone engine has a tag vocabulary: a bracketed direction is read aloud
# as words. XTTS loops on ellipses and em-dashes inside its sentence splitter,
# truncates a sentence past 250 characters, and hears one to three CAPS words as
# emphasis; F5 spells a CAPS word letter by letter (its own README) and takes its
# pauses from commas and spaces. The writer may emit a forgiving micro-grammar -
# [emph]word[/emph] and [beat] - resolved here; unmarked text is untouched.

import re as _re

CAPS_EMPHASIS_MAX = 3                    # XTTS: this many CAPS words stay emphasis
XTTS_SENTENCE_MAX = 220                  # XTTS: a longer sentence is cut at a clause
# Real acronyms are spelled by both engines, and should be: never emphasis, never lowered.
ACRONYMS = frozenset((
    "DJ DJS FM AM TV UK USA EU UN NASA FBI CIA NFL NBA NHL MLB BBC CNN NPR CEO CEOS AI "
    "OK UFO UFOS DNA VIP VIPS ASAP LOL OMG GPS ATM SUV RV NYC HQ IQ DMV CD CDS DVD USB "
    "PDF URL RSVP FAQ ETA").split())

_ACTION = _re.compile(
    r"^(?:(?:he|she|they|i|we|you|[a-z]+ly|long|short|dramatic|awkward|little|small|big|"
    r"nervous|quiet|soft|brief|another|a)\s+){0,2}"
    r"(?:laugh\w*|chuckl\w*|giggl\w*|snicker\w*|cackl\w*|sigh\w*|gasp\w*|groan\w*|grunt\w*|"
    r"sniff\w*|sob|sobs|sobbing|cough\w*|clear\w*\s+(?:\w+\s+)?throat|paus\w*|beat|"
    r"grin\w*|smil\w*|smirk\w*|shrug\w*|wink\w*|nod|nods|nodding|whisper\w*|shout\w*|"
    r"yell\w*|mutter\w*|mumbl\w*|scoff\w*|snort\w*|cry|cries|crying|inhal\w*|exhal\w*|"
    r"breath|breathe|breathes|breathing|clap|claps|clapping|hum|hums|humming|sing|sings|"
    r"singing|stammer\w*|gulp\w*|winc\w*|eye[\s-]?roll\w*|rolls?\s+(?:\w+\s+)?eyes|"
    r"sarcastic\w*|deadpan|softly|quietly|loudly|excitedly|nervously|angrily|sadly|"
    r"happily|dramatically|mocking\w*)"
    r"(?:\W.*)?$", _re.I | _re.S)
_EMPH = _re.compile(r"\[(?:emph|emphasis|stress)\]\s*([^\[\]]{1,60}?)\s*\[/(?:emph|emphasis|stress)\]", _re.I)
_BEAT = _re.compile(r"\s*\[(?:beat|pause)\]\s*", _re.I)
_STARRED = _re.compile(r"(?<![\w*])(\*{1,2}|_{1,2})(?=\S)([^*_\n]{1,60}?)(?<=\S)\1(?![\w*])")
_BRACKETED = _re.compile(r"\[[^\[\]\n]{0,80}\]|\{[^{}\n]{0,80}\}|</?[A-Za-z][^<>\n]{0,60}>")
_PAREN = _re.compile(r"\(([^()\n]{1,60})\)")
_CAPSWORD = _re.compile(r"\b[A-Z][A-Z']*[A-Z]\b")


def _is_action(words):
    w = " ".join(str(words or "").split())
    return bool(w) and len(w.split()) <= 6 and bool(_ACTION.match(w))


def _caps(phrase):
    """A marked phrase as emphasis: its words of three letters or more in CAPS
    (one to CAPS_EMPHASIS_MAX words; a longer phrase stays as written)."""
    words = str(phrase or "").split()
    if not words or len(words) > CAPS_EMPHASIS_MAX:
        return " ".join(words)
    return " ".join(w.upper() if sum(c.isalpha() for c in w) >= 3 else w for w in words)


def unmark(text):
    """The written line with its markup resolved (see the module notes above);
    the line itself when it carries none."""
    raw = str(text or "")
    try:
        if not any(c in raw for c in "[*_{<"):
            return raw
        t = _EMPH.sub(lambda m: _caps(m.group(1)), raw)
        beat = [False]

        def _beat(_m):
            beat[0] = True
            return " — "
        t = _BEAT.sub(_beat, t)

        def _star(m):
            inner = m.group(2).strip()
            if _is_action(inner):
                return " "
            return _caps(inner) if len(inner.split()) == 1 else inner
        t = _STARRED.sub(_star, t)
        t = _BRACKETED.sub(" ", t)
        if t == raw:
            return raw
        if beat[0]:                                   # a beat at either end is no beat
            t = _re.sub(r"^[\s—]+|[\s—]+$", "", t)
        t = _re.sub(r"[ \t]{2,}", " ", t)
        t = _re.sub(r" +([,.;:!?])", r"\1", t)
        return t.strip()
    except Exception:  # noqa: BLE001
        return raw


def _sentence_start(text, at):
    i = at - 1
    while i >= 0 and text[i] in " \t\n\"'“‘(":
        i -= 1
    return i < 0 or text[i] in ".!?"


def _decap(word, first):
    w = word.lower()
    if w == "i" or w.startswith("i'"):
        w = "I" + w[1:]
    return w[:1].upper() + w[1:] if first else w


def caps_for(text, engine):
    """CAPS words as `engine` should see them: XTTS keeps the CAPS_EMPHASIS_MAX
    longest of three letters or more (the rest lowered); F5 keeps none; an
    acronym is never touched; any other engine gets the text as it is."""
    t = str(text or "")
    try:
        if engine not in ("xtts", "f5"):
            return t
        hits = [m for m in _CAPSWORD.finditer(t) if m.group(0).replace("'", "") not in ACRONYMS]
        if not hits:
            return t
        keep = set()
        if engine == "xtts":
            emph = [m for m in hits if sum(c.isalpha() for c in m.group(0)) >= 3]
            keep = {m.start() for m in sorted(emph, key=lambda m: (-len(m.group(0)), m.start()))[:CAPS_EMPHASIS_MAX]}
        out, pos = [], 0
        for m in hits:
            if m.start() in keep:
                continue
            out.append(t[pos:m.start()])
            out.append(_decap(m.group(0), _sentence_start(t, m.start())))
            pos = m.end()
        out.append(t[pos:])
        return "".join(out)
    except Exception:  # noqa: BLE001
        return t


def presplit(text, cap=XTTS_SENTENCE_MAX, floor=60):
    """Every sentence longer than `cap` characters cut into sentences at its last
    clause break (", " "; " ": ") before the cap and past `floor`; a sentence with
    no such break is left for the engine's own splitter."""
    t = str(text or "")
    try:
        if len(t) <= cap:
            return t
        out = []
        for s in _re.split(r"(?<=[.!?])\s+", t):
            while len(s) > cap:
                cut = max(s.rfind(", ", 0, cap), s.rfind("; ", 0, cap), s.rfind(": ", 0, cap))
                if cut < floor:
                    break
                out.append(s[:cut].rstrip(",;: ") + ".")
                s = s[cut + 2:].lstrip()
                s = s[:1].upper() + s[1:]
            if s:
                out.append(s)
        return " ".join(out)
    except Exception:  # noqa: BLE001
        return t


def speakable(text, engine, flatten=None):
    """The words `engine` is handed for a line: markup resolved (unmark), action
    parentheses dropped, CAPS as the engine should see them (caps_for), then the
    station's flattener (`flatten`, its _xtts_sanitize: plain ASCII, no ellipsis
    or em-dash) and, for XTTS, sentences cut to XTTS_SENTENCE_MAX. On any failure:
    the flattener on the line as written, which is what it was."""
    raw = str(text or "")
    try:
        t = unmark(raw)
        t = _PAREN.sub(lambda m: " " if _is_action(m.group(1)) else m.group(0), t)
        t = caps_for(t, engine)
        if flatten is not None:
            t = flatten(t)
            t = _re.sub(r"\s+([,.;:!?])", r"\1", t)    # "Well , I" (a flattened dash) reads "Well, I"
        if engine == "xtts":
            t = presplit(t)
        return t
    except Exception:  # noqa: BLE001
        return flatten(raw) if flatten is not None else raw


# --- [es-near] which reference baked a take (emotion engine step 2b) ----------------

def baked_ref(stamp):
    """The reference file (its stem: "reference", "reference_f5", later
    "reference_<family>") a take's ES stamp says it was made with, from `ref` or
    `native.ref`; None when the take predates the record (a match for anything)."""
    if not isinstance(stamp, dict):
        return None
    got = stamp.get("ref")
    if got is None and isinstance(stamp.get("native"), dict):
        got = stamp["native"].get("ref")
    return None if got is None else str(got)
