"""[wave-g] The Hour Director (system3_hour.py), proven on a fake sheet, fake dice, a fake cupboard and fake doors.

Covers: the legs read off the sheet, decide (the sheet, the silent draw weighted by quota pressure, the jam
roll), book (the cupboard's fit tests and the weighted draw), dispatch (the segment door, the record pin, the
dialogue shelf, the refusal reason), fallback_due, the round ledger on disk (48 hours), the routes (TestClient
when it is installed), System 2 idle under engine "system3" (the real System2Runtime), and the HOUR tables.

Nothing here touches the station: DATA_DIR is a temporary directory and every door is a fake.
"""
import asyncio
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import system3
import system3_hour
import system3_tables

ROOT = Path(__file__).resolve().parent.parent
HOUR = "2026-10-06T14"
NOW = time.mktime((2026, 10, 6, 14, 20, 0, 0, 0, -1))
PREP = {"track_talk": "track_talk", "ad": "ad", "manager": "manager", "caller": "caller",
        "banter_caller": "caller", "bombshell": "ad", "gallery": "gallery", "banter": "banter",
        "book_time": "banter", "sfx_supercut": "sfx_supercut", "news": "news"}


class FakeFlow:
    def __init__(self):
        self.notes = []

    def note(self, gate, why="", passed=True, road="", text="", ref="", **_):
        self.notes.append({"gate": gate, "why": why, "passed": passed, "road": road, "text": text, "ref": ref})
        return {}


class FakeRuntime:
    """Stands in for System 2's runtime: its config, and its own configure door."""

    def __init__(self, host, config):
        self.host = host
        self.config = dict(config)

    def configure(self, payload):
        self.config.update(payload)
        (self.host.DATA_DIR / "system2-config.json").write_text(json.dumps(self.config, indent=2), "utf-8")
        return dict(self.config)


class FakeHost:
    def __init__(self, tmp, engine="system3", fallback=True):
        self.DATA_DIR = Path(tmp)
        self.sys2 = FakeRuntime(self, {"engine": engine, "fallback": fallback, "horizon_hours": 6})
        self._system2 = lambda: self.sys2
        self._RADIO = {"now": {"id": "track-1", "title": "A record"}, "sched_pos": {}}
        self._SPEAKING = [0]
        self._busy = False
        self._floor_busy = lambda: self._busy
        self.SCHED_PREP_KIND = dict(PREP)
        self.rows = []              # the hour's sheet rows
        self.take = {}              # what schedule_take() returns
        self.jam = ""
        self.occurrence = "occ-1"
        self.extra = {}             # kind -> what schedule_extra_round returns
        self.extra_calls = []
        self.pinned = []
        self.shelves = {}           # road -> rows
        self.shelf_ok = True
        self.shelf_calls = []
        self._READY_SHELF_REFUSED = [""]
        self.draw_log = []
        self.chance_answers = []
        self.logs = []
        self.FLOW_LEDGER = FakeFlow()
        self.engine_answer = None

    # the sheet
    def _sched_hour_key(self, at=None):
        return HOUR if at is None else time.strftime("%Y-%m-%dT%H", time.localtime(at))

    def _sched_hour_epoch(self, key):
        return time.mktime(time.strptime(str(key), "%Y-%m-%dT%H"))

    def schedule_read(self):
        return {"presets": {"canon": []}, "hours": {}}

    def schedule_hour_slots(self, store, key, when=None):
        return ("canon", [dict(r) for r in self.rows], False)

    def schedule_prompt_for(self, store, slot):
        return str(slot.get("act") or "")

    def schedule_take(self):
        return dict(self.take) if self.take else {}

    def schedule_jammed(self):
        return self.jam

    def _schedule_dispatch_occurrence(self):
        return self.occurrence

    def _schedule_pin_record(self):
        self.pinned.append(True)
        return None

    async def schedule_extra_round(self, kind, track, dj, occurrence=None):
        self.extra_calls.append((kind, occurrence))
        return self.extra.get(kind)

    # the cupboard
    async def _ready_shelf_air(self, kind, track=None, rescue=False, pick=None, force=False,
                               on_handoff=None, named=False):
        self.shelf_calls.append((kind, pick))
        if self.shelf_ok:
            return ["a finished line"]
        self._READY_SHELF_REFUSED[0] = "it does not fit the entry on air and may not go out of turn"
        return []

    def road_source(self, kind):
        return list(self.shelves.get(kind, []))

    def dialogue_row_ready(self, kind, row):
        return bool(row.get("ready", True))

    def row_unaired(self, row):
        return not row.get("aired")

    def bank_reair_refusal(self, road, row, cid=""):
        return "the re-air gate retired it" if row.get("retired") else ""

    def dialogue_entry(self, row):
        return row

    # the dice
    def s3_weighted(self, key, labels, weights, label="", media=None):
        self.draw_log.append((key, list(labels), [round(float(w), 4) for w in weights]))
        return 0

    def s3_chance(self, key, odds, label="", dial=""):
        self.draw_log.append((key, round(float(odds), 4)))
        return self.chance_answers.pop(0) if self.chance_answers else False

    # the rest
    def pipeline_log(self, stage, text, extra=""):
        self.logs.append(text)

    def dj_settings(self):
        return {}

    def require_auth(self, authorization=None):
        return None

    def require_read_auth(self, authorization=None):
        return None


