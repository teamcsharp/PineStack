"""[s3-dice-door] part 3: the last bare draws of the banter, button, speakbox
deal, writer-heat, SFX TV, Gazette and Pine roads go through System 3's dice
door (tools/system3_dice3_part3_patch.py)."""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = "system3_dice3_part3_patch"

# function -> (the bare draws that must be gone, the dice keys it now rolls)
CONVERTED = {
    "dj_banter": (['random.random() < dj["saved_rate"]',
                   "random.sample(list(dj['diatribe_interjections'])"],
                  ['"banter.saved_replay"', "'banter.interjections'"]),
    "ask_model": (["random.uniform(0.0, _hot)", "random.uniform(0.0, 0.35 * _heat)"],
                  ['"writer.shelf_heat"', '"writer.call_heat"']),
    "_swath_deal": (["random.randrange(len(pool))"], ['"speakbox.deal_lead"']),
    "api_director_script_reseed": (["random.randint(1, max(1, len(turns) - 1))"], ['"director.reseed_at"']),
    "dj_banter_api": (["random.randint(2, 6)", "random.randint(240, 520)", "random.randint(7, 14)"],
                      ['"button.banter_most"', '"button.banter_cap"', '"button.banter_lines"']),
    "dj_converse_api": (["random.randint(6, 12)"], ['"button.converse_lines"']),
    "dj_dice_api": (["random.choice(readers)"], ['"dice.reader"']),
    "_replay_volley": (["random.random() < 0.5"], ['"replay.last_word"']),
    "sfx_db_pick_short_video": (["random.choice(fresh or folders)", "random.randrange(int(count))"],
                                ['"sfxtv.short_folder"', '"sfxtv.short_clip"']),
    "sfx_db_pick_rotation_row": (["random.randrange(count)"], ['"sfxtv.deck_clip"']),
    "_sfx_db_pick_any": (["random.randrange(count)"], ['"sfxtv.any_clip"']),
    "_paper_seed_draw": (["random.shuffle(files)", "random.randrange(max(1, len(words) - 55 + 1))"],
                         ['"paper.seed_docs"', '"paper.seed_docs_again"', '"paper.seed_start"']),
    "pine_submit": (["random.choice("], ['"pine.submit_phrase"']),
    "pine_resolve": (["random.choice("], ['"pine.complete_phrase"']),
}
# every draw in these is now System 3's (dj_banter and ask_model keep draws
# that are another tool's lines or the decode's own entropy)
WHOLLY = [f for f in CONVERTED if f not in ("dj_banter", "ask_model")]
BARE = re.compile(r"(?<![\w.])random\.(?:random|choice|choices|sample|shuffle|uniform|randint|randrange)\(")


def tool():
    spec = importlib.util.spec_from_file_location(TOOL, ROOT / "tools" / (TOOL + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def source_of(text, name):
    """A top-level function's source: its def line to the next top-level def."""
    m = re.search(r"^(?:async def|def) %s\(" % re.escape(name), text, re.M)
    assert m, "%s is not in app.py" % name
    nxt = re.compile(r"^(?:async def |def |class |@)", re.M).search(text, m.end())
    return text[m.start(): nxt.start() if nxt else len(text)]


class DicePart3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")

    def test_every_edit_is_in_app_py(self):
        mod = tool()
        applied, missing = mod.check(self.text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(self.text)), "every part-3 dice edit is present exactly once")

    def test_the_converted_draws_roll_system3s_dice(self):
        for fn, (gone, keys) in CONVERTED.items():
            src = source_of(self.text, fn)
            for draw in gone:
                self.assertNotIn(draw, src, "%s still draws %s itself" % (fn, draw))
            for key in keys:
                self.assertIn(key, src, "%s does not roll %s" % (fn, key))
            self.assertRegex(src, r"\b(?:s3_(?:chance|roll|choice|sample|weighted)|_S3Dice)\(", fn)
            self.assertIn("# [s3-dice-door]", src, fn)

    def test_the_wholly_converted_roads_have_no_bare_draw_left(self):
        for fn in WHOLLY:
            self.assertEqual(BARE.findall(source_of(self.text, fn)), [], fn)

    def test_the_integer_draws_keep_randints_range(self):
        # lo + min(hi - lo, int(u * (hi - lo + 1))) over u in [0, 1): every
        # value lo..hi, evenly - the station's own randint when System 3 is off
        for lo, hi in ((2, 6), (240, 520), (7, 14), (6, 12)):
            n = 100 * (hi - lo + 1)
            got = [lo + min(hi - lo, int(((k + 0.5) / n) * (hi - lo + 1))) for k in range(n)]
            self.assertEqual(sorted(set(got)), list(range(lo, hi + 1)))
            self.assertEqual({got.count(v) for v in range(lo, hi + 1)}, {100})
            self.assertEqual(lo + min(hi - lo, int(0.9999999999 * (hi - lo + 1))), hi)


if __name__ == "__main__":
    unittest.main()
