"""The editable graph routes actual System 3 turns and recorded decisions."""

import copy
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import conversation_graph
import system3
import system3_runtime
from system3_store import System3Store
from test_system3_runtime import FakeStation


def scene(seed="graph-test", turns=18, graph=None, seats=None, caller=False):
    config = system3.default_config()
    if graph is not None:
        config["structure"]["graph"] = conversation_graph.normalize(graph)
    config["structure"]["graph"]["enabled"] = True
    inputs = {"road": "banter", "seats": seats or ["A", "B", "D"],
              "names": {"A": "Host", "B": "Co-host", "D": "Third chair", "C": "Jane"},
              "turns": turns, "target_seconds": turns * 15,
              "subject": {"topic": "the town budget"},
              "availability": {}, "speakerbox_rates": {}, "graph_caller_available": caller}
    conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
    system3.plan_more(conv, config)
    return conv, config


def test_graph_rolls_branches_and_cast_without_replacing_system3_table_draws():
    conv, config = scene()
    turns = [t for t in conv["turns"] if t.get("graph_node")]
    assert turns
    assert turns[0]["graph_type"] == "initiator"
    assert all(t["speaker"] != turns[0]["speaker"] for t in turns[1:3]
               if t["graph_type"] == "reply")
    assert any(e["family"] == "GRAPH" and e["stages"][0]["stage"] == "branch"
               for e in conv["decision_events"])
    assert any(e["family"] == "ES" for e in conv["decision_events"])
    assert any(e["family"] == "GRAPH" and e["stages"][0]["stage"] == "handling"
               for e in conv["decision_events"])
    assert any(t.get("graph_intonation") for t in turns)
    assert all(t.get("performance") for t in turns)
    assert "Allow about" in system3.render_sheet(conv)
    assert system3.replay(copy.deepcopy(conv), config)["ok"]


def test_rebuttal_answers_the_original_responders_after_two_independent_half_chances():
    graph = conversation_graph.default_graph("a specific topic")
    seen = 0
    for n in range(30):
        conv, _ = scene(seed=f"answer-{n}", turns=20, graph=graph)
        for i, turn in enumerate(conv["turns"]):
            if turn.get("graph_node") not in ("answer_a", "answer_b"):
                continue
            source = "reply_" + turn["graph_node"][-1]
            preceding = [t for t in conv["turns"][:i] if t.get("graph_node") == source]
            assert preceding and preceding[-1]["speaker"] == turn["speaker"]
            assert "answer the initiator's rebuttal" in turn["protocol"]
            seen += 1
    assert seen > 0


def test_graph_sanitizer_rejects_broken_links_and_bounds_the_editor_values():
    graph = conversation_graph.normalize({"nodes": [
        {"id": "one", "type": "initiator", "chance": 8, "seconds": 10000},
        {"id": "two", "type": "reply", "respond_to": "one", "draws": [{"family": "ES"}]},
        {"id": "bad", "type": "invalid"}],
        "edges": [{"from": "one", "to": "two", "weight": 5},
                  {"from": "two", "to": "missing", "weight": 1}]})
    assert [n["id"] for n in graph["nodes"]] == ["one", "two"]
    assert graph["nodes"][0]["chance"] == 1
    assert graph["nodes"][0]["seconds"] == 300
    assert graph["nodes"][1]["respond_to"] == "one"
    assert [(e["from"], e["to"]) for e in graph["edges"]] == [("one", "two")]
    assert conversation_graph.normalize({"nodes": {}, "edges": {}, "topic_options": {}})["nodes"] == []


def test_graph_mode_b_replan_replays_the_same_recorded_rolls():
    conv, config = scene(seed="graph-replan", turns=12)
    for index in range(3):
        system3.observe(conv, index, "No, that claim is wrong.")
    system3.replan(conv, config, 3, until=12)
    assert system3.replay(copy.deepcopy(conv), config)["ok"]


def test_call_chain_requires_an_available_caller_and_receives_topic_context():
    graph = conversation_graph.default_graph()
    for edge in graph["edges"]:
        if edge["from"] == "call_gate":
            edge["weight"] = 1 if edge["to"] == "call" else 0
        if edge["from"] == "reply_gate":
            edge["weight"] = 1 if edge["to"] == "reply_a" else 0
    absent, _ = scene(seed="call-path", graph=graph)
    assert not any(t.get("graph_type") == "call" for t in absent["turns"])
    present, _ = scene(seed="call-path", graph=graph, caller=True)
    calls = [t for t in present["turns"] if t.get("graph_type") == "call"]
    assert calls and calls[0]["name"] == "Jane"
    assert "town budget" in calls[0]["protocol"]


def test_topic_change_keeps_the_road_and_seeds_the_next_chapter():
    graph = conversation_graph.default_graph()
    graph["topic_options"] = ["the library renovation"]
    for edge in graph["edges"]:
        if edge["from"] == "reply_gate":
            edge["weight"] = 1 if edge["to"] == "topic_change" else 0
    conv, _ = scene(seed="topic-loop", turns=6, graph=graph)
    chapters = [t for t in conv["turns"] if t.get("graph_node") == "start"]
    assert len(chapters) > 1
    assert chapters[0]["speaker"] != chapters[1]["speaker"]
    assert chapters[1]["topic_override"] == "the library renovation"
    assert conv["graph_structure"]["road"] == "banter"
    assert any(e["family"] == "GRAPH" and e["stages"][0]["stage"] == "initiator"
               for e in conv["decision_events"])


def test_new_station_starts_with_the_conversation_graph_enabled():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        store = System3Store(root + "/system3.sqlite3")
        try:
            assert store.config()["structure"]["graph"]["enabled"] is True
        finally:
            store.close()


def test_graph_editor_api_previews_and_versions_the_live_system3_structure():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        host = FakeStation(root)
        app = FastAPI()
        system3_runtime.install(app, host)
        with TestClient(app) as client:
            graph = conversation_graph.default_graph()
            graph["enabled"] = True
            preview = client.post("/api/system3/graph/preview", json={
                "road": "banter", "graph": graph, "seconds": 180, "turns": 12,
            }, headers={"Authorization": "Bearer k"})
            assert preview.status_code == 200, preview.text
            assert preview.json()["turns"]
            assert any(roll["kind"] == "branch" for roll in preview.json()["rolls"])
            saved = client.put("/api/system3/structure", json={
                "steps": system3.default_config()["structure"]["steps"], "graph": graph,
            }, headers={"Authorization": "Bearer k"})
            assert saved.status_code == 200, saved.text
            live = client.get("/api/system3/config").json()["config"]["structure"]["graph"]
            assert live["enabled"] is True
            assert live["edges"] == graph["edges"]
            preset = client.put("/api/system3/graph/presets/Talk chapter", json={"graph": graph},
                                headers={"Authorization": "Bearer k"})
            assert preset.status_code == 200, preset.text
            listed = client.get("/api/system3/graph/presets").json()["presets"]
            assert listed["Talk chapter"]["edges"] == graph["edges"]
            assert client.delete("/api/system3/graph/presets/Talk chapter",
                                 headers={"Authorization": "Bearer k"}).status_code == 200
