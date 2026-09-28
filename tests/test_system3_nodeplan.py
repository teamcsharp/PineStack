"""[nodeplan] Every segment is a talk chapter (docs/NodePlan/nodeplan.md).

The road graphs derived from each road's structure, the single-voice roads'
chapters with the Rolodex intact, prompts that name what they answer, the
nested call ending on the real call-end wheel, the measured-pace fit, the
variant election, and the proof that dormant graphs move nothing."""
import copy
import json
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import conversation_graph
import system3
import system3_runtime
import system3_tables
from test_system3_runtime import FakeStation, ctx, settle


def _inputs(road, seats, **kw):
    names = {"A": "Host", "B": "Co-host", "D": "Third chair", "C": "Marge"}
    out = {"road": road, "at": 1.0, "seats": list(seats),
           "names": {s: names.get(s, s) for s in seats},
           "turns": kw.pop("turns", 12), "target_seconds": kw.pop("target_seconds", 0.0),
           "words_per_turn": 60.0,
           "subject": {"topic": kw.pop("topic", "the town budget")},
           "availability": {}, "speakerbox_rates": {}}
    out.update(kw)
    return out


def _memo_call_graph(config):
    """The memo chapter with the call path forced open, for the call tests."""
    graph = copy.deepcopy(config["structures"]["memo"]["graph"])
    graph["enabled"] = True
    for edge in graph["edges"]:
        if edge["from"] == "call_gate":
            edge["weight"] = 1 if edge["to"] == "call" else 0
        if edge["from"] == "reply_gate":
            edge["weight"] = 1 if edge["to"] == "reply_a" else 0
    return graph


class RoadChapters(unittest.TestCase):
    def test_every_road_derives_a_valid_dormant_chapter(self):
        for road, st in system3_tables.default_structures().items():
            if road == "caller":
                continue
            graph = conversation_graph.road_graph(road, st)
            self.assertEqual(conversation_graph.validate(graph), [], road)
            self.assertFalse(graph["enabled"], road)
            self.assertTrue(any(n["type"] == "end" for n in graph["nodes"]), road)
            self.assertTrue(any(n["type"] == "rebuttal" for n in graph["nodes"]), road)
            start = next(n for n in graph["nodes"] if n["id"] == "start")
            if road in system3_tables.LINE_ROADS:
                self.assertEqual(start["protocol_road"], road)
            else:
                # the diamonds hold a call chain that ends on the wheel
                legs = {n.get("call_leg") for n in graph["nodes"] if n["type"] == "call"}
                self.assertEqual(legs, {"open", "close"}, road)
                answers = [n for n in graph["nodes"] if n.get("respond_to")]
                self.assertEqual(len(answers), 4, road)   # 1:2 for EACH replier
                self.assertTrue(all(n["chance"] == .5 for n in answers), road)
            # the road's own words open the chapter
            act = (st["legs"][0].get("act") or "")[:80]
            self.assertIn(act[:40], start["prompt"], road)

    def test_default_config_carries_the_chapters_without_moving_the_hash(self):
        config = system3.default_config()
        old = system3.default_config()
        for road, item in old["structures"].items():
            item["graph"] = conversation_graph.protocol_graph(road)
        self.assertEqual(system3.config_hash(config), system3.config_hash(old))
        self.assertGreater(len(config["structures"]["memo"]["graph"]["nodes"]), 1)
        self.assertFalse(config["structures"]["memo"]["graph"]["enabled"])
        caller = config["structures"]["caller"]["graph"]["nodes"]
        self.assertEqual([n["type"] for n in caller], ["protocol"])

    def test_dormant_graphs_leave_the_legs_plan_untouched(self):
        config = system3.default_config()
        conv = system3.new_conversation(_inputs("memo", ["A", "B", "D"], turns=8),
                                        config, system3.normalise_settings({}), seed="np-dorm")
        system3.plan_legs(conv, config, road="memo")
        families = {e["family"] for e in conv["decision_events"]}
        self.assertNotIn("GRAPH", families)
        self.assertNotIn("VARIANT", families)
        self.assertTrue(all(t.get("leg") for t in conv["turns"]))


