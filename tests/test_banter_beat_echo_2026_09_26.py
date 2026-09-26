import unittest

import app


class BeatEchoTests(unittest.TestCase):  # [#1462]
    ROW = {"turn": 5, "seat": "A",
           "work": "refuse the premise of it outright, plainly. Quote back "
                   "the word or claim you are answering."}

    def test_a_turn_that_speaks_its_direction_is_named(self):
        why = app._beat_turn_echo(
            "I refuse the premise of it outright, plainly.", self.ROW, [])
        self.assertIn("direction", why)

    def test_a_turn_repeating_the_round_is_named(self):
        said = [("B", "Structure."), ("A", "Pinned by what?")]
        self.assertIn("repeated", app._beat_turn_echo("structure", self.ROW, said))

    def test_a_real_answer_passes(self):
        said = [("B", "The vending machine is haunted.")]
        self.assertEqual(app._beat_turn_echo(
            "Haunted? It ate my dollar, that is a business model.",
            self.ROW, said), "")


if __name__ == "__main__":
    unittest.main()
