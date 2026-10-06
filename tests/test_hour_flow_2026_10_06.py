"""[hour-flow] 2026-10-06: one running-order entry's own structure, and micro-exchanges on a leg.

"convert 'the hour' view for a segment into a vertical flowchart ... add, remove,
insert, adjust, extend nodes ... select a node to give more inner conversational
depth ... micro exchanges" - the operator. Edit scope "Both, with a toggle".

Runs in the station container:
  docker exec -e PYTHONPATH=/app:/app/tests spark-agent sh -c \\
    "cd /app && python3 -m unittest discover -s /tmp/waveB/tests -p 'test_hour_flow_2026_10_06.py' -v"
Against a staged copy (the live tree until the patch is applied):
  PYTHONPATH=/tmp/waveB/stage:/app:/app/tests ... the same.
"""
import asyncio
import copy
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_runtime
import system3_tables
from test_system3_runtime import FakeStation, ctx, settle

AUTH = {"Authorization": "Bearer k"}
PIN = "62e7c965e7fe2b0d"
SEG = {"id": "hour-1790582400000:hour-05", "template": "hour-05", "kind": "news", "label": "News at five past",
       "start": 1790583240.0, "ends": 1790583480.0, "hour": "2026-09-28T03", "index": 4, "engine": "system2"}


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def inputs(road, slot="", **kw):
    names = {"A": "Host", "B": "Co-host", "D": "Third chair", "C": "Marge"}
    seats = kw.pop("seats", ["A", "B"])
    out = {"road": road, "at": 1.0, "seats": list(seats), "names": {s: names.get(s, s) for s in seats},
           "turns": kw.pop("turns", 6), "target_seconds": 0.0, "words_per_turn": 60.0,
           "subject": {"topic": kw.pop("topic", "the town budget")}, "availability": {"news": True},
           "speakerbox_rates": {}}
    if slot:
        out["segment"] = dict(SEG, template=slot)
    out.update(kw)
    return out


def entry_variant(cfg, road, slot, **over):
    """An entry's own structure, made the way put_entry_structure makes one."""
    st = copy.deepcopy(system3.road_structure(cfg, road))
    for drop in ("graph", "weight", "variant_of"):
        st.pop(drop, None)
    st.update({"id": "%s@%s" % (road, slot), "label": "[%s for %s]" % (road, slot), "entry_of": road, "entry": slot,
               "scope": "entry", "version": 2})
    st.update(over)
    cfg.setdefault("structures", system3_tables.default_structures())["%s@%s" % (road, slot)] = st
    return st


def plan(cfg, inp, road, seed="hf-1", cid="hf1"):
    conv = system3.new_conversation(inp, cfg, settings(seed), conversation_id=cid)
    system3.plan_legs(conv, cfg, inp, road)
    return conv


class TheEntryKey(unittest.TestCase):
    def test_the_defaults_are_untouched(self):
        # The default config's hash is pinned in tests/test_system3.py (a6e7222d33bd92c3 in
        # the container today; PIN above is the older value the share showed). Measured
        # 2026-10-06: the live tree and the patched stage compute the same hash, so the
        # literal is left to that test. Asserted here: nothing of [hour-flow] reached a
        # default - no leg carries `inner`, no entry key is held, the hash is stable.
        cfg = system3.default_config()
        for road, st in system3_tables.DEFAULT_ROAD_STRUCTURES.items():
            for leg in st["legs"]:
                self.assertNotIn("inner", leg, road)
        self.assertFalse([k for k in cfg["structures"] if "@" in k])
        self.assertEqual(system3.config_hash(cfg), system3.config_hash(system3.default_config()))
        self.assertEqual(len(system3.config_hash(cfg)), len(PIN))

    def test_the_entry_is_read_off_the_inputs(self):
        self.assertEqual(system3.entry_slot_of({"segment": {"template": "hour-05", "id": "occ"}}), "hour-05")
        self.assertEqual(system3.entry_slot_of({"slot_id": "news-2", "segment": {"template": "hour-05"}}), "news-2",
                         "the door's own word outranks the segment on air")
        self.assertEqual(system3.entry_slot_of({}), "")
        self.assertEqual(system3.entry_slot_of(None), "")
        self.assertEqual(system3.entry_slot_clean(" hour 05 "), "hour05")
        self.assertEqual(system3.entry_slot_clean("a/b"), "", "a slash is not a key character")
        self.assertEqual(system3.entry_slot_clean("x" * 200), "x" * 80)
        self.assertEqual(system3.entry_key("news~v2", "hour-05"), "news@hour-05")

    def test_road_structure_prefers_the_entrys_own_only_when_asked(self):
        cfg = system3.default_config()
        mine = entry_variant(cfg, "news", "hour-05")
        self.assertIs(system3.road_structure(cfg, "news", slot_id="hour-05"), mine)
        self.assertEqual(system3.road_structure(cfg, "news")["id"], "news_legs")
        self.assertEqual(system3.road_structure(cfg, "news", slot_id="hour-09")["id"], "news_legs")
        mine["enabled"] = False
        self.assertEqual(system3.road_structure(cfg, "news", slot_id="hour-05")["id"], "news_legs",
                         "a switched-off entry structure is passed over")


