"""[bank-first-2] 2026-10-06: the larder transport hands its round over as a READY round.

Measured: the sweep's first walk after the 13:34 restart put a banter round on the air
(its task sat in _banter_air -> speak_turns -> _paged_settle) and still counted 0 airings:
speak_turns credits on_handoff only when ready_takes is given.
"""
import ast
import asyncio
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import app

SOURCE = Path(app.__file__).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("no top-level function %s" % name)


def _calls(node):
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


class TheReadyRound(unittest.TestCase):
    def test_the_larder_transport_asks_for_the_takes_and_holds_the_entry_busy(self):
        node = _function("larder_round_air")
        self.assertIn("_ready_round_takes", _calls(node))
        src = ast.get_source_segment(SOURCE, node)
        self.assertIn("ready_takes=_takes or None", src)
        self.assertIn("_READY_SHELF_BUSY.add(id(entry))", src)
        self.assertIn("_READY_SHELF_BUSY.discard(id(entry))", src)

    def test_the_round_airs_with_its_takes_and_the_entry_is_released(self):
        now = time.time()
        entry = {"at": now - 900, "script": "A: one\nB: two", "prep_kind": "banter"}
        seen: list[Any] = []
        busy: set = set()

        async def fake_air(e, track, ready_takes=None, on_handoff=None, **kw):
            seen.append((ready_takes, id(e) in busy))
            if callable(on_handoff):
                on_handoff()
            return ["one", "two"]

        handed: list[int] = []
        with mock.patch.object(app, "_LARDER", [entry]), \
                mock.patch.object(app, "_READY_SHELF_BUSY", busy), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True), \
                mock.patch.object(app, "_ready_round_takes", lambda kind, row: [{"i": 0, "key": "k", "text": "one", "voice": "v", "who": "dj", "seconds": 1.0}]), \
                mock.patch.object(app, "larder_reair_gate", lambda at: (at, None)), \
                mock.patch.object(app, "stock_used_by", lambda: {}), \
                mock.patch.object(app, "stock_expires_at", lambda kind, row: now + 86400), \
                mock.patch.object(app, "repeat_safe", lambda kind, row: True), \
                mock.patch.object(app, "row_innings", lambda kind, row: 3), \
                mock.patch.object(app, "_larder_save", lambda: None), \
                mock.patch.object(app, "gap_round_flag", lambda flag: None), \
                mock.patch.object(app, "pipeline_log", lambda *a, **k: None), \
                mock.patch.object(app, "_banter_air", fake_air):
            said = asyncio.new_event_loop().run_until_complete(app.larder_round_air(entry, None, on_handoff=lambda: handed.append(1)))
        self.assertEqual(said, ["one", "two"])
        self.assertEqual(len(seen[0][0]), 1, "the recorded takes ride along")
        self.assertTrue(seen[0][1], "the entry is busy while it airs")
        self.assertNotIn(id(entry), busy, "and released after")
        self.assertEqual(handed, [1])


if __name__ == "__main__":
    unittest.main()
