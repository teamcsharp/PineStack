"""[outlandish] The meter measures and never filters; the structure reacts.

Pure: outlandish.py (the meter, the dispute odds, the reaction, the mini-round,
the cut-in odds, the holding aside), sfx_repertoire.py (his reaction database).
Engine: system3.py patched by tools/outlandish_system3_patch.py (the dispute
odds on the next seat, the cut-in node, the golden path untouched).
Runtime: system3_runtime.py + outlandish_runtime.py on a FakeStation (the
interjection's mini-round, the board's one-liner, the reaction clip, the audit
log, the review list and its export, the roll tile and feed records).
"""
import asyncio
import copy
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import conversation_graph
import outlandish
import script_decision_tree
import sfx_repertoire
import system3
import system3_runtime
import outlandish_runtime
from test_system3_runtime import FakeStation, ctx, settle

HIGH = ("Trust me, the moon landing was faked and the lizard people in the deep state don't want you to know - "
        "those morons deserve to die.")
MILD = "That record has a lovely warm bass line, and the drummer really leans into it."


def tables(**dial_over):
    got = {t["id"]: t for t in outlandish.default_tables()}
    for tid, dials in dial_over.items():
        for cat in got[tid]["categories"]:
            if cat["id"] == "dials":
                for it in cat["items"]:
                    if it["id"] in dials:
                        it["weight"] = dials[it["id"]]
    return list(got.values())


def config_with(**dial_over):
    config = system3.default_config()
    config["tables"] = list(config["tables"]) + tables(**dial_over)
    return config


class MeterTests(unittest.TestCase):
    def test_a_plain_line_reads_zero(self):
        r = outlandish.score(MILD)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["level"], "none")
        self.assertEqual(outlandish.headline(r), "OUTLANDISH 0 · clean")

    def test_an_outlandish_line_reads_high_with_its_reasons(self):
        r = outlandish.score(HIGH)
        self.assertGreaterEqual(r["score"], 90)
        self.assertEqual(r["level"], "high")
        self.assertIn("conspiracy", r["tags"])
        self.assertIn("violence", r["tags"])
        labels = {c["id"] for c in r["cues"]}
        self.assertTrue({"faked", "reptilians", "cabal", "deserve_die"} <= labels, labels)
        self.assertTrue(all(c["match"] for c in r["cues"]))
        self.assertTrue(outlandish.headline(r).startswith("OUTLANDISH %d · " % r["score"]))

    def test_an_idiom_is_not_violence(self):
        self.assertEqual(outlandish.score("Oh man, that just kills me.")["score"], 0)
        self.assertGreater(outlandish.score("They killed him in the parking lot.")["score"], 0)

    def test_the_dials_move_the_thresholds(self):
        meter = tables(OUTLANDISH1={"audit_at": 9.5, "react_at": 9.9})[0]
        r = outlandish.score("the moon landing was a hoax", meter)
        self.assertEqual(outlandish.thresholds(meter)["audit"], 95)
        self.assertIn(r["level"], ("dispute", "low"))

    def test_the_reading_is_a_tile_row(self):
        r = outlandish.score(HIGH)
        ev = outlandish.measure_event(r, "c1", "c1:t00", "abc123", "dj", HIGH)
        self.assertEqual(ev["family"], "MEASURE")
        self.assertEqual(ev["lines"], ["abc123"])
        st = ev["stages"][0]
        self.assertEqual(st["draw"]["dice"], r["score"])
        self.assertGreater(len(st["candidates"]), 1)
        self.assertEqual(ev["selected"]["label"], outlandish.headline(r))

    def test_the_model_pass_blends_only_when_its_dial_is_on(self):
        off = outlandish.score(MILD, model={"score": 90, "tags": ["absurdity"]})
        self.assertEqual(off["score"], 0)
        meter = tables(OUTLANDISH1={"model_pass": 2.5})[0]
        on = outlandish.score(MILD, meter, model={"score": 90, "tags": ["absurdity"]})
        self.assertEqual(on["score"], 45)
        self.assertIn("absurdity", on["tags"])
        self.assertEqual(outlandish.parse_model('ok {"score": 71, "tags": ["shock"]}'), {"score": 71.0, "tags": ["shock"]})

    def test_a_cue_must_be_a_pattern(self):
        bad = copy.deepcopy(outlandish.OUTLANDISH1)
        bad["categories"][0]["items"][0]["text"] = "(unclosed"
        with self.assertRaises(ValueError):
            outlandish.validate_table(bad)
        for t in outlandish.default_tables():
            self.assertEqual(system3.validate_table(t)["id"], t["id"])     # [outl-families]


