"""[s3-mgrtopics] The station manager's topic roulette (system3_mgrtopics.py,
tools/system3_mgrtopics_{engine,runtime,app,ui}_patch.py).

The operator, 2026-09-28: "I want a node in there rolling for him to choose a
topic at random to say to the cast downstairs from the topic database. I dont
want him saying the same things over and over. I also want the manager to have
a topics database of his own ... a sub message based on the topic that he uses
to further intimidate / ingratiate / horrify / attempt to discuss with."

  - the roll is seeded (same dice, same message) and recorded: three decision
    events (MGRTOPIC, MGRAPPROACH, MGRSUB) with every candidate, weight and die
  - anti-repeat, measured over 50 messages: no topic inside its exclusion
    window, far more distinct topics than a roll with the rest switched off
  - editing the table changes the draw; a row switched off never lands; the
    station's topics board is a source; a sub message kept to a topic
  - the runtime: seeded once into a stored config (the default config's hash
    does not move), the roll lands on the upstairs line's node and its running
    order, his history persists, decision replay still holds
  - the prompt: dj_upstairs_write's writer is handed the rolled direction
    (app test, run in the container)
"""
import asyncio
import copy
import json
import tempfile
import unittest

import system3
import system3_mgrtopics as mt
import system3_runtime

from test_system3_runtime import FakeStation, settle
from fastapi import FastAPI
from fastapi.testclient import TestClient

BOARD = [{"id": "b%d" % i, "text": "board topic number %d, about the lake" % i, "used": i % 3} for i in range(8)]


def config(board_on=True):
    cfg = system3.default_config()
    cfg["tables"] = cfg["tables"] + mt.default_tables()
    if not board_on:
        topic = next(t for t in cfg["tables"] if t["id"] == "MGRTOPIC1")
        next(c for c in topic["categories"] if c.get("source") == "board")["items"][0]["enabled"] = False
    return cfg


def table(cfg, tid):
    return next(t for t in cfg["tables"] if t["id"] == tid)


