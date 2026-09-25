"""Quiet SFX should become audible without crossing the peak ceiling."""

import audioop
import math
import sqlite3
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import app


class QuietSfxNormalizationTests(unittest.TestCase):
    def test_cadence_draw_stays_inside_video_window(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.execute("CREATE TABLE clips (path TEXT, seconds REAL, playable INTEGER, video INTEGER)")
        con.executemany("INSERT INTO clips VALUES (?, ?, ?, ?)", [
            ("/clips/short-a.mp4", 2.0, 1, 1),
            ("/clips/short-b.mp4", 8.0, 1, 1),
            ("/clips/long.mp4", 90.0, 1, 1),
            ("/clips/audio.wav", 4.0, 1, 0),
        ])
        with (mock.patch.object(app, "sfx_db_reader", return_value=con),
              mock.patch.object(app, "sfx_pin_prefix", return_value="")):
            draws = [app.sfx_db_pick_short_video(10.0) for _ in range(30)]
        self.assertTrue(all(row and row[1] <= 10 for row in draws))
        self.assertTrue(all(row[0].suffix == ".mp4" for row in draws))

    def test_quiet_clip_is_boosted_and_peak_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "quiet.wav"
            output = Path(directory) / "levelled.wav"
            samples = [int(100 * math.sin(2 * math.pi * 440 * i / 22050))
                       for i in range(22050)]
            with wave.open(str(source), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(22050)
                handle.writeframes(struct.pack("<%dh" % len(samples), *samples))
            with (mock.patch.object(app, "sfx_is_video", return_value=False),
                  mock.patch.object(app, "sfx_levelled_name", return_value=output),
                  mock.patch.object(app, "box_gain", return_value=1.0)):
                self.assertEqual(app.sfx_levelled(source), output)
            with wave.open(str(output), "rb") as handle:
                frames = handle.readframes(handle.getnframes())
            self.assertGreater(audioop.rms(frames, 2), 1500)
            self.assertLessEqual(audioop.max(frames, 2) / 32767, app.SFX_PEAK + 0.01)


if __name__ == "__main__":
    unittest.main()
