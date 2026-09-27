"""[s3-roads] Every road on the station is System 3's: the register, one
structure per road, the SFX Guy's node on every host turn, single-voice
lines through the line hook with a LINE draw over the road's own list,
and the origin of every line on the status and the ledger."""
import asyncio
import copy
import json
import tempfile
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_runtime
import system3_tables
from test_system3_runtime import FakeStation, ctx, settle


def settings(**over):
    raw = {"mode": "active", "test_seed": "roads-1"}
    raw.update(over)
    return system3.normalise_settings(raw)


def inputs(road, **over):
    base = {"road": road, "seats": ["A", "B"], "turns": 6,
            "subject": {"topic": "the hour", "keywords": ["hour"]}, "availability": {},
            "sfxguy": {"rate": 100, "warp": 35, "voice": True, "every_units": 2}}
    base.update(over)
    return base


class RegisterTests(unittest.TestCase):
    def test_every_road_that_speaks_is_on_the_register_and_directed(self):
        ids = [r["id"] for r in system3_tables.ROAD_REGISTER]
        for road in ("banter", "caller", "recap", "ad", "news", "manager", "memo", "gallery", "mixtape",
                     "open_show", "fan_mail", "guest", "sfxguy", "track_talk", "station_id", "upstairs",
                     "interject", "ad_spot"):
            self.assertIn(road, ids)
        for r in system3_tables.ROAD_REGISTER:
            self.assertTrue(r.get("writer") and r.get("hook") and r.get("what"), r["id"])
            self.assertNotIn("directed", r, "no road is registered as an exception")

    def test_every_conversation_road_has_a_valid_structure(self):
        structures = system3_tables.default_structures()
        for road in system3.ROADS:
            if road == "banter":
                continue
            self.assertIn(road, structures, road)
            self.assertEqual(system3_tables.validate_structure(road, structures[road]), [], road)
        for road in system3_tables.LINE_ROADS:
            self.assertEqual(structures[road]["kind"], "line")
            self.assertEqual(len(structures[road]["legs"]), 1)

    def test_road_modes_cover_every_road(self):
        s = settings(mode="active_selected_roads", roads=["recap", "banter"])
        self.assertEqual(system3.road_mode(s, "recap"), "active")
        self.assertEqual(system3.road_mode(s, "news"), "shadow")
        self.assertEqual(system3.road_mode(settings(), "track_talk"), "active")
        self.assertEqual(system3.road_mode(settings(), "nonesuch"), "off")


class LegsTests(unittest.TestCase):
    def test_a_recap_is_planned_from_its_legs(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("recap"), config, settings(), conversation_id="recap1")
        system3.plan_legs(conv, config, road="recap")
        legs = [t["leg"] for t in conv["turns"]]
        self.assertEqual(legs[0], "open")
        self.assertEqual(legs[1], "first")
        self.assertEqual(legs[-1], "land")
        self.assertTrue(all(x == "next" for x in legs[2:-1]))
        seats = [t["speaker"] for t in conv["turns"]]
        self.assertTrue(all(seats[i] != seats[i + 1] for i in range(len(seats) - 1)), seats)
        self.assertTrue(all(t.get("performance", {}).get("emotion") for t in conv["turns"]))
        sheet = system3.render_legs_sheet(conv)
        self.assertIn("THE RUNNING ORDER OF THIS RECAP", sheet)
        self.assertIn("OPENS THE RECAP", sheet)
        self.assertIn("[Say it in", sheet)
        self.assertEqual(conv["road_structure"]["road"], "recap")

    def test_the_budget_stays_inside_the_structure(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("ad", turns=30), config, settings(), conversation_id="ad1")
        system3.plan_legs(conv, config, road="ad")
        self.assertLessEqual(len(conv["turns"]), 8)
        conv = system3.new_conversation(inputs("memo", turns=3), config, settings(), conversation_id="memo1")
        system3.plan_legs(conv, config, road="memo")
        self.assertGreaterEqual(len(conv["turns"]), 3)
        seats = [t["speaker"] for t in conv["turns"]]
        self.assertTrue(all(seats[i] != seats[i + 1] for i in range(len(seats) - 1)), seats)

    def test_a_road_with_no_legs_falls_back_to_the_cycle(self):
        config = system3.default_config()
        # an emptied structure falls back to the road's default legs (a
        # config saved before them has none); a road with no legs at all
        # is planned as the banter cycle
        config["structures"]["recap"] = {"legs": []}
        conv = system3.new_conversation(inputs("recap"), config, settings(), conversation_id="recap2")
        system3.plan_legs(conv, config, road="recap")
        self.assertEqual(conv["road_structure"]["id"], "recap_legs")
        conv = system3.new_conversation(inputs("nonesuch"), config, settings(), conversation_id="recap3")
        system3.plan_legs(conv, config, road="nonesuch")
        self.assertTrue(conv["turns"])
        self.assertNotIn("road_structure", conv)

    def test_an_edited_leg_reaches_the_sheet(self):
        config = system3.default_config()
        config["structures"]["news"]["legs"][0]["act"] = "THE LEAD, sung."
        conv = system3.new_conversation(inputs("news"), config, settings(), conversation_id="news1")
        system3.plan_legs(conv, config, road="news")
        self.assertIn("THE LEAD, sung.", system3.render_legs_sheet(conv))


