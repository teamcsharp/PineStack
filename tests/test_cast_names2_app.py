"""[cast-names] Round two through the real app.py (run in the container, after
tools/cast_names_patch.py, tools/cast_names2_patch.py and - for the director
test - tools/cast_names2_modules_patch.py director.py):

  the personas dj_settings() hands the writers follow the names;
  Sam is named in his writers (the board shape, the flow instruction, the
  director's beat, and the prompt text of the rest);
  dialogue_row_ready consults the rename gate, and the rename desk re-records
  a held row with the names changed;
  a caller is never drawn under a cast member's name.

Nothing touches the station's data dir or settings file: load_settings()
answers a validated dict, the rolls and names books are temp paths, the shelf
and larder are empty lists for the length of a test."""
import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings = app.validate_settings(app.DEFAULT_SETTINGS)
        keep = app._cast_save
        for patch in (
                mock.patch.object(app, "CAST_NAMES_PATH", root / "cast_names.json"),
                mock.patch.object(app, "CAST_HISTORY_PATH", root / "cast_names_history.json"),
                mock.patch.object(app, "load_settings", lambda: self.settings),
                mock.patch.object(app, "_cast_save", lambda wait=False: keep(wait=True)),
                mock.patch.object(app, "pipeline_log", lambda *a, **k: None),
                mock.patch.object(app, "note_action", lambda *a, **k: None),
                mock.patch.dict(app._CAST_STATE, {"loaded": False, "rolled": {},
                                                  "rolling": False, "version": 0}),
                mock.patch.dict(app._CAST_HISTORY, {"loaded": True, "seen": {}}),
                mock.patch.dict(app._CAST_RENAME_TICK, {"at": 0.0})):
            patch.start()
            self.addCleanup(patch.stop)
        for memo in (app._CAST_MEMO,):
            memo.clear()
        app._CAST_OVERLAY[0] = None
        app._CAST_PERSONA_MEMO[0] = None
        app._CAST_GONE_MEMO[0] = None

    def use(self, **dj):
        self.settings = app.validate_settings(dict(app.DEFAULT_SETTINGS, dj=dict(self.settings["dj"], **dj)))
        app._CAST_MEMO.clear()
        return self.settings["dj"]


class Personas(Base):
    def test_the_cohost_persona_says_his_name(self):
        self.use(cohost_persona="You are Skip, the co-host. Fond of the host.",
                 cohost_name="Rex", cohost_name_mode="custom")
        got = app.dj_settings()
        self.assertEqual(got["cohost_persona"], "You are Rex, the co-host. Fond of the host.")
        self.assertIn("You are Skip", self.settings["dj"]["cohost_persona"])   # stored as written

    def test_the_default_persona_follows_a_rolled_name(self):
        self.use(cohost_name_mode="random", cohost_name_pool="Rex")
        self.assertTrue(app.dj_settings()["cohost_persona"].startswith("You are Rex, the co-host"))


class SamByName(Base):
    def test_the_board_joins_in_names_him(self):
        got = app.bombshell_angle("the moon is cheese", "the board joins in")
        self.assertIn("Sam, the SFX guy behind the glass", got)
        self.use(sfxguy_name="Gus", sfxguy_name_mode="custom")
        self.assertIn("Gus, the SFX guy behind the glass",
                      app.bombshell_angle("the moon is cheese", "the board joins in"))

    def test_the_flow_instruction_names_him(self):
        got = app.schedule_flow_clause({"flow": [{"type": "sfx", "seconds": 6}]})
        self.assertIn("Sam, the SFX guy, plays", got)

    def test_his_writers_ask_for_his_name(self):
        for fn in (app._sfx_verdict, app._sfxguy_news_fill, app.drop_liner_brew):
            self.assertIn("cast_name('sfxguy')", inspect.getsource(fn), fn.__name__)
        src = inspect.getsource(app)
        self.assertEqual(src.count("the SFX guy — a thick-accented country boy"), 2)

    def test_the_director_beat_names_him(self):
        import director
        if not hasattr(director, "director_beat_words"):
            self.skipTest("tools/cast_names2_modules_patch.py is not applied to director.py")
        self.assertIs(director.CAST_NAME, app.cast_name)
        self.assertTrue(director.director_beat_words("sfx").startswith("Sam, the SFX guy"))