def slot(id_, kind, minutes=10, label="", act="", **extra):
    return dict({"id": id_, "kind": kind, "label": label or kind.title(), "minutes": minutes,
                 "enabled": True, "act": act}, **extra)


def row(id_, **extra):
    return dict({"id": id_, "at": NOW - 7200, "aired": False, "ready": True}, **extra)


def director(host, clock=None):
    return system3_hour.HourDirector(host, clock=clock or (lambda: NOW))


class TempCase(unittest.TestCase):
    engine = "system3"
    fallback = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hour-director-test-")
        self.host = FakeHost(self.tmp, engine=self.engine, fallback=self.fallback)
        self.d = director(self.host)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class LegsTest(TempCase):
    def test_the_hour_is_read_off_the_sheet_in_order(self):
        self.host.rows = [slot("b1", "book_time", 30, "Book", act="read the book"),
                          slot("n1", "news", 15, "News"),
                          slot("x1", "caller", 5, "Off", enabled=False),
                          slot("c1", "caller", 5, "Caller")]
        plan = self.d.legs(HOUR)
        self.assertEqual(plan["id"], "hour@" + HOUR)
        self.assertEqual([leg["id"] for leg in plan["legs"]], ["b1", "n1", "c1"])
        book, news, caller = plan["legs"]
        self.assertEqual(book["road"], "banter")                 # a window rides the banter road
        self.assertEqual(book["dynamic_kind"], "book_time")
        self.assertEqual(news["road"], "news")
        self.assertEqual(news["dynamic_kind"], "")
        self.assertEqual(book["act"], "read the book")
        start = self.host._sched_hour_epoch(HOUR)
        self.assertEqual(book["start"], start)
        self.assertEqual(book["deadline"], start + 30 * 60)
        self.assertEqual(news["start"], start + 30 * 60)
        self.assertEqual(caller["deadline"], start + 50 * 60)
        self.assertEqual([leg["place"] for leg in plan["legs"]], ["open", "middle", "close"])

    def test_engine_is_read_from_system_2s_config(self):
        self.assertEqual(self.d.engine(), "system3")
        self.assertTrue(self.d.enabled())
        self.assertTrue(self.d.fallback_on())


