"""[line-roll] the speakbox rolls through the document's lines.

"It should be subjected to the roulette where it rolls through the documents
and then it rolls through the lines." The start and every following line of a
swath are System 3 draws over the lines themselves; order never runs backwards.
"""
import unittest
from unittest import mock

import app

POOL = ["Line number %d says something whole." % i for i in range(30)]


class LineRoll(unittest.TestCase):

    def test_every_line_is_a_roll_over_lines(self):
        seen = []

        def pick(key, labels, weights, label="", media=None):
            seen.append((key, list(labels)))
            return 0
        with mock.patch.object(app, "s3_weighted", side_effect=pick):
            got = app.speakbox_swath_lines(POOL, most=5, cap=5000)
        self.assertEqual(len(got), 5)
        self.assertEqual(seen[0][0], "speakbox.swath_start")
        self.assertIn(POOL[0][:140], seen[0][1])        # the rolodex shows the words
        self.assertTrue(all(k == "speakbox.swath_line" for k, _ in seen[1:]))
        self.assertEqual(len(seen), 5)

    def test_order_only_runs_forward(self):
        for _ in range(40):
            got = app.speakbox_swath_lines(POOL, most=8, cap=5000)
            at = [POOL.index(x) for x in got]
            self.assertEqual(at, sorted(at))
            self.assertEqual(len(set(at)), len(at))

    def test_the_cap_still_bounds_the_swath(self):
        got = app.speakbox_swath_lines(POOL, most=9, cap=80)
        self.assertLessEqual(len(" ".join(got)), 80 + len(POOL[0]))

    def test_a_skip_can_happen(self):
        with mock.patch.object(app, "s3_weighted", side_effect=lambda k, l, w, label="", media=None: len(l) - 1):
            got = app.speakbox_swath_lines(POOL, most=3, cap=5000)
        at = [POOL.index(x) for x in got]
        self.assertGreater(at[1] - at[0], 1)


if __name__ == "__main__":
    unittest.main()
