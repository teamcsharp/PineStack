"""[s3-visuals] The rotating visuals roll through System 3 ("roulette where
they rotate", the total-coverage audit, 2026-09-28).

GAP 6: the hourly H3 door's picks - which source road, which unused clip or
picture, where the window's markers land - are drawn on System 3's dice
(h3.hourly_source / h3.hourly_fresh / h3.hourly_marker / h3.hourly_host),
recorded onto the hour's entry in the presets history (`rolls`), carried by
h3_prompts_words onto every render row, and one durable line per hourly
render lands in data/h3_hourly_airings.jsonl. The render itself is STUBBED
everywhere here - nothing in this file may queue or start an H3 render
(#1285) - and the clock runs on a fixture clock.

GAP 7: the slideshow playlist deals its shuffle server-side on the
records.rotation_deal pattern - a seedless ask rolls slideshow.deal ONCE,
the dealt seed rides the answer and reproduces the order exactly; each
served row carries the transition it enters with, dealt from the tabled
pool slideshow.transition.

Everything is exec'd out of app.py's own text with stubs - no station, no
GPU, no render, no network."""
import __future__
import asyncio
import json
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import comfy_workshop  # noqa: E402 - the prompt compiler, pure

APP_TEXT = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
FLAGS = __future__.annotations.compiler_flag


def function_source(name):
    m = re.search(r"^(?:async def|def|class) %s\b" % re.escape(name), APP_TEXT, re.M)
    assert m, name
    for nxt in re.finditer(r"\n(?=[^\s#)\]}])", APP_TEXT[m.end():]):
        src = APP_TEXT[m.start():m.end() + nxt.start() + 1]
        try:
            compile(src, "app.py", "exec", flags=FLAGS, dont_inherit=True)
        except SyntaxError:
            continue
        return src
    raise AssertionError(name)


def fresh_block():
    m = re.search(r"\n_H3_FRESH_FILE = .*?(?=\nasync def h3_hourly_render)", APP_TEXT, re.S)
    assert m, "the fresh helpers (and the [s3-visuals] door collectors) are in app.py"
    return m.group(0)


def prompts_section():
    start = APP_TEXT.index("# --- [h3-prompts] THE HOURLY PROMPTS")
    end = APP_TEXT.index('@app.on_event("startup")\nasync def _parody_stinger_start() -> None:\n', start)
    return APP_TEXT[start:end]


def slideshow_block():
    m = re.search(r"\nSLIDESHOW_TRANSITION_LABEL = .*?(?=\n@app\.get\(\"/api/slideshow/playlist\"\))", APP_TEXT, re.S)
    assert m, "the slideshow deal helpers are in app.py"
    return m.group(0)


def transitions_list():
    m = re.search(r"\nSLIDESHOW_TRANSITIONS = \[.*?\]\n", APP_TEXT, re.S)
    assert m, "SLIDESHOW_TRANSITIONS is in app.py"
    return m.group(0)


class HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class FakeApp:
    def __init__(self):
        self.routes, self.startup = [], []

    def _route(self, method):
        def deco(path):
            def keep(fn):
                self.routes.append((method, path, fn))
                return fn
            return keep
        return deco

    def __getattr__(self, name):
        if name in ("get", "post", "put", "delete"):
            return self._route(name.upper())
        raise AttributeError(name)

    def on_event(self, kind):
        def keep(fn):
            self.startup.append(fn)
            return fn
        return keep


