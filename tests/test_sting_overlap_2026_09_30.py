"""[reply-gap:sting-overlap] "During the play of an MP4 tag ... is allowed to play
the roulette and RNG buildup of the next tab if it's a conversation tab in order
to give it more time." A dialogue card's buildup runs inside the sting the air
ends on; after a DJ line it stays in full."""
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import reply_gap as rg  # noqa: E402


def _air(prev: dict, secs: float, gap: float = 1.0) -> float:
    rg.save({"gap": gap, "range": gap, "roll": False})
    until = time.time() + 30.0
    rg._BOOKED.update({"until": 0.0, "tail": 0.0, "sting": 0.0, "from": 0.0})
    prev = dict(prev, seconds=secs, tail_s=0.0)
    rg.booked(prev, until)
    return until


class StingOverlap(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        rg.use_path(Path(self.tmp.name) / "reply_gap.json")

    def tearDown(self):
        rg.use_path(None)
        self.tmp.cleanup()

    def door(self, clip, until):
        return rg.door(clip, until, time.time(), tail_of=lambda c: 0.0,
                       rng=random.Random(1), build_of=lambda c: 3304)

    def test_a_line_after_a_long_sting_builds_during_it(self):
        until = _air({"who": "board", "url": "/sfx/abc", "sting": True}, 6.0)
        line = {"who": "dj", "text": "Oh, come ON!", "broadcast_ms": 0, "url": "/media/line.wav"}
        start = self.door(line, until)
        g = line["gap_before"]
        self.assertEqual(g["overlap_build_ms"], 3304)
        self.assertAlmostEqual(start, until + 1.0, delta=0.05)     # only the pause after the sting

    def test_a_short_sting_hides_only_its_own_length(self):
        until = _air({"who": "board", "url": "/sfx/abc", "sting": True}, 2.0)
        line = {"who": "cohost", "text": "Wait, what?", "broadcast_ms": 0, "url": "/media/line.wav"}
        start = self.door(line, until)
        self.assertEqual(line["gap_before"]["overlap_build_ms"], 2000)
        self.assertAlmostEqual(start, until + 1.0 + 1.304, delta=0.05)

    def test_a_line_after_a_line_keeps_its_whole_buildup(self):
        until = _air({"who": "dj", "text": "First."}, 4.0)
        line = {"who": "cohost", "text": "Second.", "broadcast_ms": 0, "url": "/media/line.wav"}
        start = self.door(line, until)
        self.assertEqual(line["gap_before"]["overlap_build_ms"], 0)
        self.assertAlmostEqual(start, until + 1.0 + 3.304, delta=0.05)

    def test_a_sting_after_a_sting_does_not_overlap(self):
        until = _air({"who": "board", "url": "/sfx/abc", "sting": True}, 6.0)
        sting = {"who": "board", "url": "/sfx/def", "sting": True, "text": "a sting", "broadcast_ms": 0}
        self.door(sting, until)
        self.assertEqual((sting.get("gap_before") or {}).get("overlap_build_ms", 0), 0)


class ThePage(unittest.TestCase):
    def test_both_players_announce_early_and_subtract_the_overlap(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("function pineReplyGapBuildAhead(clip, el, queue)"), 2)
        self.assertEqual(src.count("pineReplyGapBuild(clip) - pineReplyGapOverlap(clip)"), 2)
        self.assertEqual(src.count("rolled: !early && !!(g && g.rolled)"), 2)
        view = (ROOT / "desktop/renderer/script-page.js").read_text(encoding="utf-8")
        self.assertIn("if (d.early) return;", view)
        self.assertIn("mvUpcoming.early ||", view)


if __name__ == "__main__":
    unittest.main()
