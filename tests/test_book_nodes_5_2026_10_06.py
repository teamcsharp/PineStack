"""[book-nodes-5] 2026-10-06: stock-before-prose leaves a segment's window alone - its parts are stock already.

The 16:15 window: the sweep stood aside, and gap_kind_policy swapped the sheet's book_time for a banked call.
"""
import unittest
from pathlib import Path
from unittest import mock

import app


class StockBeforeProseAndTheWindow(unittest.TestCase):
    def test_an_owned_book_time_window_keeps_its_kind(self):
        with mock.patch.object(app, "dynamic_segment_window_owned", lambda: True, create=True):
            self.assertEqual(app.gap_kind_policy("book_time", {}), ("book_time", ""))
            self.assertEqual(app.gap_kind_policy("sfx_supercut", {}), ("sfx_supercut", ""))

    def test_a_window_that_owns_nothing_is_the_policy_s_to_judge(self):
        """The question is asked; what the policy answers then is its own business (it may keep or swap)."""
        asked = []

        def owned():
            asked.append(True)
            return False
        with mock.patch.object(app, "dynamic_segment_window_owned", owned, create=True):
            kind, why = app.gap_kind_policy("book_time", {})
        self.assertTrue(asked, "the policy asks whether the window owns the air")
        self.assertIsInstance(kind, str)

    def test_cover_kinds_are_still_never_touched(self):
        with mock.patch.object(app, "dynamic_segment_window_owned", lambda: True, create=True):
            self.assertEqual(app.gap_kind_policy("record", {}), ("record", ""))
            self.assertEqual(app.gap_kind_policy("", {}), ("", ""))

    def test_the_rule_is_in_the_policy_not_in_the_chain(self):
        src = Path(app.__file__).read_text(encoding="utf-8")
        body = src.split("def gap_kind_policy", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('if kind in ("book_time", "sfx_supercut"):', body)
        self.assertIn('_owned = globals().get("dynamic_segment_window_owned")', body)


if __name__ == "__main__":
    unittest.main()
