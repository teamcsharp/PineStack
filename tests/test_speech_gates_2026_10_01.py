"""[speech-gates] every gate on the station's speech, editable: the registry,
its store, and that every target it names is real."""
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import h3_speak  # noqa: E402
import speech_gates as sg  # noqa: E402

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")


def fake_app():
    return {"NOREPEAT_HOURS": 24.0, "NOREPEAT": types.SimpleNamespace(min_words=4), "RERUN_JACCARD": 0.62,
            "RERUN_CONTAIN": 0.85, "BLOCK_RATE_CAP": 0.35, "PHRASE_ACROSS_LINES": 12, "AD_REPEAT_JACCARD": 0.5,
            "AD_REPEAT_CONTAIN": 0.7, "CALL_NOVELTY_MAX_SIMILARITY": 0.48, "ENGLISH_DIACRITIC_MAX": 0.04}


class Registry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "speech_gates.json"
        sg._STATE.update(values={}, rules_off={}, boot={}, at=0.0)
        h3_speak.OFF.clear()
        self.saved = (h3_speak.MIN_WORDS, h3_speak.MAX_WORDS)

    def tearDown(self):
        h3_speak.MIN_WORDS, h3_speak.MAX_WORDS = self.saved
        h3_speak.OFF.clear()
        sg._STATE.update(values={}, rules_off={}, boot={}, at=0.0, path=None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_every_target_is_real(self):
        import reair_gate  # noqa: F401
        import system3  # noqa: F401
        missed = sg.apply(fake_app())
        self.assertEqual(missed, {})
        for g in sg.GATES:
            for p in g["params"]:
                head, *rest = p[7].split(".")
                if head == "app":
                    self.assertRegex(APP_TEXT, r"(?m)^%s = " % re.escape(rest[0]), p[7])
                self.assertLessEqual(p[5], p[4], p)
                self.assertLessEqual(p[4], p[6], p)

    def test_a_change_is_live_kept_and_reset(self):
        ns = fake_app()
        sg.load(self.path)
        sg.apply(ns)
        view = sg.change(ns, {"gate": "h3_sentence", "key": "min_words", "value": 2})
        self.assertEqual(h3_speak.MIN_WORDS, 2)
        self.assertEqual(h3_speak.speech_why("Buy it today!"), "", "a 3-word punchline passes at 2")
        p = next(x for x in view["gates"][0]["params"] if x["key"] == "min_words")
        self.assertEqual((p["value"], p["default"], p["changed"]), (2, 4, True))
        sg.change(ns, {"gate": "norepeat", "key": "hours", "value": 500})
        self.assertEqual(ns["NOREPEAT_HOURS"], 168.0, "clamped to the safe range")
        sg.change(ns, {"gate": "norepeat", "key": "min_words", "value": 6})
        self.assertEqual(ns["NOREPEAT"].min_words, 6)
        # kept: a restart reads it back
        sg._STATE.update(values={}, rules_off={})
        sg.load(self.path)
        ns2 = fake_app()
        sg.apply(ns2)
        self.assertEqual(ns2["NOREPEAT_HOURS"], 168.0)
        sg.change(ns2, {"gate": "norepeat", "reset": True})
        self.assertEqual(ns2["NOREPEAT_HOURS"], 24.0, "the station's own value back")

    def test_a_rule_switched_off_lets_such_lines_through(self):
        ns = fake_app()
        sg.load(self.path)
        sg.apply(ns)
        self.assertIn("speaker label", h3_speak.speech_why("Ash: We never sleep at this station."))
        sg.change(ns, {"gate": "h3_sentence", "rule": "speaker", "on": False})
        self.assertEqual(h3_speak.speech_why("Ash: We never sleep at this station."), "")
        self.assertIn("speaker", h3_speak.OFF)
        self.assertIn("an unfilled placeholder", h3_speak.sentence_why("We play {mxtape} tonight."),
                      "an unfilled slot is always refused")
        sg.change(ns, {"gate": "h3_sentence", "rule": "speaker", "on": True})
        self.assertNotIn("speaker", h3_speak.OFF)
        with self.assertRaises(KeyError):
            sg.change(ns, {"gate": "h3_sentence", "rule": "nope", "on": False})
        with self.assertRaises(KeyError):
            sg.change(ns, {"gate": "nope", "key": "x", "value": 1})

    def test_an_env_value_is_the_station_s_own(self):
        ns = fake_app()
        ns["NOREPEAT_HOURS"] = 12.0           # NOREPEAT_HOURS=12 in the environment
        sg.load(self.path)
        sg.apply(ns)
        self.assertEqual(ns["NOREPEAT_HOURS"], 12.0, "apply never overwrites what nobody changed")
        g = next(x for x in sg.view(ns)["gates"] if x["id"] == "norepeat")
        self.assertEqual(g["params"][0]["default"], 12.0)


class Wiring(unittest.TestCase):
    def test_wired(self):
        for bit in ('@app.get("/api/speech-gates")', '@app.post("/api/speech-gates")',
                    "_speech_gates.apply(globals())", "overlap / union >= RERUN_JACCARD",
                    "overlap / small >= RERUN_CONTAIN", "> ENGLISH_DIACRITIC_MAX:"):
            self.assertIn(bit, APP_TEXT)
        html = (ROOT / "desktop" / "renderer" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="./speech-gates.js"', html)
        self.assertIn('href="./speech-gates.css"', html)
        kt = (ROOT / "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt").read_text(encoding="utf-8")
        self.assertIn('"speech-gates.js"', kt)
        self.assertIn('"speech-gates.css"', kt)
        for name in ("speech-gates.js", "speech-gates.css", "script-page.js"):
            self.assertEqual((ROOT / "desktop/renderer" / name).read_text(encoding="utf-8"),
                             (ROOT / "app/src/main/assets/pine-views" / name).read_text(encoding="utf-8"), name)
        self.assertIn("root.PineSpeechGates.open()", (ROOT / "desktop/renderer/script-page.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
