"""[s3-memory] What the writer is reminded of is System 3's MEMORY roll.

The operator's guide (2026-09-28): memory context is given ONLY WHEN RELEVANT -
the clock, the last topic, the last segment and how it went, the callers
against the quota, the manager's last word - "rules, then roulette": each
kind's rule decides eligibility (recorded with why), the roulette draws among
the eligible on the round's own stream, and the writer's memory block carries
exactly the items drawn."""
import asyncio
import copy
import importlib.util
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import system3
import system3_tables

ROOT = Path(__file__).resolve().parents[1]
AT = 1790000000.0                  # a fixed "now" for the plans: every rule reads inputs.at


def facts(**over):
    """Every kind relevant: 3 min to the top of the hour, a subject 6 min ago,
    News just handed over, 1 call against 4 an hour at minute 57, the manager 5
    min ago."""
    base = {
        "clock": {"at": AT, "hour": 15, "minute": 57, "second": 0, "clock": "3:57 pm",
                  "segment": {"label": "Talk radio", "kind": "banter", "started": AT - 120, "ends": AT + 900}},
        "last_topic": {"topic": "the parking meter tax on Elm Street", "keywords": ["parking", "meter", "street"],
                       "at": AT - 360, "landing": "Pay the meter, you animal.", "landing_who": "Skip"},
        "last_segment": {"label": "News", "kind": "news", "started": AT - 900, "ended": AT - 120, "heard": 12,
                         "withdrawn": 1, "calls": 0, "now": {"label": "Talk radio", "started": AT - 120}},
        "callers_quota": {"count": 1, "quota": 4, "minute": 57.0, "paused": False},
        "manager_note": {"text": "Spin more records and stop talking about parking.", "at": AT - 300},
    }
    for k, v in over.items():
        if v is None:
            base.pop(k, None)
        else:
            base[k] = v
    return base


def inputs(memory=None, **over):
    base = {"road": "banter", "at": AT, "seats": ["A", "B"], "turns": 8, "names": {"A": "Dill", "B": "Skip"},
            "subject": {"topic": "whether the new barbecue joint deserves the hype",
                        "keywords": ["barbecue", "joint", "deserves"], "authority": "obligated"},
            "memory_rolls": True, "memory": facts() if memory is None else memory}
    base.update(over)
    return base


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def plan(seed="mem", config=None, memory=None, **over):
    return system3.plan_scene(inputs(memory, **over), config or system3.default_config(), settings(seed),
                              conversation_id="mem-" + seed)


def memory_event(conv):
    got = [e for e in conv["decision_events"] if e["family"] == "MEMORY"]
    return got[0] if got else None


def verdicts(conv):
    return {v["id"]: v for v in memory_event(conv)["meta"]["verdicts"]}


def memory_table(config):
    return next(t for t in config["tables"] if t["id"] == "MEMORY1")


def set_rule(config, kind, **rule):
    cat = next(c for c in memory_table(config)["categories"] if c["id"] == kind)
    cat["rule"].update(rule)
    return config


def without_memory_table(config):
    config["tables"] = [t for t in config["tables"] if t.get("family") != "MEMORY"]
    return config


