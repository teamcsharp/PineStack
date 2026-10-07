"""[pineex] Wave D, 2026-10-06: the pineEX preset installer and the supercut version of an hourly render.

1. tools/pineex_preset_install.py creates the preset when the station has none of that name, leaves it
   alone when it is in place, updates it (matched by name, case-insensitively) when it differs, and says
   which fields the store would cut - proven against the station's own [h3-prompts] doors, exec'd out of
   app.py's text onto a real FastAPI app behind a TestClient (no station, no disk but a temp dir).
2. The [pineex-supercut] block: the opt-in rule (pineEX by name; "supercut" in a preset's style or
   constraints; a plain preset gets none), the caption, the folder, the bounded road (cut -> clip book ->
   the endless set's request door -> the gallery row) with the burn faked, the cycle's cooldown respected,
   a failure that never raises, the hook in update_generation firing only for an hourly row that just
   read done, and - where the container's ffmpeg and Pillow are - one real burn of a one-second test
   picture with the caption measured at the bottom.

app.py is the first one on sys.path (PYTHONPATH=<stage>:/app:/app/tests runs this against a staged copy;
PINEEX_APP_PY names one outright). The tools live beside this file's folder (../tools).
"""
import __future__
import asyncio
import copy
import hashlib
import importlib.util
import io
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
import warnings
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"


def _app_py() -> Path:
    named = os.environ.get("PINEEX_APP_PY")
    if named:
        return Path(named)
    for entry in sys.path:
        cand = Path(entry or ".") / "app.py"
        if cand.is_file():
            return cand.resolve()
    return (HERE.parent / "app.py").resolve()


APP_PY = _app_py()
APP_TEXT = APP_PY.read_bytes().decode("utf-8").replace("\r\n", "\n").lstrip("\ufeff")
FLAGS = __future__.annotations.compiler_flag


def function_source(name: str) -> str:
    """A top-level def/class out of app.py, cut at the next top-level statement."""
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


