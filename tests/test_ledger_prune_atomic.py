"""[ledger-prune-atomic] The script ledger is never seen half written.

09-29: the ledger crossed 8 MB and the hourly prune re-wrote all 8.5 MB in place
(truncate, then write) while keeping every row; a watcher tailing it lost nine
rows of one block. Nothing to drop now rewrites nothing, and a real prune
replaces the file whole.

Run (never against the live data): SPARK_AGENT_DATA_DIR=/tmp/x/data \
    PYTHONPATH=tests:. python3 -m unittest tests.test_ledger_prune_atomic
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app


def row(block, ord_, at):
    return {"block": block, "ord": ord_, "at": at, "line_id": "L%d-%d" % (block, ord_), "text": "x"}


class PruneTests(unittest.TestCase):
    def prune(self, rows):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "script_ledger.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        before = path.read_bytes()
        written, replaced = [], []
        real_write, real_replace = Path.write_text, os.replace

        def spy_write(self_, *a, **k):
            written.append(str(self_))
            return real_write(self_, *a, **k)

        def spy_replace(src, dst):
            replaced.append((str(src), str(dst)))
            return real_replace(src, dst)

        memo = {"at": 0.0, "rows": []}
        with mock.patch.object(app, "SCRIPT_LEDGER_PATH", path), \
                mock.patch.object(app, "_SCRIPT_LEDGER_MEMO", memo), \
                mock.patch.object(app, "_SCRIPT_LEDGER_PRUNED", [0.0]), \
                mock.patch.object(Path, "write_text", spy_write), \
                mock.patch.object(app.os, "replace", spy_replace):
            app._script_ledger_prune()
        return path, before, written, replaced, memo

    def test_nothing_to_drop_rewrites_nothing(self):
        now = time.time()
        path, before, written, replaced, memo = self.prune([row(2, 0, now), row(1, 0, now - 60)])
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(str(path), written, "the ledger itself is never truncated and re-written")
        self.assertEqual(replaced, [])
        self.assertEqual([(r["block"], r["ord"]) for r in memo["rows"]], [(1, 0), (2, 0)], "memo still refreshed")

    def test_a_real_prune_replaces_the_file_whole(self):
        now = time.time()
        old = now - app.SCRIPT_LEDGER_KEEP_S - 100
        path, _before, written, replaced, memo = self.prune([row(1, 0, old), row(2, 0, now), row(2, 1, now)])
        self.assertNotIn(str(path), written)
        self.assertEqual(len(replaced), 1)
        self.assertEqual(replaced[0][1], str(path))
        kept = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        self.assertEqual([(r["block"], r["ord"]) for r in kept], [(2, 0), (2, 1)])
        self.assertFalse(Path(replaced[0][0]).exists(), "no temporary file is left behind")
        self.assertEqual(len(memo["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
