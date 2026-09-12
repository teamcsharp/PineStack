"""2026-09-08: the retirement desk. "Whenever rhyming rhetoric ... is pending
deletion ... I want Pinebox to show me a notification so I can go in and
approve it ... set the rules for objects of that type ... timers for each and
every item."

Every deletion road asks retire_may(); a rhymed round waits for the operator
by default, a plain one goes as before; remove takes it out at once, keep
extends its life and its airings; the rules are per kind; the state lists
every item with its timer; the ceilings still bound the stores."""
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app

_REAL_LARDER_CURRENT = app._larder_current      # the fixture patches it; two tests need the real one


def _round(at=None, tinted=True, aired_at=0.0, aired=0, **extra):
    now = time.time()
    row = {"at": at if at is not None else now, "script": "A: The plate is copper, mate.",
           "script_plain": "A: The plate is copper.", "aired_at": aired_at, "aired": aired}
    if tinted:
        row["script_tinted"] = row["script"]
        row["use"] = "tinted"
    row.update(extra)
    return row


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {
            "dialogue_tint_required": lambda: True,
            "dialogue_tint_ready": lambda kind, row: bool((row or {}).get("script_tinted")),
            "orch_policy": lambda *a, **k: None,
            "note_action": mock.Mock(), "_larder_save": mock.Mock(), "_pantry_save": mock.Mock(),
            "_radio_entry_rejected": mock.Mock(), "_retire_write": mock.Mock(),
            "_RETIRE": {"rules": {}, "ledger": {}, "seq": 0, "noted_at": 0.0, "noted": 0, "saved_at": 0.0},
            "_LARDER": [], "_SHELF": {}, "larder_cap": lambda: 3, "TINTED_KEEP_ROWS": 4,
            "_larder_current": lambda e: True,
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def test_the_rules_default_to_asking_about_rhymed_items(self):
        banter = app.retire_rule("banter")
        self.assertEqual(banter["ask"], "tinted")
        # 2026-09-09 (#1157): forever, not 96 hours. See the note in
        # test_gold_freeze_2026_09_09.py - the desk had never recorded
        # anything because the shield returned above retire_may, and the
        # keep would have released four days of backlog in one minute.
        self.assertEqual(banter["keep_hours"], app.RETIRE_KEEP_FOREVER)
        self.assertEqual(banter["innings"], app.SHELF_REUSE_MOST_EVERGREEN)
        self.assertEqual(app.retire_rule("news")["ask"], "never")
        self.assertEqual(app.retire_rule("news")["keep_hours"], 0.0)
        self.assertEqual(app.retire_rule("station_id")["ask"], "never")
        kinds = app.retire_kinds()
        self.assertEqual(kinds[0], "banter")
        self.assertIn("gallery", kinds)

    def test_a_plain_round_goes_and_a_rhymed_round_waits(self):
        plain = _round(tinted=False)
        self.assertTrue(app.retire_may("banter", plain, "past the larder's freshness"))
        self.assertEqual(app.retire_summary()["pending"], 0)
        rhymed = _round()
        self.assertFalse(app.retire_may("banter", rhymed, "past the larder's freshness"))
        self.assertFalse(app.retire_may("banter", rhymed, "past the larder's freshness"))
        summary = app.retire_summary()
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["rhymed"], 1)
        entry = app._RETIRE["ledger"][rhymed["sid"]]
        self.assertEqual(entry["state"], "pending")
        self.assertEqual(entry["asks"], 1)
        self.assertIn("freshness", entry["why"])
        app.note_action.assert_called()

    def test_remove_takes_it_out_of_the_larder_now(self):
        row = _round()
        app._LARDER.append(row)
        self.assertFalse(app.retire_may("banter", row, "over the cap"))
        got = app.retire_decide([row["sid"]], "remove")
        self.assertEqual(got["removed"], [row["sid"]])
        self.assertNotIn(row, app._LARDER)
        self.assertEqual(app._RETIRE["ledger"][row["sid"]]["state"], "remove")
        self.assertEqual(app.retire_summary()["pending"], 0)
        app._larder_save.assert_called()
        # Were the same row to come back by another road, the answer stands.
        self.assertTrue(app.retire_may("banter", row, "over the cap"))

    def test_remove_takes_a_shelf_row_out_too(self):
        row = {"at": time.time() - 100000, "text": "A painting of a copper plate, mate.", "tint_ok": True,
               "aired": 12, "aired_at": time.time() - 4 * 3600}
        app._SHELF["gallery"] = [row]
        self.assertFalse(app.resort_may_drop("gallery", row, set(), "the shelf burn sweep"))
        got = app.retire_decide([row["sid"]], "remove")
        self.assertEqual(got["removed"], [row["sid"]])
        self.assertEqual(app._SHELF["gallery"], [])
        app._pantry_save.assert_called()

    def test_an_explicit_keep_is_the_operators_and_the_kinds_rule_does_not_stomp_it(self):
        """2026-09-09 (#1157): the kind now keeps rhymed work for good, but a
        hand-set extension is a decision about THIS item and outranks the
        default. Found by this test: without the retire_kept guard in
        tinted_keep_until, the desk's own extend button was a no-op."""
        row = _round(aired_at=time.time() - 4 * 3600, aired=app.SHELF_REUSE_MOST_EVERGREEN)
        app._LARDER.append(row)
        self.assertFalse(app.retire_may("banter", row, "its innings are used"))
        got = app.retire_decide([row["sid"]], "keep", 48)
        self.assertEqual(got["kept"], [row["sid"]])
        self.assertAlmostEqual(row["keep_until"], time.time() + 48 * 3600, delta=30)
        self.assertEqual(row["retire_kept"], 1)
        self.assertGreater(app.row_innings("banter", row), app.SHELF_REUSE_MOST_EVERGREEN)
        self.assertTrue(app.shelf_is_repeat("banter", row))
        self.assertEqual(app._RETIRE["ledger"][row["sid"]]["state"], "keep")
        # The keep does its job: no new ask while the extended life runs.
        self.assertFalse(app.retire_may("banter", row, "its innings are used"))
        self.assertEqual(app._RETIRE["ledger"][row["sid"]]["asks"], 1)
        self.assertEqual(app.retire_summary()["pending"], 0)
        # When it lapses the desk asks again, as a new arrival.
        row["keep_until"] = time.time() - 1
        self.assertFalse(app.retire_may("banter", row, "past the larder's freshness"))
        entry = app._RETIRE["ledger"][row["sid"]]
        self.assertEqual(entry["state"], "pending")
        self.assertEqual(entry["asks"], 2)

    def test_keep_without_hours_uses_the_kinds_rule(self):
        row = _round()
        app._LARDER.append(row)
        app.retire_may("banter", row, "over the cap")
        app.retire_decide([row["sid"]], "keep")
        # 2026-09-09 (#1157): the kind's rule is now "for good". Before the
        # fix this computed now + (-1 * 3600) and then clamped to 0.5 h - a
        # keep that expired half an hour after the operator granted it.
        self.assertEqual(row["keep_until"], app.KEEP_FOREVER_AT)

    def test_a_keep_from_an_hours_rule_still_expires(self):
        app.retire_rules_set("banter", keep_hours=48)
        row = _round()
        app._LARDER.append(row)
        app.retire_may("banter", row, "over the cap")
        app.retire_decide([row["sid"]], "keep")
        self.assertAlmostEqual(row["keep_until"], time.time() + 48 * 3600, delta=30)

    def test_the_rules_change_who_is_asked_and_how_long_a_keep_is(self):
        app.retire_rules_set("banter", ask="all")
        plain = _round(tinted=False)
        self.assertFalse(app.retire_may("banter", plain, "over the cap"))
        app.retire_rules_set("banter", ask="never")
        self.assertTrue(app.retire_may("banter", _round(), "over the cap"))
        app.retire_rules_set("banter", ask="tinted", keep_hours=48, innings=20)
        fresh = _round()
        self.assertAlmostEqual(app.tinted_keep_until("banter", fresh), time.time() + 48 * 3600, delta=30)
        self.assertEqual(app.row_innings("banter", fresh), 20)
        rules = {r["kind"]: r for r in app.retire_rules_all()}
        self.assertEqual(rules["banter"]["keep_hours"], 48.0)
        self.assertEqual(rules["banter"]["innings"], 20)
        self.assertIn("plain", rules["banter"]["clocks"])
        app._retire_write.assert_called()
        with self.assertRaises(ValueError):
            app.retire_decide(["x"], "shred")

    def test_the_state_lists_every_item_with_its_timer_waiting_first(self):
        old = _round(at=time.time() - 3600, aired_at=time.time() - 1800, aired=1)
        young = _round(tinted=False)
        app._LARDER.extend([young, old])
        app._SHELF["gallery"] = [{"at": time.time(), "text": "A painting of a copper plate.", "tint_ok": True, "aired": 0}]
        self.assertFalse(app.retire_may("banter", old, "the contract moved"))
        state = app.retire_state()
        self.assertEqual(state["counts"]["inventory"], 3)
        self.assertEqual(state["counts"]["pending"], 1)
        self.assertEqual(state["pending"][0]["id"], old["sid"])
        self.assertTrue(state["pending"][0]["live"])
        first = state["inventory"][0]
        self.assertEqual(first["id"], old["sid"])
        self.assertTrue(first["pending"])
        for item in state["inventory"]:
            self.assertGreaterEqual(item["life_left"], 0)
            self.assertIn("innings", item)
            self.assertIn("stage", item)
        self.assertEqual(sum(1 for i in state["inventory"] if i["rhymed"]), 2)
        self.assertEqual(len(state["rules"]), len(app.retire_kinds()))
        # A waiting row that left by another road is retired from the queue.
        app._LARDER.remove(old)
        state = app.retire_state()
        self.assertEqual(state["counts"]["pending"], 0)
        self.assertEqual(app._RETIRE["ledger"][old["sid"]]["state"], "gone")

    def test_the_larder_trim_keeps_waiting_rows_and_the_ceiling_still_holds(self):
        plain = [_round(at=time.time() - i, tinted=False) for i in range(5)]
        rhymed = [_round(at=time.time() - 100 - i, aired_at=time.time() - 7200 - i, aired=1) for i in range(6)]
        app._LARDER.extend(plain + rhymed)
        app.larder_trim()
        # Three plain rows (the cap), every rhymed row (two over the repertoire ceiling wait).
        self.assertEqual(sum(1 for e in app._LARDER if not e.get("script_tinted")), 3)
        self.assertEqual(sum(1 for e in app._LARDER if e.get("script_tinted")), 6)
        self.assertEqual(app.retire_summary()["pending"], 2)
        # The hard ceiling - twice cap + repertoire = 14 - forces the oldest out and writes it down.
        app._LARDER.extend(_round(at=time.time() - 1000 - i, aired_at=time.time() - 9000, aired=1) for i in range(8))
        app.larder_trim()
        self.assertLessEqual(len(app._LARDER), 14)
        forced = [v for v in app._RETIRE["ledger"].values() if v.get("state") == "forced"]
        self.assertTrue(forced)
        self.assertIn("ceiling", forced[0]["why"])

    def test_a_rhymed_round_in_its_keep_survives_a_moved_contract(self):
        # 13:54 CST, 2026-09-08: the plot's act rolled over, the writing contract
        # moved, and every kept round was rebound away without a word.
        with mock.patch.object(app, "_larder_profile_signature", lambda: "today"), \
                mock.patch.object(app, "_larder_current", _REAL_LARDER_CURRENT):
            rhymed = _round(profile="yesterday")
            plain = _round(tinted=False, profile="yesterday")
            self.assertTrue(app._larder_current(rhymed))
            self.assertFalse(app._larder_current(plain))
            self.assertTrue(app.dialogue_row_viable("banter", rhymed))
            self.assertIn("contract", app.larder_unviable_why(plain))
            app._LARDER.extend([rhymed, plain])
            self.assertEqual(app.larder_rebind_viable(), 1)
            self.assertEqual(app._LARDER, [rhymed])
            app._radio_entry_rejected.assert_called_once()
            # With the rule at "everything" the plain round waits instead.
            app.retire_rules_set("banter", ask="all")
            plain2 = _round(tinted=False, profile="yesterday")
            app._LARDER.append(plain2)
            self.assertEqual(app.larder_rebind_viable(), 0)
            self.assertIn(plain2, app._LARDER)
            self.assertEqual(app.retire_summary()["pending"], 1)
            # Keep re-binds the contract: the operator says it is fine today.
            app.retire_decide([plain2["sid"]], "keep", 24)
            self.assertEqual(plain2["profile"], "today")
            self.assertTrue(app._larder_current(plain2))

    def test_a_waiting_row_holds_its_clips(self):
        row = _round(keys=["clip-a", "clip-b"], profile="x")
        app._LARDER.append(row)
        with mock.patch.object(app, "_larder_profile_signature", lambda: "y"), \
                mock.patch.object(app, "_larder_current", _REAL_LARDER_CURRENT), \
                mock.patch.object(app, "tinted_kept", lambda kind, r: False), \
                mock.patch.object(app, "_row_clip_keys", lambda r: set(r.get("keys") or [])):
            self.assertFalse(app.dialogue_row_viable("banter", row))
            self.assertFalse(app.retire_may("banter", row, "the contract moved"))
            self.assertIn(row["sid"], app.retire_pending_ids())
            self.assertTrue({"clip-a", "clip-b"} <= app.pantry_spoken_for())

    def test_the_larder_prune_reads_one_rule(self):
        stale = _round(at=time.time() - 30 * 3600, tinted=False)
        self.assertIn("freshness", app.larder_prune_why(stale, False))
        self.assertEqual(app.larder_prune_why(_round(tinted=False), False), "")
        self.assertEqual(app.larder_prune_why(stale, True), "")          # paused and unheard
        with mock.patch.object(app, "_larder_current", lambda e: False):
            self.assertIn("contract", app.larder_prune_why(_round(tinted=False), False))


if __name__ == "__main__":
    unittest.main()
