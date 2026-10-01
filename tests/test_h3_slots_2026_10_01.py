"""[h3-slots] {mxtape} {fordtape} {videos} {sfxclip} {convograph} {gazette} {arena}:
the pure builders (h3_slots.py) and the roll (exec'd out of app.py with stubs)."""
import __future__
import asyncio
import re
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import h3_slots  # noqa: E402
import flow_chart  # noqa: E402

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")
FLAGS = __future__.annotations.compiler_flag


class Pure(unittest.TestCase):
    def test_tokens_and_digits(self):
        self.assertEqual(h3_slots.tokens("in {arena} vs {arena2} to {mxtape}", "{arena} {gazette} {record}"),
                         ["arena", "arena2", "mxtape", "gazette"])
        self.assertEqual(h3_slots.base("arena2"), "arena")
        self.assertEqual(h3_slots.base("record"), "")

    def test_phrases(self):
        self.assertEqual(h3_slots.mxtape("MX tape · August 4"), 'the MX mixtape "MX tape · August 4" by Ehm Eckx')
        self.assertEqual(h3_slots.arena("2026-09-30_neon-forest_00012.png"),
                         'an arena built from the Pine Box gallery picture "neon forest"')
        self.assertIn("which shows a dog on a skateboard",
                      h3_slots.sfxclip("a stadium jumbotron", {"name": "dog_skate.mp4", "seen_desc": "a dog on a skateboard."}))
        self.assertIn('someone says "hello there"', h3_slots.sfxclip("a tv", {"name": "x", "said": "hello there"}))
        self.assertEqual(h3_slots.gazette({"headline": 'The "Big" Night', "deck": "All of it."}),
                         "the Pine Box Gazette, its front page headline reading \"The 'Big' Night\" (All of it)")

    def test_convograph_reads_a_real_flow(self):
        conv = {"identity": {"conversation_id": "abcdef0123456789"}, "inputs": {"road": "caller",
                "subject": {"topic": "cats on the radio"}},
                "turns": [{"index": 0, "turn_id": "t0", "speaker": "A"}],
                "decision_events": [{"family": "CALLARC", "seq": 1, "stages": [
                    {"selected": "esc", "draw": {"dice": 41},
                     "candidates": [{"id": "esc", "label": "escalation", "p": 0.4},
                                    {"id": "res", "label": "resolution", "p": 0.6}]}]}]}
        text = h3_slots.convograph(flow_chart.build_flow(conv))
        self.assertIn("(#abcdef01) on the caller road", text)
        self.assertIn('about "cats on the radio"', text)
        self.assertIn('callarc rolled "escalation" at 40% over 1 others', text)

    def test_the_app_s_pattern_names_the_same_slots(self):
        m = re.search(r'^H3_SLOT_NAMES = r"\(\?:([a-z|]+)\)', APP_TEXT, re.M)
        self.assertEqual(tuple(m.group(1).split("|")), h3_slots.NAMED)

    def test_catalogue_explains_every_named_slot(self):
        names = {r["name"] for r in h3_slots.catalogue()}
        for n in h3_slots.NAMED + ("conversation", "record", "station", "speakerbox"):
            self.assertIn(n, names)
        self.assertTrue(all(r["says"] for r in h3_slots.catalogue()))


def section():
    start = APP_TEXT.index("# --- [h3-slots] THE NAMED SLOTS")
    end = APP_TEXT.index("def h3_speak_fill(template: Any", start)
    return APP_TEXT[start:end]