class FakeSystem3:
    """System 3's dice as the station's door sees them, over a desk that can
    hold POOLS1 rows - chance and roll included ([s3-visuals])."""

    def __init__(self):
        self.on = True
        self.config = {"tables": [{"id": "POOLS1", "family": "POOL", "enabled": True, "categories": []}]}
        self.pooled, self.picks, self.rolls, self.chances = [], [], [], []
        self.last = {}
        self.u = 0.5

    def live(self):
        return self.on

    def category(self, key):
        return next((c for c in self.config["tables"][0]["categories"] if c["id"] == key), None)

    def pool(self, key, opts, label=""):
        if not self.on:
            return None
        self.pooled.append((key, list(opts), label))
        cat = self.category(key)
        if cat is None:
            self.config["tables"][0]["categories"].append(
                {"id": key, "label": label[:90], "weight": 1.0,
                 "items": [{"id": "o%d" % i, "label": o[:60], "text": o, "weight": 1.0} for i, o in enumerate(opts)]})
            return list(opts)
        return [i["text"] for i in cat["items"] if i.get("enabled") is not False and float(i.get("weight", 1)) > 0]

    def pick(self, key, cands, label="", weights=None, media=None):
        if not self.on:
            return None
        w = [max(0.0, float(x or 0)) for x in weights] if weights is not None and len(list(weights)) == len(cands) \
            else [1.0] * len(cands)
        if sum(w) <= 0:
            w = [1.0] * len(cands)
        total, run, k = sum(w), 0.0, 0
        for k, x in enumerate(w):
            run += x
            if self.u * total < run:
                break
        rec = {"kind": "pick", "key": key, "label": label, "of": len(cands), "index": k + 1,
               "picked": cands[k][:160], "u": self.u, "dice": int(self.u * 100) + 1, "at": time.time(),
               "candidates": list(cands)[:12]}
        self.picks.append(rec)
        self.last[key] = rec
        return k

    def roll(self, key, label=""):
        if not self.on:
            return None
        rec = {"kind": "roll", "key": key, "label": label, "u": float(self.u),
               "dice": int(self.u * 100) + 1, "at": time.time()}
        self.rolls.append(rec)
        self.last[key] = rec
        return float(self.u)

    def chance(self, key, odds, label="", dial=""):
        if not self.on:
            return None
        hit = self.u < float(odds or 0)
        rec = {"kind": "chance", "key": key, "label": label, "odds": round(float(odds or 0), 4),
               "u": self.u, "dice": int(self.u * 100) + 1, "hit": hit, "at": time.time(), "dial": dial}
        self.chances.append(rec)
        self.last[key] = rec
        return hit

    def last_roll(self, key):
        return dict(self.last[key]) if key in self.last else None


def clip_book():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE clips(sid TEXT, name TEXT, seconds REAL, folder TEXT, playable INT, video INT, said TEXT)")
    rows = [("%016x" % i, "clip %d" % i, 20.0 + i, "f", 1, 1, "somebody talking") for i in range(4)]
    db.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?,?)", rows)
    return db


