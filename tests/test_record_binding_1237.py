# -*- coding: utf-8 -*-
"""#1237: a line bound to a record airs with that record.  Belongs in tests/.

    "when a song is associated with a particular dialogue, that song is
    playing whenever that basic dialogue is playing."

record_binding.py is imported for real; app.py is never imported (the
technique of tests/test_record_talk_segment_1179.py).  Nothing reads or
writes data/, nothing opens a socket.

What the request asks for, and where each is asserted:

    the photograph itself                  ThePhotograph
    (a) an intro airs only with its record  AnIntroAirsOnlyWithItsRecord
    (b) a send-off airs only after it       ASendOffAirsOnlyAfterItsRecord
    (c) the sequencer's hook                TheSequencersHook
    (d) a skip cuts the intro with it       ASkipCutsTheIntroWithTheRecord
    nothing bound = the old station         NothingBoundIsTheOldStation
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import record_binding as rb  # noqa: E402

DEATH = {"id": "a7a8c4cbc6d93371", "title": "見えないハプティクス",
         "artist": "DEATH DEVOIR", "seconds": 144.1}
GLASS = {"id": "a96cc81b649f8a91", "title": "6-I'm Going To Make A Cake",
         "artist": "Philip Glass", "seconds": 244.6}
TAPE = {"id": "8ad8c87c3e1adf88", "title": "MX tape · schitz1",
        "artist": "Ehm Eckx", "seconds": 130.0}
T0 = 1789879201.0                       # Philip Glass's needle, 04:40:01 UTC


def deck(now=None, started=0.0, coming=None, history=(), queue=(), at=T0):
    return rb.deck(now or {}, started, coming or {}, list(history),
                   list(queue), at)


class ThePhotograph(unittest.TestCase):
    """DEATH DEVOIR started 04:37:35, ended 04:39:59, Philip Glass started
    04:40:01, the DEATH DEVOIR introduction went out 04:41:27."""

    def test_the_intro_in_the_photograph_is_refused(self):
        view = deck(now=GLASS, started=T0, history=[TAPE, DEATH], at=T0 + 86)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view, 22.0)
        self.assertFalse(ok)
        self.assertIn("already played", why)
        self.assertIn("Philip Glass", why)

    def test_the_same_intro_over_its_own_record_airs(self):
        view = deck(now=DEATH, started=T0 - 146, history=[TAPE], at=T0 - 120)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view, 22.0)
        self.assertTrue(ok, why)
        self.assertIn("on the deck", why)


class AnIntroAirsOnlyWithItsRecord(unittest.TestCase):

    def test_next_record_talk_first(self):
        view = deck(now=GLASS, started=T0, coming=DEATH, at=T0 + 240)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view)
        self.assertTrue(ok, why)
        self.assertIn("next", why)

    def test_an_intro_that_would_outlive_its_record_is_refused(self):
        view = deck(now=DEATH, started=T0, at=T0 + 130)      # 14 s left
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view, 20.0)
        self.assertFalse(ok)
        self.assertIn("outlive", why)

    def test_a_live_write_is_not_started_without_the_time_for_it(self):
        view = deck(now=DEATH, started=T0, at=T0 + 40)       # 104 s left
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view, live=True)
        self.assertFalse(ok)
        self.assertIn("live introduction", why)
        # ...and is started when there is: a 245 s record, 10 s in.
        view = deck(now=GLASS, started=T0, at=T0 + 10)
        ok, why = rb.check(rb.snapshot(GLASS), rb.PART_INTRO, view, live=True)
        self.assertTrue(ok, why)

    def test_a_record_queued_but_not_next_is_named_with_its_place(self):
        view = deck(now=GLASS, started=T0, queue=[TAPE, DEATH], at=T0 + 5)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view)
        self.assertFalse(ok)
        self.assertIn("queued at 2", why)

    def test_a_record_nowhere_is_refused_and_the_deck_named(self):
        view = deck(now=GLASS, started=T0, at=T0 + 5)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_INTRO, view)
        self.assertFalse(ok)
        self.assertIn("Philip Glass", why)


class ASendOffAirsOnlyAfterItsRecord(unittest.TestCase):

    def test_the_record_just_gone(self):
        view = deck(now=GLASS, started=T0, history=[TAPE, DEATH], at=T0 + 3)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_OUTRO, view)
        self.assertTrue(ok, why)

    def test_the_record_ending_talk_first(self):
        view = deck(now=DEATH, started=T0 - 140, history=[TAPE], at=T0)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_OUTRO, view)
        self.assertTrue(ok, why)

    def test_two_records_later_is_stale(self):
        view = deck(now=TAPE, started=T0, history=[DEATH, GLASS], at=T0 + 3)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_OUTRO, view)
        self.assertFalse(ok)
        self.assertIn("stale", why)

    def test_a_record_that_never_played_has_nothing_to_send_off(self):
        view = deck(now=GLASS, started=T0, at=T0 + 3)
        ok, why = rb.check(rb.snapshot(DEATH), rb.PART_OUTRO, view)
        self.assertFalse(ok)


class TheSequencersHook(unittest.TestCase):
    """record_bound_to_block(block) for A2's GET /api/playout."""

    LEDGER = [
        {"block": 41, "ord": 0, "line_id": "l-one", "kind": "intro"},
        {"block": 41, "ord": 1, "line_id": "l-two", "kind": "interject"},
        {"block": 42, "ord": 0, "line_id": "l-three", "kind": "banter"},
    ]
    BOUND = {"l-two": {**rb.snapshot(DEATH), "part": "intro", "at": T0}}

    def lookup(self, line_id):
        return self.BOUND.get(line_id)

    def test_a_block_number_resolves_through_its_lines(self):
        got = rb.resolve(41, lambda: self.LEDGER, self.lookup)
        self.assertIsNotNone(got)
        self.assertEqual(got["id"], DEATH["id"])
        self.assertEqual(got["line_id"], "l-two")
        self.assertEqual(got["part"], "intro")

    def test_a_block_with_no_bound_line_is_none(self):
        self.assertIsNone(rb.resolve(42, lambda: self.LEDGER, self.lookup))
        self.assertIsNone(rb.resolve(99, lambda: self.LEDGER, self.lookup))

    def test_an_inspector_dict_and_a_screenplay_element(self):
        got = rb.resolve({"block": 41}, lambda: self.LEDGER, self.lookup)
        self.assertEqual((got or {}).get("id"), DEATH["id"])
        got = rb.resolve({"id": "ln-l-two"}, lambda: [], self.lookup)
        self.assertEqual((got or {}).get("id"), DEATH["id"])
        got = rb.resolve({"lines": [{"line_id": "l-one"}, {"line_id": "l-two"}]},
                         lambda: [], self.lookup)
        self.assertEqual((got or {}).get("line_id"), "l-two")

    def test_a_record_action_names_the_record_itself(self):
        got = rb.resolve("ac-rec-" + GLASS["id"], lambda: [], self.lookup,
                         lambda tid: GLASS if tid == GLASS["id"] else None)
        self.assertEqual((got or {}).get("id"), GLASS["id"])
        self.assertEqual(got["part"], "record")
        self.assertEqual(got["artist"], "Philip Glass")

    def test_a_block_that_carries_its_binding(self):
        got = rb.resolve({"bound": rb.snapshot(TAPE)}, lambda: [], self.lookup)
        self.assertEqual((got or {}).get("id"), TAPE["id"])


