"""[sfx-nosound] A clip with no sound track is noted once, and the cadence's
picture road stops dealing it for its sound.

MEASURED 2026-09-27 16:15Z to 2026-09-28: 123 identical ffmpeg failures,
about every half hour -

    [out#0/wav] Output file does not contain any stream
    Error opening output file /app/data/voice_media/sfx/
        64d00c69528ff1f9-1789333711068352100-src.wav.

- one picture-only .MP4 (samples_grabbed/Rest, 2.2 s of h264, no audio
stream) dealt to _sfx_cadence_video_pick, decoded through _as_wav, refused,
and dealt again: it never aired, so it was never spent, so it was the only
unspent short video in its folder.

These run real ffmpeg on two clips made here (a picture with a sound track
and one without), in a directory of their own - never the station's
voice_media/sfx.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # noqa: BLE001
    FFMPEG = ""


def make_clip(path, with_sound):
    args = [FFMPEG, "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=0.6"]
    if with_sound:
        args += ["-f", "lavfi", "-i",
                 "sine=frequency=440:sample_rate=48000:duration=0.6",
                 "-c:a", "aac", "-b:a", "64k"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.6", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


@unittest.skipUnless(FFMPEG, "no ffmpeg on this box")
class ASoundlessClipIsNotedOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.levelled = root / "levelled"
        (root / "samples").mkdir()
        self.silent = make_clip(root / "samples" / "picture only.MP4", False)
        self.heard = make_clip(root / "samples" / "picture and sound.mp4", True)
        patch = mock.patch.object(app, "SFX_LEVELLED", self.levelled)
        patch.start()
        self.addCleanup(patch.stop)

    def notes(self):
        return sorted(p.name for p in self.levelled.glob("*.nosound"))

    def test_the_decode_runs_once_and_the_note_answers_after(self):
        self.assertIs(app._as_wav(self.silent, timeout=20), self.silent)
        self.assertEqual(len(self.notes()), 1)
        self.assertTrue(app.sfx_soundless(self.silent))
        self.assertIn("no sound track", (self.levelled / self.notes()[0]).read_text())
        with mock.patch.object(app.subprocess, "run",
                               side_effect=AssertionError("decoded it again")):
            for _ in range(3):
                self.assertIs(app._as_wav(self.silent, timeout=20), self.silent)

    def test_a_clip_with_sound_still_decodes_and_is_never_noted(self):
        got = app._as_wav(self.heard, timeout=20)
        self.assertEqual(got.suffix, ".wav")
        self.assertTrue(got.is_file())
        self.assertEqual(self.notes(), [])
        self.assertFalse(app.sfx_soundless(self.heard))

    def test_any_other_failure_is_not_noted_and_is_tried_again(self):
        """A share that did not answer, a decode that ran out of time: the
        next deal may succeed, so nothing is written down."""
        busy = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=4.0)
        with mock.patch.object(app.subprocess, "run", side_effect=busy) as run:
            self.assertIs(app._as_wav(self.silent, timeout=4.0), self.silent)
            self.assertIs(app._as_wav(self.silent, timeout=4.0), self.silent)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.notes(), [])
        self.assertFalse(app.sfx_soundless(self.silent))

    def test_a_replaced_file_is_looked_at_again(self):
        """The note is the file of THAT mtime, like the wav beside it."""
        app._as_wav(self.silent, timeout=20)
        self.assertTrue(app.sfx_soundless(self.silent))
        import os
        stamp = self.silent.stat().st_mtime_ns + 5_000_000_000
        os.utime(self.silent, ns=(stamp, stamp))
        app.sfx_stamp_forget(self.silent)
        self.assertFalse(app.sfx_soundless(self.silent))


@unittest.skipUnless(FFMPEG, "no ffmpeg on this box")
class TheCadenceStopsDealingIt(unittest.TestCase):
    """_sfx_cadence_video_pick: the road that needs a picture's SOUND."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.levelled = root / "levelled"
        (root / "Rest").mkdir()
        self.silent = make_clip(root / "Rest" / "picture only.MP4", False)
        self.heard = make_clip(root / "Rest" / "picture and sound.mp4", True)
        self.spent = []
        self.deals = []

        def deal(_most, rolled=None):
            self.deals.append(1)
            return (self.silent, 0.6) if len(self.deals) % 2 else (self.heard, 0.6)

        for name, value in {
                "SFX_LEVELLED": self.levelled,
                "_s3_dice_live": mock.Mock(return_value=False),
                "sfx_match_on": mock.Mock(return_value=False),
                "sfx_bans": mock.Mock(return_value=set()),
                "sfx_weights": mock.Mock(return_value={}),
                "sting_recent": mock.Mock(return_value=False),
                "sfx_video_on_cooldown": mock.Mock(return_value=False),
                "sfx_cap_seconds": mock.Mock(return_value=600.0),
                "sfx_db_pick_short_video": mock.Mock(side_effect=deal),
                "sfx_is_silent": mock.Mock(return_value=False),
                "sfx_levelled": mock.Mock(side_effect=lambda wav: wav),
                "sfx_level_submit": mock.Mock(),
                "_sfx_video_rotation_mark": mock.Mock(
                    side_effect=lambda keys, folder="": self.spent.extend(keys)),
                "_sfx_video_rotation_mark_clip": mock.Mock(),
                "_sfx_roll_note": mock.Mock()}.items():
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_soundless_deal_is_spent_and_the_sound_goes_on(self):
        got = app._sfx_cadence_video_pick("")
        self.assertIsNotNone(got)
        path, audio, _seconds, _why = got
        self.assertEqual(path, self.heard)
        self.assertEqual(audio.suffix, ".wav")
        # the picture-only clip: noted, and spent for this deck pass
        self.assertTrue(app.sfx_soundless(self.silent))
        self.assertEqual(self.spent, [app.sfx_id(self.silent)])

    def test_the_second_deal_costs_no_ffmpeg(self):
        app._sfx_cadence_video_pick("")
        self.deals.clear()                  # the book deals it first again
        real = app.subprocess.run

        def only_the_sound(args, *a, **k):
            if str(self.silent) in [str(x) for x in args]:
                raise AssertionError("decoded the picture-only clip again")
            return real(args, *a, **k)

        with mock.patch.object(app.subprocess, "run", side_effect=only_the_sound):
            got = app._sfx_cadence_video_pick("")
        self.assertEqual(got[0], self.heard)
        self.assertEqual(self.spent, [app.sfx_id(self.silent)] * 2)


if __name__ == "__main__":
    unittest.main()
