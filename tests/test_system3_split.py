"""[s3-split] The SPLIT node: a long read (an advert, the manager's page, a
speaker-box monologue) shared out among the studio by System 3's roulette,
with the Insertion list (IL1) deciding how each voice takes over - and the
caps that cut a line's words mid-word in the record.

The operator, 2026-09-28: "if the person's about to say something that's
going to exceed a minute or approach forty-five seconds, then that should be
split with another person in the studio ... A long statment or ad read or
manager read can have up to 3 splits with splits being a checkbox we can
enable to a particular message node."

Engine tests are pure; the runtime tests run System3Runtime on a temp store
behind the stand-in station (test_system3_runtime.FakeStation)."""
import asyncio
import copy
import json
import re
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_runtime
import system3_tables
from system3_store import System3Store
from test_system3_runtime import FakeStation, settle

SENTENCE = "The spot runs long tonight and nobody in the booth can stop it. "
STUDIO = [{"who": "dj", "seat": "A", "name": "Dill"}, {"who": "cohost", "seat": "B", "name": "Skip"},
          {"who": "drop", "seat": "S", "name": "Sam", "voice": "sam-voice"}]


def read_of(seconds, pace=18.9):
    """A read of about `seconds` at `pace`, whole sentences."""
    n = max(1, int(round(seconds * pace / len(SENTENCE))))
    return (SENTENCE * n).strip()


def settings(seed="split-1"):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def line_conv(config=None, seed="split-1", road="ad_spot", cid="c1"):
    config = config or system3.default_config()
    inputs = {"road": road, "seats": ["A"], "names": {"A": "Dill"}, "roles": {"A": "dj"}, "turns": 1,
              "subject": {"topic": "the break"}, "availability": {}}
    conv = system3.new_conversation(inputs, config, settings(seed), conversation_id=cid)
    system3.plan_line(conv, config, inputs)
    return conv, config


def draws(conv):
    return [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u"))
            for e in conv["decision_events"]]


class RuleTests(unittest.TestCase):
    def test_under_the_threshold_a_read_is_never_split(self):
        for secs in (5, 30, 44.5):
            r = system3.split_rule(read_of(secs), 18.9, 45, 3)
            self.assertEqual((r["want"], r["cuts"]), (1, []), secs)

    def test_over_it_the_fewest_parts_up_to_three_splits(self):
        self.assertEqual(system3.split_rule(read_of(60), 18.9, 45, 3)["want"], 2)
        self.assertEqual(system3.split_rule(read_of(100), 18.9, 45, 3)["want"], 3)
        self.assertEqual(system3.split_rule(read_of(170), 18.9, 45, 3)["want"], 4)
        self.assertEqual(system3.split_rule(read_of(400), 18.9, 45, 3)["want"], 4)   # 3 splits at most
        self.assertEqual(system3.split_rule(read_of(400), 18.9, 45, 1)["want"], 2)   # the node's own max
        r = system3.split_rule(read_of(100), 18.9, 45, 3)
        parts = system3._split_pieces(r["words"], r["cuts"])
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertLessEqual(len(p) / 18.9, 45)

    def test_cut_only_at_sentence_ends_and_nothing_is_lost(self):
        text = " ".join("Sentence number %d says something about the weather and the hour." % i for i in range(40))
        r = system3.split_rule(text, 18.9, 45, 3)
        parts = system3._split_pieces(r["words"], r["cuts"])
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts), r["words"])
        for p in parts:
            self.assertRegex(p, r"[.!?]$")
            self.assertRegex(p, r"^Sentence number \d+ ")

    def test_a_sentence_longer_than_a_part_stays_whole(self):
        text = "and then " * 200 + "the end."
        r = system3.split_rule(text, 18.9, 45, 3)
        self.assertGreater(r["want"], 1)
        self.assertEqual(r["cuts"], [])

    def test_a_title_or_an_initial_is_not_a_sentence_end(self):
        text = "Mr. Pine says hello. We met Dr. Smith at 3 a.m. today. J. R. was there. It rained."
        ends = system3.sentence_ends(text)
        cut_before = [text[:e] for e in ends]
        self.assertEqual([c.split()[-1] for c in cut_before], ["hello.", "today.", "there."])

    def test_no_cut_leaves_a_scrap(self):
        text = "Short. " + ("word " * 1100).strip() + "."
        r = system3.split_rule(text, 18.9, 45, 3)
        self.assertEqual(r["cuts"], [])          # the only sentence end is at 7 characters

    def test_the_section_validates(self):
        ok = system3.validate_split({"threshold_seconds": 40, "pace": 16, "paces": {"manager": 14},
                                     "who": {"drop": 0.5}, "max_splits": 2, "junk": 1})
        self.assertEqual((ok["threshold_seconds"], ok["pace"], ok["max_splits"]), (40, 16, 2))
        self.assertEqual(ok["who"]["drop"], 0.5)
        self.assertEqual(ok["who"]["dj"], 1.0)
        self.assertNotIn("junk", ok)
        for bad in ({"threshold_seconds": 2}, {"max_splits": 4}, {"max_splits": True}, {"pace": "fast"},
                    {"who": {"Dill!": 1}}, {"paces": {"dj": 99}}, []):
            with self.assertRaises(ValueError, msg=str(bad)):
                system3.validate_split(bad)
        self.assertEqual(system3.split_config({}), system3.DEFAULT_SPLIT)
        self.assertEqual(system3.split_config({"split": {"pace": 1000}}), system3.DEFAULT_SPLIT)