class RuleTests(unittest.TestCase):
    """The rules decide eligibility, and say why either way."""

    def test_every_kind_is_relevant_in_the_busy_moment(self):
        v = verdicts(plan())
        self.assertEqual({k: v[k]["state"] for k in v},
                         {"clock": "top", "last_topic": "contrasts", "last_segment": "smooth",
                          "callers_quota": "behind", "manager_note": "fresh"})
        self.assertTrue(all(x["eligible"] for x in v.values()))

    def test_the_clock_only_near_the_top_of_the_hour_or_a_segment_end(self):
        mid = facts(clock={"at": AT, "hour": 15, "minute": 31, "second": 0, "clock": "3:31 pm",
                           "segment": {"label": "Talk radio", "started": AT - 600, "ends": AT + 900}})
        v = verdicts(plan(memory=mid))["clock"]
        self.assertFalse(v["eligible"])
        self.assertIn("31 min past the hour", v["why"])
        just = facts(clock={"at": AT, "hour": 16, "minute": 1, "second": 30, "clock": "4:01 pm", "segment": {}})
        self.assertEqual(verdicts(plan(memory=just))["clock"]["state"], "past")
        ending = facts(clock={"at": AT, "hour": 15, "minute": 31, "second": 0, "clock": "3:31 pm",
                              "segment": {"label": "Talk radio", "started": AT - 600, "ends": AT + 90}})
        self.assertEqual(verdicts(plan(memory=ending))["clock"]["state"], "segment")
        # the rule's numbers are the table's: widen "before the top" and 3:31 is near enough
        cfg = set_rule(system3.default_config(), "clock", before_top=30)
        self.assertEqual(verdicts(plan(memory=mid, config=cfg))["clock"]["state"], "top")

    def test_the_manager_only_while_his_word_is_fresh(self):
        old = facts(manager_note={"text": "Talk less.", "at": AT - 45 * 60})
        v = verdicts(plan(memory=old))["manager_note"]
        self.assertFalse(v["eligible"])
        self.assertIn("45 min ago", v["why"])
        cfg = set_rule(system3.default_config(), "manager_note", within_minutes=60)
        self.assertTrue(verdicts(plan(memory=old, config=cfg))["manager_note"]["eligible"])
        # on his own road his words are the round's material, not a memory
        self.assertFalse(verdicts(plan(road="manager"))["manager_note"]["eligible"])
        self.assertFalse(verdicts(plan(memory=facts(manager_note=None)))["manager_note"]["eligible"])

    def test_the_callers_only_when_behind_or_ahead_by_the_margin(self):
        def state(**c):
            base = {"count": 1, "quota": 4, "minute": 57.0, "paused": False}
            base.update(c)
            return verdicts(plan(memory=facts(callers_quota=base)))["callers_quota"]
        self.assertEqual(state()["state"], "behind")
        self.assertEqual(state(count=4, minute=40.0)["state"], "ahead")
        # ahead is the clock hour's own count: the last hour's tail in the rolling
        # count never makes this hour look ahead
        self.assertFalse(state(count=3, this_hour=1, minute=20.0)["eligible"])
        self.assertEqual(state(count=3, this_hour=3, minute=20.0)["state"], "ahead")
        self.assertEqual(state(count=5, this_hour=4, minute=50.0)["state"], "ahead", "the hour's quota is met")
        cfg = system3.default_config()
        for c in memory_table(cfg)["categories"]:
            c["weight"] = 1.0 if c["id"] == "callers_quota" else 0.0
        ahead = facts(callers_quota={"count": 3, "this_hour": 3, "quota": 4, "minute": 20.0, "paused": False})
        self.assertIn("3 calls since the top of the hour against 4 an hour",
                      system3.memory_text(plan(memory=ahead, config=cfg)))
        on_pace = state(count=2, minute=30.0)
        self.assertFalse(on_pace["eligible"])
        self.assertIn("on pace", on_pace["why"])
        self.assertFalse(state(minute=10.0)["eligible"], "too early in the hour to judge")
        self.assertFalse(state(quota=0)["eligible"], "the dial is off")
        self.assertFalse(state(paused=True)["eligible"], "off air nobody is behind")
        cfg = set_rule(system3.default_config(), "callers_quota", behind=False)
        self.assertFalse(verdicts(plan(config=cfg))["callers_quota"]["eligible"])

    def test_the_last_topic_only_when_this_round_carries_it_on_or_turns_from_it(self):
        self.assertEqual(verdicts(plan())["last_topic"]["state"], "contrasts")
        same = {"topic": "the parking meters scam downtown", "keywords": ["parking", "meters", "scam"],
                "authority": "obligated"}
        v = verdicts(plan(subject=same))["last_topic"]
        self.assertEqual(v["state"], "continues")
        self.assertIn("parking", v["why"])
        free = {"topic": "", "keywords": [], "authority": "free"}
        self.assertEqual(verdicts(plan(subject=free))["last_topic"]["state"], "continues")
        stale = facts(last_topic={"topic": "the parking meter tax", "at": AT - 3 * 3600})
        self.assertFalse(verdicts(plan(memory=stale))["last_topic"]["eligible"])
        cfg = set_rule(system3.default_config(), "last_topic", contrasts=False)
        self.assertFalse(verdicts(plan(config=cfg))["last_topic"]["eligible"])

    def test_the_last_segment_only_at_the_start_of_the_next(self):
        self.assertEqual(verdicts(plan())["last_segment"]["state"], "smooth")
        later = facts(last_segment={"label": "News", "started": AT - 1800, "ended": AT - 600, "heard": 9,
                                    "withdrawn": 0, "calls": 0, "now": {"label": "Talk radio", "started": AT - 600}})
        v = verdicts(plan(memory=later))["last_segment"]
        self.assertFalse(v["eligible"])
        self.assertIn("past the hand-over", v["why"])
        rough = facts(last_segment={"label": "News", "started": AT - 900, "ended": AT - 60, "heard": 0,
                                    "withdrawn": 4, "calls": 0, "now": {"label": "Talk radio", "started": AT - 60}})
        self.assertEqual(verdicts(plan(memory=rough))["last_segment"]["state"], "rough")
        self.assertFalse(verdicts(plan(memory=facts(last_segment=None)))["last_segment"]["eligible"])
        # something ran in between that no round saw: nothing is said about it
        unseen = facts(last_segment={"label": "", "kind": "", "unseen": True, "started": AT - 900, "ended": AT - 60,
                                     "now": {"label": "Talk radio", "started": AT - 60}})
        v = verdicts(plan(memory=unseen))["last_segment"]
        self.assertFalse(v["eligible"])
        self.assertIn("no round planned in it", v["why"])

    def test_a_banked_round_is_told_nothing_unless_a_rule_says_so(self):
        conv = plan(bank=True)
        self.assertFalse(any(v["eligible"] for v in verdicts(conv).values()))
        self.assertTrue(all("banked" in v["why"] for v in verdicts(conv).values()))
        self.assertEqual(system3.memory_text(conv), "")
        cfg = set_rule(system3.default_config(), "manager_note", on_banked=True)
        v = verdicts(plan(bank=True, config=cfg))
        self.assertTrue(v["manager_note"]["eligible"])
        # System 2's slot writes for the air it will get: the round is live
        self.assertTrue(verdicts(plan(bank=True, system2_job_id="job-1"))["clock"]["eligible"])

    def test_a_kind_may_be_kept_to_some_roads(self):
        cfg = system3.default_config()
        cat = next(c for c in memory_table(cfg)["categories"] if c["id"] == "callers_quota")
        cat["roads"] = ["caller"]
        v = verdicts(plan(config=cfg))["callers_quota"]
        self.assertFalse(v["eligible"])
        self.assertIn("not on the banter road", v["why"])
        cleaned = system3.validate_table(dict(memory_table(cfg)))
        self.assertEqual(next(c for c in cleaned["categories"] if c["id"] == "callers_quota")["roads"], ["caller"])
        cat["roads"] = ["caller", "no-such-road"]
        cleaned = system3.validate_table(dict(memory_table(cfg)))
        self.assertEqual(next(c for c in cleaned["categories"] if c["id"] == "callers_quota")["roads"], ["caller"])

    def test_a_kind_the_desk_adds_rolls_on_the_fact_of_its_name(self):
        cfg = system3.default_config()
        memory_table(cfg)["categories"].append(
            {"id": "speaker_outage", "label": "The speaker is out", "weight": 1.0, "rule": {},
             "items": [{"id": "panic", "label": "Panic", "weight": 1.0, "text": "{synopsis}"}]})
        mem = facts(speaker_outage={"text": "the pine box speaker has carried nothing for 6 minutes", "minutes": 6.0})
        self.assertTrue(verdicts(plan(memory=mem, config=cfg))["speaker_outage"]["eligible"])
        self.assertFalse(verdicts(plan(config=cfg))["speaker_outage"]["eligible"], "no such fact: nothing to say")
        for c in memory_table(cfg)["categories"]:
            if c["id"] != "speaker_outage":
                c["weight"] = 0.0
        self.assertIn("carried nothing for 6 minutes", system3.memory_text(plan(memory=mem, config=cfg)))

    def test_a_host_with_no_facts_is_told_nothing_and_says_why(self):
        conv = plan(memory={})
        ev = memory_event(conv)
        self.assertEqual(ev["meta"]["eligible"], 0)
        self.assertEqual(ev["selected"]["id"], "NONE")
        self.assertEqual([s["stage"] for s in ev["stages"]], ["rules"])
        self.assertIsNone(ev["rng"])
        self.assertEqual(system3.memory_text(conv), "")
        self.assertTrue(all(v["why"] for v in ev["meta"]["verdicts"]))


