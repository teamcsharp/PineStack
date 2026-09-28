"""[s3-lists2] The DJ settings' lists and the evolved heat lines are desk
lists backed by THEIR OWN stores (tools/system3_lists2_patch.py on app.py):
a desk edit writes the store the DJ-settings editor writes, so neither
overrides the other; the second caller's name is a tabled row set filtered
per call AFTER the draw; the heat director rolls the band's own POOLS1 key
so the seed rows' desk weights reach it.

"Any list to do with conversation or the roulette needs to be listed here
as an editable table" (operator, 2026-09-28).

Four layers, from anywhere to the container:
  ToolContractTests     the tool itself: three edits, check 0/2/1, apply is
                        atomic and idempotent (never imports app)
  RegistryRoundTrip     the [s3-lists2] registry block lifted out of the
                        tool and run against a REAL ListRegistry with the
                        stores stubbed: every desk door round-trips into the
                        store and the road's reader answers it (no app)
  AppTextTests          app.py's text: the tool is applied on this tree, the
                        duo draw filters AFTER the tabled pool, the heat
                        director rolls the band's key, the block sits after
                        everything it uses (never imports app)
  StationTests          app itself: the lists are registered against the
                        station's own stores; a desk write lands in
                        settings.json / heat_lines.json and the air-side
                        readers (dj_settings, _heat_read, heat_reference)
                        answer it (imports app - run in the container)
"""
import copy
import json
import re
import tempfile
import threading
import typing
import unittest
import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_TEXT: list = []

DJ_KEYS = ("intro_phrases", "station_ids", "request_phrases", "interject_phrases",
           "open_phrases", "sponsors", "diatribe_interjections")
BANDS = ("cool", "warm", "hot", "running hot", "scorching")
WHO = {"what": "the desk (test)"}


