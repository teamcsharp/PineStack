"""[voice-actor] "Call in now" through System 3: the graph and runtime halves.

Runs against the PATCHED system3.py / system3_runtime.py that verify_tools.py
writes to tests/patched/, beside the live snapshot's other modules and the
station's own runtime test fakes (tests/test_system3_runtime.py FakeStation).

  python test_voice_actor_s3.py <snapshot_dir>
"""
import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAP = Path(sys.argv.pop(1) if len(sys.argv) > 1 else HERE.parent / "live2").resolve()
sys.path[:0] = [str(HERE / "patched"), str(SNAP), str(SNAP / "tests")]

import system3            # noqa: E402  (the patched one)
import system3_runtime    # noqa: E402
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from test_system3_runtime import FakeStation, ctx, settle   # noqa: E402

assert "voice_actor_diamond" in dir(system3), "tests/patched/system3.py is not the patched copy"
assert hasattr(system3_runtime.System3Runtime, "_voice_actor_arm"), "system3_runtime not patched"

IJ = {"id": "d_test000001", "caller_id": "517b3829", "name": "Crochet Ashley",
      "persona": "Crochet Master. Fastest crochet artist on the planet",
      "goal": "Yard more yarn", "topic": "the yarn shortage downtown", "voice_id": "vl_e0babc72",
      "segment_id": ""}


def _inputs(road, seats, **kw):
    names = {"A": "Host", "B": "Co-host", "D": "Third chair", "C": "Caller"}
    out = {"road": road, "at": 1.0, "seats": list(seats),
           "names": {s: names.get(s, s) for s in seats},
           "turns": kw.pop("turns", 12), "target_seconds": kw.pop("target_seconds", 0.0),
           "words_per_turn": 60.0, "subject": {"topic": kw.pop("topic", "the town budget")},
           "availability": {}, "speakerbox_rates": {}}
    out.update(kw)
    return out


def _graph(config, road="memo"):
    """The road's chapter, enabled, the reply gate walked towards the call
    diamond - the call gate itself keeps the graph's own .12 / .88."""
    graph = copy.deepcopy(config["structures"][road]["graph"])
    graph["enabled"] = True
    for edge in graph["edges"]:
        if edge["from"] == "reply_gate":
            edge["weight"] = 1 if edge["to"] == "reply_a" else 0
    return graph


def _armed_inputs(road, seats, **kw):
    inputs = _inputs(road, seats, **kw)
    inputs["call_interjection"] = dict(IJ)
    inputs["graph_caller_available"] = True
    inputs["names"]["C"] = IJ["name"]
    return inputs


class GraphDiamond(unittest.TestCase):
    def plan(self, seed, armed=True, road="memo"):
        config = system3.default_config()
        graph = _graph(config, road)
        config["structures"][road]["graph"] = graph        # replay reads the graph from the config
        inputs = (_armed_inputs if armed else _inputs)(road, ["A", "B", "D"], turns=12)
        conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
        system3.plan_graph(conv, config, graph, inputs=inputs, road=road)
        return conv, config, graph

    def call_gate_events(self, conv, graph):
        by_id = {n["id"]: n for n in graph["nodes"]}
        gates = {n["id"] for n in graph["nodes"] if n["type"] == "decision"
                 and any(by_id[e["to"]]["type"] == "call" for e in graph["edges"] if e["from"] == n["id"])}
        return [e for e in conv["decision_events"] if e["family"] == "GRAPH"
                and e["stages"][0]["stage"] == "branch" and (e.get("meta") or {}).get("node") in gates]

    def test_the_first_diamond_takes_the_dispatched_call_on_a_recorded_draw(self):
        for i in range(8):
            conv, config, graph = self.plan("va-now-%d" % i)
            took = conv.get("call_interjection")
            self.assertTrue(took, "seed %d reached no diamond" % i)
            self.assertEqual(took["id"], IJ["id"])
            calls = [t for t in conv["turns"] if t.get("graph_type") == "call"]
            self.assertTrue(calls)
            self.assertTrue(all(t["speaker"] == "C" for t in calls))
            c = next(p for p in conv["participants"] if p["actor_id"] == "C")
            self.assertEqual(c["name"], IJ["name"])
            brief = calls[0]["protocol"]
            self.assertIn("joins a live discussion", brief)             # the node's own brief stays
            self.assertIn("put through by the operator", brief)
            self.assertIn("Crochet Master", brief)
            self.assertIn("yarn shortage", brief)
            gate = self.call_gate_events(conv, graph)[0]
            rows = gate["stages"][0]["candidates"]
            by = {r["id"]: r for r in rows}
            self.assertEqual(by["call"]["effective_weight"] if "effective_weight" in by["call"] else by["call"]["weight"], 1.0)
            other = [r for r in rows if r["id"] != "call"]
            self.assertTrue(all((r.get("effective_weight", r.get("weight"))) == 0.0 for r in other))
            self.assertTrue(any("operator dispatch" in w for w in by["call"]["why"]))
            self.assertEqual((gate.get("meta") or {}).get("dispatch"), IJ["id"])
            # every edge still on the wheel, the flow weights kept as the base
            self.assertEqual(sorted(r["id"] for r in rows), sorted(["call", "expand_one"]))

    def test_the_call_is_taken_once_and_replays(self):
        conv, config, graph = self.plan("va-once")
        gates = self.call_gate_events(conv, graph)
        forced = [g for g in gates if (g.get("meta") or {}).get("dispatch")]
        self.assertEqual(len(forced), 1)
        replayed = system3.replay(json.loads(json.dumps(conv)), config)
        self.assertTrue(replayed["ok"], replayed.get("why"))

    def test_without_a_dispatch_the_diamond_rolls_as_the_graph_says(self):
        for i in range(8):
            conv, _config, graph = self.plan("va-none-%d" % i, armed=False)
            self.assertFalse(conv.get("call_interjection"))
            self.assertFalse([t for t in conv["turns"] if t.get("speaker") == "C"])
            for gate in self.call_gate_events(conv, graph):
                self.assertFalse((gate.get("meta") or {}).get("dispatch"))

    def test_the_brief_rides_only_the_conversation_that_took_it(self):
        conv, _c, _g = self.plan("va-brief")
        other = {"call_interjection": {"id": "d_other"}}
        self.assertEqual(system3.voice_actor_call_brief(conv, other), "")
        self.assertEqual(system3.voice_actor_call_brief({"turns": []}, {"call_interjection": dict(IJ)}), "")


