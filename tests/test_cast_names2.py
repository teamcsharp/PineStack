"""[cast-names] Round two, pinned without importing app: the personas follow
the names, a caller is never a cast member, and the rename desk holds a
banked row that says a gone name, re-records just those lines with the names
changed and swaps words and takes together.

The code under test is the text tools/cast_names_patch.py and
tools/cast_names2_patch.py put into app.py, executed against stand-ins for
the station (its settings, the shelf, the pantry, the recording road,
System 3's dice). recast_desk is the real module. The director tool is run
over a copy of director.py when it sits beside tests/. The same ground
through the real app is tests/test_cast_names2_app.py (container only)."""
import asyncio
import hashlib
import importlib.util
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import recast_desk  # noqa: E402  (the real, pure bookkeeping module)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ONE = load("cast_names_patch")
TWO = load("cast_names2_patch")
MODS = load("cast_names2_modules_patch")


def _edit_new(tool, name):
    return next(new for n, old, new, count in tool.EDITS if n == name)


class _App:
    def get(self, *a, **k):
        return lambda fn: fn

    post = get


class _SyncThread:
    def __init__(self, target=None, **_):
        self.target = target

    def start(self):
        self.target()


class Station:
    """Both tools' helper blocks, with stand-ins for the rest of app.py."""

    def __init__(self, dj=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rng = random.Random(3)
        self.pantry: dict[str, dict[str, Any]] = {}
        self.larder: list[dict[str, Any]] = []
        self.shelf: dict[str, list[dict[str, Any]]] = {}
        self.rendered: list[tuple[str, str, str]] = []
        self.refuse = False
        self.logs: list[str] = []
        ns: dict[str, Any] = {
            "Any": Any, "re": re, "json": json, "time": time, "hashlib": hashlib,
            "random": self.rng, "RLock": threading.RLock, "Thread": _SyncThread,
            "asyncio": asyncio, "app": _App(), "Header": lambda default=None: default,
            "Request": object, "require_auth": lambda a: None,
            "require_read_auth": lambda a: None,
            "data_path": lambda *parts: self.dir.joinpath(*parts),
            "pipeline_log": lambda kind, text, extra="": self.logs.append(text),
            "note_action": lambda *a, **k: None,
            "s3_pool": lambda key, options, label="": list(options),
            "s3_choice": lambda key, options, label="", tabled=True: self.rng.choice(list(options)),
            "recast_desk": recast_desk,
            "dialogue_entry": self.dialogue_entry,
            "phrase_row_spoken": self.spoken,
            "_recast_piles": self.piles,
            "_recast_key_fn": self.key,
            "_recast_have_fn": lambda key: self.pantry.get(key),
            "prep_render_line": self.render,
            "render_relief": lambda: False,
            "prep_should_stop": lambda: "",
            "_recast_first_ids": lambda: set(),
            "alt_sid": lambda kind, row: str(row.get("sid") or ""),
            "_larder_save": lambda: None,
            "_pantry_save": lambda *a: None,
        }
        ns["DEFAULT_DJ"] = {}
        exec(compile(ONE._VALIDATORS.split("DEFAULT_DJ = {")[0], "one-validators", "exec"), ns)
        ns["DEFAULT_DJ"] = eval("{\n" + ONE._DEFAULTS + "}", ns)
        saved = sys.modules.get("director")
        self.director = types.ModuleType("director")
        sys.modules["director"] = self.director
        try:
            exec(compile(ONE._DJ_SETTINGS_NEW + TWO._HELPERS_NEW, "helpers", "exec"), ns)
            exec(compile(_edit_new(TWO, "cast2-caller-names"), "callers", "exec"), ns)
        finally:
            if saved is not None:
                sys.modules["director"] = saved
            else:
                sys.modules.pop("director", None)
        ns["load_settings"] = lambda: {"dj": self.stored}
        ns["CALLER_NAMES_PATH"] = self.dir / "caller_names.json"
        ns["CALLER_NAME_SEED"] = ["Big Ron", "Tammy", "Gus"]
        self.ns = ns
        raw = dict(dj or {})
        self.stored = dict(raw, **ns["cast_settings_clean"](raw))

    # --- stand-ins -------------------------------------------------------
    @staticmethod
    def dialogue_entry(row):
        if not isinstance(row, dict):
            return None
        got = row.get("entry")
        if isinstance(got, dict):
            return got
        if "script" in row and ("prep_kind" in row or "prep_turns" in row):
            return row
        return None

    @staticmethod
    def spoken(row):
        out = []
        for src in (row.get("entry") if isinstance(row.get("entry"), dict) else None, row):
            if isinstance(src, dict):
                for k in ("script", "script_plain", "text"):
                    if isinstance(src.get(k), str):
                        out.append(src[k])
        return "\n".join(out)

    @staticmethod
    def key(text, voice):
        return hashlib.sha1(("%s|%s" % (text, voice)).encode()).hexdigest() if text and voice else ""

    async def render(self, text, who, voice, kind=""):
        if self.refuse:
            return None
        key = self.key(text, voice)
        self.pantry[key] = {"text": text, "voice": voice, "seconds": 2.0}
        self.rendered.append((text, who, voice))
        return {"key": key, "voice": voice, "engine": "xtts", "seconds": 2.0}

    def piles(self):
        out = [("banter", e, e) for e in self.larder]
        for kind, rows in self.shelf.items():
            for row in rows:
                held = row.get("entry")
                out.append((kind, row, held if isinstance(held, dict) else None))
        return out

    # --- helpers ---------------------------------------------------------
    def set(self, **dj):
        merged = dict(self.stored, **dj)
        self.stored = dict(merged, **self.ns["cast_settings_clean"](merged))
        return self.stored

    def recorded(self, text, voice="xtts:vl_1"):
        key = self.key(text, voice)
        self.pantry[key] = {"text": text, "voice": voice, "seconds": 3.0}
        return key

    def shelf_round(self, kind, lines, voice="xtts:vl_1"):
        takes = []
        for i, (who, text) in enumerate(lines):
            takes.append({"i": i, "who": who, "text": text, "voice": voice,
                          "key": self.recorded(text, voice), "seconds": 3.0})
        entry = {"chunks": len(takes), "made": len(takes), "takes": takes,
                 "keys": [t["key"] for t in takes], "prep_kind": kind,
                 "script": "\n".join(("A: " if w == "dj" else "B: ") + t for w, t in lines)}
        row = {"kind": kind, "sid": "%s-%d" % (kind, len(self.shelf.get(kind, []))),
               "at": time.time(), "entry": entry}
        self.shelf.setdefault(kind, []).append(row)
        return row

    def read(self, kind, text, voice="xtts:vl_drop", **extra):
        row = {"kind": kind, "text": text, "voice": voice,
               "key": self.recorded(text, voice), "seconds": 3.0, "at": time.time(), **extra}
        self.shelf.setdefault(kind, []).append(row)
        return row

    def tick(self, budget=50):
        return asyncio.run(self.ns["cast_rename_tick"](budget=budget, force=True))

    def blocked(self, kind, row):
        return self.ns["cast_names_row_blocked"](kind, row)

    def close(self):
        self.tmp.cleanup()


class PersonasFollowTheName(unittest.TestCase):
    SKIP = "You are Skip, the co-host. Fond of the host. Skip's habits: skip the intro."

    def setUp(self):
        self.s = Station({"cohost_persona": self.SKIP, "persona": "You are Dill. You know the host well."})
        self.addCleanup(self.s.close)
        self.dj = self.s.ns["dj_settings"]

    def test_the_station_cast_changes_nothing(self):
        got = self.dj()
        self.assertIs(got, self.s.stored)
        self.assertEqual(got["cohost_persona"], self.SKIP)

    def test_a_renamed_cohost_is_named_in_his_persona_only(self):
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        got = self.dj()
        self.assertEqual(got["cohost_persona"],
                         "You are Rex, the co-host. Fond of the host. Rex's habits: skip the intro.")
        self.assertEqual(got["persona"], "You are Dill. You know the host well.")
        self.assertEqual(self.s.stored["cohost_persona"], self.SKIP)   # never rewritten
        self.assertIs(self.dj(), got)                                   # one cached copy

    def test_the_host_follows_too_and_the_owner_is_left_alone(self):
        self.s.set(host_name="Moe", host_name_mode="custom")
        got = self.dj()
        self.assertEqual(got["persona"], "You are Moe. You know the host well.")
        self.assertIn("Skip", got["cohost_persona"])                    # only the role's own

    def test_rename_text_trades_cleanly(self):
        swap = self.s.ns["cast_rename_text"]
        self.assertEqual(swap("Rex told Moe, Moe told Rex.", {"Rex": "Moe", "Moe": "Rex"}),
                         "Moe told Rex, Rex told Moe.")
        self.assertEqual(swap("Samantha and Sam", {"Sam": "Jo"}), "Samantha and Jo")
        self.assertEqual(swap("skip it, SKIP", {"Skip": "Rex"}), "skip it, SKIP")


class CallersAreNeverTheCast(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.taken = self.s.ns["cast_name_taken"]

    def test_whole_names_and_first_names(self):
        for name in ("Skip", "skip", " Sam ", "Dill", "Skip Johnson", "sam from ohio"):
            self.assertTrue(self.taken(name), name)
        for name in ("Skipper", "Samantha", "Big Ron", "", None):
            self.assertFalse(self.taken(name), name)

    def test_a_filled_third_seat_is_taken_too(self):
        self.s.ns["dj_settings"] = lambda: {"third_name": "Martha"}
        self.assertTrue(self.taken("Martha B"))

    def test_the_names_follow_the_cast(self):
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.taken("Rex"))
        self.assertFalse(self.taken("Skip"))

    def test_caller_names_leave_the_cast_out_and_the_raw_list_keeps_them(self):
        self.s.ns["CALLER_NAMES_PATH"].write_text(json.dumps(["Sam", "Tammy", "Skip Jones", "Bob"]))
        self.assertEqual(self.s.ns["caller_names"](), ["Tammy", "Bob"])
        self.assertEqual(self.s.ns["caller_names_raw"](), ["Sam", "Tammy", "Skip Jones", "Bob"])

    def test_a_dictionary_of_nothing_but_cast_falls_back_to_the_seed(self):
        self.s.ns["CALLER_NAMES_PATH"].write_text(json.dumps(["Sam", "Dill"]))
        self.assertEqual(self.s.ns["caller_names"](), ["Big Ron", "Tammy", "Gus"])


class TheRenameDesk(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)

    def test_first_sight_stamps_the_names_in_force(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, read the memo."), ("cohost", "On it.")])
        got = self.s.tick()
        self.assertEqual(got["stamped"], 1)
        self.assertEqual(row["entry"]["cast_names"], {"host": "Dill", "cohost": "Skip", "sfxguy": "Sam"})
        self.assertFalse(self.s.blocked("manager", row))

    def test_a_renamed_cohost_holds_rerecords_and_swaps(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, read the memo."),
                                              ("cohost", "On it."),
                                              ("dj", "Thanks Skip.")])
        other = self.s.shelf_round("gallery", [("dj", "What a painting."), ("cohost", "Sure is.")])
        self.s.tick()                                   # stamped under Dill/Skip/Sam
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.s.blocked("manager", row))
        self.assertFalse(self.s.blocked("gallery", other))
        why = row["entry"]["cast_stale"]
        self.assertEqual(why["map"], {"Skip": "Rex"})
        self.assertIn("Skip (Rex now)", why["why"])
        old_keys = [t["key"] for t in row["entry"]["takes"]]
        got = self.s.tick()
        self.assertEqual(got["opened"], 1)
        self.assertEqual(got["swaps"], 1)
        self.assertEqual(sorted(t for t, _w, _v in self.s.rendered),
                         ["Rex, read the memo.", "Thanks Rex."])      # just those lines
        entry = row["entry"]
        self.assertEqual([t["text"] for t in entry["takes"]],
                         ["Rex, read the memo.", "On it.", "Thanks Rex."])
        self.assertEqual(entry["takes"][1]["key"], old_keys[1])       # untouched line kept
        self.assertNotEqual(entry["takes"][0]["key"], old_keys[0])
        self.assertIn("A: Rex, read the memo.", entry["script"])
        self.assertEqual(entry["cast_names"]["cohost"], "Rex")
        self.assertNotIn("cast_stale", entry)
        self.assertNotIn("cast_rename", entry)
        self.assertEqual(set(entry["cast_rename_done"]["keys"]), {old_keys[0], old_keys[2]})
        self.assertFalse(self.s.blocked("manager", row))

    def test_held_until_the_engine_has_made_every_line(self):
        row = self.s.shelf_round("news", [("dj", "Skip has the weather."), ("cohost", "Skip here.")])
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.s.refuse = True
        got = self.s.tick()
        self.assertEqual((got["opened"], got["swaps"], got["lines"]), (1, 0, 0))
        self.assertTrue(self.s.blocked("news", row))
        self.s.refuse = False
        self.assertEqual(self.s.tick(budget=1)["lines"], 1)            # a line a pass
        self.assertTrue(self.s.blocked("news", row))
        self.assertEqual(self.s.tick(budget=1)["swaps"], 1)
        self.assertFalse(self.s.blocked("news", row))

    def test_a_read_is_renamed_too(self):
        row = self.s.read("station_id", "This is Sam on Pine Box FM.", text_plain="This is Sam on Pine Box FM.")
        self.s.tick()
        self.s.set(sfxguy_name="Gus", sfxguy_name_mode="custom")
        self.assertTrue(self.s.blocked("station_id", row))
        got = self.s.tick()
        self.assertEqual(got["swaps"], 1)
        self.assertEqual(self.s.rendered, [("This is Gus on Pine Box FM.", "drop", "xtts:vl_drop")])
        self.assertEqual((row["text"], row["text_plain"]),
                         ("This is Gus on Pine Box FM.", "This is Gus on Pine Box FM."))
        self.assertEqual(row["key"], self.s.key("This is Gus on Pine Box FM.", "xtts:vl_drop"))
        self.assertFalse(self.s.blocked("station_id", row))

    def test_a_produced_spot_is_held_and_says_why(self):
        row = self.s.read("ad", "Skip says buy now.", voice="xtts:vl_1", produced="ad-1")
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.s.blocked("ad", row))
        self.assertEqual(self.s.tick()["opened"], 0)
        self.assertIn("no road", row["cast_stale"]["why"])

    def test_names_that_go_back_release_the_row(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, you there?"), ("cohost", "Yes.")])
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.s.refuse = True
        self.s.tick()
        self.assertIn("cast_rename", row["entry"])
        self.s.set(cohost_name_mode="fixed")
        self.assertFalse(self.s.blocked("manager", row))
        self.s.tick()
        self.assertNotIn("cast_rename", row["entry"])

    def test_a_voice_that_moved_under_the_shadow_reopens_it(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, you there?"), ("cohost", "Yes.")])
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.s.refuse = True
        self.s.tick()
        row["entry"]["takes"][0]["voice"] = "xtts:vl_new"               # the recast desk swapped
        self.s.refuse = False
        self.s.tick()                   # drops the stale shadow
        self.s.tick()                   # reopens in the new voice and swaps
        take = row["entry"]["takes"][0]
        self.assertEqual((take["text"], take["voice"]), ("Rex, you there?", "xtts:vl_new"))

    def test_a_swap_drops_an_open_voice_shadow(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, you there?"), ("cohost", "Yes.")])
        self.s.tick()
        row["entry"]["recast"] = {"at": 1.0, "seats": {"dj": {"old": "a", "new": "b"}}, "takes": []}
        row["entry"]["recast_needed"] = True
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.s.tick()
        self.assertNotIn("recast", row["entry"])
        self.assertNotIn("recast_needed", row["entry"])

    def test_two_names_that_trade_places(self):
        row = self.s.shelf_round("manager", [("dj", "Rex to Moe: over."), ("cohost", "Moe to Rex: back.")])
        self.s.set(host_name="Rex", host_name_mode="custom", cohost_name="Moe", cohost_name_mode="custom")
        self.s.tick()
        self.s.set(host_name="Moe", cohost_name="Rex")
        self.s.tick()
        self.assertEqual([t["text"] for t in row["entry"]["takes"]],
                         ["Moe to Rex: over.", "Rex to Moe: back."])

    def test_a_larder_round_is_covered(self):
        entry = {"chunks": 1, "made": 1, "prep_kind": "banter", "prep_turns": 1,
                 "script": "A: Skip!",
                 "takes": [{"i": 0, "who": "dj", "text": "Skip!", "voice": "v",
                            "key": self.s.recorded("Skip!", "v"), "seconds": 1.0}]}
        self.s.larder.append(entry)
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.s.blocked("banter", entry))
        self.s.tick()
        self.assertEqual(entry["takes"][0]["text"], "Rex!")
        self.assertEqual(entry["script"], "A: Rex!")

    def test_the_state_readout(self):
        row = self.s.shelf_round("manager", [("dj", "Skip, you there?"), ("cohost", "Yes.")])
        self.s.tick()
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.s.refuse = True
        self.s.tick()
        got = self.s.ns["cast_rename_state"]()
        self.assertEqual((got["held"], got["open"], got["lines_want"], got["lines_made"]), (1, 1, 1, 0))
        self.assertEqual(got["rows"][0]["names"], {"Skip": "Rex"})
        self.assertEqual(got["rows"][0]["sid"], row["sid"])


class LineBanks(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.stale = self.s.ns["cast_names_line_stale"]

    def test_nobody_renamed_nothing_stale(self):
        self.assertFalse(self.stale({"text": "Skip, that was a bar."}))

    def test_a_gold_bar_saying_a_gone_name_is_held(self):
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.stale({"text": "Skip, that was a bar."}))
        self.assertFalse(self.stale({"text": "Rex, that was a bar."}))

    def test_the_names_book_remembers_rolled_names(self):
        self.s.set(cohost_name="Rex", cohost_name_mode="custom")
        self.assertTrue(self.s.ns["cast_history_note"]())
        self.s.set(cohost_name="Moe")
        self.s.ns["cast_history_note"]()
        self.assertTrue(self.stale({"text": "Rex, that was a bar."}))
        kept = json.loads((self.s.dir / "cast_names_history.json").read_text())
        self.assertIn("Rex", kept["seen"]["cohost"])


@unittest.skipUnless((ROOT / "director.py").exists(), "director.py is not beside tests/")
class DirectorNamesHim(unittest.TestCase):
    def test_the_sfx_beat_names_him(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "director.py"
            shutil.copyfile(ROOT / "director.py", copy)
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "tools" / "cast_names2_modules_patch.py"),
                                             str(copy), *a], capture_output=True, text=True).returncode
            self.assertIn(run(), (0, 2))
            self.assertIn(run("--apply"), (0, 2))
            self.assertEqual(run(), 2)
            spec = importlib.util.spec_from_file_location("director_copy", copy)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertEqual(mod.director_beat_words("sfx"),
                             "Sam, the SFX guy, puts something over the top of it")
            mod.CAST_NAME = lambda role: {"sfxguy": "Gus"}.get(role, "")
            self.assertTrue(mod.director_beat_words("sfx").startswith("Gus, the SFX guy"))
            mod.CAST_NAME = lambda role: 1 / 0
            self.assertTrue(mod.director_beat_words("sfx").startswith("Sam,"))


