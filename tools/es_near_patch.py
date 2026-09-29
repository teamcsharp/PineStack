"""[es-near] The emotion engine's near-term wiring in app.py (PLAN.md steps 2 and 4).

STEP 2a - EXPRESSIVE TAKES NO LONGER AIR QUIETER. es_voice.hold_crest was dead
code (no caller). _level_voice brings a clip to one RMS but never lets its peak
past 95% of full scale, and for this station's voices the PEAK binds: a
performance that sharpens the peaks (a brighter shelf, a higher melody) came out
quieter than the same line said plainly (the module's own measurement: -0.6 to
-1.1 LU). perf_apply now measures the take's crest before the performance and
hands the leveller that crest back after it (a lookahead limiter, no overshoot;
a lower crest is left alone), so a performed take gets the plain take's loudness.
Every road through perf_apply gets it - voice_generate and the shelf re-perform.

STEP 2b - A SHELF TAKE KNOWS WHICH REFERENCE MADE IT. voice_ref_for(vid, engine)
is now the one truth for which reference file an engine clones a voice from (F5
prefers reference_f5.wav, #816 - the rule that sat inline in _f5_synthesize;
the per-emotion banks of step 5 will choose here). An ES take's stamp records it
(clip["es"]["native"]["ref"]: what the engine performed natively), and the two
shelf roads (dj_speak #842, the premake #886) treat a take made from another
reference than the engine would use now as a MISS - rendered fresh, logged -
because the re-perform delta es_voice.ratio(want, baked) is only honest against
the same baseline. A take whose stamp predates the record is a hit, as before:
the shelf is not thrown away at deploy, and a line with no ES is untouched.

STEP 4 - THE WORDS THE ENGINE READS. The three synthesis roads hand their engine
es_voice.speakable(text, engine, _xtts_sanitize) instead of _xtts_sanitize(text):
markup resolved and dropped (a *laughs* was read out as the word "laughs"), CAPS
as the engine should see them (XTTS: at most three, as emphasis; F5: none - it
spells them), then the same flattener as before (no ellipsis, no em-dash, plain
ASCII) and, for XTTS, sentences cut under 220 characters at a clause break. And
spoken_text - the one door every spoken line passes - resolves the writer's
micro-grammar first (es_voice.unmark: [emph]x[/emph] -> CAPS, [beat] -> a dash,
an *action* dropped whole) before its SPOKEN_NOISE strip; a line with no markup
is byte-for-byte what it was.

Needs es_voice.py with tools/edit_es_voice_near.py applied (unmark, speakable,
baked_ref) - apply that first. Every anchor sits outside the stored text of the
other tools (collision scan in the emovoice proof). No behaviour moves for a
line without markup, without CAPS, without an ES roll.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and atomic,
LF only. ON THE HOST.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- 2a. loudness parity -----------------------------------------------------------
    ("near-crest-in",
     'def perf_apply(raw: bytes, vec: dict[str, Any]) -> bytes:\n'
     '    """One clip through its performance vector: tempo, pitch and energy in\n'
     '    ffmpeg, pause lengths in the wave itself."""\n'
     '    try:\n'
     '        import io\n'
     '        import wave\n'
     '        with wave.open(io.BytesIO(raw), "rb") as probe:\n'
     '            rate = probe.getframerate()\n',
     'def perf_apply(raw: bytes, vec: dict[str, Any]) -> bytes:\n'
     '    """One clip through its performance vector: tempo, pitch and energy in\n'
     '    ffmpeg, pause lengths in the wave itself."""\n'
     '    try:\n'
     '        import io\n'
     '        import wave\n'
     '        with wave.open(io.BytesIO(raw), "rb") as probe:\n'
     '            rate = probe.getframerate()\n'
     '        # [es-near] the crest the take arrived with: the leveller caps a clip by\n'
     '        # its PEAK, so a performance that sharpened the peaks would air quieter\n'
     '        # than the plain take - it is handed this crest back at the end\n'
     '        _crest_in = _es_voice.crest_db(raw)\n', 1),
    ("near-crest-hold",
     '    except Exception:\n'
     '        pass\n'
     '    return raw\n'
     '\n'
     '\n'
     'def voice_effect_pick() -> dict[str, float]:\n',
     '        raw = _es_voice.hold_crest(raw, _crest_in)       # [es-near] the plain take\'s loudness\n'
     '    except Exception:\n'
     '        pass\n'
     '    return raw\n'
     '\n'
     '\n'
     'def voice_effect_pick() -> dict[str, float]:\n', 1),

    # --- 2b. which reference made a take --------------------------------------------------
    ("near-ref-for",
     'def voice_ref_path(vid: str) -> Path | None:\n'
     '    if not VOICE_ID_SHAPE.match(vid or ""):\n'
     '        return None\n'
     '    ref = VOICES_DIR / vid / "reference.wav"\n'
     '    return ref if ref.exists() else None\n',
     'def voice_ref_path(vid: str) -> Path | None:\n'
     '    if not VOICE_ID_SHAPE.match(vid or ""):\n'
     '        return None\n'
     '    ref = VOICES_DIR / vid / "reference.wav"\n'
     '    return ref if ref.exists() else None\n'
     '\n'
     '\n'
     'def voice_ref_for(vid: str, engine: str) -> Path | None:\n'
     '    """[es-near] THE reference file `engine` clones library voice `vid` from -\n'
     '    one truth for the synthesis roads and for the take\'s stamp. F5 prefers\n'
     '    a neutral reference_f5.wav cut for it (#816: F5 continues its reference,\n'
     '    and the library one bled its words onto the air); every other engine\n'
     '    the library reference. (The per-emotion banks will choose here.)"""\n'
     '    ref = voice_ref_path(vid)\n'
     '    if ref is not None and engine == "f5":\n'
     '        alt = ref.with_name("reference_f5.wav")\n'
     '        if alt.is_file():\n'
     '            return alt\n'
     '    return ref\n'
     '\n'
     '\n'
     'def voice_ref_variant(vid: str, engine: str) -> str:\n'
     '    """[es-near] voice_ref_for\'s file as a take records it: its stem\n'
     '    ("reference", "reference_f5"), "" when the voice has none."""\n'
     '    ref = voice_ref_for(vid, engine)\n'
     '    return ref.stem if ref is not None else ""\n', 1),
    ("near-f5-ref",
     '    _f5_ref = ref.with_name("reference_f5.wav")\n'
     '    if _f5_ref.is_file():\n'
     '        ref = _f5_ref\n',
     '    ref = voice_ref_for(voice, "f5") or ref                 # [es-near] the one rule, voice_ref_for\n', 1),
    ("near-stamp",
     '    _clip_out = {\n'
     '        "path": f"/media/{key}",\n',
     '    # [es-near] which reference baked this take: what the engine performed\n'
     '    # natively, beside its speed and temperature. A shelf road re-performs it\n'
     '    # only while the engine would still clone from the same one.\n'
     '    if isinstance(_es_block, dict):\n'
     '        _es_native = dict(_es_native, ref=voice_ref_variant(voice, engine))\n'
     '    _clip_out = {\n'
     '        "path": f"/media/{key}",\n', 1),
    ("near-shelf-fn",
     'def _pantry_bytes_of(row: dict[str, Any]) -> int:\n',
     'def _es_shelf_ref_ok(clip: dict[str, Any] | None) -> bool:\n'
     '    """[es-near] Whether a shelf take was made from the reference its engine\n'
     '    would clone from now (voice_ref_variant). A take from another one is a\n'
     '    MISS - its performance baseline is not this voice\'s any more (a\n'
     '    reference_f5.wav cut since, or a bank) - and is rendered fresh. A take\n'
     '    whose stamp predates the record is a hit, as it always was."""\n'
     '    try:\n'
     '        baked = _es_voice.baked_ref((clip or {}).get("es"))\n'
     '        if baked is None:\n'
     '            return True\n'
     '        now = voice_ref_variant(str(clip.get("voice") or ""), str(clip.get("engine") or ""))\n'
     '        if baked == now:\n'
     '            return True\n'
     '        pipeline_log("perf", "(es-near) a shelf take was made from %s, the engine now clones from %s"\n'
     '                     " - rendered fresh" % (baked or "no reference", now or "no reference"),\n'
     '                     extra=str(clip.get("path") or "")[:200])\n'
     '        return False\n'
     '    except Exception:  # noqa: BLE001\n'
     '        return True\n'
     '\n'
     '\n'
     'def _pantry_bytes_of(row: dict[str, Any]) -> int:\n', 1),
    ("near-shelf-line",
     '            if _prep_ready:\n'
     '                pipeline_log("lookahead", "off the pantry shelf - no render "\n'
     '                             f"needed - {kind} (#842)")\n',
     '            if _prep_ready and _es_shelf_ref_ok(_prep_ready):   # [es-near] same reference, or a miss\n'
     '                pipeline_log("lookahead", "off the pantry shelf - no render "\n'
     '                             f"needed - {kind} (#842)")\n', 1),
    ("near-shelf-turns",
     '            if _ready:\n'
     '                pipeline_log("lookahead", "off the pantry shelf - no render "\n'
     '                             f"needed - {item[\'who\']} (#886)")\n',
     '            if _ready and _es_shelf_ref_ok(_ready):             # [es-near] same reference, or a miss\n'
     '                pipeline_log("lookahead", "off the pantry shelf - no render "\n'
     '                             f"needed - {item[\'who\']} (#886)")\n', 1),

    # --- 4. the words the engine reads ------------------------------------------------------
    ("near-mouth",
     '    Two of anything stays, as emphasis; the rest is dropped."""\n',
     '    Two of anything stays, as emphasis; the rest is dropped."""\n'
     '    # [es-near] the writer\'s micro-grammar first ([emph]x[/emph] -> CAPS, [beat]\n'
     '    # -> a dash) and an *action* dropped whole - the strip below leaves its word\n'
     '    # to be read out. Unmarked text is untouched (es_voice.unmark).\n'
     '    line = _es_voice.unmark(line)\n', 1),
    ("near-xtts-text",
     '        "text": _xtts_sanitize(text)[:XTTS_MAX_CHARS],\n'
     '        "reference_audio": base64.b64encode(ref.read_bytes()).decode(),\n'
     '        "language": "en",\n'
     '    }\n',
     '        "text": _es_voice.speakable(text, "xtts", _xtts_sanitize)[:XTTS_MAX_CHARS],   # [es-near]\n'
     '        "reference_audio": base64.b64encode(ref.read_bytes()).decode(),\n'
     '        "language": "en",\n'
     '    }\n', 1),
    ("near-clone-text",
     '        "text": _xtts_sanitize(text)[:XTTS_MAX_CHARS],\n'
     '        "reference_audio": base64.b64encode(ref.read_bytes()).decode(),\n'
     '        "language": "en",\n'
     '        "opts": {"speed": max(0.75, min(1.25, rate))},\n'
     '    }\n',
     '        "text": _es_voice.speakable(text, engine, _xtts_sanitize)[:XTTS_MAX_CHARS],   # [es-near]\n'
     '        "reference_audio": base64.b64encode(ref.read_bytes()).decode(),\n'
     '        "language": "en",\n'
     '        "opts": {"speed": max(0.75, min(1.25, rate))},\n'
     '    }\n', 1),
    ("near-f5-text",
     '    clean = _xtts_sanitize(text)\n'
     '    pieces = (sentence_chunks(clean, cap=280, most=24)\n',
     '    clean = _es_voice.speakable(text, "f5", _xtts_sanitize)   # [es-near] F5 never sees a CAPS word\n'
     '    pieces = (sentence_chunks(clean, cap=280, most=24)\n', 1),
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