class TheEntryVariantIsChosen(unittest.TestCase):
    def test_the_entry_variant_is_chosen_over_the_roads(self):
        cfg = system3.default_config()
        mine = entry_variant(cfg, "news", "hour-05")
        mine["legs"][0]["act"] = "THE LEAD FOR THE FIVE-PAST BULLETIN: the one story this entry is for."
        conv = plan(cfg, inputs("news", "hour-05"), "news")
        self.assertEqual(conv["road_structure"]["id"], "news@hour-05")
        self.assertTrue(conv["turns"][0]["protocol"].startswith("THE LEAD FOR THE FIVE-PAST BULLETIN"))
        ev = [e for e in conv["decision_events"] if e["family"] == "VARIANT"]
        self.assertEqual(len(ev), 1)
        self.assertIsNone(ev[0]["rng"], "the entry's own is not a draw")
        self.assertEqual(ev[0]["selected"]["id"], "news@hour-05")
        self.assertEqual(ev[0]["selected"]["entry"], "hour-05")
        self.assertEqual(conv["variant_roll"], {"structure": "news@hour-05", "event_id": ev[0]["event_id"],
                                                "of": 1, "entry": "hour-05"})

    def test_another_entry_of_the_kind_runs_the_roads_own(self):
        cfg = system3.default_config()
        entry_variant(cfg, "news", "hour-05")
        other = plan(cfg, inputs("news", "hour-09"), "news", cid="hf2")
        self.assertEqual(other["road_structure"]["id"], "news_legs")
        self.assertFalse([e for e in other["decision_events"] if e["family"] == "VARIANT"],
                         "no variants on the desk: nothing is drawn, the trajectory is unchanged")
        bare = plan(cfg, inputs("news"), "news", cid="hf3")
        self.assertEqual(bare["road_structure"]["id"], "news_legs")

    def test_the_entrys_own_never_joins_another_entrys_weighted_draw(self):
        cfg = system3.default_config()
        entry_variant(cfg, "news", "hour-05", variant_of="news")   # an old-style tag on it changes nothing
        variant = copy.deepcopy(system3.road_structure(cfg, "news"))
        variant.update({"id": "news~v2", "variant_of": "news", "weight": 1.0, "label": "[News variant]"})
        variant.pop("graph", None)
        cfg["structures"]["news~v2"] = variant
        conv = plan(cfg, inputs("news", "hour-09"), "news", cid="hf4")
        ev = next(e for e in conv["decision_events"] if e["family"] == "VARIANT")
        self.assertEqual([c["id"] for c in ev["stages"][0]["candidates"]], ["news", "news~v2"])

    def test_the_door_can_name_the_entry_without_a_segment(self):
        cfg = system3.default_config()
        entry_variant(cfg, "memo", "memo-2")
        conv = plan(cfg, inputs("memo", slot_id="memo-2", turns=4), "memo", cid="hf5")
        self.assertEqual(conv["road_structure"]["id"], "memo@memo-2")

    def test_replay_lands_the_same_plan(self):
        import json
        cfg = system3.default_config()
        mine = entry_variant(cfg, "news", "hour-05")
        mine["legs"][0]["inner"] = [{"seat": "B", "act": "asks one question about the lead", "families": ["ES", "RS"]}]
        conv = plan(cfg, inputs("news", "hour-05"), "news", cid="hf6")
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), cfg)["ok"])


