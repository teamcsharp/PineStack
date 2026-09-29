"""[rounds-tree] GET /api/script/segment/{id}/decision-tree - the builder and the route.

Run: PYTHONPATH=tests:. python3 -m unittest tests.test_script_decision_tree
"""
import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

import script_decision_tree as sdt

SEED = "seed0001"


def ev(seq, family, stages, node="", turn_index=-1, turn_id="", selected=None):
    return {"event_id": "c1:%04d" % seq, "seq": seq, "family": family, "stages": stages,
            "meta": {"node": node} if node else {}, "turn_index": turn_index, "turn_id": turn_id,
            "selected": selected or {}, "rng": {"seed": SEED}}


def stage(name, cands, sel, dice, n=0):
    return {"stage": name, "candidates": [{"id": c, "label": lab, "weight": w, "base": w, "p": p, "why": ["w"]}
                                          for c, lab, w, p in cands],
            "draw": {"seed": SEED, "n": n, "label": "X:%s" % name, "u": dice / 100.0, "dice": dice, "sides": 100},
            "selected": sel, "total": sum(c[2] for c in cands)}


def es_event(seq, tid, tix):
    return ev(seq, "ES", [
        stage("table", [("ES1", "Emotional Set 1", 1.0, 1.0)], "ES1", 1),
        stage("category", [("anger", "ANGER", 1.0, 0.25), ("joy", "JOY", 3.0, 0.75)], "anger", 12, 1),
        stage("item", [("anger.fury", "fury", 1, 0.5), ("anger.spite", "spite", 1, 0.5)], "anger.fury", 70, 2)],
        turn_index=tix, turn_id=tid, selected={"table": "ES1", "label": "fury", "text": "play it hot"})


def conversation(graph=True, status="generated"):
    turns = [
        {"turn_id": "c1:t00", "index": 0, "step": "start", "step_label": "Start", "speaker": "A", "name": "Dill",
         "cycle": 0, "status": "generated", "text": "", "decisions": [{"family": "ES", "event_id": "c1:0010"}]},
        {"turn_id": "c1:t01", "index": 1, "step": "reply_a", "step_label": "Reply A", "speaker": "B", "name": "Skip",
         "cycle": 0, "status": "generated", "text": "No way that works.", "decisions": [{"family": "RS", "event_id": "c1:0099"}]},
        {"turn_id": "c1:t02", "index": 2, "step": "rebuttal", "step_label": "Rebuttal", "speaker": "A", "name": "Dill",
         "cycle": 0, "status": "dropped", "text": "", "decisions": []},
    ]
    events = [es_event(10, "c1:t00", 0),
              ev(20, "LENGTH", [stage("dice", [], 3, 9)], selected={"label": "3 turns"})]
    if graph:
        events += [
            ev(1, "GRAPH", [stage("initiator", [("A", "Dill", 1, 0.5), ("B", "Skip", 1, 0.5)], "A", 31)], node="start",
               turn_index=0),
            ev(2, "GRAPH", [stage("branch", [("reply_a", "Reply A", 0.5, 0.5), ("exit_gate", "Exit Gate", 0.5, 0.5)],
                                  "reply_a", 22)], node="reply_gate", turn_index=1),
            ev(3, "GRAPH", [stage("speaker", [("B", "Skip", 1, 1.0)], "B", 64)], node="reply_a", turn_index=1),
            ev(4, "GRAPH", [stage("chance", [("speak", "speak", 1, 0.5), ("skip", "skip", 1, 0.5)], "skip", 88)],
               node="answer_a", turn_index=2),
            ev(5, "GRAPH", [stage("handling", [("5", "missed the point", 1, 0.2), ("6", "agrees", 4, 0.8)], "5", 7)],
               node="rebuttal", turn_index=3),
        ]
    return {"identity": {"conversation_id": "c1", "road_kind": "banter", "system2_slot_id": "hour-x:hour-05"},
            "mode": "active", "status": status, "created": 1000.0, "engine": "system3-engine/4", "seed": SEED,
            "subject": {"topic": "tape"}, "turns": turns, "decision_events": events,
            "lines": [{"line_id": "L0", "turn_id": "c1:t00", "block": 7, "ord": 0, "text": "Boat tank.",
                       "segment": "hour-x:hour-05"},
                      {"line_id": "L1", "turn_id": "c1:t01", "block": 7, "ord": 1, "text": "No way that works."}]}