class DecideTest(TempCase):
    def test_the_sheet_names_the_entry_and_no_die_is_rolled(self):
        self.host.take = slot("n1", "news", 15)
        due = self.d.decide()
        self.assertEqual((due["kind"], due["policy"], due["named"]), ("news", "sheet", "news"))
        self.assertEqual(self.host.draw_log, [])

    def test_a_silent_sheet_draws_hour1_weighted_by_quota_pressure(self):
        self.host.take = {}
        self.host.rows = [slot("b1", "banter", 10), slot("b2", "banter", 10), slot("n1", "news", 15)]
        due = self.d.decide()
        self.assertEqual(due["policy"], "silent")
        key, labels, weights = self.host.draw_log[0]
        self.assertEqual(key, "hour.silent")
        self.assertEqual(labels, ["banter", "caller", "news", "gallery", "manager", "ad", "deep", "bombshell", "recap"])
        table = dict(zip(labels, weights))
        # banter: HOUR1 4.0, two of its legs unaired, gain 0.5 -> x1.5 ; news: 1.5 with gain 1.5, one leg -> x2.5
        self.assertEqual(table["banter"], 6.0)
        self.assertEqual(table["news"], 3.75)
        self.assertEqual(table["caller"], 2.0)                   # not planned on this sheet: no pressure
        self.assertIn(due["kind"], labels)
        kinds = [d["picked"] for d in self.d._draws[HOUR]["silent"]]
        self.assertEqual(kinds, [due["kind"]])
        self.assertEqual(len(self.d._draws[HOUR]["quota"]), 1)

    def test_aired_legs_take_the_pressure_off(self):
        self.host.rows = [slot("b1", "banter", 10), slot("b2", "banter", 10)]
        self.d._rows[HOUR] = [{"kind": "banter", "served": True, "rounds": 1, "slot_id": "b1"}]
        self.host.take = {}
        self.d.decide()
        table = dict(zip(*self.host.draw_log[0][1:3]))
        self.assertEqual(table["banter"], 5.0)                   # behind 1 of 2: x1.25 of 4.0

    def test_a_jammed_entry_is_displaced_only_when_the_jam_roll_hits(self):
        self.host.take = slot("c1", "caller", 5)
        self.host.jam = "the sheet is jammed on Caller - 2.1x its 300s"
        self.host.chance_answers = [True]
        due = self.d.decide()
        self.assertEqual(due["policy"], "jam")
        self.assertEqual(due["named"], "caller")
        self.assertEqual(due["kind"], "banter")                   # the first HOUR1 kind, the fake's pick
        self.assertIn(("hour.jam", 0.5), self.host.draw_log)

    def test_a_jammed_entry_is_kept_when_the_jam_roll_misses(self):
        self.host.take = slot("c1", "caller", 5)
        self.host.jam = "jammed"
        self.host.chance_answers = [False]
        due = self.d.decide()
        self.assertEqual((due["kind"], due["policy"]), ("caller", "sheet"))


class BookTest(TempCase):
    def test_only_a_fitting_finished_round_is_drawn_and_the_refusals_are_counted(self):
        good = row("a", at=NOW - 7200)
        self.host.shelves = {"banter": [good, row("b", ready=False), row("c", dynamic_kind="book_time"),
                                        row("d", aired=True, retired=True)]}
        picked = self.d.book("banter", {"deadline": NOW + 60, "label": "Banter"})
        self.assertIs(picked, good)
        key, labels, weights = self.host.draw_log[-1]
        self.assertEqual(key, "hour.book")
        self.assertEqual(len(labels), 1)
        self.assertEqual(weights, [6.0])                         # 1 + 2 hours waiting = 3; a deadline inside 15 minutes doubles it
        self.assertEqual(self.d._book_why, "")

    def test_a_window_part_books_only_into_its_own_window(self):
        part = row("w1", dynamic_kind="book_time")
        self.host.shelves = {"banter": [part]}
        self.assertIsNone(self.d.book("banter", {"label": "Banter"}))
        self.assertIn("a window's part belongs to its own window", self.d._book_why)
        self.assertIs(self.d.book("book_time", {"label": "Book"}), part)

    def test_an_empty_shelf_says_why(self):
        self.host.shelves = {}
        self.assertIsNone(self.d.book("banter", {"label": "Banter"}))
        self.assertIn("no finished banter round fits this leg", self.d._book_why)

    def test_the_lifecycle_refuses_what_does_not_fit_the_leg(self):
        class Life:
            enabled = True

            def compatible(self, kind, r):
                return r.get("fits", False)
        self.host._pantry_lifecycle = lambda: Life()
        self.host.shelves = {"banter": [row("no"), row("yes", fits=True)]}
        self.assertEqual(self.d.book("banter", {"label": "Banter"})["id"], "yes")


