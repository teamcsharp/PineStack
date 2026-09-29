"""[es-near] The emotion engine's near-term wiring (docs: emotts PLAN.md steps 2 + 4).

- Step 2a: a performed take airs at the plain take's loudness - perf_apply hands
  the leveller the crest the take arrived with (es_voice.hold_crest, dead code
  until now). Measured here on a synthetic voiced take through the station's own
  perf_apply and _level_rms (ffmpeg via imageio-ffmpeg, as in the container).
- Step 2b: a shelf take records which reference made it; a take from another
  reference than its engine would clone from now is a miss.
- Step 4: what each engine is handed - markup resolved and dropped, XTTS never an
  ellipsis or an em-dash and at most three CAPS words, F5 never a CAPS word
  (acronyms excepted), long XTTS sentences cut at a clause - and a line with no
  markup and no CAPS is exactly what the station handed the engine before.

app.py is read, never imported (tools/es_near_patch.py and
tools/edit_es_voice_near.py must be applied). No test touches the station's
data dir; nothing renders."""
import io
import math
import re
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

import es_voice

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

ROOT = Path(__file__).resolve().parents[1]


def _app_text():
    return (ROOT / "app.py").read_text(encoding="utf-8")


def _top_level(text, head):
    i = text.find("\n" + head) + 1
    if not i:
        raise AssertionError("app.py has no top-level %r (are the tools applied?)" % head)
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


def _app(*heads, **ns):
    text = _app_text()
    space: dict[str, Any] = {"re": re, "Any": Any, "Path": Path, "_es_voice": es_voice, **ns}
    exec(compile("".join(_top_level(text, h) for h in heads), "app.py[es-near]", "exec"), space)
    return space


SANITIZE = None


def sanitize(text):
    global SANITIZE
    if SANITIZE is None:
        SANITIZE = _app("def _xtts_sanitize(")["_xtts_sanitize"]
    return SANITIZE(text)


# lines of the kind the writer returns (the markup is what models emit unasked)
MARKED = [
    "*laughs* That is the best news I've heard all week.",
    "Well [beat] I told him [emph]never[/emph] again... and that was it — done.",
    "Oh come ON, (sighs) you cannot be serious about this, Skip.",
    "[Dill, deadpan] The raccoon has a lawyer now.",
    "I mean *really*? A van full of raccoons? <laugh> Unbelievable.",
    "*clears throat* Right. Moving on, folks – the weather.",
    "{pause} It is what it is.",
]
PLAIN = [
    "The raccoon van is back on Fifth Street, and nobody knows who is driving it.",
    "So what you're telling me is the mayor owns a boat.",
    "Honestly? I'd have done the same thing.",
    "It's quarter past nine on the station, stay with us.",
    "The DJ on the FM side said the NASA launch slipped again.",
]


