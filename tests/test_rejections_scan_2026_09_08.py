"""2026-09-08 (late): the deep scan of the rejection queue - the source side.

45 of 199 cut lines were verbatim speakbox passages stapled into a round as
a turn; every 600+ character source but one, every raw run-on and every
mid-word stub ("Mfortable.", "Sgard.") was one. A passage no bar-set can
carry is read plain; the two doors the afternoon's bound missed (the seed
put-back and the full swath) are bounded when raw; the harvest window opens
on a sentence or a word, never inside one, and a stub is not fresh material.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import line_review

LONG = ("Got to keep the little fucker busy. Wouldn't want him to sneak in a little unstructured time "
        "in the woods; that wouldn't be any good for anyone at all. " * 3).strip()
RAW = " ".join(["word"] * 60)
STUB = "Sgard. And i am burdened with glorious purpose."
SHORT = "It's no different, bro. It's a coming showing you a problem."


class PlainPassages(unittest.TestCase):
    def test_a_verbatim_passage_no_bar_set_can_carry_is_read_plain(self):
        verbatim = [["head", LONG], ["head", RAW], ["head", STUB], ["tail", "trying to discern what's real and what's not."],
                    ["head", SHORT]]
        self.assertTrue(app._tint_plain_passage(LONG, verbatim))            # 300+ characters
        self.assertTrue(app._tint_plain_passage(RAW, verbatim))             # a raw run-on
        self.assertTrue(app._tint_plain_passage(STUB, verbatim))            # a mid-word stub
        self.assertTrue(app._tint_plain_passage("trying to discern what's real and what's not.", verbatim))
        self.assertFalse(app._tint_plain_passage(SHORT, verbatim))          # short and punctuated: still tinted
        self.assertFalse(app._tint_plain_passage("Exactly. It feels like a tangible piece of control.",
                                                 [["head", "Exactly. It feels like a tangible piece of control."]]))

    def test_a_turn_the_writer_wrote_is_never_a_passage(self):
        self.assertFalse(app._tint_plain_passage(LONG, []))
        self.assertFalse(app._tint_plain_passage(LONG, None))
        self.assertFalse(app._tint_plain_passage(STUB, [["head", SHORT]]))

    def test_the_regrade_sweep_reads_such_rows_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = line_review.LineReviewStore(Path(tmp) / "lr.sqlite3")
            row = store.record("tint", LONG, "a bar that keeps nothing", ["semantic checks did not pass"],
                               {"kind": "banter", "chunks": [], "entry": {"verbatim": [["head", LONG]]}},
                               evaluation={"strength": 0.88, "version": 9})
            with mock.patch.object(app, "_LINE_REVIEW", store), \
                    mock.patch.object(app, "_crystal_vocab", lambda: set()), \
                    mock.patch.object(app, "crystal_grade_strict", lambda: False):
                got = app.line_review_regrade_pending()
            self.assertEqual(got["read_plain"], 1, got)
            self.assertEqual(store.get(row["id"])["effect"]["status"], "read_plain")


class HarvestWindow(unittest.TestCase):
    def test_the_window_opens_on_a_sentence_or_a_word_never_inside_one(self):
        body = "comfortable feeling here. Asgard and i am burdened with glorious purpose today " * 20
        at = 3                                   # inside "comfortable"
        start = app._harvest_window_start(body, at)
        self.assertEqual(body[start:start + 6], "Asgard")
        raw = "so ultra boutique bougie wealth poured out everywhere " * 40
        start = app._harvest_window_start(raw, 4)     # inside "ultra": the next word
        self.assertEqual(raw[start:start + 8], "boutique")
        self.assertEqual(app._harvest_window_start(body, 0), 0)

    def test_a_stub_is_not_fresh_material(self):
        for line in ("Mfortable. Must feel good.", STUB, "trying to discern what's real and what's not."):
            with self.subTest(line=line):
                self.assertTrue(app._gem_is_stub(line))
        for line in ("Exactly. It feels like a tangible piece of control.", "The station needs a copper plate.",
                     "Hold on. Cheers and applause.", "Dreamscape is too flowery; it should have been called peace."):
            with self.subTest(line=line):
                self.assertFalse(app._gem_is_stub(line))


class BoundedDoors(unittest.TestCase):
    def test_the_bound_is_applied_where_the_passages_go_in(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn('_seed_put = _verbatim_turn_text(seed["text"])', source)
        self.assertIn('_full_text = _verbatim_turn_text(full_swath["text"])', source)
        self.assertIn('and not _tint_plain_passage(str(s or ""), verbatim)', source)


if __name__ == "__main__":
    unittest.main()
