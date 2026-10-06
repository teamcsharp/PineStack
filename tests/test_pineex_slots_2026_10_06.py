"""[pineex] Wave C of the pineEX preset: {music} {product} {offer} {brand} {protagonist} {research}.

The pure phrases (h3_slots.py); the rolls, the shelves, the products store, the
protagonist's three rolls and the hourly door's route (exec'd out of app.py's own
text with stubs - no station); the products API through FastAPI's TestClient.

The app.py under test is the one beside the h3_slots module that imports first
(a stage on PYTHONPATH before /app, or /app itself), so a run against a stage
tests the stage.
"""
import __future__
import asyncio
import json
import re
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

import h3_slots  # noqa: E402
import h3_overview  # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402

ROOT = Path(h3_slots.__file__).resolve().parent
APP_TEXT = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
FLAGS = __future__.annotations.compiler_flag
NEW = ("music", "product", "offer", "brand", "protagonist", "research")


def section() -> str:
    start = APP_TEXT.index("# --- [h3-slots] THE NAMED SLOTS")
    end = APP_TEXT.index("def h3_speak_fill(template: Any", start)
    return APP_TEXT[start:end]


def routes_block() -> str:
    start = APP_TEXT.index("# --- [pineex] THE PRODUCTS API")
    end = APP_TEXT.index("# [h3-base] THE BASE PRESETS", start)
    return APP_TEXT[start:end]


class Pure(unittest.TestCase):
    def test_named_regex_labels_catalogue_know_the_six(self):
        for n in NEW:
            self.assertIn(n, h3_slots.NAMED)
            self.assertIn(n, {r["name"] for r in h3_slots.catalogue()})
        m = re.search(r'^H3_SLOT_NAMES = r"\(\?:([a-z|]+)\)', APP_TEXT, re.M)
        names = set(m.group(1).split("|"))
        for n in NEW:
            self.assertIn(n, names)
        labels = APP_TEXT[APP_TEXT.index("H3_SLOT_LABELS = {"):APP_TEXT.index("H3_SLOT_SCREEN_LABEL = ")]
        for key in ("music", "product", "offer", "brand", "protagonist_kind", "protagonist_folder",
                    "protagonist_clip", "research", "research_topic"):
            self.assertIn('"%s": "' % key, labels)
        self.assertEqual(h3_slots.tokens("{music} {product2} {offer} {brand} {brand2} {protagonist} {research}"),
                         ["music", "product2", "offer", "brand", "brand2", "protagonist", "research"])
        self.assertEqual(h3_slots.base("brand2"), "brand")
        self.assertTrue(all(e for n, s, e in h3_slots.CATALOGUE if n in NEW), "every new slot has an example")

    def test_phrases(self):
        self.assertEqual(h3_slots.music({"title": "Moonlight Drive", "artist": "The Doors"}),
                         'the record "Moonlight Drive" by The Doors')
        self.assertEqual(h3_slots.music({"path": "/music/2026-01-01_blue_lamp.mp3"}), 'the record "blue lamp"')
        self.assertEqual(h3_slots.product({"name": "Pine Cam", "pitch": "the camera on the desk."}),
                         'the product "Pine Cam" - the camera on the desk')
        self.assertEqual(h3_slots.product({"name": "Grandma's Pickles"}), 'the product "Grandma\'s Pickles"')
        self.assertEqual(h3_slots.brand("a blimp over the stadium", 'We "never" sleep'),
                         "a blimp over the stadium carrying the words \"We 'never' sleep\" in Pine Box FM livery")
        self.assertEqual(h3_slots.brand("a water tower", ""), "a water tower in Pine Box FM livery")
        self.assertEqual(h3_slots.protagonist({"kind": "clips", "name": "dog_skate_00012.mp4",
                                               "seen_desc": "a dog on a skateboard."}),
                         'the protagonist is whoever appears in the clip "dog skate", which shows a dog on a skateboard')
        self.assertEqual(h3_slots.protagonist({"kind": "clips", "name": "x.mp4", "said": "hello there"}),
                         'the protagonist is whoever appears in the clip "x", in which someone says "hello there"')
        self.assertEqual(h3_slots.protagonist({"kind": "renders", "folder": "pictures", "file": "salt_flats.png"}),
                         'the protagonist is the figure in the Pine Box gallery picture "salt flats"')
        self.assertEqual(h3_slots.protagonist({"kind": "renders", "folder": "videos", "file": "lighthouse_00001.mp4"}),
                         'the protagonist is the figure in the Pine Box gallery video "lighthouse"')
        self.assertEqual(h3_slots.research("cats on the radio", {"title": "Cats take over", "snippet": "A station in Ohio."}),
                         'what the web says about "cats on the radio": "Cats take over" - A station in Ohio')
        self.assertEqual(h3_slots.research("cats", {"title": "Cats", "snippet": "Cats"}), 'what the web says about "cats": "Cats"')
        self.assertEqual(h3_slots.clip_label({"name": "dog_skate.mp4", "seen_desc": "a dog on a skateboard"}),
                         "dog skate: a dog on a skateboard")
        feat = {"tag": "tag-x", "insertions": 4, "deletions": 1,
                "commits": [{"commit": "abc1234", "subject": "Did a thing", "at": "2026-10-01", "body": "It does a thing."}]}
        self.assertEqual(h3_slots.offer("feature", feat), h3_slots.feature(feat) + " - " + h3_slots.releaselog(feat))
        self.assertEqual(h3_slots.offer("product", {"name": "Pine Cam"}), 'the product "Pine Cam"')
        self.assertGreaterEqual(len(h3_slots.BRANDED), 12)
        self.assertTrue(any("police" in s for s in h3_slots.BRANDED) and any("spaceship" in s for s in h3_slots.BRANDED))
        self.assertEqual(h3_slots.PROTAGONIST_KINDS, ("renders", "clips"))
        self.assertEqual(h3_slots.RENDER_FOLDERS, ("pictures", "videos"))


