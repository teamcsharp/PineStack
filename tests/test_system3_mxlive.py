"""[s3-live-event] Station events: the wheels move only while an event is on.

Run one module at a time, niced, in the container tree:
  PYTHONPATH=/tmp/pinelive-fin:/tmp/pinelive-fin/tests nice -n 19 \
      timeout 600 python -m unittest tests.test_system3_mxlive -v
"""
import copy
import hashlib
import json
import time
import unittest

import system3
import system3_runtime
import system3_tables

VOLATILE = ("at", "config_hash")


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, float):
        return round(obj, 9)
    return obj


def _digest(conv):
    body = {"decisions": _clean(conv["decision_events"]),
            "turns": [{k: t.get(k) for k in ("index", "speaker", "step", "phase", "topic_change",
                                             "track_talk", "events", "shock", "mention")}
                      for t in conv["turns"]],
            "draws": conv.get("draws")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _inputs(road="banter", events=None, record_event="", bank=False, turns=8):
    return {
        "road": road, "at": 1790000000.0, "seats": ["A", "B"],
        "names": {"A": "Pine", "B": "Box"}, "roles": {"A": "dj", "B": "cohost"},
        "turns": turns, "target_seconds": 90.0, "words_per_turn": 60.0,
        "subject": {"topic": "the test's fixed subject", "category": "banter",
                    "authority": "obligated", "keywords": [], "angle": ""},
        "availability": {}, "topic_bank": [],
        "speakerbox_rates": {"full": 0.0, "prepend": 0.0, "append": 0.0},
        "bank": bank, "round_rolls": True, "rewrite_rolls": True,
        "event_rolls": True, "dice_hosts": True, "interjections": [],
        "record": {"id": "ab12cd34ef56ab12", "title": "Night Drive", "artist": "The Pine Box Band"},
        "station_name": "Pine Box FM", "live": not bank,
        "events": dict(events or {}), "record_event": record_event,
    }


def _config(with_events=True):
    config = system3.default_config()
    if with_events:
        config["tables"] = config["tables"] + system3_tables.default_event_tables()
        for name, rule in system3_tables.default_event_blocks().items():
            config["blocks"][name] = rule
        config["events"] = system3_tables.default_events()
    return config


SETTINGS = system3.normalise_settings({"mode": "shadow"})
LIVE = {"mxlive": {"stage": "live", "name": "MX Live", "source": "pinelive"}}


class EventView(unittest.TestCase):
    def test_untagged_config_is_the_same_object(self):
        config = system3.default_config()
        self.assertIs(system3.event_view(config, {"events": {}}), config)

    def test_off_strips_every_tagged_table(self):
        config = _config()
        view = system3.event_view(config, {"events": {}})
        ids = {t["id"] for t in view["tables"]}
        for tid in ("MXLIVE1", "MXLIVECALL1", "MXLIVECTS1", "MXLIVETRACK1", "MXLIVEID1", "MXLIVEANGLE1"):
            self.assertNotIn(tid, ids)
        self.assertEqual(len(view["tables"]), len(system3.default_config()["tables"]))

    def test_stage_filters_categories(self):
        config = _config()
        view = system3.event_view(config, {"events": {"mxlive": {"stage": "upcoming"}}})
        by_id = {t["id"]: t for t in view["tables"]}
        self.assertIn("MXLIVE1", by_id)
        self.assertEqual([c["id"] for c in by_id["MXLIVE1"]["categories"]], ["trail"])
        # live-only tables have no upcoming rows and are out altogether
        self.assertNotIn("MXLIVETRACK1", by_id)
        self.assertNotIn("MXLIVEID1", by_id)
        live_view = system3.event_view(config, {"events": LIVE})
        live_ids = {t["id"] for t in live_view["tables"]}
        self.assertIn("MXLIVETRACK1", live_ids)
        self.assertIn("MXLIVEID1", live_ids)

    def test_banked_round_never_takes_an_event_row(self):
        config = _config()
        view = system3.event_view(config, {"events": LIVE, "bank": True})
        ids = {t["id"] for t in view["tables"]}
        self.assertNotIn("MXLIVE1", ids)
        self.assertNotIn("MXLIVECTS1", ids)


class DrawsUnmoved(unittest.TestCase):
    def test_same_draws_with_the_tables_in_and_no_event_on(self):
        """The in-test sweep: the six tables in the config, the event off -
        every seed's every decision identical to the plain config's."""
        plain = system3.default_config()
        loaded = _config()
        for i in range(12):
            seed = "unit-sweep-%03d" % i
            a = system3.plan_scene(_inputs(), copy.deepcopy(plain), SETTINGS,
                                   seed=seed, conversation_id="a%03d" % i)
            b = system3.plan_scene(_inputs(), copy.deepcopy(loaded), SETTINGS,
                                   seed=seed, conversation_id="a%03d" % i)
            self.assertEqual(_digest(a), _digest(b), "seed %s moved" % seed)

    def test_config_hash_is_the_stored_configs_own(self):
        loaded = _config()
        conv = system3.plan_scene(_inputs(events=LIVE), copy.deepcopy(loaded), SETTINGS,
                                  seed="hash-check", conversation_id="hash0")
        self.assertEqual(conv["config_hash"], system3.config_hash(loaded))


class EventOn(unittest.TestCase):
    def test_event_rows_land_and_are_stamped(self):
        loaded = _config()
        landed = None
        for i in range(60):
            conv = system3.plan_scene(_inputs(events=LIVE), copy.deepcopy(loaded), SETTINGS,
                                      seed="on-%03d" % i, conversation_id="on%03d" % i)
            plans = [p for p in conv.get("event_plans") or [] if p.get("table") == "MXLIVE1"]
            if plans:
                landed = (conv, plans[0])
                break
        self.assertIsNotNone(landed, "no MXLIVE1 row landed in 60 seeds")
        conv, plan = landed
        self.assertEqual(plan.get("event"), "mxlive")
        turn = conv["turns"][plan["turn_index"]]
        row = [e for e in turn.get("events") or [] if e.get("table") == "MXLIVE1"][0]
        self.assertEqual(row.get("event"), "mxlive")            # the line's stamp
        claims = system3.event_claims(conv)
        self.assertTrue(any(c.startswith("MXLIVE1:") for c in claims), claims)
        # the Rolodex's word: the decision event's meta names the event
        ev = [e for e in conv["decision_events"] if e["event_id"] == plan["event_id"]][0]
        self.assertEqual((ev.get("meta") or {}).get("event"), "mxlive")

    def test_cts_rows_join_only_while_on(self):
        loaded = _config()

        def cts_tables(events):
            view = system3.event_view(loaded, {"events": events})
            return {t["id"] for t in system3._tables_for(view, "CTS")}

        self.assertNotIn("MXLIVECTS1", cts_tables({}))
        self.assertIn("MXLIVECTS1", cts_tables(LIVE))

    def test_track_talk_speaks_about_the_live_set(self):
        loaded = _config()
        settings = system3.normalise_settings({"mode": "shadow",
                                               "controls": {"track_talk": 1.0}})
        got = None
        for i in range(30):
            conv = system3.plan_scene(_inputs(events=LIVE, record_event="mxlive"),
                                      copy.deepcopy(loaded), settings,
                                      seed="tt-%03d" % i, conversation_id="tt%03d" % i)
            plan = conv.get("track_talk_plan")
            if plan and (plan.get("record") or {}).get("direction"):
                got = (conv, plan)
                break
        self.assertIsNotNone(got, "no live track-talk direction in 30 seeds")
        conv, plan = got
        rec = plan["record"]
        self.assertEqual(rec.get("event"), "mxlive")
        self.assertEqual(rec.get("table"), "MXLIVETRACK1")
        self.assertTrue(rec.get("direction"))
        sheet = system3.render_sheet(conv)
        self.assertIn("LIVE", sheet)
        self.assertIn(rec["direction"][:40], sheet)
        # and the claim reaches the block
        self.assertTrue(any(c.startswith("MXLIVETRACK1:") for c in system3.event_claims(conv)))

    def test_claimed_block_kept_only_on_a_claim(self):
        loaded = _config()
        clean = system3.plan_scene(_inputs(), copy.deepcopy(loaded), SETTINGS,
                                   seed="claim-off", conversation_id="cl0")
        out = system3.decide_blocks(["event_facts"], loaded, "claim-off", conv=clean)
        self.assertFalse(out[0]["keep"])
        self.assertEqual(out[0]["kind"], "claimed")
        claimed = dict(clean)
        claimed = copy.deepcopy(clean)
        claimed["event_plans"] = [{"event": "mxlive", "table": "MXLIVE1", "id": "shout"}]
        out2 = system3.decide_blocks(["event_facts"], loaded, "claim-on", conv=claimed)
        self.assertTrue(out2[0]["keep"])
        self.assertIn("MXLIVE1:shout", out2[0]["why"])


class Validation(unittest.TestCase):
    def test_event_families_validate(self):
        for t in system3_tables.default_event_tables():
            got = system3.validate_table(t)
            self.assertEqual(got["id"], t["id"])
        bad = dict(system3_tables.MXLIVETRACK1, family="NOSUCH")
        with self.assertRaises(ValueError):
            system3.validate_table(bad)

    def test_event_table_roads_survive_validation(self):
        got = system3.validate_table(system3_tables.MXLIVEID1)
        self.assertEqual(got["roads"], ["station_id"])
        self.assertEqual(got.get("event"), "mxlive")


class RuntimeSide(unittest.TestCase):
    def _rt(self, config):
        rt = system3_runtime.System3Runtime.__new__(system3_runtime.System3Runtime)
        rt.config = config
        rt.ready = True
        import threading
        rt.lock = threading.Lock()
        rt.metrics = {"failures": 0, "fallbacks": 0}
        rt.log = lambda *a, **k: None
        return rt

    def test_station_events_follow_the_probe(self):
        rt = self._rt(_config())
        rt.event_probe = lambda: {"enabled": True, "armed": True, "phase": "live"}
        got = rt.station_events()
        self.assertEqual(got["mxlive"]["stage"], "live")
        rt.event_probe = lambda: {"enabled": True, "armed": True, "phase": "arming"}
        self.assertEqual(rt.station_events()["mxlive"]["stage"], "upcoming")
        # off, but seen live moments ago: the after window
        rt.event_probe = lambda: {"enabled": True, "armed": False, "phase": "idle"}
        self.assertEqual(rt.station_events()["mxlive"]["stage"], "after")
        rt._event_mem["mxlive"]["seen_at"] = time.time() - 9999.0
        self.assertEqual(rt.station_events(), {})

    def test_pool_and_line_rows_only_while_on(self):
        rt = self._rt(_config())
        rt.event_probe = lambda: {}
        self.assertEqual(rt._pool_event_rows("banter.stock_angle"), [])
        self.assertEqual(rt._event_line_candidates("station_id", {"station_name": "Pine Box FM"}), [])
        rt.event_probe = lambda: {"enabled": True, "armed": True, "phase": "live"}
        angles = rt._pool_event_rows("banter.stock_angle")
        self.assertTrue(angles and any("MX" in a for a in angles))
        self.assertEqual(rt._pool_event_rows("some.other.wheel"), [])
        ids = rt._event_line_candidates("station_id", {"station_name": "Pine Box FM"})
        self.assertTrue(ids)
        self.assertTrue(all("Pine Box FM" in c["text"] or "{station}" not in c["text"] for c in ids))
        self.assertTrue(all(c["id"].startswith("MXLIVEID1:") for c in ids))
        self.assertEqual(rt._event_line_candidates("reply", {}), [])

    def test_record_event_of(self):
        rt = self._rt(_config())
        rt.event_probe = lambda: {"enabled": True, "armed": True, "phase": "live"}
        self.assertEqual(rt.record_event_of({"record": {"title": "MX Live", "pinelive": True}}), "mxlive")
        self.assertEqual(rt.record_event_of({"record": {"title": "Night Drive"}}), "")
        rt.event_probe = lambda: {}
        self.assertEqual(rt.record_event_of({"record": {"title": "MX Live", "pinelive": True}}), "")

    def test_add_missing_station_events_once(self):
        class Store:
            def __init__(self):
                self.saved = []

            def save_config(self, config, note=""):
                self.saved.append(note)
                return "h"

        rt = self._rt({"tables": [], "blocks": {}})
        rt.store = Store()
        rt.fail = lambda *a, **k: None
        added = rt.add_missing_station_events()
        self.assertIn("event mxlive", added)
        self.assertIn("block event_facts", added)
        self.assertIn("mxlive", rt.config["events"])
        self.assertEqual(rt.config["blocks"]["event_facts"]["kind"], "claimed")
        self.assertEqual(rt.add_missing_station_events(), [])      # remembered
        # a deleted register entry stays deleted
        del rt.config["events"]["mxlive"]
        self.assertEqual(rt.add_missing_station_events(), [])


if __name__ == "__main__":
    unittest.main()
