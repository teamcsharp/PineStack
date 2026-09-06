"""#1064: the roads that still spoke plain - the SFX guy, the emergency
continuity lines and the listening responses - go through the crystal."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from response_bank import ResponseBank, add_listening_responses


class UniverseRoadsTests(unittest.IsolatedAsyncioTestCase):
    def test_a_plain_response_never_serves_under_a_crystal(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "media"
            media.mkdir()
            (media / "plain.wav").write_bytes(b"x")
            (media / "bar.wav").write_bytes(b"x")
            bank = ResponseBank(Path(tmp) / "bank.json", media)
            self.assertTrue(bank.put("v", "xtts", "I'm listening.", "listening",
                                     {"path": "/voice/plain.wav", "seconds": 1.0}, {}))
            self.assertTrue(bank.put("v", "xtts", "I'm listening.", "listening",
                                     {"path": "/voice/bar.wav", "seconds": 1.2},
                                     {"said": "I'm all ears, no fears, spit it here.",
                                      "crystal": "DOOM:doom"}))
            self.assertEqual([r["text"] for r in bank.ready("v", "xtts")], ["I'm listening."])
            self.assertEqual([r.get("said") for r in bank.ready("v", "xtts", "DOOM:doom")],
                             ["I'm all ears, no fears, spit it here."])
            self.assertIsNone(bank.take("v", "xtts", "anything", crystal="OTHER:x"))
            chosen = bank.take("v", "xtts", "anything", crystal="DOOM:doom")
            self.assertEqual(chosen["said"], "I'm all ears, no fears, spit it here.")
            # The fixed acknowledgments are only owed to the plain repertoire.
            self.assertTrue(any(r["text"] == "Go on." for r in bank.missing_entries("v", "xtts")))
            self.assertFalse(any(r["text"] == "Go on."
                                 for r in bank.missing_entries("v", "xtts", crystal="DOOM:doom")))

    def test_the_playlist_speaks_the_bar(self):
        playlist = [{"who": "dj", "chunk": "x" * 300, "turn_end": False},
                    {"who": "dj", "chunk": "more", "turn_end": True}]
        voices = {"dj": "a", "cohost": "b"}
        got = add_listening_responses(
            playlist, voices,
            lambda who, ctx, used: {"text": "Go on.", "said": "Keep it flowin'.",
                                    "clip": {"path": "/voice/c.wav"}})
        spoken = [i for i in got if i.get("listening_response")]
        self.assertEqual(spoken[0]["chunk"], "Keep it flowin'.")

    def test_continuity_is_keyed_by_crystal_and_picked_by_plain_text(self):
        with (mock.patch.object(app, "_CONTINUITY_BANK", {}),
              mock.patch.object(app, "_CONTINUITY_LOADED", [True]),
              mock.patch.object(app, "voice_engine_for", return_value="xtts"),
              mock.patch.object(app, "continuity_crystal", return_value="DOOM:doom"),
              tempfile.TemporaryDirectory() as tmp):
            (Path(tmp) / "c.wav").write_bytes(b"x")
            with mock.patch.object(app, "VOICE_MEDIA_DIR", Path(tmp)):
                key = app.continuity_key("dj", "v", "xtts", "Stay with us.", "DOOM:doom")
                app._CONTINUITY_BANK[key] = {
                    "who": "dj", "voice": "v", "engine": "xtts",
                    "text": "Stay in the mix, we fix the tricks.", "plain": "Stay with us.",
                    "crystal": "DOOM:doom", "clip": {"path": "/voice/c.wav", "seconds": 2.0}}
                row = app.continuity_pick("dj", "v", "Stay with us.")
                self.assertIsNotNone(row)
                self.assertEqual(row["text"], "Stay in the mix, we fix the tricks.")
                with mock.patch.object(app, "continuity_crystal", return_value=""):
                    self.assertIsNone(app.continuity_pick("dj", "v", "Stay with us."))

    def test_continuity_crystal_is_empty_when_the_pass_is_off(self):
        with mock.patch.object(app, "dialogue_tint_wanted", return_value=False):
            self.assertEqual(app.continuity_crystal(), "")
        with (mock.patch.object(app, "dialogue_tint_wanted", return_value=True),
              mock.patch.object(app, "_crystal_vocab_key", return_value="DOOM:doom")):
            self.assertEqual(app.continuity_crystal(), "DOOM:doom")


if __name__ == "__main__":
    unittest.main()