class TablesTests(unittest.TestCase):
    def test_il1_is_a_valid_default_table(self):
        il = [t for t in system3_tables.default_tables() if t["id"] == "IL1"]
        self.assertEqual(len(il), 1)
        self.assertEqual(il[0]["family"], "IL")
        system3.validate_table(il[0])
        cats = il[0]["categories"]
        self.assertGreaterEqual(len(cats), 6)
        for c in cats:
            self.assertTrue(c.get("direction"), c["id"])
            for it in c["items"]:
                self.assertTrue(it["text"].strip())
                self.assertLessEqual(len(it["text"]), 60, it)
        self.assertIn("IL1", [t["id"] for t in system3.default_config()["tables"]])

    def test_the_switch_is_on_where_the_long_reads_are(self):
        cfg = system3.default_config()
        steps = {s["id"]: s for s in cfg["structure"]["steps"]}
        self.assertTrue(steps["initial"]["splits"])
        for road, leg in (("ad_spot", "spot"), ("upstairs", "page")):
            node = system3.road_structure(cfg, road)["legs"][0]
            self.assertEqual((node["id"], node["splits"], node["max_splits"]), (leg, True, 3))
            self.assertEqual(system3_tables.validate_structure(road, system3.road_structure(cfg, road)), [])
        self.assertNotIn("splits", system3.road_structure(cfg, "station_id")["legs"][0])
        self.assertEqual(system3.split_node({"splits": True, "max_splits": 2}), {"max": 2})
        self.assertIsNone(system3.split_node({"splits": False}))

    def test_a_bad_switch_is_refused(self):
        st = copy.deepcopy(system3.road_structure(system3.default_config(), "ad_spot"))
        st["legs"][0]["max_splits"] = 5
        self.assertTrue(system3_tables.validate_structure("ad_spot", st))
        st["legs"][0].update(max_splits=2, splits="yes")
        self.assertTrue(system3_tables.validate_structure("ad_spot", st))


