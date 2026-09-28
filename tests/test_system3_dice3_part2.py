"""[s3-dice-door] The third dice sweep, part 2: the speakbox scenes, the cast,
the seat, the banter dice, the story clock, the phones and the ad clock roll
System 3's dice (tools/system3_dice3_part2_patch.py is applied to app.py)."""
import importlib.util
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

# function -> (the bare draws that were converted, the keys it now rolls)
CONVERTED = {
    "speakbox_harvest": (["random.randrange(0, len(body) - SPEAKBOX_GEM_WINDOW)"],
                         ["speakbox.harvest_window"]),
    "switchboard_fill": (["random.random() * total"], ["switchboard.kind"]),
    "speakbox_scene_angle": (['random.choice(["A", "B"])', "random.choice([first, other])",
                              "random.random() < 0.35"],
                             ["speakbox.scene_performer", "speakbox.scene_jab", "speakbox.caught_quoting"]),
    "speakbox_angle": (['random.choice(["A", "B"])', "random.random() < 0.34", "random.random() < 0.35"],
                       ["speakbox.drop_speaker", "speakbox.monologue", "speakbox.caught_quoting"]),
    "banter_voices": (["random.choice(have)"], ["cast.female_voice", "cast.male_voice"]),
    "session_voices": (["random.random() < 0.5"], ["cast.host_is_woman"]),
    "voice_effect_pick": (['random.random() >= dj["fx_rate"]', 'random.uniform(dj["fx_min"], dj["fx_max"])'],
                          ["voice.fx_wet", "voice.fx_depth"]),
    "sting_due": (["random.random() < SFX_UNHEARD_SHARE", "random.random() < SFX_FRESH_SHARE"],
                  ["sting.unheard_first", "sting.fresh_first"]),
    "_sfx_deck_fill": (["random.choice(pool)"], ["sfx.deck_video"]),
    "_sting_over_record": (["random.uniform(8.0, 25.0)"], ["sting.over_record_at"]),
    "seat_line": (["random.choice(pool)"], []),          # keyed per reason: seat.<reason>_<leave|back>
    "seat_reason_draw": (["random.choice("], ["seat.reason"]),
    "_seat_door_sample_blocking": (["random.choice(pool)"], ["seat.door_sample"]),
    "seat_go_away": (["random.uniform(0.75, 1.25)"], ["seat.away_span"]),
    "approach_pick": (["random.choice(DIALOGUE_APPROACHES)", "random.choices("],
                      ["approach.builtin", "approach.frame"]),
    "banter_dice_roll": (["random.random()"], ["banter.dice_roll"]),
    "banter_dice_pick": (["random.choices("], ["banter.dice_card"]),
    "banter_beat_sheet": (["random.choice(pool)", "random.random() > rate"],
                          ["banter.sheet_seat", "banter.sheet_dice_turn"]),
    "banter_due": (["random.uniform("], ["banter.clock_gap"]),
    "story_open_async": (["random.uniform(STORY_DUE_MIN_S"], ["story.next_part_due"]),
    "story_beat_async": (["random.uniform(STORY_DUE_MIN_S"], ["story.next_part_due"]),
    "_call_rerun_pick_blocking": (["random.choice(cands)"], ["call.rerun_take"]),
    "caller_face": (["random.choice(free)"], ["call.face_picture"]),
    "caller_voice_for": (["random.random()"], ["call.library_voice"]),
    "ad_clock": (["roll = random.random()"], ["station.clock_ad_kind"]),
    "caller_clock": (["random.uniform(0.6, 1.4)", "random.random() < 0.5"],
                     ["call.clock_wait", "call.flood_banter"]),
}

S3_CALL = re.compile(r"\bs3_(chance|roll|pool|choice|sample|weighted|unrepeated)\(|\b_S3Dice\(")


def app_text():
    return (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def function_source(text, name):
    m = re.search(r"^(?:async )?def %s\(" % re.escape(name), text, re.M)
    if m is None:
        raise AssertionError("no function %s in app.py" % name)
    end = re.compile(r"^[^\s#]", re.M).search(text, m.end())
    return text[m.start(): end.start() if end else len(text)]


class Dice3Part2Tests(unittest.TestCase):
    def test_the_tool_is_applied(self):
        spec = importlib.util.spec_from_file_location(
            "system3_dice3_part2_patch", ROOT / "tools" / "system3_dice3_part2_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = app_text()
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every part-2 dice edit is present exactly once")
        for marker in ("def s3_chance(", "def s3_roll(", "def s3_pool(", "def s3_choice(",
                       "def s3_weighted(", "class _S3Dice:"):
            self.assertIn(marker, text, "the dice door (system3_dice_patch.py) is open")

    def test_every_converted_draw_rolls_system3s_dice(self):
        text = app_text()
        for name, (draws, keys) in CONVERTED.items():
            src = function_source(text, name)
            for draw in draws:
                self.assertNotIn(draw, src, "%s still draws %s bare" % (name, draw))
            self.assertRegex(src, S3_CALL, "%s rolls through the dice door" % name)
            self.assertIn("[s3-dice-door]", src, name)
            for key in keys:
                self.assertTrue('"%s"' % key in src or "'%s'" % key in src, "%s rolls %s" % (name, key))

    def test_the_seat_book_is_a_desk_pool_per_reason(self):
        src = function_source(app_text(), "seat_line")
        self.assertIn('_sk = "seat.%s_%s" % (reason if reason in SEAT_AWAY_BOOK else "coffee", which)', src)
        self.assertIn("lines = s3_pool(_sk,", src)
        self.assertIn("s3_choice(_sk, pool,", src)

    def test_what_was_left_as_the_stations_own_random(self):
        # DSP texture and a retry wait stay the station's own; the decisions
        # above them are System 3's (see the tool's docstring for the rest)
        text = app_text()
        fx = function_source(text, "voice_effect_pick")
        self.assertIn('"delay": random.uniform(0.09, 0.22),', fx)
        rec = function_source(text, "_sting_over_record")
        self.assertIn("await asyncio.sleep(random.uniform(9.0, 14.0))", rec)


if __name__ == "__main__":
    unittest.main()