class MicroExchanges(unittest.TestCase):
    def shaped(self, inner, turns=6, max_turns=10):
        cfg = system3.default_config()
        st = copy.deepcopy(system3.road_structure(cfg, "news"))
        st["legs"][0]["inner"] = inner
        st["max_turns"] = max_turns
        st["min_turns"] = min(st["min_turns"], max_turns)
        cfg["structures"]["news"] = st
        inp = inputs("news", turns=turns)
        return plan(cfg, inp, "news", cid="mx1"), st

    def test_inner_rows_expand_into_turns_in_order_right_after_their_leg(self):
        conv, st = self.shaped([{"seat": "B", "act": "asks ONE question about the lead", "families": ["ES", "RS"]},
                                {"seat": "alternate", "act": "answers it in one breath", "families": ["ES"]}])
        turns = conv["turns"]
        self.assertEqual([t["leg"] for t in turns[:4]], ["lead", "lead", "lead", "react"])
        self.assertEqual([t["speaker"] for t in turns[:4]], ["A", "B", "A", "B"],
                         "the exchange alternates off the lead's seat, and lands clear of the next leg")
        self.assertEqual(turns[1]["inner"], {"of": "lead", "index": 0, "id": "lead.x1"})
        self.assertEqual(turns[2]["inner"], {"of": "lead", "index": 1, "id": "lead.x2"})
        self.assertNotIn("inner", turns[0])
        self.assertNotIn("inner", turns[3])
        self.assertTrue(turns[1]["protocol"].startswith("asks ONE question about the lead"))
        self.assertEqual(turns[1]["place"], "open")
        fams = {d["family"] for d in turns[1]["decisions"]}
        self.assertIn("ES", fams)
        self.assertIn("RS", fams, "an inner turn draws from its families like a leg")
        self.assertIn("ES", {d["family"] for d in turns[2]["decisions"]}, "ES rides every exchange")
        self.assertEqual(conv["timing"]["turn_budget"], len(turns))
        for a, b in zip(turns, turns[1:]):
            self.assertNotEqual(a["speaker"], b["speaker"], "nobody speaks twice in a row")

    def test_the_exchanges_count_against_the_turn_budget(self):
        # want 6: lead + 2 exchanges + react + back is 5; one middle pass would make 6
        # but lands A after A, so the parity fix takes it out - the budget holds
        conv, st = self.shaped([{"seat": "B", "act": "asks one question", "families": ["ES"]},
                                {"seat": "alternate", "act": "answers it", "families": ["ES"]}], turns=6)
        self.assertLessEqual(len(conv["turns"]), 6)
        self.assertEqual([t["leg"] for t in conv["turns"]], ["lead", "lead", "lead", "react", "back"])

    def test_max_turns_bounds_the_exchanges_and_never_drops_a_leg(self):
        conv, st = self.shaped([{"seat": "B", "act": "asks one question", "families": ["ES"]},
                                {"seat": "alternate", "act": "answers it", "families": ["ES"]}],
                               turns=4, max_turns=4)
        turns = conv["turns"]
        self.assertEqual(len(turns), 4)
        self.assertEqual([t.get("inner", {}).get("id") for t in turns], [None, "lead.x1", None, None],
                         "the exchange nearest the end went first; every leg stayed")
        self.assertEqual([t["leg"] for t in turns], ["lead", "lead", "react", "back"])
        self.assertEqual(turns[-1]["place"], "close")
        self.assertEqual(system3._inner_trim([({"id": "a"}, "A"), ({"id": "a.x1", "inner_of": "a"}, "B"), ({"id": "b"}, "A")], 1),
                         [({"id": "a"}, "A"), ({"id": "b"}, "A")], "legs are never dropped, even past the bound")

    def test_a_leg_without_inner_is_the_leg_it_was(self):
        cfg = system3.default_config()
        a = plan(cfg, inputs("news"), "news", seed="same", cid="s1")
        cfg2 = system3.default_config()
        cfg2["structures"]["news"]["legs"][0]["inner"] = []
        b = plan(cfg2, inputs("news"), "news", seed="same", cid="s1")
        self.assertEqual([(t["leg"], t["speaker"]) for t in a["turns"]], [(t["leg"], t["speaker"]) for t in b["turns"]])
        self.assertEqual(system3.inner_rows({"id": "x"}), [])
        self.assertEqual(system3.inner_rows({"id": "x", "inner": [{"seat": "B"}]}), [], "a row without an act is nothing")

    def test_the_sheet_prints_the_exchange_as_a_row(self):
        conv, st = self.shaped([{"seat": "B", "act": "asks one question about the lead", "families": ["ES"]}])
        sheet = system3.render_legs_sheet(conv)
        self.assertIn(" 2  B  - asks one question about the lead", sheet)


