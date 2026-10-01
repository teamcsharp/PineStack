"""[flowchart] every conversation as a conditional flowchart, by its hex key."""
import unittest

import flow_chart as fc
import system3

from test_system3_callarc_2026_10_01 import plan, cfg_with, MEMO


class Build(unittest.TestCase):
    def setUp(self):
        self.conv = plan("flow1", cfg_with(first=1.0), memo=MEMO)
        self.conv["lines"] = [{"line_id": "3c4782ab", "turn_id": self.conv["turns"][0]["turn_id"],
                               "who": "dj", "text": "The request line is ringing, you're live.", "at": 1790000000.0}]
        self.flow = fc.build_flow(self.conv, [{"n": 1, "stage": "banked", "text": "A: ...", "seconds": 90.0,
                                               "at": 1790000001.0}], now_turn_id=self.conv["turns"][0]["turn_id"])

    def test_the_graph_runs_start_to_end_with_every_turn_and_every_draw(self):
        nodes = self.flow["nodes"]
        self.assertEqual(nodes[0]["type"], "start")
        self.assertEqual(nodes[-1]["type"], "end")
        self.assertEqual(self.flow["key"], self.conv["identity"]["conversation_id"])
        self.assertEqual(sum(1 for n in nodes if n["type"] == "turn"), len(self.conv["turns"]))
        decided = sum(1 for e in self.conv["decision_events"] if e.get("stages"))
        self.assertEqual(sum(1 for n in nodes if n["type"] == "decision"), decided)
        self.assertEqual(len(self.flow["edges"]), len(nodes) - 1)
        self.assertEqual(len({n["id"] for n in nodes}), len(nodes))       # every node keyed once

    def test_a_turns_draws_come_just_before_it(self):
        nodes = self.flow["nodes"]
        for i, n in enumerate(nodes):
            if n["type"] == "decision" and isinstance(n.get("turn_index"), int) and n["turn_index"] >= 0:
                nxt = next(m for m in nodes[i + 1:] if m["type"] == "turn")
                self.assertEqual(nxt["index"], n["turn_index"])

    def test_a_decision_names_its_winner_its_losers_and_its_die(self):
        arc = next(n for n in self.flow["nodes"] if n["type"] == "decision" and n["family"] == "CALLARC")
        self.assertTrue(arc["winner"]["label"])
        self.assertTrue(arc["losers"])
        self.assertIsNotNone(arc["dice"])
        back = [n for n in self.flow["nodes"] if n["type"] == "decision" and n["family"] == "CALLSHIFT"
                and n["kind"].startswith("back_")]
        self.assertTrue(back)
        self.assertIsNotNone(back[0]["odds"])

    def test_the_line_on_air_and_its_code(self):
        first = next(n for n in self.flow["nodes"] if n["type"] == "turn")
        self.assertTrue(first["now"])
        self.assertEqual(first["codes"], ["3c4782ab"])
        self.assertIn("ringing", first["said"])
        self.assertEqual(self.flow["counts"]["aired"], 1)
        self.assertEqual(self.flow["nodes"][-1]["label"], "aired")
        self.assertTrue(any(n["type"] == "step" and n["label"] == "banked" for n in self.flow["nodes"]))

    def test_the_report_reads_as_lines(self):
        text = fc.report_text(self.flow)
        self.assertIn("FLOW %s" % self.flow["key"], text)
        self.assertIn("◆ CALLARC", text)
        self.assertIn("codes=3c4782ab", text)
        self.assertTrue(text.strip().endswith("END  aired"))


class Route(unittest.TestCase):
    def test_the_routes_are_installed(self):
        import app
        paths = {getattr(r, "path", "") for r in app.app.routes}
        for p in ("/api/flow/now", "/api/flow/recent", "/api/flow/{key}"):
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main()