class SplitTurnTests(unittest.TestCase):
    def split(self, seconds=100, seed="split-1", studio=STUDIO, node=None, **kw):
        conv, config = line_conv(seed=seed)
        got = system3.split_turn(conv, config, conv["turns"][0], read_of(seconds), studio, speaker_who="dj",
                                 pace=18.9, pace_why="test", node=node or {"max": 3}, **kw)
        return conv, config, got

    def test_a_short_read_is_recorded_whole_with_no_draw(self):
        conv, config = line_conv()
        before = draws(conv)
        got = system3.split_turn(conv, config, conv["turns"][0], read_of(20), STUDIO, speaker_who="dj",
                                 pace=18.9, node={"max": 3})
        self.assertFalse(got["split"])
        ev = conv["decision_events"][-1]
        self.assertEqual((ev["family"], ev["selected"]["id"], ev["rng"]), ("SPLIT", "WHOLE", None))
        self.assertIn("not over the 45 s threshold", ev["meta"]["why"])
        self.assertEqual(draws(conv)[:-1], before)
        self.assertEqual(len(conv["turns"]), 1)
        self.assertNotIn("split_draws", conv)

    def test_a_node_without_the_box_is_not_touched(self):
        conv, config = line_conv()
        n = len(conv["decision_events"])
        got = system3.split_turn(conv, config, conv["turns"][0], read_of(100), STUDIO, speaker_who="dj")
        self.assertFalse(got["split"])
        self.assertEqual(len(conv["decision_events"]), n)

    def test_a_long_read_becomes_turns_of_its_own_in_order(self):
        conv, _config, got = self.split(100)
        self.assertTrue(got["split"])
        parts = got["parts"]
        self.assertEqual([p["part"] for p in parts], [1, 2, 3])
        self.assertEqual([t["turn_id"] for t in conv["turns"]], ["c1:t00", "c1:t00s2", "c1:t00s3"])
        self.assertEqual([t["index"] for t in conv["turns"]], [0, 1, 2])
        self.assertEqual(" ".join(p["body"] for p in parts), got["whole"])
        self.assertEqual(conv["turns"][0]["text"], parts[0]["body"])
        for p, t in zip(parts[1:], conv["turns"][1:]):
            self.assertEqual(t["split_of"], "c1:t00")
            self.assertEqual(t["text"], p["text"])
            self.assertTrue(p["text"].startswith(p["lead_in"]) and p["text"].endswith(p["body"]))
            self.assertIn("takes over", t["step_label"])
            self.assertEqual(t["leg"], "spot")
        rule = next(e for e in conv["decision_events"] if e["family"] == "SPLIT" and e["rng"] is None)
        self.assertEqual((rule["selected"]["id"], rule["selected"]["parts"]), ("SPLIT", 3))

    def test_who_is_never_the_reader_nor_the_same_voice_twice_in_a_row(self):
        seen = set()
        for i in range(40):
            conv, _config, got = self.split(170, seed="who-%d" % i)
            parts = got["parts"]
            self.assertEqual(parts[0]["who"], "dj")
            for a, b in zip(parts, parts[1:]):
                self.assertNotEqual(a["who"], b["who"])
            for ev in [e for e in conv["decision_events"] if e["family"] == "SPLIT" and e["rng"]]:
                st = ev["stages"][0]
                self.assertNotIn(st["selected"], [x["id"] for x in st["excluded"]])
                self.assertTrue(st["candidates"])
                self.assertEqual(ev["rng"]["seed"], conv["seed"] + "|split")
            seen.update(p["who"] for p in parts[1:])
        self.assertEqual(seen, {"dj", "cohost", "drop"})      # the reader may come back after another voice

    def test_the_next_voice_never_takes_the_last_part(self):
        for i in range(30):
            conv, config = line_conv(seed="next-%d" % i)
            got = system3.split_turn(conv, config, conv["turns"][0], read_of(60), STUDIO, speaker_who="dj",
                                     pace=18.9, node={"max": 3}, next_who="cohost")
            self.assertEqual(got["parts"][-1]["who"], "drop")

    def test_nobody_else_in_the_studio_reads_it_whole(self):
        conv, _config, got = self.split(100, studio=[STUDIO[0]])
        self.assertFalse(got["split"])
        self.assertIn("nobody else in the studio", got["why"])
        self.assertEqual(conv["turns"][0]["text"], got["whole"])
        self.assertEqual(len(conv["turns"]), 1)

    def test_the_insertion_list_is_drawn_and_recorded(self):
        conv, config, got = self.split(100)
        ils = [e for e in conv["decision_events"] if e["family"] == "IL"]
        self.assertEqual(len(ils), 2)
        for ev, p in zip(ils, got["parts"][1:]):
            self.assertEqual([s["stage"] for s in ev["stages"]][-2:], ["category", "item"])
            self.assertEqual(ev["rng"]["seed"], conv["seed"] + "|split:IL")
            self.assertEqual(ev["selected"]["table"], "IL1")
            self.assertTrue(p["lead_in"])
            self.assertNotIn("{prev}", p["lead_in"])
            turn = next(t for t in conv["turns"] if t["turn_id"] == p["turn_id"])
            self.assertEqual([d["family"] for d in turn["decisions"]], ["SPLIT", "IL"])
            self.assertEqual(turn["directions"][0]["family"], "IL")
        # a switched-off insertion list: the part carries on with no lead-in, and says so
        config = copy.deepcopy(config)
        for t in config["tables"]:
            if t["id"] == "IL1":
                t["enabled"] = False
        conv2, _ = line_conv(config=config, seed="il-off")
        got2 = system3.split_turn(conv2, config, conv2["turns"][0], read_of(60), STUDIO, speaker_who="dj",
                                  pace=18.9, node={"max": 3})
        self.assertTrue(got2["split"])
        self.assertEqual(got2["parts"][1]["lead_in"], "")
        self.assertTrue([e for e in conv2["decision_events"] if e["family"] == "IL" and e["meta"].get("empty")])

    def test_the_split_rolls_on_its_own_stream(self):
        a, config = line_conv(seed="stream-1")
        b, _ = line_conv(seed="stream-1")
        self.assertEqual(draws(a), draws(b))
        plan_draws, main = draws(a), a["draws"]
        system3.split_turn(a, config, a["turns"][0], read_of(100), STUDIO, speaker_who="dj", pace=18.9,
                           node={"max": 3})
        self.assertEqual(draws(a)[:len(plan_draws)], plan_draws)
        self.assertEqual(a["draws"], main)                       # the plan's stream never moved
        self.assertEqual(a["split_draws"], 2)
        # the switch alone moves no draw of the plan: the same seed with every box unticked
        off = system3.default_config()
        off["structures"] = copy.deepcopy(system3_tables.default_structures())
        for st in off["structures"].values():
            for leg in st.get("legs") or []:
                leg.pop("splits", None)
                leg.pop("max_splits", None)
        c, _ = line_conv(config=off, seed="stream-1")
        self.assertEqual([x[:3] for x in draws(c)], [x[:3] for x in plan_draws])

    def test_decision_replay_rolls_the_split_again(self):
        conv, config, got = self.split(170, seed="replay-1")
        self.assertTrue(got["split"])
        stored = json.loads(json.dumps(conv))
        rp = system3.replay(stored, config)
        self.assertTrue(rp["ok"], rp.get("why"))
        self.assertEqual(rp["events"], len(conv["decision_events"]))

    def test_a_whole_take_made_ahead_is_still_split(self):
        conv, _config, got = self.split(100, prepared=True)
        self.assertTrue(got["split"])
        rule = next(e for e in conv["decision_events"] if e["family"] == "SPLIT" and e["rng"] is None)
        self.assertTrue(rule["meta"]["prepared"])
        self.assertIn("made ahead", rule["meta"]["rule"])

    def test_the_weights_are_the_split_sections(self):
        conv, config = line_conv(seed="w")
        config = copy.deepcopy(config)
        config["split"] = system3.validate_split({"who": {"cohost": 0, "drop": 1}})
        for i in range(10):
            c, _ = line_conv(config=config, seed="w-%d" % i)
            got = system3.split_turn(c, config, c["turns"][0], read_of(60), STUDIO, speaker_who="dj",
                                     pace=18.9, node={"max": 3})
            self.assertEqual(got["parts"][1]["who"], "drop")
            ev = [e for e in c["decision_events"] if e["family"] == "SPLIT" and e["rng"]][0]
            self.assertIn("cohost", [x["id"] for x in ev["stages"][0]["excluded"]])