class TheGateAndTheDesk(Base):
    def test_dialogue_row_ready_consults_the_gate(self):
        self.assertIn("cast_names_row_blocked", inspect.getsource(app.dialogue_row_ready))
        row = {"text": "Sam on the air.", "key": "k"}
        with mock.patch.object(app, "dialogue_tint_ready", lambda kind, r: True), \
                mock.patch.object(app, "dialogue_audio_ready", lambda kind, r: True):
            with mock.patch.object(app, "cast_names_row_blocked", lambda kind, r: False):
                self.assertTrue(app.dialogue_row_ready("station_id", row))
            with mock.patch.object(app, "cast_names_row_blocked", lambda kind, r: True):
                self.assertFalse(app.dialogue_row_ready("station_id", row))

    def test_a_held_read_is_rerecorded_with_the_new_name(self):
        row = {"kind": "station_id", "text": "Sam on Pine Box FM.", "voice": "vl_drop",
               "key": "old", "seconds": 2.0, "at": 1.0}
        shelf = {"station_id": [row]}

        async def render(text, who, voice, kind=""):
            return {"key": "new-" + text, "voice": voice, "engine": "xtts", "seconds": 2.5}

        with mock.patch.object(app, "_SHELF", shelf), mock.patch.object(app, "_LARDER", []), \
                mock.patch.object(app, "prep_render_line", render), \
                mock.patch.object(app, "_recast_have_fn", lambda key: None), \
                mock.patch.object(app, "render_relief", lambda: False), \
                mock.patch.object(app, "prep_should_stop", lambda: ""), \
                mock.patch.object(app, "_larder_save", lambda: None), \
                mock.patch.object(app, "_pantry_save", lambda *a: None):
            asyncio.run(app.cast_rename_tick(force=True))        # stamped: Dill / Skip / Sam
            self.assertEqual(row["cast_names"]["sfxguy"], "Sam")
            self.use(sfxguy_name="Gus", sfxguy_name_mode="custom")
            self.assertTrue(app.cast_names_row_blocked("station_id", row))
            got = asyncio.run(app.cast_rename_tick(force=True))
            self.assertEqual(got["swaps"], 1)
            self.assertEqual((row["text"], row["key"]), ("Gus on Pine Box FM.", "new-Gus on Pine Box FM."))
            self.assertFalse(app.cast_names_row_blocked("station_id", row))
            self.assertEqual(app.cast_rename_state()["held"], 0)


class Callers(Base):
    def test_the_draw_never_hands_out_a_cast_name(self):
        book = {"pools": {"p": {"label": "p", "weight": 1.0, "enabled": True,
                                "names": ["Skip", "Sam", "Dill", "Skip Jones", "Bob", "Ann"]}}}
        with mock.patch.object(app, "name_book", lambda: book), \
                mock.patch.object(app, "read_callers", lambda: []), \
                mock.patch.dict(app._RADIO, {"names_used": []}):
            for _ in range(40):
                name, _pool = app.name_draw()
                self.assertIn(name, ("Bob", "Ann"))

    def test_conjure_draws_again_rather_than_ring_a_cast_name(self):
        draws = iter([("Sam", "p"), ("Skip", "p"), ("Bob", "p")])
        with mock.patch.object(app, "name_draw", lambda: next(draws)):
            self.assertEqual(app.conjure_caller()["name"], "Bob")

    def test_the_dictionary_draw_and_the_editor(self):
        with mock.patch.object(app, "caller_names_raw", lambda: ["Sam", "Tammy"]):
            self.assertEqual(app.caller_names(), ["Tammy"])


if __name__ == "__main__":
    unittest.main()
