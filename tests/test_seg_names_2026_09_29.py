"""[seg-names] THE SCRIPT'S ROUND CARDS CARRY THE OPERATOR'S SEGMENT NAMES.

"these should be named after the segment names I assigned to the station."

The round ledger never wrote down which running-order entry a round filled,
so the Script titled every card by its road ("Studio Banter"). The link lives
on the entry (System2's reservation, the shelf's window, the slot a job banked
it for); screenplay_round_open now reads it and the round row keeps it.

The failures worth a test are the silent ones: a link that falls back to the
clock (adherence was once 4%, so the name would be wrong and look right), and
an UNKNOWN round drawn as "(no slot)" - which tells the operator something
false about his running order.
"""
import inspect
import unittest
from unittest import mock

import app


class FakeRuntime:
    def __init__(self, slots):
        self._plans = [{"slots": slots}]
        self._event_plans = []
        self.store = None


def plan(occ, label, kind):
    return {"id": occ, "label": label, "kind": kind,
            "preset": "canonical hour (fits the engine)", "start": 100.0}


class RoundSlotLink(unittest.TestCase):
    def setUp(self):
        runtime = FakeRuntime([plan("hour-1:hour-03", "Painting selling", "gallery"),
                               plan("hour-1:hour-08", "Call with banter", "banter_caller")])
        self.patches = [mock.patch.dict(app.__dict__, {"_system2": lambda: runtime}),
                        mock.patch.object(app, "segment_on_air", return_value={})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_the_reservation_names_the_entry(self):
        got = app.screenplay_round_slot({"prep_kind": "gallery",
                                         "_system2": {"slot_id": "hour-1:hour-03",
                                                      "reservation_id": "r1"}})
        self.assertEqual((got["label"], got["how"], got["entry"]),
                         ("Painting selling", "stacked", "hour-03"))

    def test_the_shelf_window_counts_only_for_its_own_road(self):
        got = app.screenplay_round_slot({"prep_kind": "caller", "_ready_slot": {
            "occurrence": "hour-1:hour-08", "slot_id": "hour-08", "kind": "banter_caller"}})
        self.assertEqual((got["label"], got["how"]), ("Call with banter", "shelf"))
        other = app.screenplay_round_slot({"prep_kind": "manager", "_ready_slot": {
            "occurrence": "hour-1:hour-08", "slot_id": "hour-08", "kind": "banter_caller"}})
        self.assertEqual(other["how"], "none")

    def test_the_entry_on_air_counts_only_when_it_runs_the_road(self):
        seg = {"id": "hour-1:hour-06", "template": "hour-06", "kind": "manager",
               "label": "Angry messages from upstairs", "start": 5.0}
        with mock.patch.object(app, "segment_on_air", return_value=seg):
            mine = app.screenplay_round_slot({"prep_kind": "manager"})
            theirs = app.screenplay_round_slot({"prep_kind": "gallery"})
            rescued = app.screenplay_round_slot({"prep_kind": "manager", "_ready_free": True})
        self.assertEqual((mine["label"], mine["how"]),
                         ("Angry messages from upstairs", "on its entry"))
        self.assertEqual(theirs["how"], "none")        # never the clock's guess
        self.assertEqual(rescued["how"], "none")
        self.assertIn("rescue", rescued["why"])

    def test_banked_for_is_the_last_link(self):
        got = app.screenplay_round_slot({"prep_kind": "gallery",
                                         "system2_slot": "hour-1:hour-03"})
        self.assertEqual((got["label"], got["how"]), ("Painting selling", "banked"))

    def test_a_road_no_entry_runs_says_so(self):
        got = app.screenplay_round_slot({"prep_kind": "station_id"})
        self.assertEqual(got["how"], "none")
        self.assertIn("no entry", got["why"])

    def test_the_round_row_keeps_the_mark(self):
        mark = {"at": 1.0, "had": set(), "slot": {"occurrence": "x", "label": "Ad read",
                                                  "how": "stacked"}}
        with mock.patch.dict(app._RADIO, {"chat": [{"id": "l1", "text": "hi"}]}):
            row = app.screenplay_round_row({"prep_kind": "ad"}, mark)
        self.assertEqual(row["slot"]["label"], "Ad read")

    def test_the_open_stamps_the_slot(self):
        src = inspect.getsource(app.screenplay_round_open)
        self.assertIn("screenplay_round_slot(entry)", src)
        self.assertIn("screenplay_slot_label", inspect.getsource(app.screenplay_round_write))

    def test_an_unnamed_occurrence_is_named_from_the_sheet(self):
        with mock.patch.dict(app.__dict__, {"_system2": lambda: FakeRuntime([])}), \
                mock.patch.object(app, "schedule_public", return_value={
                    "active": "canonical hour (fits the engine)",
                    "slots": [{"id": "hour-04", "kind": "ad", "label": "Ad read"}]}):
            got = app.screenplay_slot_label({"occurrence": "p|h|3|hour-04|1",
                                             "entry": "hour-04", "how": "shelf"})
        self.assertEqual((got["label"], got["label_from"]), ("Ad read", "running order"))


def air(rid, at, rnd):
    return {"id": rid, "who": "dj", "kind": "banter", "round": rnd,
            "text": "words " + rid, "air_at": at, "ts": at, "aired": "published",
            "seconds": 2.0, "sid": "s-" + rid, "turn": 0}


class SceneHeadingCarriesTheSlot(unittest.TestCase):
    def compose(self, rows, rounds, open_round=None):
        d = {"air": rows, "prov": {}, "rounds": rounds, "records": [], "ads": [],
             "calls": [], "memos": [], "pauses": [], "models": [],
             "open_round": open_round or {}}
        with mock.patch.object(app, "script_ledger_order", return_value={}):
            script = app.screenplay_compose(0.0, 1e12, d, [])
        return {e["round"]: e.get("slot") for e in script["elements"]
                if e.get("type") == "scene"}

    def test_named_none_and_unknown_are_three_answers(self):
        rows = [air("a", 100.0, "gallery"), air("b", 400.0, "manager"),
                air("c", 800.0, "banter"), air("d", 1200.0, "station_id")]
        rounds = [{"at": 99.0, "lines": ["a"], "kind": "gallery",
                   "slot": {"occurrence": "o", "entry": "hour-03", "how": "stacked",
                            "label": "Painting selling"}},
                  {"at": 399.0, "lines": ["b"], "kind": "manager",
                   "slot": {"how": "none", "why": "the entry on air runs another road"}},
                  {"at": 799.0, "lines": ["c"], "kind": "banter"}]      # older than the stamp
        got = self.compose(rows, rounds)
        self.assertEqual(got["gallery"]["label"], "Painting selling")
        self.assertTrue(got["manager"]["none"])
        self.assertIsNone(got["banter"])          # unknown is never drawn as none
        self.assertTrue(got["station_id"]["none"])

    def test_the_round_on_air_is_named_before_its_row_lands(self):
        rows = [air("a", 500.0, "banter")]
        got = self.compose(rows, [], open_round={
            "at": 499.0, "kind": "banter",
            "slot": {"occurrence": "o", "how": "on its entry", "label": "Banter during recordings"}})
        self.assertEqual(got["banter"]["label"], "Banter during recordings")


if __name__ == "__main__":
    unittest.main()
