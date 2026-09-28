"""[s3-cast] The cast's favourites (FAV1) and the operator's directives
(DIRECTIVE1): what used to be stapled to every host prompt as "LIVE MIND
ADJUSTMENTS FOR THIS CHARACTER" - every liked line with "you may repeat it",
every Mind desk note - is two tables System 3 rolls, records and lands on one
turn, and a favourite repeated word for word fails validation."""
import asyncio
import copy
import json
import tempfile
import time
import unittest

import system3
import system3_tables
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle, written
from fastapi import FastAPI
from fastapi.testclient import TestClient


FAVS = [{"id": "fav_a", "label": "office fire", "text": "Just lit the manager's office on fire; six or seven minutes max before it's dire.",
         "seat": "A", "who": "dj", "name": "Host", "line_id": "L1"},
        {"id": "fav_b", "label": "snipers", "text": "Sparking a GTA chase that takes the drama far; stuck in a field where snipers wield the shield.",
         "seat": "B", "who": "cohost", "name": "Skip", "line_id": "L2"}]


def cast_config(favs=FAVS, directives=None):
    cfg = system3.default_config()
    for t in cfg["tables"]:
        if t["id"] == "FAV1":
            t["categories"][0]["items"] = copy.deepcopy(favs)
        if t["id"] == "DIRECTIVE1":
            for cat in t["categories"]:
                cat["items"] = copy.deepcopy((directives or {}).get(cat["id"], []))
    return cfg


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10, "names": {"A": "Host", "B": "Skip"},
            "roles": {"A": "dj", "B": "cohost"}, "at": 1_800_000_000.0,
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]}, "availability": {"speakbox": False},
            "cast_rolls": True}
    base.update(over)
    return base


def settings(seed, **controls):
    return system3.normalise_settings({"mode": "active", "test_seed": seed, "controls": controls})


def plan(seed="c1", cfg=None, favorites=1.0, **over):
    return system3.plan_scene(inputs(**over), cfg or cast_config(), settings(seed, favorites=favorites),
                              conversation_id="cast-" + seed)


def events(conv, family):
    return [e for e in conv["decision_events"] if e["family"] == family]


class TableTests(unittest.TestCase):
    def test_the_two_pools_are_default_tables_and_may_stand_empty(self):
        ids = [t["id"] for t in system3.default_config()["tables"]]
        self.assertEqual(ids[ids.index("FAV1"):ids.index("FAV1") + 2], ["FAV1", "DIRECTIVE1"])
        system3.validate_table(system3_tables.FAV1)
        system3.validate_table(system3_tables.DIRECTIVE1)
        self.assertEqual(system3.DEFAULT_CONTROLS["favorites"], 0.25)
        # an empty pool draws nothing and records nothing
        conv = system3.plan_scene(inputs(), system3.default_config(), settings("empty", favorites=1.0))
        self.assertFalse(events(conv, "FAV") or events(conv, "DIRECTIVE"))

    def test_a_directive_row_is_checked_and_clamped(self):
        t = copy.deepcopy(system3_tables.DIRECTIVE1)
        t["categories"][0]["items"] = [{"id": "d1", "text": "Never apologises on air.", "odds": 7, "airings": "3"}]
        got = system3.validate_table(t)["categories"][0]["items"][0]
        self.assertEqual((got["odds"], got["airings"], got["until"]), (1.0, 3, 0.0))
        t["categories"][0]["items"] = [{"id": "d2", "text": "  "}]
        with self.assertRaises(ValueError):
            system3.validate_table(t)
        f = copy.deepcopy(system3_tables.FAV1)
        f["categories"][0]["items"] = [{"id": "f1", "text": ""}]
        with self.assertRaises(ValueError):
            system3.validate_table(f)