class LineRoadChapters(unittest.TestCase):
    def plan(self, seed="np-line"):
        config = system3.default_config()
        config["structures"]["station_id"]["graph"]["enabled"] = True
        inputs = _inputs("station_id", ["D", "A", "B"], turns=7, topic="station identification")
        inputs["names"]["D"] = "Sam"
        inputs["line_seat"] = "D"
        inputs["candidates"] = [{"id": "1", "text": "PINE 91.5, the only one", "weight": 1},
                                {"id": "2", "text": "You are locked to the Pine", "weight": 2}]
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
        system3.plan_graph(conv, config, config["structures"]["station_id"]["graph"],
                           inputs=inputs, road="station_id")
        return conv, config

    def test_the_line_keeps_its_voice_and_its_rolodex(self):
        conv, config = self.plan()
        first = conv["turns"][0]
        self.assertEqual(first["speaker"], "D")
        self.assertEqual(first.get("graph_type"), "initiator")
        # the LINE draw is still the recorded Rolodex, on the chapter's first turn
        self.assertTrue(any(d["family"] == "LINE" for d in first["decisions"]))
        self.assertIn(conv["line_choice"]["id"], ("1", "2"))
        # no raffle for the line's own voice: no initiator election event
        self.assertFalse(any(e["family"] == "GRAPH" and e["stages"][0]["stage"] == "initiator"
                             for e in conv["decision_events"]))

    def test_the_studio_answers_and_the_voice_rebuts(self):
        for seed in ("np-line", "np-line-2", "np-line-3"):
            conv, config = self.plan(seed)
            replies = [t for t in conv["turns"] if t.get("graph_type") == "reply"]
            self.assertTrue(replies, seed)
            self.assertTrue(all(t["speaker"] in ("A", "B") for t in replies), seed)
            self.assertIn("It answers what", replies[0]["protocol"])
            rebuttal = [t for t in conv["turns"] if t.get("graph_type") == "rebuttal"]
            self.assertTrue(rebuttal, seed)
            self.assertEqual(rebuttal[0]["speaker"], "D", seed)
            self.assertIn("The repliers were", rebuttal[0]["protocol"])
            self.assertTrue(all(t.get("performance") for t in conv["turns"]), seed)
            replayed = system3.replay(json.loads(json.dumps(conv)), config)
            self.assertTrue(replayed["ok"], (seed, replayed.get("why")))


class PromptsNameTheirTargets(unittest.TestCase):
    def test_replies_and_rebuttals_carry_names(self):
        config = system3.default_config()
        config["structure"]["graph"]["enabled"] = True
        named_reply = named_rebuttal = False
        for seed in ("np-name-1", "np-name-2", "np-name-3"):
            inputs = _inputs("banter", ["A", "B", "D"], turns=18, target_seconds=270.0)
            conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
            system3.plan_more(conv, config)
            for i, t in enumerate(conv["turns"]):
                if t.get("graph_node") in ("reply_a", "reply_b") and i:
                    prev = conv["turns"][i - 1]
                    if "It answers what %s just said." % prev["name"] in t["protocol"]:
                        named_reply = True
                if t.get("graph_type") == "rebuttal" and "The repliers were" in t["protocol"]:
                    named_rebuttal = True
        self.assertTrue(named_reply)
        self.assertTrue(named_rebuttal)


class NestedCalls(unittest.TestCase):
    def plan(self, seed="np-memo-3", **kw):
        config = system3.default_config()
        graph = _memo_call_graph(config)
        config["structures"]["memo"]["graph"] = graph
        inputs = _inputs("memo", ["A", "B", "D"], turns=14, target_seconds=240.0,
                         topic="the memo about the coffee machine", **kw)
        inputs["graph_caller_available"] = True
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
        system3.plan_graph(conv, config, graph, inputs=inputs, road="memo")
        return conv, config

    def test_the_call_joins_with_context_and_ends_on_the_wheel(self):
        conv, config = self.plan()
        calls = [t for t in conv["turns"] if t.get("graph_type") == "call"]
        self.assertTrue(calls)
        self.assertEqual(calls[0]["speaker"], "C")
        self.assertIn("joins a live discussion", calls[0]["protocol"])
        self.assertIn("coffee machine", calls[0]["protocol"])
        resolves = [e for e in conv["decision_events"] if e["family"] == "RESOLVE"]
        self.assertEqual(len(resolves), 1)   # one wheel per round, like a real call
        closes = [t for t in calls if (t.get("callend") or {}).get("role") == "resolution"]
        self.assertTrue(closes)
        self.assertIn("ends the way the wheel rolled it", closes[0]["protocol"])
        self.assertTrue(any(d["family"] == "RESOLVE" for d in closes[0]["decisions"]))
        self.assertTrue((conv.get("callend") or {}).get("says"))
        replayed = system3.replay(json.loads(json.dumps(conv)), config)
        self.assertTrue(replayed["ok"], replayed.get("why"))

    def test_without_a_caller_the_diamond_never_opens_the_line(self):
        config = system3.default_config()
        graph = _memo_call_graph(config)
        inputs = _inputs("memo", ["A", "B", "D"], turns=10)
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed="np-nocall")
        system3.plan_graph(conv, config, graph, inputs=inputs, road="memo")
        self.assertFalse([t for t in conv["turns"] if t.get("graph_type") == "call"])
        self.assertFalse([e for e in conv["decision_events"] if e["family"] == "RESOLVE"])