class NormalizerTests(unittest.TestCase):
    def test_no_engine_ever_reads_markup_aloud(self):
        for line in MARKED:
            for engine in ("xtts", "f5"):
                said = es_voice.speakable(line, engine, sanitize)
                self.assertNotRegex(said, r"[\[\]{}<>*_]", (line, engine))
                self.assertNotRegex(said.lower(), r"\b(laughs?|sighs|beat|emph|clears throat|deadpan|pause)\b",
                                    (line, engine, said))

    def test_xtts_never_sees_an_ellipsis_or_a_dash_and_at_most_three_caps(self):
        shout = "THIS IS THE GREATEST DAY OF MY WHOLE LIFE AND I'M NOT KIDDING ANYBODY"
        for line in MARKED + PLAIN + [shout]:
            said = es_voice.speakable(line, "xtts", sanitize)
            self.assertNotRegex(said, "[…—–]|\\.\\.", line)
            caps = [w for w in re.findall(r"\b[A-Z][A-Z']*[A-Z]\b", said) if w not in es_voice.ACRONYMS]
            self.assertLessEqual(len(caps), es_voice.CAPS_EMPHASIS_MAX, said)
        said = es_voice.speakable(shout, "xtts", sanitize)
        self.assertEqual(said, "This is the GREATEST day of my whole life and I'm not KIDDING ANYBODY.")

    def test_f5_never_sees_a_caps_word_but_an_acronym_is_spelled(self):
        said = es_voice.speakable("WOW. The DJ said NO WAY, and I'M done. *Really* (laughs)", "f5", sanitize)
        self.assertEqual(said, "Wow. The DJ said no way, and I'm done. Really.")
        for line in MARKED + PLAIN:
            said = es_voice.speakable(line, "f5", sanitize)
            self.assertEqual([w for w in re.findall(r"\b[A-Z][A-Z']*[A-Z]\b", said) if w not in es_voice.ACRONYMS],
                             [], said)

    def test_the_micro_grammar(self):
        self.assertEqual(es_voice.unmark("I told him [emph]never[/emph] again."), "I told him NEVER again.")
        self.assertEqual(es_voice.unmark("Well [beat] no."), "Well — no.")
        self.assertEqual(es_voice.unmark("[beat] Well, no. [pause]"), "Well, no.", "a beat at either end is no beat")
        self.assertEqual(es_voice.unmark("That was *huge*."), "That was HUGE.")
        self.assertEqual(es_voice.unmark("*shrugs* Fine."), "Fine.")
        self.assertEqual(es_voice.unmark("It was *a whole thing* honestly."), "It was a whole thing honestly.")
        self.assertEqual(es_voice.speakable("Well [beat] no.", "xtts", sanitize), "Well, no.")
        self.assertEqual(es_voice.speakable("I said [emph]no[/emph].", "f5", sanitize), "I said no.")
        # a parenthesis that is speech stays speech (at the engine; the mouth's own strip is unchanged)
        self.assertIn("(and he meant it)", es_voice.speakable("He said wow (and he meant it).", "xtts", sanitize))

    def test_an_unmarked_line_is_what_the_station_sent_before(self):
        for line in PLAIN + ["Plain words, nothing else.", "", "snake_case stays"]:
            self.assertEqual(es_voice.unmark(line), line)
            for engine in ("xtts", "f5"):
                self.assertEqual(es_voice.speakable(line, engine, sanitize), sanitize(line), (line, engine))
        self.assertEqual(es_voice.speakable("Some text [x]", "kokoro"), "Some text")

    def test_a_long_xtts_sentence_is_cut_at_a_clause(self):
        long = ("We drove out past the old quarry, where the road turns to gravel and the signal drops, "
                "and there it was, the van, parked sideways across both lanes with its hazards on, "
                "and not one raccoon in sight, which honestly worried me more than if the thing had been full.")
        said = es_voice.speakable(long, "xtts", sanitize)
        self.assertTrue(all(len(s) <= es_voice.XTTS_SENTENCE_MAX for s in re.split(r"(?<=[.!?])\s+", said)), said)
        self.assertEqual(re.sub(r"[^a-z]", "", said.lower()), re.sub(r"[^a-z]", "", long.lower()), "no word lost")
        self.assertEqual(es_voice.speakable(long, "f5", sanitize), sanitize(long), "F5 pieces are cut upstream")

    def test_failure_is_the_flattener_as_before(self):
        def boom(_t):
            raise ValueError("x")
        self.assertEqual(es_voice.caps_for(None, "xtts"), "")
        self.assertEqual(es_voice.unmark(None), "")
        with self.assertRaises(ValueError):
            es_voice.speakable("hi", "xtts", boom)


class WiringTests(unittest.TestCase):
    def test_the_roads_are_wired(self):
        text = _app_text()
        perf = _top_level(text, "def perf_apply(")
        self.assertLess(perf.index("_crest_in = _es_voice.crest_db(raw)"), perf.index("_es_voice.intonate("))
        self.assertLess(perf.index("perf_pause_stretch(raw, scale)"), perf.index("_es_voice.hold_crest(raw, _crest_in)"))
        self.assertIn('_es_voice.speakable(text, "xtts", _xtts_sanitize)', _top_level(text, "async def _xtts_synthesize("))
        f5 = _top_level(text, "async def _f5_synthesize(")
        self.assertIn('_es_voice.speakable(text, "f5", _xtts_sanitize)', f5)
        self.assertIn('voice_ref_for(voice, "f5")', f5)
        self.assertIn("_es_voice.speakable(text, engine, _xtts_sanitize)", _top_level(text, "async def _clone_synthesize("))
        mouth = _top_level(text, "def spoken_text(")
        self.assertLess(mouth.index("line = _es_voice.unmark(line)"), mouth.index("SPOKEN_NOISE.sub("))
        self.assertIn("_es_native = dict(_es_native, ref=voice_ref_variant(voice, engine))", text)
        self.assertEqual(text.count("_es_shelf_ref_ok(_prep_ready)"), 1)
        self.assertEqual(text.count("_es_shelf_ref_ok(_ready)"), 1)