class Validation(unittest.TestCase):
    def legs(self, inner):
        st = copy.deepcopy(system3_tables.DEFAULT_ROAD_STRUCTURES["news"])
        st["legs"][0]["inner"] = inner
        return st

    def test_validate_structure_accepts_inner(self):
        st = self.legs([{"seat": "B", "act": "asks", "families": ["ES", "RS"]}, {"act": "answers"}])
        self.assertEqual(system3_tables.validate_structure("news", st), [])
        self.assertEqual(system3_tables.validate_structure("news", self.legs([])), [])
        self.assertEqual(system3_tables.inner_problems({"id": "lead"}, "leg lead"), [])

    def test_validate_structure_names_a_bad_row(self):
        bad = system3_tables.validate_structure("news", self.legs([{"seat": "Z", "act": "x"}]))
        self.assertTrue(any("inner 1" in p and "seat" in p for p in bad), bad)
        bad = system3_tables.validate_structure("news", self.legs([{"seat": "B", "act": "x", "families": ["NOPE"]}]))
        self.assertTrue(any("families" in p for p in bad), bad)
        bad = system3_tables.validate_structure("news", self.legs([{"seat": "B"}]))
        self.assertTrue(any("needs an act" in p for p in bad), bad)
        bad = system3_tables.validate_structure("news", self.legs("not a list"))
        self.assertTrue(any("inner must be a list" in p for p in bad), bad)
        bad = system3_tables.validate_structure("news", self.legs([{"act": "x"}] * (system3_tables.INNER_MAX + 1)))
        self.assertTrue(any("at most" in p for p in bad), bad)