def _exec(src: str, ns: dict) -> None:
    exec(compile(src, "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102 - the station's own code


def prompts_section() -> str:
    start = APP_TEXT.index("# --- [h3-prompts] THE HOURLY PROMPTS")
    end = APP_TEXT.index('@app.on_event("startup")\nasync def _parody_stinger_start() -> None:\n', start)
    return APP_TEXT[start:end]


def supercut_section() -> str:
    start = APP_TEXT.index("# --- [pineex-supercut] THE SUPERCUT VERSION OF AN HOURLY RENDER")
    end = APP_TEXT.index("\nasync def h3_hourly_render(", start)
    return APP_TEXT[start:end]


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KEY = "test-key"


# --------------------------------------------------------------------------------------------------
# the patch itself
class PatchApplied(unittest.TestCase):
    def test_every_edit_is_in_this_app_py(self):
        mod = _tool("pineex_supercut_patch")
        out = io.StringIO()
        held, sys.stdout = sys.stdout, out
        try:
            code = mod.main(["pineex_supercut_patch.py", "--check", str(APP_PY.parent)])
        finally:
            sys.stdout = held
        self.assertEqual(code, 2, "every edit should read applied on %s:\n%s" % (APP_PY, out.getvalue()))
        self.assertIn("h3_supercut_landed(landed)", APP_TEXT)
        self.assertIn("# --- [pineex-supercut] THE SUPERCUT VERSION OF AN HOURLY RENDER", APP_TEXT)
        self.assertIn('"supercut": row.get("supercut_version")', APP_TEXT)
        self.assertTrue(all(ord(c) < 128 for c in supercut_section()), "the block is ASCII")

    def test_the_hook_sits_after_the_row_is_written_and_outside_the_lock(self):
        src = function_source("update_generation")
        self.assertLess(src.index("GENERATIONS_PATH.write_text("), src.index("h3_supercut_landed(landed)"))
        tail = src[src.index("h3_supercut_landed(landed)") - 200:]
        self.assertIn('fields.get("status") == "done"', tail)
        # the hook line is at the function's own indent, not inside the `async with`
        line = next(l for l in src.splitlines() if "h3_supercut_landed(landed)" in l)
        self.assertEqual(len(line) - len(line.lstrip()), 8)


# --------------------------------------------------------------------------------------------------
# the [h3-prompts] doors on a real FastAPI app, for the installer
class FakeSystem3:
    def __init__(self):
        self.on = False

    def live(self):
        return self.on

    def pool(self, key, opts, label=""):
        return None

    def pick(self, key, cands, label="", weights=None, media=None):
        return None

    def last_roll(self, key):
        return None


def station(tmp: str, rows: dict | None = None) -> dict[str, Any]:
    from fastapi import FastAPI, Header, HTTPException, Request
    import comfy_workshop
    s3 = FakeSystem3()
    logs: list[str] = []

    def need_auth(authorization):
        if authorization != "Bearer " + KEY:
            raise HTTPException(401, "no key")

    ns: dict[str, Any] = {
        "__name__": "station", "DATA_DIR": Path(tmp), "RLock": threading.RLock, "Any": Any, "json": json,
        "time": time, "os": os, "re": re, "copy": copy, "uuid": uuid, "shutil": shutil, "asyncio": asyncio,
        "Path": Path, "random": random, "comfy_workshop": comfy_workshop,
        "pipeline_log": lambda lane, text, extra="": logs.append(text),
        "HTTPException": HTTPException, "Header": Header, "Request": Request, "app": FastAPI(),
        "require_auth": need_auth, "require_read_auth": need_auth,
        "workshop_generation": lambda pid: (rows or {}).get(pid),
        "_read_all_generations": lambda: list((rows or {}).values()),
        "system3_pool": s3.pool, "system3_pick": s3.pick, "system3_last_roll": s3.last_roll,
        "system3_dice_live": s3.live, "_system3": lambda: s3}
    for name in ("s3_pool", "_S3Dice", "s3_weighted", "_s3_dice_live", "_s3_sfx_rolled"):
        _exec(function_source(name), ns)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)      # the section's @app.on_event("startup")
        _exec(prompts_section(), ns)
    ns["_logs"] = logs
    return ns


class ClientDoor:
    """The installer's one door (call(method, path, body)) over a TestClient."""

    def __init__(self, client, key=KEY):
        self.client, self.key, self.calls = client, key, []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        resp = self.client.request(method, path, json=body, headers={"Authorization": "Bearer " + self.key})
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"detail": resp.text}