class WindowTests(unittest.TestCase):
    """[s3-window] the segment editor's powers: variants, pins, the budget roll."""

    def test_a_variant_rolls_and_is_recorded(self):
        config = system3.default_config()
        base = config["structures"]["news"]
        config["structures"]["news~v1"] = {**base, "id": "news~v1", "label": "News B", "variant_of": "news",
                                          "weight": 1e9, "enabled": True}
        conv = system3.new_conversation(inputs("news"), config, settings(), conversation_id="newsv")
        system3.plan_legs(conv, config, road="news")
        self.assertEqual(conv["variant_roll"]["structure"], "news~v1")
        ev = [e for e in conv["decision_events"] if e["family"] == "VARIANT"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["selected"]["of"], 2)
        self.assertIsNotNone(ev[0]["rng"])
        # switched off, it is not on the table and nothing is rolled
        config["structures"]["news~v1"]["enabled"] = False
        conv2 = system3.new_conversation(inputs("news"), config, settings(), conversation_id="newsv2")
        system3.plan_legs(conv2, config, road="news")
        self.assertNotIn("variant_roll", conv2)
        self.assertFalse([e for e in conv2["decision_events"] if e["family"] == "VARIANT"])

    def test_a_pinned_draw_is_recorded_without_a_roll(self):
        config = system3.default_config()
        es = next(it["id"] for t in config["tables"] if t["family"] == "ES"
                  for c in t["categories"] for it in c["items"])
        config["structures"]["news"]["legs"][0]["draws"] = [{"family": "ES", "fixed": es}]
        conv = system3.new_conversation(inputs("news"), config, settings(), conversation_id="newsf")
        system3.plan_legs(conv, config, road="news")
        first = [e for e in conv["decision_events"] if e["family"] == "ES" and e["turn_index"] == 0]
        self.assertTrue(first)
        self.assertIsNone(first[0]["rng"])
        self.assertEqual(first[0]["selected"]["id"], es)
        self.assertEqual(first[0]["meta"]["authority"], "fixed")
        self.assertEqual(first[0]["stages"][0]["stage"], "fixed")

    def test_a_slot_sized_round_rolls_its_length_in_the_segment_band(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("banter", turns=8, target_seconds=200.0, turn_seconds=10.0, budget_roll=True),
                                        config, settings(), conversation_id="len1")
        system3.plan_more(conv, config)
        roll = conv["length_roll"]
        self.assertTrue(8 <= roll["turns"] <= 12, roll)          # never shorter than the slot; at most 1.5x
        self.assertEqual(conv["timing"]["turn_budget"], roll["turns"])
        ev = [e for e in conv["decision_events"] if e["family"] == "LENGTH"]
        self.assertEqual(len(ev), 1)
        self.assertIn("fills the segment", ev[0]["stages"][0]["rule"])
        # without the runtime saying the slot gave a budget, the size is the obligation it was
        conv2 = system3.new_conversation(inputs("banter", turns=8, target_seconds=200.0, turn_seconds=10.0),
                                         config, settings(), conversation_id="len2")
        system3.plan_more(conv2, config)
        self.assertNotIn("length_roll", conv2)


