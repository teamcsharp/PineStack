"""Real retained rhyme refusals; no models, recording or review mutations."""
import unittest

import app


class RealRhymeRefusalTests(unittest.TestCase):
    TOUCH = ("Yeah, they try to put a price on whatever they touch, "
             "Just makes it worse, an excessive clutch.")
    KID = ("You want me to explain it like I'm talking to a kid, "
           "Then get corrected by you? A disaster bid, "
           "Setting up total ruin for the whole segment, "
           "Is that how the plot is spent?")

    def test_touch_clutch_uses_actual_vowel_not_ou_spelling(self):
        self.assertTrue(app._rap_slant("touch", "clutch"))
        report = app.rap_rhyme_evidence(self.TOUCH)
        self.assertTrue(report["ok"], report)
        self.assertIn(("touch", "clutch"), report["end"])

    def test_touch_exception_does_not_change_other_ou_words(self):
        self.assertFalse(app._rap_slant("touch", "couch"))
        self.assertFalse(app._rap_slant("touch", "ouch"))
        self.assertTrue(app._rap_slant("couch", "pouch"))
        self.assertTrue(app._rap_slant("sound", "round"))
        self.assertFalse(app._rap_slant("touch", "touch"))

    def test_three_word_landing_keeps_kid_bid_endpoint(self):
        bars = app._rap_bars(self.KID)
        self.assertIn("A disaster bid", bars)
        report = app.rap_rhyme_evidence(self.KID)
        self.assertTrue(report["ok"], report)
        self.assertIn(("kid", "bid"), report["end"])

    def test_short_filler_is_not_a_separate_rhyme_bar(self):
        text = "No, I mean, the gate is open, you know, the copper plate is missing."
        bars = app._rap_bars(text)
        self.assertEqual(bars, ["No, I mean, the gate is open",
                                "you know, the copper plate is missing."])
        self.assertEqual(app._rap_words(" ".join(bars)), app._rap_words(text))

    def test_explicit_bars_and_all_original_words_are_preserved(self):
        explicit = "A disaster bid / I talk to a kid."
        self.assertEqual(app._rap_bars(explicit),
                         ["A disaster bid", "I talk to a kid."])
        self.assertEqual(app._rap_words(" ".join(app._rap_bars(self.KID))),
                         app._rap_words(self.KID))

    def test_shared_suffix_and_repeated_words_remain_insufficient(self):
        for first, second in (("walking", "sleeping"), ("garbage", "back"),
                              ("dramatic", "specific"), ("kid", "kid")):
            with self.subTest(first=first, second=second):
                self.assertFalse(app._rap_slant(first, second))
        self.assertFalse(app.rap_rhyme_evidence(
            "The copper plate is missing. Someone left the window open.")["ok"])


if __name__ == "__main__":
    unittest.main()
