"""#1064 (reading the LCD): a hard DOOM bar keeps a fifth of the content
words, a speaker label is not part of a bar, and no budget under the hold."""
import unittest
from unittest import mock

import app


class HardBarTests(unittest.TestCase):
    def test_a_hard_bar_keeps_a_fifth_of_the_content_words(self):
        source = ("You wouldn't sully your hands, but you'll damn us to a black hole for "
                  "eternity, because no matter how much you try you cannot make it happen.")
        bar = ("You yank the plug / tug the rug / you die in a shrug / do it yourself! / "
               "Your palms too pristine for the grime but you'll consign us to a black hole / "
               "no matter how you try, the trick won't fly.")
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            hard = app.tint_evaluate(source, bar, [], force=0.88, strict=False)
            soft = app.tint_evaluate(source, bar, [], force=0.3, strict=False)
            garbage = app.tint_evaluate(source, "MF DOOM and I am Mister Fantastik on my grizzly, feds try to creep me.",
                                        [], force=0.88, strict=False)
        self.assertTrue(hard["ok"], hard["faults"])
        self.assertGreaterEqual(hard["semantic"]["anchor_recall"], 0.2)
        self.assertFalse(soft["semantic"]["ok"])
        self.assertFalse(garbage["semantic"]["ok"])

    def test_a_speaker_label_is_stripped_from_a_bar(self):
        self.assertEqual(app._tint_out_clean("HOST: Gather 'round suckas / got a piece here"),
                         "Gather 'round suckas; got a piece here")
        self.assertEqual(app._tint_out_clean("Skip: the bins gone"), "the bins gone")
        self.assertEqual(app._tint_out_clean("Warning: the bins gone"), "Warning: the bins gone")

    def test_no_tint_budget_under_the_hold(self):
        with (mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "tint_budget_left", return_value=0.0),
              mock.patch.object(app, "tint_budget", return_value=100.0)):
            self.assertEqual(app.tint_pressure(), "")
        with (mock.patch.object(app, "crystal_tint_holds", return_value=False),
              mock.patch.object(app, "tint_budget_left", return_value=0.0),
              mock.patch.object(app, "tint_budget", return_value=100.0)):
            self.assertIn("spent its", app.tint_pressure())


if __name__ == "__main__":
    unittest.main()
