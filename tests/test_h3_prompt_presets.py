"""[h3-prompts] The hourly H3 render's words are presets the operator saves,
cycles and rolls from the Pine Box Gallery (P and the dice), and every video
shows the words it was told.

The store, its doors, the hour's resolution (the active preset reaches the
hourly prompt; the dice pick among the presets through System 3's own door and
the roll is recorded), the clip road's words in voice_ad_render, the dress a
queued host / gallery render takes at dispatch and the compose wrapper are all
exec'd out of app.py's own text with stubs - no station, no GPU, no render.
The popup's prompts-used section is read through ad-viewer.js's own
usedWords() (node, when it is installed)."""
import __future__
import asyncio
import copy
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
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
import comfy_workshop  # noqa: E402 - the prompt compiler itself, pure

APP_TEXT = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
FLAGS = __future__.annotations.compiler_flag          # app.py's own `from __future__ import annotations`


def function_source(name):
    """A top-level def/class out of app.py, cut at the next top-level statement
    (no whole-file parse of a 12 MB file)."""
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


def section_source():
    start = APP_TEXT.index("# --- [h3-prompts] THE HOURLY PROMPTS")
    end = APP_TEXT.index('@app.on_event("startup")\nasync def _parody_stinger_start() -> None:\n', start)
    return APP_TEXT[start:end]