@unittest.skipUnless((ROOT / "app.py").exists(), "app.py is not beside tests/")
class PatchTools(unittest.TestCase):
    def test_both_tools_stack_and_stay_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "app.py"
            shutil.copyfile(ROOT / "app.py", copy)
            run = lambda tool, *a: subprocess.run(
                [sys.executable, str(ROOT / "tools" / tool), str(copy), *a],
                capture_output=True, text=True).returncode
            self.assertIn(run("cast_names_patch.py", "--apply"), (0, 2))
            self.assertIn(run("cast_names2_patch.py"), (0, 2))
            self.assertIn(run("cast_names2_patch.py", "--apply"), (0, 2))
            self.assertEqual(run("cast_names2_patch.py"), 2)
            self.assertEqual(run("cast_names_patch.py"), 2)     # round one still reads applied
            self.assertEqual(run("cast_names2_patch.py", "--apply"), 2)
            text = copy.read_bytes()
            self.assertNotIn(b"\r", text)
            src = text.decode("utf-8")
            for needle in ("def cast_names_row_blocked(", "async def cast_rename_tick(",
                           "await cast_rename_tick()", "def caller_names_raw(",
                           "settings = cast_personas_follow(settings)",
                           '_cast_gate = globals().get("cast_names_row_blocked")'):
                self.assertEqual(src.count(needle), 1, needle)


if __name__ == "__main__":
    unittest.main()
