"""#1064: the LCD's paused-state cupboard view, and the rule with no stopgap."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class CupboardTests(unittest.TestCase):
    def test_the_cupboard_lists_every_stored_round_line_by_line(self):
        bar = ("Before midnight, the station needs that copper plate; "
               "operation meets calibration to settle the wait.")
        entry = {"prep_kind": "banter", "label": "booth rounds", "at": 5.0,
                 "script": "A: " + bar + "\nB: The plain second line has no rhyme at all.",
                 "script_tinted": "A: " + bar + "\nB: The plain second line has no rhyme at all.",
                 "use": "tinted", "made": 2, "chunks": 2, "keys": ["k1", "k2"],
                 "tint": {"ok": True, "coverage": {"met": True, "version": 4, "cut": 1,
                                                    "target": 100, "strength": 1.0}}}
        with (mock.patch.object(app, "_SHELF", {"manager": [{"entry": dict(entry, prep_kind="manager", label="memos")}]}),
              mock.patch.object(app, "_LARDER", [entry]),
              mock.patch.object(app, "_CUPBOARD_MEMO", {"at": 0.0, "value": None}),
              mock.patch.object(app, "dialogue_row_ready", return_value=True),
              mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.object(app, "crystal_active", return_value=[{"name": "DOOM"}]),
              mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "writing_room_state", return_value={"active": 1, "waiting": 0, "jobs": []}),
              mock.patch.object(app, "_PREP_NOW", {"kind": "gallery", "stage": "waiting for tint"}),
              mock.patch.object(app, "_TINT_JUDGE_RING", [{"ok": False, "candidate": "x", "faults": ["no rhyme evidence"]}]),
              mock.patch.dict(app._RADIO, {"pipeline": [{"ts": 1, "kind": "crystal", "text": "(#1064) turn 2 is cut before the studio"}]})):
            got = app.cupboard_state()
            again = app.cupboard_state()
        self.assertIs(got, again)                      # memoised for the LCD's polling
        self.assertTrue(got["paused"])
        self.assertEqual(got["tint"]["crystals"], ["DOOM"])
        self.assertEqual(len(got["rounds"]), 2)
        first = got["rounds"][0]
        self.assertEqual(first["state"], "ready")
        self.assertEqual(first["grade"], "rhyme")
        self.assertEqual(first["cut"], 1)
        self.assertEqual([l["who"] for l in first["lines"]], ["HOST", "SKIP"])
        self.assertTrue(first["lines"][0]["rhyme"])
        self.assertFalse(first["lines"][1]["rhyme"])
        self.assertEqual(got["preparing"]["kind"], "gallery")
        self.assertEqual(got["feed"][-1]["kind"], "crystal")
        self.assertEqual(got["judgements"][-1]["faults"], ["no rhyme evidence"])

    def test_every_verdict_lands_on_the_ring(self):
        with (mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
              mock.patch.object(app, "_TINT_JUDGE_RING", [])):
            app.tint_evaluate("The station needs a copper plate.", "The station needs a copper plate.", [], force=0.9)
            self.assertEqual(len(app._TINT_JUDGE_RING), 1)
            self.assertFalse(app._TINT_JUDGE_RING[0]["ok"])

    def test_no_plain_continuity_while_a_crystal_is_on(self):
        with (mock.patch.object(app, "_CONTINUITY_BANK", {}),
              mock.patch.object(app, "_CONTINUITY_LOADED", [True]),
              mock.patch.object(app, "_CONTINUITY_STATE", {}),
              mock.patch.object(app, "voice_engine_for", return_value="xtts"),
              mock.patch.object(app, "continuity_crystal", return_value="DOOM:doom"),
              tempfile.TemporaryDirectory() as tmp):
            (Path(tmp) / "c.wav").write_bytes(b"x")
            with mock.patch.object(app, "VOICE_MEDIA_DIR", Path(tmp)):
                app._CONTINUITY_BANK[app.continuity_key("dj", "v", "xtts", "Stay with us.")] = {
                    "who": "dj", "voice": "v", "engine": "xtts", "text": "Stay with us.",
                    "clip": {"path": "/voice/c.wav", "seconds": 2.0}}
                self.assertIsNone(app.continuity_pick("dj", "v", "Stay with us."))
                app._CONTINUITY_BANK[app.continuity_key("dj", "v", "xtts", "Stay with us.", "DOOM:doom")] = {
                    "who": "dj", "voice": "v", "engine": "xtts", "text": "Stay in the mix.",
                    "plain": "Stay with us.", "crystal": "DOOM:doom",
                    "clip": {"path": "/voice/c.wav", "seconds": 2.0}}
                row = app.continuity_pick("dj", "v", "Stay with us.")
                self.assertEqual(row["text"], "Stay in the mix.")
                self.assertFalse(row["stopgap"])


if __name__ == "__main__":
    unittest.main()
