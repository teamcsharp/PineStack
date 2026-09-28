"""[cast-names] The cast's names through the real app.py: the settings keep
them, dj_settings() carries them, booth_actor_name() prints them, the SFX
guy's old "The SFX Guy" becomes his name, the random roll is kept and the
button rolls again; the routes and the DJ options' cast box exist.

Imports app (run in the container, after tools/cast_names_patch.py --apply).
Nothing here touches the station's data dir or settings file: the rolls file
is a temp path, load_settings() answers a validated dict, and the keeper's
write is made on the test's own thread."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class CastNamesApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cast_names.json"
        self.settings = app.validate_settings(app.DEFAULT_SETTINGS)
        keep = app._cast_save
        for patch in (
                mock.patch.object(app, "CAST_NAMES_PATH", self.path),
                mock.patch.object(app, "load_settings", lambda: self.settings),
                mock.patch.object(app, "_cast_save", lambda wait=False: keep(wait=True)),
                mock.patch.object(app, "pipeline_log", lambda *a, **k: None),
                mock.patch.dict(app._CAST_STATE, {"loaded": False, "rolled": {},
                                                  "rolling": False, "version": 0})):
            patch.start()
            self.addCleanup(patch.stop)
        app._CAST_MEMO.clear()
        app._CAST_OVERLAY[0] = None
        self.addCleanup(app._CAST_MEMO.clear)

    def use(self, **dj):
        self.settings = app.validate_settings(dict(app.DEFAULT_SETTINGS, dj=dj))
        return self.settings["dj"]

    def test_default_dj_and_validate_keep_the_cast(self):
        self.assertEqual((app.DEFAULT_DJ["host_name"], app.DEFAULT_DJ["cohost_name"],
                          app.DEFAULT_DJ["sfxguy_name"]), ("Dill", "Skip", "Sam"))
        dj = self.use(sfxguy_name="Moe", sfxguy_name_mode="custom",
                      host_name_mode="random", host_name_pool="Rex, Gus",
                      cast_reroll_daily=False)
        self.assertEqual((dj["sfxguy_name"], dj["sfxguy_name_mode"]), ("Moe", "custom"))
        self.assertEqual(dj["host_name_pool"], ["Rex", "Gus"])
        self.assertFalse(dj["cast_reroll_daily"])
        again = app.validate_settings(dict(app.DEFAULT_SETTINGS, dj=dj))["dj"]
        for key in ("host_name", "host_name_mode", "host_name_pool", "cohost_name",
                    "cohost_name_mode", "sfxguy_name", "sfxguy_name_mode",
                    "cast_reroll_daily"):
            self.assertEqual(again[key], dj[key], key)

    def test_the_station_cast_everywhere(self):
        dj = app.dj_settings()
        self.assertEqual((dj["host_name"], dj["cohost_name"], dj["sfxguy_name"]),
                         ("Dill", "Skip", "Sam"))
        self.assertEqual(app.booth_actor_name("dj"), "Dill")
        self.assertEqual(app.booth_actor_name("cohost"), "Skip")
        self.assertEqual(app.booth_actor_name("drop"), "Sam")
        self.assertEqual(app.booth_actor_name("sfx"), "Sam")

    def test_the_old_sfx_guy_label_is_his_name_now(self):
        self.assertEqual(app.booth_actor_name("drop", "The SFX Guy"), "Sam")
        self.assertEqual(app.booth_actor_name("drop", "Big Moe"), "Big Moe")
        self.assertEqual(app.booth_actor_name("cohost", "Skippy"), "Skippy")

    def test_the_desk_is_not_the_host(self):
        self.assertEqual(app.booth_actor_name("host"), "The desk")

    def test_custom_names_reach_dj_settings_and_the_booth(self):
        self.use(host_name="Rex", host_name_mode="custom",
                 sfxguy_name="Moe", sfxguy_name_mode="custom")
        self.assertEqual(app.dj_settings()["host_name"], "Rex")
        self.assertEqual(app.booth_actor_name("dj"), "Rex")
        self.assertEqual(app.booth_actor_name("drop", "The SFX Guy"), "Moe")
        self.assertEqual(app.cast_name("sfxguy"), "Moe")

    def test_random_is_rolled_kept_and_shown(self):
        self.use(host_name_mode="random", host_name_pool="Rex, Gus")
        got = app.dj_settings()["host_name"]
        self.assertIn(got, ("Rex", "Gus"))
        self.assertEqual(self.settings["dj"]["host_name"], "Dill")   # the store keeps its text
        self.assertTrue(self.path.exists())
        state = app.cast_names_state()
        self.assertEqual(state["cast"]["host"]["rolled"]["name"], got)
        self.assertEqual(app.dj_settings()["host_name"], got)        # once a day, not per ask

    def test_the_button_rolls_a_different_name(self):
        self.use(sfxguy_name_mode="random", sfxguy_name_pool="Rex, Gus")
        before = app.cast_name("sfxguy")
        got = app.cast_roll_now()
        self.assertEqual(got["rolled"], ["sfxguy"])
        self.assertNotEqual(got["names"]["sfxguy"], before)
        self.assertEqual(app.booth_actor_name("drop"), got["names"]["sfxguy"])

    def test_routes_and_the_cast_box(self):
        paths = {getattr(r, "path", "") for r in app.app.routes}
        self.assertIn("/api/cast/names", paths)
        self.assertIn("/api/cast/names/roll", paths)
        page = app.CONTROL_PANEL_HTML
        for needle in ('id="djCast"', 'id="djHostNameMode"', 'id="djSfxguyNamePool"',
                       'id="djCastRoll"', "...castCollect(),", "castFill(dj);"):
            self.assertEqual(page.count(needle), 1, needle)
        self.assertEqual(page.count('id="djCohostName"'), 1)   # one field, in the cast box


if __name__ == "__main__":
    unittest.main()
