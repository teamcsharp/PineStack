"""[emotion-engine] the emotion engine's window: queue, tasks, audit, the raw
take kept for before/after, resources, and the Voice actors card that shows them."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import emotion_engine as ee  # noqa: E402


class Door(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ee._NS.update({"VOICE_MEDIA_DIR": Path(self.tmp.name), "media_sign": lambda k: "sig-" + k})
        ee._TASKS.clear(); ee._BY_ID.clear(); ee._AUDIT.clear(); ee._RAW_KEYS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_line_waits_then_renders_then_is_shaped(self):
        t = ee.begin("line1", "dj", "xtts", "BenSpapi", "Hello", {"tempo": 1.05, "junk": 9})
        q = ee.queue_rows()
        self.assertEqual((q[0]["place"], q[0]["state"], q[0]["es"]), (1, "queued", {"tempo": 1.05}))
        ee.rendering(t)
        self.assertEqual(ee.queue_rows()[0]["state"], "rendering")
        ee.synthed(t, b"RIFFraw-take", "wav")
        raw = ee._BY_ID[t]["raw"]
        self.assertTrue((Path(self.tmp.name) / raw).read_bytes() == b"RIFFraw-take", "the raw take is kept")
        ee.shaped(t, "final.wav", 37, 2.4)
        s = ee.state()
        task = s["tasks"][0]
        self.assertEqual(task["state"], "done")
        self.assertEqual(task["raw_url"], "/media/%s?t=sig-%s" % (raw, raw))
        self.assertEqual(task["final_url"], "/media/final.wav?t=sig-final.wav")
        self.assertEqual(s["queue"], [])
        self.assertIn("dsp_ms", s["timing"])
        self.assertEqual([a["what"] for a in s["audit"]][:3],
                         ["shaped and stored", "the engine answered", "entered the voice door"])

    def test_raw_takes_are_bounded(self):
        for i in range(ee.RAW_KEPT + 5):
            t = ee.begin("l%d" % i, "dj", "xtts", "v", "x", None)
            ee.synthed(t, b"RIFF", "wav")
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), ee.RAW_KEPT)

    def test_failed_and_lost(self):
        t = ee.begin("l", "dj", "f5", "v", "x", None)
        ee.failed(t, "synthesis failed - boom")
        self.assertEqual(ee._BY_ID[t]["state"], "failed")
        t2 = ee.begin("l2", "dj", "f5", "v", "x", None)
        ee._BY_ID[t2]["at"] -= ee.LOST_S + 1
        ee._lost_sweep(__import__("time").time())
        self.assertEqual(ee._BY_ID[t2]["state"], "lost")


class Wiring(unittest.TestCase):
    def test_the_voice_door_reports_every_step(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        for call in ("_emotion.begin(", "_emotion.rendering(_ee)", "_emotion.synthed(_ee, audio, ext)",
                     "_emotion.shaped(_ee, key,", "_emotion.failed(_ee,", "_emotion.install(app, globals())"):
            self.assertIn(call, src, call)

    def test_the_voice_actors_card_has_the_seven_sub_tabs(self):
        js = (ROOT / "desktop/renderer/voice-actor.js").read_text(encoding="utf-8")
        self.assertIn("'emotion'", js)
        for tab in ("'queue', 'Queue'", "'tasks', 'Tasks'", "'audit', 'Audit log'", "'ab', 'Before/After'",
                    "'prompts', 'Prompts'", "'res', 'Resources'", "'rolls', 'Roulette log'"):
            self.assertIn(tab, js, tab)
        self.assertIn("/api/emotion/state", js)
        kiosk = ROOT / "app/src/main/assets/pine-views/voice-actor.js"
        self.assertEqual(kiosk.read_text(encoding="utf-8"), js, "the kiosk copy is the renderer, byte for byte")


if __name__ == "__main__":
    unittest.main()