class PassageTests(unittest.TestCase):
    def test_a_monologue_is_shared_out_in_the_running_order(self):
        config = system3.default_config()
        inputs = {"road": "banter", "seats": ["A", "B", "D"], "turns": 6,
                  "names": {"A": "Dill", "B": "Skip", "D": "Guest"}, "roles": {"A": "dj", "B": "cohost", "D": "third"},
                  "subject": {"topic": "a passage"}, "availability": {"speakbox": True},
                  "speakerbox_rates": {"prepend": 0.0, "append": 0.0, "full": 0.0}}
        conv = system3.plan_scene(inputs, config, settings("passage"), conversation_id="p1")
        first = conv["turns"][0]
        first["speakerbox"] = [{"mark": "full", "mode": "FULL_SWATH", "material": {"file": "x.md", "text": read_of(80)}}]
        nxt = conv["turns"][1]
        people = [{"who": "dj", "seat": "A", "name": "Dill"}, {"who": "cohost", "seat": "B", "name": "Skip"},
                  {"who": "third", "seat": "D", "name": "Guest"}]
        who0 = {"A": "dj", "B": "cohost", "D": "third"}[first["speaker"]]
        next_who = {"A": "dj", "B": "cohost", "D": "third"}[nxt["speaker"]]
        got = system3.split_turn(conv, config, first, read_of(80), people, speaker_who=who0, pace=18.9,
                                 next_who=next_who, node={"max": 3}, mode="passage")
        self.assertTrue(got["split"])
        part = conv["turns"][1]
        self.assertEqual(part["split_of"], first["turn_id"])
        self.assertEqual(part["status"], "planned")
        self.assertNotEqual(part["who"], next_who)
        first["speakerbox"][0]["material"]["text"] = got["parts"][0]["body"]
        sheet = system3.render_sheet(conv)
        self.assertIn("TAKES THE PASSAGE OVER from %s" % first["name"], sheet)
        self.assertIn("stops there, mid-read", sheet)
        self.assertIn(json.dumps(got["parts"][1]["body"]), sheet)
        self.assertIn(json.dumps(got["parts"][0]["body"]), sheet)