class FavouriteTests(unittest.TestCase):
    def test_a_favourite_is_three_recorded_draws_landing_on_one_host_turn(self):
        conv = plan("fav-1")
        ev = events(conv, "FAV")
        self.assertEqual(len(ev), 1)
        self.assertEqual([s["stage"] for s in ev[0]["stages"]], ["dice", "item", "turn"])
        self.assertIsNotNone(ev[0]["rng"])
        landed = [t for t in conv["turns"] if t.get("favorite")]
        self.assertEqual(len(landed), 1)
        self.assertEqual(ev[0]["turn_id"], landed[0]["turn_id"])
        self.assertIn(landed[0]["favorite"]["id"], ("fav_a", "fav_b"))
        self.assertTrue(any(d["family"] == "FAV" for d in landed[0]["decisions"]))
        sheet = system3.render_sheet(conv)
        self.assertIn("THAT THE OPERATOR LIKED", sheet)
        self.assertIn("never repeat it and never quote it", sheet)
        self.assertNotIn("you may repeat it", sheet)
        self.assertTrue(system3.turn_stamp(conv, landed[0])["round"].get("favorite"))

    def test_the_favorites_control_is_the_odds(self):
        off = plan("fav-off", favorites=0.0)
        self.assertEqual(events(off, "FAV")[0]["selected"]["id"], "NONE")
        self.assertFalse(any(t.get("favorite") for t in off["turns"]))
        hits = sum(1 for i in range(80) if any(t.get("favorite") for t in plan("q%d" % i, favorites=0.25)["turns"]))
        self.assertTrue(8 <= hits <= 34, hits)          # about one in four

    def test_whose_line_it_was_is_said(self):
        only_skip = cast_config(favs=[FAVS[1]])
        conv = plan("whose", cfg=only_skip)
        t = next(t for t in conv["turns"] if t.get("favorite"))
        row = system3._row_work(t, conv)
        self.assertIn("A LINE OF YOURS" if t["speaker"] == "B" else "A LINE SKIP SAID", row)

    def test_a_favourite_that_came_up_lately_weighs_a_quarter(self):
        conv = plan("rest", fav_recent=["fav_a"])
        item = next(s for s in events(conv, "FAV")[0]["stages"] if s["stage"] == "item")
        a = next(c for c in item["candidates"] if c["id"] == "fav_a")
        b = next(c for c in item["candidates"] if c["id"] == "fav_b")
        self.assertAlmostEqual(a["weight"], 0.25)
        self.assertEqual(b["weight"], 1.0)
        self.assertIn("came up lately x0.25", a["why"])

    def test_the_rolls_are_opt_in_and_move_no_other_draw(self):
        with_cast = plan("same")
        without = system3.plan_scene(inputs(cast_rolls=False), cast_config(), settings("same", favorites=1.0),
                                     conversation_id="cast-same")
        strip = lambda c: [(e["family"], e["selected"].get("id") if e["selected"] else None, (e.get("rng") or {}).get("u"))
                           for e in c["decision_events"] if e["family"] not in ("FAV", "DIRECTIVE")]
        self.assertEqual(strip(with_cast), strip(without))
        self.assertFalse(events(without, "FAV"))

    def test_a_copied_favourite_fails_validation_and_one_in_its_spirit_passes(self):
        conv = plan("copy")
        t = next(t for t in conv["turns"] if t.get("favorite"))
        fav = t["favorite"]["text"]
        lines = [(x["speaker"], "No, that is wrong, and here is why it matters tonight.") for x in conv["turns"]]
        lines[t["index"]] = (t["speaker"], "Well. " + fav)
        val = system3.validate(conv, lines)
        self.assertEqual(val["verdict"], "non_compliant")
        self.assertTrue(val["repair_wanted"])
        self.assertEqual(val["favorite_copies"], 1)
        lines[t["index"]] = (t["speaker"], "I would torch the whole memo drawer before I read one more of those.")
        val = system3.validate(conv, lines)
        self.assertEqual(val["favorite_copies"], 0)
        self.assertTrue(any(c["what"].startswith("FAV") and c["result"] == "met"
                            for r in val["turns"] for c in r["checks"]))

    def test_replay_reproduces_the_cast_draws(self):
        conv = plan("replay")
        cfg = cast_config()
        self.assertTrue(system3.replay(json.loads(json.dumps(conv)), cfg)["ok"])

    def test_a_replan_lands_the_favourite_again(self):
        conv = plan("replan")
        idx = next(t["index"] for t in conv["turns"] if t.get("favorite"))
        system3.replan(conv, cast_config(), max(1, idx - 1))
        self.assertEqual(sum(1 for t in conv["turns"] if t.get("favorite")), 1)
        self.assertEqual(len(events(conv, "FAV")), 1)


