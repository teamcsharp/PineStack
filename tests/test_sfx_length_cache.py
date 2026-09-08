"""Duration scans retain the real grab library without whole-cache resets."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import wave

import app


class SfxLengthCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "clip.wav"
        self.write_wav(1)
        for patcher in (mock.patch.object(app, "_SFX_LEN_CACHE", {}),
                        mock.patch.object(app, "_SFX_LEN_DIRTY", [0]),
                        mock.patch.object(app, "_sfx_len_save")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_wav(self, seconds):
        with wave.open(str(self.path), "wb") as handle:
            handle.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            handle.writeframes(b"\0\0" * (8000 * seconds))

    def test_full_grab_library_survives_next_measurement_and_cache_hit(self):
        app._SFX_LEN_CACHE.update({f"/samples/grabs/{i}:1": 2.0
                                   for i in range(15761)})
        self.assertEqual(app.sfx_seconds(self.path), 1.0)
        self.assertEqual(len(app._SFX_LEN_CACHE), 15762)
        self.assertEqual(app._SFX_LEN_CACHE["/samples/grabs/0:1"], 2.0)
        with mock.patch.object(wave, "open", side_effect=AssertionError("redecoded")):
            self.assertEqual(app.sfx_seconds(self.path), 1.0)

    def test_overflow_evicts_only_oldest_reading(self):
        app._SFX_LEN_CACHE.update({f"old-{i}": 2.0
                                   for i in range(app.SFX_LEN_CACHE_MAX)})
        self.assertEqual(app.sfx_seconds(self.path), 1.0)
        self.assertEqual(len(app._SFX_LEN_CACHE), app.SFX_LEN_CACHE_MAX)
        self.assertNotIn("old-0", app._SFX_LEN_CACHE)
        self.assertIn("old-1", app._SFX_LEN_CACHE)
        self.assertIn(f"old-{app.SFX_LEN_CACHE_MAX - 1}", app._SFX_LEN_CACHE)

    def test_replaced_file_is_measured_using_new_mtime(self):
        self.assertEqual(app.sfx_seconds(self.path), 1.0)
        old = self.path.stat().st_mtime_ns
        self.write_wav(2)
        os.utime(self.path, ns=(old + 1_000_000, old + 1_000_000))
        self.assertEqual(app.sfx_seconds(self.path), 2.0)
        self.assertEqual(len(app._SFX_LEN_CACHE), 2)


if __name__ == "__main__":
    unittest.main()
