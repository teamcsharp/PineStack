"""[s3-segment] The station's scheduled segments, on System 3's side.

The operator (2026-09-28): "every conversation should be chained as the
"segment" per the station that is scheduled with everything for that segment
occuring within the section of the messenger view ... inspect other segments
via the right click menu and be able to trace the nodes of how the segments
are constructed via roulette RNG and System 3." And: "Interjection shouldn't
be displayed here as segments ... each segment is the only way these are
sectioned."

What these hold, measured failure first:
  * identity.schedule_occurrence_id was empty on 276 of 276 conversations - a
    conversation is now planned knowing the scheduled segment on air;
  * nothing recorded which segment a line went out in - the register files
    every block of the script under its segment, rounds and single lines alike,
    and a single line is a conversation IN a segment, never a segment;
  * a segment is traceable down to its rolls, with its own scheduling decision.
"""
import asyncio
import tempfile
import time
import unittest
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3_runtime
from test_system3_runtime import FakeStation, ctx, settle

AUTH = {"Authorization": "Bearer k"}
T0 = 1790582400.0
SEG_A = {"id": "hour-1790582400000:hour-05", "template": "hour-05", "kind": "banter",
         "label": "Banter during recordings", "start": T0 + 840, "ends": T0 + 1080,
         "hour": "2026-09-28T03", "index": 4, "engine": "system2"}
SEG_B = {"id": "hour-1790582400000:hour-06", "template": "hour-06", "kind": "manager",
         "label": "Angry messages from upstairs", "start": T0 + 1080, "ends": T0 + 1320,
         "hour": "2026-09-28T03", "index": 5, "engine": "system2"}
SEG_C = {"id": "hour-1790582400000:hour-07", "template": "hour-07", "kind": "caller",
         "label": "Call", "start": T0 + 1320, "ends": T0 + 1500, "hour": "2026-09-28T03",
         "index": 6, "engine": "system2"}


def room_entry(seg, state):
    return {"ordinal": seg["index"], "kind": seg["kind"], "label": seg["label"], "slot_id": seg["template"],
            "occurrence": seg["id"], "minutes": 4.0, "start": seg["start"], "deadline": seg["ends"],
            "state": state, "own_seconds": 12.0, "aired_seconds": 80.0, "notes": "", "prompt_id": "",
            "prompt": "SCHEDULE - THIS ROUND IS THE ENTRY", "flow": [], "flow_prompt": "",
            "script": {"state": "bound", "drafts": 0, "turns": [{"seat": "A", "text": "x" * 500}]},
            "aired": [{"at": seg["start"] + 5, "who": "dj", "kind": "dialogue", "round": "banter",
                       "line": "L1", "seconds": 3.0, "text": "hello"}],
            "direction": {"standing": [], "next": [], "clause": "keep it moving"},
            "review": {"state": "approved"}, "beats": [{"id": "b1"}],
            "orchestration": {"kind": seg["kind"], "target": {"lines": 18}, "have": {"lines": 6}}}


