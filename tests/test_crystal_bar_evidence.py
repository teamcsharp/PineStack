"""Rhyme evidence survives spoken cleanup without granting a whole tint pass.

The fixed gallery pair is the real retained benchmark trial
3a4bf5b664a44dac956c38789dfe3c89 (review event 3333). No models are called.
"""
import unittest
from unittest import mock

import app


class CrystalBarEvidenceTests(unittest.TestCase):
    SOURCE = (
        "Fever dream? No, it’s more than a dream; it’s a visual scream about "
        "overabundance and the desperate need for something tangible when "
        "everything else is dissolving into noise. It should have been called "
        "primal hunger made visible, showing the sheer weight of instinct "
        "crushing any sense of order."
    )
    RAW = (
        "Fever dream? No, more than a dream—a visual scream / "
        "About overabundance and a desperate need for something tangible in the noise stream / "
        "Everything else dissolving, should've been called primal hunger made visible / "
        "Showing sheer weight of instinct crushing any sense of order, making it indivisible."
    )
    CLEAN = (
        "Fever dream? No, more than a dream—a visual scream; "
        "About overabundance and a desperate need for something tangible in the noise stream; "
        "Everything else dissolving, should've been called primal hunger made visible; "
        "Showing sheer weight of instinct crushing any sense of order, making it indivisible."
    )
    PROSE = (
        "The invoice arrived? I checked the sender, reviewed the account balance, "
        "and put it in the drawer. The kettle boiled, so I poured a cup of tea.",
        "All set? The blue box belongs on the shelf, while the green bag stays beside the door. "
        "Tomorrow morning, bring the keys.",
        "Ready? Please bring paper, pencils, and a ruler. The classroom opens tomorrow morning.",
        "Hello, this is Maxine Brown, calling from a car behind the store with rain on the roof.",
        "When you saw the sliding magnets, what did you do next, and what shifted after that?",
        "The station needs a copper plate before midnight. That apparatus hums beside the tall window.",
    )

    def test_actual_gallery_bar_pairs_survive_comma_cleanup_after_the_opening_question(self):
        self.assertEqual(app._tint_out_clean(self.RAW), self.CLEAN)
        self.assertNotIn("/", self.CLEAN)
        original = app.rap_rhyme_evidence(self.RAW)
        spoken = app.rap_rhyme_evidence(self.CLEAN)
        self.assertTrue(original["ok"], original)
        self.assertTrue(spoken["ok"], spoken)
        self.assertEqual(spoken["end"], original["end"])
        self.assertIn(("scream", "stream"), [tuple(pair) for pair in spoken["end"]])
        self.assertIn(("visible", "indivisible"), [tuple(pair) for pair in spoken["end"]])

    def test_short_comma_fragments_merge_without_losing_words_or_the_final_rhyme(self):
        bars = app._rap_bars(self.CLEAN)
        self.assertEqual(app._rap_words(" ".join(bars)), app._rap_words(self.CLEAN))
        self.assertEqual([app._rap_end(bar) for bar in bars],
                         ["dream", "scream", "stream", "visible", "indivisible"])
        self.assertTrue(bars[1].startswith("No, more"))
        self.assertTrue(bars[3].startswith("Everything else dissolving, should've"))
        self.assertTrue(bars[-1].endswith("order, making it indivisible."))

    def test_comma_recovery_is_not_disabled_by_other_sentence_punctuation(self):
        for ending in ("?", "!", ".", ";", ":"):
            with self.subTest(ending=ending):
                text = self.CLEAN.replace("Fever dream?", "Fever dream" + ending, 1)
                report = app.rap_rhyme_evidence(text)
                self.assertTrue(report["ok"], report)
                self.assertEqual(app._rap_words(" ".join(app._rap_bars(text))), app._rap_words(text))

    def test_explicit_short_bars_keep_their_boundaries_and_order(self):
        expected = ["Is it clear?", "Stay here", "Draw near"]
        for separator in (" / ", "\n"):
            with self.subTest(separator=separator):
                self.assertEqual(app._rap_bars(separator.join(expected)), expected)

    def test_short_lists_do_not_create_discarded_or_standalone_rhyme_fragments(self):
        text = self.PROSE[2]
        bars = app._rap_bars(text)
        self.assertEqual(app._rap_words(" ".join(bars)), app._rap_words(text))
        self.assertIn("Please bring paper, pencils, and a ruler.", bars)
        self.assertNotIn("pencils", bars)
        self.assertFalse(app.rap_rhyme_evidence(text)["ok"])

    def test_ordinary_unrhymed_prose_still_fails_with_sentences_and_commas(self):
        for text in self.PROSE:
            with self.subTest(text=text):
                report = app.rap_rhyme_evidence(text)
                self.assertFalse(report["ok"], report)

    def test_rhyme_repair_does_not_waive_the_actual_candidate_transformation_failure(self):
        token = app._REJECTION_LAB_PREVIEW.set(True)
        try:
            with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
                report = app.tint_evaluate(self.SOURCE, self.CLEAN, [], force=.88, strict=False)
        finally:
            app._REJECTION_LAB_PREVIEW.reset(token)
        self.assertTrue(report["rhyme"]["rap"]["ok"])
        self.assertNotIn("no rhyme evidence - the bar does not land a rhyme", report["machine_faults"])
        self.assertIn("rhetoric was not materially transformed", report["machine_faults"])
        self.assertFalse(report["machine_ok"])
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