class Builder(unittest.TestCase):
    def test_odds(self):
        self.assertEqual(sdt.odds_text(0.5), "1:2")
        self.assertEqual(sdt.odds_text(0.3333), "1:3")
        self.assertEqual(sdt.odds_text(0.6), "60%")
        self.assertEqual(sdt.odds_text(1.0), "certain")
        self.assertEqual(sdt.odds_text(None), "")

    def test_chain_order_and_diamonds(self):
        r = sdt.build_round(conversation(), {"L0": {"air_at": 5.0}})
        kinds = [(e["type"], e.get("node")) for e in r["elements"]]
        self.assertEqual(kinds, [("stage", "start"), ("diamond", "reply_gate"), ("stage", "reply_a"),
                                 ("diamond", "answer_a"), ("stage", "rebuttal")])
        gate = r["elements"][1]
        self.assertEqual(gate["dice"], 22)
        self.assertEqual(gate["seed"], SEED)
        self.assertEqual(gate["odds"], "1:2")
        self.assertEqual(gate["kind"], "exit")                 # it offered the exit gate
        self.assertEqual(gate["not_taken"], ["Exit Gate"])
        self.assertEqual([f["weight"] for f in gate["faces"]], [0.5, 0.5])
        skip = r["elements"][3]
        self.assertEqual(skip["kind"], "chance")
        self.assertEqual(skip["not_taken"], ["Answer A"])      # a skipped optional node is the untaken branch

    def test_stage_receipts_and_states(self):
        r = sdt.build_round(conversation(), {"L0": {"air_at": 5.0}})
        start, reply, rebut = [e for e in r["elements"] if e["type"] == "stage"]
        self.assertEqual(start["state"], "aired")
        self.assertEqual(start["text"], "Boat tank.")          # the ledger row's words when the turn has none
        self.assertEqual(start["line"]["block"], 7)
        self.assertEqual(start["who_roll"]["dice"], 31)
        self.assertEqual(start["who_roll"]["odds"], "1:2")
        rec = start["rolls"][0]
        self.assertEqual(rec["table"], "ES1")
        self.assertEqual((rec["category"]["label"], rec["category"]["dice"], rec["category"]["odds"]), ("ANGER", 12, "1:4"))
        self.assertEqual((rec["sub"]["label"], rec["sub"]["dice"], rec["sub"]["index"], rec["sub"]["of"]), ("fury", 70, 1, 2))
        self.assertEqual(reply["state"], "scripted")
        self.assertEqual(reply["who_roll"]["dice"], 64)
        self.assertEqual(reply["rolls"][0].get("missing"), sdt.NOT_RECORDED)   # an event the ledger does not hold
        self.assertEqual(rebut["state"], "rejected")
        self.assertEqual(rebut["node_rolls"][0]["category"]["label"], "missed the point")
        self.assertEqual([x["family"] for x in r["round_rolls"]], ["LENGTH"])

    def test_no_graph_is_not_recorded(self):
        r = sdt.build_round(conversation(graph=False), {})
        self.assertFalse(any(e["type"] == "diamond" for e in r["elements"]))
        self.assertFalse(r["recorded"]["graph"])
        self.assertTrue(any("not recorded" in n for n in r["notes"]))
        self.assertIsNone(r["elements"][0]["who_roll"])

    def test_withheld_round_is_grey(self):
        r = sdt.build_round(conversation(status="withheld"), {})
        self.assertEqual(r["elements"][2]["state"], "rejected")
        self.assertEqual(r["elements"][0]["state"], "rejected")   # withheld: nothing of it goes out
        self.assertEqual(sdt.build_round(conversation(status="withheld"), {"L0": {"air_at": 1}})["elements"][0]["state"],
                         "aired")                                 # ... unless the ledger saw it air

    def test_scripts_and_match(self):
        entry = {"script": {"turns": [], "selected_candidate": "v2", "draft_variants": [
            {"id": "v1", "turns": [{"text": "Something else entirely here."}]},
            {"id": "v2", "turns": [{"text": "No way that works."}, {"text": "Boat tank."}]}]}}
        got = sdt.scripts_of(entry)
        self.assertEqual([(g["candidate"], g["selected"]) for g in got], [("v1", False), ("v2", True)])
        conv = conversation()
        conv["turns"][0]["text"] = "Boat tank."
        self.assertEqual(sdt.match_score(got[1]["texts"], conv), 1.0)
        self.assertEqual(sdt.match_score(got[0]["texts"], conv), 0.0)