class SegmentTests(unittest.TestCase):
    def boot(self, segment=None, **station):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name, **station)
        self.on_air = dict(segment) if segment else None
        if segment is not None:
            self.station["segment_on_air"] = lambda at=0.0: dict(self.on_air) if self.on_air else {}
        self.rooms = []
        self.station["director_room"] = self.room
        self.station["director_why"] = lambda kind: {
            "kind": kind, "stock": {"rows": 13}, "pool": {"ready_now": 10},
            "census": {"why": {"READY": 12}}, "entries": [{"label": "Banter", "commit": "ready"}],
            "say": "13 written", "task": {"count": 9}}
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active", "test_seed": "seg-1"}, headers=AUTH)
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def room(self, which=0):
        self.rooms.append(which)
        if which == 0:
            return {"hour": "hour-1790582400000", "entries": [room_entry(SEG_A, "aired"), room_entry(SEG_B, "on air"),
                                                              room_entry(SEG_C, "planned")]}
        return {"hour": "hour-1790586000000", "entries": []}

    def plan_round(self, **over):
        return asyncio.run(self.station["system3_direct_banter"](**ctx(**over)))

    def plan_line(self, road="interject", text="Hold on, a memo."):
        return asyncio.run(self.station["system3_direct_line"](road=road, who="dj", dj={"host_name": "Caine"},
                                                               context="a memo", candidates=[text]))

    def rows_of(self, h, prefix, board=True):
        rows = []
        for t in h.conv["turns"][:3]:
            rows.append({"line_id": "%s%d" % (prefix, t["index"]), "who": "dj", "kind": "dialogue",
                         "text": "words %d" % t["index"],
                         "dice": {"s3": {"conversation_id": h.id, "turn_id": t["turn_id"]}}})
        if board:
            rows.append({"line_id": prefix + "sfx", "who": "board", "kind": "sfx", "text": "crash",
                         "system3": {"conversation_id": h.id, "mode": "active", "turn_id": ""}})
        return rows

    # --- the stamp at planning -------------------------------------------------------
    def test_a_round_is_planned_knowing_the_segment_on_air(self):
        self.boot(SEG_A)
        h = self.plan_round()
        self.assertEqual(h.conv["identity"]["segment"]["id"], SEG_A["id"])
        self.assertEqual(h.conv["identity"]["segment"]["label"], "Banter during recordings")
        self.assertEqual(h.conv["identity"]["schedule_occurrence_id"], SEG_A["id"],
                         "the engine's own identity field, empty on every conversation until now")
        self.assertEqual(h.conv["inputs"]["segment"]["kind"], "banter")
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id, headers=AUTH).json()
        self.assertEqual(got["identity"]["segment"]["id"], SEG_A["id"])

    def test_a_single_line_is_planned_knowing_its_segment_too(self):
        self.boot(SEG_B)
        h = self.plan_line()
        self.assertTrue(h.active)
        self.assertEqual(h.conv["identity"]["segment"]["id"], SEG_B["id"])
        self.assertEqual(h.conv["identity"]["schedule_occurrence_id"], SEG_B["id"])

    def test_no_schedule_no_segment_and_nothing_breaks(self):
        self.boot(None)                      # a station without segment_on_air
        h = self.plan_round()
        self.assertEqual(h.conv["identity"]["segment"], {})
        self.assertEqual(h.conv["identity"]["schedule_occurrence_id"], "")
        self.station["segment_on_air"] = lambda at=0.0: {}      # a station running no schedule
        h2 = self.plan_line()
        self.assertEqual(h2.conv["identity"]["segment"], {})

    # --- the register -------------------------------------------------------------------
    def test_every_block_files_under_its_segment_rounds_and_single_lines_alike(self):
        self.boot(SEG_A)
        r1 = self.plan_round()
        i1 = self.plan_line(text="Hold on, a memo.")
        self.on_air = dict(SEG_B)
        i2 = self.plan_line(text="Wait - upstairs wants a word.")
        seg_block = self.station["system3_segment_block"]
        seg_block(101, T0 + 900, "sid-1", self.rows_of(r1, "r1-"), SEG_A, "banter")
        seg_block(102, T0 + 950, "", [{"line_id": "i1", "who": "dj", "kind": "interject", "text": "Hold on",
                                       "system3": dict(i1.stamp)}], SEG_A, "banter")
        seg_block(103, T0 + 960, "", [{"line_id": "b1", "who": "board", "kind": "sfx", "text": "honk"}],
                  SEG_A, "banter")                                   # a clip no node made: counted, no conversation
        seg_block(104, T0 + 1100, "", [{"line_id": "i2", "who": "dj", "kind": "interject", "text": "Wait",
                                        "system3": dict(i2.stamp)}], SEG_B, "manager")
        settle()
        got = self.client.get("/api/system3/segments?since=%f" % (T0 - 3600), headers=AUTH).json()
        segs = got["segments"]
        self.assertEqual([s["id"] for s in segs], [SEG_A["id"], SEG_B["id"]], "the script's own order")
        a, b = segs
        self.assertEqual((a["first_block"], a["last_block"], a["blocks"]), (101, 103, 3))
        self.assertEqual(a["lines"], 4 + 1 + 1)
        self.assertEqual([c["conversation_id"] for c in a["conversations"]], [r1.id, i1.id])
        self.assertEqual([c["single"] for c in a["conversations"]], [False, True],
                         "an interjection is a line IN the segment, never a segment of its own")
        self.assertEqual((a["rounds"], a["singles"]), (1, 1))
        self.assertEqual(a["conversations"][0]["lines"], 4)
        self.assertEqual(a["conversations"][0]["road"], "banter")
        self.assertEqual(a["label"], "Banter during recordings")
        self.assertEqual([c["conversation_id"] for c in b["conversations"]], [i2.id])
        self.assertEqual(got["now"]["id"], SEG_B["id"], "the segment on air now, even before its first block")
        self.assertNotIn("plan", got)
        planned = self.client.get("/api/system3/segments?plan=1&since=%f" % (T0 - 3600), headers=AUTH).json()
        self.assertEqual([e["occurrence"] for e in planned["plan"]["entries"]], [SEG_A["id"], SEG_B["id"], SEG_C["id"]])

    def test_a_block_heard_in_two_parts_is_merged_and_keeps_its_segment(self):
        self.boot(SEG_A)
        i1 = self.plan_line()
        seg_block = self.station["system3_segment_block"]
        seg_block(201, T0 + 900, "", [{"line_id": "x1", "system3": dict(i1.stamp)}], SEG_A)
        seg_block(201, T0 + 1200, "", [{"line_id": "x1-punct-1", "system3": dict(i1.stamp)},
                                       {"line_id": "x1", "system3": dict(i1.stamp)}], SEG_B)
        settle()
        rec = self.rt.store.segment_record(SEG_A["id"])
        self.assertEqual(rec["blocks"][0]["line_ids"], ["x1", "x1-punct-1"])
        self.assertEqual(rec["segment"]["lines"], 2)
        self.assertEqual(rec["blocks"][0]["at"], T0 + 900)
        self.assertIsNone(self.rt.store.segment_record(SEG_B["id"]), "a block never moves segment")

    def test_a_register_fault_never_reaches_the_ledger(self):
        self.boot(SEG_A)
        seg_block = self.station["system3_segment_block"]
        seg_block(301, T0, "", None, SEG_A)
        seg_block(302, T0, "", ["not a row", {"dice": "nope"}, {"system3": "nope"}], SEG_A)
        seg_block(303, T0, "", [{"line_id": "y"}], {})          # no segment: nothing to file
        seg_block("not a block", T0, "", [], SEG_A)
        settle()
        self.assertEqual(self.rt.store.segment_record(SEG_A["id"])["segment"]["first_block"], 301)

    def test_the_conversations_lines_carry_their_segment(self):
        self.boot(SEG_A)
        h = self.plan_round()
        rows = self.rows_of(h, "c-", board=False)
        self.station["system3_observe_ledger"](401, "sid-4", rows, "banter")
        self.station["system3_segment_block"](401, T0 + 900, "sid-4", rows, SEG_A, "banter")
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id, headers=AUTH).json()
        self.assertEqual({ln["segment"] for ln in got["lines"]}, {SEG_A["id"]})
        line = self.client.get("/api/system3/line?line_id=c-0", headers=AUTH).json()
        self.assertEqual(line["line"]["segment"], SEG_A["id"])

    # --- the trace ------------------------------------------------------------------------
    def test_a_segment_is_traced_down_to_its_rolls_with_its_own_scheduling_decision(self):
        self.boot(SEG_A)
        r1 = self.plan_round()
        i1 = self.plan_line()
        seg_block = self.station["system3_segment_block"]
        rows = self.rows_of(r1, "t-")
        self.station["system3_observe_ledger"](501, "sid-5", rows, "banter")     # the ledger's own hook first
        seg_block(501, T0 + 900, "sid-5", rows, SEG_A, "banter")
        seg_block(502, T0 + 950, "", [{"line_id": "t-i", "system3": dict(i1.stamp)}], SEG_A)
        seg_block(503, T0 + 1100, "", [{"line_id": "t-j", "system3": dict(i1.stamp)}], SEG_B)
        settle()
        got = self.client.get("/api/system3/segment/" + SEG_A["id"], headers=AUTH).json()
        self.assertTrue(got["registered"])
        self.assertEqual(got["segment"]["label"], "Banter during recordings")
        self.assertEqual([b["block"] for b in got["blocks"]], [501, 502])
        convs = got["conversations"]
        self.assertEqual([c["conversation_id"] for c in convs], [r1.id, i1.id])
        rnd, one = convs
        self.assertFalse(rnd["single"])
        self.assertTrue(one["single"])
        self.assertEqual(rnd["planned_in"]["id"], SEG_A["id"])
        self.assertEqual(rnd["structure"]["id"], "banter_cycle")
        self.assertTrue(rnd["length"] and rnd["length"]["turns"] >= 8)
        fams = {x["family"] for x in rnd["rolls"]}
        self.assertIn("LENGTH", fams, "the round-level rolls are on the trace")
        self.assertEqual(len(rnd["turns"]), len(r1.conv["turns"]))
        t0 = rnd["turns"][0]
        self.assertTrue(t0["rolls"], "each turn with its own rolls")
        self.assertTrue(all("dice" in x and "family" in x for x in t0["rolls"]))
        self.assertEqual(t0["lines"], ["t-0"])
        self.assertEqual(rnd["lines"], 4)
        self.assertEqual(one["line_ids"], ["t-i"], "only the lines it has IN this segment")
        self.assertNotIn("conversation", rnd)
        self.assertEqual(got["next"]["id"], SEG_B["id"])
        self.assertIsNone(got["previous"])
        sched = got["scheduling"]
        self.assertEqual(sched["entry"]["occurrence"], SEG_A["id"])
        self.assertEqual(sched["entry"]["state"], "aired")
        self.assertEqual(len(sched["entry"]["script"]["turns"][0]["text"]), 240, "the bulk is trimmed")
        self.assertEqual(sched["entry"]["aired"]["count"], 1)
        self.assertEqual(sched["census"]["census"]["why"]["READY"], 12)
        self.assertNotIn("task", sched["census"])
        encoded = self.client.get("/api/system3/segment/%s?scheduling=0" % quote(SEG_A["id"], safe=""), headers=AUTH)
        self.assertEqual(encoded.status_code, 200, "the page asks with the id encoded (':' as %3A)")
        self.assertEqual(encoded.json()["segment"]["id"], SEG_A["id"])
        full = self.client.get("/api/system3/segment/%s?full=1&scheduling=0" % SEG_A["id"], headers=AUTH).json()
        self.assertEqual(full["conversations"][0]["conversation"]["identity"]["conversation_id"], r1.id)
        self.assertTrue(full["conversations"][0]["conversation"]["decision_events"])
        self.assertNotIn("scheduling", full)

    def test_a_segment_not_reached_yet_answers_from_the_room_and_an_unknown_one_is_404(self):
        self.boot(SEG_B)
        now = self.client.get("/api/system3/segment/" + SEG_B["id"], headers=AUTH).json()
        self.assertFalse(now["registered"])
        self.assertEqual(now["segment"]["id"], SEG_B["id"])
        self.assertEqual(now["conversations"], [])
        self.assertEqual(now["scheduling"]["entry"]["state"], "on air")
        later = self.client.get("/api/system3/segment/" + SEG_C["id"], headers=AUTH).json()
        self.assertEqual(later["segment"]["label"], "Call")
        self.assertEqual(later["scheduling"]["entry"]["state"], "planned")
        gone = self.client.get("/api/system3/segment/hour-1:hour-99", headers=AUTH)
        self.assertEqual(gone.status_code, 404)

    def test_a_room_that_cannot_answer_says_why(self):
        self.boot(SEG_A)
        self.station["director_room"] = lambda which=0: (_ for _ in ()).throw(RuntimeError("no plan"))
        self.station.pop("director_why")
        self.station["system3_segment_block"](601, T0 + 900, "", [{"line_id": "z"}], SEG_A)
        settle()
        got = self.client.get("/api/system3/segment/" + SEG_A["id"], headers=AUTH).json()
        self.assertIsNone(got["scheduling"]["entry"])
        self.assertTrue(any("could not be read" in w for w in got["scheduling"]["why"]))
        self.assertIsNone(got["scheduling"]["census"])

    def test_what_system2_wrote_for_the_segment_is_on_its_trace(self):
        self.boot(SEG_A)
        h = self.plan_round(system2_job={"slot_id": SEG_C["id"], "job_id": SEG_C["id"] + ":prepare",
                                         "trace_id": "tr"}, bank=True)
        settle()
        self.station["system3_segment_block"](701, T0 + 1330, "", [{"line_id": "p"}], SEG_C)
        settle()
        got = self.client.get("/api/system3/segment/%s?scheduling=0" % SEG_C["id"], headers=AUTH).json()
        self.assertEqual([c["conversation_id"] for c in got["prepared_for"]], [h.id])

    def test_the_register_ages_with_the_ledger(self):
        self.boot(SEG_A)
        old = time.time() - 8 * 86400
        self.station["system3_segment_block"](801, old, "", [{"line_id": "o"}], dict(SEG_A, id="old-seg"))
        self.station["system3_segment_block"](802, time.time(), "", [{"line_id": "n"}], SEG_A)
        settle()
        system3_runtime._STORE_POOL.submit(self.rt.store.retention).result(timeout=10)
        self.assertIsNone(self.rt.store.segment_record("old-seg"))
        self.assertIsNotNone(self.rt.store.segment_record(SEG_A["id"]))
        self.assertEqual(self.rt.store.counts()["segments"], 1)

    def test_the_status_counts_the_blocks_filed(self):
        self.boot(SEG_A)
        self.station["system3_segment_block"](901, T0, "", [{"line_id": "s"}], SEG_A)
        settle()
        got = self.client.get("/api/system3/status", headers=AUTH).json()
        self.assertEqual(got["metrics"]["segment_blocks"], 1)
        self.assertEqual(got["store"]["segments"], 1)


if __name__ == "__main__":
    unittest.main()