def app_text():
    if not _TEXT:
        _TEXT.append((ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n"))
    return _TEXT[0]


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "system3_lists2_patch", ROOT / "tools" / "system3_lists2_patch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


class ToolContractTests(unittest.TestCase):
    def synthetic(self, mod):
        """A tiny base that carries each anchor exactly once."""
        parts = []
        for name, old, new, count in mod.EDITS:
            self.assertEqual(count, 1, name)
            parts.append(old)
        return "# a synthetic base\n" + "\n".join(parts)

    def test_three_edits_check_0_2_1_and_an_atomic_apply(self):
        mod = load_tool()
        self.assertEqual([e[0] for e in mod.EDITS], ["registry", "duo-name", "heat-key"])
        base = self.synthetic(mod)
        self.assertEqual(mod.check(base), (0, []))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "app.py"
            target.write_bytes(base.encode("utf-8"))
            self.assertEqual(mod.apply(target), 0)
            after = target.read_bytes().decode("utf-8")
            self.assertEqual(mod.check(after), (3, []))
            self.assertIn("_s3_lists2_register()", after)
            self.assertNotIn("\r", after)
            self.assertEqual(mod.apply(target), 2, "a second apply changes nothing")
            self.assertEqual(target.read_bytes().decode("utf-8"), after)
        # an anchor edited away is MISSING, named
        broken = base.replace("banter.heat_line", "banter.heat_lines")
        applied, missing = mod.check(broken)
        self.assertEqual(applied, 0)
        self.assertTrue(any(m.startswith("heat-key") for m in missing), missing)

    def test_the_registry_block_parses_and_keeps_off_pools1(self):
        import ast
        mod = load_tool()
        ast.parse(mod.REGISTRY2)
        for key in DJ_KEYS:
            self.assertIn('"dj.%s"' % key, mod.REGISTRY2)
        self.assertIn('"heat." + key', mod.REGISTRY2)
        # backed by their OWN stores - never a POOLS1 copy
        self.assertNotIn("s3_pool(", mod.REGISTRY2)
        self.assertNotIn("POOLS1", mod.REGISTRY2.replace(
            "never copied onto POOLS1", "").replace("(POOLS1 banter.heat_seed_%s)", ""))
        # the registry edit keeps its anchor: the block lands BEFORE _sfxguy_key
        name, old, new, count = mod.EDITS[0]
        self.assertTrue(new.endswith(old), "the anchor survives at the end of the insert")

    def test_the_docstring_states_the_contract_and_what_is_not_done(self):
        doc = load_tool().__doc__
        for said in ("--check exits 0 ready / 2 applied / 1 missing", "ON THE HOST",
                     "sfxguy.id_shelf", "edit_lists2_reconcile.py",
                     "system3_dice_patch.py", "system3_dice_banter_patch.py"):
            self.assertIn(said, doc)


def lifted_registry(tmp, dj, heat, heat_max=4):
    """The [s3-lists2] block out of the tool, run against a REAL ListRegistry
    with the two stores stubbed the way app.py keeps them: the DJ settings
    document behind load_settings/save_settings, heat_lines.json on disk."""
    import system3_lists
    reg = system3_lists.ListRegistry(Path(tmp) / "edits.jsonl")
    heat_path = Path(tmp) / "heat_lines.json"
    if heat is not None:
        heat_path.write_text(heat if isinstance(heat, str) else json.dumps(heat))
    store = {"settings": {"prompts": [{"name": "a", "prompt": "b"}], "dj": copy.deepcopy(dj)},
             "saved": 0}

    def load_settings():
        return copy.deepcopy(store["settings"])   # a desk edit must go through save

    def save_settings(data):
        store["saved"] += 1
        store["settings"] = copy.deepcopy(data)
        return data

    def _heat_read():
        try:
            data = json.loads(heat_path.read_text())
            return {k: [str(x) for x in v] for k, v in data.items() if isinstance(v, list)}
        except Exception:
            return {}

    def _heat_write(data):
        heat_path.parent.mkdir(parents=True, exist_ok=True)
        heat_path.write_text(json.dumps(data, indent=1) + "\n")

    ns = {"Any": typing.Any, "json": json, "_S3_LISTS": reg,
          "_s3_list_id": system3_lists.text_id, "_s3_list_words": system3_lists.clean_words,
          "load_settings": load_settings, "save_settings": save_settings,
          "_WORD_DIAL_LOCK": threading.RLock(), "_HEAT_LOCK": threading.RLock(),
          "HEAT_LINES_PATH": heat_path, "_heat_read": _heat_read, "_heat_write": _heat_write,
          "HEAT_BANDS": ((50.0, "cool"), (62.0, "warm"), (72.0, "hot"),
                         (82.0, "running hot"), (999.0, "scorching")),
          "_HEAT_MAX_PER_BAND": heat_max}
    exec(compile(load_tool().REGISTRY2, "app.py [s3-lists2]", "exec"), ns)
    return reg, store, ns, heat_path


class RegistryRoundTrip(unittest.TestCase):
    DJ = {"intro_phrases": ["playing {title} by {by}", "here is {title}"],
          "station_ids": ["you are locked in"],
          "request_phrases": ["a request: {title}"],
          "interject_phrases": ["still going"],
          "open_phrases": ["good evening"],
          "sponsors": ["Pine Cones Cereal"],
          "diatribe_interjections": ["hang on", "no no no"]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reg, self.store, self.ns, self.heat_path = lifted_registry(
            self.tmp.name, self.DJ, {"warm": ["a1", "a2", "a3", "a4"], "cool": ["c1"]})

    def dj(self, key):
        return self.store["settings"]["dj"][key]

    def rid(self, words):
        import system3_lists
        return system3_lists.text_id(words)

    def test_the_desk_lists_their_stores_and_their_doors(self):
        got = {c["id"]: c for c in self.reg.catalog()}
        want = ["dj.%s" % k for k in DJ_KEYS] + ["heat." + b.replace(" ", "_") for b in BANDS]
        self.assertEqual([c["id"] for c in self.reg.catalog()], want)
        for lid, meta in got.items():
            self.assertEqual(meta["family"], "LIST", lid)
            self.assertEqual(meta["can"], {"add": True, "edit": True, "switch": False, "remove": True}, lid)
        self.assertEqual(got["dj.sponsors"]["store"], "data/settings.json (dj.sponsors)")
        self.assertEqual(got["heat.running_hot"]["store"], "data/heat_lines.json (running hot)")
        self.assertEqual(got["dj.diatribe_interjections"]["count"], 2)
        self.assertEqual((got["heat.warm"]["count"], got["heat.scorching"]["count"]), (4, 0))
        self.assertIn("line.stock_phrase", got["dj.intro_phrases"]["what"])
        self.assertIn("banter.interjections", got["dj.diatribe_interjections"]["what"])
        self.assertIn("ad.sponsor", got["dj.sponsors"]["what"])

    def test_a_desk_add_writes_the_store_the_editor_writes(self):
        got = self.reg.add("dj.diatribe_interjections", {"text": "  wait   wait "}, WHO)
        self.assertEqual(self.dj("diatribe_interjections"), ["hang on", "no no no", "wait wait"])
        self.assertEqual((got["id"], got["row"]["text"]), (self.rid("wait wait"), "wait wait"))
        self.assertEqual(self.store["saved"], 1, "one save, through save_settings")
        # and the DJ-settings editor's own save is what the desk shows: no copy
        self.store["settings"]["dj"]["sponsors"] = ["From The Editor"]
        self.assertEqual([r["text"] for r in self.reg.page("dj.sponsors")["rows"]], ["From The Editor"])

    def test_an_edit_moves_the_row_in_place(self):
        got = self.reg.edit("dj.intro_phrases", self.rid("playing {title} by {by}"),
                            {"text": "spinning {title}"}, WHO)
        self.assertEqual(self.dj("intro_phrases"), ["spinning {title}", "here is {title}"])
        self.assertEqual(got["id"], self.rid("spinning {title}"))

    def test_words_already_on_the_list_are_refused_and_nothing_is_written(self):
        from system3_lists import ListError
        before = list(self.dj("intro_phrases"))
        with self.assertRaises(ListError) as caught:
            self.reg.add("dj.intro_phrases", {"text": "HERE   is {title}"}, WHO)
        self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(ListError) as caught:
            self.reg.edit("dj.intro_phrases", self.rid("playing {title} by {by}"),
                          {"text": "here is {title}"}, WHO)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.dj("intro_phrases"), before)
        self.assertEqual(self.store["saved"], 0)
        self.assertTrue(any(e.get("failed") for e in self.reg.edits("dj.intro_phrases")),
                        "the refused write still left its record")

    def test_the_desk_caps_are_the_stores_own_caps(self):
        from system3_lists import ListError
        self.store["settings"]["dj"]["sponsors"] = ["s %d" % i for i in range(20)]
        with self.assertRaises(ListError) as caught:
            self.reg.add("dj.sponsors", {"text": "the twenty-first"}, WHO)
        self.assertIn("20 at most", str(caught.exception))
        self.store["settings"]["dj"]["open_phrases"] = ["o %d" % i for i in range(40)]
        with self.assertRaises(ListError) as caught:
            self.reg.add("dj.open_phrases", {"text": "the forty-first"}, WHO)
        self.assertIn("40 at most", str(caught.exception))
        with self.assertRaises(ListError):
            self.reg.add("dj.station_ids", {"text": "x" * 301}, WHO)       # dj_lines strips at 300
        with self.assertRaises(ListError):
            self.reg.add("dj.sponsors", {"text": "y" * 201}, WHO)          # sponsors at 200

    def test_the_last_row_of_a_phrase_bank_stays_but_a_sponsor_list_may_empty(self):
        from system3_lists import ListError
        with self.assertRaises(ListError) as caught:
            self.reg.remove("dj.interject_phrases", self.rid("still going"), WHO)
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("the last row stays", str(caught.exception))
        self.reg.remove("dj.sponsors", self.rid("Pine Cones Cereal"), WHO)  # fewest 0
        self.assertEqual(self.dj("sponsors"), [])

    def test_an_edit_to_no_words_is_refused_never_a_silent_removal(self):
        from system3_lists import ListError
        with self.assertRaises(ListError) as caught:
            self.reg.edit("dj.diatribe_interjections", self.rid("no no no"), {"text": ""}, WHO)
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("no words", str(caught.exception))
        self.assertEqual(self.dj("diatribe_interjections"), ["hang on", "no no no"],
                         "a cleared box removes nothing; removal is its own door")

    def test_repeated_words_are_each_reachable(self):
        from system3_lists import ListError
        self.store["settings"]["dj"]["diatribe_interjections"] = ["hang on", "hang on", "third"]
        rows = self.reg.page("dj.diatribe_interjections")["rows"]
        self.assertEqual([r["id"] for r in rows],
                         [self.rid("hang on"), self.rid("hang on") + "-2", self.rid("third")])
        with self.assertRaises(ListError):
            self.reg.edit("dj.diatribe_interjections", self.rid("hang on") + "-2", {"text": "HANG ON"}, WHO)
        self.reg.remove("dj.diatribe_interjections", self.rid("hang on") + "-2", WHO)
        self.assertEqual(self.dj("diatribe_interjections"), ["hang on", "third"])

    def test_switch_is_a_door_these_lists_do_not_have(self):
        from system3_lists import ListError
        with self.assertRaises(ListError) as caught:
            self.reg.edit("dj.sponsors", self.rid("Pine Cones Cereal"), {"on": False}, WHO)
        self.assertEqual(caught.exception.status, 405)

    def test_a_heat_add_goes_on_the_end_and_the_band_keeps_its_newest(self):
        self.reg.add("heat.warm", {"text": "a5"}, WHO)
        stored = json.loads(self.heat_path.read_text())
        self.assertEqual(stored["warm"], ["a2", "a3", "a4", "a5"], "the oldest drops, as heat_evolve does")
        self.assertEqual(stored["cool"], ["c1"], "no other band moves")
        self.assertEqual(self.ns["_heat_read"]()["warm"], ["a2", "a3", "a4", "a5"],
                         "the road's own reader answers the desk's row")

    def test_a_heat_edit_and_removal_write_the_file(self):
        self.reg.edit("heat.warm", self.rid("a2"), {"text": "a2 rewritten"}, WHO)
        self.reg.remove("heat.warm", self.rid("a4"), WHO)
        self.assertEqual(json.loads(self.heat_path.read_text())["warm"], ["a1", "a2 rewritten", "a3"])
        self.reg.remove("heat.cool", self.rid("c1"), WHO)                   # fewest 0: a band may empty
        self.assertEqual(json.loads(self.heat_path.read_text())["cool"], [])

    def test_an_unparsable_heat_file_is_refused_never_overwritten(self):
        from system3_lists import ListError
        self.heat_path.write_text("not json {{{")
        with self.assertRaises(ListError) as caught:
            self.reg.add("heat.warm", {"text": "lost"}, WHO)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.heat_path.read_text(), "not json {{{",
                         "one band written over that would drop every other band's lines")

    def test_every_desk_write_is_written_down(self):
        self.reg.add("heat.cool", {"text": "c2"}, WHO)
        self.reg.remove("heat.cool", self.rid("c2"), WHO)
        ops = [e["op"] for e in self.reg.edits("heat.cool")]
        self.assertEqual(ops, ["remove", "add"])
        self.assertEqual(self.reg.edits("heat.cool")[0]["who"], WHO)


class AppTextTests(unittest.TestCase):
    def test_the_tool_is_applied_on_this_tree(self):
        mod = load_tool()
        applied, missing = mod.check(app_text())
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.EDITS), "every [s3-lists2] edit is present exactly once")

    def duo_site(self):
        calls = door_calls(app_text(), "call.duo_name")
        self.assertEqual(len(calls), 1, "one duo-name draw")
        return calls[0]

    def run_duo(self, pool_rows, caller_name):
        expr, seen = self.duo_site(), {"pools": []}

        def s3_pool(key, options, label=""):
            seen["pools"].append((key, tuple(options), label))
            return list(pool_rows)

        def s3_choice(key, options, label, tabled=None):
            seen.update(key=key, options=list(options), tabled=tabled)
            return options[0]

        ns = {"s3_pool": s3_pool, "s3_choice": s3_choice,
              "NEW_VOICE_NAMES": ("Marlowe", "Cass", "Dex"), "caller": {"name": caller_name}}
        eval(compile(expr, "app.py duo site", "eval"), ns)
        return seen

    def test_the_whole_name_list_is_tabled_and_the_callers_name_is_filtered_after(self):
        seen = self.run_duo(["Rue", "dex", "Sal"], "DEX")
        self.assertEqual(seen["pools"][0], ("call.duo_name", ("Marlowe", "Cass", "Dex"),
                                            "the second person's name"))
        self.assertEqual(seen["options"], ["Rue", "Sal"], "never the caller's own name, case-blind")
        self.assertEqual((seen["key"], seen["tabled"]), ("call.duo_name", False),
                         "the roll stays a recorded roll; the rows live under the pool")

    def test_a_pool_of_only_the_callers_name_still_answers(self):
        seen = self.run_duo(["dex"], "Dex")
        self.assertEqual(seen["options"], ["dex"], "the filter never leaves the draw empty")
        self.assertEqual(len(seen["pools"]), 2, "the fallback re-reads the same tabled pool")

    def test_the_heat_director_rolls_the_bands_own_key(self):
        text = app_text()
        m = re.search(r"^def heat_reference\(", text, re.M)
        end = re.compile(r"^def ", re.M).search(text, m.end())
        src = text[m.start():end.start()]
        self.assertIn('director=_S3Dice("banter.heat_seed_" + band.replace(" ", "_")', src)
        self.assertIn('s3_pool("banter.heat_seed_" + band.replace(" ", "_")', src)
        self.assertNotIn('"banter.heat_line"', text, "the old un-desked key is not rolled anywhere")

    def test_the_registry_sits_after_everything_it_uses(self):
        text = app_text()
        block = text.index("_S3_DJ_LISTS = (")
        # what the block evaluates AT IMPORT must already be defined above it
        for needed in ("_S3_LISTS = _S3ListRegistry(", "HEAT_BANDS: tuple", "_HEAT_MAX_PER_BAND"):
            self.assertLess(text.index(needed), block, needed)
        # what its doors look up at call time need only exist in the module
        # (_WORD_DIAL_LOCK is defined ~55k lines below the block; every door
        # runs after import, when the whole module is bound)
        for later in ("def load_settings(", "def save_settings(", "def _heat_read(",
                      "def _heat_write(", "_WORD_DIAL_LOCK = ", "HEAT_LINES_PATH = "):
            self.assertIn(later, text, later)
        self.assertEqual(text.count("\n_WORD_DIAL_LOCK = "), 1, "one lock, one binding")
        self.assertLess(block, text.index("def _sfxguy_key("), "the block keeps its anchor below it")

    def test_the_desk_caps_match_the_stores_own_validation(self):
        text = app_text()
        mod = load_tool()
        # validate_settings: dj_lines strips to 300 chars / 40 rows, sponsors 200 / 20
        for stated in ('[:300]', '][:40]', '[:200]', '][:20]'):
            self.assertIn(stated, text)
        rows = re.findall(r'\("dj\.(\w+)", "\w+", "[^"]+", (\d+), (\d+), (\d+),', mod.REGISTRY2)
        caps = {name: (int(most), int(chars), int(fewest)) for name, most, chars, fewest in rows}
        self.assertEqual(set(caps), set(DJ_KEYS))
        for key in DJ_KEYS:
            self.assertEqual(caps[key], (20, 200, 0) if key == "sponsors" else (40, 300, 1), key)


