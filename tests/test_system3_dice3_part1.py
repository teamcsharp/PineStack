"""[s3-dice-door] The rest of the station's own dice are System 3's (part 1):
the render reply, the box's intonation, the rotation's deal, the response
bank's documents, a record's callback, the torrent's kind of round and its
breath, the six-hourly questions, the spot, the read and the bed an advert
takes, the officer outside, and upstairs cutting in - every one a roll through
the dice door (tools/system3_dice3_part1_patch.py), none a bare random draw."""
import ast
import importlib.util
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = "system3_dice3_part1_patch"

# the function, and the keys its rolls go through System 3's dice door on
CONVERTED = {
    "announce_render_complete": ("render.reply",),
    "voice_ad_render": ("ad.voice_at_share",),
    "_hot_shelf_pick": ("records.hot_shelf",),
    "speak": ("voice.reply_pace", "voice.reply_pitch", "voice.reply_pitch_var",
              "voice.reply_energy", "voice.reply_pauses"),
    "radio_fill": ("records.rotation_deal",),
    "response_bank_sources": ("speakbox.response_docs", "speakbox.response_docs_old",
                              "speakbox.response_swath"),
    "track_callback": ("records.callback", "records.callback_after", "records.callback_before"),
    "directive_draw_kind": ("torrent.round_kind",),
    "orch_routine_questions": ("orch.routine_questions",),
    "coord_spot_ready": ("ad.gap_spot",),
    "torrent_breath": ("torrent.breath",),
    "loved_moment": ("ad.bed_moment",),
    "ad_pick": ("ad.read_pick",),
    "_siren_sample": ("police.siren",),
    "dj_police_outside": ("police.character", "police.pitch"),
    "manager_cut_in_clause": ("manager.cut_in", "manager.cut_in_gripe",
                              "manager.cut_in_manner", "manager.cut_in_react"),
    "upstairs_clock": ("manager.page_first_wait", "manager.page_wait"),
    "_music_bed_track": ("ad.bed_marked", "ad.bed_marked_pick", "ad.bed_fave",
                         "ad.bed_fave_pick", "ad.bed_any"),
    "dj_music_ad": ("ad.bed_start",),
    "ad_produce": ("ad.bed_start",),
}

# a bare draw off the station's own random (random.Random - a seeded deal - is not one)
DRAWS = {"random", "choice", "choices", "uniform", "randint", "randrange", "shuffle",
         "sample", "gauss", "triangular", "betavariate", "expovariate", "normalvariate"}


def tool():
    spec = importlib.util.spec_from_file_location(TOOL, ROOT / "tools" / (TOOL + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def function_source(text, name):
    """A top-level function's source, cut at the next top-level statement - no
    whole-file parse of a 12 MB app.py."""
    m = re.search(r"^(?:async )?def %s\(" % re.escape(name), text, re.M)
    assert m, name
    # the next line that starts in column 0 with code; a string that runs in
    # column 0 inside the body cuts it short, so widen until it parses
    for nxt in re.finditer(r"\n(?=[^\s#])", text[m.end():]):
        src = text[m.start():m.end() + nxt.start() + 1]
        try:
            ast.parse(src)
        except SyntaxError:
            continue
        return src
    return text[m.start():]


def bare_draws(src):
    tree = ast.parse(src)
    return sorted({"random.%s (line %d)" % (n.func.attr, n.lineno) for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and isinstance(n.func.value, ast.Name) and n.func.value.id == "random"
                   and n.func.attr in DRAWS})


class DiceThreePartOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")

    def test_the_tool_reports_applied(self):
        mod = tool()
        applied, missing = mod.check(self.text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(self.text)))
        for marker in ("def s3_chance(", "def s3_roll(", "def s3_choice(", "def s3_sample(", "def s3_weighted("):
            self.assertIn(marker, self.text)

    def test_every_converted_road_rolls_the_dice_door_and_no_bare_draw(self):
        for name, keys in CONVERTED.items():
            src = function_source(self.text, name)
            self.assertEqual(bare_draws(src), [], name)
            self.assertIn("s3_", src, name)
            self.assertIn("[s3-dice-door]", src, name)
            for key in keys:
                self.assertIn('"%s"' % key, src, "%s rolls %s" % (name, key))

    def test_keys_are_stable_and_short(self):
        keys = re.findall(r's3_(?:chance|roll|choice|sample|weighted|unrepeated)\("([^"]+)"',
                          "\n".join(new for _n, _o, new, _c in tool().EDITS))
        self.assertTrue(keys)
        for key in keys:
            self.assertRegex(key, r"^[a-z0-9_]+\.[a-z0-9_]+$")
            self.assertLessEqual(len(key), 60)

    def test_the_bed_filter_asks_without_rolling(self):
        # _music_bed_track only asks whether a favourite has a marked moment:
        # one roll per favourite would be noise on the Audit feed
        src = function_source(self.text, "_music_bed_track")
        self.assertIn("roll=False", src)
        self.assertIn("roll: bool = True", function_source(self.text, "loved_moment"))


if __name__ == "__main__":
    unittest.main()