class StructureTests(unittest.TestCase):
    def test_the_dispute_odds_ramp_from_the_threshold(self):
        self.assertEqual(outlandish.dispute_boost(30), {})
        half = outlandish.dispute_boost(70)
        full = outlandish.dispute_boost(100)
        self.assertAlmostEqual(full["RS:argue"], 2.6)
        self.assertTrue(1 < half["RS:argue"] < full["RS:argue"])
        self.assertLess(full["RS:supportive"], 1)
        spec = {"family": "IRS", "category": "refutation", "id": "dispute"}
        self.assertEqual(outlandish.boost_for(spec, full)[1], "IRS:refutation")

    def test_what_followed(self):
        turns = [{"turn_id": "t0", "index": 0, "speaker": "A", "decisions": []},
                 {"turn_id": "t1", "index": 1, "speaker": "B",
                  "decisions": [{"family": "RS", "category": "argue", "item": "debunk"}]}]
        self.assertEqual(outlandish.follow_of(turns, 0, {"t0", "t1"})["state"], "aired")
        self.assertEqual(outlandish.follow_of(turns, 0, {"t0"})["state"], "planned_cut")
        turns[1]["decisions"] = [{"family": "RS", "category": "supportive", "item": "agree"}]
        self.assertEqual(outlandish.follow_of(turns, 0, {"t0", "t1"})["state"], "none")

    def test_the_reaction_rolls_only_above_its_threshold_and_leans_on_the_tags(self):
        low = outlandish.react_plan(outlandish.score(MILD), u_speak=0.0, u_cat=0.5)
        self.assertFalse(low["react"])
        self.assertEqual(low["stages"], [])
        r = outlandish.score(HIGH)
        plan = outlandish.react_plan(r, u_speak=0.0, u_cat=0.5)
        self.assertTrue(plan["react"])
        cat = plan["stages"][1]
        self.assertTrue(any("the line is" in w for c in cat["candidates"] for w in c["why"]))
        self.assertIn(plan["category"], sfx_repertoire.CATEGORIES)
        self.assertFalse(outlandish.react_plan(r, u_speak=0.999, u_cat=0.5)["react"])

    def test_the_mini_round_and_the_cut_in_odds(self):
        self.assertIn(outlandish.miniround_plan(u=0.0)["turns"], (3, 4, 6))
        self.assertEqual({outlandish.miniround_plan(u=u / 20)["turns"] for u in range(20)}, {3, 4, 6})
        self.assertEqual(outlandish.cutin_odds(10)[0], 0.0)
        self.assertLess(outlandish.cutin_odds(35)[0], outlandish.cutin_odds(90)[0])
        self.assertLessEqual(outlandish.cutin_odds(10000)[0], 0.6)

    def test_the_holding_aside_never_mentions_waiting(self):
        plan = outlandish.hold_plan(u_share=0.0, u_cat=0.3, u_item=0.3, u_seat=0.3)
        self.assertTrue(plan["aside"])
        self.assertIn(plan["seat"], ("A", "B", "D"))
        d = outlandish.hold_direction(plan)
        self.assertIn("Do NOT mention waiting", d)
        self.assertFalse(outlandish.hold_plan(u_share=0.99)["aside"])


class RepertoireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.rep = sfx_repertoire.Repertoire(str(Path(self.tmp.name) / "r.db"))
        self.addCleanup(self.rep.close)

    def test_the_classifier_files_micro_moments_and_game_sounds(self):
        got = dict((c, v) for c, v, _w in sfx_repertoire.classify("oh my god", "memes", "", 1.2, True))
        self.assertIn("gasp", got)
        self.assertGreater(got["gasp"], 0.7)
        game = dict((c, v) for c, v, _w in sfx_repertoire.classify("mario death", "8-bit game sfx", "", 2.0, False))
        self.assertIn("fail", game)
        self.assertEqual(sfx_repertoire.classify("a long ambient pad", "pads", "", 45.0, False), [])
        self.assertNotIn("what", dict((c, v) for c, v, _w in sfx_repertoire.classify(
            "tell me what you think about the budget", "talk", "", 4.0, False)))

    def test_votes_and_marks_teach_him(self):
        for sid, name in (("a", "oh my god"), ("b", "gasp"), ("c", "whoa")):
            self.rep.note_clip(sid, "/x/%s.mp4" % sid, name, "memes", 1.5, True, source="backfill")
        base = {c["sid"]: c["weight"] for c in self.rep.shortlist("gasp")}
        self.rep.vote("c", "up")
        self.rep.mark("c", "gasp")
        top = self.rep.shortlist("gasp")
        self.assertEqual(top[0]["sid"], "c")
        self.assertGreater(top[0]["weight"], base["c"] * 4)
        self.assertEqual(top[0]["source"], "your mark")
        self.rep.vote("a", "down")
        self.assertLess(next(c for c in self.rep.shortlist("gasp") if c["sid"] == "a")["weight"], base["a"])
        self.assertEqual([c["sid"] for c in self.rep.shortlist("gasp", used=lambda s: s != "b")], ["b"])
        st = self.rep.stats()
        self.assertEqual(st["marked"], 1)
        self.assertEqual(st["reactions_from_upvotes"], 1)
        self.assertEqual(self.rep.mark("c", "nonsense")["ok"], False)

    def test_the_backfill_walks_the_clip_book_with_a_cursor(self):
        import sqlite3
        book = Path(self.tmp.name) / "sfx_clips.db"
        con = sqlite3.connect(str(book))
        con.execute("CREATE TABLE clips (path TEXT PRIMARY KEY, sid TEXT, name TEXT, folder TEXT, video INTEGER, "
                    "seconds REAL, playable INTEGER, said TEXT)")
        rows = [("/s/%d.mp4" % i, "s%d" % i, ["booing crowd", "a pad", "rimshot", "huh"][i % 4], "sfx", 1, 1.5, 1, None)
                for i in range(40)]
        con.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
        a = self.rep.backfill(str(book), cap=25)
        b = self.rep.backfill(str(book), cap=25)
        self.assertEqual(a["read"] + b["read"], 40)
        self.assertTrue(b["wrapped"])
        self.assertEqual(self.rep.stats()["by_category"]["rimshot"], 10)


