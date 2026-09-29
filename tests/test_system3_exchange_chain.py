"""[s3-chain] system3_runtime.line_chapter / line_chapter_state on a REAL
runtime: a line road with its graph on plans a chapter (road, turn ids, planned
seconds); a known conversation that is not a line road's chapter answers
{"chapter": False}; an unknown one None; a written exchange binds only whole
(>= 3 turns, >= 2 voices, every planned seat), each row carrying its own
turn's stamp; the shelf's state is recorded on the conversation."""
import asyncio
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import conversation_graph
import system3_runtime
import system3_tables
from test_system3_runtime import FakeStation, settle


class LineChapter(unittest.TestCase):
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
                             json={"mode": "active_selected_roads", "roads": roads, "test_seed": "chain-rt"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def enable(self, road):
        st = system3_tables.default_structures()[road]
        graph = conversation_graph.road_graph(road, st)
        graph["enabled"] = True
        saved = self.client.put("/api/system3/structures/" + road, json={"legs": st["legs"], "graph": graph},
                                headers={"Authorization": "Bearer k"})
        self.assertEqual(saved.status_code, 200, saved.text)

    def line(self, road="station_id", **kw):
        return asyncio.new_event_loop().run_until_complete(self.station["system3_direct_line"](
            road=road, who=kw.pop("who", "dj"), dj={"host_name": "Dill", "cohost_name": "Skip", "third_name": "Sam"},
            context=kw.pop("context", "station identification"), text=kw.pop("text", "This is Pine Box FM."), **kw))

    def test_a_line_roads_chapter_plans_binds_whole_and_stamps_each_turn(self):
        self.boot(["banter", "station_id"])
        self.enable("station_id")
        handle = self.line()
        chapter = self.station["system3_line_chapter"]
        plan = chapter(handle.stamp)
        self.assertTrue(plan["chapter"])
        self.assertEqual(plan["road"], "station_id")
        n = plan["turns"]
        self.assertGreaterEqual(n, 3)
        self.assertEqual(len(plan["turn_ids"]), n)
        self.assertEqual(len(plan["seconds"]), n)
        self.assertGreaterEqual(len(set(plan["seats"])), 2)
        self.assertIn(" 1 ", plan["sheet"])
        said = ["This is Pine Box FM.",
                "Pine Box FM at four in the morning, Dill? Somebody has to keep the kettle on.",
                "The kettle and the transmitter, Skip, both humming away in the dark.",
                "Humming is what a station does when nobody upstairs is watching the dials.",
                "Upstairs is asleep, which is exactly why the records get louder after midnight.",
                "Louder records, colder tea, and a caller who swears the moon is a satellite.",
                "The moon has better reception than our transmitter ever had, honestly.",
                "Reception or not, the night shift keeps the lights on for whoever is out there.",
                "Whoever is out there, we see you, and we are not turning the music down.",
                "Turn it up then, and let the next record answer for all of us.",
                "The next record has opinions, and it is about to share every one of them.",
                "Opinions at this hour are the only honest thing left on the dial."]
        written = [(s, said[i % len(said)]) for i, s in enumerate(plan["seats"])]
        self.assertIsNone(chapter(handle.stamp, written[:-1]))                 # not whole: refused
        self.assertIsNone(chapter(handle.stamp, [(plan["seats"][0], t) for _s, t in written]))  # one voice
        rows = chapter(handle.stamp, written)
        self.assertEqual(len(rows), n)
        self.assertEqual([r["stamp"]["turn_id"] for r in rows], plan["turn_ids"])     # each its own node
        self.assertEqual([r["stamp"]["chapter_turn"] for r in rows], list(range(n)))
        self.assertTrue(all(r["stamp"]["chapter_of"] == n for r in rows))
        self.assertEqual(len({r["stamp"]["turn_id"] for r in rows}), n)
        conv = self.rt.recent[handle.stamp["conversation_id"]]
        self.assertEqual(conv["status"], "chapter_ready")
        self.assertTrue(all(b.get("script_index") is not None for b in conv["bindings"]))

    def test_not_a_chapter_and_unknown_are_told_apart(self):
        self.boot(["banter", "station_id"])
        handle = self.line()                                  # graph OFF by default: the line as it was
        got = self.station["system3_line_chapter"](handle.stamp)
        self.assertEqual(got, {"chapter": False, "road": "station_id", "turns": 1})
        self.assertIsNone(self.station["system3_line_chapter"]({"conversation_id": "nope", "mode": "active"}))
        self.assertIsNone(self.station["system3_line_chapter"](None))

    def test_the_shelf_state_is_recorded_on_the_conversation(self):
        self.boot(["banter", "station_id"])
        self.enable("station_id")
        handle = self.line()
        note = self.station["system3_line_chapter_state"]
        note(handle.stamp, "pending", "attempt 1: turn 2 answers nothing", {"attempts": 1})
        conv = self.rt.recent[handle.stamp["conversation_id"]]
        self.assertEqual(conv["chapter_state"]["state"], "pending")
        self.assertEqual(conv["chapter_state"]["attempts"], 1)
        note(handle.stamp, "aired", "5 turns under sid x")
        self.assertEqual(conv["status"], "chapter_aired")
        note({"conversation_id": "unknown"}, "aired")         # unknown: nothing, no fault


if __name__ == "__main__":
    unittest.main()
