"""[cast-names] The cast's names - Dill, Skip, Sam - fixed, custom or random.

Runs anywhere: it does NOT import app. The code under test is the text
tools/cast_names_patch.py puts into app.py, executed here against small
stand-ins for the station (its settings, System 3's dice door, the data
dir), so the rules are pinned before the patch is ever applied. The last
class runs the patch tool itself over a temporary copy of app.py (skipped
when app.py is not beside tests/). tests/test_cast_names_app.py covers the
same ground through the real app (container only)."""
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
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "cast_names_patch.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("cast_names_patch", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PATCH = load_tool()


class _App:
    def get(self, *a, **k):
        return lambda fn: fn

    post = get


class _SyncThread:
    """The keeper's write, made on the caller's thread so a test can read it."""

    def __init__(self, target=None, **_):
        self.target = target

    def start(self):
        self.target()


class Station:
    """The code the patch adds, in a namespace with stand-ins for app.py."""

    def __init__(self, dj=None, desk=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pool_calls, self.choice_calls, self.logs = [], [], []
        self.desk = dict(desk or {})       # key -> the options System 3's desk holds
        self.rng = random.Random(7)
        self.on_choice = None
        ns: dict[str, Any] = {
            "Any": Any, "re": re, "json": json, "time": time, "hashlib": hashlib,
            "random": self.rng, "RLock": threading.RLock, "Thread": _SyncThread,
            "asyncio": None, "app": _App(), "Header": lambda default=None: default,
            "Request": object, "require_auth": lambda a: None,
            "require_read_auth": lambda a: None,
            "data_path": lambda *parts: self.dir.joinpath(*parts),
            "pipeline_log": lambda kind, text, extra="": self.logs.append(text),
            "s3_pool": self.s3_pool, "s3_choice": self.s3_choice,
        }
        validators = PATCH._VALIDATORS.split("DEFAULT_DJ = {")[0]
        exec(compile(validators, "cast-validators", "exec"), ns)
        ns["DEFAULT_DJ"] = eval("{\n" + PATCH._DEFAULTS + "}", ns)
        ns["PINE_BOX_FM"] = "Pine Box FM"
        exec(compile(PATCH._DJ_SETTINGS_NEW + "    return settings\n",
                     "cast-helper", "exec"), ns)
        ns["load_settings"] = lambda: {"dj": self.stored}
        self.ns = ns
        self.stored = ns["cast_settings_clean"](dj or {})

    def s3_pool(self, key, options, label=""):
        self.pool_calls.append((key, list(options), label))
        return list(self.desk.get(key) or options)

    def s3_choice(self, key, options, label="", tabled=True):
        self.choice_calls.append((key, list(options), label, tabled))
        if self.on_choice:
            self.on_choice()
        return self.rng.choice(list(options))

    def set(self, **dj):
        self.stored = self.ns["cast_settings_clean"](dict(self.stored, **dj))
        return self.stored

    def restart(self):
        """A new process: nothing in memory, the rolls file still on disk."""
        st = self.ns["_CAST_STATE"]
        st.update(loaded=False, rolled={}, rolling=False, version=0)
        self.ns["_CAST_MEMO"].clear()
        self.ns["_CAST_OVERLAY"][0] = None

    def kept(self):
        path = self.dir / "cast_names.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def close(self):
        self.tmp.cleanup()


class NameRules(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.clean = self.s.ns["cast_name_clean"]
        self.pool = self.s.ns["cast_pool_clean"]

    def test_good_names_pass_as_written(self):
        for name in ("Dill", "Skip", "Sam", "Mary-Jo", "O'Neil", "Dr. Who",
                     "Zoë", "R2", "Bob & Ray", "x" * 30):
            self.assertEqual(self.clean(name), name, name)

    def test_whitespace_is_collapsed(self):
        self.assertEqual(self.clean("  Big   Dill \n"), "Big Dill")

    def test_names_that_would_break_something_are_refused(self):
        for bad in ("", "   ", "x" * 31, "Sam:", "{station}", "<b>Sam</b>",
                    "Sam\x07", "*Sam*", "...", "Sam|Skip", "\U0001f399 Sam", None):
            self.assertEqual(self.clean(bad), "", repr(bad))

    def test_pool_reads_commas_semicolons_and_lines_once_each(self):
        got = self.pool("Rex, moe;Gus\nrex , , {bad}, Lou")
        self.assertEqual(got, ["Rex", "moe", "Gus", "Lou"])

    def test_pool_is_capped_at_sixty(self):
        self.assertEqual(len(self.pool(["N%d" % i for i in range(99)])), 60)


class SettingsKeys(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.cast = self.s.ns["cast_settings_clean"]

    def test_defaults_are_dill_skip_sam_fixed(self):
        got = self.cast({})
        self.assertEqual((got["host_name"], got["cohost_name"], got["sfxguy_name"]),
                         ("Dill", "Skip", "Sam"))
        for role in ("host", "cohost", "sfxguy"):
            self.assertEqual(got[role + "_name_mode"], "fixed")
            self.assertEqual(got[role + "_name_pool"], list(self.s.ns["CAST_NAME_POOL"]))
        self.assertTrue(got["cast_reroll_daily"])

    def test_default_dj_carries_every_key_the_validator_writes(self):
        self.assertEqual(set(self.cast({})) - set(self.s.ns["DEFAULT_DJ"]), set())

    def test_a_name_typed_before_the_modes_is_a_custom_name(self):
        self.assertEqual(self.cast({"cohost_name": "Rex"})["cohost_name_mode"], "custom")
        self.assertEqual(self.cast({"cohost_name": "Skip"})["cohost_name_mode"], "fixed")

    def test_a_bad_mode_or_name_falls_back(self):
        got = self.cast({"host_name": "{oops}", "host_name_mode": "chaos",
                         "sfxguy_name_mode": "RANDOM", "sfxguy_name_pool": ""})
        self.assertEqual(got["host_name"], "Dill")
        self.assertEqual(got["host_name_mode"], "fixed")
        self.assertEqual(got["sfxguy_name_mode"], "random")
        self.assertEqual(got["sfxguy_name_pool"], list(self.s.ns["CAST_NAME_POOL"]))

    def test_validating_twice_changes_nothing(self):
        once = self.cast({"host_name": "Rex", "host_name_mode": "custom",
                          "cohost_name_pool": "A, B", "cast_reroll_daily": False})
        self.assertEqual(self.cast(once), once)


class Names(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.names = self.s.ns["cast_names"]
        self.name = self.s.ns["cast_name"]

    def test_fixed_is_the_station_cast(self):
        self.assertEqual(self.names(), {"host": "Dill", "cohost": "Skip", "sfxguy": "Sam"})
        self.assertEqual(self.s.choice_calls, [])

    def test_fixed_ignores_the_text_in_the_box(self):
        self.s.set(host_name="Rex", host_name_mode="fixed")
        self.assertEqual(self.name("host"), "Dill")

    def test_custom_is_the_operators_text(self):
        self.s.set(sfxguy_name="Moe", sfxguy_name_mode="custom")
        self.assertEqual(self.name("sfxguy"), "Moe")
        self.assertEqual(self.name("drop"), "Moe")        # seat words resolve too
        self.assertEqual(self.name("sfx"), "Moe")

    def test_a_dict_that_never_met_the_validator_keeps_its_names(self):
        """A caller that hands in its own DJ dict (a test, System 2's work
        copy) gets the names written in it, as it always did."""
        self.assertEqual(self.name("cohost", {"cohost_name": "Rex"}), "Rex")
        self.assertEqual(self.name("host", {"host_name": "Caine"}), "Caine")
        self.assertEqual(self.names({}), {"host": "Dill", "cohost": "Skip", "sfxguy": "Sam"})

    def test_names_never_raise(self):
        def broken():
            raise OSError("settings share down")
        self.s.ns["load_settings"] = broken
        self.assertEqual(self.names(), {"host": "Dill", "cohost": "Skip", "sfxguy": "Sam"})
        self.s.ns["load_settings"] = lambda: "not a dict"
        self.assertEqual(self.name("sfxguy"), "Sam")
        self.s.ns["load_settings"] = lambda: {"dj": ["not", "a", "dict"]}
        self.assertEqual(self.name("drop"), "Sam")
        self.s.ns["dj_settings"] = lambda: None
        self.assertEqual(self.name("third"), "")

    def test_seat_words(self):
        self.assertEqual(self.name("dj"), "Dill")
        self.assertEqual(self.name("A"), "Dill")
        self.assertEqual(self.name("B"), "Skip")
        self.assertEqual(self.name("nobody"), "")

    def test_random_rolls_through_the_dice_door_and_is_kept(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex, Moe, Gus")
        got = self.name("host")
        self.assertIn(got, ("Rex", "Moe", "Gus"))
        (key, options, label), = self.s.pool_calls
        self.assertTrue(key.startswith("cast.host."))
        self.assertEqual(options, ["Rex", "Moe", "Gus"])      # the whole pool goes on the desk
        self.assertIn("host", label)
        (ckey, _, _, tabled), = self.s.choice_calls
        self.assertEqual(ckey, key)
        self.assertFalse(tabled)                              # tabled once, by s3_pool
        kept = self.s.kept()["rolled"]["host"]
        self.assertEqual(kept["name"], got)
        self.assertEqual(kept["day"], self.s.ns["cast_day"]())

    def test_random_rolls_once_a_day(self):
        self.s.set(cohost_name_mode="random")
        first = self.name("cohost")
        for _ in range(5):
            self.assertEqual(self.name("cohost"), first)
        self.assertEqual(len(self.s.choice_calls), 1)

    def test_a_new_day_rolls_again(self):
        self.s.set(cohost_name_mode="random")
        self.name("cohost")
        tomorrow = time.time() + 86400 * 1.5
        self.s.ns["cast_day"] = lambda now=None, _t=tomorrow: time.strftime(
            "%Y-%m-%d", time.localtime(_t))
        self.name("cohost")
        self.assertEqual(len(self.s.choice_calls), 2)

    def test_the_show_day_turns_at_five_not_midnight(self):
        day = self.s.ns["cast_day"]
        at = lambda h, m: time.mktime((2026, 9, 28, h, m, 0, 0, 0, -1))
        self.assertEqual(day(at(0, 30)), "2026-09-27")        # the late show is still yesterday's
        self.assertEqual(day(at(4, 59)), "2026-09-27")
        self.assertEqual(day(at(5, 0)), "2026-09-28")
        self.assertEqual(day(at(23, 59)), "2026-09-28")

    def test_daily_off_keeps_the_name_across_days(self):
        self.s.set(cohost_name_mode="random", cast_reroll_daily=False)
        first = self.name("cohost")
        tomorrow = time.time() + 86400 * 1.5
        self.s.ns["cast_day"] = lambda now=None, _t=tomorrow: time.strftime(
            "%Y-%m-%d", time.localtime(_t))
        self.assertEqual(self.name("cohost"), first)
        self.assertEqual(len(self.s.choice_calls), 1)

    def test_a_restart_keeps_the_rolled_names(self):
        self.s.set(host_name_mode="random", sfxguy_name_mode="random")
        before = self.names()
        self.s.restart()
        self.assertEqual(self.names(), before)
        self.assertEqual(len(self.s.choice_calls), 2)          # no roll after the restart

    def test_a_pool_that_no_longer_holds_the_name_rolls_again(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex")
        self.assertEqual(self.name("host"), "Rex")
        self.s.set(host_name_pool="Moe")
        self.assertEqual(self.name("host"), "Moe")

    def test_adding_to_the_pool_keeps_the_name(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex")
        self.name("host")
        self.s.set(host_name_pool="Rex, Moe, Gus")
        self.assertEqual(self.name("host"), "Rex")
        self.assertEqual(len(self.s.choice_calls), 1)

    def test_the_cast_never_shares_a_name(self):
        for seed in range(20):
            self.s.rng.seed(seed)
            self.s.restart()
            self.s.set(host_name_mode="random", cohost_name_mode="random",
                       sfxguy_name_mode="random", host_name_pool="A, B, C",
                       cohost_name_pool="A, B, C", sfxguy_name_pool="A, B, C",
                       cast_reroll_daily=False)
            self.s.ns["_CAST_STATE"]["rolled"] = {}
            got = self.names()
            self.assertEqual(len(set(got.values())), 3, got)

    def test_a_random_name_stays_clear_of_a_custom_one(self):
        self.s.set(host_name="Rex", host_name_mode="custom",
                   cohost_name_mode="random", cohost_name_pool="Rex, Moe")
        for seed in range(10):
            self.s.rng.seed(seed)
            self.s.ns["_CAST_STATE"]["rolled"] = {}
            self.s.ns["_CAST_MEMO"].clear()
            self.assertEqual(self.name("cohost"), "Moe")

    def test_the_desk_can_hold_the_pool(self):
        """System 3's desk answers the options (POOLS1); the roll is off those."""
        self.s.set(host_name_mode="random", host_name_pool="Rex, Moe")
        pool = ["Rex", "Moe"]
        key = "cast.host." + self.s.ns["_cast_pool_sig"](pool)
        self.s.desk[key] = ["Zed"]
        self.assertEqual(self.name("host"), "Zed")
        self.assertEqual(self.name("host"), "Zed")            # kept: the pool is the same one
        self.assertEqual(len(self.s.choice_calls), 1)

    def test_dice_that_fail_still_name_him(self):
        def broken(*a, **k):
            raise RuntimeError("dice down")
        self.s.ns["s3_choice"] = broken
        self.s.set(sfxguy_name_mode="random", sfxguy_name_pool="Rex, Moe")
        self.assertIn(self.name("sfxguy"), ("Rex", "Moe"))

    def test_a_roll_that_asks_for_the_names_does_not_recurse(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex, Moe")
        seen = []
        self.s.on_choice = lambda: seen.append(self.s.ns["cast_names"]())
        got = self.name("host")
        self.assertIn(got, ("Rex", "Moe"))
        self.assertEqual(len(seen), 1)                          # it answered, it did not roll
        self.assertEqual(len(self.s.choice_calls), 1)

    def test_a_busy_lock_never_holds_the_caller(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex, Moe")
        self.s.ns["_cast_state"]()                             # loaded, as after the first ask
        lock = self.s.ns["_CAST_LOCK"]
        got = []
        held, release = threading.Event(), threading.Event()

        def hold():
            with lock:
                held.set()
                release.wait(5)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(5)
        t0 = time.time()
        got.append(self.name("host"))
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(got, ["Dill"])                       # the name before the roll
        release.set()
        t.join(5)
        self.assertIn(self.name("host"), ("Rex", "Moe"))      # and the next ask rolls


class TheButton(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)
        self.roll = self.s.ns["cast_roll_now"]

    def test_nobody_random_is_said_not_rolled(self):
        got = self.roll()
        self.assertEqual(got["rolled"], [])
        self.assertIn("random", got["said"])
        self.assertEqual(self.s.choice_calls, [])

    def test_it_gives_everybody_random_a_different_name(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex, Moe",
                   sfxguy_name_mode="random", sfxguy_name_pool="Gus, Lou")
        before = self.s.ns["cast_names"]()
        got = self.roll()
        self.assertEqual(got["rolled"], ["host", "sfxguy"])
        self.assertNotEqual(got["names"]["host"], before["host"])
        self.assertNotEqual(got["names"]["sfxguy"], before["sfxguy"])
        self.assertEqual(got["names"]["cohost"], "Skip")      # fixed stays fixed
        self.assertIn("Rolled:", got["said"])
        self.assertEqual(self.s.kept()["rolled"]["host"]["name"], got["names"]["host"])

    def test_only_the_roles_asked_for(self):
        self.s.set(host_name_mode="random", cohost_name_mode="random")
        got = self.roll(["cohost"])
        self.assertEqual(got["rolled"], ["cohost"])

    def test_state_shows_modes_pools_and_rolls(self):
        self.s.set(host_name_mode="random", host_name_pool="Rex",
                   cohost_name="Moe", cohost_name_mode="custom")
        got = self.s.ns["cast_names_state"]()
        self.assertEqual(got["names"], {"host": "Rex", "cohost": "Moe", "sfxguy": "Sam"})
        self.assertEqual(got["cast"]["host"]["mode"], "random")
        self.assertEqual(got["cast"]["host"]["pool"], ["Rex"])
        self.assertEqual(got["cast"]["host"]["rolled"]["name"], "Rex")
        self.assertEqual(got["cast"]["cohost"]["custom"], "Moe")
        self.assertEqual(got["keys"]["sfxguy"], "sfxguy_name")


class DjSettingsCarriesTheNames(unittest.TestCase):
    def setUp(self):
        self.s = Station()
        self.addCleanup(self.s.close)

    def test_same_dict_when_the_names_already_stand(self):
        self.assertIs(self.s.ns["dj_settings"](), self.s.stored)

    def test_a_copy_with_the_names_otherwise_and_the_store_untouched(self):
        self.s.set(host_name="Rex", host_name_mode="fixed",
                   sfxguy_name_mode="random", sfxguy_name_pool="Moe")
        got = self.s.ns["dj_settings"]()
        self.assertIsNot(got, self.s.stored)
        self.assertEqual((got["host_name"], got["sfxguy_name"]), ("Dill", "Moe"))
        self.assertEqual(self.s.stored["host_name"], "Rex")   # the operator's text is kept
        self.assertIs(self.s.ns["dj_settings"](), got)        # one cached copy


@unittest.skipUnless((ROOT / "app.py").exists(), "app.py is not beside tests/")
class PatchTool(unittest.TestCase):
    def test_check_apply_idempotent_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "app.py"
            shutil.copyfile(ROOT / "app.py", copy)
            run = lambda *a: subprocess.run([sys.executable, str(TOOL), str(copy), *a],
                                            capture_output=True, text=True).returncode
            self.assertIn(run(), (0, 2))
            self.assertIn(run("--apply"), (0, 2))
            self.assertEqual(run(), 2)
            self.assertEqual(run("--apply"), 2)
            text = copy.read_bytes()
            self.assertNotIn(b"\r", text)
            src = text.decode("utf-8")
            for needle in ("def cast_name(", "def cast_names_overlay(",
                           '@app.get("/api/cast/names")', '"sfxguy_name": "Sam"',
                           "**cast_settings_clean(raw_dj)", 'id="djCastRoll"'):
                self.assertEqual(src.count(needle), 1, needle)

    def test_anchors_are_unique_or_already_replaced(self):
        text = (ROOT / "app.py").read_bytes().decode("utf-8")
        for name, old, new, count in PATCH.EDITS:
            state = PATCH.state_of(text, old, new, count)
            self.assertIn(state, ("ready", "applied"), name)


if __name__ == "__main__":
    unittest.main()