class RouletteTests(unittest.TestCase):
    """Then the roulette decides among the eligible, on its own stream."""

    def test_the_roulette_draws_only_among_the_eligible(self):
        # the clock and the callers are not relevant here; over many seeds they are never drawn
        mem = facts(clock={"at": AT, "hour": 15, "minute": 31, "second": 0, "clock": "3:31 pm", "segment": {}},
                    callers_quota={"count": 2, "quota": 4, "minute": 31.0, "paused": False})
        seen = set()
        for seed in map(str, range(60)):
            conv = plan(seed=seed, memory=mem)
            ev = memory_event(conv)
            eligible = {v["id"] for v in ev["meta"]["verdicts"] if v["eligible"]}
            self.assertEqual(eligible, {"last_topic", "last_segment", "manager_note"})
            drawn = {x["kind"] for x in ev["selected"]["items"]}
            self.assertTrue(drawn and drawn <= eligible, drawn)
            seen |= drawn
            pick = next(s for s in ev["stages"] if s["stage"] == "item")
            self.assertEqual({c["id"] for c in pick["candidates"]}, eligible)
            self.assertEqual({x["id"] for x in pick["excluded"]}, {"clock", "callers_quota"})
            self.assertTrue(all(x["why"] for x in pick["excluded"]))
        self.assertEqual(seen, {"last_topic", "last_segment", "manager_note"}, "every eligible kind comes up")

    def test_how_many_is_between_least_and_most_and_never_more_than_are_eligible(self):
        counts = set()
        for seed in map(str, range(40)):
            ev = memory_event(plan(seed=seed))
            counts.add(len(ev["selected"]["items"]))
            self.assertEqual(ev["meta"]["least"], 1)
            self.assertEqual(ev["meta"]["most"], 2)
        self.assertEqual(counts, {1, 2})
        one = facts(clock=None, last_topic=None, last_segment=None, callers_quota=None)
        ev = memory_event(plan(memory=one))
        self.assertEqual(len(ev["selected"]["items"]), 1)
        self.assertNotIn("how many", [s["stage"] for s in ev["stages"]], "one eligible: nothing to count")
        cfg = system3.default_config()
        memory_table(cfg).update(least=3, most=3)
        self.assertEqual(len(memory_event(plan(config=cfg))["selected"]["items"]), 3)
        cfg = system3.default_config()
        memory_table(cfg).update(least=0, most=0)
        self.assertEqual(memory_event(plan(config=cfg))["selected"]["items"], [])

    def test_the_event_records_every_candidate_its_weight_and_the_die(self):
        cfg = system3.default_config()
        next(c for c in memory_table(cfg)["categories"] if c["id"] == "manager_note")["weight"] = 3.0
        ev = memory_event(plan(config=cfg))
        rules = ev["stages"][0]
        self.assertEqual(rules["stage"], "rules")
        self.assertEqual({v["id"] for v in rules["verdicts"]}, set(system3.MEMORY_KINDS))
        for cat in memory_table(cfg)["categories"]:
            self.assertIn(cat["label"], rules["rule"], "every kind's verdict is in the words of the rules stage")
        self.assertIsNone(rules["draw"], "the rules draw no number")
        pick = next(s for s in ev["stages"] if s["stage"] == "item")
        weights = {c["id"]: c["weight"] for c in pick["candidates"]}
        self.assertEqual(weights["manager_note"], 3.0)
        self.assertEqual(weights["clock"], 1.0)
        self.assertTrue(1 <= pick["draw"]["dice"] <= 100)
        self.assertEqual(pick["draw"]["label"], "MEMORY:pick1")
        self.assertTrue(pick["draw"]["seed"].endswith("|round:MEMORY"))
        self.assertEqual(ev["rng"], pick["draw"])
        self.assertEqual(ev["turn_index"], -1)
        self.assertEqual(ev["selected"]["table"], "MEMORY1")

    def test_a_weight_of_nothing_is_never_drawn(self):
        cfg = system3.default_config()
        for c in memory_table(cfg)["categories"]:
            c["weight"] = 0.0 if c["id"] != "clock" else 1.0
        for seed in map(str, range(20)):
            ev = memory_event(plan(seed=seed, config=cfg))
            self.assertEqual([x["kind"] for x in ev["selected"]["items"]], ["clock"])

    def test_its_own_stream_the_table_absent_moves_no_other_draw(self):
        def strip(conv):
            return [(e["family"], (e.get("selected") or {}).get("id"), (e.get("rng") or {}).get("u"))
                    for e in conv["decision_events"] if e["family"] != "MEMORY"]

        def turns(conv):
            return [[t["speaker"], t["step"]] + [d.get("item") for d in t["decisions"] if d.get("family") != "MEMORY"]
                    for t in conv["turns"]]
        for seed in ("a", "b", "c"):
            with_table = plan(seed=seed)
            without = plan(seed=seed, config=without_memory_table(system3.default_config()))
            not_asked = plan(seed=seed, memory_rolls=False)
            self.assertIsNotNone(memory_event(with_table))
            self.assertIsNone(memory_event(without))
            self.assertIsNone(memory_event(not_asked))
            self.assertEqual(strip(with_table), strip(without))
            self.assertEqual(strip(with_table), strip(not_asked))
            self.assertEqual(turns(with_table), turns(without))
            self.assertEqual(with_table["draws"], without["draws"], "the round's own stream never moved")
            self.assertNotIn("memory", without)

    def test_the_block_carries_only_the_drawn_items(self):
        for seed in map(str, range(30)):
            conv = plan(seed=seed)
            ev = memory_event(conv)
            text = system3.memory_text(conv)
            items = ev["selected"]["items"]
            self.assertTrue(text.startswith(system3.MEMORY_HEAD))
            self.assertEqual(text, system3.MEMORY_HEAD + "; ".join(x["text"] for x in items) + ".")
            self.assertEqual(ev["selected"]["text"], text.strip())
            self.assertNotIn("{", text)
            drawn = {x["kind"] for x in items}
            said = {"clock": "3:57 pm", "manager_note": "Spin more records", "callers_quota": "the phones",
                    "last_segment": "News", "last_topic": "Elm Street"}
            for kind, words in said.items():
                if kind in drawn:
                    self.assertIn(words, text, kind)
                else:
                    self.assertNotIn(words, text, "%s was not drawn, so none of it is sent" % kind)
            first = conv["turns"][0]
            mine = [d for d in first["decisions"] if d["family"] == "MEMORY"]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["event_id"], ev["event_id"])
            self.assertFalse(any(d["family"] == "MEMORY" for t in conv["turns"][1:] for d in t["decisions"]))

    def test_a_way_of_putting_it_is_a_die_when_more_than_one_fits(self):
        one = facts(clock=None, last_topic=None, last_segment=None, callers_quota=None)
        ways = set()
        for seed in map(str, range(30)):
            ev = memory_event(plan(seed=seed, memory=one))
            way = next((s for s in ev["stages"] if s["stage"] == "the way: The manager's last word"), None)
            self.assertIsNotNone(way)
            self.assertEqual({c["id"] for c in way["candidates"]}, {"word", "hanging"})
            ways.add(ev["selected"]["items"][0]["item"])
        self.assertEqual(ways, {"word", "hanging"})
        # the clock's items each fit one state: no die for the way
        clock_only = facts(last_topic=None, last_segment=None, callers_quota=None, manager_note=None)
        ev = memory_event(plan(memory=clock_only))
        self.assertEqual(ev["selected"]["items"][0]["item"], "top")
        self.assertFalse([s for s in ev["stages"] if s["stage"].startswith("the way:")])

    def test_replay_and_a_replan_keep_the_roll(self):
        conv = plan(seed="replay")
        stored = copy.deepcopy(conv)
        got = system3.replay(stored, system3.default_config())
        self.assertTrue(got["ok"], got.get("why"))
        before = copy.deepcopy(conv["memory"])
        system3.replan(conv, system3.default_config(), 0)
        self.assertEqual(conv["memory"], before)
        self.assertEqual(sum(1 for e in conv["decision_events"] if e["family"] == "MEMORY"), 1)
        self.assertTrue(any(d["family"] == "MEMORY" for d in conv["turns"][0]["decisions"]))

    def test_every_planner_rolls_it(self):
        cfg = system3.default_config()
        news = system3.new_conversation(inputs(road="news", turns=6), cfg, settings("legs"))
        system3.plan_legs(news, cfg, road="news")
        self.assertIsNotNone(memory_event(news))
        call = system3.new_conversation(inputs(road="caller", seats=["A", "C"], turns=10,
                                               call={"first": "Ann", "name": "Ann Lee"}), cfg, settings("call"))
        system3.plan_call(call, cfg)
        self.assertIsNotNone(memory_event(call))
        line = system3.new_conversation(inputs(road="track_talk", seats=["A"], turns=1), cfg, settings("line"))
        system3.plan_line(line, cfg)
        v = verdicts(line)
        self.assertFalse(v["last_segment"]["eligible"], "a single line does not open a segment")
        stock = system3.new_conversation(inputs(road="interject", seats=["A"], turns=1,
                                                candidates=[{"id": "a", "text": "Oh come on."}]), cfg, settings("stock"))
        system3.plan_line(stock, cfg)
        self.assertIsNone(memory_event(stock), "a drawn stock line has no writer to remind")


