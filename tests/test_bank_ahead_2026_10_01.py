"""[bank-ahead] 2026-10-01: a pause banks the demanding roads days ahead.

"the goal of pausing the station is to bank enough quality roulette driven
system 3 dialogue to alleviate the realtime pressure of speech generation
... I want callers being stored with variable outcomes and manager messages
for days queued up."
"""
import unittest
from unittest import mock

import app


def settings(**over):
    base = dict(app.DEFAULT_DJ)
    base.update(over)
    return base


class BankAhead(unittest.TestCase):
    def patch(self, paused=True, **dj):
        return [mock.patch.object(app, "radio_paused", lambda: paused),
                mock.patch.object(app, "dj_settings", lambda: settings(**dj))]

    def run_with(self, patches, fn):
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def test_only_while_paused_and_only_for_the_listed_roads(self):
        self.assertEqual(self.run_with(self.patch(paused=False), lambda: app.bank_ahead_hours("caller")), 0.0)
        self.assertEqual(self.run_with(self.patch(), lambda: app.bank_ahead_hours("caller")), 72.0)
        self.assertEqual(self.run_with(self.patch(), lambda: app.bank_ahead_hours("manager")), 72.0)
        self.assertEqual(self.run_with(self.patch(), lambda: app.bank_ahead_hours("news")), 0.0)
        self.assertEqual(self.run_with(self.patch(bank_ahead_hours=0), lambda: app.bank_ahead_hours("caller")), 0.0)

    def test_the_shelf_makes_room_for_days(self):
        on_air = self.run_with(self.patch(paused=False), lambda: app.shelf_cap("manager"))
        paused = self.run_with(self.patch(), lambda: app.shelf_cap("manager"))
        self.assertGreaterEqual(paused, app.SHELF_CAPS["manager"] * 72 // 2)
        self.assertGreater(paused, on_air)
        # a road off the list keeps exactly the cap it had
        news = self.run_with(self.patch(), lambda: app.shelf_cap("news"))
        news_off = self.run_with(self.patch(bank_ahead_hours=0), lambda: app.shelf_cap("news"))
        self.assertEqual(news, news_off)

    def test_a_banked_road_is_owed_days_even_without_an_entry_this_hour(self):
        patches = self.patch() + [
            mock.patch.object(app, "schedule_read", lambda: {"enabled": True}),
            mock.patch.object(app, "schedule_slots_now", lambda store: ("x", [])),
        ]
        got = self.run_with(patches, app.hour_needs)
        self.assertEqual(got["manager"]["owed"], app.BANK_AHEAD_SEGMENT_SECONDS * 72)
        self.assertIn("caller", got)
        patches = self.patch(paused=False) + patches[2:]
        self.assertNotIn("manager", self.run_with(patches, app.hour_needs))

    def test_the_dial_is_sanitised(self):
        base = app.validate_settings(app.DEFAULT_SETTINGS)
        got = app.validate_settings(dict(app.DEFAULT_SETTINGS, dj=dict(
            base["dj"], bank_ahead_hours=999,
            bank_ahead_roads="Manager, caller, news, nonsense, caller")))
        dj = got["dj"]
        self.assertEqual(dj["bank_ahead_hours"], 168.0)
        self.assertEqual(dj["bank_ahead_roads"], "manager,caller")


class CallOutcome(unittest.TestCase):
    def test_system3_callend_wins(self):
        entry = {"prep_name": "Dana", "prep_rule": {"label": "abrupt hang-up"},
                 "call": {"callend": {"says": "she wins the painting",
                                      "resolve": {"id": "R7", "label": "wins the painting",
                                                  "effect": "awarded", "prize": "a painting"}},
                          "scenario": {"conclusion": {"label": "a truce"}}}}
        got = app.call_outcome_of(entry)
        self.assertEqual(got["source"], "system3")
        self.assertEqual(got["label"], "wins the painting")
        self.assertEqual(got["effect"], "awarded")
        self.assertEqual(got["conclusion"], "a truce")
        self.assertEqual(got["caller"], "Dana")

    def test_the_ending_shelf_otherwise(self):
        got = app.call_outcome_of({"prep_rule": {"label": "furious hang-up", "text": "slams the phone"}})
        self.assertEqual(got["source"], "ending_shelf")
        self.assertEqual(got["label"], "furious hang-up")
        self.assertEqual(app.call_outcome_of({}), {})

    def test_the_census_counts_unheard_endings(self):
        rows = [{"entry": {"prep_rule": {"label": "furious hang-up"}}, "aired": 0},
                {"entry": {"prep_rule": {"label": "furious hang-up"}}, "aired": 0},
                {"entry": {"prep_rule": {"label": "wins trivia"}}, "aired": 0}]
        with mock.patch.object(app, "shelf_rows", lambda k: rows if k == "caller" else []), \
                mock.patch.object(app, "row_unaired", lambda r: True):
            got = app.caller_outcome_census()
        self.assertEqual(got["unheard_calls"], 3)
        self.assertEqual(got["distinct"], 2)
        self.assertEqual(got["endings"]["furious hang-up"], 2)
        self.assertAlmostEqual(got["most_common_share"], 0.67)


if __name__ == "__main__":
    unittest.main()
