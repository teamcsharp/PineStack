"""[tree-heard] A segment's decision tree holds the rounds that WENT OUT in it.

Measured 09-29 (tools/script_watch.py): 30% of heard lines were filed under an
entry that was not on air when they were heard, because the register files a
block when it is written. The tree now decides by where a round was HEARD.

Run: PYTHONPATH=tests:. python3 -m unittest tests.test_tree_heard
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import script_decision_tree as sdt
from test_script_decision_tree import FakeStore, conversation


def conv(cid, created=1000.0):
    c = conversation()
    c["identity"] = dict(c["identity"], conversation_id=cid)
    c["created"] = created
    c["lines"] = [dict(x, line_id="%s-%s" % (cid, x["line_id"])) for x in c["lines"]]
    return c


def origin(folder, rows, full=True):
    path = Path(folder) / "system3_origin.sqlite3"
    db = sqlite3.connect(str(path))
    if full:
        db.execute("CREATE TABLE origin(line_id TEXT PRIMARY KEY, air_at REAL NOT NULL, verdict TEXT, "
                   "conversation_id TEXT, block INTEGER, ord INTEGER)")
        db.executemany("INSERT INTO origin VALUES(?,?,?,?,?,?)", rows)
    else:
        db.execute("CREATE TABLE origin(line_id TEXT PRIMARY KEY, air_at REAL NOT NULL, verdict TEXT)")
        db.executemany("INSERT INTO origin VALUES(?,?,?)", [r[:3] for r in rows])
    db.commit()
    db.close()
    return path


ENTRY = {"kind": "banter", "start": 1000.0, "deadline": 2000.0}


def record(*cids):
    return {"segment": {"id": "seg", "start": 1000.0, "ends": 2000.0},
            "conversations": [{"conversation_id": c, "first_block": 10 + i} for i, c in enumerate(cids)]}


class TreeHeard(unittest.TestCase):
    def test_a_round_written_here_that_went_out_later_leaves_the_tree(self):
        store = FakeStore({"late": conv("late"), "here": conv("here")}, record=record("late", "here"))
        with tempfile.TemporaryDirectory() as tmp:
            path = origin(tmp, [("late-L0", 2300.0, "traced", "late", 10, 0),
                                ("here-L0", 1500.0, "traced", "here", 11, 0)])
            got = sdt.collect(store, "seg", ENTRY, path, now=2500.0)
        self.assertEqual([r["conversation_id"] for r in got["rounds"]], ["here"])
        self.assertEqual([w["conversation_id"] for w in got["went_elsewhere"]], ["late"])
        self.assertIn("after", got["went_elsewhere"][0]["why"])
        self.assertEqual(got["window"], [1000.0, 2000.0])

    def test_a_round_heard_here_that_was_filed_elsewhere_joins_in_script_order(self):
        store = FakeStore({"mine": conv("mine"), "early": conv("early")}, record=record("mine"))
        with tempfile.TemporaryDirectory() as tmp:
            path = origin(tmp, [("mine-L0", 1600.0, "traced", "mine", 12, 0),
                                ("early-L0", 1100.0, "traced", "early", 9, 0)])
            got = sdt.collect(store, "seg", ENTRY, path, now=2500.0)
        self.assertEqual([r["conversation_id"] for r in got["rounds"]], ["early", "mine"])
        self.assertTrue(got["rounds"][0]["filed_elsewhere"])
        self.assertEqual(got["rounds"][0]["source"], "aired")
        self.assertEqual(got["rounds"][0]["elements"][0]["state"], "aired")

    def test_a_round_across_the_boundary_stays_and_one_not_heard_yet_stays(self):
        store = FakeStore({"across": conv("across"), "waiting": conv("waiting")}, record=record("across", "waiting"))
        with tempfile.TemporaryDirectory() as tmp:
            path = origin(tmp, [("across-L0", 1990.0, "traced", "across", 10, 0),
                                ("across-L1", 2010.0, "traced", "across", 10, 1)])
            got = sdt.collect(store, "seg", ENTRY, path, now=2500.0)
        self.assertEqual([r["conversation_id"] for r in got["rounds"]], ["across", "waiting"])
        self.assertEqual(got["went_elsewhere"], [])

    def test_an_origin_without_the_columns_answers_as_before(self):
        store = FakeStore({"late": conv("late")}, record=record("late"))
        with tempfile.TemporaryDirectory() as tmp:
            path = origin(tmp, [("late-L0", 2300.0, "traced", "late", 10, 0)], full=False)
            got = sdt.collect(store, "seg", ENTRY, path, now=2500.0)
        self.assertEqual([r["conversation_id"] for r in got["rounds"]], ["late"])
        self.assertEqual(got["went_elsewhere"], [])

    def test_no_window_no_change(self):
        store = FakeStore({"late": conv("late")}, record={"segment": {"id": "seg"},
                                                          "conversations": [{"conversation_id": "late"}]})
        with tempfile.TemporaryDirectory() as tmp:
            path = origin(tmp, [("late-L0", 2300.0, "traced", "late", 10, 0)])
            got = sdt.collect(store, "seg", None, path, now=2500.0)
        self.assertEqual([r["conversation_id"] for r in got["rounds"]], ["late"])
        self.assertIsNone(got["window"])


if __name__ == "__main__":
    unittest.main()