def _tool():
    spec = importlib.util.spec_from_file_location("h3_prompt_presets_patch", ROOT / "tools" / "h3_prompt_presets_patch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class FakeApp:
    """Records the routes the section registers, in order."""

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
    """System 3's dice as the station's door sees them (system3_pool / _pick /
    _last_roll / _dice_live) over a desk config it can hold POOLS1 rows in."""

    def __init__(self):
        self.on = True
        self.config = {"tables": [{"id": "POOLS1", "family": "POOL", "enabled": True, "categories": []}]}
        self.pooled, self.picks, self.last = [], [], {}
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
        if cat is None:            # tabled (the runtime writes it within seconds)
            self.config["tables"][0]["categories"].append(
                {"id": key, "label": label[:90], "weight": 1.0,
                 "items": [{"id": "o%d" % i, "label": o[:60], "text": o, "weight": 1.0} for i, o in enumerate(opts)]})
            return list(opts)
        return [i["text"] for i in cat["items"] if i.get("enabled") is not False and float(i.get("weight", 1)) > 0]

    def pick(self, key, cands, label="", weights=None, media=None):
        if not self.on:
            return None
        w = list(weights) if weights is not None else [1.0] * len(cands)
        total, run, k = sum(w), 0.0, 0
        for k, x in enumerate(w):
            run += x
            if self.u * total < run:
                break
        rec = {"kind": "pick", "key": key, "label": label, "of": len(cands), "index": k + 1,
               "picked": cands[k][:160], "u": self.u, "dice": int(self.u * 100) + 1, "at": time.time(),
               "candidates": list(cands), "weights": w}
        self.picks.append(rec)
        self.last[key] = rec
        return k

    def last_roll(self, key):
        return dict(self.last[key]) if key in self.last else None


def station(tmp, s3=None, rows=None):
    """The section and System 3's dice door, exec'd out of app.py into one namespace."""
    s3 = s3 or FakeSystem3()
    logs = []

    def need_auth(authorization):
        if not authorization:
            raise HTTPException(401, "no key")

    ns = {"__name__": "station", "DATA_DIR": Path(tmp), "RLock": threading.RLock, "Any": Any, "json": json,
          "time": time, "os": os, "re": re, "copy": copy, "uuid": uuid, "shutil": shutil, "asyncio": asyncio,
          "Path": Path, "random": random, "comfy_workshop": comfy_workshop, "pipeline_log": lambda lane, text: logs.append(text),
          "HTTPException": HTTPException, "Header": lambda default=None: default, "Request": object, "app": FakeApp(),
          "require_auth": need_auth, "require_read_auth": need_auth,
          "workshop_generation": lambda pid: (rows or {}).get(pid), "_read_all_generations": lambda: list((rows or {}).values()),
          "system3_pool": s3.pool, "system3_pick": s3.pick, "system3_last_roll": s3.last_roll,
          "system3_dice_live": s3.live, "_system3": lambda: s3}
    for name in ("s3_pool", "_S3Dice", "s3_weighted", "_s3_dice_live", "_s3_sfx_rolled"):
        exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(section_source(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102 - the station's own code
    ns["_logs"], ns["_s3"] = logs, s3
    return ns


class Req:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class Presets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.rows = {}
        self.ns = station(self.dir, rows=self.rows)
        self.file = Path(self.dir) / "h3_prompt_presets.json"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- the store --------------------------------------------------------
    def test_today_s_words_are_the_default_preset(self):
        view = self.ns["h3_prompts_view"]()
        self.assertEqual([p["name"] for p in view["presets"]], ["Default"])
        self.assertEqual((view["active"], view["dice"], view["next"]), ("default", False, None))
        default = self.ns["H3_PROMPTS_DEFAULT"]
        for field in self.ns["H3_PROMPTS_FIELDS"]:
            self.assertEqual(view["presets"][0][field], default[field], field)
        self.assertFalse(self.file.exists(), "nothing is written until the operator acts or an hour runs")
        fill = self.ns["h3_prompts_fill"]
        # the words the hourly door always used, now the Default's (the literals
        # still in h3_hourly_render and voice_ad_render, joined across lines)
        joined = re.sub(r'"\s*\n\s*"', "", APP_TEXT)
        self.assertIn('"' + fill(default["gallery"], goal="").rstrip() + ' " + goal', joined)
        self.assertIn('"' + fill(default["host"], goal="").rstrip() + ' " + goal', joined)
        clip_head, clip_tail = default["clip"].split("{goal}")
        self.assertIn('"' + clip_head + '"\n                 + str(goal or "deliver the ad")\n                 + "'
                      + clip_tail + '")', re.sub(r'"\s*\n\s*"(?=[A-Za-z. ,])', "", APP_TEXT))
        self.assertEqual(fill(default["goal"], conversation="X"),
                         "Make a short, funny but professional Pine Box FM sponsor stinger that naturally "
                         "follows this hour's conversation: X")

    def test_create_update_activate_delete_and_every_write_is_atomic(self):
        ns = self.ns
        got = ns["h3_prompts_create"]({"name": "  Chefs   at war ", "goal": "Two chefs fight over {record}",
                                       "clip": "", "speech": "Pine Box FM - hot!", "activate": True})
        chefs = next(p for p in got["presets"] if p["id"] == got["saved"])
        self.assertEqual(chefs["name"], "Chefs at war")
        self.assertEqual(chefs["clip"], ns["H3_PROMPTS_DEFAULT"]["clip"], "a blank road keeps the Default's words")
        self.assertEqual(got["active"], chefs["id"])
        self.assertTrue(self.file.exists())
        self.assertEqual([p.name for p in Path(self.dir).iterdir() if p.name.endswith(".tmp")], [])
        on_disk = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual([p["name"] for p in on_disk["presets"]], ["Default", "Chefs at war"])
        with self.assertRaises(HTTPException) as same:
            ns["h3_prompts_create"]({"name": "chefs AT war"})
        self.assertEqual(same.exception.status_code, 409)
        with self.assertRaises(HTTPException) as stale:
            ns["h3_prompts_update"](chefs["id"], {"goal": "x", "was": chefs["updated_at"] - 50})
        self.assertEqual(stale.exception.status_code, 409, "a save over a newer preset is refused")
        got = ns["h3_prompts_update"](chefs["id"], {"name": "Chefs", "style": "  claymation ", "was": chefs["updated_at"]})
        chefs = next(p for p in got["presets"] if p["id"] == chefs["id"])
        self.assertEqual((chefs["name"], chefs["style"], chefs["goal"]), ("Chefs", "claymation", "Two chefs fight over {record}"))
        self.assertEqual(ns["h3_prompts_activate"]("default")["active"], "default")
        with self.assertRaises(HTTPException):
            ns["h3_prompts_activate"]("p-nothere")
        got = ns["h3_prompts_delete"](chefs["id"])
        self.assertEqual([p["name"] for p in got["presets"]], ["Default"])
        with self.assertRaises(HTTPException) as last:
            ns["h3_prompts_delete"]("default")
        self.assertEqual(last.exception.status_code, 409, "the last preset stays")
        # a fresh process reads what was written
        again = station(self.dir, rows=self.rows)
        self.assertEqual([p["name"] for p in again["h3_prompts_view"]()["presets"]], ["Default"])

    def test_an_unreadable_store_falls_back_and_is_kept(self):
        self.file.write_text("{not json", encoding="utf-8")
        view = station(self.dir)["h3_prompts_view"]()
        self.assertEqual([p["name"] for p in view["presets"]], ["Default"])
        self.assertTrue((Path(self.dir) / "h3_prompt_presets.json.unreadable").exists())

    # --- the doors -------------------------------------------------------
    def test_the_doors_need_the_key_and_the_fixed_routes_come_first(self):
        routes = [(m, p) for m, p, _fn in self.ns["app"].routes]
        for want in [("GET", "/api/h3/prompts"), ("GET", "/api/h3/prompts/history"), ("POST", "/api/h3/prompts"),
                     ("POST", "/api/h3/prompts/active"), ("POST", "/api/h3/prompts/dice"),
                     ("POST", "/api/h3/prompts/next"), ("POST", "/api/h3/prompts/{pid}"),
                     ("POST", "/api/h3/prompts/{pid}/delete")]:
            self.assertIn(want, routes)
        at = routes.index(("POST", "/api/h3/prompts/{pid}"))
        for fixed in ("active", "dice", "next"):
            self.assertLess(routes.index(("POST", "/api/h3/prompts/" + fixed)), at, fixed + " is not swallowed by {pid}")
        self.assertTrue(self.ns["app"].startup, "the store loads at startup, off the loop")
        door = {(m, p): fn for m, p, fn in self.ns["app"].routes}

        async def run():
            with self.assertRaises(HTTPException):
                await door[("POST", "/api/h3/prompts")](Req({"name": "x"}), authorization=None)
            made = await door[("POST", "/api/h3/prompts")](Req({"name": "Beach"}), authorization="k")
            pid = made["saved"]
            await door[("POST", "/api/h3/prompts/{pid}")](pid, Req({"goal": "A beach party"}), authorization="k")
            await door[("POST", "/api/h3/prompts/active")](Req({"id": pid}), authorization="k")
            await door[("POST", "/api/h3/prompts/dice")](Req({"on": True}), authorization="k")
            await door[("POST", "/api/h3/prompts/next")](Req({"preset_id": pid}), authorization="k")
            view = await door[("GET", "/api/h3/prompts")](summary=0, authorization="k")
            summary = await door[("GET", "/api/h3/prompts")](summary=1, authorization="k")
            gone = await door[("POST", "/api/h3/prompts/{pid}/delete")](pid, authorization="k")
            return view, summary, gone
        view, summary, gone = asyncio.run(run())
        beach = next(p for p in view["presets"] if p["name"] == "Beach")
        self.assertEqual((beach["goal"], view["active"], view["dice"]), ("A beach party", beach["id"], True))
        self.assertEqual(view["next"]["name"], "Beach")
        self.assertEqual(view["next_hour"]["how"], "next")
        self.assertNotIn("presets", summary, "the gallery's header polls the small view")
        self.assertEqual(summary["next_hour"]["words"], '"Beach", pinned for the next hour')
        self.assertEqual([p["name"] for p in gone["presets"]], ["Default"])
        self.assertEqual(gone["next"]["name"], "Beach", "a pin is a copy: deleting the preset leaves the next hour's words")

    # --- the hour -----------------------------------------------------------
    def _brief(self, ns, chat, now):
        ns["_RADIO"] = {"chat": chat, "now": now, "on": True}
        exec(compile(function_source("h3_hourly_ad_prompt"), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
        return ns["h3_hourly_ad_prompt"]

    def test_the_active_preset_reaches_the_hourly_prompt(self):
        ns = self.ns
        brief = self._brief(ns, [{"text": "short"}, {"text": "We were just talking about pizza toppings."}],
                            {"title": "Pineapple", "artist": "The Crusts"})
        ns["h3_prompts_load"]()
        self.assertEqual(brief(), "Make a short, funny but professional Pine Box FM sponsor stinger that naturally "
                                  "follows this hour's conversation: We were just talking about pizza toppings.",
                         "the Default preset is the brief this always was")
        made = ns["h3_prompts_create"]({"name": "Chefs", "goal": "Two chefs fight over {record}", "activate": True,
                                        "clip": "In a kitchen: {goal}. They shout.", "gallery": "The picture comes alive: {goal}",
                                        "speech": "Pine Box FM - hot!", "style": "claymation",
                                        "constraints": "No cats.", "audio_direction": "Sizzling pans."})
        goal = brief()
        self.assertEqual(goal, "Two chefs fight over Pineapple The Crusts")
        hours = json.loads(self.file.read_text(encoding="utf-8"))["history"]
        self.assertEqual((hours[-1]["preset"]["id"], hours[-1]["how"], hours[-1]["goal"]), (made["saved"], "active", goal))
        # the clip road: voice_ad_render, out of app.py, queues the preset's words
        queued = []
        for name in ("voice_ad_spoken_copy", "h3_ad_speech_seconds", "h3_ad_speech_parts", "h3_ad_duration_plan",
                     "voice_ad_render"):
            exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
        ns.update({"math": __import__("math"), "H3_MAX_DURATION_S": 15.125, "H3_MAX_REFERENCE_S": 15.0,
                   "H3_AD_WORDS_PER_SECOND": 2.2, "s3_roll": lambda key, label="": 0.25,
                   "_parody_stinger_queue": lambda: type("Q", (), {"add": staticmethod(
                       lambda body: queued.append(body) or {"id": "q%d" % len(queued), "status": "queued"})})(),
                   "_parody_stinger_wake": threading.Event(), "_RADIO": {"on": False}})
        clip = {"id": "0123456789abcdef", "name": "talker", "seconds": 10.0, "video": True}
        asyncio.run(ns["voice_ad_render"](goal, reference_clip=clip, hourly=True, trim_in_s=0.0, trim_out_s=10.0))
        body = queued[-1]
        self.assertEqual(body["prompt"], "In a kitchen: Two chefs fight over Pineapple The Crusts. They shout.")
        self.assertEqual(body["speech"], "Pine Box FM - hot!")
        self.assertEqual((body["style"], body["h3_brief"]), ("claymation", {"constraints": "No cats.", "audio_direction": "Sizzling pans."}))
        self.assertEqual((body["h3_prompts"]["road"], body["h3_prompts"]["preset"]["name"]), ("clip", "Chefs"))
        # a listener's ad (not hourly) is told what it always was
        asyncio.run(ns["voice_ad_render"]("wave at the sign", reference_clip=clip))
        self.assertNotIn("h3_prompts", queued[-1])
        self.assertTrue(queued[-1]["prompt"].startswith("Create a polished short Pine Box advertisement"))
        # the gallery road: h3_hourly_render queues its own words; dispatch dresses them
        gallery = {"mode": "reference", "purpose": "parody_stinger", "source": "a.png", "source_type": "gallery",
                   "speech": "", "prompt": "Create a Pine Box FM stinger using the supplied image. Natural motion and "
                                           "synchronized spoken dialogue. No captions or logos. " + goal,
                   "duration_mode": "at_least", "steps": 4, "air_it": False, "hourly": True}
        dressed = ns["h3_prompts_dress"](gallery)
        self.assertEqual(dressed["prompt"], "The picture comes alive: " + goal)
        self.assertEqual((dressed["speech"], dressed["style"]), ("Pine Box FM - hot!", "claymation"))
        self.assertEqual(dressed["h3_prompts"]["road"], "gallery")
        self.assertIs(ns["h3_prompts_dress"](dressed), dressed, "dressed once")
        plain = dict(gallery, hourly=False)
        self.assertIs(ns["h3_prompts_dress"](plain), plain, "a render that is not hourly passes as it is")
        # the preset's audio direction and constraints reach the compiled prompt; the gear's brief is lent back
        before = dict(comfy_workshop.BRIEF)
        text = ns["h3_prompts_compose"](dressed["h3_brief"], dressed["prompt"], dressed["speech"], "image", "reference",
                                        seconds=5.0, purpose="parody_stinger", style=dressed["style"])
        self.assertIn("No cats.", text)
        self.assertIn("Sizzling pans.", text)
        self.assertIn("claymation - one style only", text)
        self.assertEqual(comfy_workshop.BRIEF, before)
        self.assertEqual(ns["h3_prompts_compose"](None, "A scene", "", "", "text", seconds=5.0),
                         comfy_workshop.compose_prompt("A scene", "", "", "text", seconds=5.0))

    def test_a_queued_render_finds_its_own_hour(self):
        ns = self.ns
        ns["h3_prompts_create"]({"name": "Fixed", "goal": "The same scene every hour", "activate": True,
                                 "gallery": "First words: {goal}"})
        first = ns["h3_prompts_hour"]("talk", "")
        ns["h3_prompts_update"](first["preset"]["id"], {"gallery": "Second words: {goal}"})
        second = ns["h3_prompts_hour"]("talk", "")
        self.assertEqual(first["goal"], second["goal"], "the same brief two hours running")
        payload = {"prompt": "Create a Pine Box FM stinger ... " + first["goal"], "hourly": True,
                   "mode": "reference", "source_type": "gallery"}
        self.assertEqual(ns["h3_prompts_dress"](payload)["prompt"], "First words: The same scene every hour",
                         "first in, first out: the older hour's render takes the older hour's words")
        self.assertEqual(ns["h3_prompts_dress"](payload)["prompt"], "Second words: The same scene every hour")
        # after a restart the claims are read back from the store
        again = station(self.dir)
        again["h3_prompts_load"]()
        self.assertEqual(again["h3_prompts_dress"](payload)["h3_prompts"]["hour"], second["hour"],
                         "every hour taken: the one taken last (a retried render)")

    # --- the dice ----------------------------------------------------------
    def test_the_dice_pick_among_the_presets_through_system3_and_record_the_roll(self):
        ns, s3 = self.ns, self.ns["_s3"]
        for name in ("Chefs", "Beach"):
            ns["h3_prompts_create"]({"name": name, "goal": name + " scene"})
        ns["h3_prompts_dice"](True)
        self.assertEqual(s3.pooled[-1][0], "h3.hourly_preset", "dice on: the presets go on the desk")
        self.assertEqual(sorted(s3.category("h3.hourly_preset")["items"][i]["text"] for i in range(3)),
                         ["Beach", "Chefs", "Default"])
        s3.u = 0.5
        hour = ns["h3_prompts_hour"]("talk", "")
        self.assertEqual(hour["how"], "dice")
        roll = hour["roll"]
        self.assertEqual((roll["by"], roll["picked"], roll["index"], roll["of"]), ("system3", "Chefs", 2, 3))
        self.assertEqual((roll["dice"], s3.picks[-1]["weights"]), (51, [1.0, 1.0, 1.0]))
        self.assertEqual(hour["goal"], "Chefs scene")
        stored = json.loads(self.file.read_text(encoding="utf-8"))["history"][-1]
        self.assertEqual((stored["how"], stored["roll"]["dice"], stored["preset"]["name"]), ("dice", 51, "Chefs"))
        self.assertIn("rolled by System 3: d100 51, 2 of 3", ns["h3_prompts_how"](stored))
        # the desk weights them: one switched off, one weighted up; a preset saved since rides at 1
        items = {i["text"]: i for i in s3.category("h3.hourly_preset")["items"]}
        items["Default"]["enabled"] = False
        items["Beach"]["weight"] = 3.0
        ns["h3_prompts_create"]({"name": "Late", "goal": "Late scene"})
        s3.u = 0.99
        hour = ns["h3_prompts_hour"]("talk", "")
        self.assertEqual(s3.picks[-1]["candidates"], ["Chefs", "Beach", "Late"])
        self.assertEqual(s3.picks[-1]["weights"], [1.0, 3.0, 1.0])
        self.assertEqual(hour["preset"]["name"], "Late")
        odds = {o["id"]: o for o in ns["h3_prompts_view"]()["odds"]}
        late = next(p for p in ns["h3_prompts_view"]()["presets"] if p["name"] == "Late")
        self.assertEqual((odds[late["id"]]["share"], odds[late["id"]]["on_desk"], odds["default"]["off"]), (20.0, False, True))
        # a pin beats the dice, once
        ns["h3_prompts_pin"]({"preset_id": "default"})
        hour = ns["h3_prompts_hour"]("talk", "")
        self.assertEqual((hour["how"], hour["preset"]["name"]), ("next", "Default"))
        self.assertIsNone(json.loads(self.file.read_text(encoding="utf-8"))["next"], "the pin is spent")
        self.assertEqual(ns["h3_prompts_hour"]("talk", "")["how"], "dice")
        # System 3 off: the station rolls its own, and says so
        s3.on = False
        hour = ns["h3_prompts_hour"]("talk", "")
        self.assertEqual(hour["roll"]["by"], "station")
        self.assertIn(hour["preset"]["name"], ("Default", "Chefs", "Beach", "Late"))

    def test_the_hour_never_takes_the_lock_on_the_event_loop(self):
        ns = self.ns
        ns["h3_prompts_load"]()
        held, release = threading.Event(), threading.Event()

        def hold():
            with ns["_H3_PROMPTS_LOCK"]:
                held.set()
                release.wait(5)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(5)

        async def hour():
            began = time.time()
            got = ns["h3_prompts_hour"]("talk on the loop", "")
            spent = time.time() - began
            release.set()
            await asyncio.sleep(0.3)          # the history write, in a worker, once the lock is free
            return got, spent
        got, spent = asyncio.run(hour())
        t.join(5)
        # held until after this returns: had the hour waited on the lock it would
        # have sat the holder's whole five seconds out
        self.assertLess(spent, 2.0, "the loop never waited on the store's lock")
        deadline = time.time() + 5
        while time.time() < deadline:
            hours = json.loads(self.file.read_text(encoding="utf-8")).get("history") if self.file.exists() else []
            if hours and hours[-1]["hour"] == got["hour"]:
                break
            time.sleep(0.05)
        self.assertEqual(hours[-1]["hour"], got["hour"])

    # --- a video's words, reused -------------------------------------------
    def test_a_video_s_words_can_be_pinned_or_saved(self):
        ns = self.ns
        self.rows["new"] = {"prompt_id": "new", "files": ["PineBox-H3_00160_.mp4"], "request": "x",
                            "h3_prompts": {"preset": {"id": "p-1", "name": "Chefs"},
                                           "fields": dict(ns["H3_PROMPTS_DEFAULT"], goal="Chefs {record}")}}
        self.rows["old"] = {"prompt_id": "old", "files": ["PineBox-H3_00151_.mp4"], "speech": "",
                            "request": "Create a polished short Pine Box advertisement ... must Make a short ..."}
        self.rows["none"] = {"prompt_id": "none", "files": ["x.mp4"]}
        view = ns["h3_prompts_pin"]({"from_prompt_id": "new"})
        self.assertEqual(view["next"]["name"], "Chefs")
        self.assertEqual(ns["h3_prompts_hour"]("talk", "Song")["goal"], "Chefs Song")
        made = ns["h3_prompts_create"]({"from_prompt_id": "old", "name": "The old one"})
        old = next(p for p in made["presets"] if p["id"] == made["saved"])
        self.assertEqual(old["clip"], self.rows["old"]["request"], "a video from before the presets: what it was sent")
        self.assertEqual(old["gallery"], old["clip"])
        with self.assertRaises(HTTPException) as none:
            ns["h3_prompts_pin"]({"from_prompt_id": "none"})
        self.assertEqual(none.exception.status_code, 409)
        history = ns["h3_prompts_history"](10)
        self.assertEqual(history["hours"][0]["how"], "next")


class Wiring(unittest.TestCase):
    def test_every_edit_is_in_app_py(self):
        mod = _tool()
        applied, missing = mod.check(APP_TEXT)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(APP_TEXT)))
        for bit in ('return h3_prompts_hour(subject[:520], " ".join(record.split()))["goal"]',
                    "payload = h3_prompts_dress(payload)", 'final_prompt = h3_prompts_compose(payload.get("h3_brief"),',
                    '"hourly", "h3_prompts"):', '**h3_prompts_payload_keys(_h3_words),',
                    '**({"h3_prompts": payload["h3_prompts"]}'):
            self.assertIn(bit, APP_TEXT)

    def test_nothing_here_renders(self):
        section = section_source()
        for road in ("_submit_generation(", "_parody_stinger_queue(", "voice_ad_render(", "build_workflow("):
            self.assertNotIn(road, section, "the presets change what the hourly render is told - never add one (#1285)")
        self.assertNotRegex(section, r"\brandom\.", "the dice are System 3's door, never a bare draw")


class Popup(unittest.TestCase):
    VIEWS = [ROOT / "desktop" / "renderer" / "ad-viewer.js", ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "ad-viewer.js"]

    def test_the_copies_carry_the_p_the_dice_and_the_section(self):
        texts = [p.read_text(encoding="utf-8") for p in self.VIEWS]
        self.assertEqual(texts[0], texts[1], "the desk's and the tablet's gallery are the same file")
        js = texts[0]
        self.assertIn("h3Bar.insertBefore(pButton, h3Gear); h3Bar.insertBefore(pDice, h3Gear);", js)
        self.assertIn("'m:casino'", js)
        self.assertIn("pBackOff = root.PineDismiss.onBack(", js, "BACK closes the P screen, then the card (#1450c)")
        self.assertIn("clearInterval(pTimer); pBackOff();", js)
        self.assertLess(js.index("var stage = make('div', 'pav-stage'); box.appendChild(stage);"),
                        js.index("used.append(usedTick, usedBody); box.appendChild(used);"))
        self.assertLess(js.index("used.append(usedTick, usedBody); box.appendChild(used);"),
                        js.index("var modes = make('div', 'pav-modes');"), "under the video, above Generated / Original")
        self.assertNotRegex(js, "[\U0001F300-\U0001FAFF]", "Carbon icons, never emoji")
        css = (ROOT / "desktop" / "renderer" / "view-chrome.css").read_text(encoding="utf-8")
        for rule in (".pav-used-tick", ".pine-voice-ad-card .pav-p ", ".pav-prompts[hidden]", ".pav-on-prompts"):
            self.assertIn(rule, css)

    def test_the_section_renders_from_a_video_record(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed here")
        rec = {"hour": "h3h-1", "at": 1790586208, "how": "dice", "road": "clip",
               "preset": {"id": "p-1", "name": "Chefs at war"},
               "roll": {"by": "system3", "dice": 37, "index": 2, "of": 3},
               "goal": "Two chefs fight", "direction": "In a kitchen: Two chefs fight.", "speech": "Pine Box FM!",
               "style": "claymation", "constraints": "", "audio_direction": ""}
        rows = [{"prompt_id": "a", "files": ["PineBox-H3_00160_.mp4"], "request": "In a kitchen: Two chefs fight.",
                 "tags": "subject_definitions: ...", "h3_prompts": rec},
                {"prompt_id": "b", "files": ["PineBox-H3_00151_.mp4"], "tags": "summary: ...",
                 "request": "Create a polished short Pine Box advertisement from the reference performance. The person "
                            "or people on screen must Make a short, funny but professional Pine Box FM sponsor stinger "
                            "that naturally follows this hour's conversation: hello"},
                {"prompt_id": "c", "files": ["x.png"]}]
        script = ("const v = require(%s); process.stdout.write(JSON.stringify(%s.map(r => v.usedWords(r))));"
                  % (json.dumps(str(self.VIEWS[0])), json.dumps(rows)))
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        new, old, none = json.loads(out.stdout)
        self.assertEqual([i["label"] for i in new["items"]],
                         ["Brief", "Direction sent", "Line spoken", "Style", "Final H3 prompt"])
        self.assertEqual(new["summary"], '"Chefs at war" - rolled by System 3: d100 37, 2 of 3 - clip road')
        self.assertTrue(new["recorded"] and new["reusable"])
        self.assertEqual((old["recorded"], old["hourly"], old["summary"]),
                         (False, True, "an hourly render from before its prompts were kept"))
        self.assertEqual([i["label"] for i in old["items"]], ["Direction sent", "Final H3 prompt"])
        self.assertIn("were not recorded", old["note"])
        self.assertEqual((none["summary"], none["reusable"], none["note"]),
                         ("not recorded", False, "No prompt was recorded with this video."))


if __name__ == "__main__":
    unittest.main()
