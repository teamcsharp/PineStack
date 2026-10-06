"""[supercut-react] 2026-10-06: the booth answers the supercut, on the roulette."""
import ast
import asyncio
import unittest
from pathlib import Path

import system3
import system3_tables
import dynamic_segments_runtime

ROOT = Path(__file__).resolve().parents[1]


class TheRoad(unittest.TestCase):
    def test_the_table_the_road_and_the_structure_exist(self):
        self.assertIn("REACT", system3.FAMILIES)
        self.assertIn("supercut_react", system3.ROADS)
        ids = [t["id"] for t in system3_tables.DEFAULT_TABLES]
        self.assertIn("REACT1", ids)
        table = next(t for t in system3_tables.DEFAULT_TABLES if t["id"] == "REACT1")
        self.assertEqual(table["family"], "REACT")
        items = table["categories"][0]["items"]
        self.assertGreaterEqual(len(items), 6)
        self.assertIn("loves_it", [i["id"] for i in items])
        self.assertIn("hates_it", [i["id"] for i in items])
        self.assertIn("supercut_react", system3_tables.ROAD_IDS)
        st = system3_tables.DEFAULT_ROAD_STRUCTURES["supercut_react"]
        self.assertEqual(st["kind"], "legs")
        fams = {d["family"] for leg in st["legs"] for d in leg["draws"]}
        self.assertIn("REACT", fams)
        self.assertEqual([leg["place"] for leg in st["legs"]], ["open", "middle", "close"])

    def test_the_default_tables_are_what_a_stored_config_gains(self):
        ids = [t["id"] for t in system3_tables.default_tables()]
        self.assertIn("REACT1", ids)

    def test_the_stance_prints_on_the_running_order_row(self):
        turn = {"performance": {"emotion": "giddy", "intensity": 0.6},
                "directions": [{"family": "REACT", "text": "LOVES IT - out loud"}]}
        add = system3._leg_row_add(turn)
        self.assertIn("the stance: LOVES IT - out loud", add)


class TheRuntime(unittest.IsolatedAsyncioTestCase):
    def runtime(self, g):
        rt = dynamic_segments_runtime.DynamicSegments.__new__(dynamic_segments_runtime.DynamicSegments)
        rt.g = g
        rt.last = {}
        rt.log = lambda *a, **k: None
        rt.call = lambda name, *a, **k: (g[name](*a) if callable(g.get(name)) else k.get("default"))
        return rt

    def test_the_angle_names_what_the_supercut_showed_and_said(self):
        rt = self.runtime({})
        row = {"product": "the Pine Box FM lighthouse plate", "seconds": 45.2,
               "source_plan": {"clips": [{"role": "opening", "said": "this is Pine Box FM"},
                                         {"role": "sell", "name": "fluffy ducks.mp4"},
                                         {"role": "closing", "said": "every hour on the hour"}]}}
        angle = rt.react_angle(row)
        self.assertIn("45-second montage", angle)
        self.assertIn("opening: 'this is Pine Box FM'", angle)
        self.assertIn("sell: fluffy ducks.mp4", angle)
        self.assertIn("cut from 3 clip(s)", angle)

    async def test_a_prepared_supercut_banks_its_reaction_on_its_own_shelf(self):
        shelf = {}
        written = []
        saved = []

        async def banter(track, **kw):
            written.append(kw)
            kw["bank_to"].append({"script": "A: loved it\nB: hated it", "seconds": 0.0, "lines": 2})
            return ["x"]

        def shelf_put(kind, row):
            shelf.setdefault(kind, []).append(dict(row, at=1.0))

        g = {"_SHELF": shelf, "dj_banter": banter, "shelf_put": shelf_put, "_shelf_save": lambda: saved.append(1)}
        rt = self.runtime(g)
        ok = await rt.bank_reaction("occ-1", {"product": "plates", "seconds": 30, "source_plan": {"clips": []}})
        self.assertTrue(ok)
        self.assertEqual(written[0]["road"], "supercut_react")
        self.assertTrue(written[0]["bank"])
        self.assertEqual(len(shelf["supercut_react"]), 1)
        self.assertEqual(shelf["supercut_react"][0]["supercut_occurrence"], "occ-1")
        self.assertEqual(shelf["supercut_react"][0]["entry"]["prep_kind"], "supercut_react")
        self.assertEqual(saved, [1])
        # a second call for the same occurrence writes nothing more
        self.assertFalse(await rt.bank_reaction("occ-1", {}))
        self.assertEqual(len(written), 1)

    async def test_the_reaction_airs_from_the_shelf_else_live(self):
        row = {"entry": {"script": "A: hi", "prep_kind": "supercut_react"}, "supercut_occurrence": "occ-2"}
        aired = []
        live = []

        async def air(kind, track, rescue=False, pick=None, on_handoff=None, **kw):
            aired.append((kind, rescue, pick is row))
            if on_handoff:
                on_handoff()
            return ["said"]

        async def banter(track, **kw):
            live.append(kw)
            return ["live"]

        g = {"_SHELF": {"supercut_react": [row]}, "dialogue_row_ready": lambda k, r: True,
             "_ready_shelf_air": air, "dj_banter": banter}
        rt = self.runtime(g)
        self.assertTrue(await rt.react("occ-2", {"source_plan": {"clips": []}}))
        self.assertEqual(aired, [("supercut_react", True, True)])
        self.assertTrue(row.get("supercut_handed_off"))
        self.assertEqual(live, [])
        self.assertEqual(rt.last["occ-2"]["reaction"], "aired from the shelf")
        # nothing banked for this occurrence: written live, on the road
        self.assertTrue(await rt.react("occ-3", {"source_plan": {"clips": []}}))
        self.assertEqual(live[0]["road"], "supercut_react")
        self.assertNotIn("bank", live[0])


class WiredWhereItMatters(unittest.TestCase):
    def test_dispatch_answers_the_supercut_and_the_shelf_is_round_shaped(self):
        src = (ROOT / "dynamic_segments_runtime.py").read_text(encoding="utf-8")
        self.assertIn("await self.react(key, row, track)", src)
        self.assertIn("self.bank_reaction_later(occurrence, row)", src)
        app = (ROOT / "app.py").read_bytes().decode("utf-8")
        tree = ast.parse(app.replace("\r\n", "\n"))
        kinds = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUND_SHELF_KINDS" for t in node.targets):
                kinds = ast.literal_eval(node.value)
        self.assertIn("supercut_react", kinds or ())


if __name__ == "__main__":
    unittest.main()