FEATS = {"tag-x": {"tag": "tag-x", "insertions": 4, "deletions": 1,
                   "commits": [{"commit": "abc1234", "subject": "Did a thing", "at": "2026-10-01", "body": "It does a thing."}]}}


def clip_book() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.execute("CREATE TABLE clips (path TEXT PRIMARY KEY, sid TEXT, name TEXT, folder TEXT, video INTEGER, "
                "playable INTEGER, seconds REAL, seen_at REAL, seen_desc TEXT, said TEXT)")
    rows = [("/s/dogs/dog_skate.mp4", "a" * 16, "dog_skate", "dogs", 1, 1, 12.5, 100.0, "a dog on a skateboard.", ""),
            ("/s/dogs/dog_bark.mp4", "b" * 16, "dog_bark", "dogs", 1, 1, 4.0, 200.0, "", "woof woof"),
            ("/s/dogs/dog_audio.wav", "c" * 16, "dog_audio", "dogs", 0, 1, 3.0, 300.0, "", ""),
            ("/s/cats/cat_nap.mp4", "d" * 16, "cat_nap", "cats", 1, 1, 8.0, 50.0, "a cat asleep", ""),
            ("/s/gone/gone.mp4", "e" * 16, "gone", "gone", 1, 0, 8.0, 50.0, "", "")]
    con.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return con


