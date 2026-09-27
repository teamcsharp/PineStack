"""[s3-line-link] A spoken line is linked to its node at speak time; the
ledger's own row is never overwritten; a withdrawn row carries its stamp.
Pure: a fake runtime and store, and the edits read out of the files."""
import importlib.util
import threading
import unittest
from pathlib import Path

import system3_runtime

ROOT = Path(__file__).resolve().parents[1]


class _Store:
    def __init__(self):
        self.rows = {}

    def line(self, line_id):
        return self.rows.get(line_id)

    def add_lines(self, rows):
        for r in rows:
            self.rows[r["line_id"]] = dict(r)


class _Fake:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = 0
        self.metrics = {"writes_dropped": 0}
        self.store = _Store()
        self.failed = []

    def fail(self, where, exc):
        self.failed.append((where, exc))


def _drain():
    system3_runtime._STORE_POOL.submit(lambda: None).result(timeout=10)


class LinkSpoken(unittest.TestCase):
    def test_a_stamped_line_is_linked_and_a_ledger_row_is_never_overwritten(self):
        rt = _Fake()
        link = system3_runtime.System3Runtime.link_spoken
        link(rt, "L1", {"conversation_id": "c1", "turn_id": "c1:t00"}, "dj", "Coming up next")
        _drain()
        got = rt.store.line("L1")
        self.assertEqual((got["conversation_id"], got["turn_id"], got["block"], got["who"]), ("c1", "c1:t00", None, "dj"))
        rt.store.rows["L2"] = {"line_id": "L2", "conversation_id": "c9", "turn_id": "c9:t03", "block": 42}
        link(rt, "L2", {"conversation_id": "c1", "turn_id": "c1:t00"}, "dj", "x")
        _drain()
        self.assertEqual(rt.store.line("L2")["block"], 42, "the ledger's row wins")
        for stamp in (None, {}, {"turn_id": "x"}, "c1"):
            link(rt, "L3", stamp)
        link(rt, "", {"conversation_id": "c1"})
        _drain()
        self.assertIsNone(rt.store.line("L3"))
        self.assertEqual((rt.pending, rt.failed), (0, []))
        self.assertEqual(rt.metrics["lines_linked_live"], 2)

    def test_a_full_backlog_drops_and_counts(self):
        rt = _Fake()
        rt.pending = system3_runtime.WRITE_BACKLOG
        system3_runtime.System3Runtime.link_spoken(rt, "L1", {"conversation_id": "c1"})
        _drain()
        self.assertEqual((rt.metrics["writes_dropped"], rt.store.line("L1")), (1, None))


class Wiring(unittest.TestCase):
    def test_every_edit_is_in_both_files(self):
        spec = importlib.util.spec_from_file_location("s3_line_link_patch", ROOT / "tools" / "s3_line_link_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for fname in mod.FILES:
            text = (ROOT / fname).read_bytes().decode("utf-8").replace("\r\n", "\n")
            applied, missing = mod.check(text, fname)
            self.assertEqual(missing, [], fname)
            self.assertEqual(applied, len(mod.FILES[fname]), fname)
        app = (ROOT / "app.py").read_bytes().decode("utf-8")
        self.assertIn('entry["system3"] = dict(system3)', app)
        self.assertEqual(app.count("_bound_why, system3=system3)") + app.count("_bound_why, clip, system3=system3)"), 2)


if __name__ == "__main__":
    unittest.main()
