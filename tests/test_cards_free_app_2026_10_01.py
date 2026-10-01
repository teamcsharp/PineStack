"""[cards-free] the turn-by-turn road pauses at the operator's reply gap and nothing else."""
import tempfile
import unittest
from pathlib import Path

import app
import reply_gap as rg


class TurnPause(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rg.use_path(Path(self.tmp.name) / "g.json")

    def tearDown(self):
        rg.use_path(None)
        self.tmp.cleanup()

    def test_instant_is_rapid_fire(self):
        rg.save({"gap": 0, "roll": False})
        for _ in range(20):
            self.assertEqual(app.reply_pause_s(None, "dj", "a line"), 0.0)

    def test_a_set_gap_is_exactly_that(self):
        rg.save({"gap": 2.5, "roll": False})
        self.assertEqual(app.reply_pause_s(None, "dj", "a line"), 2.5)

    def test_a_rolled_gap_stays_inside_the_range(self):
        rg.save({"gap": 0.5, "range": 1.5, "roll": True})
        for _ in range(20):
            self.assertTrue(0.5 <= app.reply_pause_s(None, "dj", "a line") <= 1.5)

    def test_the_monologue_beat_and_jitter_are_gone_from_the_turn_road(self):
        import inspect
        src = inspect.getsource(app._speak_turns_floorless)
        self.assertNotIn("random.uniform(1.05, 1.7)", src)
        self.assertIn("reply_pause_s(ready_meta", src)

    def test_the_page_player_starts_an_instant_reply_on_the_last_words(self):
        page = app.RADIO_PAGE_HTML if hasattr(app, "RADIO_PAGE_HTML") else ""
        src = open(app.__file__, encoding="utf-8").read()
        self.assertEqual(src.count("if (s <= 0) return pineReplyGapEndAt;"), 2)


if __name__ == "__main__":
    unittest.main()
