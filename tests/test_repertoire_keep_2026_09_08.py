"""2026-09-08: "tinted rhetoric should not expire for 96 hours. Once it is
rhyming, I need that stored and played and added to the repertoire."

A rhymed round keeps for TINTED_KEEP_SECONDS from the moment it is first
seen through the crystal; every expiry clock and drop predicate honours the
stamp; the larder holds the repertoire beside its stock; a kept round gets
the evergreen innings; a purge spares it unless forced."""
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


def _entry(at=None, aired_at=0.0, aired=0, tinted=True, **extra):
    now = time.time()
    row = {"at": at if at is not None else now, "script": "A: The plate is copper, mate.",
           "script_plain": "A: The plate is copper.", "aired_at": aired_at, "aired": aired}
    if tinted:
        row["script_tinted"] = row["script"]
        row["use"] = "tinted"
    row.update(extra)
    return row


class KeepTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app, "dialogue_tint_required", lambda: True))
        self.stack.enter_context(mock.patch.object(
            app, "dialogue_tint_ready", lambda kind, row: bool((row or {}).get("script_tinted"))))
        self.stack.enter_context(mock.patch.object(app, "orch_policy", lambda *a, **k: None))
        self.stack.enter_context(mock.patch.object(app, "TINTED_KEEP_SECONDS", 345600.0))
        # The retirement desk (later on 2026-09-08) asks before a rhymed round
        # is dropped; these tests pin the trim itself, so the rule is "never".
        self.stack.enter_context(mock.patch.object(app, "_RETIRE", {
            "rules": {"banter": {"ask": "never"}}, "ledger": {}, "seq": 0,
            "noted_at": 0.0, "noted": 0, "saved_at": 0.0}))
        self.stack.enter_context(mock.patch.object(app, "_retire_write", mock.Mock()))

    def test_a_rhymed_round_is_stamped_96_hours_and_a_plain_one_is_not(self):
        row = _entry()
        until = app.tinted_keep_until("banter", row)
        self.assertGreater(until, time.time() + 345600 - 60)
        self.assertEqual(row["keep_until"], until)
        self.assertTrue(app.tinted_kept("banter", row))
        self.assertEqual(app.tinted_keep_until("banter", _entry(tinted=False)), 0.0)
        # A bulletin dies with its stories whatever it rhymed.
        self.assertEqual(app.tinted_keep_until("news", _entry()), 0.0)
        # The stamp is one clock: a shelf row wrapping the entry reads the same value.
        wrapped = {"at": row["at"], "entry": row}
        self.assertEqual(app.tinted_keep_until("banter", wrapped), until)

    def test_the_crystal_off_stamps_nothing_but_an_old_stamp_stands(self):
        with mock.patch.object(app, "dialogue_tint_required", lambda: False):
            self.assertEqual(app.tinted_keep_until("banter", _entry()), 0.0)
            stamped = _entry(keep_until=time.time() + 100)
            self.assertTrue(app.tinted_kept("banter", stamped))

    def test_every_expiry_clock_honours_the_keep(self):
        old = _entry(at=time.time() - 30 * 3600, aired_at=time.time() - 25 * 3600, aired=1)
        self.assertGreater(app.stock_expires_at("banter", old), time.time() + 345600 - 3600 * 2)
        self.assertFalse(app.resort_may_drop("banter", old, set()))
        plain = _entry(at=time.time() - 30 * 3600, aired_at=time.time() - 25 * 3600, aired=1, tinted=False)
        self.assertTrue(app.resort_may_drop("banter", plain, set()))

    def test_a_kept_round_gets_the_evergreen_innings(self):
        self.assertEqual(app.row_innings("banter", _entry()), app.SHELF_REUSE_MOST_EVERGREEN)
        self.assertEqual(app.row_innings("banter", _entry(tinted=False)), app.SHELF_REUSE_MOST)
        aired_twice = _entry(aired_at=time.time() - 4 * 3600, aired=5)
        self.assertTrue(app.shelf_is_repeat("banter", aired_twice))
        self.assertFalse(app.shelf_is_repeat("banter", _entry(aired_at=time.time() - 4 * 3600, aired=5, tinted=False)))

    def test_the_larder_holds_the_repertoire_beside_its_stock(self):
        kept = [_entry(at=time.time() - i * 60, aired_at=time.time() - (i + 1) * 3600, aired=1) for i in range(6)]
        stock = [_entry(at=time.time() - i * 10, tinted=False) for i in range(5)]
        with mock.patch.object(app, "_LARDER", kept + stock), \
                mock.patch.object(app, "larder_cap", lambda: 3), \
                mock.patch.object(app, "TINTED_KEEP_ROWS", 4), \
                mock.patch.object(app, "dialogue_row_viable", lambda kind, row: True):
            app.larder_trim()
            left = list(app._LARDER)
            self.assertEqual(len(left), 7)
            self.assertEqual(sum(1 for e in left if app.tinted_kept("banter", e)), 4)
            # The newest three plain rounds stayed; the oldest-aired kept rounds went first.
            self.assertEqual([e for e in left if not e.get("script_tinted")], stock[-3:])
            self.assertEqual(sorted(e["aired_at"] for e in left if e.get("script_tinted")),
                             sorted(e["aired_at"] for e in kept[:4]))
            # A resting kept round does not count against the writing cap.
            self.assertEqual(app.larder_stock_count(), 3)

    def test_an_unheard_kept_round_is_the_last_to_go(self):
        unheard = _entry(at=time.time() - 3600)
        aired = [_entry(at=time.time() - i * 60, aired_at=time.time() - (i + 1) * 3600, aired=1) for i in range(3)]
        with mock.patch.object(app, "_LARDER", [unheard] + aired), \
                mock.patch.object(app, "larder_cap", lambda: 1), \
                mock.patch.object(app, "TINTED_KEEP_ROWS", 2):
            app.larder_trim()
            self.assertIn(unheard, app._LARDER)
            self.assertEqual(len(app._LARDER), 2)

    def test_the_repertoire_status_counts_what_is_kept(self):
        rows = [_entry(aired_at=time.time() - 600, aired=1), _entry()]
        with mock.patch.object(app, "_LARDER", rows), mock.patch.object(app, "_SHELF", {}), \
                mock.patch.object(app, "shelf_rest_now", lambda: 10800.0):
            got = app.repertoire_status()
        self.assertEqual(got["larder"]["kept"], 2)
        self.assertEqual(got["larder"]["aired"], 1)
        self.assertEqual(got["larder"]["unaired"], 1)
        self.assertEqual(got["larder"]["resting"], 1)
        self.assertEqual(got["keep_hours"], 96.0)


if __name__ == "__main__":
    unittest.main()
