"""[num-leak-verb] A person who turns 18 is not reading out a turn number (2026-10-05).

The first two lines are the station's own: they aired on 10-05 as "when he earlier" and "I earlier tomorrow".

Run from the repo root:  python3 -m unittest tests.test_num_leak_verb_2026_10_05
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the repo root, however this file is run

import bookkeeping_numbers as bn  # noqa: E402

BIRTHDAYS = [
    "Hey, just call me back when he turn 18, all right?",
    "Yes, I turn 75 tomorrow.",
    "Like that isn't a Nah, call me back when he turn 18, bro.",
    "She'll turn 30 in May, and he is about to turn 18.",
    "You turn 21 once, so we turn 40 quietly.",
    "My kids turn 5 and 7 this year.",
    "They will turn 65 before the lease is up.",
    "It's my turn to talk now, and I'm taking it.",
    "Take the second turn on the left past the gas station.",
]
NAMES = {
    "Turn 4 is where you lost me.": "earlier is where you lost me.",
    "As I said, turn 3 covers it.": "As I said, earlier covers it.",
    "Go back to the turn 2 point.": "Go back to the earlier point.",
    "That was the whole point of turn 7.": "That was the whole point of earlier.",
    "See turn 12 for the details.": "See earlier for the details.",
    "That's just not right you're ignoring the actual point I made in turn two it's not what you think":
        "That's just not right you're ignoring the actual point I made earlier it's not what you think",
    "Back in turn 3 you said the opposite.": "earlier you said the opposite.",
}


class NumLeakVerbTest(unittest.TestCase):
    def test_a_birthday_is_left_exactly_as_it_was_said(self):
        for said in BIRTHDAYS:
            self.assertEqual(bn.spoken_gate(said), (said, []), said)

    def test_a_turn_used_as_a_name_is_still_cut(self):
        for said, want in NAMES.items():
            out, hits = bn.spoken_gate(said)
            self.assertEqual(out, want, said)
            self.assertTrue(hits and hits[0].startswith("turn number"), (said, hits))

    def test_what_is_named_in_the_hit_is_the_turn_alone(self):
        _out, hits = bn.spoken_gate("As I said, turn 3 covers it.")
        self.assertEqual(hits, ["turn number 'turn 3'"])

    def test_both_in_one_line(self):
        out, hits = bn.spoken_gate("Turn 2 was about the day I turn 40.")
        self.assertEqual(out, "earlier was about the day I turn 40.")
        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()