class RebuttalTarget(unittest.TestCase):
    def test_the_lead_comes_back_on_one_answer_spice_weighed(self):
        config = system3.default_config()
        graph = config["structures"]["memo"]["graph"]
        graph["enabled"] = True
        self.assertEqual(next(n for n in graph["nodes"] if n["type"] == "rebuttal").get("target"),
                         "rolled")
        seen = 0
        for i in range(6):
            inputs = _inputs("memo", ["A", "B", "D"], turns=12, target_seconds=200.0)
            conv = system3.new_conversation(inputs, config, system3.normalise_settings({}),
                                            seed="np-tgt-%d" % i)
            system3.plan_graph(conv, config, graph, inputs=inputs, road="memo")
            targeted = [t for t in conv["turns"]
                        if t.get("graph_type") == "rebuttal" and t.get("graph_target")]
            events = [e for e in conv["decision_events"]
                      if e["family"] == "GRAPH" and e["stages"][0]["stage"] == "target"]
            self.assertEqual(len(events), len(targeted))
            for turn, event in zip(targeted, events):
                seen += 1
                rows = event["stages"][0]["candidates"]
                self.assertTrue(all(r["weight"] >= r["base"] for r in rows))
                self.assertTrue(any("intensity" in " ".join(r.get("why") or []) for r in rows))
                self.assertIn("Take on", turn["protocol"])
                self.assertIn(turn["graph_target"], [r["id"] for r in rows])
                self.assertEqual(turn["graph_target"], event["selected"]["id"])
        self.assertGreater(seen, 0)

    def test_without_the_field_no_target_is_drawn(self):
        config = system3.default_config()
        config["structure"]["graph"]["enabled"] = True   # the live banter chapter has no `target`
        inputs = _inputs("banter", ["A", "B", "D"], turns=16, target_seconds=240.0)
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed="np-tgt-off")
        system3.plan_more(conv, config)
        self.assertFalse([e for e in conv["decision_events"]
                          if e["family"] == "GRAPH" and e["stages"][0]["stage"] == "target"])
        self.assertFalse([t for t in conv["turns"] if t.get("graph_target")])


class SplitBridge(unittest.TestCase):
    def test_the_split_switch_survives_normalize_and_split_node_reads_it(self):
        graph = system3.default_config()["structure"]["graph"]
        graph["nodes"][0]["splits"] = True
        got = conversation_graph.normalize(graph)
        start = next(n for n in got["nodes"] if n["id"] == "start")
        self.assertTrue(start.get("splits"))
        self.assertTrue(system3.split_node(start))
        # untouched nodes carry no key at all (stored hashes stand)
        self.assertNotIn("splits", got["nodes"][1])


class PaceFit(unittest.TestCase):
    def test_the_measured_pace_calibrates_and_the_fit_is_recorded(self):
        conv, _ = NestedCalls().plan(turn_seconds=9.0)
        profile = conv["graph_profile"]
        self.assertEqual(profile["pace_seconds_per_turn"], 9.0)
        self.assertGreaterEqual(profile["chapters"], 1)
        self.assertGreaterEqual(profile["replies"], 1)
        self.assertIn("closed", profile)
        self.assertIsNotNone(profile["fit"])
        self.assertGreater(profile["estimated_seconds"], 0)

    def test_without_a_measure_the_design_estimate_stands(self):
        conv, _ = NestedCalls().plan(seed="np-pace-0")
        profile = conv["graph_profile"]
        self.assertEqual(profile["pace_seconds_per_turn"], 0)
        # the last turn is still told to land the segment amiably
        self.assertTrue(conv["turns"] and ("amiable ending" in conv["turns"][-1]["protocol"]
                                           or conv["turns"][-1].get("graph_type") == "end"))


