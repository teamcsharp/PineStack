"""[s3-dice4] The last station randoms that chose on-air words outside System
3's roulette roll through the dice door, and the door's pools are editable
(tools/system3_dice4_patch.py on app.py; call_scenarios.py [s3-dice4]).

"the point of making everything go on system 3 is to have no dialogue hit the
station unless it is scripted via the RNG roulette system" (operator).

Five layers, from anywhere to the container:
  AppTextTests          app.py's text: the tool is applied, no bare draw is
                        left on its roads, every list it tables is a sensible
                        editable pool (never imports app)
  LiftedHelperTests     the [s3-dice4] helpers lifted out of app.py and run
                        with the door stubbed (never imports app)
  CallScenarioTests     call_scenarios with a director: every draw is the
                        director's, at the catalog's own weights
  TablingOddsTests      System 3's runtime on a temp store: tabling a list
                        keeps today's options and today's draws, and the
                        desk's edits reach the draw (needs fastapi)
  AppDiceTests          app itself under a live runtime on a temp store
                        (imports app - run in the container; the recent book,
                        the data dir and every writer are patched)
"""
import ast
import importlib.util
import os
import random
import re
import tempfile
import typing
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_TEXT = []


def app_text():
    if not _TEXT:
        _TEXT.append((ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n"))
    return _TEXT[0]


def function_source(text, name):
    m = re.search(r"^(?:async )?def %s\(" % re.escape(name), text, re.M)
    if m is None:
        raise AssertionError("no function %s in app.py" % name)
    end = re.compile(r"^[^\s#)]", re.M).search(text, m.end())    # a ") -> ...:" line closes a signature
    return text[m.start(): end.start() if end else len(text)]


def module_const(text, name):
    """A module-level literal by name, parsed on its own (app.py is never
    parsed whole here: it is twelve megabytes)."""
    m = re.search(r"^%s(?::[^=\n]+)? = " % re.escape(name), text, re.M)
    if m is None:
        raise AssertionError("no %s in app.py" % name)
    end = re.compile(r"^[)\]}]", re.M).search(text, m.end())
    return ast.literal_eval(text[m.end(): end.end()])


def between(text, start, stop):
    a = text.index(start) + len(start)
    return text[a: text.index(stop, a)]


def door_calls(text, key):
    """The full text of every s3_choice / s3_sample call that rolls `key`
    (its first argument), found by matching brackets."""
    out = []
    for m in re.finditer(r"\bs3_(?:choice|sample)\((?:\s|#[^\n]*\n)*[\"']%s[\"']" % re.escape(key), text):
        depth, j = 1, text.index("(", m.start()) + 1
        while depth and j < len(text):
            depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(text[j], 0)
            j += 1
        out.append(text[m.start():j])
    return out


def tabled_lists(text):
    """Every list the tool puts on the desk, by the POOLS1 key it gets."""
    import sfx_reaction
    drop = module_const(text, "DROP_LINES")
    lists = {
        "call.rerun_intro": list(module_const(text, "CALL_RERUN_INTROS")),
        "sting.complaint_line": list(sfx_reaction.COMPLAINT_LINES),
        "banter.host_temper": list(module_const(text, "HOST_TEMPERS")),
        "button.suspense_format": list(module_const(text, "SUSPENSE_FORMATS")),
        "speakbox.reaction": list(module_const(text, "SPEAKBOX_REACTIONS")),
        "speakbox.engage": list(module_const(text, "SPEAKBOX_ENGAGE")),
        "speakbox.monologue_form": list(module_const(text, "SPEAKBOX_MONOLOGUE")),
        "speakbox.drop_form": list(module_const(text, "SPEAKBOX_DROPS")),
        "sfxguy.id_shelf": [ln for ln in drop if "{station}" in ln] or list(drop),
        "call.heat_jokes": list(module_const(text, "HEAT_SO_HOT")),
        "banter.stock_angle": ast.literal_eval("[" + between(
            text, 's3_pool("banter.stock_angle", [', '], "which stock angle the free round takes"))') + "]"),
        "call.flood_angle": ast.literal_eval("[" + between(
            text, 's3_unrepeated("call.flood_angle", [', '], "phonetired"') + "]"),
    }
    for band, rows in module_const(text, "HEAT_SEED").items():
        lists["banter.heat_seed_" + band.replace(" ", "_")] = list(rows)
    # tabled by the door before; a literal now (an f-string here would not parse).
    # The span carries line comments ("# [s3-dice-door]" has a bracket of its
    # own), so they go before the list is found.
    who = between(text, 's3_choice("call.callin_who",', '], "who the call-in is announced as")')
    who = "\n".join(line.split("#", 1)[0] for line in who.split("\n"))
    lists["call.callin_who"] = ast.literal_eval(who[who.index("["):] + "]")
    return lists


# the slots each tabled template may carry (filled by name, never str.format)
SLOTS = {"call.rerun_intro": {"{name}", "{premise}"}, "speakbox.monologue_form": {"{first}", "{other}"},
         "speakbox.drop_form": {"{other}"}, "sfxguy.id_shelf": {"{station}"}, "call.callin_who": {"{line}"}}


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "system3_dice4_patch", ROOT / "tools" / "system3_dice4_patch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AppTextTests(unittest.TestCase):
    def test_the_tool_is_applied(self):
        mod = load_tool()
        text = app_text()
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every [s3-dice4] edit is present exactly once")
        for marker in ("def s3_chance(", "def s3_pool(", "def s3_unrepeated(", "def s3_weighted(", "class _S3Dice:"):
            self.assertIn(marker, text, "the dice door (system3_dice_patch.py) is open")

    def test_every_anchor_is_unique_at_a_line_start(self):
        mod = load_tool()
        text = app_text()
        for name, old, new, count in mod.plan(text):
            at = text.find(new)
            self.assertGreaterEqual(at, 0, name)
            self.assertTrue(at == 0 or text[at - 1] == "\n", "%s lands mid-line" % name)
            self.assertEqual(text.count(new), 1, name)

    # function -> (the bare draws that must be gone, what it rolls now)
    CONVERTED = {
        "call_rerun_take": (["unrepeated(list(CALL_RERUN_INTROS)", '"rerun-intro").format('],
                            ['"call.rerun_intro"', "_s3_fill(s3_unrepeated("]),
        "_sting_react": (["unrepeated(list(COMPLAINT_LINES)"], ['"sting.complaint_line"']),
        "sfxguy_line": ([], ["director = _S3SfxGuyDice(warp)"]),
        "drop_liner": ([], ['s3_pool("sfxguy.id_shelf"']),
        "heat_reference": (["pool = list(HEAT_SEED.get(band"], ['s3_pool("banter.heat_seed_"']),
        "heat_joke_bank": (["pool = list(HEAT_SO_HOT)"], ['s3_pool("call.heat_jokes"']),
        "speakbox_aside": (["unrepeated(list(SPEAKBOX_"], ["'speakbox.engage'"]),
        "speakbox_scene_angle": (["unrepeated(list(SPEAKBOX_"], ["'speakbox.reaction'"]),
        "speakbox_angle": (["unrepeated(list(SPEAKBOX_", "drop.format("],
                           ['"speakbox.monologue_form"', '"speakbox.drop_form"', "'speakbox.reaction'",
                            "'speakbox.engage'", "_s3_fill(drop, first=first, other=other)"]),
        "dj_dice_api": (["unrepeated(list(SPEAKBOX_"],
                        ["if _s3_active() else", "'speakbox.reaction'", "'speakbox.engage'"]),
        "dj_banter_api": (["unrepeated(list(SUSPENSE_FORMATS)"], ['"button.suspense_format"']),
        "dj_banter": (["unrepeated(list(HOST_TEMPERS)"],
                      ['"banter.host_temper"', 's3_pool("banter.stock_angle"']),
        "caller_clock": (["angle=unrepeated(["], ['s3_unrepeated("call.flood_angle"']),
        "dj_callin": (['f"someone on {line_say}"'], ['"someone on {line}"', "who = _s3_fill(who, line=line_say)"]),
    }

    def test_no_bare_draw_is_left_on_these_roads(self):
        text = app_text()
        for fn, (gone, rolls) in self.CONVERTED.items():
            src = function_source(text, fn)
            for bare in gone:
                self.assertNotIn(bare, src, "%s still draws %r" % (fn, bare))
            for key in rolls:
                self.assertIn(key, src, "%s does not roll %s" % (fn, key))

    def test_the_callers_cold_topic_and_the_scenario_are_system3s_draws(self):
        text = app_text()
        self.assertIn("unrepeated(planted, 'caller-topic', director=_S3Dice('call.planted_topic'", text)
        self.assertNotIn("unrepeated(planted, 'caller-topic')", text)
        self.assertEqual(text.count('rng=_S3Weighted("call.scenario"'), 2,
                         "select_call_scenario and call_path_draw both take the dice")

    def test_complaint_due_is_the_door_not_the_modules_random(self):
        text = app_text()
        self.assertNotIn("from sfx_reaction import COMPLAINT_LINES, complaint_due", text)
        self.assertEqual(len(re.findall(r"^def complaint_due\(\) -> bool:", text, re.M)), 1)
        self.assertIn('s3_chance("sting.complaint", 1.0 / 3.0,', text)
        self.assertGreaterEqual(text.count("complaint_due()") - 1, 2, "both complaint roads roll it")

    def test_each_tabled_list_is_a_sensible_editable_pool(self):
        """Text rows, unique, none blank, under the desk's 200, nothing the desk
        would re-space (so the first roll's options are the station's own), and
        no brace but the slots the road fills by name."""
        for key, rows in tabled_lists(app_text()).items():
            self.assertTrue(rows, key)
            self.assertTrue(all(isinstance(r, str) for r in rows), key)
            self.assertEqual(len(rows), len(set(rows)), "%s repeats a row" % key)
            self.assertTrue(all(r.strip() for r in rows), "%s has a blank row" % key)
            self.assertLessEqual(len(rows), 200, key)
            self.assertEqual([" ".join(r.split()) for r in rows], rows, "%s would be re-spaced" % key)
            braces = {b for r in rows for b in re.findall(r"\{[^}]*\}", r)}
            self.assertLessEqual(braces, SLOTS.get(key, set()), key)
            self.assertLessEqual(len(key), 60, key)

    # Left untabled on purpose (the tool's docstring says why): switched to
    # tabled=True as the calls stand, each would break its road - one key over
    # six DJ-settings banks, a DJ-settings list shadowed, macro-state names,
    # dict keys, shape names, (label, text) pairs, a per-call filtered list.
    # Tabling the whole list and filtering after (as _cast_roll does) is not
    # a naive tabling, and passes.
    UNTABLED_ON_PURPOSE = ("line.stock_phrase", "ad.break_sponsor", "banter.interjections", "call.weather",
                           "gallery.hawk_moods", "angle.topic_shape", "angle.topic_fresh_shape",
                           "angle.topic_swerve", "call.duo_name")

    def test_the_lists_left_untabled_are_not_tabled_naively(self):
        text = app_text()
        for key in self.UNTABLED_ON_PURPOSE:
            calls = door_calls(text, key)
            self.assertTrue(calls, "%s is no longer drawn through the door" % key)
            for call in calls:
                self.assertIn("tabled=False", call, "%s is tabled as the call stands" % key)

    def test_the_new_pool_keys_are_not_already_rolled_untabled(self):
        """A key the door already draws untabled would start a POOLS1 row for a
        different list: every tabled key is either new or the draw's own key."""
        text = app_text()
        shared = {"banter.stock_angle", "call.heat_jokes", "sfxguy.id_shelf"}   # the pick's own key, same list
        for key in tabled_lists(text):
            if key in shared or key.startswith("banter.heat_seed_"):
                continue
            quoted = len(re.findall(r"[\"']%s[\"']" % re.escape(key), text))
            self.assertGreaterEqual(quoted, 1, key)
            self.assertNotRegex(text, r"s3_(choice|sample)\([\"']%s[\"'][^\n]*tabled=False" % re.escape(key))


def lifted_helpers():
    """The [s3-dice4] helper block out of app.py, run with the door stubbed."""
    text = app_text()
    start = text.index("_S3_FILL_SLOT = re.compile(")
    end = text.index("# --- Minds (#627)", start)
    calls = []

    def s3_chance(key, odds, label="", dial=""):
        calls.append(("chance", key, odds, label, dial))
        return True

    def s3_roll(key, label=""):
        calls.append(("roll", key, label))
        return 0.25

    def s3_weighted(key, labels, weights, label="", media=None):
        calls.append(("weighted", key, list(labels), list(weights), label))
        return len(labels) - 1

    class _S3Dice:
        def __init__(self, key, label="", weights=None, media=None):
            self.key, self.label = key, label

        def pick(self, _label, candidates):
            calls.append(("pick", self.key, _label, list(candidates), self.label))
            return 0

    ns = {"re": re, "Any": typing.Any, "s3_chance": s3_chance, "s3_roll": s3_roll,
          "s3_weighted": s3_weighted, "_S3Dice": _S3Dice}
    exec(compile(text[start:end], "app.py [s3-dice4]", "exec"), ns)
    return ns, calls


class LiftedHelperTests(unittest.TestCase):
    def test_fill_is_by_name_in_one_pass_and_leaves_the_operators_braces(self):
        ns, _ = lifted_helpers()
        fill = ns["_s3_fill"]
        self.assertEqual(fill("Back on the line - {name}, about {premise}.", name="Al", premise="the roof"),
                         "Back on the line - Al, about the roof.")
        self.assertEqual(fill("{first} and {other} {unknown} {not a slot}", first="A", other="B"),
                         "A and B {unknown} {not a slot}")
        self.assertEqual(fill("{name}!", name="{premise}", premise="x"), "{premise}!", "one pass")
        self.assertEqual(fill("someone on {line}", line="line 3"), "someone on line 3")
        self.assertEqual(fill("a caller", line="line 3"), "a caller")
        for tmpl in module_const(app_text(), "SPEAKBOX_DROPS") + module_const(app_text(), "SPEAKBOX_MONOLOGUE"):
            self.assertEqual(fill(tmpl, first="A", other="B"), tmpl.format(first="A", other="B"))
        for tmpl in module_const(app_text(), "CALL_RERUN_INTROS"):
            self.assertEqual(fill(tmpl, name="N", premise="P"), tmpl.format(name="N", premise="P"))

    def test_complaint_due_rolls_sting_complaint_at_one_in_three(self):
        ns, calls = lifted_helpers()
        self.assertIs(ns["complaint_due"](), True)
        self.assertEqual(calls[-1][:3], ("chance", "sting.complaint", 1.0 / 3.0))

    def test_the_weighted_source_names_each_draw(self):
        ns, calls = lifted_helpers()
        src = ns["_S3Weighted"]("call.scenario", "the call's path")
        self.assertEqual(src.draw("motive", ["a: x", "b: y"], [3, 1]), 1)
        self.assertEqual(calls[-1], ("weighted", "call.scenario.motive", ["a: x", "b: y"], [3.0, 1.0],
                                     "the call's path: motive"))
        src.draw("", ["only"], [1])
        self.assertEqual(calls[-1][1], "call.scenario")
        self.assertEqual(src.random(), 0.25)
        self.assertEqual(calls[-1], ("roll", "call.scenario", "the call's path"))

    def test_the_sfx_guys_director_rolls_only_when_there_is_something_to_say(self):
        ns, calls = lifted_helpers()
        guy = ns["_S3SfxGuyDice"](0)
        self.assertFalse(guy.takes("news", False))
        self.assertFalse(guy.takes("reaction", True), "the warp dial at 0 is off - and no roll recorded")
        self.assertEqual(calls, [])
        self.assertTrue(guy.takes("news", True))
        self.assertEqual(calls[-1][:3], ("chance", "sfxguy.news_take", 0.15))
        warm = ns["_S3SfxGuyDice"](40)
        self.assertTrue(warm.takes("reaction", True))
        self.assertEqual((calls[-1][1], calls[-1][2], calls[-1][4]), ("sfxguy.warp_take", 0.4, "sfxguy_warp"))
        self.assertFalse(warm.takes("quip", True), "a kind it does not roll is not taken")
        self.assertEqual(warm.pick("quip", ["one", "two"]), 0)
        self.assertEqual(calls[-1][:4], ("pick", "sfxguy.quip", "quip", ["one", "two"]))
        self.assertIsNone(warm.done("one", "quip"))

    def test_the_shelf_ids_escape_every_brace_but_the_station(self):
        text = app_text()
        start = text.index('    naming = [ln.replace("{", "{{")')
        end = text.index("\n", text.index("for ln in s3_pool(\"sfxguy.id_shelf\"", start)) + 1
        desk = ["{station}!", "Locked in to {station}, {nobody} knows", "a } stray { brace"]
        ns = {"naming": ["{station}!"], "s3_pool": lambda key, rows, label="": list(desk)}
        exec(compile("\n".join(l[4:] for l in text[start:end].split("\n")), "drop_liner", "exec"), ns)
        self.assertEqual([ln.format(station="Pine FM") for ln in ns["naming"]],
                         ["Pine FM!", "Locked in to Pine FM, {nobody} knows", "a } stray { brace"])


class FixedRandom:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class Director(FixedRandom):
    """A source that can make the pick itself, as the station's dice do."""

    def __init__(self, answer=0, *values):
        super().__init__(*values)
        self.answer, self.draws = answer, []

    def draw(self, what, labels, weights):
        self.draws.append((what, list(labels), list(weights)))
        return self.answer(len(labels)) if callable(self.answer) else self.answer


class CallScenarioTests(unittest.TestCase):
    def setUp(self):
        import call_scenarios
        self.cs = call_scenarios
        if "what: str" not in (ROOT / "call_scenarios.py").read_text(encoding="utf-8"):
            self.skipTest("call_scenarios.py [s3-dice4] (edit_call_scenarios.py) is not applied here")

    def catalog(self):
        return self.cs.load_scenario_catalog(ROOT / "no-such-dir" / "call_scenarios.json")   # the builtins

    def test_every_draw_is_the_directors_at_the_catalogs_weights(self):
        cat = self.catalog()
        pick = Director(answer=lambda n: n - 1)
        got = self.cs.select_call_scenario(cat, rng=pick)
        live = [row for row in cat["scenarios"] if row["enabled"]]
        self.assertEqual(got["id"], live[-1]["id"])
        what, labels, weights = pick.draws[0]
        self.assertEqual(what, "")
        self.assertEqual(weights, [row["weight"] for row in live])
        self.assertEqual(labels[0], "%s: %s" % (live[0]["id"], live[0]["premise"]))
        plan = self.cs.call_path_draw(got, caller_name="Doreen", topic="the roof", rng=pick)
        self.assertEqual([d[0] for d in pick.draws[1:]], list(self.cs.BEATS) + ["conclusion"])
        motive = [w for _, _, w in self.cs.DEFAULT_PATH_MAP["motive"]]
        self.assertEqual(pick.draws[1][2], [float(w) for w in motive])
        self.assertEqual(pick.draws[1][1][0], "explain: seek an explanation for the subject")
        self.assertEqual([b["id"] for b in plan["beats"]],
                         [self.cs.DEFAULT_PATH_MAP[b][-1][0] for b in self.cs.BEATS])
        self.assertEqual(plan["conclusion"]["id"], got["conclusion_pool"][-1]["id"])

    def test_an_answer_out_of_range_falls_back_to_the_arithmetic(self):
        cat = self.catalog()
        for bad in (-1, 99, True, None, "0"):
            pick = Director(bad, 0.0)
            live = [row for row in cat["scenarios"] if row["enabled"]]
            self.assertEqual(self.cs.select_call_scenario(cat, rng=pick)["id"], live[0]["id"], bad)

    def test_a_plain_random_source_draws_exactly_as_before(self):
        cat = self.catalog()
        seeded = [self.cs.select_call_scenario(cat, rng=random.Random(s))["id"] for s in range(40)]
        again = [self.cs.select_call_scenario(cat, rng=random.Random(s))["id"] for s in range(40)]
        self.assertEqual(seeded, again)
        low = self.cs.call_path_draw(cat["scenarios"][0], rng=FixedRandom(*([0.01] * 7)))
        self.assertEqual([b["id"] for b in low["beats"]], [self.cs.DEFAULT_PATH_MAP[b][0][0] for b in self.cs.BEATS])


def _runtime_or_skip(case):
    try:
        import system3                     # noqa: F401
        import system3_runtime             # noqa: F401
        from test_system3_runtime import FakeStation   # noqa: F401  (needs fastapi)
    except Exception as exc:  # noqa: BLE001
        case.skipTest("System 3's runtime cannot load here: %s" % exc)


class Dice:
    """System 3's dice as the station installs them - live, on a temp store."""

    def __init__(self, mode="active"):
        import system3
        import system3_runtime
        from test_system3_runtime import FakeStation
        self.s3, self.srt = system3, system3_runtime
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(FakeStation(self.tmp.name)))
        self.rt.settings = system3.normalise_settings({"mode": mode})
        self.rt.ready = True
        system3_runtime._S3_ROLLS.set(None)
        vars(system3_runtime._S3_LAST).clear()

    def door(self):
        return {"system3_chance": self.rt.chance, "system3_pool": self.rt.pool, "system3_pick": self.rt.pick,
                "system3_roll": self.rt.roll, "system3_last_roll": self.rt.last_roll,
                "system3_dice_live": self.rt._dice_live}

    def fix_stream(self, seed="dice4"):
        self.srt._S3_ROLLS.set({"seed": seed, "stream": self.s3.DrawStream("station|" + seed), "rolls": []})

    def flush(self):
        return self.srt._STORE_POOL.submit(self.rt.dice_flush).result(timeout=20)

    def pools(self):
        tab = next((t for t in self.rt.config.get("tables") or [] if t.get("id") == "POOLS1"), {})
        return {c["id"]: c for c in tab.get("categories") or []}

    def rolls(self, key):
        return [r for r in self.rt.station_view() if r["key"] == key]

    def close(self):
        self.srt._STORE_POOL.submit(lambda: None).result(timeout=20)
        self.rt.store.close()
        self.tmp.cleanup()


class TablingOddsTests(unittest.TestCase):
    def setUp(self):
        _runtime_or_skip(self)
        self.dice = Dice()
        self.addCleanup(self.dice.close)

    def draws(self, key, rows, n=60):
        """n station picks under `key` over `rows`, on a fixed stream."""
        self.dice.fix_stream()
        return [self.dice.rt.pick(key, rows, key) for _ in range(n)]

    def test_tabling_keeps_todays_options_and_todays_draws(self):
        lists = tabled_lists(app_text())
        before = {}
        for key, rows in lists.items():
            self.assertEqual(self.dice.rt.pool(key, rows, key), rows, "%s: the first roll is the station's list" % key)
            before[key] = self.draws(key, rows)
        added = self.dice.flush()
        self.assertEqual(sorted(added), sorted(lists), "every list became one POOLS1 category")
        pools = self.dice.pools()
        for key, rows in lists.items():
            cat = pools[key]
            self.assertEqual([i["text"] for i in cat["items"]], rows, key)
            self.assertEqual([i["id"] for i in cat["items"]], ["o%d" % i for i in range(len(rows))], "stable ids")
            self.assertEqual({i["weight"] for i in cat["items"]}, {1.0}, key)
            self.assertEqual(self.dice.rt.pool(key, rows, key), rows, "%s: the desk hands back the same" % key)
            self.assertEqual(self.draws(key, rows), before[key], "%s: tabling moved the draw" % key)
        self.assertEqual(self.dice.flush(), [], "a list is tabled once")

    def test_the_desks_edits_reach_the_draw(self):
        rows = tabled_lists(app_text())["banter.host_temper"]
        self.dice.rt.pool("banter.host_temper", rows, "tempers")
        self.dice.flush()
        cfg = self.dice.rt.config
        cat = self.dice.pools()["banter.host_temper"]
        cat["items"][0]["enabled"] = False
        cat["items"][1]["text"] = "sulking about the parking"
        cat["items"].append({"id": "o99", "label": "new", "text": "suspiciously cheerful", "weight": 1.0})
        self.dice.rt.config = cfg
        got = self.dice.rt.pool("banter.host_temper", rows, "tempers")
        self.assertNotIn(rows[0], got)
        self.assertIn("sulking about the parking", got)
        self.assertIn("suspiciously cheerful", got)
        for item in cat["items"]:
            item["weight"] = 0.0 if item["text"] != "suspiciously cheerful" else 1.0
        self.assertEqual({got[self.dice.rt.pick("banter.host_temper", got)] for _ in range(20)},
                         {"suspiciously cheerful"}, "the desk's weights are the draw's")


def _app_or_skip(case):
    if not (Path("/.dockerenv").exists() or os.environ.get("S3_DICE4_IMPORT_APP")):
        case.skipTest("imports app - run in the container")
    try:
        import app   # noqa: F401
    except Exception as exc:  # noqa: BLE001
        case.skipTest("app does not import here: %s" % exc)


class AppDiceTests(unittest.TestCase):
    """app itself, the door wired to a live runtime on a temp store."""

    def setUp(self):
        _app_or_skip(self)
        _runtime_or_skip(self)
        import app
        self.app = app
        self.stack = mock.patch.multiple(app, _RADIO={"recent": {}, "on": False}, _recent_load=lambda: None,
                                         _recent_save=lambda: None, _RECENT_DIRTY=[0])
        self.stack.start()
        self.addCleanup(self.stack.stop)
        self.dice = Dice()
        self.addCleanup(self.dice.close)
        door = mock.patch.dict(app.__dict__, self.dice.door())
        door.start()
        self.addCleanup(door.stop)

    def patch(self, **values):
        p = mock.patch.multiple(self.app, **values)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def run_async(coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_complaint_due_is_a_station1_roll(self):
        got = self.app.complaint_due()
        self.assertIn(got, (True, False))
        roll = self.dice.rolls("sting.complaint")[-1]
        self.assertEqual((roll["kind"], roll["odds"]), ("chance", 0.3333))
        self.assertEqual(self.dice.flush(), ["sting.complaint"])

    def test_the_speakbox_fallbacks_roll_and_table_their_pools(self):
        self.patch(_s3_active=lambda: False)
        angle = self.app.speakbox_angle({"file": "x.md", "text": "the thing itself"})
        self.assertTrue(any(r in angle for r in self.app.SPEAKBOX_REACTIONS), angle)
        self.assertTrue(any(e in angle for e in self.app.SPEAKBOX_ENGAGE), angle)
        self.assertNotIn("{other}", angle)
        for key in ("speakbox.reaction", "speakbox.engage"):
            self.assertTrue(self.dice.rolls(key), key)
        self.assertTrue(self.dice.rolls("speakbox.monologue_form") or self.dice.rolls("speakbox.drop_form"))
        added = set(self.dice.flush())
        self.assertLessEqual({"speakbox.reaction", "speakbox.engage"}, added)

    def test_the_heat_comparatives_are_a_desk_row_set(self):
        self.patch(heat_band=lambda: ("", 0.0))
        got = self.app.heat_joke_bank(4).split("; ")
        self.assertEqual(len(got), 4)
        self.assertTrue(set(got) <= set(self.app.HEAT_SO_HOT))
        self.assertEqual(len(self.dice.rolls("call.heat_jokes")), 4)
        self.assertIn("call.heat_jokes", self.dice.flush())

    def test_the_sfx_guy_without_a_plan_rolls_the_door(self):
        said = mock.Mock()
        self.patch(dj_settings=lambda: {"sfxguy_warp": 0}, crystal_active=lambda: [],
                   sfxguy_quips=lambda voice: ["one saying", "another saying"], _sfxguy_said=lambda: {},
                   _sfxguy_stamp=said, fire_and_forget=lambda coro, *a, **k: coro.close(),
                   _SFXGUY_NEWS=[], _SFXGUY_WARPED=[])
        line = self.app.sfxguy_line("guy", "context")
        self.assertIn(line, ("one saying", "another saying"))
        pick = self.dice.rolls("sfxguy.quip")[-1]
        self.assertEqual((pick["kind"], pick["picked"], pick["of"]), ("pick", line, 2))
        self.assertEqual(self.dice.rolls("sfxguy.warp_take"), [], "the warp dial at 0 is not rolled")

    def test_the_shelf_id_is_tabled_and_an_operators_brace_never_breaks_it(self):
        self.patch(_DROP_FRESH=[], fire_and_forget=lambda coro, *a, **k: coro.close(),
                   crystal_tint_two_pass=lambda: False)
        line = self.run_async(self.app.drop_liner("Pine FM"))
        self.assertIn("Pine FM", line)
        self.assertEqual(self.dice.rolls("sfxguy.id_shelf")[-1]["kind"], "pick")
        self.assertIn("sfxguy.id_shelf", self.dice.flush())
        cat = self.dice.pools()["sfxguy.id_shelf"]
        cat["items"] = [{"id": "o0", "label": "odd", "text": "{station} - {nobody} {asked", "weight": 1.0}]
        line = self.run_async(self.app.drop_liner("Pine FM"))
        self.assertEqual(line, "Pine FM - {nobody} {asked")

    def test_the_call_scenario_is_three_kinds_of_recorded_draw(self):
        cat = self.app.load_scenario_catalog(Path(self.dice.tmp.name) / "none.json")
        sc = self.app.select_call_scenario(cat, rng=self.app._S3Weighted("call.scenario", "which scenario"))
        self.assertTrue(self.dice.rolls("call.scenario"))
        self.app.call_path_draw(sc, topic="the roof", rng=self.app._S3Weighted("call.scenario", "the call's path"))
        for what in ("motive", "landing", "conclusion"):
            self.assertTrue(self.dice.rolls("call.scenario." + what), what)
        self.assertEqual(self.dice.flush(), [], "the catalog is the editor: nothing is tabled")


if __name__ == "__main__":
    unittest.main()
