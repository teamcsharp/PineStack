"""Real local concat preserves the source performance and optional row order."""
import asyncio
from contextlib import ExitStack
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import wave

import app


class SingleClipCadenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app, "VOICE_MEDIA_DIR", self.root))
        self.stack.enter_context(mock.patch.object(app, "_sfx_cadence_enabled", return_value=True))
        self.stack.enter_context(mock.patch.object(app, "_SFX_CADENCE", mock.Mock(state=lambda: {"heard_units": 3})))
        self.stack.enter_context(mock.patch.object(app, "_SFX_CADENCE_PLAN_UNITS", [3]))
        self.release = self.stack.enter_context(mock.patch.object(app, "_sfx_cadence_release"))
        self.model = self.stack.enter_context(mock.patch.object(app, "ask_model", mock.AsyncMock(side_effect=AssertionError("No model"))))
        self.tts = self.stack.enter_context(mock.patch.object(app, "voice_render_any", mock.AsyncMock(side_effect=AssertionError("No TTS"))))
        self.host = self.wav("a" * 32 + ".wav", 331, 1.0)
        self.sample = self.wav("sample.wav", 903, .4)
        self.guy = self.wav("guy.wav", 631, .7)
        self.clip = {"path": "/media/" + self.host.name, "sig": "original", "engine": "xtts", "voice": "host-voice", "ms": 1934}
        self.extras = [{"path": str(self.sample), "who": "board", "text": "Sample", "seconds": 1.3, "sfx_sample_id": "sample-id"},
                       {"path": str(self.guy), "who": "drop", "voice": "actual-guy", "text": "I hear you clear, keep talking here.", "seconds": 1.6, "sfxguy_reservation": "reserved-guy"}]
        self.additions = self.stack.enter_context(mock.patch.object(app, "_sfx_cadence_additions", mock.AsyncMock(return_value=self.extras)))

        def store(raw):
            (self.root / ("b" * 32 + ".wav")).write_bytes(raw)
            return {"path": "/media/" + "b" * 32 + ".wav", "sig": "mixed", "bytes": len(raw)}
        self.stack.enter_context(mock.patch.object(app, "_store_media", side_effect=store))

    def wav(self, name, frequency, seconds):
        path = self.root / name
        with wave.open(str(path), "wb") as out:
            out.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            frames = [int(5000 * math.sin(2 * math.pi * frequency * i / 24000)) for i in range(int(seconds * 24000))]
            frames += [0] * 21600
            out.writeframes(struct.pack("<" + "h" * len(frames), *frames))
        return path

    async def test_real_concat_keeps_host_audio_first_and_exact_extra_voices_in_order(self):
        original = self.host.read_bytes()
        clip, stream = await app._sfx_single_clip(self.clip, "The complete original host words.", "dj", "host-voice", "interject", "host-id")
        self.assertEqual(self.host.read_bytes(), original)
        self.assertEqual((clip["voice"], clip["engine"], clip["ms"]), ("host-voice", "xtts", 1934))
        self.assertEqual([row["who"] for row in stream["rows"]], ["dj", "board", "drop"])
        self.assertEqual([row["id"] for row in stream["rows"]], ["host-id", "host-id-punct-1", "host-id-punct-2"])
        self.assertEqual(stream["rows"][0]["text"], "The complete original host words.")
        self.assertEqual(stream["rows"][2]["voice"], "actual-guy")
        self.assertEqual(stream["rows"][2]["sfxguy_reservation"], "reserved-guy")
        self.assertGreater(stream["length"], 3)
        self.assertLessEqual(stream["rows"][-1]["until"], stream["length"])
        for first, second in zip(stream["rows"], stream["rows"][1:]):
            self.assertAlmostEqual(first["until"], second["from"])
        # Real output contains the original tone, then sample, then guy.
        with wave.open(str(self.root / ("b" * 32 + ".wav")), "rb") as audio:
            rate = audio.getframerate()
            frames = struct.unpack("<" + "h" * audio.getnframes(), audio.readframes(audio.getnframes()))
        for row, expected in zip(stream["rows"], (331, 903, 631)):
            start = int((row["from"] + .08) * rate)
            part = frames[start:start + int(.18 * rate)]
            crossings = sum(a <= 0 < b for a, b in zip(part, part[1:]))
            self.assertAlmostEqual(crossings / .18, expected, delta=35)
        self.release.assert_not_called()
        self.model.assert_not_awaited()
        self.tts.assert_not_awaited()

    async def test_concat_failure_returns_unchanged_original_and_releases_only_optional_take(self):
        with mock.patch.object(app, "_call_concat_blocking", return_value=None):
            clip, stream = await app._sfx_single_clip(self.clip, "All original words.", "dj", "host-voice", "interject", "host-id")
        self.assertIs(clip, self.clip)
        self.assertEqual(len(stream["rows"]), 1)
        self.assertEqual(stream["rows"][0]["text"], "All original words.")
        self.release.assert_called_once_with(self.extras)
        self.assertFalse((self.root / ("b" * 32 + ".wav")).exists())

    async def test_no_optional_due_still_returns_host_ack_window_without_remixing(self):
        self.additions.return_value = []
        with mock.patch.object(app, "_call_concat_blocking") as concat:
            clip, stream = await app._sfx_single_clip(self.clip, "Words.", "dj", "host-voice", "interject", "host-id")
        self.assertIs(clip, self.clip)
        self.assertEqual(len(stream["rows"]), 1)
        self.assertAlmostEqual(stream["rows"][0]["until"], 1.9, places=1)
        concat.assert_not_called()

    async def test_caller_is_not_an_interjection_slot(self):
        clip, stream = await app._sfx_single_clip(self.clip, "Caller words.", "caller", "caller-voice", "call", "caller-id")
        self.assertIs(clip, self.clip)
        self.assertEqual(stream, {})
        self.additions.assert_not_awaited()

    def test_global_cadence_includes_autonomous_non_sting_lines(self):
        with mock.patch.object(app, "_sfx_cadence_enabled", return_value=True):
            self.assertTrue(app._sfx_single_cadence_wanted(False, False, "manager"))
            self.assertTrue(app._sfx_single_cadence_wanted(False, False, "station_id"))
            self.assertFalse(app._sfx_single_cadence_wanted(False, True, "manager"))
            self.assertFalse(app._sfx_single_cadence_wanted(False, False, "reply"))

        with mock.patch.object(app, "_sfx_cadence_enabled", return_value=False):
            self.assertFalse(app._sfx_single_cadence_wanted(False, False, "manager"))
            self.assertTrue(app._sfx_single_cadence_wanted(True, False, "manager"))


if __name__ == "__main__":
    unittest.main()