class Rolls(unittest.TestCase):
    """The section of app.py, exec'd with stubs for everything outside it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rolls: list[tuple[str, list[str]]] = []
        self.force: dict[str, Any] = {}
        self.logs: list[str] = []
        self.notes: dict[str, Any] = {}
        self.research: dict[str, Any] = {}
        self.busy: set[str] = set()
        self.sponsors = ["Pine Box FM", "Grandma's Pickles"]

        def weighted(key, labels, weights, label="", media=None):
            self.rolls.append((key, list(labels)))
            k = self.force.get(key, 0)
            return k if isinstance(k, int) else list(labels).index(k)

        def choice(key, options, label="", tabled=True):
            self.rolls.append((key, list(options)))
            k = self.force.get(key, 0)
            return list(options)[k] if isinstance(k, int) else k

        def pool(key, options, label=""):
            self.rolls.append((key + ".pool", list(options)))
            return [o for o in options if o != self.force.get(key + ".retired")]

        def note(name, key, opts, picked):
            self.notes[name] = {"key": key, "opts": list(opts), "picked": picked}

        def roll_note(name, key, rec=None):
            self.notes[name] = {"key": key, **(rec or {})}

        async def fetch(key, query):
            self.research["asked"] = (key, query)
            self.research["store"][key] = {"at": time.time(), "key": key, "query": query,
                                           "results": list(self.research.get("results") or [])}
            self.busy.discard(key)

        self.ns = {
            "Any": Any, "asyncio": asyncio, "re": re, "time": time, "json": json, "uuid": uuid, "Path": Path,
            "RLock": RLock, "h3_slots": h3_slots, "h3_overview": h3_overview, "HTTPException": HTTPException,
            "s3_weighted": weighted, "s3_choice": choice, "s3_pool": pool, "s3_roll": lambda key, label="": 0.55,
            "pipeline_log": lambda lane, text: self.logs.append(text),
            "_H3_SLOT_MEMO": {"at": 0.0, "vals": {}}, "H3_SLOT_KEEP_S": 1800.0, "H3_SLOT_OPTS": 40,
            "_H3_HOURLY_ROLLS": self.notes, "h3_hourly_roll_note": roll_note, "_h3_slot_note": note,
            "_h3_slot_last": lambda key: {"dice": 7, "key": key},
            "_h3_slot_speakerbox": lambda: "We never sleep at Pine Box FM.",
            "data_path": lambda name: Path(self.tmp.name) / name,
            "dj_settings": lambda: {"sponsors": list(self.sponsors)},
            "music_index": lambda force=False: [{"id": "t1", "title": "Title A", "artist": "Artist A", "path": "/m/a.mp3"},
                                                {"id": "t2", "title": "Title B", "artist": "Artist B", "path": "/m/b.mp3"},
                                                {"id": "t3", "title": "Title C", "artist": "", "path": "/m/c.mp3"}],
            "read_bombshells": lambda: [{"text": "cats on the radio"}, {"topic": "the price of eggs"}],
            "sfx_db_reader": clip_book, "_SFX_DB_LOCK": RLock(),
            "settings_web_search": lambda: True, "_s3_research_key": lambda t: " ".join(re.findall(r"[a-z0-9]+", t.lower())),
            "_s3_research_load": lambda: None, "_S3_RESEARCH": {}, "_S3_RESEARCH_BUSY": self.busy,
            "S3_RESEARCH_KEEP_S": 3600.0, "_s3_research_fetch": fetch, "clean_search_query": lambda t: t,
        }
        self.research["store"] = self.ns["_S3_RESEARCH"]
        exec(compile(section(), "app.py", "exec", flags=FLAGS, dont_inherit=True), self.ns)  # noqa: S102
        self.ns["h3_feature_pool"] = lambda page=None: dict(FEATS)
        real_shelf = self.ns["h3_slot_shelf"]
        self.shelves = {"arena": ["neon_forest.png", "salt_flats.png"], "videos": ["lighthouse_00001.mp4"],
                        "gazette": [{"headline": "Cats Take Over", "deck": "Again"}, {"headline": "Eggs Up"}]}
        self.ns["h3_slot_shelf"] = lambda name: self.shelves[name] if name in self.shelves else real_shelf(name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, coro):
        return asyncio.run(coro)

    # --- the shelves ---
    def test_music_shelf_is_the_library_s_size_and_one_float_lands_on_a_record(self):
        self.assertEqual(self.ns["h3_slot_shelf"]("music"), 3)
        self.assertEqual(self.ns["h3_slot_music_row"](0.55, 3)["title"], "Title B")
        self.assertEqual(self.ns["h3_slot_music_row"](0.999, 3)["title"], "Title C")
        got = self.run_(self.ns["h3_slot_music"]("music"))
        self.assertEqual(got, 'the record "Title B" by Artist B')
        self.assertEqual(self.notes["slot_music"]["key"], "h3.slot_music")
        self.assertEqual(self.notes["slot_music"]["picked"], "Title B - Artist B")
        self.assertEqual(self.ns["h3_slot_music_sync"]("music2"), 'the record "Title B" by Artist B')
        self.ns["music_index"] = lambda force=False: []
        self.assertEqual(self.ns["h3_slot_music_sync"]("music"), "")
        self.assertTrue(any("the music library is empty" in x for x in self.logs))

    def test_products_file_is_seeded_once_and_merged_with_the_dj_s_sponsors(self):
        path = Path(self.tmp.name) / "h3_products.json"
        self.assertFalse(path.exists())
        store = self.ns["h3_products_read"]()
        self.assertTrue(path.exists(), "the first read writes the seed")
        names = [p["name"] for p in store["products"]]
        self.assertEqual(len(names), len(self.ns["H3_PRODUCTS_SEED"]))
        for want in ("Pine Box FM", "The Pine Box Gazette", "The PineTab kiosk", "Pine Cam", "MX mixtapes", "Book Time"):
            self.assertIn(want, names)
        self.assertTrue(all(p["id"] and p["pitch"] and p["added_at"] for p in store["products"]))
        self.assertTrue(any("seeded with" in x for x in self.logs))
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([p["id"] for p in on_disk["products"]], [p["id"] for p in store["products"]])
        shelf = self.ns["h3_slot_shelf"]("product")
        self.assertEqual(len(shelf), len(names) + 1, "Pine Box FM is on both lists once; the pickles join")
        extra = shelf[-1]
        self.assertEqual((extra["name"], extra["id"], extra["from"]), ("Grandma's Pickles", "dj-2", "dj.sponsors"))
        # a second read does not reseed, and a hand edit on disk is kept
        on_disk["products"].append({"id": "mine", "name": "The Night Shift", "pitch": "ours"})
        path.write_text(json.dumps(on_disk), encoding="utf-8")
        again = self.ns["h3_products_read"]()
        self.assertEqual(again["products"][-1]["name"], "The Night Shift")
        self.assertEqual(sum("seeded with" in x for x in self.logs), 1)

    def test_an_unreadable_products_file_is_left_alone(self):
        path = Path(self.tmp.name) / "h3_products.json"
        path.write_text("{not json", encoding="utf-8")
        store = self.ns["h3_products_read"]()
        self.assertEqual(len(store["products"]), len(self.ns["H3_PRODUCTS_SEED"]))
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")
        self.assertTrue(any("could not be read" in x for x in self.logs))

    def test_product_rolls_over_the_merged_shelf(self):
        self.force["h3.slot_product"] = "Grandma's Pickles"
        got = self.ns["h3_slot_named_sync"]("product")
        self.assertEqual(got, 'the product "Grandma\'s Pickles"')
        self.assertEqual(self.notes["slot_product"]["picked"], "Grandma's Pickles")
        self.assertIn("Pine Cam", self.notes["slot_product"]["opts"])
        self.force["h3.slot_product"] = "Pine Cam"
        self.assertTrue(self.ns["h3_slot_named_sync"]("product2").startswith('the product "Pine Cam" - the camera'))

    def test_clip_book_shelves(self):
        self.assertEqual(self.ns["h3_slot_clip_folders"](), ["dogs", "cats"], "folders with a playable video clip, fullest first")
        rows = self.ns["h3_slot_clip_rows"]("dogs")
        self.assertEqual([r["name"] for r in rows], ["dog_bark", "dog_skate"], "video clips only, newest indexed first")
        self.assertEqual(rows[1], {"sid": "a" * 16, "name": "dog_skate", "seconds": 12.5,
                                   "seen_desc": "a dog on a skateboard.", "said": ""})

    # --- the rolls ---
    def test_offer_rolls_a_feature_with_its_release_log(self):
        self.force["h3.slot_offer"] = "a feature"
        got = self.run_(self.ns["h3_slot_offer"]("offer"))
        self.assertEqual(got, h3_slots.feature(FEATS["tag-x"]) + " - " + h3_slots.releaselog(FEATS["tag-x"]))
        self.assertEqual(self.notes["slot_offer"], {"key": "h3.slot_offer", "opts": ["a feature", "a product"], "picked": "a feature"})
        self.assertIn("slot_feature", self.notes, "the feature's own roll is on the rolodex")
        self.assertEqual(self.ns["h3_slot_feature"]("feature"), h3_slots.feature(FEATS["tag-x"]),
                         "{feature} elsewhere in the hour is the same feature")
        self.assertEqual(self.ns["h3_slot_feature"]("releaselog"), h3_slots.releaselog(FEATS["tag-x"]))

    def test_offer_rolls_a_product(self):
        self.force["h3.slot_offer"] = "a product"
        self.force["h3.slot_product"] = "Pine Cam"
        got = self.run_(self.ns["h3_slot_offer"]("offer"))
        self.assertTrue(got.startswith('the product "Pine Cam" - '), got)
        self.assertEqual(self.notes["slot_offer"]["picked"], "a product")
        self.assertEqual(self.notes["slot_offer_product"]["key"], "h3.slot_product")
        self.assertEqual(self.notes["slot_offer_product"]["picked"], "Pine Cam")
        self.assertNotIn("slot_feature", self.notes)
        # the sync road, and a feature road with an empty release log falls to a product
        self.assertTrue(self.ns["h3_slot_offer_sync"]("offer2").startswith('the product "Pine Cam"'))
        self.force["h3.slot_offer"] = "a feature"
        self.ns["h3_feature_pool"] = lambda page=None: {}
        self.ns["_CHANGELOG"] = type("C", (), {"page": staticmethod(lambda n: {"entries": []})})()
        self.assertTrue(self.run_(self.ns["h3_slot_offer"]("offer3")).startswith('the product "Pine Cam"'))
        self.assertTrue(any("release log has none - a product instead" in x for x in self.logs))

    def test_brand_rolls_a_surface_from_the_tabled_pool_with_the_hour_s_speakerbox_words(self):
        retired = h3_slots.BRANDED[0]
        self.force["h3.slot_brand.retired"] = retired
        got = self.ns["h3_slot_brand"]("brand")
        self.assertEqual(got, '%s carrying the words "We never sleep at Pine Box FM." in Pine Box FM livery' % h3_slots.BRANDED[1])
        self.assertNotIn(retired, self.notes["slot_brand"]["opts"], "a retired surface is never offered")
        self.assertEqual(self.notes["slot_brand"]["picked"], h3_slots.BRANDED[1])
        self.assertEqual(self.ns["_H3_SLOT_MEMO"]["vals"]["speakerbox"], "We never sleep at Pine Box FM.")
        self.force["h3.slot_brand"] = 3
        got2 = self.ns["h3_slot_brand"]("brand2")
        self.assertIn('carrying the words "We never sleep at Pine Box FM."', got2, "the sentence is shared")
        self.assertNotEqual(got.split(" carrying")[0], got2.split(" carrying")[0], "each digit its own surface")
        self.assertIn("slot_brand2", self.notes)
        # the whole pool when the desk's pool answers nothing usable
        self.ns["s3_pool"] = lambda key, options, label="": ["not a surface"]
        self.force["h3.slot_brand"] = 0
        self.assertTrue(self.ns["h3_slot_brand"]("brand3").startswith(h3_slots.BRANDED[0]))

    def test_topic_is_rolled_once_and_kept(self):
        self.force["h3.plot_topic"] = "the price of eggs"
        self.assertEqual(self.ns["h3_slot_topic"](), "the price of eggs")
        self.assertEqual(self.notes["slot_topic"]["key"], "h3.plot_topic")
        self.force["h3.plot_topic"] = "cats on the radio"
        self.assertEqual(self.ns["h3_slot_topic"](), "the price of eggs", "kept for the hour")
        self.assertEqual(sum(1 for k, _ in self.rolls if k == "h3.plot_topic"), 1)

    def test_protagonist_three_rolls_clips(self):
        self.force["h3.slot_protagonist_kind"] = "clips"
        self.force["h3.slot_protagonist_folder"] = "dogs"
        self.force["h3.slot_protagonist_clip"] = 1
        got = self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        self.assertEqual(got, 'the protagonist is whoever appears in the clip "dog skate", which shows a dog on a skateboard')
        keys = [k for k, _ in self.rolls]
        self.assertEqual(keys, ["h3.slot_protagonist_kind", "h3.slot_protagonist_folder", "h3.slot_protagonist_clip"])
        self.assertEqual(self.notes["slot_protagonist_kind"], {"key": "h3.slot_protagonist_kind", "opts": ["renders", "clips"], "picked": "clips"})
        self.assertEqual(self.notes["slot_protagonist_folder"]["opts"], ["dogs", "cats"])
        self.assertEqual(self.notes["slot_protagonist_clip"]["opts"], ["dog bark: woof woof", "dog skate: a dog on a skateboard."])
        self.assertEqual(self.notes["slot_protagonist_clip"]["picked"], "dog skate: a dog on a skateboard.")
        star = self.ns["_H3_SLOT_MEMO"]["protagonist"]
        self.assertEqual({k: star[k] for k in ("kind", "folder", "sid", "name", "seconds")},
                         {"kind": "clips", "folder": "dogs", "sid": "a" * 16, "name": "dog_skate", "seconds": 12.5})
        self.assertEqual(star["words"], got)
        self.assertEqual(self.ns["_H3_SLOT_MEMO"]["protagonist_at"], self.ns["_H3_SLOT_MEMO"]["at"])

    def test_protagonist_three_rolls_renders(self):
        self.force["h3.slot_protagonist_kind"] = "renders"
        self.force["h3.slot_protagonist_folder"] = "pictures"
        self.force["h3.slot_protagonist_clip"] = "salt flats"
        got = self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        self.assertEqual(got, 'the protagonist is the figure in the Pine Box gallery picture "salt flats"')
        self.assertEqual(self.notes["slot_protagonist_folder"]["opts"], ["pictures", "videos"])
        self.assertEqual(self.notes["slot_protagonist_clip"]["opts"], ["neon forest", "salt flats"])
        star = self.ns["_H3_SLOT_MEMO"]["protagonist"]
        self.assertEqual((star["kind"], star["folder"], star["file"]), ("renders", "pictures", "salt_flats.png"))
        self.force["h3.slot_protagonist_folder"] = "videos"
        self.force["h3.slot_protagonist_clip"] = 0
        got = self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        self.assertEqual(got, 'the protagonist is the figure in the Pine Box gallery video "lighthouse"')
        self.assertEqual(self.ns["_H3_SLOT_MEMO"]["protagonist"]["file"], "lighthouse_00001.mp4")
        # no pictures on the wall: the videos, and the log says so
        self.shelves["arena"] = []
        self.force["h3.slot_protagonist_folder"] = "pictures"
        got = self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        self.assertIn('video "lighthouse"', got)
        self.assertTrue(any("rolled the gallery pictures but there are none" in x for x in self.logs))
        # nothing anywhere: taken out, no protagonist on the memo
        self.shelves["videos"] = []
        self.assertEqual(self.run_(self.ns["h3_slot_protagonist"]("protagonist")), "")
        self.assertNotIn("protagonist", self.ns["_H3_SLOT_MEMO"])

    def test_protagonist_clips_with_an_empty_book_falls_to_the_renders(self):
        self.force["h3.slot_protagonist_kind"] = "clips"
        empty = sqlite3.connect(":memory:", check_same_thread=False)
        empty.execute("CREATE TABLE clips (path TEXT, sid TEXT, name TEXT, folder TEXT, video INTEGER, playable INTEGER, seconds REAL, seen_at REAL)")
        self.ns["sfx_db_reader"] = lambda: empty
        got = self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        self.assertIn("Pine Box gallery picture", got)
        self.assertTrue(any("book has no playable video clip - the renders instead" in x for x in self.logs))

    def test_the_door_s_only_slots_are_taken_out_elsewhere(self):
        for tok in ("protagonist", "research", "convograph"):
            self.assertEqual(self.ns["h3_slot_named_sync"](tok), "")
        self.assertEqual(sum("rolled by the hourly door only" in x for x in self.logs), 3)

    def test_preroll_fills_the_memo_with_all_six(self):
        self.force["h3.slot_offer"] = "a product"
        self.force["h3.slot_protagonist_kind"] = "clips"
        self.research["results"] = [{"n": 1, "title": "Cats take over", "snippet": "A station in Ohio.", "verdict": "used"}]
        text = "{music}. {product}. {offer}. {brand} and {brand2}. {protagonist}. {research}. {topic}"
        done = self.run_(self.ns["h3_slots_preroll"](text))
        self.assertEqual(set(done), {"music", "product", "offer", "brand", "brand2", "protagonist", "research"})
        vals = self.ns["_H3_SLOT_MEMO"]["vals"]
        for tok in done:
            self.assertTrue(vals[tok], tok)
        self.assertIn('the record "Title B"', vals["music"])
        self.assertIn("the protagonist is whoever appears in the clip", vals["protagonist"])
        self.assertIn('what the web says about "cats on the radio"', vals["research"])
        self.assertEqual(vals["topic"], "cats on the radio", "the topic rolled for the research is the hour's {topic}")
        self.assertTrue(any("{music} rolled - " in x for x in self.logs))
        self.assertEqual(vals["brand"].split(" carrying")[1], vals["brand2"].split(" carrying")[1], "one sentence, two surfaces")

    # --- the research ---
    def test_research_rolls_a_judged_result_about_the_hour_s_topic(self):
        self.research["results"] = [
            {"n": 1, "title": "Never this", "snippet": "no", "verdict": "refused"},
            {"n": 2, "title": "Cats take over", "snippet": "A station in Ohio.", "verdict": "used"},
            {"n": 3, "title": "", "snippet": "", "verdict": "empty"},
            {"n": 4, "title": "Spare one", "snippet": "Kept aside.", "verdict": "spare"}]
        self.force["h3.slot_research"] = "Spare one"
        got = self.run_(self.ns["h3_slot_research"]("research"))
        self.assertEqual(got, 'what the web says about "cats on the radio": "Spare one" - Kept aside')
        self.assertEqual(self.research["asked"], ("cats on the radio", "cats on the radio"))
        self.assertEqual(self.notes["slot_research"]["opts"], ["Cats take over", "Spare one"], "refused and empty never offered")
        self.assertEqual(self.ns["_H3_SLOT_MEMO"]["vals"]["topic"], "cats on the radio")
        self.assertNotIn("cats on the radio", self.busy)
        # a kept search is not searched again
        self.research["asked"] = None
        self.force["h3.slot_research"] = 0
        self.assertEqual(self.run_(self.ns["h3_slot_research"]("research2")),
                         'what the web says about "cats on the radio": "Cats take over" - A station in Ohio')
        self.assertIsNone(self.research["asked"])

    def test_research_without_a_topic_bank_searches_a_rolled_gazette_headline(self):
        self.ns["read_bombshells"] = lambda: []
        self.force["h3.slot_research_topic"] = "Eggs Up"
        self.research["results"] = [{"n": 1, "title": "Egg prices up", "snippet": "Again.", "verdict": "used"}]
        got = self.run_(self.ns["h3_slot_research"]("research"))
        self.assertEqual(got, 'what the web says about "Eggs Up": "Egg prices up" - Again')
        self.assertEqual(self.notes["slot_research_topic"]["opts"], ["Cats Take Over", "Eggs Up"])
        self.assertEqual(self.research["asked"][0], "eggs up")

    def test_research_nothing_found_or_off_or_slow_is_taken_out(self):
        self.research["results"] = []
        self.assertEqual(self.run_(self.ns["h3_slot_research"]("research")), "")
        self.assertTrue(any("the web had nothing usable" in x for x in self.logs))
        self.ns["settings_web_search"] = lambda: False
        self.assertEqual(self.run_(self.ns["h3_slot_research"]("research")), "")
        self.assertTrue(any("the web search is off" in x for x in self.logs))
        self.ns["settings_web_search"] = lambda: True
        self.ns["read_bombshells"] = lambda: []
        self.shelves["gazette"] = []
        self.ns["_H3_SLOT_MEMO"]["vals"].pop("topic", None)
        self.assertEqual(self.run_(self.ns["h3_slot_research"]("research")), "")
        self.assertTrue(any("no topic and no Gazette headline" in x for x in self.logs))

    def test_research_waits_a_bounded_time(self):
        async def slow(key, query):
            try:
                await asyncio.sleep(5)
            finally:
                self.busy.discard(key)
        self.ns["_s3_research_fetch"] = slow
        self.ns["H3_SLOT_RESEARCH_WAIT_S"] = 0.2
        t0 = time.time()
        self.assertEqual(self.run_(self.ns["h3_slot_research"]("research")), "")
        self.assertLess(time.time() - t0, 3.0)
        self.assertTrue(any("did not answer in 0 s (TimeoutError)" in x for x in self.logs))
        self.assertNotIn("cats on the radio", self.busy)

    # --- the hourly door's route ---
    def door(self):
        made = {"queue": [], "renders": [], "bound": [], "woken": 0}

        class Queue:
            def add(self, payload):
                made["queue"].append(payload)
                return {"id": "q-%d" % len(made["queue"]), "status": "queued"}

        class Wake:
            def set(self):
                made["woken"] += 1

        async def render(goal, reference_clip=None, hourly=False, **kw):
            made["renders"].append({"goal": goal, "clip": reference_clip, "hourly": hourly, **kw})
            return ("Request completed.", {"queue_id": "v-1", "clip": reference_clip})

        self.ns.update({"_parody_stinger_queue": lambda: Queue(), "_parody_stinger_wake": Wake(),
                        "voice_ad_render": render, "voice_ad_spoken_copy": lambda goal: "say: " + goal,
                        "h3_hourly_rolls_bind": lambda goal: made["bound"].append(goal),
                        "h3_hourly_window": lambda clip: (1.5, 11.5)})
        return made

    def test_the_door_routes_a_clip_protagonist_through_voice_ad_render(self):
        made = self.door()
        self.force["h3.slot_protagonist_kind"] = "clips"
        self.force["h3.slot_protagonist_clip"] = 1
        self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        got = self.run_(self.ns["h3_hourly_protagonist"]("sell the night"))
        self.assertEqual(got[2], "clip")
        self.assertIn("the protagonist is the clip dog_skate", got[0])
        self.assertEqual(len(made["renders"]), 1)
        r = made["renders"][0]
        self.assertEqual(r["goal"], "sell the night")
        self.assertEqual(r["clip"]["id"], "a" * 16)
        self.assertTrue(r["clip"]["video"])
        self.assertEqual(r["clip"]["seconds"], 12.5)
        self.assertEqual((r["hourly"], r["trim_in_s"], r["trim_out_s"]), (True, 1.5, 11.5))
        self.assertEqual(made["queue"], [], "not the gallery road")
        self.assertEqual(made["bound"], ["sell the night"], "the rolls were bound to the hour before the render")
        self.assertEqual(self.notes["source"]["key"], "h3.slot_protagonist_kind")
        self.assertIn("dog skate", self.notes["source"]["picked"])
        self.assertEqual(self.notes["source"]["dice"], 7, "the die's own record rides along")
        self.assertIn("marker", self.notes)
        self.assertTrue(any("the protagonist is the clip dog_skate" in x for x in self.logs))

    def test_a_clip_without_a_length_is_rendered_without_a_window(self):
        made = self.door()
        self.ns["_H3_SLOT_MEMO"].update(protagonist={"kind": "clips", "folder": "dogs", "sid": "b" * 16, "name": "dog_bark",
                                                      "seconds": 0, "words": "the protagonist is dog bark"},
                                        protagonist_at=self.ns["_H3_SLOT_MEMO"]["at"])
        got = self.run_(self.ns["h3_hourly_protagonist"]("goal"))
        self.assertEqual(got[2], "clip")
        self.assertNotIn("trim_in_s", made["renders"][0])
        self.assertNotIn("marker", self.notes)

    def test_the_door_routes_a_picture_protagonist_through_the_gallery_payload(self):
        made = self.door()
        self.force["h3.slot_protagonist_kind"] = "renders"
        self.force["h3.slot_protagonist_clip"] = "salt flats"
        self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        got = self.run_(self.ns["h3_hourly_protagonist"]("sell the night"))
        self.assertEqual(got[2], "gallery image")
        self.assertEqual(got[1], {"id": "q-1", "status": "queued"})
        self.assertIn("salt_flats.png", got[0])
        self.assertEqual(made["renders"], [])
        p = made["queue"][0]
        self.assertEqual({k: p[k] for k in ("mode", "purpose", "source", "source_type", "speech", "hourly", "air_it")},
                         {"mode": "reference", "purpose": "parody_stinger", "source": "salt_flats.png",
                          "source_type": "gallery", "speech": "say: sell the night", "hourly": True, "air_it": False})
        self.assertIn("supplied image", p["prompt"])
        self.assertTrue(p["prompt"].endswith("sell the night"))
        self.assertNotIn("at_share", p)
        self.assertEqual(made["woken"], 1)
        self.assertEqual(made["bound"], ["sell the night"])
        self.assertEqual(self.notes["source"]["key"], "h3.slot_protagonist_kind")

    def test_the_door_routes_a_video_render_through_the_generation_reference_road(self):
        made = self.door()
        self.force["h3.slot_protagonist_kind"] = "renders"
        self.force["h3.slot_protagonist_folder"] = "videos"
        self.run_(self.ns["h3_slot_protagonist"]("protagonist"))
        got = self.run_(self.ns["h3_hourly_protagonist"]("sell the night"))
        self.assertEqual(got[2], "gallery video")
        p = made["queue"][0]
        self.assertEqual((p["source"], p["source_type"], p["mode"]), ("lighthouse_00001.mp4", "generation", "reference"))
        self.assertEqual(p["at_share"], 0.55, "the voice-ad road's own die places the window")
        self.assertIn("supplied video", p["prompt"])
        self.assertEqual(made["renders"], [])

    def test_no_protagonist_means_today_s_roll(self):
        made = self.door()
        self.assertIsNone(self.run_(self.ns["h3_hourly_protagonist"]("goal")))
        # a protagonist left from an earlier memo window is not this hour's
        self.ns["_H3_SLOT_MEMO"].update(protagonist={"kind": "renders", "file": "old.png", "words": "x"}, protagonist_at=-1.0)
        self.assertIsNone(self.run_(self.ns["h3_hourly_protagonist"]("goal")))
        self.assertEqual((made["queue"], made["renders"], made["bound"]), ([], [], []))
        self.assertNotIn("source", self.notes)


class ProductsApi(unittest.TestCase):
    """The three routes, exec'd out of app.py onto a bare FastAPI app, over a temp products file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs: list[str] = []
        ns = {
            "Any": Any, "asyncio": asyncio, "re": re, "time": time, "json": json, "uuid": uuid, "Path": Path,
            "RLock": RLock, "h3_slots": h3_slots, "h3_overview": h3_overview, "HTTPException": HTTPException,
            "pipeline_log": lambda lane, text: self.logs.append(text),
            "data_path": lambda name: Path(self.tmp.name) / name,
            "dj_settings": lambda: {"sponsors": ["Grandma's Pickles"]},
            "_H3_SLOT_MEMO": {"at": 0.0, "vals": {}}, "H3_SLOT_KEEP_S": 1800.0, "H3_SLOT_OPTS": 40, "_H3_HOURLY_ROLLS": {},
        }
        exec(compile(section(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102

        def auth(authorization, want="Bearer k"):
            if authorization != want:
                raise HTTPException(status_code=401, detail="no")

        async def body(request):
            try:
                payload = await request.json()
            except Exception:  # noqa: BLE001
                payload = None
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Expected an object")
            return payload

        self.app = FastAPI()
        ns.update({"app": self.app, "Header": Header, "Request": Request, "require_auth": auth,
                   "require_read_auth": lambda a: auth(a) if a != "Bearer r" else None, "_h3_prompts_body": body})
        exec(compile(routes_block(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
        self.ns = ns

    def tearDown(self):
        self.tmp.cleanup()

    def test_routes(self):
        from fastapi.testclient import TestClient
        c = TestClient(self.app)
        self.assertEqual(c.get("/api/h3/products").status_code, 401)
        got = c.get("/api/h3/products", headers={"Authorization": "Bearer r"})
        self.assertEqual(got.status_code, 200, "a read key reads")
        view = got.json()
        self.assertTrue(view["ok"])
        self.assertEqual(len(view["products"]), len(self.ns["H3_PRODUCTS_SEED"]))
        self.assertEqual([s["name"] for s in view["sponsors"]], ["Grandma's Pickles"])
        self.assertEqual(view["count"], len(view["products"]) + 1)
        self.assertEqual(set(view["products"][0]), {"id", "name", "pitch", "added_at"})
        # writes need the write key
        self.assertEqual(c.post("/api/h3/products", json={"name": "x"}, headers={"Authorization": "Bearer r"}).status_code, 401)
        self.assertEqual(c.post("/api/h3/products", json={"pitch": "no name"}, headers={"Authorization": "Bearer k"}).status_code, 400)
        self.assertEqual(c.post("/api/h3/products", json=[1], headers={"Authorization": "Bearer k"}).status_code, 400)
        got = c.post("/api/h3/products", json={"name": " The Night  Shift ", "pitch": "ours, after dark."},
                     headers={"Authorization": "Bearer k"})
        self.assertEqual(got.status_code, 200, got.text)
        added = got.json()["products"][-1]
        self.assertEqual((added["name"], added["pitch"]), ("The Night Shift", "ours, after dark."))
        self.assertTrue(added["id"].startswith("pr-"))
        on_disk = json.loads((Path(self.tmp.name) / "h3_products.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["products"][-1]["name"], "The Night Shift")
        self.assertEqual(c.post("/api/h3/products", json={"name": "the night shift"}, headers={"Authorization": "Bearer k"}).status_code, 409)
        self.assertEqual(c.post("/api/h3/products/nope/delete", headers={"Authorization": "Bearer k"}).status_code, 404)
        self.assertEqual(c.post("/api/h3/products/%s/delete" % added["id"], headers={"Authorization": "Bearer r"}).status_code, 401)
        got = c.post("/api/h3/products/%s/delete" % added["id"], headers={"Authorization": "Bearer k"})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(len(got.json()["products"]), len(self.ns["H3_PRODUCTS_SEED"]))
        self.assertTrue(any('"The Night Shift" added' in x for x in self.logs))
        self.assertTrue(any("removed" in x for x in self.logs))


class Wiring(unittest.TestCase):
    def test_the_door_asks_the_protagonist_before_it_rolls_the_source(self):
        door = APP_TEXT[APP_TEXT.index("async def h3_hourly_render(state"):APP_TEXT.index('@app.get("/api/h3/hourly")')]
        ask = door.index("_h3_star = await h3_hourly_protagonist(goal)")
        self.assertLess(door.index("goal = h3_hourly_ad_prompt()"), ask)
        self.assertLess(door.index('h3_hourly_roll_note("host", "h3.hourly_host")'), ask, "the host's hours stay the host's")
        self.assertLess(ask, door.index("_h3_gallery = False"))
        self.assertLess(ask, door.index('s3_weighted("h3.hourly_source"'))
        self.assertIn("if _h3_star:\n        return _h3_star", door)

    def test_the_rest_is_wired(self):
        for bit in ('values.setdefault("topic", h3_slot_topic())',
                    'elif name == "music":                                          # [pineex] wave C',
                    "got = await h3_slot_protagonist(tok)", "got = await h3_slot_research(tok)",
                    'if name in ("convograph", "protagonist", "research"):',
                    "return h3_slot_music_sync(tok)", "return h3_slot_offer_sync(tok)", "return h3_slot_brand(tok)",
                    '@app.get("/api/h3/products")', '@app.post("/api/h3/products")', '@app.post("/api/h3/products/{pid}/delete")',
                    'if name == "music":                      # [pineex]', 'if name == "product":                    # [pineex]',
                    'elif name == "product":                                              # [pineex]',
                    "return h3_slots.product(got)"):
            self.assertIn(bit, APP_TEXT, bit)
        self.assertNotIn('values.setdefault("topic", s3_choice("h3.plot_topic"', APP_TEXT, "one topic roll, through h3_slot_topic")


if __name__ == "__main__":
    unittest.main()
