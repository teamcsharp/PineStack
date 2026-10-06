"""[supercut-gallery] 2026-10-06: every archived supercut has a poster frame, made once and kept; the tiles are the videos.

"I want these scrolling pieces of media at the top to be the videos in a slideshow gallery. So when I tap on
them I'm able to play the videos of each and every one of the supercuts made so far."
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sfx_supercut
import sfx_supercut_archive
from sfx_supercut_archive import SupercutArchive


class ThePosterRoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.made = []

        def make(video, out):
            self.made.append((video, out))
            out.write_bytes(b"\xff\xd8\xff" + b"0" * 64)
        self.host = {"DATA_DIR": self.root, "SFX_ADS_DIR": self.root / "sfx_ads", "media_sign": lambda key: "signed-" + key,
                     "poster_make": make}
        self.archive = SupercutArchive(self.host)
        self.video = self.root / "supercut-" + "a" * 24 + ".mp4" if False else self.root / ("supercut-" + "a" * 24 + ".mp4")
        self.video.write_bytes(b"mp4" * 10)
        self.archive.video = lambda identifier: self.video
        self.archive.identity = lambda identifier: str(identifier)

    def test_decorate_adds_the_poster_url_beside_the_video_url_signed_alike(self):
        row = {"metadata": json.dumps({"id": "sca-x", "video_name": "supercut-" + "a" * 24 + ".mp4"}), "reusable_ad_id": ""}
        got = self.archive.decorate(row)
        self.assertEqual(got["video_url"], "/api/sfx/supercut/archive/sca-x/video?t=signed-sca-x")
        self.assertEqual(got["poster_url"], "/api/sfx/supercut/archive/sca-x/poster?t=signed-sca-x")
        plain = self.archive.decorate({"metadata": json.dumps({"id": "sca-y"}), "reusable_ad_id": ""})
        self.assertNotIn("poster_url", plain, "a cut with no video has no frame")
        self.assertNotIn("video_url", plain)

    def test_the_frame_is_made_once_and_kept(self):
        out = self.archive.poster("sca-x")
        self.assertEqual(out, self.root / "sfx_ads" / "supercuts" / "posters" / "sca-x.jpg")
        self.assertTrue(out.is_file())
        self.assertEqual(len(self.made), 1)
        again = self.archive.poster("sca-x")
        self.assertEqual(again, out)
        self.assertEqual(len(self.made), 1, "the second ask reads the kept frame")

    def test_a_cut_without_a_video_has_no_frame(self):
        self.archive.video = mock.Mock(side_effect=ValueError("This historical archive has no MP4 video"))
        with self.assertRaises(ValueError):
            self.archive.poster("sca-old")
        self.assertEqual(self.made, [])

    def test_an_empty_frame_is_refused(self):
        self.host["poster_make"] = lambda video, out: out.write_bytes(b"")
        with self.assertRaises(ValueError):
            self.archive.poster("sca-z")

    def test_poster_frame_asks_ffmpeg_for_one_scaled_frame(self):
        out = self.root / "p" / "x.jpg"
        out.parent.mkdir()
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"jpg")
        fake_imageio = mock.Mock()
        fake_imageio.get_ffmpeg_exe = lambda: "/bin/ffmpeg-x"
        with mock.patch.dict("sys.modules", {"imageio_ffmpeg": fake_imageio}), mock.patch("subprocess.run", run):
            got = sfx_supercut_archive.poster_frame(self.video, out, at=1.0, width=480)
        self.assertEqual(got, out)
        self.assertTrue(out.is_file())
        cmd = calls[0]
        self.assertEqual(cmd[0], "/bin/ffmpeg-x")
        self.assertIn("-frames:v", cmd)
        self.assertIn("scale=480:-2", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], str(self.video))
        self.assertTrue(str(cmd[-1]).endswith(".tmp.jpg"), "written beside, then renamed")

    def test_the_route_is_mounted_like_the_video_s(self):
        src = Path(sfx_supercut.__file__).read_text(encoding="utf-8")
        self.assertIn("@app.get('/api/sfx/supercut/archive/{identifier}/poster')", src)
        body = src.split("archive/{identifier}/poster')", 1)[1].split("@app.post", 1)[0]
        self.assertIn("runtime.archive.poster", body)
        self.assertIn("media_type='image/jpeg'", body)
        self.assertIn("hmac.compare_digest", body, "signed like the video, else read auth")
        self.assertIn("HTTPException(404", body)


if __name__ == "__main__":
    unittest.main()
