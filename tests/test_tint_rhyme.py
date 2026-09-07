"""#1064: every line rhymes - the rap-aware reading is mandatory under the
meaning grade, and the spoken form carries no bar marks or markdown."""
import unittest
from unittest import mock

import app

BARS = [
    "Pick a gate, spider-man / see how the reward is non-existent / this hero's progress is distant / "
    "the real villain's in the water, metal fingers movin' in a blizzard / targeting Soviets, Americans, "
    "little pricks with the wizard",
    "Tryin' to make you giggle, that's the trick; say a true thing from the heart, earnest and slick, "
    "that's when it lands and sticks.",
    "Black Panther, a chosen fella, who's gonna propel ya to the future? Better grab an umbrella cause "
    "these bogus leaders just lie hella.",
    "Copper plate by midnight or the lights go dark, that's the spark.",
    "Before midnight, the station needs that copper plate; operation meets calibration to settle the wait.",
]
PROSE = [
    "Hello, this is Maxine Brown, calling from a car behind the store with rain on the roof.",
    "When you saw the sliding magnets, what did you do next, and what shifted after that?",
    "The station needs a copper plate before midnight. That apparatus hums beside the tall window.",
    "walking reading cooking",
    "I checked it and noted the time.",
]


class TintRhymeTests(unittest.TestCase):
    def test_real_bars_prove_rhyme_and_prose_does_not(self):
        for bar in BARS:
            self.assertTrue(app.rap_rhyme_evidence(bar)["ok"], bar)
        for line in PROSE:
            self.assertFalse(app.rap_rhyme_evidence(line)["ok"], line)

    def test_shared_endings_are_not_rhyme(self):
        self.assertFalse(app._rap_slant("walking", "cooking"))
        self.assertFalse(app._rap_slant("garbage", "back"))
        self.assertFalse(app._rap_slant("dramatic", "specific"))
        self.assertTrue(app._rap_slant("trick", "sticks"))
        self.assertTrue(app._rap_slant("blizzard", "wizard"))
        self.assertTrue(app._rap_slant("clear", "dear"))

    def test_the_meaning_grade_refuses_a_bar_that_does_not_rhyme(self):
        source = "The station needs a copper plate before midnight."
        paraphrase = "The station requires a copper plate before the midnight hour arrives."
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            report = app.tint_evaluate(source, paraphrase, [], force=0.9, strict=False)
            self.assertFalse(report["ok"])
            self.assertIn("no rhyme evidence - the bar does not land a rhyme", report["faults"])
            self.assertEqual(report["version"], 3)
            good = app.tint_evaluate(source, BARS[4], [], force=0.9, strict=False)
            self.assertTrue(good["ok"], good["faults"])
            self.assertTrue(good["rhyme"]["rap"]["ok"])

    def test_stored_tints_from_the_old_grade_are_not_current(self):
        report = {"coverage": {"met": True, "target": 100, "version": 2, "strength": 1.0}}
        with (mock.patch.object(app, "dialogue_tint_required", return_value=True),
              mock.patch.object(app, "crystal_coverage_target", return_value=100),
              mock.patch.object(app, "crystal_force", return_value=1.0)):
            self.assertFalse(app.tint_coverage_ready(report))
            report["coverage"]["version"] = 3
            self.assertTrue(app.tint_coverage_ready(report))

    def test_the_spoken_form_has_no_bar_marks_or_markdown(self):
        self.assertEqual(app._tint_out_clean("**Pick** a gate / see the reward / it's gone"),
                         "Pick a gate, see the reward, it's gone")
        self.assertTrue(app.rap_rhyme_evidence(app._tint_out_clean(BARS[0]))["ok"])


if __name__ == "__main__":
    unittest.main()