class DispatchTest(TempCase):
    def run_dispatch(self):
        return asyncio.run(self.d.dispatch(self.host._RADIO["now"], {}))

    def test_a_dialogue_leg_airs_the_booked_round_and_is_on_the_ledger(self):
        self.host.occurrence = "occ-7"
        self.host.take = slot("n1", "banter", 10, "Banter")
        picked = row("a")
        self.host.shelves = {"banter": [picked]}
        self.assertTrue(self.run_dispatch())
        self.assertEqual(self.host.shelf_calls[-1][0], "banter")
        self.assertIs(self.host.shelf_calls[-1][1], picked)
        hour = self.d._rows[HOUR]
        self.assertEqual(len(hour), 1)
        self.assertTrue(hour[0]["served"])
        self.assertEqual(hour[0]["booked"]["id"], "a")
        self.assertEqual(hour[0]["occurrence"], "occ-7")
        self.assertEqual(self.host.FLOW_LEDGER.notes[-1]["gate"], "hour.dispatch")
        self.assertTrue(self.host.FLOW_LEDGER.notes[-1]["passed"])

    def test_a_dynamic_window_goes_through_the_segment_door(self):
        self.host.take = slot("w1", "book_time", 30, "Book")
        self.host.extra = {"book_time": True}
        self.assertTrue(self.run_dispatch())
        self.assertEqual(self.host.extra_calls, [("book_time", "occ-1")])
        self.assertEqual(self.host.shelf_calls, [])

    def test_a_record_is_pinned_then_the_needle_door_is_asked(self):
        self.host.take = slot("r1", "record", 4, "Spin")
        self.host.extra = {"record": True}
        self.assertTrue(self.run_dispatch())
        self.assertEqual(self.host.pinned, [True])
        self.assertEqual(self.host.extra_calls[0][0], "record")

    def test_a_refused_round_leaves_its_reason_and_the_fallback_armed(self):
        self.host.take = slot("n1", "banter", 10, "Banter")
        self.host.shelves = {"banter": [row("a")]}
        self.host.shelf_ok = False
        self.assertFalse(self.run_dispatch())
        why = self.d._rows[HOUR][0]["why"]
        self.assertIn("the cupboard refused the booked round", why)
        self.assertIn("may not go out of turn", why)
        self.assertTrue(self.d.fallback_due())

    def test_a_door_that_says_not_mine_leaves_the_chain_to_its_fallback(self):
        self.host.take = slot("t1", "track_talk", 5)
        self.host.extra = {}
        self.assertFalse(self.run_dispatch())
        self.assertIn("not one of its own", self.d._rows[HOUR][0]["why"])

    def test_the_fallback_waits_for_a_silent_occurrence_and_not_for_a_served_one(self):
        self.host.take = slot("n1", "banter", 10, "Banter")
        self.host.shelves = {"banter": [row("a")]}
        self.host.occurrence = "occ-9"
        self.host.shelf_ok = True
        self.assertTrue(self.run_dispatch())
        self.assertFalse(self.d.fallback_due())
        self.host.occurrence = "occ-10"
        self.host.shelves = {"banter": []}
        self.assertFalse(self.run_dispatch())
        self.assertTrue(self.d.fallback_due())

    def test_nothing_falls_back_while_the_floor_is_busy(self):
        self.host.take = {}
        self.host._SPEAKING = [1]
        self.assertFalse(self.d.fallback_due())

    def test_a_silent_draw_airs_through_its_own_door(self):
        self.host.take = {}
        self.host.shelves = {"banter": [row("a")]}
        self.assertTrue(self.run_dispatch())
        self.assertTrue(self.d._rows[HOUR][0]["occurrence"].startswith("silent@"))
        self.assertEqual(self.d._rows[HOUR][0]["policy"], "silent")


class FallbackOffTest(TempCase):
    fallback = False

    def test_fallback_off_is_never_due(self):
        self.host.take = {}
        self.assertFalse(self.d.fallback_due())
        self.assertFalse(self.run_dispatch_now())

    def run_dispatch_now(self):
        return asyncio.run(self.d.dispatch(None, {}))


class Engine2Test(TempCase):
    engine = "system2"

    def test_under_system_2_the_director_is_not_the_engine(self):
        self.assertFalse(self.d.enabled())
        self.assertFalse(self.d.fallback_due())
        self.assertFalse(asyncio.run(self.d.dispatch(None, {})))
        self.assertEqual(self.host.draw_log, [])


