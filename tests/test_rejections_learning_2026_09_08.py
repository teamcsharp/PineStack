"""2026-09-08 (evening): the rejections the operator saw, and what the
station learns from them."""
import unittest
from unittest import mock

import app


class TransformationRuleTests(unittest.TestCase):
    SOURCE = "Hold on to line seven five six three eight; Hello now, what you see there"

    def test_the_operators_own_edit_passes_it_rhymes_now(self):
        # Typed by the operator into "Try wording" and refused for exactly one
        # fault: the candidate carries the source's words and adds a landing.
        made = "Hold on to line seven five six three eight; Hello now, what you see there this late."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=False)
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(report["transformation"]["rhyme_added"])
        self.assertEqual(report["transformation"]["lexical_distance"], 0.143)

    def test_an_echo_that_does_not_rhyme_is_still_refused(self):
        made = "Hold on to line seven five six three eight; Hello now, what you see there tonight."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["transformation"]["rhyme_added"])
        self.assertIn("rhetoric was not materially transformed", report["faults"])

    def test_the_strict_grade_still_demands_the_full_transformation(self):
        made = "Hold on to line seven five six three eight; Hello now, what you see there this late."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=True)
        self.assertIn("rhetoric was not materially transformed", report["faults"])

    def test_an_echo_is_named_as_an_echo_in_the_repair_hint(self):
        # 92 of the 95 "not transformed" cuts in the census handed the source back unchanged.
        hint = app.tint_repair_hint(self.SOURCE, self.SOURCE + " tonight.",
                                    ["rhetoric was not materially transformed"], {})
        self.assertIn("ECHO", hint)
        self.assertIn("two to four bars", hint)
        recast = app.tint_repair_hint(self.SOURCE, "Line seven five six three eight is on hold, so hello and tell me now.",
                                      ["rhetoric was not materially transformed"], {})
        self.assertIn("STYLE", recast)
        self.assertNotIn("ECHO", recast)

    def test_a_source_that_already_rhymes_gets_no_credit_for_keeping_it(self):
        source = "The plate is copper and the station waits tonight / the copper hums and the light is bright"
        made = source + " indeed"
        report = app.tint_evaluate(source, made, [], force=0.88, strict=False)
        self.assertFalse(report["transformation"]["rhyme_added"])


if __name__ == "__main__":
    unittest.main()