class Rolls(unittest.TestCase):
    def setUp(self):
        self.rolls, self.notes, self.logs = [], {}, []
        self.shelves = {"mxtape": ["MX tape · August 4", "MX tape · June 1"], "fordtape": [],
                        "videos": ["lighthouse_00001.mp4"], "arena": ["neon_forest.png", "salt_flats.png"],
                        "gazette": [{"id": "e1", "headline": "Cats Take Over", "deck": "Again"}], "sfxclip": 10}

        def weighted(key, labels, weights, label="", media=None):
            self.rolls.append(key)
            return len([k for k in self.rolls if k == key]) - 1   # first roll 0, second 1

        def choice(key, options, label="", tabled=True):
            self.rolls.append(key)
            return list(options)[2]

        rolls_store: dict[str, Any] = {}
        self.ns = {"Any": Any, "asyncio": asyncio, "re": re, "time": time, "Path": Path, "h3_slots": h3_slots,
                   "s3_weighted": weighted, "s3_choice": choice, "s3_roll": lambda key, label="": 0.55,
                   "pipeline_log": lambda lane, text: self.logs.append(text),
                   "_H3_SLOT_MEMO": {"at": 0.0, "vals": {}}, "H3_SLOT_KEEP_S": 1800.0, "H3_SLOT_OPTS": 40,
                   "_H3_HOURLY_ROLLS": rolls_store,
                   "h3_hourly_roll_note": lambda name, key, rec=None: rolls_store.__setitem__(name, {"key": key}),
                   "_h3_slot_note": lambda name, key, opts, picked: rolls_store.__setitem__(
                       name, {"key": key, "opts": opts, "picked": picked})}
        exec(compile(section(), "app.py", "exec", flags=FLAGS, dont_inherit=True), self.ns)  # noqa: S102
        self.ns["h3_slot_shelf"] = lambda name: self.shelves[name]
        self.ns["h3_slot_sfx_row"] = lambda u, total: {"name": "door_slam_%d" % int(u * total), "seen_desc": "a door slams"}

    def test_preroll_fills_the_memo(self):
        got = asyncio.run(self.ns["h3_slots_preroll"](
            "Concert to {mxtape}. {arena} vs {arena2}. {gazette}. {videos}. {sfxclip}. {fordtape}."))
        vals = self.ns["_H3_SLOT_MEMO"]["vals"]
        self.assertEqual(vals["mxtape"], 'the MX mixtape "MX tape · August 4" by Ehm Eckx')
        self.assertIn('"neon forest"', vals["arena"])
        self.assertIn('"salt flats"', vals["arena2"], "a second spelling is its own roll")
        self.assertIn("Cats Take Over", vals["gazette"])
        self.assertIn('a computer monitor on a cluttered desk playing the Pine Box gallery video "lighthouse"',
                      vals["videos"])
        self.assertIn('playing the clip "door slam", which shows a door slams', vals["sfxclip"])
        self.assertEqual(vals["fordtape"], "", "an empty shelf is taken out")
        self.assertTrue(any("{fordtape} - nothing on its shelf" in x for x in self.logs))
        for tok in ("mxtape", "arena", "arena2", "gazette", "videos", "sfxclip"):
            self.assertIn("slot_" + tok, self.ns["_H3_HOURLY_ROLLS"])
        self.assertIn("slot_screen_videos", self.ns["_H3_HOURLY_ROLLS"])
        self.assertIn("h3.slot_screen", self.rolls)
        self.assertEqual(set(got), {"mxtape", "arena", "arena2", "gazette", "videos", "sfxclip", "fordtape"})

    def test_a_fault_is_taken_out_not_raised(self):
        def boom(name):
            raise OSError("share gone")
        self.ns["h3_slot_shelf"] = boom
        asyncio.run(self.ns["h3_slots_preroll"]("{mxtape}"))
        self.assertEqual(self.ns["_H3_SLOT_MEMO"]["vals"]["mxtape"], "")
        self.assertTrue(any("could not be rolled (OSError)" in x for x in self.logs))

    def test_convograph_is_the_door_s_only(self):
        self.assertEqual(self.ns["h3_slot_named_sync"]("convograph"), "")


class Wiring(unittest.TestCase):
    def test_wired(self):
        for bit in ("await h3_slots_preroll(", "h3_slot_named_sync(tok) if re.fullmatch(H3_SLOT_NAMES, tok)",
                    '"id": "base-mx-concert"', '"id": "base-ford-performance"', '"id": "base-arena-battle"',
                    '"slots": h3_slots.catalogue()', '"fordtape_folder": "_general ford"'):
            self.assertIn(bit, APP_TEXT)
        js = (ROOT / "desktop" / "renderer" / "ad-viewer.js").read_text(encoding="utf-8")
        for bit in ("rnd.value = 'random'", "function slotOpen(", "function slotCheck(", "slotCheckAll();"):
            self.assertIn(bit, js)
        for name in ("ad-viewer.js", "view-chrome.css"):
            self.assertEqual((ROOT / "desktop" / "renderer" / name).read_text(encoding="utf-8"),
                             (ROOT / "app" / "src" / "main" / "assets" / "pine-views" / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