class TableTests(unittest.TestCase):
    def test_memory1_is_a_default_table_and_validates(self):
        cfg = system3.default_config()
        t = memory_table(cfg)
        self.assertEqual(t["family"], "MEMORY")
        self.assertEqual({c["id"] for c in t["categories"]}, set(system3.MEMORY_KINDS))
        got = system3.validate_table(t)
        self.assertEqual((got["least"], got["most"]), (1, 2))
        self.assertIn("MEMORY", system3.FAMILIES)
        self.assertIn("MEMORY1", [x["id"] for x in system3_tables.default_tables()])

    def test_a_bad_rule_or_count_is_refused_or_clamped(self):
        t = copy.deepcopy(system3_tables.MEMORY1)
        t["categories"][0]["rule"]["before_top"] = "soon"
        with self.assertRaises(ValueError):
            system3.validate_table(t)
        t = copy.deepcopy(system3_tables.MEMORY1)
        t.update(least=4, most=2)
        got = system3.validate_table(t)
        self.assertEqual((got["least"], got["most"]), (4, 4))
        t = copy.deepcopy(system3_tables.MEMORY1)
        t["categories"][0]["items"][0]["when"] = {"no": 1}
        with self.assertRaises(ValueError):
            system3.validate_table(t)

    def test_the_memory_block_is_an_obligation_node(self):
        rules = system3.block_rules(system3.default_config())
        self.assertEqual(rules["memory"]["kind"], "obligation")
        self.assertEqual(rules["show_memory"]["kind"], "obligation")
        got = system3.decide_blocks(["show_memory", "memory"], system3.default_config(), "s")
        self.assertTrue(all(d["keep"] for d in got))


