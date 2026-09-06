"""#1064: the meaning grade judges meaning, not sentence starts."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class TintMeaningTests(unittest.TestCase):
    def test_a_sentence_start_is_not_a_name_when_the_crystal_knows_the_word(self):
        plain = ('Relax, I was just trying to make you giggle." When you try and say '
                 "something that's true, earnestly from the heart, that's when it lands.")
        bar = ("Tryin' to make you giggle, that's the trick; say a true thing from the "
               "heart, earnest and slick, that's when it lands and sticks.")
        with mock.patch.object(app, "_crystal_vocab",
                               return_value=frozenset({"relax", "when", "giggle"})):
            report = app.tint_evaluate(plain, bar, [], force=0.9)
        self.assertTrue(report["semantic"]["entities"], report["semantic"])
        self.assertTrue(report["ok"], report["faults"])

    def test_a_real_name_at_a_sentence_start_still_binds(self):
        plain = "Mara returned 12 copper plates before midnight."
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset({"relax"})):
            swapped = app.tint_evaluate(
                plain, "Nora returned 12 copper plates before midnight; operation "
                       "meets calibration.", [], force=1.0)
            kept = app.tint_evaluate(
                plain, "Mara brought 12 copper plates back before the midnight bell; "
                       "operation meets calibration.", [], force=1.0)
        self.assertFalse(swapped["semantic"]["entities"])
        self.assertTrue(kept["semantic"]["entities"])

    def test_a_hard_rewrite_may_keep_a_third_of_the_content_words(self):
        plain = "The station needs a copper plate before midnight tonight for the show."
        bar = "Copper plate by midnight or the lights go dark, that's the spark."
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            hard = app.tint_evaluate(plain, bar, [], force=0.9)
            soft = app.tint_evaluate(plain, bar, [], force=0.6)
        self.assertGreaterEqual(hard["semantic"]["anchor_recall"], 0.35)
        self.assertLess(hard["semantic"]["anchor_recall"], 0.5)
        self.assertTrue(hard["semantic"]["ok"])
        self.assertFalse(soft["semantic"]["ok"])
        garbage = app.tint_evaluate(plain, "MF DOOM and I am Mister Fantastik on my grizzly.",
                                    [], force=0.9)
        self.assertFalse(garbage["semantic"]["ok"])

    def test_continuity_falls_back_to_the_plain_pair_as_a_stopgap(self):
        with (mock.patch.object(app, "_CONTINUITY_BANK", {}),
              mock.patch.object(app, "_CONTINUITY_LOADED", [True]),
              mock.patch.object(app, "_CONTINUITY_STATE", {}),
              mock.patch.object(app, "voice_engine_for", return_value="xtts"),
              mock.patch.object(app, "continuity_crystal", return_value="DOOM:doom"),
              tempfile.TemporaryDirectory() as tmp):
            (Path(tmp) / "c.wav").write_bytes(b"x")
            with mock.patch.object(app, "VOICE_MEDIA_DIR", Path(tmp)):
                plain_key = app.continuity_key("dj", "v", "xtts", "Stay with us.")
                app._CONTINUITY_BANK[plain_key] = {
                    "who": "dj", "voice": "v", "engine": "xtts", "text": "Stay with us.",
                    "clip": {"path": "/voice/c.wav", "seconds": 2.0}}
                row = app.continuity_pick("dj", "v", "Stay with us.")
                self.assertIsNotNone(row)
                self.assertTrue(row["stopgap"])
                self.assertIn("stopgap", app._CONTINUITY_STATE)
                rap_key = app.continuity_key("dj", "v", "xtts", "Stay with us.", "DOOM:doom")
                app._CONTINUITY_BANK[rap_key] = {
                    "who": "dj", "voice": "v", "engine": "xtts",
                    "text": "Stay in the mix.", "plain": "Stay with us.", "crystal": "DOOM:doom",
                    "clip": {"path": "/voice/c.wav", "seconds": 2.0}}
                row = app.continuity_pick("dj", "v", "Stay with us.")
                self.assertFalse(row["stopgap"])
                self.assertEqual(row["text"], "Stay in the mix.")


if __name__ == "__main__":
    unittest.main()