class SfxGuyNodeTests(unittest.TestCase):
    def test_his_node_rolls_on_every_host_turn_at_the_dial(self):
        config = system3.default_config()
        conv = system3.plan_scene(inputs("banter", turns=8), config, settings(), conversation_id="guy1")
        nodes = [t["sfxguy"] for t in conv["turns"]]
        self.assertTrue(all(n and n["event_id"] for n in nodes))
        self.assertTrue(all(n["speak"] for n in nodes), "at rate 100 he always pipes up")
        self.assertTrue(all(n["kind"] in ("news", "reaction", "quip") for n in nodes))
        self.assertTrue(all(len(n["order"]) == 3 for n in nodes))
        ev = [e for e in conv["decision_events"] if e["family"] == "SFXGUY"]
        self.assertEqual(len(ev), len(conv["turns"]))
        self.assertEqual(ev[0]["stages"][0]["stage"], "dice")
        self.assertEqual(ev[0]["stages"][1]["stage"], "item")
        self.assertEqual({c["id"] for c in ev[0]["stages"][1]["candidates"]}, {"news", "reaction", "quip"})
        quiet = system3.plan_scene(inputs("banter", turns=8, sfxguy={"rate": 0, "warp": 35, "voice": True}),
                                   config, settings(), conversation_id="guy2")
        self.assertTrue(all(not t["sfxguy"]["speak"] for t in quiet["turns"]))

    def test_no_voice_no_node_and_never_over_a_caller(self):
        config = system3.default_config()
        conv = system3.plan_scene(inputs("banter", sfxguy={"voice": False}), config, settings(), conversation_id="guy3")
        self.assertTrue(all(t["sfxguy"] is None for t in conv["turns"]))
        self.assertFalse([e for e in conv["decision_events"] if e["family"] == "SFXGUY"])
        conv = system3.new_conversation(inputs("caller", seats=["A", "C"]), config, settings(), conversation_id="guy4")
        conv["inputs"]["call"] = {"first": "Mo", "name": "Mo Bell", "other": "Skip"}
        system3.plan_call(conv, config)
        for t in conv["turns"]:
            if t["speaker"] == "C":
                self.assertFalse(t["sfxguy"]["speak"])
                self.assertEqual(t["sfxguy"]["why"], "never over a caller")

    def test_his_numbers_leave_the_rounds_draws_alone(self):
        config = system3.default_config()
        a = system3.plan_scene(inputs("banter", sfxguy={"voice": False}), config, settings(), conversation_id="same")
        b = system3.plan_scene(inputs("banter"), config, settings(), conversation_id="same")
        strip = lambda c: [[d.get("item") for d in t["decisions"]] for t in c["turns"]]
        self.assertEqual(strip(a), strip(b))
        self.assertEqual(system3.replay(b, config)["ok"], True)

    def test_the_stamp_carries_his_node(self):
        config = system3.default_config()
        conv = system3.plan_scene(inputs("banter"), config, settings(), conversation_id="guy5")
        stamp = system3.turn_stamp(conv, conv["turns"][0])
        self.assertEqual(set(stamp["sfxguy"]), {"speak", "kind", "order", "event_id"})


