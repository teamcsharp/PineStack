"""[es-bank] [ad-rolo] banked lines go through the emotion engine; adverts roll a rolodex.

"I want banked scheduled and written cupboard footage taken through the emotion engine
and i want the cupboard storing ads and stingers with emotional intonation where people
passionately try to sell things driven by scripted situations seeded by the speakerbox
and rolled through a rolodex to randomly give each ad a unique angle and hilarious
outcome."                                                        - the operator, 2026-10-01
"""
import asyncio
import unittest
from unittest import mock

import app


class Handle:
    active = True

    def __init__(self):
        self.stamp = {"conversation_id": "abc123", "turn_id": "abc123:0", "road": "ad_spot"}
        self.bound = ""


class AdRolodex(unittest.TestCase):
    def test_three_rolls_and_a_brief(self):
        got = app.ad_rolodex("Pine Box coffee")
        self.assertIn(got["angle"], app.AD_ANGLES)
        self.assertIn(got["outcome"], app.AD_OUTCOMES)
        self.assertIn(got["passion"], app.AD_PASSIONS)
        for part in ("SCRIPTED SITUATION", "PASSIONATE", "Pine Box coffee", got["angle"], got["outcome"]):
            self.assertIn(part, got["brief"])

    def test_the_rolls_are_system3_dice_doors(self):
        seen = []

        def choice(key, options, label="", tabled=True):
            seen.append((key, tabled))
            return list(options)[0]
        with mock.patch.object(app, "s3_choice", choice):
            app.ad_rolodex("x")
        self.assertEqual([k for k, _ in seen], ["ad.angle", "ad.outcome", "ad.passion"])
        self.assertTrue(all(t for _, t in seen), "tabled: the desk edits the pools")

    def test_the_pitch_reaches_the_writer(self):
        got = {}

        async def line(kind, track, extra="", direct="", tint=True, **kw):
            got["direct"] = direct
            return "Buy the coffee. It is the only coffee. The Pine Box coffee will change your life forever."
        with mock.patch.object(app, "dj_line", line), \
                mock.patch.object(app, "speakbox_quote", mock.AsyncMock(return_value={})), \
                mock.patch.object(app, "dialogue_tint_wanted", lambda: False):
            asyncio.run(app.ad_write_fresh("Pine Box coffee", tries=1, pitch=" THE PITCH: a wedding toast."))
        self.assertIn("THE PITCH: a wedding toast.", got["direct"])


class EsBank(unittest.TestCase):
    def test_a_line_with_no_node_is_recorded_on_its_road_with_its_feeling(self):
        h = Handle()
        opened = {}

        async def direct_line(**ctx):
            opened.update(ctx)
            return h

        def bind(handle, text):
            handle.bound = text

        async def stamp_perf(stamp, who):
            return ({"dims": {"joy": 1.0}, "voice": {"energy": 1.4}} if stamp else None), None

        async def render(text, voice, engine, fx=None, who=""):
            return {"path": "/media/x.wav", "seconds": 2.0, "fx": fx}
        with mock.patch.dict(app.__dict__, {"system3_direct_line": direct_line, "system3_bind_line": bind}), \
                mock.patch.object(app, "configured_radio_voice", lambda who, v: "v1"), \
                mock.patch.object(app, "voice_engine_for", lambda v: "piper"), \
                mock.patch.object(app, "pantry_get", lambda k: None), \
                mock.patch.object(app, "render_relief", lambda: False), \
                mock.patch.object(app, "prep_should_stop", lambda: False), \
                mock.patch.object(app, "engine_prep_take", lambda e: True), \
                mock.patch.object(app, "engine_prep_give", lambda e: None), \
                mock.patch.object(app, "voice_render_any", render), \
                mock.patch.object(app, "_s3_stamp_perf", stamp_perf), \
                mock.patch.object(app, "performance_vector", lambda who, voice, state=None, es=None: {"es": es} if es else {}), \
                mock.patch.object(app, "pantry_put", lambda *a, **k: None), \
                mock.patch.object(app, "task_note", lambda *a, **k: None):
            made = asyncio.run(app.prep_render_line("Buy it now, friends.", "dj", kind="ad"))
        self.assertEqual(opened["road"], "ad_spot")
        self.assertTrue(opened["bank"])
        self.assertEqual(h.bound, "Buy it now, friends.")
        self.assertEqual(made["system3"]["road"], "ad_spot")


if __name__ == "__main__":
    unittest.main()
