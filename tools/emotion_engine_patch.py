"""[emotion-engine] hook emotion_engine.py into the voice door (voice_generate).

Usage (ON THE HOST): python3 tools/emotion_engine_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

EDITS = [
    ("import", '''import es_voice as _es_voice              # [s3-es-voice] how a feeling sounds: the DSP + the engines' own controls
''', '''import es_voice as _es_voice              # [s3-es-voice] how a feeling sounds: the DSP + the engines' own controls
import emotion_engine as _emotion           # [emotion-engine] the emotion engine's own window
''', 1),
    ("begin", '''    try:
        # [s3-es-voice] the line's ES block asks the engine first (its own speed
        # and temperature); what it did natively is not done again by the DSP
        _es_block = ((fx or {}).get("perf") or {}).get("es") if isinstance((fx or {}).get("perf"), dict) else None
''', '''    try:                                                     # [emotion-engine] the line entered the door
        _ee = _emotion.begin(line, speaker, engine, voice, text,
                             ((fx or {}).get("perf") or {}).get("es") if isinstance((fx or {}).get("perf"), dict) else None)
    except Exception:  # noqa: BLE001
        _ee = ""
    try:
        # [s3-es-voice] the line's ES block asks the engine first (its own speed
        # and temperature); what it did natively is not done again by the DSP
        _es_block = ((fx or {}).get("perf") or {}).get("es") if isinstance((fx or {}).get("perf"), dict) else None
''', 1),
    ("rendering", '''        _es_scope = _ES_ENGINE_OPTS.set(_es_opts)
        try:
            audio, ext = await synthesize(text, voice, engine)
        finally:
            _ES_ENGINE_OPTS.reset(_es_scope)
    except HTTPException:
        voice_refund(len(text))
        raise
    except Exception as exc:
        voice_refund(len(text))
        raise HTTPException(
''', '''        _es_scope = _ES_ENGINE_OPTS.set(_es_opts)
        try:
            _emotion.rendering(_ee)                          # [emotion-engine]
            audio, ext = await synthesize(text, voice, engine)
        finally:
            _ES_ENGINE_OPTS.reset(_es_scope)
    except HTTPException as _ee_exc:
        voice_refund(len(text))
        _emotion.failed(_ee, str(getattr(_ee_exc, "detail", "") or _ee_exc))   # [emotion-engine]
        raise
    except Exception as exc:
        voice_refund(len(text))
        _emotion.failed(_ee, "synthesis failed - %s" % exc)                      # [emotion-engine]
        raise HTTPException(
''', 1),
    ("synthed", '''    if fx and _es_native.get("tempo"):                        # [s3-es-voice] the engine's share, done
        fx = dict(fx, perf=dict(fx["perf"], es_native_tempo=float(_es_native["tempo"])))
    if fx:
        audio = await asyncio.to_thread(voice_effect_apply, audio, ext, fx)
''', '''    if fx and _es_native.get("tempo"):                        # [s3-es-voice] the engine's share, done
        fx = dict(fx, perf=dict(fx["perf"], es_native_tempo=float(_es_native["tempo"])))
    try:
        _emotion.synthed(_ee, audio, ext)                    # [emotion-engine] the raw take, kept
    except Exception:  # noqa: BLE001
        pass
    _ee_dsp = time.monotonic()
    if fx:
        audio = await asyncio.to_thread(voice_effect_apply, audio, ext, fx)
'''  , 1),
    ("shaped", '''    took = int((time.monotonic() - started) * 1000)
    length = await _clip_seconds_async(f"/media/{key}")
''', '''    took = int((time.monotonic() - started) * 1000)
    length = await _clip_seconds_async(f"/media/{key}")
    try:
        _emotion.shaped(_ee, key, int((time.monotonic() - _ee_dsp) * 1000), length)   # [emotion-engine]
    except Exception:  # noqa: BLE001
        pass
''', 1),
    ("install", '''try:
    import sfx_display as _sfx_display
''', '''try:                                                        # [emotion-engine] GET /api/emotion/state
    _emotion.install(app, globals())
except Exception as _ee_exc:  # noqa: BLE001
    print("the emotion engine window did not install: %s: %s" % (type(_ee_exc).__name__, _ee_exc))
try:
    import sfx_display as _sfx_display
''', 1),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[emotion-engine]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "%s: anchor found %d times" % (label, got)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/app.py.bak-emotion-engine")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