def _voiced_take(seconds=2.4, sr=24000, f0=118.0):
    """A synthetic voice: a glottal-like pulse train through two formant
    resonances, syllable envelopes, a 300 ms pause in the middle."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    f = f0 * (1 + 0.06 * np.sin(2 * np.pi * 1.3 * t))
    phase = np.cumsum(f) / sr
    src = (np.sin(2 * np.pi * phase) + 0.5 * np.sin(4 * np.pi * phase) + 0.3 * np.sin(6 * np.pi * phase)
           + 0.2 * np.sin(10 * np.pi * phase) + 0.15 * np.sin(16 * np.pi * phase))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t) ** 2
    env[int(1.0 * sr):int(1.3 * sr)] = 0.0
    x = 0.25 * src * env
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(np.round(x * 32767), -32768, 32767).astype("<i2").tobytes())
    return out.getvalue()


def _rms_peak(raw):
    x, _p = es_voice._read(raw)
    return float(np.sqrt(np.mean(x * x))), float(np.max(np.abs(x)))


@unittest.skipIf(np is None, "numpy")
class LevelTests(unittest.TestCase):
    """Step 2a: after the station's leveller a performed take is as loud as the plain take."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app("def _pitch_chain(", "def _ffmpeg_af(", "def perf_dsp_chain(", "def perf_pause_stretch(",
                       "def perf_apply(", "def _level_rms(")

    def test_a_brighter_higher_take_is_not_levelled_quieter(self):
        take = _voiced_take()
        plain_rms, _ = _rms_peak(self.app["_level_rms"](take, 5200))
        for vec in ({"pace": 1.0, "range": 1.30, "energy": 0.60, "pause_scale": 1.0, "es": {"pitch": 0.8}},
                    {"pace": 1.0, "range": 1.35, "energy": 0.40, "pause_scale": 1.0, "es": {"pitch": 1.2}}):
            performed = self.app["perf_apply"](take, dict(vec))
            self.assertNotEqual(performed, take, "the performance ran")
            self.assertLessEqual(es_voice.crest_db(performed), es_voice.crest_db(take) + 0.25)
            rms, peak = _rms_peak(self.app["_level_rms"](performed, 5200))
            self.assertLessEqual(peak, 0.951)
            self.assertAlmostEqual(20 * math.log10(rms / plain_rms), 0.0, delta=0.3)

    def test_nothing_to_perform_is_untouched(self):
        take = _voiced_take()
        self.assertEqual(self.app["perf_apply"](take, {}), take)


class ShelfRefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.voices = Path(self.tmp.name)
        self.logs = []
        self.app = _app("def voice_ref_path(", "def voice_ref_for(", "def voice_ref_variant(", "def _es_shelf_ref_ok(",
                        VOICES_DIR=self.voices, VOICE_ID_SHAPE=re.compile(r"^vl_[a-f0-9]{8}\Z"),
                        pipeline_log=lambda *a, **k: self.logs.append(a))
        (self.voices / "vl_0000abcd").mkdir()
        (self.voices / "vl_0000abcd" / "reference.wav").write_bytes(b"x")

    def take(self, engine, stamp):
        return {"voice": "vl_0000abcd", "engine": engine, "path": "/media/t.wav", **({"es": stamp} if stamp is not None else {})}

    def test_the_reference_an_engine_clones_from(self):
        ok, variant = self.app["_es_shelf_ref_ok"], self.app["voice_ref_variant"]
        self.assertEqual(variant("vl_0000abcd", "f5"), "reference")
        self.assertEqual(variant("vl_0000abcd", "xtts"), "reference")
        self.assertEqual(variant("en_US-amy", "piper"), "")
        self.assertTrue(ok(self.take("f5", None)), "no stamp: a hit, as always")
        self.assertTrue(ok(self.take("f5", {"tempo": 1.05})), "a stamp from before the record: a hit")
        self.assertTrue(ok(self.take("f5", {"native": {"ref": "reference"}})))
        (self.voices / "vl_0000abcd" / "reference_f5.wav").write_bytes(b"y")     # an F5-safe cut, since
        self.assertEqual(variant("vl_0000abcd", "f5"), "reference_f5")
        self.assertFalse(ok(self.take("f5", {"native": {"ref": "reference"}})), "baked from the old one: a miss")
        self.assertTrue(ok(self.take("xtts", {"native": {"ref": "reference"}})), "XTTS keeps the library one")
        self.assertTrue(ok(self.take("f5", {"ref": "reference_f5"})))
        self.assertEqual(len(self.logs), 1)
        self.assertIsNone(es_voice.baked_ref({"tempo": 1.0}))
        self.assertEqual(es_voice.baked_ref({"ref": "reference_anger", "native": {"ref": "x"}}), "reference_anger")


if __name__ == "__main__":
    unittest.main()