class RuntimeTests(unittest.TestCase):
    """The station's facts reach the round; the block reaches the writer."""

    def boot(self, hook=True, mode="active"):
        import system3_runtime
        from test_system3_runtime import FakeStation, settle
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.station = FakeStation(tmp.name)
        self.asked = []
        now = time.time()
        lt = time.localtime(now)
        self.facts = {
            "clock": {"at": now, "hour": lt.tm_hour, "minute": lt.tm_min, "second": lt.tm_sec, "clock": "now",
                      "segment": {}},
            "manager_note": {"text": "Spin more records.", "at": now - 60},
            "topic": {"text": "a passage about raccoons in the van", "at": now - 120},
        }
        if hook:
            self.station["system3_memory_facts"] = lambda road, c: self.asked.append(road) or copy.deepcopy(self.facts)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        client.post("/api/system3/settings", json={"mode": mode, "test_seed": "memrt"},
                    headers={"Authorization": "Bearer k"})
        return self.rt

    def plan_and_ask(self, **over):
        from test_system3_runtime import ctx

        async def go():
            h = await self.station["system3_direct_banter"](**ctx(**over))
            return h, self.station["system3_memory_block"]()
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(go())
        finally:
            loop.close()

    def test_the_host_facts_reach_the_round_and_its_block(self):
        self.boot()
        h, text = self.plan_and_ask(bank=False)
        self.assertEqual(self.asked, ["banter"])
        mem = h.conv["inputs"]["memory"]
        self.assertTrue(h.conv["inputs"]["memory_rolls"])
        self.assertEqual(mem["manager_note"]["text"], "Spin more records.")
        self.assertEqual(mem["last_topic"]["source"], "the last subject the station heard")
        self.assertNotIn("topic", mem)
        ev = memory_event(h.conv)
        self.assertIsNotNone(ev)
        self.assertTrue(verdicts(h.conv)["manager_note"]["eligible"])
        self.assertEqual(text, system3.memory_text(h.conv))
        self.assertTrue(text.startswith(system3.MEMORY_HEAD))
        for x in ev["selected"]["items"]:
            self.assertIn(x["text"], text)

    def test_a_banked_round_gets_an_empty_block_not_the_digest(self):
        self.boot()
        h, text = self.plan_and_ask(bank=True)
        self.assertEqual(text, "")
        self.assertIsNotNone(memory_event(h.conv))

    def test_a_host_without_the_hook_rolls_and_finds_nothing(self):
        self.boot(hook=False)
        h, text = self.plan_and_ask(bank=False)
        self.assertEqual(memory_event(h.conv)["meta"]["eligible"], 0)
        self.assertEqual(text, "")

    def test_no_active_round_no_block(self):
        rt = self.boot()
        self.assertIsNone(self.station["system3_memory_block"]())
        rt.settings = system3.normalise_settings({"mode": "off"})
        h, text = self.plan_and_ask(bank=False)
        self.assertIsNone(h)
        self.assertIsNone(text, "System 3 off: the station keeps its own show memory")

    def test_the_last_topic_is_the_last_round_on_the_air(self):
        rt = self.boot()
        old = system3.plan_scene({"road": "banter", "subject": {"topic": "the raccoon took the van", "keywords": []}},
                                 system3.default_config(), settings("old"), conversation_id="old-round")
        rt.remember(old)
        rt.carry = {"at": time.time() - 90, "from": "old-round", "road": "banter", "seats": {}, "dynamics": {},
                    "unresolved": [], "landing": {"who": "cohost", "name": "Skip", "text": "Get the van back."},
                    "tempers": []}
        got = rt.memory_inputs("banter", {}, "")["memory"]["last_topic"]
        self.assertEqual(got["topic"], "the raccoon took the van")
        self.assertEqual(got["from"], "old-round")
        self.assertEqual(got["landing_who"], "Skip")
        self.assertIn("raccoon", got["keywords"])
        self.assertEqual(got["source"], "System 3's record of the last round on air")