class EngineTests(unittest.TestCase):
    def plan(self, config, seed="outl-1", turns=10, controls=None):
        inputs = {"road": "banter", "seats": ["A", "B"], "names": {"A": "Host", "B": "Co-host"},
                  "turns": turns, "target_seconds": turns * 12, "subject": {"topic": "the budget"},
                  "availability": {}, "speakerbox_rates": {}, "round_rolls": True,
                  "interjections": ["Oh, come on.", "No.", "Stop."]}
        settings = system3.normalise_settings({"controls": controls or {}})
        conv = system3.new_conversation(inputs, config, settings, seed=seed)
        system3.plan_more(conv, config)
        return conv

    def test_the_golden_path_is_untouched_without_the_tables(self):
        a = self.plan(system3.default_config())
        b = self.plan(system3.default_config())
        fams = {e["family"] for e in a["decision_events"]}
        self.assertFalse(fams & {"MEASURE", "CUTIN", "MINIROUND"})
        self.assertEqual([(e["family"], (e.get("rng") or {}).get("u")) for e in a["decision_events"]],
                         [(e["family"], (e.get("rng") or {}).get("u")) for e in b["decision_events"]])

    def test_the_cut_in_is_a_turn_in_the_round_with_its_own_rolls(self):
        config = config_with(CUTIN1={"base": 5.0, "max": 5.0, "min_words": 0.1})
        conv = self.plan(config, controls={"interjections": 0.5})
        evs = [e for e in conv["decision_events"] if e["family"] == "CUTIN"]
        self.assertTrue(evs)
        self.assertFalse([e for e in conv["decision_events"] if e["family"] == "INTERJECT"])
        hit = next(e for e in evs if e["selected"]["id"] == "CUT_IN")
        cut = next(t for t in conv["turns"] if t["turn_id"] == hit["meta"]["cutin_turn"])
        self.assertEqual(cut["step"], "interject")
        self.assertIn(cut["interject"][0], ("Oh, come on.", "No.", "Stop."))
        self.assertTrue(any(d["family"] == "RS" for d in cut["decisions"]))
        self.assertTrue(any(t.get("carry_on") for t in conv["turns"]))
        self.assertEqual([s["stage"] for s in hit["stages"]], ["dice", "seat", "phrase"])
        tree = script_decision_tree.build_round(conv)
        self.assertTrue(any(el.get("type") == "diamond" and el.get("node") == "cutin" for el in tree["elements"]))
        per_round = int(outlandish.dial(outlandish.table_of(config, "CUTIN1"), "per_round", 2, "raw"))
        self.assertLessEqual(sum(1 for t in conv["turns"] if t.get("cutin")), per_round)

    def test_an_outlandish_line_raises_the_next_seats_dispute_odds(self):
        config = config_with()
        conv = self.plan(config)
        system3.observe(conv, 0, HIGH)
        system3.replan(conv, config, 1)
        t0, t1 = conv["turns"][0], conv["turns"][1]
        self.assertTrue(any(d["family"] == "MEASURE" for d in t0["decisions"]))
        why = [w for e in conv["decision_events"] if e.get("turn_id") == t1["turn_id"] and e["family"] in ("RS", "IRS")
               for st in e["stages"] for c in st.get("candidates") or [] for w in c.get("why") or []]
        self.assertTrue(any(w.startswith("after an outlandish line") for w in why), why[:8])
        # a plain line moves nothing
        conv2 = self.plan(config, seed="outl-2")
        system3.observe(conv2, 0, MILD)
        system3.replan(conv2, config, 1)
        why2 = [w for e in conv2["decision_events"] for st in e["stages"] for c in st.get("candidates") or []
                for w in c.get("why") or []]
        self.assertFalse(any(w.startswith("after an outlandish line") for w in why2))

    def test_the_boost_moves_the_reply_toward_a_dispute(self):
        config = config_with()
        hits = {"plain": 0, "high": 0}
        for n in range(80):
            for kind, text in (("plain", MILD), ("high", HIGH)):
                conv = self.plan(config, seed="mc-%d" % n, turns=4)
                system3.observe(conv, 0, text)
                system3.replan(conv, config, 1)
                if outlandish.is_dispute(conv["turns"][1]["decisions"]):
                    hits[kind] += 1
        self.assertGreater(hits["high"], hits["plain"])