class ASkipCutsTheIntroWithTheRecord(unittest.TestCase):

    def test_only_the_intros_of_that_record_die(self):
        lines = {
            "intro-death": {**rb.snapshot(DEATH), "part": "intro", "at": T0 - 5},
            "outro-death": {**rb.snapshot(DEATH), "part": "outro", "at": T0 - 5},
            "intro-glass": {**rb.snapshot(GLASS), "part": "intro", "at": T0 - 5},
            "old-death": {**rb.snapshot(DEATH), "part": "intro",
                          "at": T0 - 2 * rb.CUT_LOOKBACK_S},
            "cut-death": {**rb.snapshot(DEATH), "part": "intro", "at": T0 - 5,
                          "cut_at": T0 - 1},
        }
        self.assertEqual(rb.cut_ids(lines, DEATH["id"], T0), ["intro-death"])
        self.assertEqual(rb.cut_ids(lines, GLASS["id"], T0), ["intro-glass"])
        self.assertEqual(rb.cut_ids(lines, "", T0), [])

    def test_a_cut_is_offered_to_pages_for_a_while_then_forgotten(self):
        cuts = [{"row_id": "a", "at": T0}, {"row_id": "b", "at": T0 - 500},
                {"row_id": "a", "at": T0}]
        self.assertEqual(rb.fresh_cuts(cuts, T0 + 10), ["a"])
        self.assertEqual(rb.fresh_cuts(cuts, T0 + rb.CUT_WINDOW_S + 1), [])


class NothingBoundIsTheOldStation(unittest.TestCase):

    def test_an_unbound_line_always_airs(self):
        view = deck(now=GLASS, started=T0, at=T0 + 5)
        self.assertEqual(rb.check({}, rb.PART_INTRO, view), (True, ""))
        self.assertEqual(rb.check(None, "outro", view), (True, ""))
        self.assertEqual(rb.snapshot({"title": "no id"}), {})

    def test_the_paperwork_names_the_record_without_its_id(self):
        row = rb.verdict_row(T0, "l-two", DEATH, "intro", False,
                             "its record has already played", "before the air",
                             "dj", "Let the silence hang a second")
        self.assertIn("DEATH DEVOIR", row["say"])
        self.assertIn("withdrawn", row["say"])
        self.assertNotIn(DEATH["id"], row["say"])
        self.assertEqual(row["bound"]["id"], DEATH["id"])
        self.assertEqual(rb.label(rb.snapshot(GLASS)),
                         "Philip Glass - 6-I'm Going To Make A Cake")


if __name__ == "__main__":
    unittest.main()