class RollTests(unittest.TestCase):
    def test_the_roll_is_seeded_and_every_draw_is_recorded(self):
        cfg = config()
        a = mt.roll(cfg, system3.DrawStream("seed-1"), BOARD)
        b = mt.roll(cfg, system3.DrawStream("seed-1"), BOARD)
        self.assertEqual((a["key"], a["approach"]["id"], a["sub"]["key"]), (b["key"], b["approach"]["id"], b["sub"]["key"]))
        self.assertEqual([e["family"] for e in a["events"]], ["MGRTOPIC", "MGRAPPROACH", "MGRSUB"])
        topic_ev = a["events"][0]
        self.assertEqual([s["stage"] for s in topic_ev["stages"]], ["category", "item"])
        for ev in a["events"]:
            for st in ev["stages"]:
                self.assertTrue(st["candidates"], ev["family"])
                self.assertTrue(all({"id", "label", "weight", "p", "why"} <= set(c) for c in st["candidates"]))
                self.assertIsNotNone(st["draw"]["dice"])
                self.assertIn(st["selected"], [c["id"] for c in st["candidates"]])
        self.assertIn(a["approach"]["id"], mt.APPROACHES)
        seeds = {mt.roll(cfg, system3.DrawStream("s%d" % i), BOARD)["key"] for i in range(40)}
        self.assertGreater(len(seeds), 10, "other dice, other topics")

    def test_anti_repeat_over_fifty_messages(self):
        cfg = config()
        got = mt.measure(cfg, "fifty", 50, BOARD)
        knobs = mt.rest_knobs(cfg)
        # no topic comes back inside its exclusion window
        self.assertGreater(got["min_gap"], knobs["exclude_last"])
        # the same roll with the rest switched off (no history read) repeats itself
        off = copy.deepcopy(cfg)
        table(off, "MGRTOPIC1")["rest"] = dict(knobs, exclude_last=0, rest_window=0, sub_exclude=0, approach_rest=1.0)
        base = mt.measure(off, "fifty", 50, BOARD)
        print("\n[s3-mgrtopics] 50 messages: distinct topics %d (rest off: %d), shortest gap %s (rest off: %s), "
              "most airings of one topic %d (rest off: %d), distinct sub messages %d (rest off: %d)"
              % (got["distinct"], base["distinct"], got["min_gap"], base["min_gap"], got["most"], base["most"],
                 got["distinct_subs"], base["distinct_subs"]))
        self.assertGreaterEqual(got["distinct"], 20)
        self.assertLessEqual(got["most"], 5)
        self.assertGreater(got["distinct"], base["distinct"])
        self.assertLess(base["min_gap"], got["min_gap"])
        # and over many seeds, never inside the window
        for s in range(10):
            self.assertGreater(mt.measure(cfg, "w%d" % s, 50, BOARD)["min_gap"], knobs["exclude_last"])

    def test_a_tiny_database_still_draws(self):
        cfg = config(board_on=False)
        topic = table(cfg, "MGRTOPIC1")
        for c in topic["categories"]:
            for it in c["items"]:
                it["enabled"] = it["id"] in ("talk_less", "pay")
        got = mt.measure(cfg, "tiny", 12)
        self.assertEqual(got["draws"], 12, "everything held out: the rested ones come back, the node never goes quiet")
        self.assertEqual(set(got["keys"]), {"own:talk_less", "own:pay"})

    def test_editing_the_table_changes_the_draw(self):
        cfg = config(board_on=False)
        before = [mt.roll(cfg, system3.DrawStream("e%d" % i))["key"] for i in range(30)]
        topic = table(cfg, "MGRTOPIC1")
        for c in topic["categories"]:
            for it in c["items"]:
                it["enabled"] = False
        topic["categories"][0]["items"].append({"id": "parking", "label": "his parking space",
                                                "text": "somebody parked in his space again", "weight": 1.0})
        after = [mt.roll(cfg, system3.DrawStream("e%d" % i)) for i in range(30)]
        self.assertTrue(all(r["key"] == "own:parking" for r in after))
        self.assertNotEqual(before, [r["key"] for r in after])
        self.assertIn("somebody parked in his space again", after[0]["direction"])
        # re-weighting an approach moves the approach draw
        sub = table(cfg, "MGRSUB1")
        for c in sub["categories"]:
            c["weight"] = 1.0 if c["id"] == "horrify" else 0.0
        self.assertTrue(all(mt.roll(cfg, system3.DrawStream("h%d" % i))["approach"]["id"] == "horrify" for i in range(20)))

    def test_a_row_switched_off_never_lands(self):
        cfg = config()
        topic = table(cfg, "MGRTOPIC1")
        off = {"consultant", "pay", "ratings"}
        for c in topic["categories"]:
            for it in c["items"]:
                if it["id"] in off:
                    it["enabled"] = False
        sub = table(cfg, "MGRSUB1")
        sub["categories"][0]["items"][0]["enabled"] = False       # intimidate: "file"
        keys, subs = set(), set()
        for s in range(8):
            got = mt.measure(cfg, "off%d" % s, 50, BOARD)
            keys |= set(got["keys"])
        for i in range(200):
            r = mt.roll(cfg, system3.DrawStream("o%d" % i), BOARD)
            keys.add(r["key"])
            subs.add(r["sub"]["key"])
        self.assertFalse({"own:" + x for x in off} & keys)
        self.assertNotIn("intimidate:file", subs)
        # and the record says why it was out
        r = mt.roll(cfg, system3.DrawStream("why"), BOARD, recent=[])
        excluded = [x for st in r["events"][0]["stages"] for x in st.get("excluded") or []]
        if r["group"]["id"] == "upstairs":
            self.assertIn("switched off in its table", [x["why"] for x in excluded])

    def test_the_station_topics_board_is_a_source(self):
        cfg = config()
        topic = table(cfg, "MGRTOPIC1")
        for c in topic["categories"]:
            if c.get("source") != "board":
                c["weight"] = 0.0
        r = mt.roll(cfg, system3.DrawStream("board"), BOARD)
        self.assertEqual(r["topic"]["source"], "board")
        self.assertTrue(r["key"].startswith("board:"))
        self.assertIn(r["topic_text"], [b["text"] for b in BOARD])
        # the least-sprung weigh most (1/(1+used)), recorded as why
        cands = r["events"][0]["stages"][1]["candidates"]
        self.assertTrue(any("sprung" in " ".join(c["why"]) for c in cands))
        # the board switched off, nothing else on: nothing to draw
        next(c for c in topic["categories"] if c.get("source") == "board")["items"][0]["enabled"] = False
        self.assertIsNone(mt.roll(cfg, system3.DrawStream("board"), BOARD))

    def test_a_sub_message_kept_to_its_topic(self):
        cfg = config(board_on=False)
        topic = table(cfg, "MGRTOPIC1")
        for c in topic["categories"]:
            for it in c["items"]:
                it["enabled"] = it["id"] in ("consultant", "pay")
        seen = {}
        for i in range(300):
            r = mt.roll(cfg, system3.DrawStream("k%d" % i))
            seen.setdefault(r["key"], set()).add(r["sub"]["id"])
        self.assertIn("consultant_shovel", seen["own:consultant"])
        self.assertFalse({"consultant_shovel", "consultant_notes", "owner_smile"} & seen["own:pay"])

    def test_the_direction_carries_topic_approach_and_sub_message(self):
        r = mt.roll(config(), system3.DrawStream("dir"), BOARD)
        for words in (r["topic_text"], r["approach"]["label"].upper(), r["sub"]["text"]):
            self.assertIn(words, r["direction"])
        self.assertNotIn("{topic}", r["direction"])
        self.assertIn(r["topic_text"], r["memo_direction"])
        self.assertIn(r["topic_text"], r["sheet"])

    def test_the_tables_validate(self):
        for t in mt.default_tables():
            out = system3.validate_table(t)
            self.assertEqual(out["family"], t["family"])
        bad = copy.deepcopy(mt.MGRSUB1)
        bad["categories"][0]["items"][0]["text"] = ""
        bad["categories"][0]["items"][0]["label"] = ""
        with self.assertRaises(ValueError):
            system3.validate_table(bad)
        t = copy.deepcopy(mt.MGRTOPIC1)
        t["rest"] = {"exclude_last": 999, "rest_factor": -3}
        out = system3.validate_table(t)
        self.assertEqual((out["rest"]["exclude_last"], out["rest"]["rest_factor"]), (mt.HISTORY_KEEP, 0.0))

    def test_the_default_config_hash_does_not_move(self):
        self.assertEqual(system3.config_hash(system3.default_config()), "d4458771c5395e72")
        self.assertFalse({"MGRTOPIC1", "MGRSUB1"} & {t["id"] for t in system3.default_config()["tables"]})


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.station["read_bombshells"] = lambda: [dict(b) for b in BOARD]
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "mgr"})
        system3_runtime._S3_ROLLS.set(None)

    def test_seeded_once_into_the_stored_config(self):
        ids = [t["id"] for t in self.rt.config["tables"]]
        self.assertIn("MGRTOPIC1", ids)
        self.assertIn("MGRSUB1", ids)
        self.assertIn("MGRTOPIC1", self.rt.config["defaults_added"])
        self.assertEqual(self.rt.add_missing_default_tables(), [], "added once")

    def test_off_means_no_roll(self):
        self.rt.settings = self.rt.apply_settings({"mode": "off"})
        self.assertIsNone(self.station["system3_manager_topic"](road="upstairs"))

    def test_the_roll_lands_on_his_line_and_its_running_order(self):
        got = self.station["system3_manager_topic"](road="upstairs")
        self.assertTrue(got["topic_text"] and got["direction"])
        self.assertEqual(self.rt.station_view()[-1]["kind"], "mgrtopic")
        h = asyncio.run(self.station["system3_direct_line"](road="upstairs", who="manager", seat="C",
                                                             dj={"host_name": "Dill", "cohost_name": "Skip"},
                                                             name="The Manager", context=got["topic_text"]))
        self.assertTrue(h and h.active)
        conv = h.conv
        fams = [e["family"] for e in conv["decision_events"] if (e.get("meta") or {}).get("key") == "manager.topic"]
        self.assertEqual(fams, ["MGRTOPIC", "MGRAPPROACH", "MGRSUB"])
        self.assertEqual(conv["mgr_topic"]["key"], got["key"])
        first = next(t for t in conv["turns"] if not t.get("split_of"))
        self.assertEqual([d["family"] for d in first["decisions"] if d["family"].startswith("MGR")], fams)
        self.assertIn(got["topic_text"], h.sheet)
        self.assertIn(got["topic_text"], conv["plan"]["sheet"])
        ev = next(e for e in conv["decision_events"] if e["family"] == "MGRTOPIC")
        self.assertEqual(ev["turn_id"], first["turn_id"])
        # decision replay holds: the road's own rolls are recorded, not re-planned
        stored = json.loads(json.dumps(conv))
        self.assertTrue(system3.replay(stored, self.rt.config)["ok"])

    def test_the_studio_chapter_is_written_from_the_topic(self):
        # live, the upstairs road's graph is on: the page opens a chapter the studio answers
        import conversation_graph
        cfg = copy.deepcopy(self.rt.config)
        st = copy.deepcopy(system3.road_structure(cfg, "upstairs"))
        st["graph"] = conversation_graph.default_graph()
        st["graph"]["enabled"] = True
        cfg.setdefault("structures", {})["upstairs"] = st
        self.rt.config = cfg
        got = self.station["system3_manager_topic"](road="upstairs")
        h = asyncio.run(self.station["system3_direct_line"](road="upstairs", who="manager", seat="C", lines=6,
                                                             dj={"host_name": "Dill", "cohost_name": "Skip"},
                                                             name="The Manager", context=got["topic_text"]))
        plan = self.station["system3_line_chapter"](h.stamp)
        self.assertIsNotNone(plan)
        self.assertGreaterEqual(plan["turns"], 3)
        self.assertGreaterEqual(len(set(plan["seats"])), 2)
        self.assertIn(got["topic_text"], plan["sheet"])
        self.assertIn(got["approach"]["label"].upper(), plan["sheet"])

    def test_his_history_persists_and_holds_repeats_out(self):
        keys = []
        for _ in range(12):
            system3_runtime._S3_ROLLS.set(None)
            keys.append(self.station["system3_manager_topic"](road="upstairs")["key"])
        k = mt.rest_knobs(self.rt.config)["exclude_last"]
        for i in range(len(keys)):
            self.assertNotIn(keys[i], keys[max(0, i - k):i])
        settle()
        saved = json.loads((self.station.root / "system3_mgrtopics.json").read_text())
        self.assertEqual(saved["topics"][:12], list(reversed(keys)))
        self.rt.__dict__.pop("mgr_hist", None)                  # a restart reads it back
        self.assertEqual(self.rt._mgr_hist()["topics"][:12], list(reversed(keys)))

    def test_an_edit_on_the_desk_changes_the_draw(self):
        topic = copy.deepcopy(next(t for t in self.rt.config["tables"] if t["id"] == "MGRTOPIC1"))
        for c in topic["categories"]:
            for it in c["items"]:
                it["enabled"] = it["id"] == "thermostat"
        r = self.client.put("/api/system3/tables/MGRTOPIC1", json=topic, headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(6):
            system3_runtime._S3_ROLLS.set(None)
            self.assertEqual(self.station["system3_manager_topic"](road="memo")["key"], "own:thermostat")


try:
    import app as _app
except Exception:  # noqa: BLE001 - the station module imports only in the container
    _app = None


@unittest.skipIf(_app is None, "app.py imports in the container")
class PromptTests(unittest.TestCase):
    ROLLED = {"key": "own:consultant", "topic_text": "a consultant is coming in",
              "approach": {"id": "horrify", "label": "Horrify", "how": "a detail too far"},
              "sub": {"key": "horrify:consultant_shovel", "id": "consultant_shovel",
                      "text": "he says the consultant brought his own shovel"},
              "direction": "\nSYSTEM 3 ROLLED THIS MESSAGE: THE MAIN TOPIC: a consultant is coming in. "
                           "YOUR APPROACH: HORRIFY. THE SUB MESSAGE: he says the consultant brought his own shovel.\n"}

    def test_the_page_writer_is_handed_the_rolled_direction(self):
        from unittest import mock
        prompts, saved, updates = [], [], []

        async def ask_model(prompt, **k):
            prompts.append(prompt)
            return "Listen to me, both of you. The consultant is here."

        async def nothing(*a, **k):
            return {}

        async def same(text, *a, **k):
            return text

        def save(text, gripe, context):
            saved.append(gripe)
            return {"id": "p1", "text": text, "gripe": gripe}

        with mock.patch.object(_app, "system3_manager_topic", lambda road="": dict(self.ROLLED), create=True), \
                mock.patch.object(_app, "system3_direct_line", None, create=True), \
                mock.patch.object(_app, "pipeline_log", lambda *a, **k: None), \
                mock.patch.object(_app, "ask_model", ask_model), \
                mock.patch.object(_app, "speakbox_semantic_seed", nothing), \
                mock.patch.object(_app, "speakbox_quote", nothing), \
                mock.patch.object(_app, "crystal_line", same), \
                mock.patch.object(_app, "upstairs_context", lambda: ""), \
                mock.patch.object(_app, "upstairs_save", save), \
                mock.patch.object(_app, "upstairs_update", lambda pid, **f: updates.append(f)), \
                mock.patch.object(_app, "s3_unrepeated", mock.Mock(side_effect=AssertionError("no gripe roll"))):
            row = asyncio.run(_app.dj_upstairs_write())
        self.assertEqual(saved, ["a consultant is coming in"])
        self.assertIn("What you are on about this time: a consultant is coming in.", prompts[0])
        self.assertIn("HORRIFY", prompts[0])
        self.assertIn("brought his own shovel", prompts[0])
        self.assertEqual(row["mgr_topic"]["key"], "own:consultant")
        self.assertTrue(any("mgr_topic" in f for f in updates))

    def test_without_a_roll_the_gripe_book_as_before(self):
        from unittest import mock
        prompts = []

        async def ask_model(prompt, **k):
            prompts.append(prompt)
            return ""

        async def nothing(*a, **k):
            return {}

        with mock.patch.object(_app, "system3_manager_topic", lambda road="": None, create=True), \
                mock.patch.object(_app, "system3_direct_line", None, create=True), \
                mock.patch.object(_app, "ask_model", ask_model), \
                mock.patch.object(_app, "speakbox_semantic_seed", nothing), \
                mock.patch.object(_app, "speakbox_quote", nothing), \
                mock.patch.object(_app, "upstairs_context", lambda: ""), \
                mock.patch.object(_app, "s3_unrepeated", lambda *a, **k: "the coffee order"):
            asyncio.run(_app.dj_upstairs_write())
        self.assertIn("What you are on about this time: the coffee order.", prompts[0])
        self.assertNotIn("SYSTEM 3 ROLLED THIS MESSAGE", prompts[0])

    def test_the_studio_reaction_knows_the_topic(self):
        said = _app._s3_manager_topic_react({"mgr_topic": dict(self.ROLLED)})
        self.assertIn("a consultant is coming in", said)
        self.assertIn("horrify", said)
        self.assertEqual(_app._s3_manager_topic_react({}), "")


if __name__ == "__main__":
    unittest.main()