class DirectiveTests(unittest.TestCase):
    def rows(self, **cats):
        return cast_config(favs=[], directives=cats)

    def test_odds_one_is_a_standing_rule_recorded_and_not_drawn(self):
        cfg = self.rows(host=[{"id": "d_std", "text": "Never apologises on air.", "odds": 1.0}])
        conv = plan("std", cfg=cfg)
        ev = events(conv, "DIRECTIVE")
        self.assertEqual(len(ev), 1)
        self.assertIsNone(ev[0]["rng"])
        self.assertEqual(ev[0]["stages"][0]["stage"], "standing")
        landed = [t for t in conv["turns"] if t.get("directives")]
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0]["speaker"], "A")
        self.assertIn("THE OPERATOR'S DIRECTIVE FOR HOST ON THIS TURN: Never apologises on air", system3.render_sheet(conv))

    def test_odds_are_a_die_and_zero_is_never(self):
        cfg = self.rows(cohost=[{"id": "d_half", "text": "Mentions the parking lot fight.", "odds": 0.5}],
                        host=[{"id": "d_zero", "text": "Sings.", "odds": 0.0}])
        seen = {"IN": 0, "OUT": 0}
        for i in range(40):
            conv = plan("odds%d" % i, cfg=cfg)
            half = next(e for e in events(conv, "DIRECTIVE") if e["meta"]["seat"] == "B")
            self.assertIsNotNone(half["rng"])
            seen["IN" if half["selected"]["id"] == "d_half" else "OUT"] += 1
            zero = next(e for e in events(conv, "DIRECTIVE") if e["meta"]["seat"] == "A")
            self.assertEqual(zero["selected"]["id"], "NONE")
            for t in conv["turns"]:
                for d in t.get("directives") or []:
                    self.assertEqual(t["speaker"], "B")
        self.assertTrue(seen["IN"] > 8 and seen["OUT"] > 8, seen)

    def test_an_expired_or_spent_row_rolls_nothing(self):
        cfg = self.rows(host=[{"id": "d_old", "text": "Old news.", "until": 1_700_000_000.0},
                              {"id": "d_spent", "text": "Said enough.", "airings": 2}])
        conv = plan("life", cfg=cfg, directive_spent={"d_spent": 2})
        self.assertEqual(events(conv, "DIRECTIVE"), [])
        conv = plan("life2", cfg=cfg, directive_spent={"d_spent": 1})
        self.assertEqual([e["selected"]["id"] for e in events(conv, "DIRECTIVE")], ["d_spent"])

    def test_the_cast_row_lands_on_any_host_seat_and_a_seat_not_here_rolls_nothing(self):
        cfg = self.rows(cast=[{"id": "d_cast", "text": "Nobody says the word synergy."}],
                        third=[{"id": "d_third", "text": "Hums."}])
        conv = plan("cast", cfg=cfg)
        self.assertEqual([e["selected"]["id"] for e in events(conv, "DIRECTIVE")], ["d_cast"])
        self.assertIn(next(t for t in conv["turns"] if t.get("directives"))["speaker"], ("A", "B"))

    def test_adding_a_row_never_moves_another_rows_dice(self):
        one = self.rows(cohost=[{"id": "d_half", "text": "Mentions the parking lot fight.", "odds": 0.5}])
        two = self.rows(host=[{"id": "d_new", "text": "Whispers once.", "odds": 0.5}],
                        cohost=[{"id": "d_half", "text": "Mentions the parking lot fight.", "odds": 0.5}])
        a = next(e for e in events(plan("rowseed", cfg=one), "DIRECTIVE") if e["selected"].get("row", e["selected"]["id"]) == "d_half" or e["meta"]["seat"] == "B")
        b = next(e for e in events(plan("rowseed", cfg=two), "DIRECTIVE") if e["meta"]["seat"] == "B")
        self.assertEqual(a["rng"]["u"], b["rng"]["u"])

    def test_legs_roads_calls_and_single_lines_carry_them(self):
        cfg = cast_config(directives={"host": [{"id": "d_std", "text": "Never apologises on air."}]})
        news = system3.new_conversation(inputs(road="news", turns=6), cfg, settings("legs", favorites=1.0))
        system3.plan_legs(news, cfg, news["inputs"], "news")
        self.assertTrue(events(news, "DIRECTIVE") and events(news, "FAV"))
        sheet = system3.render_legs_sheet(news)
        self.assertIn("THE OPERATOR'S DIRECTIVE FOR HOST", sheet)
        line = system3.new_conversation(inputs(road="track_talk", seats=["A"], turns=1), cfg, settings("line", favorites=1.0))
        system3.plan_line(line, cfg, line["inputs"])
        self.assertTrue(line["turns"][0].get("directives"))
        self.assertTrue(line["turns"][0].get("favorite"))
        stock = system3.new_conversation(inputs(road="interject", seats=["A"], turns=1,
                                                candidates=[{"id": "1", "text": "Oh, come on."}]),
                                         cfg, settings("stock", favorites=1.0))
        system3.plan_line(stock, cfg, stock["inputs"])
        self.assertFalse(events(stock, "FAV") or events(stock, "DIRECTIVE"), "a drawn stock line is fixed words")
        drop = system3.new_conversation(inputs(road="interject", seats=["D"], roles={"D": "drop"}, turns=1),
                                        cfg, settings("drop", favorites=1.0))
        system3.plan_line(drop, cfg, drop["inputs"])
        self.assertFalse(events(drop, "FAV"), "never the SFX Guy's line")


