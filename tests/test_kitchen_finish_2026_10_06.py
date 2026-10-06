"""[kitchen-finish] 2026-10-06: the finishing rooms skip what is finished.

The pantry's "already ready - skip" test handed dialogue_row_ready() the inner
entry; the predicate is written for the shelf row. 53 finished rows read unready
that way and filled the recording pool and the visit budget on every pass, so
the rows behind them were never reached while nothing aired.
"""
import ast
import unittest
from pathlib import Path

import app

SOURCE = Path(app.__file__).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _source(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node)
    raise AssertionError("no top-level function %s" % name)


class FinishingRoomsSkipWhatIsFinished(unittest.TestCase):
    def test_the_pantry_hands_the_predicate_the_row(self):
        src = _source("pantry_keeper")
        self.assertNotIn("dialogue_row_ready(_kind, _e)", src)
        self.assertNotIn("dialogue_row_ready(_kind, _shelved)", src)
        # the two repaired sites, beside the row-based call the block already had
        self.assertGreaterEqual(src.count("dialogue_row_ready(_kind, _row)"), 3)

    def test_larder_prepare_asks_the_entry_shaped_predicates(self):
        src = _source("larder_prepare")
        self.assertNotIn("dialogue_row_ready(_pkind, entry)", src)
        self.assertIn("dialogue_audio_ready(_pkind, entry)", src)
        self.assertIn("dialogue_tint_ready(_pkind, entry)", src)

    def test_a_shelf_row_and_its_entry_are_both_understood_by_dialogue_entry(self):
        entry = {"script": "A: hi\nB: hello", "prep_kind": "manager", "lines": 2}
        row = {"entry": entry, "at": 1.0}
        self.assertIs(app.dialogue_entry(row), entry)
        self.assertIs(app.dialogue_entry(entry), entry)


if __name__ == "__main__":
    unittest.main()
