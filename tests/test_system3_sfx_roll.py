"""[s3-sfx-roll] The board's clip is two of System 3's rolls, and the node
shows what they landed on: a pick carries the picture of what it landed on,
the road reads its own dice back off the record, and the board line's rolls
and poster reach the STATION event, the SFX observation and the
conversation's lines (GET /api/system3/conversation/<id>). Pure: the runtime
against the stand-in station, no app.py."""
import asyncio
import json
import tempfile
import threading
import unittest

import system3
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle
from fastapi import FastAPI
from fastapi.testclient import TestClient

POSTER = "/api/sfx/poster/0123456789abcdef?t=sig"
PICTURE = {"id": "0123456789abcdef", "kind": "video", "thumb": POSTER, "thumb_kind": "frame", "poster": POSTER}
ROLL = {"road": "pool",
        "category": {"label": "horns", "dice": 41, "u": 0.405, "of": 3, "index": 2},
        "clip": {"label": "air horn", "dice": 7, "u": 0.061, "of": 12, "index": 1, "tries": 1},
        "thumb": POSTER, "thumb_kind": "frame"}


class SfxRollRuntimeTests(unittest.TestCase):
    def boot(self, mode="active"):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.station["read_bombshells"] = lambda: []
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": mode, "test_seed": "sfx-roll"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        system3_runtime._S3_ROLLS.set(None)
        vars(system3_runtime._S3_LAST).clear()     # this thread's last rolls, from an earlier test
        return self.rt

    def round_(self):
        return asyncio.new_event_loop().run_until_complete(
            self.station["system3_direct_banter"](**ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"})))

    def test_system3_off_rolls_nothing_and_there_is_nothing_to_read_back(self):
        self.boot(mode="off")
        asked = []
        got = self.station["system3_pick"]("sfx.clip", ["a", "b"], "which clip", [1.0, 1.0],
                                           media=lambda k: asked.append(k) or PICTURE)
        self.assertIsNone(got, "off: the station rolls its own")
        self.assertEqual(asked, [], "no roll, no picture asked for")
        self.assertFalse(self.station["system3_dice_live"]())
        self.assertIsNone(self.station["system3_last_roll"]("sfx.clip"))

    def test_a_pick_carries_the_picture_of_what_it_landed_on_and_reads_back(self):
        rt = self.boot()
        self.assertTrue(self.station["system3_dice_live"]())
        asked = []
        k = self.station["system3_pick"]("sfx.clip", ["a clip", "air  horn", "b clip"], "which clip in horns",
                                         [0.0, 1.0, 0.0], media=lambda i: asked.append(i) or PICTURE)
        self.assertEqual(k, 1, "the station's weights decide the wheel")
        self.assertEqual(asked, [1], "only the picked candidate's picture is asked for")
        rec = self.station["system3_last_roll"]("sfx.clip")
        self.assertEqual((rec["kind"], rec["of"], rec["index"], rec["picked"]), ("pick", 3, 2, "air horn"))
        self.assertTrue(1 <= rec["dice"] <= 100)
        self.assertEqual(rec["poster"], POSTER)
        self.assertEqual(rec["media"]["thumb_kind"], "frame")
        self.assertEqual(rt.station_view()[-1]["poster"], POSTER, "the station feed shows the picture")
        rec["dice"] = -1
        self.assertNotEqual(self.station["system3_last_roll"]("sfx.clip")["dice"], -1, "a copy is handed out")
        # a list works as well as a callable; a picture-less pick has none
        self.station["system3_pick"]("sfx.category", ["horns", "laughs"], "family", [1.0, 0.0],
                                     media=[{"thumb": "t0"}, {"thumb": "t1"}])
        self.assertEqual(self.station["system3_last_roll"]("sfx.category")["media"], {"thumb": "t0"})
        self.station["system3_pick"]("call.prizes", ["a mug", "a sweater"])
        self.assertNotIn("media", self.station["system3_last_roll"]("call.prizes"))

    def test_a_picture_that_fails_never_costs_the_roll(self):
        self.boot()

        def broken(_k):
            raise OSError("the share is down")
        k = self.station["system3_pick"]("sfx.clip", ["a", "b"], "which clip", [1.0, 1.0], media=broken)
        self.assertIn(k, (0, 1), "System 3's number stands")
        rec = self.station["system3_last_roll"]("sfx.clip")
        self.assertEqual(rec["index"], k + 1)
        self.assertNotIn("media", rec)

    def test_the_last_roll_is_the_rolling_threads_own(self):
        self.boot()
        seen = {}

        def worker():
            self.station["system3_pick"]("sfx.clip", ["only"], "which clip", [1.0])
            seen["worker"] = self.station["system3_last_roll"]("sfx.clip")
        t = threading.Thread(target=worker)
        t.start()
        t.join(10)
        self.assertEqual(seen["worker"]["picked"], "only")
        self.assertIsNone(self.station["system3_last_roll"]("sfx.clip"), "another thread's dice are not this one's")

    def test_the_station_event_keeps_the_poster(self):
        rt = self.boot()

        async def road():
            self.station["system3_pick"]("sfx.clip", ["air horn", "rimshot"], "which clip in horns",
                                         [1.0, 0.0], media=lambda k: PICTURE)
            return await self.station["system3_direct_banter"](
                **ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"}))
        h = asyncio.new_event_loop().run_until_complete(road())
        ev = h.conv["decision_events"][0]
        self.assertEqual((ev["family"], ev["meta"]["key"]), ("STATION", "sfx.clip"))
        self.assertEqual(ev["meta"]["poster"], POSTER)
        self.assertEqual(ev["meta"]["media"]["thumb_kind"], "frame")
        self.assertEqual(ev["stages"][0]["selected"], "air horn")
        self.assertTrue(system3.replay(json.loads(json.dumps(h.conv)), rt.config)["ok"])

    def test_the_board_line_carries_its_rolls_and_poster_to_the_conversation(self):
        self.boot()
        h = self.round_()
        first = h.conv["turns"][0]["turn_id"]
        rows = [{"line_id": "L0", "who": "dj", "text": "The raccoon took the van, and I let him.",
                 "system3": {"conversation_id": h.id, "mode": "active", "turn_id": first}},
                {"line_id": "B1", "who": "board", "text": "\U0001f50a air horn",
                 "system3": {"conversation_id": h.id, "mode": "active", "turn_id": "",
                             "sfx_roll": ROLL, "poster": POSTER}}]
        self.station["system3_observe_ledger"](12, "sid-1", rows, "banter")
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id).json()
        lines = {ln["line_id"]: ln for ln in got["lines"]}
        self.assertEqual(lines["B1"]["sfx_roll"], ROLL)
        self.assertEqual(lines["B1"]["poster"], POSTER)
        self.assertNotIn("sfx_roll", lines["L0"])
        self.assertNotIn("poster", lines["L0"])
        commit = next(o for o in got["observations_air"] if o["family"] == "COMMIT")
        self.assertEqual(set(commit["media"]), {"B1"})
        # a commit with no board clip carries no media map at all
        self.station["system3_observe_ledger"](13, "sid-2", rows[:1], "banter")
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id).json()
        self.assertEqual(sum(1 for o in got["observations_air"] if o["family"] == "COMMIT" and "media" in o), 1)

    def test_the_sfx_observation_says_the_rolls_chose_the_clip(self):
        self.boot()
        h = self.round_()
        direction = {"conversation_id": h.id, "turn": 1, "decided_by": "system3", "intent": "punctuate",
                     "extra": False}
        self.station["system3_sfx_observe"]({}, direction, True, [
            {"who": "board", "path": "/sfx/air horn.wav", "sfx_sample_id": "s1", "seconds": 1.0,
             "sfx_roll": ROLL, "poster": POSTER}], None)
        self.station["system3_sfx_observe"]({}, direction, True, [
            {"who": "board", "path": "/sfx/rimshot.wav", "sfx_sample_id": "s2", "seconds": 1.0}], None)
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id).json()
        sfx = [o for o in got["observations_air"] if o["family"] == "SFX"]
        self.assertEqual(sfx[0]["played"][0]["sfx_roll"], ROLL)
        self.assertEqual(sfx[0]["played"][0]["poster"], POSTER)
        self.assertTrue(sfx[0]["chosen_by"].startswith("System 3's rolls"))
        self.assertNotIn("sfx_roll", sfx[1]["played"][0])
        self.assertEqual(sfx[1]["chosen_by"], "the station's matcher, bans, weights and rotation")


if __name__ == "__main__":
    unittest.main()
