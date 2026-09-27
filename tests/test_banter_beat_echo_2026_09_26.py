import unittest

import app


class BeatDirectionTests(unittest.TestCase):  # [#1462]
    ROW = {"turn": 5, "seat": "A",
           "work": "refuse the premise of it outright, plainly. Quote back "
                   "the word or claim you are answering."}

    def test_a_turn_that_speaks_its_direction_is_caught(self):
        self.assertTrue(app._beat_speaks_direction(
            "I refuse the premise of it outright, plainly.", self.ROW))

    def test_a_real_answer_passes(self):
        self.assertFalse(app._beat_speaks_direction(
            "Haunted? It ate my dollar, that is a business model.", self.ROW))

    def test_a_short_generic_direction_never_matches(self):
        self.assertFalse(app._beat_speaks_direction(
            "Opens it, then? Fine.", {"work": "opens"}))


if __name__ == "__main__":
    unittest.main()