class RuntimeTests(unittest.TestCase):
    def boot(self, only_react="gasp", **dial_over):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        st = self.station = FakeStation(self.tmp.name)
        self.notes, self.stings, self.said, self.weights = [], [], [], {}
        clips = Path(self.tmp.name) / "clips"
        clips.mkdir()
        for name in ("gasp one.mp4", "gasp two.mp4", "gasp three.mp3", "record scratch.mp4"):
            (clips / name).write_bytes(b"x")

        async def dj_sting(to_box, after="", who="", force=False, sample=None):
            self.stings.append((str(sample), who, force))
            return str(sample)

        async def dj_speak(kind, track=None, extra="", who="dj", **kw):
            self.said.append((kind, who, extra))
            return "A quick aside."

        st.update(
            sfx_mp4_only=lambda: True,
            sfx_clip_refusal=lambda p: "mp4-only" if not str(p).endswith(".mp4") else "",
            norepeat_sfx_used=lambda sid: sid == "g1",
            sfx_match_score=lambda line, ctx="", video=None, limit=24: [],
            sfx_match_rows=lambda cands, most=24: [],
            sfx_id=lambda p: Path(str(p)).stem.replace(" ", "")[:8],
            _sfx_roll_note=lambda *a: self.notes.append(a),
            dj_sting=dj_sting, dj_speak=dj_speak, fire_and_forget=lambda coro: self._run(coro),
            _RADIO={"voice_to": "page", "chat": [{"id": "aside1", "text": "A quick aside.", "who": "dj"}]},
            _S3_LINE_BY_ID={},
            sfx_id_of_line=lambda lid: ("g2", "") if lid == "clipline" else ("", "not a sound effect"),
            sfx_by_id=lambda sid: clips / "gasp two.mp4",
            sfx_seconds=lambda p: 1.4, sfx_is_video=lambda p: str(p).endswith(".mp4"),
            sfx_weights=lambda: dict(self.weights),
            sfx_set_weight=lambda sid, w: self.weights.__setitem__(sid, w) or self.weights,
            line_vote_apply=lambda lid, vote: {"ok": True, "vote": vote, "say": "noted"},
        )
        app = FastAPI()
        system3_runtime.install(app, st)
        self.orr = outlandish_runtime.install(app, st)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.orr.stop.set)
        self.rt = st["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active_selected_roads",
                                                             "roads": ["banter", "interject"], "test_seed": "o-1"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        cfg = copy.deepcopy(self.rt.config)
        for t in cfg["tables"]:
            for tid, dials in dial_over.items():
                if t["id"] != tid:
                    continue
                for cat in t["categories"]:
                    for it in cat["items"]:
                        if cat["id"] == "dials" and it["id"] in dials:
                            it["weight"] = dials[it["id"]]
        for t in cfg["tables"]:
            if t["id"] == "SFXREACT1" and only_react:
                for cat in t["categories"]:
                    if cat["id"] not in ("dials", only_react):
                        cat["weight"] = 0.0
        st_i = system3.road_structure(cfg, "interject")
        g = conversation_graph.road_graph("interject", st_i)
        g["enabled"] = True
        cfg.setdefault("structures", {})["interject"] = dict(st_i, graph=g)
        self.rt.config = cfg
        rep = self.orr.rep
        rep.note_clip("g1", str(clips / "gasp one.mp4"), "gasp one", "memes", 1.2, True, source="backfill")
        rep.note_clip("g2", str(clips / "gasp two.mp4"), "oh my god", "memes", 1.4, True, source="backfill")
        rep.note_clip("g3", str(clips / "gasp three.mp3"), "gasp", "memes", 1.0, False, source="backfill")
        rep.note_clip("s1", str(clips / "record scratch.mp4"), "record scratch", "memes", 1.0, True, source="backfill")
        return self.rt

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_the_six_tables_are_added_once(self):
        rt = self.boot()
        ids = {t["id"] for t in rt.config["tables"]}
        self.assertTrue(set(outlandish.TABLE_IDS) <= ids)

    def test_an_interjection_is_a_mini_round_and_a_board_clip_a_one_liner(self):
        rt = self.boot()
        h = self._run(self.station["system3_direct_line"](road="interject", who="dj", dj=ctx()["dj"],
                                                          context="an outburst", text=HIGH))
        conv = h.conv
        mini = next(e for e in conv["decision_events"] if e["family"] == "MINIROUND")
        self.assertEqual(len(conv["turns"]), conv["miniround"]["turns"])
        self.assertIn(len(conv["turns"]), (3, 4, 6))
        self.assertTrue(mini["stages"][0]["draw"]["dice"])
        self.assertTrue(any(d["family"] == "MEASURE" for d in conv["turns"][0]["decisions"]))
        why = [w for e in conv["decision_events"] if e.get("turn_index") == 1 and e["family"] in ("RS", "IRS")
               for s in e["stages"] for c in s.get("candidates") or [] for w in c.get("why") or []]
        self.assertTrue(any(w.startswith("after an outlandish line") for w in why))
        plan = rt.line_chapter(h.stamp)
        self.assertTrue(plan["chapter"])
        board = self._run(self.station["system3_direct_line"](road="interject", who="board", seat="D",
                                                              name="The SFX board", context="a clip", text=""))
        self.assertEqual(len(board.conv["turns"]), 1)
        self.assertIn("sound", board.conv["inputs"]["one_line"])
        bumper = self._run(self.station["system3_direct_line"](road="interject", who="dj", dj=ctx()["dj"],
                                                               context="x", text="Back to it.",
                                                               one_line="the ad's out-bumper"))
        self.assertEqual(len(bumper.conv["turns"]), 1)

    def test_the_opener_primes_its_replies(self):
        rt = self.boot()
        h = self._run(self.station["system3_direct_line"](road="interject", who="dj", dj=ctx()["dj"],
                                                          context="a line", text=""))
        got = self.orr.prime_chapter(h.stamp, HIGH)
        self.assertTrue(got["primed"])
        conv = rt.recent[h.id]
        self.assertEqual(conv["turns"][0]["text"], HIGH)
        self.assertTrue(conv.get("outlandish_primed"))
        self.assertFalse(self.orr.prime_chapter(h.stamp, HIGH))       # once

    def test_the_sfx_guy_reacts_with_a_fresh_mp4(self):
        rt = self.boot(SFXREACT1={"odds_at_react": 5.0, "odds_at_100": 5.0})
        h = self._run(self.station["system3_direct_banter"](**ctx()))
        cid = h.id
        meta = {"system3": {"conversation_id": cid, "mode": "active"},
                "script": "A: %s\nB: Oh come off it." % HIGH,
                "turn_dice": {"0": {"s3": {"turn_id": cid + ":t00"}}}}
        clip = self.orr.react_clip(HIGH, "dj", meta, "round")
        self.assertIsNotNone(clip)
        self.assertTrue(str(clip).endswith(".mp4"))
        self.assertNotIn("gasp one", str(clip))                      # heard inside the day
        self.assertEqual(self.notes[-1][1], "reaction")
        self.assertIsNone(self.orr.react_clip(MILD, "dj", meta, "round"))
        settle()
        obs = [o for o in rt.store.conversation(cid)["observations_air"] if o.get("family") == "SFXREACT"]
        self.assertTrue(obs)
        self.assertEqual(obs[-1]["turn_id"], cid + ":t00")
        self.assertIn("reacts:", obs[-1]["selected"]["label"])

    def test_between_the_opener_and_the_reply(self):
        self.boot(SFXREACT1={"odds_at_react": 5.0, "odds_at_100": 5.0})
        e = {"opening": HIGH, "rows": [{"stamp": {"conversation_id": "", "turn_id": ""}}]}
        self.assertTrue(self._run(self.orr.react_between(e)))
        self.assertEqual(self.stings[-1][1], "sfxguy")
        self.assertTrue(self.stings[-1][2])
        self.assertFalse(self._run(self.orr.react_between({"opening": MILD})))

    def test_the_audit_log_the_tile_the_feed_and_the_review(self):
        rt = self.boot()
        h = self._run(self.station["system3_direct_banter"](**ctx()))
        cid, tid = h.id, h.conv["turns"][0]["turn_id"]
        self.station["_S3_LINE_BY_ID"]["line1"] = {"conversation_id": cid, "turn_id": tid}
        rt.store.add_lines([{"line_id": "line1", "conversation_id": cid, "turn_id": tid, "who": "dj", "text": HIGH,
                             "at": time.time()}])
        self.orr.note_row({"id": "line1", "who": "dj", "text": HIGH, "aired": "heard", "kind": "banter",
                           "round": "banter", "air_at": time.time()})
        self.orr.note_row({"id": "line2", "who": "cohost", "text": MILD, "aired": "heard", "air_at": time.time()})
        self.orr.note_row({"id": "line1", "who": "dj", "text": HIGH, "aired": "heard", "air_at": time.time()})
        settle()
        self.assertEqual(self.orr.metrics["scored"], 2)
        flow = [f for f in self.station.flow if f[0] == "outlandish"]
        self.assertEqual(len(flow), 1)
        self.assertEqual(flow[0][3]["line_id"], "line1")
        auth = {"Authorization": "Bearer k"}
        line = self.client.get("/api/system3/line?line_id=line1", headers=auth).json()
        meas = [d for d in line["decisions"] if d.get("family") == "MEASURE"]
        self.assertTrue(meas and meas[0]["selected"]["label"].startswith("OUTLANDISH"))
        dice = self.client.get("/api/system3/dice?ids=line1", headers=auth).json()
        self.assertTrue(any(r.get("family") == "MEASURE" for r in dice["lines"]["line1"]["air"]))
        rev = self.client.get("/api/outlandish?hours=1", headers=auth).json()
        self.assertEqual(rev["count"], 1)
        item = rev["items"][0]
        self.assertEqual(item["code"], "#line1")
        self.assertIn(item["follow"], ("aired", "planned_cut", "none"))
        self.assertEqual(rev["lines"], 2)
        csv = self.client.get("/api/outlandish?hours=1&format=csv", headers=auth)
        self.assertTrue(csv.text.startswith("code,aired_utc,who,road,score"))
        self.assertIn("#line1", csv.text)
        score = self.client.post("/api/outlandish/score", json={"text": HIGH}, headers=auth).json()
        self.assertGreaterEqual(score["reading"]["score"], 90)
        self.assertTrue(score["dispute_boost"])

    def test_votes_and_marks_reach_his_repertoire(self):
        self.boot()
        auth = {"Authorization": "Bearer k"}
        r = self.client.post("/api/sfxguy/reactions/mark", json={"line_id": "clipline", "category": "fail"},
                             headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        got = self.station["line_vote_apply"]("clipline", "up")
        self.assertIn("SFX Guy files it", got["say"])
        self.assertEqual(self.weights["g2"], 1.5)
        top = self.orr.rep.shortlist("fail")
        self.assertEqual(top[0]["sid"], "g2")
        self.assertEqual(top[0]["source"], "your mark")
        stats = self.client.get("/api/sfxguy/reactions", headers=auth).json()
        self.assertEqual(stats["repertoire"]["reactions_from_upvotes"], 1)
        self.assertEqual(self.client.post("/api/sfxguy/reactions/mark", json={"line_id": "nope", "category": "fail"},
                                          headers=auth).status_code, 400)

    def test_the_holding_moment_is_an_aside(self):
        self.boot(HOLDBANTER1={"banter_share": 5.0})
        plan = self.orr.hold_roll("the emergency reserve was reached")
        self.assertTrue(plan["aside"])
        self.assertEqual(self.said[-1][0], "aside")
        self.assertIn("Do NOT mention waiting", self.said[-1][2])
        self.assertIsNone(self.orr.hold_roll("again"))                # rested


if __name__ == "__main__":
    unittest.main()