class TheApi(unittest.TestCase):
    def boot(self, segment=None):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        if segment is not None:
            self.station["segment_on_air"] = lambda at=0.0: dict(segment)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active", "test_seed": "hf-api"}, headers=AUTH)
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def entry_body(self):
        legs = copy.deepcopy(system3_tables.DEFAULT_ROAD_STRUCTURES["news"]["legs"])
        legs[0]["act"] = "THE LEAD FOR THE FIVE-PAST BULLETIN."
        legs[0]["inner"] = [{"seat": "B", "act": "asks one question about the lead", "families": ["ES", "RS"]}]
        return {"legs": legs, "label": "[News at five past]", "min_turns": 4, "max_turns": 9}

    def test_get_put_delete_shapes(self):
        self.boot()
        got = self.client.get("/api/system3/structures/news?slot_id=hour-05", headers=AUTH)
        self.assertEqual(got.status_code, 200, got.text)
        d = got.json()
        self.assertEqual((d["road"], d["slot_id"], d["scope"], d["key"]), ("news", "hour-05", "road", "news"))
        self.assertEqual(d["structure"]["id"], "news_legs")
        self.assertEqual(d["road_structure"]["id"], "news_legs")
        self.assertEqual(d["default"]["id"], "news_legs")
        self.assertEqual(d["variants"], [])
        self.assertFalse(d["entry_held"])
        self.assertEqual(d["families"], ["ES", "RS", "IRS", "FL", "CTS", "REACT"])
        self.assertFalse(d["line_road"])
        # the entry's own, saved
        put = self.client.put("/api/system3/structures/news", headers=AUTH,
                              json={"scope": "entry", "slot_id": "hour-05", "structure": self.entry_body()})
        self.assertEqual(put.status_code, 200, put.text)
        saved = put.json()
        self.assertEqual((saved["scope"], saved["slot_id"], saved["road"], saved["key"]), ("entry", "hour-05", "news", "news@hour-05"))
        st = saved["structure"]
        self.assertEqual((st["id"], st["entry_of"], st["entry"], st["scope"], st["version"]), ("news@hour-05", "news", "hour-05", "entry", 2))
        self.assertNotIn("graph", st, "the legs are the entry's shape; no road graph is copied over them")
        self.assertNotIn("variant_of", st)
        self.assertEqual(st["label"], "[News at five past]")
        self.assertEqual(st["legs"][0]["inner"][0]["act"], "asks one question about the lead")
        self.assertEqual(self.rt.config["structures"]["news@hour-05"]["id"], "news@hour-05")
        # the effective one is now the entry's
        d = self.client.get("/api/system3/structures/news?slot_id=hour-05", headers=AUTH).json()
        self.assertEqual((d["scope"], d["key"], d["structure"]["id"]), ("entry", "news@hour-05", "news@hour-05"))
        self.assertEqual(d["road_structure"]["id"], "news_legs")
        self.assertTrue(d["entry_held"])
        self.assertEqual(len(d["variants"]), 1)
        self.assertEqual({k: d["variants"][0][k] for k in ("key", "scope", "entry", "legs", "inner")},
                         {"key": "news@hour-05", "scope": "entry", "entry": "hour-05", "legs": 4, "inner": 1})
        # another entry of the kind still reads the road's
        d2 = self.client.get("/api/system3/structures/news?slot_id=hour-09", headers=AUTH).json()
        self.assertEqual((d2["scope"], d2["structure"]["id"]), ("road", "news_legs"))
        # a second save is a version on
        put2 = self.client.put("/api/system3/structures/news", headers=AUTH,
                               json={"scope": "entry", "slot_id": "hour-05", "structure": self.entry_body()})
        self.assertEqual(put2.json()["structure"]["version"], 3)
        # refusals
        bad = self.client.put("/api/system3/structures/news", headers=AUTH,
                              json={"scope": "entry", "slot_id": "hour-05", "structure": {"legs": [{"id": "x"}]}})
        self.assertEqual(bad.status_code, 400)
        bad = self.client.put("/api/system3/structures/news", headers=AUTH,
                              json={"scope": "entry", "structure": self.entry_body()})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("slot_id", bad.json()["detail"])
        bad = self.client.put("/api/system3/structures/news", headers=AUTH,
                              json={"scope": "entry", "slot_id": "hour-05",
                                    "structure": {"legs": [dict(self.entry_body()["legs"][0], inner=[{"seat": "Q", "act": "x"}])]}})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("inner 1", bad.json()["detail"])
        self.assertEqual(self.client.get("/api/system3/structures/nowhere", headers=AUTH).status_code, 404)
        # today's PUT, no scope: the road's own, as before
        road = self.client.put("/api/system3/structures/news", headers=AUTH,
                               json={"legs": system3_tables.default_structures()["news"]["legs"]})
        self.assertEqual(road.status_code, 200, road.text)
        self.assertEqual((road.json()["structure"]["id"], road.json()["structure"]["version"]), ("news_legs", 2))
        self.assertEqual(self.rt.config["structures"]["news@hour-05"]["version"], 3, "the entry's own is untouched")
        # DELETE the entry's own
        gone = self.client.delete("/api/system3/structures/news?scope=entry&slot_id=hour-05", headers=AUTH)
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual({k: gone.json()[k] for k in ("deleted", "road", "slot_id", "scope")},
                         {"deleted": "news@hour-05", "road": "news", "slot_id": "hour-05", "scope": "entry"})
        self.assertNotIn("news@hour-05", self.rt.config["structures"])
        d = self.client.get("/api/system3/structures/news?slot_id=hour-05", headers=AUTH).json()
        self.assertEqual((d["scope"], d["structure"]["id"]), ("road", "news_legs"))
        self.assertEqual(self.client.delete("/api/system3/structures/news?scope=entry&slot_id=hour-05", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.delete("/api/system3/structures/news?scope=entry", headers=AUTH).status_code, 400)
        # today's DELETE, no scope: only a variant
        self.assertEqual(self.client.delete("/api/system3/structures/news", headers=AUTH).status_code, 400)
        # auth
        self.assertEqual(self.client.put("/api/system3/structures/news",
                                         json={"scope": "entry", "slot_id": "hour-05", "structure": self.entry_body()}).status_code, 401)

    def test_a_round_planned_for_the_entry_runs_its_structure(self):
        self.boot(SEG)
        put = self.client.put("/api/system3/structures/news", headers=AUTH,
                              json={"scope": "entry", "slot_id": "hour-05", "structure": self.entry_body()})
        self.assertEqual(put.status_code, 200, put.text)
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(road="news", lines=6, bank=False)))
        self.assertTrue(h.active)
        self.assertEqual(h.conv["inputs"]["slot_id"], "hour-05", "the entry off the segment on air")
        self.assertEqual(h.conv["identity"]["segment"]["template"], "hour-05")
        self.assertEqual(h.conv["road_structure"]["id"], "news@hour-05")
        self.assertTrue(h.conv["turns"][0]["protocol"].startswith("THE LEAD FOR THE FIVE-PAST BULLETIN"))
        self.assertEqual(h.conv["turns"][1]["inner"]["id"], "lead.x1")
        self.assertIn("asks one question about the lead", h.sheet)
        # the door's own word outranks the sheet
        h2 = asyncio.run(self.station["system3_direct_banter"](**ctx(road="news", lines=6, bank=False, slot_id="hour-09")))
        self.assertEqual(h2.conv["inputs"]["slot_id"], "hour-09")
        self.assertEqual(h2.conv["road_structure"]["id"], "news_legs")


if __name__ == "__main__":
    unittest.main()