class CutTests(unittest.TestCase):
    def test_a_passage_ends_at_a_sentence_end(self):
        text = "The van was gone. The raccoon had the keys, and nobody argued with it. Then the rain came down hard on the lot."
        self.assertEqual(system3.sentence_cut(text, 60), "The van was gone.")
        self.assertEqual(system3.sentence_cut(text, 80), "The van was gone. The raccoon had the keys, and nobody argued with it.")
        self.assertEqual(system3.sentence_cut(text, 500), text)
        # no sentence end in reach: a clause break, then a word
        run = "and then he said that the whole thing was a set up, which nobody believed at the time because"
        got = system3.sentence_cut(run, 60)
        self.assertEqual(got, "and then he said that the whole thing was a set up")
        wordy = "one two three four five six seven eight nine ten eleven twelve"
        got = system3.sentence_cut(wordy, 20)
        self.assertTrue(len(got) <= 20 and not got.endswith(" ") and wordy.startswith(got))
        self.assertEqual(system3.sentence_cut("  spaced   out  ", 100), "spaced out")
        self.assertEqual(system3.sentence_cut("", 10), "")

    def test_a_sheet_never_quotes_a_passage_cut_mid_sentence(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("caller", seats=["A", "C"]), config, settings(), conversation_id="cut1")
        conv["inputs"]["call"] = {"first": "Mo", "name": "Mo Bell", "other": "Skip",
                                  "speakerbox": "First sentence here. " * 30 + "A trailing fragment without an end"}
        system3.plan_call(conv, config)
        sheet = system3.render_call_sheet(conv)
        self.assertIn("First sentence here.", sheet)
        self.assertNotIn("fragment without", sheet)


class LengthTests(unittest.TestCase):
    def test_a_free_rounds_length_is_a_recorded_roll(self):
        config = system3.default_config()
        conv = system3.plan_scene(inputs("banter", turns=12, lines_rolled=True, lines_min=6, lines_max=14, lines_base=8),
                                  config, settings(), conversation_id="len1")
        roll = conv["length_roll"]
        self.assertTrue(6 <= roll["rolled"] <= 14)
        self.assertEqual(roll["turns"], max(2, min(40, 12 + (roll["rolled"] - 8))))
        self.assertEqual(len(conv["turns"]), roll["turns"])
        ev = [e for e in conv["decision_events"] if e["family"] == "LENGTH"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["stages"][0]["stage"], "dice")
        self.assertEqual(system3.replay(conv, config)["ok"], True)
        sized = system3.plan_scene(inputs("banter", turns=12), config, settings(), conversation_id="len2")
        self.assertNotIn("length_roll", sized)
        self.assertEqual(len(sized["turns"]), 12)


class LineTests(unittest.TestCase):
    def test_a_stock_line_is_a_recorded_draw_over_the_list(self):
        config = system3.default_config()
        cands = [{"id": "a", "text": "Hold on, a memo.", "weight": 1.0}, {"id": "b", "text": "Wait, upstairs wants a word.", "weight": 1.0},
                 {"id": "c", "text": "never", "weight": 0.0}]
        conv = system3.new_conversation(inputs("interject", seats=["A"], candidates=cands), config, settings(), conversation_id="line1")
        system3.plan_line(conv, config)
        self.assertEqual(len(conv["turns"]), 1)
        self.assertEqual(conv["turns"][0]["leg"], "line")
        choice = conv["line_choice"]
        self.assertIn(choice["id"], ("a", "b"))
        ev = [e for e in conv["decision_events"] if e["family"] == "LINE"][0]
        self.assertEqual(ev["stages"][0]["of"], 2)
        self.assertEqual([x["id"] for x in ev["stages"][0]["excluded"]], ["c"])
        self.assertEqual(system3.replay(conv, config)["ok"], True)

    def test_a_written_line_has_a_leg_and_a_clause(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("track_talk", seats=["A"]), config, settings(), conversation_id="line2")
        system3.plan_line(conv, config)
        self.assertEqual(conv["turns"][0]["leg"], "link")
        self.assertIn("HOW THIS RECORD LINK IS SAID", system3.render_legs_sheet(conv))
        self.assertNotIn("line_choice", conv)