class StationTests(unittest.TestCase):
    """The app's wiring - runs only where app.py imports (the container)."""

    @classmethod
    def setUpClass(cls):
        try:
            import app  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest("app.py imports only in the station's container: %s" % exc)

    def test_the_twelve_lists_are_registered_against_the_stations_stores(self):
        import app
        for key in DJ_KEYS:
            spec = app._S3_LISTS.spec("dj." + key)
            self.assertEqual(spec["family"], "LIST")
            self.assertIn("settings.json", spec["store"])
            self.assertIsNone(spec.get("switch"))
        for _ceiling, band in app.HEAT_BANDS:
            spec = app._S3_LISTS.spec("heat." + band.replace(" ", "_"))
            self.assertIn("heat_lines.json", spec["store"])
        self.assertEqual(len(app.HEAT_BANDS), 5)

    def desk(self, app, tmp):
        """Every write aimed at the temp stores: the settings file, the heat
        file and the desk's own edits ledger; the settings cache reset."""
        stack = [mock.patch.object(app, "SETTINGS_PATH", Path(tmp) / "settings.json"),
                 mock.patch.object(app, "HEAT_LINES_PATH", Path(tmp) / "heat_lines.json"),
                 mock.patch.object(app._S3_LISTS, "edits_path", Path(tmp) / "edits.jsonl"),
                 mock.patch.object(app, "library_settings_changed", lambda: None, create=True)]
        for patch in stack:
            patch.start()
            self.addCleanup(patch.stop)

        def cache_reset():
            app._SETTINGS_CACHE.update({"key": None, "value": None, "at": 0.0})
        cache_reset()
        self.addCleanup(cache_reset)
        app.save_settings(app.DEFAULT_SETTINGS)

    def test_dj_round_trip_desk_to_settings_to_the_air(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            self.desk(app, tmp)
            got = app._S3_LISTS.add("dj.sponsors", {"text": "Pine Cones Cereal"}, WHO)
            self.assertEqual(got["row"]["text"], "Pine Cones Cereal")
            self.assertIn("Pine Cones Cereal", app.load_settings()["dj"]["sponsors"],
                          "the desk wrote the DJ-settings document itself")
            self.assertIn("Pine Cones Cereal", app.dj_settings()["sponsors"],
                          "what the ad road reads answers the desk's row")
            # a phrase bank: dj_line's fallback bank is dj_settings()["intro_phrases"]
            first = app._S3_LISTS.page("dj.intro_phrases")["rows"][0]
            moved = app._S3_LISTS.edit("dj.intro_phrases", first["id"],
                                       {"text": "a fresh spin on {title}"}, WHO)
            self.assertEqual(moved["row"]["text"], "a fresh spin on {title}")
            self.assertIn("a fresh spin on {title}", app.dj_settings()["intro_phrases"],
                          "what line.stock_phrase draws from answers the desk's edit")
            # and the DJ-settings editor's own save is what the desk shows: no copy
            settings = app.load_settings()
            dj = dict(settings.get("dj") or {})
            dj["sponsors"] = ["From The Editor"]
            app.save_settings({**settings, "dj": dj})
            self.assertEqual([r["text"] for r in app._S3_LISTS.page("dj.sponsors")["rows"]],
                             ["From The Editor"])

    def test_heat_round_trip_desk_to_the_file_to_the_draw(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            self.desk(app, tmp)
            (Path(tmp) / "heat_lines.json").write_text(json.dumps(
                {"warm": ["w1", "w2", "w3", "w4", "w5"]}))
            app._S3_LISTS.add("heat.warm", {"text": "the desk hums like a kettle"}, WHO)
            self.assertIn("the desk hums like a kettle",
                          json.loads((Path(tmp) / "heat_lines.json").read_text())["warm"])
            self.assertIn("the desk hums like a kettle", app._heat_read()["warm"],
                          "heat_reference's own reader answers the desk's row")
            seen = {}

            def fake_pool(key, options, label=""):
                seen["pool_key"] = key
                return list(options)

            def fake_unrepeated(pool, key, director=None):
                seen.update(pool=list(pool), key=key, dice=getattr(director, "key", None))
                return pool[0]

            class Dice:
                def __init__(self, key, label="", **_kw):
                    self.key = key

            with mock.patch.object(app, "heat_band", lambda: ("warm", 55.0)), \
                    mock.patch.object(app, "s3_pool", fake_pool), \
                    mock.patch.object(app, "unrepeated", fake_unrepeated), \
                    mock.patch.object(app, "_S3Dice", Dice), \
                    mock.patch.object(app, "_RADIO", {"on": False}):
                got = app.heat_reference()
            self.assertTrue(got)
            self.assertEqual(seen["pool_key"], "banter.heat_seed_warm",
                             "the seed rows are the band's own POOLS1 row set")
            self.assertEqual(seen["dice"], "banter.heat_seed_warm",
                             "the pick is rolled under the band's key, so the desk's weights reach it")
            self.assertEqual(seen["key"], "heat-warm")
            self.assertIn("the desk hums like a kettle", seen["pool"],
                          "the desk's row is in the pool the dice pick from")

    def test_a_desk_write_never_touches_the_live_stores_in_this_test(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            self.desk(app, tmp)
            app._S3_LISTS.add("heat.cool", {"text": "cellar-cool tonight"}, WHO)
            self.assertTrue((Path(tmp) / "heat_lines.json").exists())
            self.assertTrue((Path(tmp) / "edits.jsonl").exists(),
                            "the desk's record went to the patched ledger")


if __name__ == "__main__":
    unittest.main()