def door(tmp, s3=None):
    """The hourly door and everything it draws with, exec'd out of app.py:
    the dice door, the [h3-prompts] section, the fresh helpers (with the
    [s3-visuals] collectors) and h3_hourly_render - the render itself is a
    stub that only records what it was asked (#1285: nothing renders)."""
    s3 = s3 or FakeSystem3()
    logs, queued, rendered = [], [], []

    ns = {"__name__": "station", "DATA_DIR": Path(tmp), "RLock": threading.RLock, "Any": Any, "json": json,
          "time": time, "os": __import__("os"), "re": re, "copy": __import__("copy"), "uuid": uuid,
          "shutil": shutil, "asyncio": asyncio, "Path": Path, "random": random,
          "comfy_workshop": comfy_workshop,
          "pipeline_log": lambda lane, text: logs.append(text),
          "HTTPException": HTTPException, "Header": lambda default=None: default, "Request": object,
          "app": FakeApp(), "require_auth": lambda a: None, "require_read_auth": lambda a: None,
          "workshop_generation": lambda pid: None, "_read_all_generations": lambda: [],
          "system3_pool": s3.pool, "system3_pick": s3.pick, "system3_roll": s3.roll,
          "system3_chance": s3.chance, "system3_last_roll": s3.last_roll,
          "system3_dice_live": s3.live, "_system3": lambda: s3,
          "sfx_db_reader": clip_book, "_SFX_DB_LOCK": threading.Lock()}
    for name in ("s3_chance", "s3_roll", "s3_pool", "_S3Dice", "s3_weighted", "_s3_dice_live", "_s3_sfx_rolled"):
        exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(prompts_section(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(fresh_block(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    for name in ("h3_hourly_ad_prompt", "h3_hourly_render"):
        exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102

    class Queue:
        @staticmethod
        def add(body):
            queued.append(body)
            return {"id": "q%d" % len(queued), "status": "queued"}

    async def voice_ad_render(goal, reference_clip=None, hourly=False, trim_in_s=None, trim_out_s=None):
        words = ns["h3_prompts_hour_for"](goal, exact=True)
        rendered.append({"goal": goal, "clip": dict(reference_clip or {}), "hourly": hourly,
                         "trim_in_s": trim_in_s, "trim_out_s": trim_out_s,
                         "h3_prompts": ns["h3_prompts_words"](words, "clip") if hourly and words else None})
        return ("made the stinger", {"id": "job%d" % len(rendered)})

    def gallery_files(most):
        return [Path("wall_a.png"), Path("wall_b.png"), Path("wall_c.jpg")]

    ns.update({"_RADIO": {"chat": [{"text": "We were talking about pizza toppings all hour."}],
                          "now": {"title": "Pineapple", "artist": "The Crusts"}, "on": True},
               "_parody_stinger_queue": lambda: Queue, "_parody_stinger_wake": threading.Event(),
               "voice_ad_render": voice_ad_render, "voice_ad_spoken_copy": lambda goal: "Pine Box FM!",
               "gallery_files": gallery_files, "gallery_paper_file": lambda name: False})
    ns["_logs"], ns["_s3"], ns["_queued"], ns["_rendered"] = logs, s3, queued, rendered
    return ns


class HourlyDoor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ns = door(self.dir)
        self.s3 = self.ns["_s3"]
        self.airings = Path(self.dir) / "h3_hourly_airings.jsonl"
        # two presets and the gallery's dice on: the preset roulette rotates
        self.ns["h3_prompts_load"]()
        self.ns["h3_prompts_create"]({"name": "Chefs", "goal": "Two chefs fight over {record}"})
        self.ns["h3_prompts_dice"](True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def hour(self):
        hours = self.ns["_H3_PROMPTS_HOURS"]
        self.assertTrue(hours, "the door resolved an hour")
        return hours[-1]

    def test_the_clip_road_rolls_everything_and_the_history_keeps_it(self):
        self.s3.u = 0.5
        message, job, source = asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 0}))
        self.assertEqual(source, "clip")
        self.assertEqual(len(self.ns["_rendered"]), 1, "exactly one render was asked for, and it was the stub")
        self.assertEqual(self.ns["_queued"], [], "nothing was queued behind the door's back")
        entry = self.hour()
        # the preset pick: the gallery's dice, System 3's roll, on the hour's record
        self.assertEqual(entry["how"], "dice")
        self.assertEqual(entry["roll"]["by"], "system3")
        self.assertEqual(entry["roll"]["key"], "h3.hourly_preset")
        # the door's own rolls: the fresh rotation and the window markers -
        # and no source roll, honestly: gallery_share 0 means nothing rotated
        rolls = entry.get("rolls") or {}
        self.assertEqual(sorted(rolls), ["fresh", "marker", "preset"])
        self.assertEqual(rolls["fresh"]["of"], 4)
        self.assertTrue(str(rolls["fresh"]["picked"]).startswith("clip:"))
        self.assertEqual(rolls["marker"]["kind"], "roll")
        self.assertEqual([r["key"] for r in self.s3.rolls], ["h3.hourly_marker"])
        self.assertEqual([r["key"] for r in self.s3.picks][:1], ["h3.hourly_preset"])
        self.assertIn("h3.hourly_fresh", [r["key"] for r in self.s3.picks])
        # the window is the roll's number placed on the clip's spare room
        sent = self.ns["_rendered"][0]
        whole = sent["clip"]["seconds"]
        self.assertAlmostEqual(sent["trim_in_s"], round(0.5 * (whole - 10.0), 2))
        self.assertAlmostEqual(sent["trim_out_s"], round(sent["trim_in_s"] + 10.0, 2))
        # the words the render was told carry the rolls (ad-viewer reads these)
        self.assertEqual(sent["h3_prompts"]["rolls"]["marker"]["dice"], rolls["marker"]["dice"])
        self.assertEqual(sent["h3_prompts"]["roll"]["by"], "system3")
        # ...and the store's history keeps the hour with its rolls
        deadline = time.time() + 5
        stored = None
        while time.time() < deadline:
            got = json.loads((Path(self.dir) / "h3_prompt_presets.json").read_text(encoding="utf-8"))
            stored = next((h for h in got.get("history", []) if h.get("hour") == entry["hour"]), None)
            if stored and stored.get("rolls"):
                break
            time.sleep(0.05)
        self.assertTrue(stored and stored.get("rolls"), "the hour's rolls landed in the presets history")
        self.assertEqual(stored["rolls"]["marker"]["key"], "h3.hourly_marker")

    def test_the_gallery_road_is_a_tabled_source_pick(self):
        self.s3.u = 0.2
        message, job, source = asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 100}))
        self.assertEqual(source, "gallery image")
        self.assertEqual(self.ns["_rendered"], [], "the gallery road queues; it never renders here")
        self.assertEqual(len(self.ns["_queued"]), 1)
        body = self.ns["_queued"][0]
        self.assertTrue(body.get("hourly"))
        self.assertTrue(body["source"].startswith("wall_"))
        # the source pick went through the tabled pool with the dial's weights
        cat = self.s3.category("h3.hourly_source")
        self.assertEqual([i["text"] for i in cat["items"]], ["gallery picture", "dialogue clip"])
        src_pick = next(r for r in self.s3.picks if r["key"] == "h3.hourly_source")
        self.assertEqual(src_pick["picked"], "gallery picture")
        rolls = (self.hour().get("rolls") or {})
        self.assertEqual(sorted(rolls), ["fresh", "preset", "source"])
        self.assertTrue(str(rolls["fresh"]["picked"]).startswith("img:"))
        # dispatch dresses the queued payload with the hour's words AND rolls
        dressed = self.ns["h3_prompts_dress"](dict(body))
        self.assertEqual(dressed["h3_prompts"]["road"], "gallery")
        self.assertEqual(dressed["h3_prompts"]["rolls"]["source"]["picked"], "gallery picture")

    def test_the_desk_can_retire_a_source_road(self):
        self.s3.u = 0.2
        asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 100}))
        cat = self.s3.category("h3.hourly_source")
        next(i for i in cat["items"] if i["text"] == "gallery picture")["enabled"] = False
        self.ns["_queued"].clear()
        message, job, source = asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 100}))
        self.assertEqual(source, "clip", "the desk retired the gallery road; the dial alone cannot bring it back")

    def test_share_zero_draws_nothing_for_the_source(self):
        self.s3.u = 0.9
        asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 0}))
        self.assertEqual([r for r in self.s3.picks if r["key"] == "h3.hourly_source"], [],
                         "nothing rotates at share 0, so nothing rolls - no fake dice")

    def test_system3_off_means_the_stations_own_dice_and_no_fake_records(self):
        self.s3.on = False
        message, job, source = asyncio.run(self.ns["h3_hourly_render"]({"enabled": True, "gallery_share": 0}))
        self.assertEqual(source, "clip")
        entry = self.hour()
        rolls = entry.get("rolls") or {}
        self.assertNotIn("fresh", rolls, "the station rolled its own: no System 3 record is invented")
        self.assertNotIn("marker", rolls)
        self.assertEqual((entry["roll"] or {}).get("by"), "station")

    def test_the_clock_writes_the_durable_airing_record(self):
        """The fixture clock fires the hour once; the render is a stub that
        hands back what a bound road would have; the airing line joins the
        marker, the hour and the rolls - the record the census was missing."""
        fixed = time.mktime((2026, 9, 28, 14, 10, 0, 0, 0, -1))

        class Clock:
            @staticmethod
            def localtime(ts=None):
                return time.localtime(fixed)

            @staticmethod
            def strftime(fmt, t=None):
                return time.strftime(fmt, t if t is not None else time.localtime(fixed))

            @staticmethod
            def time():
                return fixed

        saved, loads = [], {"enabled": True, "gallery_share": 0}
        ns = {"__name__": "clock", "asyncio": asyncio, "time": Clock, "json": json,
              "Any": Any, "Path": Path, "DATA_DIR": Path(self.dir),
              "pipeline_log": lambda lane, text: None,
              "_RADIO": {"on": True}, "_H3_HOURLY_LAST": [""], "_H3_HOURLY_MINUTE": 3,
              "h3_hourly_load": lambda: dict(loads),
              "h3_hourly_save": lambda patch: saved.append(patch) or dict(loads, **patch),
              "_H3_AIRINGS_FILE": self.airings,
              "_H3_HOURLY_ROLLS_LAST": [None],
              "_h3_prompts_offloop": lambda fn, *a: fn(*a)}
        exec(compile(function_source("h3_hourly_airing_note"), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102

        async def render(state):
            ns["_H3_HOURLY_ROLLS_LAST"][0] = {"at": fixed, "hour": "h3h-fixture",
                                              "rolls": {"marker": {"kind": "roll", "key": "h3.hourly_marker", "dice": 51}}}
            return ("made the stinger", {"id": "job-fixture"}, "clip")
        ns["h3_hourly_render"] = render
        exec(compile(function_source("h3_hourly_ad_clock"), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102

        async def run():
            task = asyncio.get_running_loop().create_task(ns["h3_hourly_ad_clock"]())
            deadline = asyncio.get_running_loop().time() + 5
            while not self.airings.exists() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.02)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(run())
        rows = [json.loads(line) for line in self.airings.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1, "one hourly render, one airing line")
        row = rows[0]
        self.assertEqual(row["marker"], "2026092814", "the fixture clock's hour")
        self.assertEqual(row["hour"], "h3h-fixture", "joins the presets history")
        self.assertEqual(row["source"], "clip")
        self.assertEqual(row["job"], "job-fixture")
        self.assertEqual(row["rolls"]["marker"]["dice"], 51)
        self.assertEqual(saved[-1]["last_marker"], "2026092814")

    def test_nothing_in_the_door_can_reach_a_real_render(self):
        """#1285 stays law: the door text may only queue through the parody
        queue or go through voice_ad_render - never submit work itself."""
        text = function_source("h3_hourly_render") + fresh_block()
        for road in ("_submit_generation(", "build_workflow(", "comfy_submit"):
            self.assertNotIn(road, text)


def slideshow(tmp, s3=None, rows=None):
    s3 = s3 or FakeSystem3()
    stamp = time.time()
    rows = rows if rows is not None else [
        {"file": "pic_%02d.png" % i, "at": stamp - 1000 + i, "bytes": 1000 + i, "kind": "image"}
        for i in range(12)]

    async def scan(force=False):
        return {"ok": True, "rows": [dict(r) for r in rows], "total": len(rows),
                "newest": max((r["at"] for r in rows), default=0.0)}

    ns = {"__name__": "station", "Any": Any, "asyncio": asyncio, "time": time, "random": random,
          "Path": Path, "json": json, "re": re,
          "Header": lambda default=None: default, "Request": object,
          "require_read_auth": lambda a: None, "slideshow_scan": scan,
          "_slideshow_favorites_read_blocking": lambda: set(),
          "system3_pool": s3.pool, "system3_pick": s3.pick, "system3_roll": s3.roll,
          "system3_chance": s3.chance, "system3_last_roll": s3.last_roll,
          "system3_dice_live": s3.live, "_system3": lambda: s3}
    for name in ("s3_roll", "s3_pool", "_S3Dice", "s3_weighted", "_s3_dice_live"):
        exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(transitions_list(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(slideshow_block(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(function_source("slideshow_playlist_api"), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    ns["_s3"], ns["_rows"] = s3, rows
    return ns


class SlideshowDeal(unittest.TestCase):
    def setUp(self):
        self.ns = slideshow(None)
        self.s3 = self.ns["_s3"]

    def ask(self, **kw):
        args = dict(request=None, limit=200, offset=0, kind="all", favorites=0,
                    order="shuffle", seed=0, since=0.0, authorization="k")
        args.update(kw)
        return asyncio.run(self.ns["slideshow_playlist_api"](**args))

    def test_a_seedless_ask_rolls_the_deal_once_and_the_seed_reproduces_it(self):
        self.s3.u = 0.375
        got = self.ask(limit=5)
        self.assertEqual([r["key"] for r in self.s3.rolls if r["key"] == "slideshow.deal"], ["slideshow.deal"],
                         "one roll deals the whole page")
        seed = got["seed"]
        self.assertEqual(seed, 1 + int(0.375 * float((1 << 53) - 2)),
                         "the dealt seed IS the recorded roll, on the records.rotation_deal pattern")
        replay = [dict(r) for r in self.ns["_rows"]]
        random.Random(seed).shuffle(replay)
        self.assertEqual([r["file"] for r in got["rows"]], [r["file"] for r in replay[:5]])
        self.assertEqual(got["deal"]["roll"]["key"], "slideshow.deal")
        self.assertEqual(got["deal"]["roll"]["u"], 0.375)

    def test_a_brought_seed_continues_the_same_deal_with_no_new_roll(self):
        first = self.ask(limit=5)
        deals = len([r for r in self.s3.rolls if r["key"] == "slideshow.deal"])
        second = self.ask(limit=5, offset=5, seed=first["seed"])
        self.assertEqual(len([r for r in self.s3.rolls if r["key"] == "slideshow.deal"]), deals,
                         "page two rolls nothing")
        replay = [dict(r) for r in self.ns["_rows"]]
        random.Random(first["seed"]).shuffle(replay)
        self.assertEqual([r["file"] for r in second["rows"]], [r["file"] for r in replay[5:10]])
        self.assertNotIn("roll", (second.get("deal") or {}), "no roll happened, none is claimed")

    def test_every_served_row_carries_a_dealt_transition_from_the_tabled_pool(self):
        got = self.ask()
        concrete = [t for t in self.ns["SLIDESHOW_TRANSITIONS"] if t != "all"]
        self.assertTrue(got["rows"], "rows served")
        for row in got["rows"]:
            self.assertIn(row["transition"], concrete)
        cat = self.s3.category("slideshow.transition")
        self.assertEqual([i["text"] for i in cat["items"]], concrete, "the pool is tabled (POOLS1)")
        self.assertTrue(any(r["key"] == "slideshow.transition" for r in self.s3.rolls),
                        "one recorded roll dealt the transitions")
        self.assertEqual(got["deal"]["transition"]["key"], "slideshow.transition")

    def test_the_desk_can_retire_a_transition(self):
        self.ask()
        cat = self.s3.category("slideshow.transition")
        for item in cat["items"]:
            if item["text"] != "crt":
                item["enabled"] = False
        got = self.ask()
        self.assertEqual({r["transition"] for r in got["rows"]}, {"crt"},
                         "every other transition is retired on the desk")

    def test_the_hot_load_deals_a_new_renders_entrance(self):
        base = self.ask()
        cutoff = max(r["at"] for r in self.ns["_rows"]) - 0.5
        got = self.ask(since=cutoff)
        self.assertTrue(got["fresh"], "the newest row is fresh")
        for row in got["fresh"]:
            self.assertIn(row["transition"], [t for t in self.ns["SLIDESHOW_TRANSITIONS"] if t != "all"])

    def test_system3_off_still_deals_and_says_nothing_false(self):
        self.s3.on = False
        got = self.ask(limit=5)
        self.assertGreater(got["seed"], 1)
        replay = [dict(r) for r in self.ns["_rows"]]
        random.Random(got["seed"]).shuffle(replay)
        self.assertEqual([r["file"] for r in got["rows"]], [r["file"] for r in replay[:5]])
        self.assertIsNone(got["deal"], "the station rolled its own: no System 3 record is claimed")

    def test_the_other_orders_are_untouched(self):
        got = self.ask(order="old", seed=0)
        self.assertEqual([r["file"] for r in got["rows"]], [r["file"] for r in sorted(self.ns["_rows"], key=lambda r: r["at"])])
        self.assertEqual(got["seed"], 1, "no deal for a dated order - the old answer shape")


class Wiring(unittest.TestCase):
    def test_every_edit_is_in_app_py(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("s3_visuals_patch", ROOT / "tools" / "s3_visuals_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        applied, missing = mod.check(APP_TEXT)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(APP_TEXT)))

    def test_the_views_consume_the_deal_on_both_surfaces(self):
        pairs = [(ROOT / "desktop" / "renderer" / "slideshow.js",
                  ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "slideshow.js"),
                 (ROOT / "desktop" / "renderer" / "ad-viewer.js",
                  ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "ad-viewer.js")]
        for desk, kiosk in pairs:
            self.assertEqual(desk.read_bytes(), kiosk.read_bytes(), "%s rides the kiosk bundle unchanged" % desk.name)
        show = pairs[0][0].read_text(encoding="utf-8")
        self.assertNotIn("Math.random", show, "the shuffle path left the client entirely")
        self.assertIn("seed: 0,", show)
        self.assertIn("row.transition", show)
        viewer = pairs[1][0].read_text(encoding="utf-8")
        self.assertIn("usedRolls", viewer)
        self.assertIn("'Hourly rolls'", viewer)


if __name__ == "__main__":
    unittest.main()
