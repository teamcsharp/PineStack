"""[s3-es-voice] System 3's ES roll shapes the recording.

2026-09-28, the operator: "The intention is for categories to be scrolled via
RNG and then the subcategories which is fed to the LLM for direction on how to
write that particular line in the correspondence and also is fed to the
intonation engine to take place affecting the way the recording is made so they
emotionally reflect the dialogue."

System 3 now puts the rolled ES row's `voice` (its Tables tab: tempo, pitch,
range, energy, pause, temp - system3_tables._ES_VOICE / _ES_ITEM_VOICE) on the
turn at the turn's intensity; system3_perf_voice / LineHandle.voice hand it to
the station. This tool carries it the rest of the way (es_voice.py is the DSP):

  1. performance_vector(..., es=): an ES line is voiced by the table. The dims'
     share of pace, pitch swing, energy and pauses steps aside (their share of
     the stumbles stays), the voice's signature, the macros and the trims stay,
     and the table's block goes on after the strength dial, literal. The vector
     carries `es` (the block) and `range` - the performance's own share of the
     pitch swing (never the signature's: the clone engine already speaks that).
  2. THE ENGINE'S OWN CONTROLS (voice_generate -> _ES_ENGINE_OPTS -> the clone
     servers' `opts`): XTTS takes the ES tempo as its native speed and the ES
     temp as its sampling temperature (XTTS_TEMP_BASE, 0.70 = the server's own
     default, +- the table); F5 the tempo as its speed. What the engine did is
     not done again by the DSP (es_native_tempo).
  3. GAP 1 - pitch_var reached nothing: perf_apply now moves the melody first
     (es_voice.intonate: TD-PSOLA on the take's own pulses; the middle by the
     ES pitch, the swing by `range`; duration and formants kept).
  4. GAP 2 - small energy and pause changes were swallowed: the pause stretch
     runs from 3% (was 15%), the tempo from 1% (was 2%), and energy is heard as
     colour, not volume (the volume it set was levelled straight back out, and
     nothing under 0.1 did anything): es_voice.energy_chain - headroom, the
     station's compressor for real effort, a high shelf - and _level_voice
     still has the last word on loudness.
  5. GAP 3 - the pantry ignored the performance: a take now records the ES it
     carries (clip["es"]), and the two roads that hand a shelf take to a line
     with an ES roll of its own (dj_speak #842, speak_turns #886) re-perform it
     when the two differ - the remaining tempo, melody, effort and pauses on the
     finished take, levelled, its tail pad kept, no engine visit. The KEY is not
     touched: it is a render address twenty roads recompute from the words, the
     voice and the engine (reconcile_round_takes, the recast desk, the
     cupboard's readiness, script production), and a performance in it would
     make every banked round miss its own takes. A long line joined from pieces
     keeps its pieces' record.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, with es_voice.py and the System 3 edits
(edit_esvoice_tables/engine/runtime.py) in the repo.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- the module --------------------------------------------------------------
    ("esv-import",
     'import recast_desk                        # [#1215]: the cupboard recast desk\n',
     'import recast_desk                        # [#1215]: the cupboard recast desk\n'
     'import es_voice as _es_voice              # [s3-es-voice] how a feeling sounds: the DSP + the engines\' own controls\n', 1),

    # --- 1. the vector -------------------------------------------------------------
    ("esv-vector-sig",
     'def performance_vector(who: str, voice: str = "",\n'
     '                       state: dict[str, float] | None = None\n'
     '                       ) -> dict[str, float]:                # [#1232]\n',
     'def performance_vector(who: str, voice: str = "",\n'
     '                       state: dict[str, float] | None = None,\n'
     '                       es: dict[str, Any] | None = None      # [s3-es-voice] the ES row\'s voice\n'
     '                       ) -> dict[str, float]:                # [#1232]\n', 1),
    ("esv-vector-state",
     '    vec["pace"] *= 1 + 0.12 * state["excitement"] - 0.10 * state["fatigue"]\n'
     '    vec["pitch_var"] *= 1 + 0.2 * state["excitement"]\n'
     '    vec["filler"] += 0.3 * state["confusion"] + 0.2 * state["nervousness"]\n'
     '    vec["restart"] += 0.25 * state["confusion"] \\\n'
     '        + 0.15 * state["nervousness"]\n'
     '    vec["repeat"] += 0.15 * state["nervousness"]\n'
     '    vec["energy"] += (0.25 * state["excitement"]\n'
     '                      + 0.2 * state["irritation"] - 0.2 * state["fatigue"])\n'
     '    vec["pause_scale"] *= 1 + 0.25 * state["fatigue"] \\\n'
     '        - 0.1 * state["irritation"]\n',
     '    # [s3-es-voice] A line whose ES roll carries a voice (System 3\'s ES table)\n'
     '    # is voiced by that table: the dims\' share of pace, pitch swing, energy and\n'
     '    # pauses steps aside (their share of the stumbles stays) and the table\'s\n'
     '    # block goes on after the strength dial, below. `_range` is the\n'
     '    # performance\'s own share of pitch_var - never the signature\'s, which the\n'
     '    # clone engine already speaks - and it is what perf_apply moves (gap 1).\n'
     '    _es_on = isinstance(es, dict)\n'
     '    _sv = 0.0 if _es_on else 1.0\n'
     '    _range = 1.0\n'
     '    vec["pace"] *= 1 + _sv * (0.12 * state["excitement"] - 0.10 * state["fatigue"])\n'
     '    _range *= 1 + _sv * 0.2 * state["excitement"]\n'
     '    vec["filler"] += 0.3 * state["confusion"] + 0.2 * state["nervousness"]\n'
     '    vec["restart"] += 0.25 * state["confusion"] \\\n'
     '        + 0.15 * state["nervousness"]\n'
     '    vec["repeat"] += 0.15 * state["nervousness"]\n'
     '    vec["energy"] += _sv * (0.25 * state["excitement"]\n'
     '                            + 0.2 * state["irritation"] - 0.2 * state["fatigue"])\n'
     '    vec["pause_scale"] *= 1 + _sv * (0.25 * state["fatigue"]\n'
     '                                     - 0.1 * state["irritation"])\n', 1),
    ("esv-vector-amusement",
     '    vec["pitch_var"] *= 1 + 0.22 * state["amusement"]\n'
     '    vec["energy"] += 0.16 * state["amusement"]\n',
     '    _range *= 1 + _sv * 0.22 * state["amusement"]            # [s3-es-voice]\n'
     '    vec["energy"] += _sv * 0.16 * state["amusement"]\n'
     '    vec["pitch_var"] *= _range\n', 1),
    ("esv-vector-macro",
     '    for key, amount in (MACRO_STATES.get(macro) or {}).items():\n'
     '        if key in _MACRO_MULT:\n'
     '            vec[key] *= amount\n'
     '        else:\n'
     '            vec[key] += amount\n',
     '    for key, amount in (MACRO_STATES.get(macro) or {}).items():\n'
     '        if key in _MACRO_MULT:\n'
     '            vec[key] *= amount\n'
     '        else:\n'
     '            vec[key] += amount\n'
     '        if key == "pitch_var":                              # [s3-es-voice] a mood\'s swing is a performance\n'
     '            _range *= amount\n', 1),
    ("esv-vector-out",
     '    if not macro and not trim             and all(abs(vec[key] - _PERF_IDENTITY[key]) < 0.03\n'
     '                    for key in _PERF_IDENTITY):\n'
     '        return {}\n'
     '    out = {key: round(vec[key], 3) for key in _PERF_IDENTITY}\n',
     '    # [s3-es-voice] the ES table, literal, after the strength dial (the perf\n'
     '    # switch still turns it off with the rest, above)\n'
     '    _range = 1 + (_range - 1) * strength\n'
     '    _es = _es_voice.clean(es) if _es_on else {}\n'
     '    if _es_on:\n'
     '        vec["pace"] *= _es.get("tempo", 1.0)\n'
     '        vec["energy"] += _es.get("energy", 0.0)\n'
     '        vec["pause_scale"] *= _es.get("pause", 1.0)\n'
     '        _range *= _es.get("range", 1.0)\n'
     '    if not macro and not trim and not _es_on             and all(abs(vec[key] - _PERF_IDENTITY[key]) < 0.03\n'
     '                    for key in _PERF_IDENTITY):\n'
     '        return {}\n'
     '    out = {key: round(vec[key], 3) for key in _PERF_IDENTITY}\n'
     '    out["range"] = round(_range, 3)                         # [s3-es-voice] the swing perf_apply moves\n'
     '    if _es_on:\n'
     '        out["es"] = _es                                     # [s3-es-voice] the engines\' share + the melody\'s middle\n', 1),

    # --- 2. the engines' own controls ------------------------------------------------
    ("esv-engine-opts",
     'async def _xtts_synthesize(text: str, voice: str) -> bytes:\n',
     '# [s3-es-voice] THE ENGINE\'S OWN CONTROLS for the line being rendered: set by\n'
     '# voice_generate around synthesize() from the line\'s ES block\n'
     '# (es_voice.engine_opts) and merged into the clone server\'s `opts` - XTTS: speed\n'
     '# and temperature, F5: speed. {} for every other line, which is what it was.\n'
     '_ES_ENGINE_OPTS: ContextVar[dict] = ContextVar("es_engine_opts", default={})\n'
     '# The XTTS server samples at 0.70 unless told otherwise (REACHY_XTTS_TEMP is not\n'
     '# set where the voice director launches it); the ES temp moves around this.\n'
     'XTTS_TEMP_BASE = float(os.getenv("XTTS_TEMP_BASE", "0.70") or 0.70)\n'
     '\n'
     '\n'
     'async def _xtts_synthesize(text: str, voice: str) -> bytes:\n', 1),
    ("esv-xtts-opts",
     '    if abs(rate - 1.0) > 0.01:\n'
     '        payload["opts"] = {"speed": max(0.75, min(1.25, rate))}\n',
     '    if abs(rate - 1.0) > 0.01:\n'
     '        payload["opts"] = {"speed": max(0.75, min(1.25, rate))}\n'
     '    if _ES_ENGINE_OPTS.get():                             # [s3-es-voice] the feeling\'s speed + temperature\n'
     '        payload["opts"] = dict(payload.get("opts") or {}, **_ES_ENGINE_OPTS.get())\n', 1),
    ("esv-f5-opts",
     '            resp = await client.post(f"{F5_URL}/synthesize", json=payload)\n',
     '            if _ES_ENGINE_OPTS.get().get("speed"):                # [s3-es-voice] the feeling\'s speed\n'
     '                payload["opts"]["speed"] = _ES_ENGINE_OPTS.get()["speed"]\n'
     '            resp = await client.post(f"{F5_URL}/synthesize", json=payload)\n', 1),
    ("esv-generate-synth",
     '        audio, ext = await synthesize(text, voice, engine)\n',
     '        # [s3-es-voice] the line\'s ES block asks the engine first (its own speed\n'
     '        # and temperature); what it did natively is not done again by the DSP\n'
     '        _es_block = ((fx or {}).get("perf") or {}).get("es") if isinstance((fx or {}).get("perf"), dict) else None\n'
     '        _es_opts, _es_native = ({}, {})\n'
     '        if isinstance(_es_block, dict):\n'
     '            _es_opts, _es_native = _es_voice.engine_opts(\n'
     '                _es_block, engine, float(dj_settings().get("speech_rate") or 1.0), XTTS_TEMP_BASE)\n'
     '        _es_scope = _ES_ENGINE_OPTS.set(_es_opts)\n'
     '        try:\n'
     '            audio, ext = await synthesize(text, voice, engine)\n'
     '        finally:\n'
     '            _ES_ENGINE_OPTS.reset(_es_scope)\n', 1),
    ("esv-generate-fx",
     '    if fx:\n'
     '        audio = await asyncio.to_thread(voice_effect_apply, audio, ext, fx)\n',
     '    if fx and _es_native.get("tempo"):                        # [s3-es-voice] the engine\'s share, done\n'
     '        fx = dict(fx, perf=dict(fx["perf"], es_native_tempo=float(_es_native["tempo"])))\n'
     '    if fx:\n'
     '        audio = await asyncio.to_thread(voice_effect_apply, audio, ext, fx)\n', 1),
    ("esv-generate-clip",
     '        "service": service,\n'
     '    }\n'
     '    if _rk:\n',
     '        "service": service,\n'
     '        # [s3-es-voice] what performance this take carries - a shelf road that\n'
     '        # hands it to a line with another feeling re-performs it (_es_pantry_perform)\n'
     '        **({"es": dict(_es_voice.clean(_es_block), native=_es_native)}\n'
     '           if isinstance(_es_block, dict) else {}),\n'
     '    }\n'
     '    if _rk:\n', 1),

    # --- the rolls reach the vector --------------------------------------------------------
    ("esv-larder",
     '                    who, voice,\n'
     '                    state=((globals()["system3_perf_state"](entry, None, text, who)\n',
     '                    who, voice,\n'
     '                    es=(globals()["system3_perf_voice"](entry, None, text, who)   # [s3-es-voice]\n'
     '                        if globals().get("system3_perf_voice") else None),\n'
     '                    state=((globals()["system3_perf_state"](entry, None, text, who)\n', 1),
    ("esv-turns",
     '            state=(globals()["system3_perf_state"](ready_meta, turns, said, who)\n'
     '                   if _s3_active() and globals().get("system3_perf_state")\n'
     '                   else None))\n',
     '            state=(globals()["system3_perf_state"](ready_meta, turns, said, who)\n'
     '                   if _s3_active() and globals().get("system3_perf_state")\n'
     '                   else None),\n'
     '            es=(globals()["system3_perf_voice"](ready_meta, turns, said, who)   # [s3-es-voice]\n'
     '                if _s3_active() and globals().get("system3_perf_voice")\n'
     '                else None))\n', 1),
    ("esv-line",
     '    if _s3_perf:\n'
     '        vec = performance_vector(who, voice or "", state=_s3_perf)\n',
     '    _s3_voice = getattr(_s3_spoken_handle, "voice", None)   # [s3-es-voice] how the feeling sounds\n'
     '    if _s3_perf or isinstance(_s3_voice, dict):\n'
     '        vec = performance_vector(who, voice or "", state=_s3_perf,\n'
     '                                 es=_s3_voice if isinstance(_s3_voice, dict) else None)\n', 1),

    # --- 3 + 4. the DSP -------------------------------------------------------------
    ("esv-dsp-tempo",
     '    if abs(pace - 1.0) > 0.02:\n'
     '        parts.append(f"atempo={pace:.3f}")\n',
     '    # [s3-es-voice] what the engine already did natively is not done twice;\n'
     '    # and a 1% tempo is a performance now (was 2%)\n'
     '    pace = max(0.6, min(1.6, pace / max(0.5, float(vec.get("es_native_tempo") or 1.0))))\n'
     '    if abs(pace - 1.0) > 0.01:\n'
     '        parts.append(f"atempo={pace:.3f}")\n', 1),
    ("esv-dsp-energy",
     '    energy = float(vec.get("energy") or 0.0)\n'
     '    if energy > 0.1:\n',
     '    energy = float(vec.get("energy") or 0.0)\n'
     '    # [s3-es-voice] ENERGY IS COLOUR, NOT VOLUME (gap 2). The volume below was\n'
     '    # levelled straight back out by _level_voice and nothing under 0.1 either\n'
     '    # way did anything: vocal effort is a brighter, pressed voice or a softer,\n'
     '    # darker one (es_voice.energy_chain: headroom, the station\'s compressor\n'
     '    # for real effort, a high shelf); the leveller keeps the last word.\n'
     '    _effort = _es_voice.energy_chain(energy)\n'
     '    if _effort:\n'
     '        parts.append(_effort)\n'
     '        energy = 0.0\n'
     '    if energy > 0.1:\n', 1),
    ("esv-apply-melody",
     '        chain = perf_dsp_chain(vec, rate)\n'
     '        if chain:\n'
     '            raw = _ffmpeg_af(raw, chain)\n',
     '        # [s3-es-voice] THE MELODY FIRST (gap 1: pitch_var reached nothing): the\n'
     '        # middle by the ES pitch, the swing by `range`, on the take\'s own\n'
     '        # pulses (es_voice.intonate: TD-PSOLA, duration and formants kept)\n'
     '        _es = vec.get("es") if isinstance(vec.get("es"), dict) else {}\n'
     '        _mid = float(_es.get("pitch") or 0.0)\n'
     '        _swing = float(vec.get("range") or 1.0)\n'
     '        if abs(_mid) >= 0.05 or abs(_swing - 1.0) >= 0.02:\n'
     '            raw, _how = _es_voice.intonate(raw, _mid, _swing)\n'
     '        chain = perf_dsp_chain(vec, rate)\n'
     '        if chain:\n'
     '            raw = _ffmpeg_af(raw, chain)\n', 1),
    ("esv-apply-pause",
     '        scale = float(vec.get("pause_scale") or 1.0)\n'
     '        if abs(scale - 1.0) > 0.15:\n'
     '            raw = perf_pause_stretch(raw, scale)\n',
     '        scale = float(vec.get("pause_scale") or 1.0)\n'
     '        if abs(scale - 1.0) > 0.03:                     # [s3-es-voice] was 0.15 (gap 2)\n'
     '            raw = perf_pause_stretch(raw, scale)\n', 1),

    # --- 5. the pantry ------------------------------------------------------------------
    ("esv-pantry-perform",
     '    row["used"] = int(row.get("used") or 0) + 1\n'
     '    return dict(clip)\n',
     '    row["used"] = int(row.get("used") or 0) + 1\n'
     '    return dict(clip)\n'
     '\n'
     '\n'
     '# --- [s3-es-voice] A SHELF TAKE IS PERFORMED FOR THE LINE THAT AIRS IT (gap 3) -\n'
     '# The pantry is keyed on the words, the voice and the engine, never on the\n'
     '# performance, and that key is a render ADDRESS twenty roads recompute from those\n'
     '# three (reconcile_round_takes, the recast desk, the cupboard\'s readiness,\n'
     '# script production): a performance in it would make every banked round miss its\n'
     '# own takes. So a take says what it carries instead (clip["es"], stamped by\n'
     '# voice_generate), and the two roads that hand a shelf take to a line with an ES\n'
     '# roll of its own (dj_speak #842, speak_turns #886) re-perform it when the two\n'
     '# differ: the remaining tempo, melody, effort and pauses on the finished take, no\n'
     '# engine visit, levelled, its tail pad kept, as a new file. A banked round\'s own\n'
     '# takes were cut for its own turns and air as they are; a line with no ES of its\n'
     '# own airs the take as it is. The temperature cannot be redone after the fact.\n'
     'ES_SHELF_TOLERANCE = {"tempo": 0.01, "pitch": 0.1, "range": 0.02, "energy": 0.03, "pause": 0.02}\n'
     '\n'
     '\n'
     'def _es_reperform_blocking(clip: dict[str, Any], want: dict[str, Any]) -> dict[str, Any] | None:\n'
     '    name = _take_media_name(clip)\n'
     '    path = (VOICE_MEDIA_DIR / name) if name else None\n'
     '    if path is None or not path.is_file():\n'
     '        return None\n'
     '    delta = _es_voice.ratio(want, clip.get("es") or {})\n'
     '    if all(abs(delta[k] - _es_voice.NEUTRAL[k]) < tol for k, tol in ES_SHELF_TOLERANCE.items()):\n'
     '        return None\n'
     '    body, pad_ms = _es_voice.split_tail(path.read_bytes())\n'
     '    out = perf_apply(body, {"pace": delta["tempo"], "range": delta["range"],\n'
     '                            "energy": delta["energy"], "pause_scale": delta["pause"],\n'
     '                            "es": {"pitch": delta["pitch"]}})\n'
     '    out = _wav_tail_pad(_level_rms(out, target=int(5200 * box_gain())), pad_ms)\n'
     '    stored = _store_media(out, "wav")\n'
     '    try:\n'
     '        with wave.open(io.BytesIO(out), "rb") as probe:\n'
     '            seconds = round(probe.getnframes() / float(probe.getframerate() or 1), 2)\n'
     '    except Exception:  # noqa: BLE001\n'
     '        seconds = float(clip.get("seconds") or 0)\n'
     '    return {**clip, **stored, "seconds": seconds,\n'
     '            "es": dict(_es_voice.clean(want), reperformed=delta),\n'
     '            "from_take": str(clip.get("path") or "")}\n'
     '\n'
     '\n'
     'async def _es_pantry_perform(clip: dict[str, Any] | None, vec: dict[str, Any] | None,\n'
     '                             who: str = "") -> dict[str, Any] | None:\n'
     '    """[s3-es-voice] `clip` off the shelf, performed for this line\'s ES (the\n'
     '    vector\'s `es`), or the clip as it is: no ES on the line, the same one\n'
     '    already in the take, or anything at all going wrong - the take airs."""\n'
     '    want = (vec or {}).get("es") if isinstance(vec, dict) else None\n'
     '    if not clip or not isinstance(want, dict):\n'
     '        return clip\n'
     '    try:\n'
     '        got = await asyncio.to_thread(_es_reperform_blocking, clip, want)\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        pipeline_log("perf", "(s3-es-voice) a shelf take could not be re-performed - it airs as made",\n'
     '                     extra=("%s: %s" % (type(exc).__name__, exc))[:300])\n'
     '        return clip\n'
     '    if not got:\n'
     '        return clip\n'
     '    pipeline_log("perf", "(s3-es-voice) a shelf take was re-performed for its line\'s feeling"\n'
     '                 + (" - " + str(who) if who else ""),\n'
     '                 extra=json.dumps({"want": want, "baked": clip.get("es") or {},\n'
     '                                   "delta": (got.get("es") or {}).get("reperformed")},\n'
     '                                  default=str)[:800])\n'
     '    return got\n', 1),
    ("esv-shelf-line",
     '                clip = _prep_ready\n'
     '                engine = str(_prep_ready.get("engine") or engine)\n',
     '                clip = await _es_pantry_perform(_prep_ready, vec, who)   # [s3-es-voice]\n'
     '                engine = str(_prep_ready.get("engine") or engine)\n', 1),
    ("esv-shelf-turns",
     '                take_note(item["who"], v, engine, text, _ready, 0, "shelf")\n'
     '                return _ready\n',
     '                take_note(item["who"], v, engine, text, _ready, 0, "shelf")\n'
     '                return await _es_pantry_perform(_ready, item.get("vec"), item["who"])   # [s3-es-voice]\n', 1),

    # --- a long line joined from pieces keeps its pieces' record ------------------------------
    ("esv-join-init",
     '            made: list[str] = []\n'
     '            secs = 0.0\n',
     '            made: list[str] = []\n'
     '            secs = 0.0\n'
     '            _es_made = None                        # [s3-es-voice] what the pieces carry\n', 1),
    ("esv-join-loop",
     '                if part and part.get("path"):\n'
     '                    made.append(part["path"])\n',
     '                if part and part.get("path"):\n'
     '                    made.append(part["path"])\n'
     '                    _es_made = part.get("es") or _es_made       # [s3-es-voice]\n', 1),
    ("esv-join-out",
     '                    out.setdefault("seconds", round(secs, 2))\n',
     '                    out.setdefault("seconds", round(secs, 2))\n'
     '                    if _es_made:                               # [s3-es-voice]\n'
     '                        out["es"] = _es_made\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
