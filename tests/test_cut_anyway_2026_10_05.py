"""[cut-anyway] [speech-idle] Supercuts assemble from what the clips say; the clips are listened to in idle time (2026-10-05).

Run from the repo root:  python3 tests/test_cut_anyway_2026_10_05.py
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def src(name: str) -> str:
    return (ROOT / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


CUSTOM, RENDER, APP = src("sfx_supercut_custom.py"), src("sfx_supercut.py"), src("app.py")


def block(text: str, head: str, stop: str) -> str:
    start = text.index(head)
    return text[start:text.index(stop, start + len(head))]


class DialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ns: dict = {}
        exec(compile(block(CUSTOM, "import difflib", "\ndef recursive(source):"), "dial", "exec"), ns)
        cls.close = staticmethod(ns["heard_close"])
        cls.default = ns["DEFAULT_ACCURACY"]

    def test_exact_words_always_stand(self):
        self.assertTrue(self.close(["pine", "box"], ["pine", "box"], 100.))
        self.assertTrue(self.close(["pine", "box"], ["pine", "box"], 0.))

    def test_at_100_only_exact_words_stand(self):
        self.assertFalse(self.close(["the", "pine", "box", "is"], ["pine", "box"], 100.))
        self.assertFalse(self.close(["pine", "bocks"], ["pine", "box"], 100.))

    def test_below_100_words_heard_inside_the_window_stand(self):
        self.assertTrue(self.close(["the", "pine", "box", "is"], ["pine", "box"], 70.))
        self.assertTrue(self.close(["uh", "station"], ["station"], 99.))

    def test_below_100_a_near_hearing_stands_and_a_different_one_does_not(self):
        self.assertTrue(self.close(["stations"], ["station"], 70.))
        self.assertFalse(self.close(["banana"], ["station"], 70.))
        self.assertFalse(self.close([], ["station"], 10.))          # silence stands for nothing

    def test_the_default_is_not_the_wall(self):
        self.assertLess(self.default, 100.)


class AssemblyTest(unittest.TestCase):
    def test_a_job_with_any_cut_is_assembled_below_100(self):
        visit = block(CUSTOM, "    async def visit(self,ident):", "    async def worker(self):")
        self.assertIn("if row['missing_words'] and (accuracy>=100. or not row['cuts']):", visit)
        self.assertIn("heard_close(tokens(proof['said']),wanted[cursor:cursor+size],accuracy)", visit)
        fallback = visit.index("# [cut-anyway] NO WINDOW WAS HEARD CLEANLY")
        self.assertLess(fallback, visit.index("row['missing_words'].append(word)"))   # the transcript's estimate before a miss
        self.assertIn("'word_cut_verified':False", visit[fallback:])
        self.assertIn("'accuracy':accuracy", visit)

    def test_a_request_carries_the_dial_and_an_old_job_is_not_exact_only(self):
        create = block(CUSTOM, "    def create(self,raw):", "    def retry(self,ident):")
        self.assertIn("raw.get('accuracy'),DEFAULT_ACCURACY", create)
        self.assertIn("cut._number(row.get('accuracy'),DEFAULT_ACCURACY)", CUSTOM)

    def test_the_renderer_honours_the_dial_and_100_is_unchanged(self):
        render = block(RENDER, "def render_source_plan(", "\n    proof = product_evidence(cfg, clips)")
        self.assertIn("exact = _number(custom.get('accuracy'), 100.) >= 100.", render)
        self.assertEqual(render.count("if exact and "), 2)
        self.assertIn("Every custom word cut needs verified trimmed source audio", render)


class IdleListenerTest(unittest.TestCase):
    def test_the_listener_runs_on_its_own_clock(self):
        clock = block(APP, "async def sfx_speech_clock(", "\n@app.get(\"/api/sfx/speech\")")
        self.assertIn("asyncio.to_thread(sfx_speech_bite,", clock)             # never on the event loop
        self.assertIn('j.get("state") == "waiting"', clock)                     # it stands aside for the writers
        self.assertIn("bites % 20 == 0", clock)                                 # the index is told now and then, not every bite
        self.assertIn('radio_worker_start("sfx_speech", sfx_speech_clock)', APP)

    def test_a_pressed_bite_and_the_clock_do_not_overlap(self):
        clock = block(APP, "async def sfx_speech_clock(", "\n@app.get(\"/api/sfx/speech\")")
        self.assertLess(clock.index('if _SFX_SPEECH.get("running"):'), clock.index("asyncio.to_thread(sfx_speech_bite,"))
        self.assertIn('_SFX_SPEECH["running"] = False', clock)


if __name__ == "__main__":
    unittest.main()