class RuntimeRoadTests(unittest.TestCase):
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
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "rt-roads"})

    def test_a_recap_round_is_planned_as_a_recap(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(road="recap", lines=6, angle="the recap", own_material=True, seed_text="")))
        self.assertIsNotNone(h)
        self.assertEqual(h.conv["identity"]["road_kind"], "recap")
        self.assertIn("THE RUNNING ORDER OF THIS RECAP", h.sheet)
        self.assertTrue(h.rolls is not None)
        self.assertEqual(system3.summary(h.conv)["road"], "recap")

    def test_a_memo_is_directed_and_an_unknown_road_is_banter(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(road="memo", whole=True, lines=3, angle="a memo", own_material=True, seed_text="")))
        self.assertEqual(h.conv["identity"]["road_kind"], "memo")
        self.assertIn("MEMO", h.sheet)
        h2 = asyncio.run(self.station["system3_direct_banter"](**ctx(road="nonesuch")))
        self.assertEqual(h2.conv["identity"]["road_kind"], "banter")

    def test_a_line_road_draws_over_its_list_and_stamps_the_row(self):
        h = asyncio.run(self.station["system3_direct_line"](
            road="interject", who="dj", dj={"host_name": "Caine"}, context="a memo is coming",
            candidates=["Hold on, a memo.", "Wait - upstairs wants a word."], candidates_from="MANAGER_BREAK_LINES"))
        self.assertIsNotNone(h)
        self.assertTrue(h.active)
        self.assertIn(h.line, ["Hold on, a memo.", "Wait - upstairs wants a word."])
        self.assertIn(h.choice, (0, 1))
        self.assertEqual(h.stamp["road"], "interject")
        self.assertTrue(h.stamp["conversation_id"] and h.stamp["turn_id"])
        self.station["system3_bind_line"](h, h.line)
        settle()
        got = self.client.get("/api/system3/conversation/" + h.stamp["conversation_id"], headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(got["identity"]["road_kind"], "interject")
        self.assertEqual(got["turns"][0]["text"], h.line)
        self.assertEqual([e["family"] for e in got["decision_events"] if e["family"] == "LINE"], ["LINE"])

    def test_a_line_road_pick_at_air_is_recorded(self):
        h = asyncio.run(self.station["system3_direct_line"](road="station_id", who="drop", dj={}, context="Pine FM"))
        i = h.pick("drop_liner", ["one", "two", "three"])
        self.assertIn(i, (0, 1, 2))
        self.station["system3_bind_line"](h, "one")
        self.assertEqual(h.conv["line_draws"][0]["pool"], "drop_liner")
        self.assertEqual(h.conv["line_draws"][0]["of"], 3)
        self.assertIn("HOW THIS STATION ID IS SAID", h.sheet)

    def test_off_and_shadow_leave_the_station_its_own_random(self):
        self.rt.settings = self.rt.apply_settings({"mode": "off"})
        self.assertIsNone(asyncio.run(self.station["system3_direct_line"](road="interject", who="dj", dj={}, candidates=["a", "b"])))
        self.rt.settings = self.rt.apply_settings({"mode": "shadow"})
        h = asyncio.run(self.station["system3_direct_line"](road="interject", who="dj", dj={}, candidates=["a", "b"]))
        self.assertFalse(h.active)
        self.assertEqual(h.sheet, "")

    def test_his_node_directs_the_air_once_per_turn(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(dj={"host_name": "Caine", "cohost_name": "Skip", "drop_voice": "guy",
                                                                       "sfxguy_rate": 100, "sfxguy_warp": 40})))
        script = "\n".join("%s: Line number %d of this round, said plainly." % (t["speaker"], t["index"]) for t in h.conv["turns"])
        entry = {"script": script, "caller_name": ""}
        self.station["system3_bind_entry"](entry, h)
        text = "Line number 0 of this round, said plainly."
        d = self.station["system3_sfxguy_direction"](entry, "dj", text)
        self.assertIsNotNone(d)
        self.assertTrue(d["speak"])
        self.assertEqual(d["turn"], 0)
        self.assertIn(d["kind"], ("news", "reaction", "quip"))
        chooser = self.station["system3_sfxguy_chooser"](d)
        self.assertFalse(chooser.takes("news", False))
        self.assertEqual(chooser.takes("reaction", True), chooser.order[0] == "reaction" or (chooser.order[0] == "news"))
        k = chooser.pick("quip", ["one", "two", "three", "four"])
        self.assertIn(k, (0, 1, 2, 3))
        chooser.done("two", "quip")
        settle()
        again = self.station["system3_sfxguy_direction"](entry, "dj", text)
        self.assertFalse(again["speak"])
        self.assertEqual(again["why"], "already spoke on this turn")
        got = self.client.get("/api/system3/conversation/" + h.id, headers={"Authorization": "Bearer k"}).json()
        obs = [o for o in got.get("observations_air", []) if o.get("family") == "SFXGUY"]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["line"], "two")
        self.assertEqual(obs[0]["draws"][0]["of"], 4)
        self.assertEqual(obs[0]["fell_through"], ["news"])

    def test_a_resolved_passage_ends_at_a_sentence_end(self):
        # the stand-in station hands back "I want to eat. Someone got eaten."
        # for any cap; a 20-character budget keeps the first sentence whole
        cfg = copy.deepcopy(self.rt.config)
        cfg["speakerbox"]["passage_chars"] = 20
        self.rt.config = cfg
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(dj={"host_name": "Caine", "cohost_name": "Skip",
                                                                       "speakbox_prepend_rate": 1.0, "speakbox_append_rate": 1.0})))
        texts = [(sb.get("material") or {}).get("text") for t in h.conv["turns"] for sb in t.get("speakerbox") or []]
        texts = [x for x in texts if x]
        self.assertTrue(texts, "a mark rolled at rate 1.0")
        for x in texts:
            self.assertEqual(x, "I want to eat.")

    def test_now_reads_the_dice_of_the_line_on_air(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(dj={"host_name": "Caine", "cohost_name": "Skip", "drop_voice": "guy",
                                                                       "sfxguy_rate": 100, "sfxguy_warp": 40})))
        script = "\n".join("%s: Line number %d of this round, said plainly." % (t["speaker"], t["index"]) for t in h.conv["turns"])
        entry = {"script": script, "caller_name": ""}
        self.station["system3_bind_entry"](entry, h)
        rows = [{"line_id": "L%d" % i, "who": "dj", "text": "Line number %d of this round, said plainly." % i,
                 "system3": {"conversation_id": h.id, "turn_id": entry["system3"]["turns"].get(str(i), "")}}
                for i in range(len(h.conv["turns"]))]
        self.station["system3_observe_ledger"](7, "sid-1", rows, "banter")
        settle()
        self.station["_SPEAKING_NOW"] = {"id": "L1", "who": "cohost", "name": "Skip", "kind": "banter",
                                         "text": rows[1]["text"], "at": time.time()}
        got = self.client.get("/api/system3/now", headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(got["line"]["id"], "L1")
        s3 = got["system3"]
        self.assertEqual(s3["conversation_id"], h.id)
        self.assertEqual(s3["road"], "banter")
        self.assertEqual(s3["turn"]["turn"], 2)
        self.assertTrue(any(r["family"] == "ES" and r["dice"] for r in s3["turn"]["rolls"]))
        self.assertTrue(any(r["family"] == "SFXGUY" for r in s3["turn"]["rolls"]))
        self.assertEqual(got["register"]["directed"], got["register"]["roads"])
        self.station["_SPEAKING_NOW"] = {"id": "nobody-made-this", "who": "dj", "text": "x", "at": time.time()}
        got = self.client.get("/api/system3/now", headers={"Authorization": "Bearer k"}).json()
        self.assertIs(got["system3"], False)
        self.station["_SPEAKING_NOW"] = {}
        got = self.client.get("/api/system3/now", headers={"Authorization": "Bearer k"}).json()
        self.assertIsNone(got["line"])

    def test_a_row_finds_its_turn_by_its_words(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(dj={"host_name": "Caine", "cohost_name": "Skip", "drop_voice": "guy",
                                                                       "sfxguy_rate": 100, "sfxguy_warp": 40})))
        script = "\n".join("%s: Line number %d of this round, said plainly." % (t["speaker"], t["index"]) for t in h.conv["turns"])
        entry = {"script": script, "caller_name": ""}
        self.station["system3_bind_entry"](entry, h)
        turns = h.conv["turns"]
        # the air spliced two rows in front: by number every link would be two off
        self.assertEqual(self.station["system3_turn_id_for"](entry, "Line number 3 of this round, said plainly.", "cohost" if turns[3]["speaker"] == "B" else "dj"), turns[3]["turn_id"])
        self.assertEqual(self.station["system3_turn_id_for"](entry, "a passage dealt in front by the old door", "dj"), "")
        self.assertEqual(self.station["system3_turn_id_for"]({}, "Line number 3 of this round, said plainly.", "dj"), "")
        # the SFX Guy's row: his node on the turn it followed, and the draw
        text0 = "Line number 0 of this round, said plainly."
        d = self.station["system3_sfxguy_direction"](entry, "dj", text0)
        chooser = self.station["system3_sfxguy_chooser"](d)
        chooser.pick("quip", ["one", "two"])
        chooser.done("two", "quip")
        rows = [{"line_id": "R0", "who": "dj", "text": text0, "system3": {"conversation_id": h.id, "turn_id": turns[0]["turn_id"]}},
                {"line_id": "G0", "who": "drop", "text": "two", "system3": {"conversation_id": h.id, "turn_id": turns[0]["turn_id"], "sfxguy": True}},
                {"line_id": "R1", "who": "cohost", "text": "Line number 1 of this round, said plainly.", "system3": {"conversation_id": h.id, "turn_id": ""}}]
        self.station["system3_observe_ledger"](9, "sid-2", rows, "banter")
        settle()
        got = self.client.get("/api/system3/line", params={"line_id": "G0"}, headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(got["turn"]["turn_id"], turns[0]["turn_id"])
        self.assertEqual(got["sfxguy"]["line"]["line"], "two")
        self.assertEqual(got["sfxguy"]["node"]["family"], "SFXGUY")
        self.assertTrue(any(e["family"] == "SFXGUY" for e in got["decisions"]))
        # a row linked to no turn heals by its words
        got = self.client.get("/api/system3/line", params={"line_id": "R1"}, headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(got["turn"]["turn_id"], turns[1]["turn_id"])
        self.assertTrue(got["healed"])

    def test_the_feed_dice_answer_for_a_batch(self):
        # [s3-dice] "a series of dice icons rolling and landing on their final numbers"
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(dj={"host_name": "Caine", "cohost_name": "Skip", "drop_voice": "guy",
                                                                       "sfxguy_rate": 100, "sfxguy_warp": 40})))
        script = "\n".join("%s: Dice line number %d of this round, said plainly." % (t["speaker"], t["index"]) for t in h.conv["turns"])
        entry = {"script": script, "caller_name": ""}
        self.station["system3_bind_entry"](entry, h)
        turns = h.conv["turns"]
        text0 = "Dice line number 0 of this round, said plainly."
        d = self.station["system3_sfxguy_direction"](entry, "dj", text0)
        chooser = self.station["system3_sfxguy_chooser"](d)
        chooser.pick("quip", ["one", "two"])
        chooser.done("two", "quip")
        rows = [{"line_id": "D0", "who": "dj", "text": text0, "system3": {"conversation_id": h.id, "turn_id": turns[0]["turn_id"]}},
                {"line_id": "DG", "who": "drop", "text": "two", "system3": {"conversation_id": h.id, "turn_id": turns[0]["turn_id"], "sfxguy": True}}]
        self.station["system3_observe_ledger"](11, "sid-3", rows, "banter")
        settle()
        tail = turns[1]["turn_id"].split(":")[-1]
        got = self.client.get("/api/system3/dice", params={"ids": "D0,DG,nobody,hinted",
                                                           "hints": "hinted:%s:%s:cohost" % (h.id, tail)},
                              headers={"Authorization": "Bearer k"}).json()["lines"]
        self.assertTrue(got["D0"]["system3"])
        self.assertEqual(got["D0"]["turn_id"], turns[0]["turn_id"])
        rolls = got["D0"]["turn"]["rolls"]
        self.assertTrue(rolls)
        drawn = [r for r in rolls if r.get("dice") is not None]
        self.assertTrue(drawn)
        self.assertTrue(all(r.get("event_id") for r in rolls))
        self.assertTrue(all(1 <= int(r["dice"]) <= 100 for r in drawn))
        # the SFX Guy's row: his node's roll on the turn he followed, and the draw at air
        self.assertTrue(got["DG"]["system3"])
        self.assertEqual(got["DG"]["who"], "drop")
        self.assertTrue(got["DG"]["air"])
        self.assertEqual(got["DG"]["air"][0]["family"], "LINE")
        self.assertEqual(got["DG"]["air"][0]["of"], 2)
        # a row no node made, and a row that carried its own stamp
        self.assertFalse(got["nobody"]["system3"])
        self.assertTrue(got["hinted"]["system3"])
        self.assertEqual(got["hinted"]["turn_id"], turns[1]["turn_id"])
        self.assertEqual(got["hinted"]["turn"]["turn"], 2)
        # an empty ask is an empty answer, not a fault
        self.assertEqual(self.client.get("/api/system3/dice", headers={"Authorization": "Bearer k"}).json(), {"lines": {}})

    def test_the_status_names_every_road_and_the_config_shows_every_structure(self):
        got = self.client.get("/api/system3/status", headers={"Authorization": "Bearer k"}).json()
        roads = {r["id"]: r for r in got["roads"]}
        self.assertEqual(roads["recap"]["mode"], "active")
        self.assertEqual(roads["recap"]["structure"], "structures/recap")
        self.assertEqual(roads["banter"]["structure"], "structure")
        self.assertEqual(roads["track_talk"]["hook"], "system3_direct_line")
        self.rt.settings = self.rt.apply_settings({"mode": "off"})
        got = self.client.get("/api/system3/status", headers={"Authorization": "Bearer k"}).json()
        self.assertEqual({r["label_air"] for r in got["roads"]}, {"not directed by System 3"})
        cfg = self.client.get("/api/system3/config", headers={"Authorization": "Bearer k"}).json()["config"]
        for road in system3.ROADS:
            if road != "banter":
                self.assertIn(road, cfg["structures"])
        self.assertIn("sfxguy", cfg)
        put = self.client.put("/api/system3/structures/recap", headers={"Authorization": "Bearer k"},
                              json={**cfg["structures"]["recap"], "legs": cfg["structures"]["recap"]["legs"][:1] + cfg["structures"]["recap"]["legs"][-1:]})
        self.assertEqual(put.status_code, 200, put.text)
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(road="recap", angle="x", own_material=True, seed_text="")))
        self.rt.settings = self.rt.apply_settings({"mode": "active"})
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(road="recap", angle="x", own_material=True, seed_text="")))
        self.assertEqual([t["leg"] for t in h.conv["turns"]], ["open", "land"])


if __name__ == "__main__":
    unittest.main()
