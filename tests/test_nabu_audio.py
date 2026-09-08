import array
import hashlib
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import wave
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg
from mutagen.flac import FLAC
from nabu_audio import NabuAudioCache, gain, level


class NabuAudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "original.wav"
        samples = array.array("h", (round((4000 if i < 24000 else 12000)
                              * math.sin(2 * math.pi * 400 * i / 24000))
                              for i in range(48000)))
        with wave.open(str(self.source), "wb") as f:
            f.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            f.writeframes(samples.tobytes())
        self.original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.cache = NabuAudioCache(Path(self.tmp.name) / "cache")

    def pcm(self, path):
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error",
            "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
            capture_output=True, check=True, timeout=10)
        samples = array.array("h")
        samples.frombytes(result.stdout)
        return samples

    def test_settings_keep_music_and_speech_gains_independent(self):
        settings = {"music_box_level": .35, "nabu_voice_level": 1,
                    "nabu_reply_level": .25}
        self.assertEqual(gain(settings, "music"), .35)
        self.assertEqual(gain(settings, "voice"), 2)
        self.assertEqual(gain(settings, "reply"), .5)
        self.assertEqual(gain({}, "voice"), 1)
        settings["nabu_music_level"] = 0
        self.assertEqual(gain(settings, "music"), 0)
        self.assertEqual(gain(settings, "voice"), 2)
        self.assertEqual(level({"nabu_voice_level": float("nan")}, "voice"), .5)

    def test_actual_device_flac_gain_offset_and_original_preservation(self):
        path = self.cache.prepare(self.source, .25, channels=2, offset=1)
        info = FLAC(path).info
        self.assertEqual((info.sample_rate, info.channels, info.bits_per_sample), (48000, 2, 16))
        self.assertAlmostEqual(info.length, 1, places=2)
        samples = self.pcm(path)
        rms = math.sqrt(sum(x*x for x in samples) / len(samples))
        self.assertAlmostEqual(rms, 12000 * .25 / math.sqrt(2), delta=30)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_hash)

    def test_speech_boost_and_zero_gain_apply_to_existing_recording(self):
        unity = self.pcm(self.cache.prepare(self.source, 1))[:48000]
        boost = self.pcm(self.cache.prepare(self.source, 2))[:48000]
        self.assertAlmostEqual(sum(abs(x) for x in boost) / sum(abs(x) for x in unity), 2, delta=.03)
        silence = self.pcm(self.cache.prepare(self.source, 0))
        self.assertTrue(silence)
        self.assertEqual(max(abs(x) for x in silence), 0)

    def test_cache_reuses_exact_derivative_without_reencoding(self):
        path = self.cache.prepare(self.source, .4)
        with mock.patch.object(self.cache, "runner", side_effect=AssertionError("reencoded")):
            self.assertEqual(self.cache.prepare(self.source, .4), path)

    def test_announcement_replacement_is_actual_short_silent_native_flac(self):
        path = self.cache.silence()
        info = FLAC(path).info
        self.assertEqual((info.sample_rate, info.channels, info.bits_per_sample), (48000, 1, 16))
        self.assertAlmostEqual(info.length, .2, places=2)
        samples = self.pcm(path)
        self.assertTrue(samples)
        self.assertEqual(max(abs(x) for x in samples), 0)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_hash)
        with mock.patch.object(self.cache, "runner", side_effect=AssertionError("unnecessary re-encode")):
            self.assertEqual(self.cache.silence(), path)

    def test_emergency_silence_never_waits_for_music_conversion_or_cache_eviction(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            self.cache.lock.acquire()
            try:
                path = executor.submit(self.cache.silence).result(timeout=1)
            finally:
                self.cache.lock.release()
        self.cache.max_files = 1
        for amplitude in (.2, .3):
            self.cache.prepare(self.source, amplitude)
        self.assertTrue(path.is_file())
        self.assertEqual(max(abs(x) for x in self.pcm(path)), 0)

    def test_boost_limits_full_scale_peaks_without_truncating_duration(self):
        samples = array.array("h", (round(24000 * math.sin(2 * math.pi * 400 * i / 24000))
                                   for i in range(24000)))
        with wave.open(str(self.source), "wb") as f:
            f.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            f.writeframes(samples.tobytes())
        original = self.source.read_bytes()
        output = self.cache.prepare(self.source, 2)
        peak = max(abs(x) for x in self.pcm(output))
        self.assertGreater(peak, 30000)
        self.assertLessEqual(peak, 32114)  # .98 full scale, rounded signed PCM16
        self.assertAlmostEqual(FLAC(output).info.length, 1, places=2)
        self.assertEqual(self.source.read_bytes(), original)

    def test_superseded_gain_does_not_publish_partial_derivative(self):
        checks = iter((True, False))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.cache.prepare(self.source, .3, valid=lambda: next(checks))
        self.assertEqual(list(self.cache.directory.glob("*.flac")), [])
        self.assertEqual(list(self.cache.directory.glob("*.part")), [])

    def test_failed_encoder_keeps_original_and_no_cache_file(self):
        self.cache.runner = mock.Mock(return_value=mock.Mock(returncode=1))
        with self.assertRaisesRegex(ValueError, "conversion failed"):
            self.cache.prepare(self.source, .2)
        self.assertEqual(list(self.cache.directory.iterdir()), [])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_hash)

    def test_overflow_only_retires_derived_cache(self):
        self.cache.max_files = 2
        for amplitude in (.2, .3, .4):
            self.cache.prepare(self.source, amplitude)
        self.assertEqual(len(list(self.cache.directory.glob("*.flac"))), 2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_hash)


if __name__ == "__main__":
    unittest.main()