class RuntimeCastTests(unittest.TestCase):
    def boot(self, dj=None):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.station["read_bombshells"] = lambda: []
        if dj is not None:
            self.station["dj_settings"] = lambda: dj
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active", "test_seed": "cast-rt",
                                                           "controls": {"favorites": 1.0}},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def run_(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def live(self, **over):
        c = ctx(bank=False, dj={"host_name": "Caine", "cohost_name": "Skip"})
        c.update(over)
        return c

    def fav_items(self):
        return next(t for t in self.rt.config["tables"] if t["id"] == "FAV1")["categories"][0]["items"]

    def test_a_vote_is_a_favourite_row_and_the_next_round_can_draw_it(self):
        rt = self.boot()
        got = self.station["system3_favorite"]("line-9", "The smoke alarm is part of the show now.", "dj", "Caine")
        self.assertTrue(got["changed"])
        self.assertEqual(self.station["system3_favorite"]("line-9", "The smoke alarm is part of the show now.", "dj")["changed"], False)
        items = self.fav_items()
        self.assertEqual([(i["seat"], i["line_id"]) for i in items], [("A", "line-9")])
        self.assertIn("favourite added", rt.store.config_versions()[0]["note"])
        h = self.run_(self.station["system3_direct_banter"](**self.live()))
        self.assertTrue(any(t.get("favorite") for t in h.conv["turns"]))
        self.assertIn("THAT THE OPERATOR LIKED", h.sheet)
        settle()
        self.assertEqual(rt.cast["fav_recent"], [items[0]["id"]])
        # the next round weighs it a quarter
        self.assertEqual(rt.cast_inputs()["fav_recent"], [items[0]["id"]])
        # a thumbs-down takes it out
        self.assertTrue(self.station["system3_favorite"]("line-9", "", "dj", liked=False)["changed"])
        self.assertEqual(self.fav_items(), [])

    def test_the_mind_desk_notes_are_adopted_once(self):
        dj = {"host_name": "Caine", "cohost_name": "Skip", "mind_adjustments": {
            "dj": [{"id": "a1", "text": 'The operator liked this line of yours: "Irony twists it - teenagers film the standoff." - say things like it, and you may repeat it.'},
                   {"id": "a2", "text": "Hates chamberpots; brings it up when cornered."}],
            "manager": [{"id": "m1", "text": "Signs every memo."}]}}
        rt = self.boot(dj)
        self.assertEqual([i["text"] for i in self.fav_items()], ["Irony twists it - teenagers film the standoff."])
        host = next(c for c in next(t for t in rt.config["tables"] if t["id"] == "DIRECTIVE1")["categories"] if c["id"] == "host")
        self.assertEqual([(i["text"], i["odds"]) for i in host["items"]], [("Hates chamberpots; brings it up when cornered.", 1.0)])
        self.assertTrue(rt.config["mind_notes_adopted"])
        rt.load()
        self.assertEqual(len(self.fav_items()), 1, "adopted once, never twice")
        self.assertEqual(rt.adopt_mind_notes(), [])

    def test_a_directive_counts_its_airings_at_the_ledger_and_runs_out(self):
        rt = self.boot()
        cfg = copy.deepcopy(rt.config)
        d = next(t for t in cfg["tables"] if t["id"] == "DIRECTIVE1")
        next(c for c in d["categories"] if c["id"] == "host")["items"] = [
            {"id": "d_twice", "text": "Calls the co-host 'captain'.", "odds": 1.0, "airings": 2}]
        r = self.client.put("/api/system3/tables/DIRECTIVE1", json=d, headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        for n in range(2):
            h = self.run_(self.station["system3_direct_banter"](**self.live()))
            self.assertTrue(any(t.get("directives") for t in h.conv["turns"]))
            entry = {"script": written(h), "quotes": {}, "dealt": []}
            self.station["system3_bind_entry"](entry, h)
            rows = [{"line_id": "L%d-%d" % (n, i), "who": "dj", "text": "x", "system3": {"conversation_id": h.id}}
                    for i in range(2)]
            rt.observe_ledger(100 + n, "sid", rows)
            rt.observe_ledger(100 + n, "sid", rows)          # a second commit of the same round counts once
            settle()
        self.assertEqual(rt.cast["directive_spent"]["d_twice"], 2)
        h = self.run_(self.station["system3_direct_banter"](**self.live()))
        self.assertFalse(any(t.get("directives") for t in h.conv["turns"]))
        view = self.client.get("/api/system3/status").json()["cast"]
        self.assertEqual(next(x for x in view["directives"] if x["id"] == "d_twice")["state"], "spent")

    def test_a_single_line_draws_them_and_says_when_it_copied(self):
        rt = self.boot()
        self.station["system3_favorite"]("line-3", "Spin it like a kingpin and never look back.", "dj", "Caine")
        h = self.run_(self.station["system3_direct_line"](road="track_talk", who="dj", dj={"host_name": "Caine"},
                                                          text="intro for the record"))
        self.assertTrue(h.conv["turns"][0].get("favorite"))
        self.assertIn("THAT THE OPERATOR LIKED", h.sheet)
        self.station["system3_bind_line"](h, "Okay. Spin it like a kingpin and never look back, folks.")
        self.assertEqual(h.conv["validation"]["verdict"], "non_compliant")
        settle()


if __name__ == "__main__":
    unittest.main()
