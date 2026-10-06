"""[flow-pen] The held rounds go back as the shelves have room (2026-10-05).

Run from the repo root:  python3 tests/test_flow_pen_2026_10_05.py
The release and re-pen logic is exercised on stand-in shelves; the station is not imported.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def block(head: str, stop: str) -> str:
    start = APP.index(head)
    return APP[start:APP.index(stop, start + len(head))]


def pen_namespace(caps):
    """The pen's three functions, run against stand-in shelves."""
    ns = {"asyncio": asyncio, "copy": copy, "json": json, "time": time, "Any": object,
          "_LARDER": [], "_SHELF": {}, "_LARDER_MAX": caps.get("banter", 14),
          "_DIALOGUE_RECOVERY": [], "_DIALOGUE_RECOVERY_LOCK": threading.RLock(),
          "_UNHEARD_MEMO": {}, "_INVENTORY_PLAN": {}, "_COMMITS": {},
          "shelf_cap": lambda kind: caps.get(kind, 6),
          "row_unaired": lambda row: not (row.get("aired_at") or row.get("aired")),
          "dialogue_entry": lambda row: row.get("entry") if isinstance(row.get("entry"), dict)
          else (row if "script" in row else None),
          "_larder_save": lambda: None, "_pantry_save": lambda force=False: None,
          "_dialogue_recovery_save": lambda: None, "pipeline_log": lambda *a, **k: None}
    src = block("def _flow_shelf_of(", "\nasync def dialogue_recovery_release(")
    exec(compile(src, "pen", "exec"), ns)
    return types.SimpleNamespace(**ns), ns


def released(cid, **extra):
    return {"script": "A: hello\nB: hi", "prep_kind": "x", "system3": {"conversation_id": cid},
            "handoff_flow": {"why": "released from the recovery queue"}, **extra}


class PenTest(unittest.TestCase):
    def test_room_is_the_cap_less_the_unaired_rows(self):
        pen, ns = pen_namespace({"caller": 4, "banter": 3})
        ns["_SHELF"]["caller"] = [{"entry": released("c%d" % i)} for i in range(3)] + [{"entry": released("old", aired_at=5.0)}]
        self.assertEqual(pen._flow_release_room("caller"), 1)           # the aired row takes no room
        ns["_LARDER"].extend(released("b%d" % i) for i in range(5))
        self.assertEqual(pen._flow_release_room("banter"), 0)
        self.assertEqual(pen._flow_release_room("news"), 6)             # an empty shelf has its whole cap

    def test_repen_moves_only_released_rows_past_the_cap_and_deletes_nothing(self):
        pen, ns = pen_namespace({"caller": 2, "banter": 2})
        own = {"entry": {"script": "A: mine\nB: yes", "system3": {"conversation_id": "own"}}, "kept": True}
        rows = [own] + [{"entry": released("c%d" % i), "seconds": 0.0, "n": i} for i in range(5)]
        ns["_SHELF"]["caller"] = rows
        ns["_LARDER"].extend(released("b%d" % i) for i in range(4))
        got = asyncio.run(pen.dialogue_recovery_repen())
        self.assertEqual(got["by_kind"], {"banter": 2, "caller": 4})
        self.assertEqual([r.get("n") for r in ns["_SHELF"]["caller"]], [None, 0])     # the station's own row and the earliest
        self.assertEqual(len(ns["_LARDER"]), 2)
        ids = [it["id"] for it in ns["_DIALOGUE_RECOVERY"]]
        self.assertEqual(sorted(ids), ["b2", "b3", "c1", "c2", "c3", "c4"])           # every moved row is in the pen
        self.assertEqual([i for i in ids if i[0] == "b"], ["b2", "b3"])               # each kind in the order it was released
        self.assertEqual([i for i in ids if i[0] == "c"], ["c1", "c2", "c3", "c4"])
        self.assertTrue(all(it["entry"]["dialogue_recovery_pending"] for it in ns["_DIALOGUE_RECOVERY"]))
        caller = next(it for it in ns["_DIALOGUE_RECOVERY"] if it["id"] == "c3")
        self.assertEqual(caller["shelf_row"], {"seconds": 0.0, "n": 3})                # its wrapper came with it
        self.assertEqual(asyncio.run(pen.dialogue_recovery_repen())["moved"], 0)       # a second pass has nothing to do

    def test_repen_leaves_a_row_that_is_being_recorded(self):
        pen, ns = pen_namespace({"caller": 1})
        ns["_SHELF"]["caller"] = [{"entry": released("c0")}, {"entry": released("c1", preparing=True)},
                                  {"entry": released("c2")}]
        asyncio.run(pen.dialogue_recovery_repen())
        # the cap is one row, and the row a recording holds is that row: it is never pulled from under a take
        self.assertEqual([r["entry"]["system3"]["conversation_id"] for r in ns["_SHELF"]["caller"]], ["c1"])
        self.assertEqual(sorted(it["id"] for it in ns["_DIALOGUE_RECOVERY"]), ["c0", "c2"])


class SourceTest(unittest.TestCase):
    def test_release_takes_only_what_fits(self):
        release = block("async def dialogue_recovery_release(", "\nasync def flow_release_clock(")
        room = release.index("_flow_release_room(_kind)")
        self.assertLess(room, release.index('s3_flow("recovery_release"'))       # nothing is rolled for rows with no room
        self.assertIn('out["waiting"] = len(items) - len(_fits)', release)

    def test_the_clock_brings_the_shelves_back_once(self):
        clock = block("async def flow_release_clock(", "\ndef tint_recovery_rows(")
        self.assertEqual(clock.count("dialogue_recovery_repen()"), 1)
        self.assertLess(clock.index("dialogue_recovery_repen()"), clock.index("while True:"))

    def test_guests_are_read_on_change_and_a_write_is_seen(self):
        read = block("def read_guests(", "\ndef write_guests(")
        self.assertIn("st.st_mtime_ns, st.st_size", read)
        self.assertLess(read.index("return list(memo[\"rows\"])"), read.index("with _GUESTS_LOCK:"))   # the memo answers before the lock
        write = block("def write_guests(", "\ndef guest_persona(")
        self.assertIn("_GUESTS_MEMO.update(at=0.0, sig=None)", write)

    def test_guests_memo_behaves(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guests.json"
            path.write_text(json.dumps([{"id": "a"}]))
            ns = {"json": json, "time": time, "Any": object, "GUESTS_PATH": path, "_GUESTS_LOCK": threading.RLock()}
            src = block("_GUESTS_MEMO: dict[str, Any] = {", "\ndef guest_persona(")
            exec(compile(src, "guests", "exec"), ns)
            self.assertEqual(ns["read_guests"](), [{"id": "a"}])
            path.write_text(json.dumps([{"id": "a"}, {"id": "bb"}]))
            self.assertEqual(len(ns["read_guests"]()), 1)                  # inside the two seconds: the memo
            ns["_GUESTS_MEMO"]["at"] = 0.0
            self.assertEqual(len(ns["read_guests"]()), 2)                  # looked again: the file changed
            ns["write_guests"]([{"id": "z"}])
            self.assertEqual(ns["read_guests"](), [{"id": "z"}])           # a write is seen at once
            got = ns["read_guests"]()
            got.append({"id": "mine"})
            self.assertEqual(len(ns["read_guests"]()), 1)                  # a caller's list is its own


if __name__ == "__main__":
    unittest.main()
