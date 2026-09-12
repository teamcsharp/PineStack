from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from sfx_cadence import SfxCadence, due_after


class SfxCadenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'cadence.sqlite3'
        self.ledger = SfxCadence(self.path)

    def test_plan_every_other_unit_without_crediting_a_render(self):
        self.assertEqual([due_after(i, 2) for i in range(6)], [False, True, False, True, False, True])
        self.assertEqual(self.ledger.state(), {'heard_units': 0, 'heard_samples': 0})
        self.assertFalse(due_after(1, 0))

    def test_page_box_retry_and_restart_only_credit_each_audible_row_once(self):
        rows = [{'id': 'line1', 'units': 1}, {'id': 'line2', 'units': 1}, {'id': 'sample', 'sample': 'sample-a'}]
        self.assertEqual(len(self.ledger.record(rows)), 3)
        self.assertEqual(self.ledger.record(rows), [])
        restored = SfxCadence(self.path)
        self.assertEqual(restored.state(), {'heard_units': 2, 'heard_samples': 1})
        self.assertEqual(restored.record(rows), [])

    def test_partial_failure_carries_the_unpaired_success_forward(self):
        self.ledger.record([{'id': 'first-heard', 'units': 1}])
        self.assertTrue(due_after(self.ledger.state()['heard_units'], 2))

    def test_concurrent_receipts_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.ledger.record([{'id': 'same', 'units': 1}]), range(12)))
        self.assertEqual(self.ledger.state()['heard_units'], 1)

    def test_invalid_batch_does_not_partly_credit(self):
        with self.assertRaises(ValueError):
            self.ledger.record([{'id': 'valid', 'units': 1}, {'id': '', 'units': 1}])
        self.assertEqual(self.ledger.state()['heard_units'], 0)


if __name__ == '__main__':
    unittest.main()