def _app_text():
    return (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def _top_level(text, head):
    """One top-level statement of app.py, from `head` to the next line that
    starts in column 0 (tests/test_system3_blocks2.py's reader)."""
    i = text.find("\n" + head) + 1
    if not i:
        raise AssertionError("app.py has no top-level %r (is system3_memory_patch applied?)" % head)
    out = [text[i:text.index("\n", i) + 1]]
    j = i + len(out[0])
    while j < len(text):
        k = text.index("\n", j) + 1
        line = text[j:k]
        if line.strip() and not line[0].isspace() and not line.startswith(")"):
            break
        out.append(line)
        j = k
    return "".join(out)


class _Clock:
    """`time` for the extracted functions: the station runs on Linux, where
    strftime takes %-I; a Windows checkout runs these tests too."""

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def strftime(fmt, *t):
        return time.strftime(fmt.replace("%-I", "%I") if os.name == "nt" else fmt, *t)


class HostTests(unittest.TestCase):
    """app.py's own functions, run with the station stubbed around them."""

    def kit(self, **ns):
        text = _app_text()
        src = "".join(_top_level(text, h) for h in (
            "_PB_OPEN, _PB_MID, _PB_CLOSE = ", "_PB_TOKEN = ", "_PB_NAME = ", "def _pb(", "def _pb_unmark(",
            "_S3_MEMORY_SEGMENTS", "S3_MEMORY_GAP_S = ", "def _s3_segment_went(", "def system3_memory_facts(",
            "def s3_memory_block(",
            "def _show_memory_raw("))
        env: dict[str, Any] = {"re": re, "Any": Any, "time": _Clock(), "_RADIO": {"on": True}, "_AIRLOG_INDEX": {},
                               "_AIRLOG_LOCK": __import__("threading").RLock(), "AIRLOG_AIRED": ("box", "stream", "both"),
                               "AIRLOG_QUIET_KINDS": frozenset({"sfx", "marker"}), "AIRLOG_QUIET_WHO": frozenset({"board"}),
                               "_quota_ring": lambda kind: [], "quota_target": lambda kind: 4,
                               "radio_paused": lambda: False,
                               "story_memory_clause": lambda: "", "crystal_read": lambda: [],
                               "show_notes_clause": lambda notes, own: "", "dj_settings": lambda: {},
                               "_BOX_LAST_OK": [time.time()], "gpu_temp_fact": lambda: ""}
        env.update(ns)
        exec(compile(src, "app.py[s3-memory]", "exec"), env)
        return env

    def test_the_tool_is_applied_to_app_py(self):
        spec = importlib.util.spec_from_file_location("system3_memory_patch", ROOT / "tools" / "system3_memory_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        applied, missing = mod.check(_app_text())
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(_app_text())))

    def test_show_memory_yields_to_the_memory_block(self):
        said = {"words": "WHAT THE BOOTH HAS IN MIND: it is 3:57 pm."}
        env = self.kit(system3_memory_block=lambda: said["words"])
        got = env["_show_memory_raw"](system3=True)
        self.assertEqual(got, env["_pb"]("memory", said["words"]))
        self.assertNotIn("TONIGHT SO FAR", env["_pb_unmark"](got))
        said["words"] = ""
        self.assertEqual(env["_show_memory_raw"](system3=True), "", "rolled and drew nothing: nothing")
        said["words"] = None
        self.assertIn("TONIGHT SO FAR", env["_show_memory_raw"](system3=True), "no roll behind it: the digest")
        env = self.kit()                                   # System 3 not installed at all
        self.assertIn("TONIGHT SO FAR", env["_show_memory_raw"]())
        env["_RADIO"]["on"] = False
        self.assertEqual(env["_show_memory_raw"](), "")

    def test_the_facts_come_from_what_the_station_keeps(self):
        now = time.time()
        radio = {"on": True,
                 "sched_slot": {"id": "s1", "kind": "banter", "label": "Talk radio", "minutes": 10},
                 "sched_pos": {"slot_id": "s1", "started": now - 120, "occurrence": "occ-1"},
                 "chat": [{"who": "manager", "text": "Spin   more records.", "air_at": now - 60, "id": "m1"},
                          {"who": "dj", "text": "later", "air_at": now}],
                 "topics": [{"text": "raccoons took the van", "at": now - 30, "file": "a.md"}]}
        env = self.kit(_RADIO=radio, _quota_ring=lambda kind: [now - 600, now - 200], quota_target=lambda kind: 4,
                       _S3_MEMORY_SEGMENTS={}, _BOX_LAST_OK=[now - 300],
                       gpu_temp_fact=lambda: "THE TEMPERATURE is 71 degrees Celsius")
        got = env["system3_memory_facts"]("banter", {})
        self.assertIn("nothing for 5 minutes", got["speaker_outage"]["text"])
        self.assertIn("71 degrees", got["machine_heat"]["text"])
        self.assertEqual(got["clock"]["segment"]["label"], "Talk radio")
        self.assertAlmostEqual(got["clock"]["segment"]["ends"], now - 120 + 600, delta=1)
        self.assertEqual(got["manager_note"]["text"], "Spin more records.")
        self.assertEqual(got["callers_quota"]["count"], 2)
        self.assertEqual(got["callers_quota"]["quota"], 4)
        lt = time.localtime(got["clock"]["at"])
        top = got["clock"]["at"] - (lt.tm_min * 60 + lt.tm_sec)
        self.assertEqual(got["callers_quota"]["this_hour"], sum(1 for t in (now - 600, now - 200) if t >= top))
        self.assertEqual(got["topic"]["text"], "raccoons took the van")
        self.assertNotIn("last_segment", got, "the schedule has not moved on yet")

    def test_the_schedule_moving_on_files_the_last_segment_once(self):
        now = time.time()
        index = {"a": {"air_at": now - 500, "aired": "stream", "who": "dj", "kind": "call"},
                 "b": {"air_at": now - 400, "aired": "stream", "who": "cohost", "kind": "call"},
                 "c": {"air_at": now - 300, "aired": "withdrawn", "who": "dj", "kind": "call"},
                 "d": {"air_at": now - 300, "aired": "stream", "who": "board", "kind": "sfx"},
                 "e": {"air_at": now - 30, "aired": "stream", "who": "dj", "kind": "call"}}
        radio = {"on": True, "sched_slot": {"id": "news", "kind": "news", "label": "News", "minutes": 10},
                 "sched_pos": {"slot_id": "news", "started": now - 600, "occurrence": "occ-news"}}
        env = self.kit(_RADIO=radio, _AIRLOG_INDEX=index, _S3_MEMORY_SEGMENTS={},
                       _quota_ring=lambda kind: [now - 350])
        self.assertNotIn("last_segment", env["system3_memory_facts"]("banter", {}))
        radio["sched_slot"] = {"id": "talk", "kind": "banter", "label": "Talk radio", "minutes": 10}
        radio["sched_pos"] = {"slot_id": "talk", "started": now - 60, "occurrence": "occ-talk"}
        calls = []
        went = env["_s3_segment_went"]
        env["_s3_segment_went"] = lambda a, b: calls.append((a, b)) or went(a, b)
        got = env["system3_memory_facts"]("banter", {})["last_segment"]
        self.assertEqual((got["label"], got["heard"], got["withdrawn"], got["calls"]), ("News", 2, 1, 1))
        self.assertAlmostEqual(got["ended"], now - 60, delta=1)
        self.assertEqual(got["now"]["label"], "Talk radio")
        env["system3_memory_facts"]("banter", {})
        self.assertEqual(len(calls), 1, "counted once, when the schedule moved on")

    def test_a_segment_no_round_saw_is_not_named_as_the_one_before(self):
        # News was seen; a record block ran after it with no round planned in it;
        # Talk radio is on now - News is not "the segment before this one"
        now = time.time()
        radio = {"on": True, "sched_slot": {"id": "news", "kind": "news", "label": "News", "minutes": 10},
                 "sched_pos": {"slot_id": "news", "started": now - 1800, "occurrence": "occ-news"}}
        env = self.kit(_RADIO=radio, _S3_MEMORY_SEGMENTS={})
        env["system3_memory_facts"]("banter", {})
        radio["sched_slot"] = {"id": "talk", "kind": "banter", "label": "Talk radio", "minutes": 10}
        radio["sched_pos"] = {"slot_id": "talk", "started": now - 60, "occurrence": "occ-talk"}
        got = env["system3_memory_facts"]("banter", {})["last_segment"]
        self.assertTrue(got["unseen"])
        self.assertEqual(got["label"], "")
        self.assertNotIn("heard", got)

    def test_a_pause_moves_the_end_along_and_the_hand_over_still_counts(self):
        now = time.time()
        radio = {"on": True, "sched_slot": {"id": "news", "kind": "news", "label": "News", "minutes": 10},
                 "sched_pos": {"slot_id": "news", "started": now - 1800, "occurrence": "occ-news"}}
        env = self.kit(_RADIO=radio)
        book = env["_S3_MEMORY_SEGMENTS"]                  # app.py's own book, as the kit built it
        env["system3_memory_facts"]("banter", {})
        # a 20-minute pause: the running order rebases the same entry's start
        radio["sched_pos"] = {"slot_id": "news", "started": now - 600, "occurrence": "occ-news"}
        env["system3_memory_facts"]("banter", {})
        self.assertAlmostEqual(book["current"]["started"], now - 1800, delta=1, msg="its start stays the first seen")
        self.assertAlmostEqual(book["current"]["ends"], now, delta=1)
        radio["sched_slot"] = {"id": "talk", "kind": "banter", "label": "Talk radio", "minutes": 10}
        radio["sched_pos"] = {"slot_id": "talk", "started": now, "occurrence": "occ-talk"}
        got = env["system3_memory_facts"]("banter", {})["last_segment"]
        self.assertEqual(got["label"], "News")
        self.assertNotIn("unseen", got)


if __name__ == "__main__":
    unittest.main()