class LedgerTest(TempCase):
    def test_the_ledger_is_written_and_read_back_by_a_fresh_director(self):
        self.host.take = {}
        self.host.shelves = {"banter": [row("a")]}
        asyncio.run(self.d.dispatch(None, {}))
        path = self.d.ledger_path()
        self.assertEqual(path, Path(self.tmp) / "system3_hour_ledger.json")
        raw = json.loads(path.read_text("utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertEqual(len(raw["hours"][HOUR]["rows"]), 1)
        self.assertFalse((Path(self.tmp) / "system3_hour_ledger.json.tmp").exists())
        fresh = director(FakeHost(self.tmp))
        view = fresh.hour_view(HOUR)
        self.assertEqual(view["hour"], HOUR)
        self.assertEqual(sum(len(v) for v in view["draws"].values()), len(raw["hours"][HOUR]["draws"]["silent"]) + len(raw["hours"][HOUR]["draws"]["quota"]))

    def test_a_dispatch_never_overwrites_the_hours_already_on_disk(self):
        old = "2026-10-06T09"
        path = Path(self.tmp) / "system3_hour_ledger.json"
        path.write_text(json.dumps({"version": 1, "hours": {old: {"rows": [{"id": "keep", "served": True}],
                                                                   "draws": {}}}}), "utf-8")
        self.host.take = {}
        self.host.shelves = {"banter": [row("a")]}
        asyncio.run(self.d.dispatch(None, {}))
        self.assertIn(old, json.loads(path.read_text("utf-8"))["hours"])

    def test_hours_older_than_48_hours_are_dropped(self):
        path = Path(self.tmp) / "system3_hour_ledger.json"
        path.write_text(json.dumps({"version": 1, "hours": {
            "2026-09-01T10": {"rows": [{"served": True}], "draws": {}}}}), "utf-8")
        self.host.take = {}
        self.host.shelves = {"banter": [row("a")]}
        asyncio.run(self.d.dispatch(None, {}))
        hours = json.loads(path.read_text("utf-8"))["hours"]
        self.assertNotIn("2026-09-01T10", hours)
        self.assertIn(HOUR, hours)

    def test_the_pure_helpers(self):
        self.assertEqual(system3_hour.quota_multipliers({"news": 2}, {"news": 1}, {"news": 1.5, "ad": 2}),
                         {"news": 1.75, "ad": 1.0})
        self.assertEqual(system3_hour.book_weight(NOW - 7200, NOW, None), 3.0)
        self.assertEqual(system3_hour.book_weight(NOW - 7200, NOW, NOW + 60), 6.0)
        self.assertEqual(system3_hour.book_weight(0, NOW, None), 1.0)
        pruned = system3_hour.ledger_prune({"a": 1, "b": 2}, 100, keep_seconds=10,
                                           epoch_of=lambda k: {"a": 1.0, "b": 95.0}[k])
        self.assertEqual(sorted(pruned), ["b"])


class EngineSetTest(TempCase):
    def test_the_engine_is_set_through_system_2s_own_door(self):
        view = self.d.set_engine({"fallback": False})
        self.assertFalse(view["fallback"])
        self.assertEqual(view["engine"], "system3")
        with self.assertRaises(ValueError):
            self.d.set_engine({"engine": "bogus"})
        with self.assertRaises(ValueError):
            self.d.set_engine({"fallback": "yes"})
        with self.assertRaises(ValueError):
            self.d.set_engine({"hour": 3})
        with self.assertRaises(ValueError):
            self.d.set_engine({})


class SystemTwoIdleTest(unittest.TestCase):
    """The real System 2 runtime, on a temporary store, under engine system3."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="s2-idle-test-")
        (Path(self.tmp) / "system2-config.json").write_text(json.dumps({"engine": "system3", "fallback": True}), "utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_system_2_stands_down(self):
        import system2_runtime

        host = FakeHost(self.tmp)
        host.OLLAMA_LANES = 1
        host.pipeline_log = lambda stage, text, extra="": None
        runtime = system2_runtime.System2Runtime(host)
        self.assertEqual(runtime.config["engine"], "system3")
        self.assertFalse(runtime.enabled)
        self.assertEqual(runtime.current_clock(), {})
        self.assertFalse(runtime.fallback_due())
        self.assertFalse(asyncio.run(runtime.dispatch()))
        self.assertFalse(runtime.owns_preparation)

    def test_system_2_settings_accept_system3(self):
        import system2_runtime

        host = FakeHost(self.tmp)
        host.OLLAMA_LANES = 1
        host.pipeline_log = lambda stage, text, extra="": None
        runtime = system2_runtime.System2Runtime(host)
        self.assertEqual(runtime.configure({"engine": "system3"})["engine"], "system3")
        with self.assertRaises(ValueError):
            runtime.configure({"engine": "system4"})


class RoutesTest(TempCase):
    def setUp(self):
        super().setUp()
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:  # noqa: BLE001 - no TestClient here: the routes are proven on the station only
            self.skipTest("TestClient is not available: %s" % exc)
        self.TestClient = TestClient
        self.app = FastAPI()
        namespace = {name: getattr(self.host, name) for name in dir(FakeHost) if not name.startswith("__")}
        namespace.update({k: v for k, v in vars(self.host).items()})
        namespace["DATA_DIR"] = self.host.DATA_DIR
        self.namespace = namespace
        self.director = system3_hour.install(self.app, namespace)

    def test_the_routes_answer_while_system_3_is_the_engine(self):
        client = self.TestClient(self.app)
        got = client.get("/api/system3/engine").json()
        self.assertEqual(got["engine"], "system3")
        self.assertTrue(got["fallback"])
        self.host.rows = [slot("n1", "news", 15, "News")]
        self.host.take = {}
        hour = client.get("/api/system3/hour", params={"hour": HOUR})
        self.assertEqual(hour.status_code, 200)
        body = hour.json()
        self.assertEqual(body["engine"], "system3")
        self.assertEqual(body["legs"][0]["id"], "n1")
        self.assertEqual(body["legs"][0]["road"], "news")
        self.assertIn("ledger", body["legs"][0])
        self.assertEqual(set(body["draws"]), {"silent", "quota", "jam"})
        posted = client.post("/api/system3/engine", json={"fallback": False})
        self.assertEqual(posted.status_code, 200)
        self.assertFalse(posted.json()["fallback"])
        self.assertEqual(client.post("/api/system3/engine", json={"engine": "nope"}).status_code, 400)
        self.assertEqual(client.post("/api/system3/engine", data="x").status_code, 400)

    def test_the_hour_route_is_404_while_system_2_is_the_engine(self):
        self.host.sys2.config["engine"] = "system2"
        client = self.TestClient(self.app)
        response = client.get("/api/system3/hour", params={"hour": HOUR})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["engine"], "system2")

    def test_the_install_publishes_the_director_on_the_namespace(self):
        self.assertIs(self.namespace["_system3_hour"](), self.director)


class TablesTest(unittest.TestCase):
    def test_the_hour_tables_ship_in_the_defaults_and_validate(self):
        tables = {t["id"]: t for t in system3_tables.default_tables() if t.get("family") == "HOUR"}
        self.assertEqual(sorted(tables), ["HOUR1", "HOUR2", "HOUR3"])
        for tid in tables:
            self.assertEqual(system3_tables.validate_hour(tables[tid])["id"], tid)
        kinds = [i["id"] for c in tables["HOUR1"]["categories"] for i in c["items"]]
        self.assertEqual(kinds, list(system3_tables.HOUR_KINDS))

    def test_system3_validates_a_hour_table_and_clamps_its_odds(self):
        self.assertIn("HOUR", system3.FAMILIES)
        table = json.loads(json.dumps(system3_tables.HOUR3))
        table["categories"][0]["items"][0]["odds"] = 2.5
        cleaned = system3.validate_table(table)
        self.assertEqual(cleaned["categories"][0]["items"][0]["odds"], 1.0)
        self.assertEqual(cleaned["family"], "HOUR")

    def test_a_bad_hour_table_is_refused(self):
        bad = json.loads(json.dumps(system3_tables.HOUR1))
        bad["categories"][0]["items"].append({"id": "weather", "text": "rain"})
        with self.assertRaises(ValueError):
            system3_tables.validate_hour(bad)
        empty = json.loads(json.dumps(system3_tables.HOUR2))
        empty["categories"][0]["items"] = []
        with self.assertRaises(ValueError):
            system3.validate_table(empty)
        with self.assertRaises(ValueError):
            system3_tables.validate_hour({"id": "HOUR9", "family": "HOUR", "categories": [{"id": "x", "items": [{"id": "banter"}]}]})

    def test_the_default_config_hash_is_the_one_the_tests_pin(self):
        self.assertEqual(system3.config_hash(system3.default_config()), "a22a5ee968719641")

    def test_the_words_and_the_table_group_are_in_the_desk(self):
        js = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        self.assertIn("HOUR: ['The hour (HOUR1-3)'", js)
        self.assertIn("TABLE_FAMILIES.push('HOUR')", js)
        app = (ROOT / "app.py").read_text(encoding="utf-8", errors="replace")
        self.assertIn("system3_hour.install(app, globals())", app)
        self.assertIn('return system3_tables.validate_hour(table)', (ROOT / "system3.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
