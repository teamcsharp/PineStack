"""[book-nodes-3] 2026-10-06: the welcome and the sign-off are wheels; a part with a take gone is re-made at the door.

The 14:45 window: the opening's welcome was the same sentence as three earlier openings, one pantry key, spent
when they aired; the part was refused for one missing take and the window went out as music.
"""
import asyncio
import re
import tempfile
import time
import unittest

import dynamic_segments_runtime as dsr
import system3
import system3_tables
from test_system3 import inputs, settings


class TheWheels(unittest.TestCase):
    def test_the_two_families_their_tables_and_the_legs_that_roll_them(self):
        for fam in ("WELCOME", "SIGNOFF"):
            self.assertIn(fam, system3.FAMILIES)
        ids = {t["id"]: t for t in system3_tables.DEFAULT_TABLES}
        self.assertEqual(ids["BK4"]["family"], "WELCOME")
        self.assertEqual(ids["BK5"]["family"], "SIGNOFF")
        for table in ("BK4", "BK5"):
            self.assertGreaterEqual(len(ids[table]["categories"][0]["items"]), 10, table + " is a wheel, not a coin")
        opening = system3_tables.DEFAULT_ROAD_STRUCTURES["book_open"]
        legs = {leg["id"]: leg for leg in opening["legs"]}
        for leg_id in ("hello_a", "hello_b"):
            self.assertTrue(any(d["family"] == "WELCOME" for d in legs[leg_id]["draws"]), leg_id + " rolls the welcome")
        self.assertIn("never the station's stock welcome sentence", legs["hello_a"]["act"])
        self.assertIn("{stationname}", legs["hello_a"]["act"])
        self.assertIn("{book}", legs["hello_a"]["act"])
        close = {leg["id"]: leg for leg in system3_tables.DEFAULT_ROAD_STRUCTURES["book_close"]["legs"]}
        self.assertTrue(any(d["family"] == "SIGNOFF" for d in close["signoff"]["draws"]), "the sign-off rolls its shape")
        self.assertTrue(any(d.get("closes") for d in close["signoff"]["draws"]), "and still closes")
        for road in ("book_open", "book_close"):
            self.assertEqual(system3_tables.validate_structure(road, system3_tables.DEFAULT_ROAD_STRUCTURES[road]), [])

    def test_an_opening_is_planned_with_a_welcome_shape_on_both_hosts(self):
        cfg = system3.default_config()
        conv = system3.new_conversation(inputs(road="book_open", seats=["A", "B"], turns=5), cfg,
                                        settings(test_seed="book-open-1"), conversation_id="c-book-open-1")
        system3.plan_legs(conv, cfg, conv["inputs"], "book_open")
        legs = [t["leg"] for t in conv["turns"]]
        self.assertEqual(legs[:2], ["hello_a", "hello_b"])
        for t in conv["turns"][:2]:
            self.assertTrue(any(d["family"] == "WELCOME" for d in t["decisions"]), t["leg"] + " draws WELCOME")
        shapes = set()
        for seed in range(12):
            c = system3.new_conversation(inputs(road="book_open", seats=["A", "B"], turns=5), cfg,
                                         settings(test_seed="book-open-%d" % seed), conversation_id="c-bo-%d" % seed)
            system3.plan_legs(c, cfg, c["inputs"], "book_open")
            d = next(d for d in c["turns"][0]["decisions"] if d["family"] == "WELCOME")
            shapes.add(str(d.get("item") or d.get("item_id") or d.get("text") or d))
        self.assertGreaterEqual(len(shapes), 4, "twelve seeds roll more than a few welcome shapes: %r" % shapes)

    def test_the_running_order_row_prints_the_welcome_and_the_sign_off(self):
        src = open(system3.__file__, encoding="utf-8").read()
        self.assertIn('add += "; the welcome: " + welcome[-1]', src)
        self.assertIn('add += "; the sign-off: " + signoff[-1]', src)


def _turns(script, *a, **k):
    out = []
    for m in re.finditer(r"(?:^|\n)\s*([ABCDE]):\s*(.*?)(?=(?:\n\s*[ABCDE]:)|\Z)", str(script or ""), re.S):
        out.append((m.group(1), " ".join(m.group(2).split())))
    return out


def _part(occurrence, phase, script, recorded=True, at=None):
    return {"at": at or time.time(), "script": script, "dynamic_kind": "book_time", "dynamic_occurrence": occurrence,
            "book_phase": phase, "book_cast": {"A": "Dill", "B": "Skip"}, "book_station": "Pine Box FM",
            "book_source": {"title": "A History of Brands"}, "recorded": recorded}


class TheDoorRemakes(unittest.TestCase):
    def _runtime(self, larder, radio, remade):
        g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
             "_LARDER": larder, "_RADIO": radio}

        async def larder_prepare(row):
            remade.append(row["book_phase"])
            row["recorded"] = True            # the kitchen rendered the missing take
            return True
        g["larder_prepare"] = larder_prepare
        rt = dsr.DynamicSegments(g)
        rt.original["dialogue_row_ready"] = lambda kind, row: bool(row.get("recorded"))
        return rt

    def _radio(self, started):
        return {"sched_slot": {"kind": "book_time", "id": "dynamic-book_time-900000", "minutes": 6.5},
                "sched_pos": {"started": started, "occurrence": ""}}

    def _run(self, rt):
        picks = []

        async def door(kind, track, pick=None, on_handoff=None, **kw):
            picks.append(pick)
            if callable(on_handoff):
                on_handoff()
            return ["said"]
        rt.g["_ready_shelf_air"] = door
        got = asyncio.new_event_loop().run_until_complete(rt.dispatch("book_time"))
        return got, picks

    def test_an_opening_missing_a_take_is_remade_then_aired(self):
        key = "dynamic-book_time-900000@1000"
        remade = []
        larder = [_part(key, "discussion", "A: later", recorded=True, at=3), _part(key, "opening", "A: Welcome to Book Time", recorded=False, at=2)]
        rt = self._runtime(larder, self._radio(1000), remade)
        got, picks = self._run(rt)
        self.assertEqual(remade, ["opening"], "the kitchen is asked for the part the window wants next, once")
        self.assertTrue(got)
        self.assertEqual(picks[0]["book_phase"], "opening", "and the re-made opening goes out first")

    def test_a_remake_that_runs_long_leaves_the_door_its_choice(self):
        key = "dynamic-book_time-900000@1000"
        larder = [_part(key, "opening", "A: Welcome", recorded=False, at=2), _part(key, "discussion", "A: later", recorded=True, at=3)]
        rt = self._runtime(larder, self._radio(1000), [])

        async def slow(row):
            await asyncio.sleep(5)
        rt.g["larder_prepare"] = slow
        rt.BOOK_REMAKE_SECONDS = 0.05
        got, picks = self._run(rt)
        self.assertFalse(got, "no opening could be made ready, and an episode opens with its welcome")
        self.assertEqual(picks, [])


if __name__ == "__main__":
    unittest.main()