class Installer(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.rows = {}
        self.ns = station(self.dir, self.rows)
        self.client = TestClient(self.ns["app"])
        self.door = ClientDoor(self.client)
        self.mod = _tool("pineex_preset_install")
        self.wanted = json.loads((TOOLS.parent / "pineex_preset.json").read_text(encoding="utf-8"))

    def view(self):
        status, got = self.door.call("GET", "/api/h3/prompts")
        self.assertEqual(status, 200)
        return got

    def test_the_preset_file_is_the_operator_s_and_within_the_limits(self):
        self.assertEqual(self.wanted["name"], "pineEX")
        for field in self.mod.FIELDS:
            self.assertIn(field, self.wanted, field)
        self.assertEqual(self.mod.cuts(self.wanted, self.mod.LIMITS), [], "no field of pineEX is cut by the store")
        self.assertIn("{protagonist}", self.wanted["goal"])
        self.assertIn("Pine Box FM", self.wanted["speech"])

    def test_check_creates_nothing_apply_creates_then_it_is_in_place(self):
        out = io.StringIO()
        got = self.mod.run(self.door, self.wanted, apply=False, out=out)
        self.assertEqual((got["action"], got["done"]), ("create", False))
        self.assertIn('would create "pineEX"', out.getvalue())
        self.assertEqual([p["name"] for p in self.view()["presets"]], ["Default"], "--check changed nothing")
        self.assertEqual([c[0] for c in self.door.calls], ["GET", "GET"])

        out = io.StringIO()
        got = self.mod.run(self.door, self.wanted, apply=True, out=out)
        self.assertEqual((got["action"], got["done"]), ("create", True))
        self.assertTrue(got["saved"].startswith("p-"), got["saved"])
        self.assertIn("created \"pineEX\": id " + got["saved"], out.getvalue())
        view = self.view()
        self.assertEqual([p["name"] for p in view["presets"]], ["Default", "pineEX"])
        made = view["presets"][1]
        self.assertEqual(made["id"], got["saved"])
        for field in self.mod.FIELDS:
            self.assertEqual(made[field], self.mod.clean(self.wanted[field], field), field)
        self.assertEqual((view["active"], view["dice"], view["next"]), ("default", False, None),
                         "the active preset, the dice and the pin are untouched")
        self.assertTrue((Path(self.dir) / "h3_prompt_presets.json").exists(), "the station wrote its own store")

        out = io.StringIO()
        got = self.mod.run(self.door, self.wanted, apply=True, out=out)
        self.assertEqual((got["action"], got["done"]), ("none", False))
        self.assertIn("nothing to change", out.getvalue())
        self.assertEqual(len(self.view()["presets"]), 2, "idempotent: still one pineEX")

    def test_an_edited_preset_is_updated_and_matched_by_name_case_insensitively(self):
        got = self.mod.run(self.door, self.wanted, apply=True, out=io.StringIO())
        pid = got["saved"]
        # somebody edits it on the station: the name's case, the style, the constraints blanked
        status, _ = self.door.call("POST", "/api/h3/prompts/" + pid,
                                   {"name": "PINEex", "style": "claymation", "constraints": ""})
        self.assertEqual(status, 200)
        out = io.StringIO()
        plan = self.mod.run(self.door, self.wanted, apply=False, out=out)
        self.assertEqual((plan["action"], plan["id"]), ("update", pid))
        self.assertEqual(sorted(f for f, _o, _n in plan["diff"]), ["constraints", "name", "style"])
        self.assertIn("- claymation", out.getvalue())
        self.assertIn("+ tactile papery print textures", out.getvalue())
        got = self.mod.run(self.door, self.wanted, apply=True, out=io.StringIO())
        self.assertEqual((got["action"], got["done"], got["saved"]), ("update", True, pid))
        view = self.view()
        self.assertEqual(len(view["presets"]), 2, "updated in place, not created beside")
        after = next(p for p in view["presets"] if p["id"] == pid)
        self.assertEqual((after["name"], after["style"], after["constraints"]),
                         ("pineEX", self.wanted["style"], self.wanted["constraints"]))
        # the update carried `was`, the station's own guard against saving over a newer edit
        body = next(b for m, p, b in self.door.calls if m == "POST" and p.endswith(pid) and b and "goal" in b)
        self.assertIn("was", body)

    def test_the_limits_are_said_and_the_station_s_cut_is_accepted(self):
        long = dict(self.wanted, name="Long goal", goal="word " * 300)        # 1500 > 1200
        plan = self.mod.plan(self.view(), long)
        self.assertEqual(plan["cuts"], [("goal", 1499, 1200)])
        out = io.StringIO()
        got = self.mod.run(self.door, long, apply=True, out=out)
        self.assertIn("CUT: goal is 1499 characters, the store keeps 1200", out.getvalue())
        self.assertTrue(got["done"])
        stored = next(p for p in self.view()["presets"] if p["id"] == got["saved"])
        self.assertEqual(len(stored["goal"]), 1200)
        self.assertTrue(stored["goal"].endswith(" "), "the store cuts AFTER cleaning: a stored field can end on a space")
        again = self.mod.run(self.door, long, apply=False, out=io.StringIO())
        self.assertEqual(again["action"], "none", "the cut copy compares equal to what the store HOLDS")

    def test_a_blank_road_compares_against_the_default_s_words_and_the_kind_is_the_store_s(self):
        blank = dict(self.wanted, name="Blank roads", clip="", host="", kind="Overview please")
        got = self.mod.run(self.door, blank, apply=True, out=io.StringIO())
        stored = next(p for p in self.view()["presets"] if p["id"] == got["saved"])
        self.assertEqual(stored["clip"], self.ns["H3_PROMPTS_DEFAULT"]["clip"], "the store fills a blank road")
        self.assertEqual(stored["kind"], "overview")
        again = self.mod.run(self.door, blank, apply=False, out=io.StringIO())
        self.assertEqual(again["action"], "none", "what the store holds for a blank road is the Default's, by design")

    def test_main_exit_codes(self):
        file = Path(self.dir) / "p.json"
        file.write_text(json.dumps(self.wanted), encoding="utf-8")
        held = os.environ.pop("SPARK_AGENT_API_KEY", None)
        try:
            self.assertEqual(self.mod.main(["--check", "--file", str(file)]), 1, "no key is an error")
        finally:
            if held is not None:
                os.environ["SPARK_AGENT_API_KEY"] = held
        self.mod.Station = lambda base, key: self.door
        out = io.StringIO()
        held_out, sys.stdout = sys.stdout, out
        try:
            self.assertEqual(self.mod.main(["--check", "--file", str(file), "--key", KEY]), 3, "something to do")
            self.assertEqual(self.mod.main(["--apply", "--file", str(file), "--key", KEY]), 0)
            self.assertEqual(self.mod.main(["--check", "--file", str(file), "--key", KEY]), 0, "in place")
        finally:
            sys.stdout = held_out
        self.assertEqual([p["name"] for p in self.view()["presets"]], ["Default", "pineEX"])

    def test_the_history_lists_the_supercut_version_beside_the_hour_s_video(self):
        hour = {"hour": "h3h-abc", "at": time.time(), "marker": "2026100616", "how": "active",
                "preset": {"id": "p-1", "name": "pineEX"}, "goal": "g", "fields": {}}
        self.ns["_H3_PROMPTS_HOURS"].append(hour)
        self.rows["pid-1"] = {"prompt_id": "pid-1", "files": ["a.mp4"], "status": "done", "ts": 1,
                              "h3_prompts": {"hour": "h3h-abc", "road": "clip"},
                              "supercut_version": {"file": "pineEX-a-supercut.mp4", "folder": "pineEX"}}
        status, got = self.door.call("GET", "/api/h3/prompts/history")
        self.assertEqual(status, 200)
        videos = got["hours"][0]["videos"]
        self.assertEqual(videos[0]["supercut"]["file"], "pineEX-a-supercut.mp4")


# --------------------------------------------------------------------------------------------------
# the supercut version
def _sid(path) -> str:
    return hashlib.sha1(str(path).encode()).hexdigest()[:16]


def supercut_ns(tmp: Path) -> dict[str, Any]:
    """The block, the cycle's request door and update_generation out of app.py, over fakes."""
    logs: list[str] = []
    fired: list[Any] = []
    booked: list[tuple] = []
    cooled: set[str] = set()
    gens = tmp / "generations.jsonl"
    gens.write_text("", encoding="utf-8")

    def read_all():
        out = []
        for line in gens.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def find(name):
        for p in (tmp / "comfy").rglob("*"):
            if p.name == name and p.is_file():
                return p
        return None

    def forget(coro):
        fired.append(coro)
        coro.close()

    ns: dict[str, Any] = {
        "__name__": "station", "Any": Any, "Path": Path, "re": re, "time": time, "json": json,
        "asyncio": asyncio, "subprocess": subprocess,
        "SFX_LOCAL_ROOT": tmp / "samples", "SFX_ADS_DIR": tmp / "comfy" / "sfx_ads",
        "SFX_VIDEO_TYPES": {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"},
        "comfy_output_find": find, "_media_duration_probe": lambda p: 9.5 if Path(p).is_file() else 0.0,
        "sfx_db_write_row": lambda path, seconds, playable=1: booked.append((Path(path), seconds, playable)) or True,
        "sfx_id": _sid, "sfx_video_on_cooldown": lambda key: key in cooled, "_SFX_CYCLE": {},
        "pipeline_log": lambda lane, text, extra="": logs.append("%s: %s" % (lane, text)),
        "fire_and_forget": forget, "_sfx_ffmpeg": lambda: "",
        "_generations_lock": asyncio.Lock(), "_read_all_generations": read_all, "GENERATIONS_PATH": gens}
    _exec(function_source("sfx_cycle_request"), ns)
    _exec(function_source("update_generation"), ns)
    _exec(supercut_section(), ns)
    ns.update(_logs=logs, _fired=fired, _booked=booked, _cooled=cooled, _gens=gens)
    return ns


def pineex_row(pid="pid-1", name="pineEX", style="tactile papery print textures", constraints="Ten seconds.",
               speech="Dance all night to the record. Pine Box FM.", hourly=True, files=("h3-pid1-clip.mp4",)):
    return {"ts": 1, "prompt_id": pid, "kind": "video", "status": "queued", "files": list(files),
            "speech": speech, "hourly": hourly,
            "h3_prompts": {"hour": "h3h-1", "road": "clip", "preset": {"id": "p-1", "name": name},
                           "fields": {"style": style, "constraints": constraints},
                           "style": style, "constraints": constraints, "speech": speech, "record": "Blue Monday"}}


class SupercutRule(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = supercut_ns(self.tmp)

    def test_pineex_by_name_supercut_by_word_a_plain_preset_gets_none(self):
        wanted = self.ns["h3_supercut_wanted"]
        self.assertEqual(wanted(pineex_row()), "pineEX")
        self.assertEqual(wanted(pineex_row(name="PineEx")), "PineEx", "the name's case does not matter")
        self.assertEqual(wanted(pineex_row(name="Chefs at war", constraints="Ten seconds; a supercut version too")),
                         "Chefs at war", "any preset opts in with the word in its constraints")
        self.assertEqual(wanted(pineex_row(name="Arena battle", style="SUPERCUT energy, kinetic")), "Arena battle",
                         "...or in its style")
        self.assertEqual(wanted(pineex_row(name="Default", style="", constraints="")), "", "a plain preset gets none")
        self.assertEqual(wanted(pineex_row(hourly=False)), "", "only an hourly render")
        row = pineex_row()
        del row["h3_prompts"]
        self.assertEqual(wanted(row), "", "no preset record, no version")
        self.assertEqual(wanted(None), "")
        self.assertEqual(wanted({"hourly": True, "h3_prompts": {"preset": {"name": "pineEX"}}}), "pineEX",
                         "a record without fields still names its preset")

    def test_the_caption_is_the_three_row_brand_card(self):
        """[supercut-brand] SUPERCUT / PINEBOX FM / the station's long name (the operator, 2026-10-06);
        the product line of [pineex-caption] gave way to the card. h3_supercut_product still reads the hour."""
        caption = self.ns["h3_supercut_caption"]
        row = pineex_row()
        row["h3_prompts"]["direction"] = ('A music video. What is sold tonight is the product "Pine Box FM Vinyl Record Holder" '
                                          '- it keeps the records upright. Sing it.')
        self.assertEqual(self.ns["h3_supercut_product"](row), "Pine Box FM Vinyl Record Holder", "the product the hour sold")
        self.assertEqual(caption(row), ["SUPERCUT", "PINEBOX FM", "Pine Box FM"], "no station setting: the short name")
        self.ns["dj_settings"] = lambda: {"station_name": "Chicken Tendo Little Pine Box FM Station"}
        self.assertEqual(caption(row), ["SUPERCUT", "PINEBOX FM", "Chicken Tendo Little Pine Box FM Station"],
                         "the station setting's long name on the third row")
        self.assertEqual(caption({}), ["SUPERCUT", "PINEBOX FM", "Chicken Tendo Little Pine Box FM Station"])

    def test_the_folder_is_named_for_the_preset_under_the_writable_root(self):
        folder = self.ns["h3_supercut_folder"]
        self.assertEqual(folder("pineEX"), self.tmp / "samples" / "pineEX")
        self.assertEqual(folder("Chefs at war!"), self.tmp / "samples" / "Chefs-at-war")
        self.assertEqual(folder(""), self.tmp / "samples" / "supercut")
        self.assertEqual(folder("../x"), self.tmp / "samples" / "x", "no path tricks")


class SupercutRoad(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = supercut_ns(self.tmp)
        self.ads = self.tmp / "comfy" / "sfx_ads"
        self.ads.mkdir(parents=True)
        self.burns: list[tuple] = []

        def fake_burn(source, target, lines, exe="", brand=None):      # [supercut-brand] the plan rides along
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            self.burns.append((Path(source), Path(target), list(lines)))
            return {"path": str(target), "size": [640, 360], "lines": list(lines)}
        self.ns["h3_supercut_burn"] = fake_burn

    def land(self, row, where=None):
        (where or self.ads).mkdir(parents=True, exist_ok=True)
        for name in row["files"]:
            ((where or self.ads) / name).write_bytes(b"\x00" * 5000)
        self.ns["_gens"].write_text(json.dumps(row) + "\n", encoding="utf-8")
        return row

    def rows(self):
        return self.ns["_read_all_generations"]()

    def test_cut_booked_handed_in_and_written_on_the_row(self):
        row = self.land(pineex_row())
        made = asyncio.run(self.ns["h3_supercut_version"](row))
        self.assertIsNotNone(made)
        target = Path(made["path"])
        self.assertEqual(target.parent, self.tmp / "samples" / "pineEX", "the pineEX folder under the writable root")
        self.assertEqual(target.name, "pineEX-h3-pid1-clip-supercut.mp4")
        self.assertTrue(target.is_file())
        self.assertEqual(self.burns[0][0], self.ads / "h3-pid1-clip.mp4")
        self.assertEqual(self.burns[0][2], ["SUPERCUT", "PINEBOX FM", "Pine Box FM"])   # [supercut-brand] three rows
        # the clip book, by hand, with the measured length
        self.assertEqual(self.ns["_booked"], [(target, 9.5, 1)])
        self.assertEqual((made["booked"], made["queued"], made["seconds"], made["folder"]), (True, True, 9.5, "pineEX"))
        # the endless set's own request door: (pick, who, why)
        asked = self.ns["_SFX_CYCLE"]["requests"]
        self.assertEqual(len(asked), 1)
        self.assertEqual((asked[0][0], asked[0][1]), (target, "pineEX"))
        self.assertIn("supercut version of this hour's pineEX render", asked[0][2])
        # the gallery row remembers
        rec = self.rows()[0]
        self.assertEqual(rec["supercut_version"]["file"], target.name)
        self.assertEqual(rec["supercut_version"]["sid"], _sid(target))
        self.assertEqual(rec["supercut_version"]["source"], "h3-pid1-clip.mp4")
        self.assertTrue(any("supercut version (pineEX): pineEX-h3-pid1-clip-supercut.mp4" in l for l in self.ns["_logs"]))
        self.assertTrue(any("in the clip book" in l and "handed to the endless set" in l for l in self.ns["_logs"]))
        # once: the row has one now
        self.assertIsNone(asyncio.run(self.ns["h3_supercut_version"](self.rows()[0])))
        self.assertEqual(len(self.burns), 1)
        self.assertEqual(self.ns["_H3_SUPERCUT_BUSY"], set())

    def test_a_published_copy_on_the_ads_shelf_is_the_source_when_the_gallery_name_moved(self):
        row = pineex_row(files=("ComfyUI_00001.mp4",))
        row["aired_files"] = ["h3-pid1-ComfyUI_00001.mp4"]
        self.land(dict(row, files=row["aired_files"]))
        self.ns["_gens"].write_text(json.dumps(row) + "\n", encoding="utf-8")
        made = asyncio.run(self.ns["h3_supercut_version"](row))
        self.assertEqual(made["source"], "h3-pid1-ComfyUI_00001.mp4")

    def test_a_plain_preset_or_a_row_without_a_file_makes_nothing(self):
        row = self.land(pineex_row(name="Default", style="", constraints=""))
        self.assertIsNone(asyncio.run(self.ns["h3_supercut_version"](row)))
        self.assertEqual(self.burns, [])
        self.assertFalse((self.tmp / "samples").exists())
        row = pineex_row(pid="pid-2", files=("gone.mp4",))
        self.ns["_gens"].write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertIsNone(asyncio.run(self.ns["h3_supercut_version"](row)))
        self.assertTrue(any("has no video file to caption" in l for l in self.ns["_logs"]))
        self.assertEqual(self.burns, [])

    def test_the_cycle_s_door_keeps_its_rules_the_book_still_gets_the_clip(self):
        row = self.land(pineex_row())
        target = self.tmp / "samples" / "pineEX" / "pineEX-h3-pid1-clip-supercut.mp4"
        self.ns["_cooled"].add(_sid(target))
        made = asyncio.run(self.ns["h3_supercut_version"](row))
        self.assertEqual((made["booked"], made["queued"]), (True, False))
        self.assertEqual(self.ns["_SFX_CYCLE"].get("requests", []), [])
        self.assertEqual(self.ns["_SFX_CYCLE"]["stale"], 1)
        self.assertTrue(any("not handed to the endless set" in l for l in self.ns["_logs"]))
        # four already waiting: the door says no, the clip is still in the book
        self.ns["_cooled"].clear()
        self.ns["_SFX_CYCLE"]["requests"] = [(self.tmp / ("w%d.mp4" % i), "sfx", "") for i in range(4)]
        row2 = self.land(pineex_row(pid="pid-2", files=("h3-pid2-clip.mp4",)))
        made = asyncio.run(self.ns["h3_supercut_version"](row2))
        self.assertEqual((made["booked"], made["queued"]), (True, False))
        self.assertEqual(len(self.ns["_SFX_CYCLE"]["requests"]), 4)

    def test_a_failed_cut_never_raises_and_leaves_no_file(self):
        row = self.land(pineex_row())

        def broken(source, target, lines, exe="", brand=None):         # [supercut-brand]
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"no")
        self.ns["h3_supercut_burn"] = broken
        self.assertIsNone(asyncio.run(self.ns["h3_supercut_version"](row)))
        self.assertEqual(self.ns["_booked"], [])
        self.assertNotIn("requests", self.ns["_SFX_CYCLE"])
        self.assertNotIn("supercut_version", self.rows()[0])
        self.assertTrue(any("not made for pid-1 (CalledProcessError" in l for l in self.ns["_logs"]))
        self.assertEqual(self.ns["_H3_SUPERCUT_BUSY"], set())

    def test_the_hook_fires_only_for_an_hourly_preset_row_that_just_read_done(self):
        ns = self.ns
        rows = [pineex_row("a"), pineex_row("b", name="Default", style="", constraints=""),
                pineex_row("c", hourly=False), pineex_row("d")]
        ns["_gens"].write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        upd = ns["update_generation"]
        asyncio.run(upd("a", files=["x.mp4"], status="done", stats={}))
        self.assertEqual(len(ns["_fired"]), 1, "the pineEX row that read done")
        asyncio.run(upd("b", files=["y.mp4"], status="done"))
        asyncio.run(upd("c", files=["z.mp4"], status="done"))
        self.assertEqual(len(ns["_fired"]), 1, "a plain preset and a listener's render fire nothing")
        asyncio.run(upd("d", status="unknown"))
        asyncio.run(upd("d", stats={"x": 1}))
        self.assertEqual(len(ns["_fired"]), 1, "only a row that reads done")
        asyncio.run(upd("a", supercut_version={"file": "made.mp4"}))
        self.assertEqual(len(ns["_fired"]), 1, "writing the version itself does not fire again")
        asyncio.run(upd("a", status="done"))
        self.assertEqual(len(ns["_fired"]), 1, "a row that has its version is left alone (a restart's repair)")
        asyncio.run(upd("nope", status="done"))
        self.assertEqual(len(ns["_fired"]), 1)
        got = {r["prompt_id"]: r for r in self.rows()}
        self.assertEqual((got["a"]["status"], got["a"]["files"], got["a"]["supercut_version"]),
                         ("done", ["x.mp4"], {"file": "made.mp4"}))
        self.assertEqual(got["d"]["status"], "unknown")


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""


def _pillow():
    try:
        return importlib.import_module("PIL.Image") is not None
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_ffmpeg() and _pillow(), "the container's imageio ffmpeg and Pillow")
class RealBurn(unittest.TestCase):
    """One real cut in the container: a one-second test picture gets the caption at the bottom."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ns = supercut_ns(self.tmp)
        self.exe = _ffmpeg()
        self.source = self.tmp / "source.mp4"
        subprocess.run([self.exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                        str(self.source)], check=True, capture_output=True, timeout=60)

    def frame(self, path):
        import imageio_ffmpeg
        reader = imageio_ffmpeg.read_frames(str(path))
        meta = next(reader)
        try:
            raw = next(reader)
        finally:
            reader.close()
        w, h = meta["size"]
        return meta, bytes(raw), w, h

    def test_the_caption_lands_at_the_bottom_and_the_sound_stays(self):
        target = self.tmp / "samples" / "pineEX" / "out-supercut.mp4"
        got = self.ns["h3_supercut_burn"](self.source, target, ["Dance all night to the record", "Pine Box FM"], self.exe)
        self.assertEqual(got["size"], [320, 180])
        self.assertTrue(target.is_file())
        self.assertFalse(target.with_name("out-supercut.caption.png").exists(), "the strip is cleaned up")
        self.assertFalse(target.with_name("out-supercut.tmp.mp4").exists())
        meta, after, w, h = self.frame(target)
        self.assertEqual((w, h), (320, 180))
        self.assertTrue(meta.get("audio_codec"), "the sound came along")
        self.assertAlmostEqual(float(meta.get("duration") or 0), 1.0, delta=0.25)
        _m, before, _w, _h = self.frame(self.source)

        def band_diff(y0, y1):
            total = 0
            for y in range(y0, y1):
                a = after[y * w * 3:(y + 1) * w * 3]
                b = before[y * w * 3:(y + 1) * w * 3]
                total += sum(abs(x - z) for x, z in zip(a, b))
            return total / max(1, (y1 - y0) * w * 3)
        top, bottom = band_diff(0, h // 4), band_diff(h - h // 4, h)
        self.assertLess(top, 6.0, "the top of the picture is as it was (encoder noise only)")
        self.assertGreater(bottom, top * 4 + 3, "the card changed the bottom of the picture")   # [supercut-brand] light letters, no dark band
        # the strip itself: no wider than the picture, dark band, white ink
        strip = self.tmp / "strip.png"
        self.ns["_h3_supercut_png"](["Dance all night to the record", "Pine Box FM"], 320, 180, strip)
        from PIL import Image
        img = Image.open(strip)
        self.assertLessEqual(img.size[0], 320)
        self.assertGreater(img.size[1], 20)
        pixels = list(img.convert("RGBA").getdata())
        self.assertTrue(any(p[0] > 200 and p[3] > 200 for p in pixels), "white ink")
        self.assertTrue(any(p[3] in range(100, 200) for p in pixels), "a translucent band")


if __name__ == "__main__":
    unittest.main()