class CapTests(unittest.TestCase):
    def test_the_engine_keeps_a_line_whole(self):
        conv, _config = line_conv()
        long = read_of(150)
        self.assertGreater(len(long), 2000)
        system3.observe(conv, 0, long)
        self.assertEqual(conv["turns"][0]["text"], long)

    def test_the_lines_table_keeps_a_line_whole(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        store = System3Store(tmp.name + "/s3.sqlite3")
        self.addCleanup(store.close)
        long = read_of(150)
        store.add_lines([{"line_id": "L1", "conversation_id": "c", "turn_id": "c:t00", "who": "dj", "text": long}])
        self.assertEqual(store.line("L1")["text"], long)


class RuntimeSplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.app = FastAPI()
        system3_runtime.install(self.app, self.station)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.assertTrue(self.rt.ready)
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "rt-split"})

    def line(self, road="ad_spot", who="dj", text=""):
        h = asyncio.run(self.station["system3_direct_line"](road=road, who=who, dj={"host_name": "Dill"},
                                                              context="the break"))
        self.station["system3_bind_line"](h, text)
        return h

    def test_an_advert_read_is_shared_out_with_stamps_of_its_own(self):
        text = read_of(100)
        h = self.line(text=text)
        self.assertEqual(h.conv["turns"][0]["split_node"], {"max": 3})
        self.assertEqual(h.conv["turns"][0]["text"], " ".join(text.split()))    # bound whole: no 1,500 cap
        dj = {"host_name": "Dill", "cohost_name": "Skip", "drop_voice": "sam-voice", "sfxguy_name": "Sam"}
        got = self.station["system3_split_line"](dict(h.stamp), text, who="dj", dj=dj, handle=h, kind="ad")
        self.assertTrue(got["split"])
        parts = got["parts"]
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0]["stamp"]["turn_id"], h.stamp["turn_id"])
        self.assertEqual(len({p["stamp"]["turn_id"] for p in parts}), 3)
        for p in parts:
            self.assertEqual(p["stamp"]["conversation_id"], h.stamp["conversation_id"])
            self.assertEqual(p["stamp"]["split"]["of"], 3)
            self.assertEqual(p["stamp"]["mode"], "active")
        sam = [p for p in parts if p["who"] == "drop"]
        for p in sam:
            self.assertEqual((p["seat"], p["voice"], p["name"]), ("S", "sam-voice", "Sam"))
        self.assertEqual(self.rt.metrics["splits"], 1)
        # the ways in it drew rest for the next reads (a quarter at the next IL draw)
        used = ["IL:" + d["item"] for t in h.conv["turns"] for d in t["decisions"] if d["family"] == "IL"]
        self.assertTrue(used and all(k in self.rt.recent_used() for k in used))
        # a second ask of the same line splits nothing more
        self.assertIsNone(self.station["system3_split_line"](dict(h.stamp), text, who="dj", dj=dj, handle=h))
        settle()
        stored = self.client.get("/api/system3/conversation/" + h.id, headers={"Authorization": "Bearer k"}).json()
        self.assertEqual([t["turn_id"] for t in stored["turns"]], [p["turn_id"] for p in parts])
        self.assertTrue(stored["splits"])

    def test_the_studio_is_whoever_is_in(self):
        people = system3_runtime.System3Runtime._studio({"host_name": "Dill", "cohost_name": "Skip"}, away="cohost")
        self.assertEqual([p["who"] for p in people], ["dj"])
        people = system3_runtime.System3Runtime._studio({"third_name": "Guest", "drop_voice": "v"})
        self.assertEqual([p["who"] for p in people], ["dj", "cohost", "third", "drop"])

    def test_a_short_read_is_whole_and_says_why(self):
        h = self.line(text=read_of(20))
        got = self.station["system3_split_line"](dict(h.stamp), read_of(20), who="dj", dj={}, handle=h)
        self.assertEqual(got["split"], False)
        self.assertIn("not over", got["why"])

    def test_a_road_whose_box_is_not_ticked_is_left_alone(self):
        h = self.line(road="station_id", who="drop", text=read_of(100))
        self.assertNotIn("split_node", h.conv["turns"][0])
        self.assertIsNone(self.station["system3_split_line"](dict(h.stamp), read_of(100), who="drop", dj={}, handle=h))

    def test_the_voice_pace_is_measured_and_the_operator_outranks_it(self):
        self.assertEqual(self.rt._pace_for("dj")[0], 18.9)
        for _ in range(8):
            self.rt.note_pace("dj", 300, 20.0)                  # 15 characters a second
        pace, why = self.rt._pace_for("dj")
        self.assertAlmostEqual(pace, 15.0, places=1)
        self.assertIn("measured", why)
        self.rt.note_pace("dj", 162, 2.43)                       # a fragment teaches nothing
        self.assertAlmostEqual(self.rt._pace_for("dj")[0], 15.0, places=1)
        cfg = copy.deepcopy(self.rt.config)
        cfg["split"] = system3.validate_split({"paces": {"dj": 20}})
        self.rt.config = cfg
        self.assertEqual(self.rt._pace_for("dj"), (20.0, "the split section's pace for dj"))

    def test_the_section_is_saved_from_the_desk_and_shown(self):
        k = {"Authorization": "Bearer k"}
        r = self.client.put("/api/system3/config/section/split", json={"threshold_seconds": 40}, headers=k)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["split"]["threshold_seconds"], 40)
        self.assertEqual(self.client.put("/api/system3/config/section/split", json={"max_splits": 9},
                                         headers=k).status_code, 400)
        view = self.client.get("/api/system3/config", headers=k).json()
        cfg = view.get("config") or view
        self.assertEqual(cfg["split"]["threshold_seconds"], 40)

    def test_a_saved_cycle_with_a_bad_switch_is_refused(self):
        k = {"Authorization": "Bearer k"}
        steps = copy.deepcopy(self.rt.config["structure"]["steps"])
        steps[0]["max_splits"] = 7
        self.assertEqual(self.client.put("/api/system3/structure", json={"steps": steps}, headers=k).status_code, 400)
        steps[0]["max_splits"] = 2
        self.assertEqual(self.client.put("/api/system3/structure", json={"steps": steps}, headers=k).status_code, 200)

    def test_the_switch_goes_on_once_for_a_config_saved_before_it(self):
        old = system3.default_config()
        for st in [old["structure"]] + [old["structures"][r] for r in ("ad_spot", "upstairs")]:
            for n in st.get("steps") or st.get("legs") or []:
                n.pop("splits", None)
                n.pop("max_splits", None)
        old["structures"]["upstairs"]["legs"][0]["splits"] = False      # the operator unticked this one
        self.rt.config = old
        done = self.rt.add_split_defaults()
        self.assertEqual(sorted(done), ["ad_spot/spot", "banter/initial"])
        self.assertIn("SPLIT_NODES", self.rt.config["defaults_added"])
        self.assertIs(self.rt.config["structures"]["upstairs"]["legs"][0]["splits"], False)
        self.assertTrue(self.rt.config["structures"]["ad_spot"]["legs"][0]["splits"])
        self.assertEqual(self.rt.add_split_defaults(), [])            # once
        self.assertEqual(self.rt.store.config()["structures"]["ad_spot"]["legs"][0]["splits"], True)

    def test_a_round_monologue_is_shared_out_before_the_sheet_is_written(self):
        passage = read_of(70)

        async def quote(exclude="", most=9, cap=0, rid="", only="", tinted=True):
            return {"file": "43d.md", "text": passage, "lines": [passage[:60]], "mind": ""}

        self.station["speakbox_quote"] = quote
        cfg = copy.deepcopy(self.rt.config)
        cfg["speakerbox"]["monologue_chars"] = 2000
        self.rt.config = cfg
        dj = {"host_name": "Dill", "cohost_name": "Skip", "third_name": "Guest",
              "speakbox_full_swath_rate": 1.0, "speakbox_prepend_rate": 0.0, "speakbox_append_rate": 0.0}
        h = asyncio.run(self.station["system3_direct_banter"](lines=6, bank=True, dj=dj, seats=["A", "B", "D"],
                                                                seed_text="", seed_file="", angle=""))
        self.assertIsNotNone(h)
        turn0 = h.conv["turns"][0]
        full = [sb for sb in turn0.get("speakerbox") or [] if sb.get("mode") == "FULL_SWATH"]
        if not full or not (full[0].get("material") or {}).get("text"):
            self.skipTest("the full-swath roll did not land on this seed")
        parts = [t for t in h.conv["turns"] if t.get("split_of") == turn0["turn_id"]]
        self.assertTrue(parts, "a 70 s monologue on a ticked step is shared out")
        self.assertIn("TAKES THE PASSAGE OVER", h.sheet)
        self.assertEqual(h.turns, len(h.conv["turns"]))
        self.assertEqual(h.conv["timing"]["turn_budget"], len(h.conv["turns"]))
        nxt = h.conv["turns"][parts[-1]["index"] + 1] if parts[-1]["index"] + 1 < len(h.conv["turns"]) else None
        if nxt:
            self.assertNotEqual(parts[-1]["speaker"], nxt["speaker"])


if __name__ == "__main__":
    unittest.main()