class RuntimeArm(unittest.TestCase):
    def boot(self, mode="active_selected_roads", hooks=True, segment_id=""):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.pending_calls, self.taken = [], []
        if hooks:
            def pending(road="", segment_id=""):
                self.pending_calls.append((road, segment_id))
                return dict(self.armed) if self.armed else None

            def taken(did, cid, turn_ids=None, node=""):
                self.taken.append((did, cid, list(turn_ids or []), node))
                self.armed = None

            self.station["voice_actor_interjection_pending"] = pending
            self.station["voice_actor_interjection_taken"] = taken
        self.station["segment_on_air"] = lambda at=0.0: ({"id": segment_id, "label": "Hour 1"}
                                                          if segment_id else {})
        self.armed = dict(IJ)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": mode, "roads": ["banter"],
                                                             "test_seed": "va-rt"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        # the banter chapter graph on (the station enabled its graphs), the
        # reply gate walked to the call diamond so a short round reaches it
        g = self.rt.config["structure"]["graph"]
        g["enabled"] = True
        for edge in g["edges"]:
            if edge["from"] == "reply_gate":
                edge["weight"] = 1 if edge["to"] == "reply_a" else 0
        return self.rt

    def direct(self, **over):
        return asyncio.new_event_loop().run_until_complete(
            self.station["system3_direct_banter"](**ctx(**over)))

    def test_a_live_round_takes_the_armed_caller_and_reports_it(self):
        self.boot()
        h = self.direct(bank=False, lines=12)
        self.assertIsNotNone(h)
        self.assertTrue(self.pending_calls)
        self.assertEqual(len(self.taken), 1, self.station.logged[-5:])
        did, cid, turns, node = self.taken[0]
        self.assertEqual(did, IJ["id"])
        self.assertEqual(cid, h.id)
        self.assertTrue(turns and node)
        self.assertEqual(h.interjection["name"], IJ["name"])
        self.assertEqual(h.conv["inputs"]["call_interjection"]["id"], IJ["id"])   # recorded inputs
        self.assertTrue(any(t["speaker"] == "C" for t in h.conv["turns"]))
        self.assertIn("C ", h.sheet.replace("\t", " ") + " ")                     # the running order has C rows

    def test_a_banked_round_never_takes_it(self):
        self.boot()
        h = self.direct(bank=True, lines=12)
        self.assertIsNotNone(h)
        self.assertEqual(self.pending_calls, [])
        self.assertEqual(self.taken, [])
        self.assertFalse(getattr(h, "interjection", None))

    def test_a_call_road_round_never_takes_it(self):
        self.boot()
        self.direct(bank=False, caller_name="Marge", road="caller", lines=10)
        self.assertEqual(self.pending_calls, [])
        self.assertEqual(self.taken, [])

    def test_shadow_mode_never_takes_it(self):
        self.boot(mode="shadow")
        self.direct(bank=False, lines=12)
        self.assertEqual(self.pending_calls, [])
        self.assertEqual(self.taken, [])

    def test_nothing_armed_plans_as_before(self):
        self.boot()
        self.armed = None
        h = self.direct(bank=False, lines=12)
        self.assertTrue(self.pending_calls)
        self.assertEqual(self.taken, [])
        self.assertFalse([t for t in h.conv["turns"] if t["speaker"] == "C"])
        self.assertNotIn("call_interjection", h.conv["inputs"])

    def test_a_station_without_the_store_plans_as_before(self):
        self.boot(hooks=False)
        h = self.direct(bank=False, lines=12)
        self.assertIsNotNone(h)
        self.assertFalse([t for t in h.conv["turns"] if t["speaker"] == "C"])

    def test_the_segment_is_handed_to_the_store(self):
        self.boot(segment_id="occ-7")
        self.direct(bank=False, lines=12)
        self.assertEqual(self.pending_calls[0][1], "occ-7")


if __name__ == "__main__":
    unittest.main(verbosity=2)
