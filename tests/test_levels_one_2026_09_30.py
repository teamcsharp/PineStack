"""[levels-one] the one station-wide set of levels: seeding, writes, adoption
(the quieter wins - a merge never raises a level), clamps."""
import tempfile
import unittest
from pathlib import Path

import levels


class LevelsOne(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "levels.json"
        levels._MEMO.update({"at": 0.0, "got": None, "path": ""})

    def tearDown(self):
        self.dir.cleanup()

    def test_unseeded_is_none(self):
        self.assertIsNone(levels.state(self.path)["levels"])

    def test_first_surface_seeds(self):
        got = levels.adopt(self.path, {"music": 0.0875, "voice": 1.04}, "PineTab")
        self.assertTrue(got["seeded"])
        self.assertEqual(got["levels"]["music"], 0.0875)
        self.assertEqual(got["levels"]["master"], 1.0)
        self.assertEqual(got["rev"], 1)

    def test_a_later_surface_only_ever_lowers(self):
        levels.adopt(self.path, {"music": 0.3, "voice": 1.0, "master": 1.0}, "PineTab")
        got = levels.adopt(self.path, {"music": 0.5, "voice": 0.6, "master": 0.35}, "desk")
        self.assertEqual(got["lowered"], ["voice", "master"])
        self.assertEqual(got["levels"]["music"], 0.3)       # never raised to 0.5
        self.assertEqual(got["levels"]["voice"], 0.6)
        self.assertEqual(got["levels"]["master"], 0.35)

    def test_adopt_with_nothing_quieter_changes_nothing(self):
        levels.adopt(self.path, {"music": 0.3}, "a")
        rev = levels.state(self.path)["rev"]
        got = levels.adopt(self.path, {"music": 0.9}, "b")
        self.assertEqual(got["lowered"], [])
        self.assertEqual(got["rev"], rev)

    def test_write_moves_and_counts(self):
        levels.adopt(self.path, {"music": 0.3}, "a")
        got = levels.write(self.path, {"music": 0.45, "pads": 1.4, "bogus": 3}, "slider")
        self.assertEqual(sorted(got["changed"]), ["music", "pads"])
        self.assertEqual(got["levels"]["pads"], 1.4)
        self.assertNotIn("bogus", got["levels"])
        self.assertEqual(got["rev"], 2)
        same = levels.write(self.path, {"music": 0.45}, "slider")
        self.assertEqual(same["changed"], [])
        self.assertEqual(same["rev"], 2)

    def test_clamps(self):
        got = levels.write(self.path, {"master": 1.7, "voice": 9, "sfx": -1}, "x")
        self.assertEqual(got["levels"]["master"], 1.0)
        self.assertEqual(got["levels"]["voice"], 2.0)
        self.assertEqual(got["levels"]["sfx"], 0.0)


if __name__ == "__main__":
    unittest.main()