class FakeStore:
    def __init__(self, convs, record=None, prepared=()):
        self.convs, self.record, self.prepared = convs, record, list(prepared)

    def segment_record(self, seg_id):
        return self.record if self.record and self.record["segment"]["id"] == seg_id else None

    def prepared_for(self, slot_id, since=0.0, limit=40):
        return [{"conversation_id": c} for c in self.prepared]

    def conversations(self, limit=50, road="", before=0.0, mode=""):
        return [{"conversation_id": k, "created": v["created"]} for k, v in self.convs.items()
                if v["identity"]["road_kind"] == road]

    def conversation(self, cid, with_events=True):
        return self.convs.get(cid)


def origin_db(folder):
    path = Path(folder) / "system3_origin.sqlite3"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE origin(line_id TEXT PRIMARY KEY, air_at REAL NOT NULL, verdict TEXT)")
    db.execute("INSERT INTO origin VALUES('L0', 1234.5, 'traced')")
    db.commit()
    db.close()
    return path


class Collect(unittest.TestCase):
    def test_aired_then_draft_and_unmatched(self):
        aired = conversation()
        draft = conversation()
        draft["identity"] = dict(draft["identity"], conversation_id="c2", system2_slot_id="hour-x:hour-01")
        draft["created"] = 2000.0
        draft["lines"] = []
        draft["turns"][0]["text"] = "A draft opener nobody heard."
        store = FakeStore({"c1": aired, "c2": draft},
                          record={"segment": {"id": "seg"}, "conversations": [{"conversation_id": "c1", "first_block": 7}]})
        entry = {"kind": "banter", "start": 2500.0, "script": {"draft_variants": [
            {"id": "v1", "turns": [{"text": "A draft opener nobody heard."}, {"text": "No way that works."}]},
            {"id": "v9", "turns": [{"text": "Words System 3 never saw at all."}]}]}}
        with tempfile.TemporaryDirectory() as tmp:
            got = sdt.collect(store, "seg", entry, origin_db(tmp), now=3000.0)
        self.assertEqual([(r["conversation_id"], r["source"]) for r in got["rounds"]], [("c1", "aired"), ("c2", "draft")])
        self.assertEqual(got["rounds"][1]["candidate"], "v1")
        self.assertTrue(got["rounds"][1]["selected"])
        self.assertEqual(got["rounds"][0]["elements"][0]["state"], "aired")
        self.assertEqual(got["rounds"][0]["elements"][0]["line"]["air_at"], 1234.5)
        self.assertEqual([u["candidate"] for u in got["unmatched"]], ["v9"])

    def test_gone_conversation(self):
        store = FakeStore({}, record={"segment": {"id": "seg"}, "conversations": [{"conversation_id": "old"}]})
        with tempfile.TemporaryDirectory() as tmp:
            got = sdt.collect(store, "seg", None, Path(tmp) / "none.sqlite3")
        self.assertTrue(got["rounds"][0]["gone"])


class Route(unittest.TestCase):
    def test_route(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:  # noqa: BLE001
            self.skipTest("fastapi test client unavailable: %s" % exc)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        origin_db(tmp.name)
        store = FakeStore({"c1": conversation()},
                          record={"segment": {"id": "hour-x:hour-05"}, "conversations": [{"conversation_id": "c1"}]})

        class RT:
            def __init__(self):
                self.store = store

            async def read(self, fn, *args):
                return await asyncio.get_running_loop().run_in_executor(None, lambda: fn(*args))

        rt = RT()
        asked = []
        ns = {"data_path": lambda name: str(Path(tmp.name) / name),
              "_SYSTEM3_RUNTIME": lambda: rt,
              "require_read_auth": lambda a: asked.append(a),
              "director_room": lambda which: {"entries": [{"occurrence": "hour-x:hour-05", "kind": "banter",
                                                           "label": "Banter", "orchestration": {"say": "written: 1/2"}}]}}
        app = FastAPI()
        sdt.install(app, ns)
        client = TestClient(app)
        res = client.get("/api/script/segment/hour-x:hour-05/decision-tree", headers={"Authorization": "Bearer k"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["schema"], sdt.SCHEMA)
        self.assertEqual(body["entry"]["say"], "written: 1/2")
        self.assertEqual(body["rounds"][0]["conversation_id"], "c1")
        self.assertEqual(asked, ["Bearer k"])
        self.assertEqual(client.get("/api/script/segment/nope/decision-tree").status_code, 404)


if __name__ == "__main__":
    unittest.main()