class RuntimeWiring(unittest.TestCase):
    def boot(self, roads):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings",
                             json={"mode": "active_selected_roads", "roads": roads,
                                   "test_seed": "np-rt"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def run_(self, coro):
        import asyncio
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_template_route_serves_every_roads_own_chapter(self):
        self.boot(["banter"])
        got = self.client.get("/api/system3/graph/template?road=memo",
                              headers={"Authorization": "Bearer k"}).json()["graph"]
        self.assertGreater(len(got["nodes"]), 10)
        self.assertFalse(got["enabled"])
        self.assertIn("MEMO", got["nodes"][0]["prompt"].upper()[:60])
        missing = self.client.get("/api/system3/graph/template?road=notaroad",
                                  headers={"Authorization": "Bearer k"})
        self.assertEqual(missing.status_code, 404)

    def test_the_fill_upgrades_protocol_macros_without_moving_the_hash(self):
        rt = self.boot(["banter"])
        config = copy.deepcopy(rt.config)
        for road, item in config["structures"].items():
            item["graph"] = conversation_graph.protocol_graph(road)
        before = system3.config_hash(config)
        rt.config = config
        self.assertTrue(rt.add_missing_conversation_graphs())
        settle()
        self.assertGreater(len(rt.config["structures"]["memo"]["graph"]["nodes"]), 1)
        self.assertFalse(rt.config["structures"]["memo"]["graph"]["enabled"])
        self.assertEqual([n["type"] for n in rt.config["structures"]["caller"]["graph"]["nodes"]],
                         ["protocol"])
        self.assertEqual(system3.config_hash(rt.config), before)
        self.assertFalse(rt.add_missing_conversation_graphs())   # once

    def test_a_variant_with_its_own_graph_is_elected_and_runs(self):
        rt = self.boot(["banter", "memo"])
        legs = system3_tables.default_structures()["memo"]["legs"]
        graph = conversation_graph.road_graph("memo", {"legs": legs})
        graph["enabled"] = True
        saved = self.client.put("/api/system3/structures/memo~v2",
                                json={"legs": legs, "graph": graph, "weight": 9999.0},
                                headers={"Authorization": "Bearer k"})
        self.assertEqual(saved.status_code, 200, saved.text)
        handle = self.run_(self.station["system3_direct_banter"](**ctx(
            road="memo", seats=["A", "B"], seed_text="", bank=False)))
        self.assertIsNotNone(handle)
        conv = handle.conv
        self.assertTrue(any(e["family"] == "VARIANT" for e in conv["decision_events"]))
        self.assertEqual((conv.get("graph_structure") or {}).get("road"), "memo")
        self.assertTrue(any(t.get("graph_node") for t in conv["turns"]))

    def test_a_single_voice_road_runs_its_chapter_when_enabled(self):
        rt = self.boot(["banter", "station_id"])
        legs = system3_tables.default_structures()["station_id"]["legs"]
        graph = conversation_graph.road_graph("station_id",
                                              system3_tables.default_structures()["station_id"])
        graph["enabled"] = True
        saved = self.client.put("/api/system3/structures/station_id",
                                json={"legs": legs, "graph": graph},
                                headers={"Authorization": "Bearer k"})
        self.assertEqual(saved.status_code, 200, saved.text)
        handle = self.run_(self.station["system3_direct_line"](
            road="station_id", who="drop", seat="D", name="Sam",
            dj={"host_name": "Caine", "cohost_name": "Skip"},
            candidates=[{"id": "a", "text": "PINE 91.5, the only one"},
                        {"id": "b", "text": "You are locked to the Pine"}],
            context="station identification"))
        self.assertIsNotNone(handle)
        conv = handle.conv
        self.assertGreater(len(conv["turns"]), 1)   # no one-line segments
        self.assertEqual(conv["turns"][0]["speaker"], "D")
        self.assertIn(handle.line, ("PINE 91.5, the only one", "You are locked to the Pine"))
        self.assertTrue(any(t["speaker"] in ("A", "B") for t in conv["turns"][1:]))
        self.assertTrue(any(d["family"] == "LINE" for d in conv["turns"][0]["decisions"]))

    def test_a_chapter_planned_round_reads_the_split_switch(self):
        rt = self.boot(["banter"])
        start = next(n for n in rt.config["structure"]["graph"]["nodes"] if n["id"] == "start")
        self.assertTrue(start.get("splits"))   # the defaults fill ticked the chapter's opening node
        inputs = _inputs("banter", ["A", "B", "D"], turns=8)
        conv = system3.new_conversation(inputs, rt.config, system3.normalise_settings({}), seed="np-split")
        system3.plan_more(conv, rt.config)
        self.assertTrue(any(t.get("graph_node") == "start" for t in conv["turns"]))
        rt._mark_split_nodes(conv, rt.config, "banter")
        opener = next(t for t in conv["turns"] if t.get("graph_node") == "start")
        self.assertTrue(opener.get("split_node"))

    def test_off_by_default_a_single_voice_road_is_the_line_it_was(self):
        rt = self.boot(["banter", "station_id"])
        handle = self.run_(self.station["system3_direct_line"](
            road="station_id", who="drop", seat="D", name="Sam",
            dj={"host_name": "Caine", "cohost_name": "Skip"},
            candidates=[{"id": "a", "text": "PINE 91.5, the only one"}],
            context="station identification"))
        self.assertIsNotNone(handle)
        self.assertEqual(len(handle.conv["turns"]), 1)
        self.assertEqual(handle.line, "PINE 91.5, the only one")


if __name__ == "__main__":
    unittest.main()
