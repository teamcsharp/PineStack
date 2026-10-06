"""Real browser codec conversion and seekable HTTP byte ranges."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import browser_video as video


class FeedTests(unittest.TestCase):
    def test_first_poll_without_known_lag_retains_the_audio_cushions_picture(self):
        rows = [{"ts": 1000 + delay, "broadcast_ms": 100000 - delay * 1000,
                 "url": "/sfx/0123456789abcdef?t=signed", "video": True,
                 "seconds": 2} for delay in (30, 45)]
        got = video.listener_video_rows(rows, 100000, lag_ms=0)
        self.assertEqual(len(got), 2)
        self.assertEqual({row["broadcast_ms"] for row in got}, {55000, 70000})

    def test_full_delayed_queue_preserves_repeated_clips_and_seek_bounds(self):
        rows = [{"ts": 1000 + i, "broadcast_ms": 100000 + i * 800,
                 "url": "/sfx/0123456789abcdef?t=signed", "video": True,
                 "from": 1.5, "to": 2.3, "seconds": 0.8} for i in range(80)]
        got = video.listener_video_rows(rows, 200000, lag_ms=100000)
        self.assertEqual(len(got), 80)
        self.assertEqual(len({row["id"] for row in got}), 80)
        self.assertEqual(got[0]["seek"], 1.5)
        self.assertEqual(got[0]["to"], 2.3)
        self.assertEqual(got[0]["url"], "/sfx/0123456789abcdef?t=signed&video=browser")

    def test_cut_missing_url_and_audio_are_not_offered(self):
        rows = [{"ts": 100, "url": "/sfx/0123456789abcdef", "video": True},
                {"ts": 200, "url": "", "video": True},
                {"ts": 201, "url": "/media/audio.wav", "video": False}]
        self.assertEqual(video.listener_video_rows(rows, 1000, cut_ms=100), [])

    def test_a_malformed_row_does_not_lose_the_following_picture(self):
        rows = [None, {"ts": "broken", "video": True},
                {"ts": 200, "broadcast_ms": 1000, "seconds": "nan",
                 "url": "http://[broken", "video": True},
                {"ts": 201, "broadcast_ms": 1000, "seconds": 2,
                 "url": "/sfx/0123456789abcdef?t=signed", "video": True}]
        got = video.listener_video_rows(rows, 1000)
        self.assertEqual(got[-1]["sfx_id"], "0123456789abcdef")

    def test_native_video_is_copied_but_ten_bit_and_hevc_are_converted(self):
        for metadata, want in [
            ("Stream #0:0: Video: h264 (High), yuv420p(progressive), 640x360", "copy"),
            ("Stream #0:0: Video: h264 (High 10), yuv420p10le, 640x360", "libx264"),
            ("Stream #0:0: Video: hevc (Main), yuv420p, 640x360", "libx264")]:
            command = video.encode_command(Path("in.mkv"), Path("out.mp4"), "ffmpeg", metadata)
            self.assertEqual(command[command.index("-c:v") + 1], want)
            self.assertIn("+faststart", command)
            self.assertNotIn("pipe:1", command)

    def test_range_parsing_handles_suffix_open_and_invalid_requests(self):
        self.assertEqual(video.byte_range("bytes=10-", 100), (10, 99))
        self.assertEqual(video.byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(video.byte_range("bytes=0-999", 100), (0, 99))
        for raw in ("bytes=100-", "bytes=-0", "bytes=20-10", "bytes=0-1,2-3", "nonsense"):
            with self.assertRaises(ValueError):
                video.byte_range(raw, 100)


class RangeResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_warming_runs_in_background_and_repeated_requests_do_not_queue_it_twice(self):
        finished = asyncio.Event()

        async def prepare(*_args):
            await finished.wait()
            return Path("ready.mp4")

        with mock.patch.object(video, "prepare_browser_video", new=mock.AsyncMock(side_effect=prepare)) as prepare_mock:
            self.assertTrue(video.warm_browser_video(Path("source.mp4"), Path("cache"), "ffmpeg"))
            self.assertFalse(video.warm_browser_video(Path("source.mp4"), Path("cache"), "ffmpeg"))
            await asyncio.sleep(0)
            prepare_mock.assert_awaited_once()
            task = video._WARM_TASKS["source.mp4"]
            finished.set()
            await task
            self.assertNotIn("source.mp4", video._WARM_TASKS)

    async def test_fixed_bytes_are_served_as_ranges_and_rejected_when_outside_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ready.mp4"
            data = bytes(range(256)) * 16
            output.write_bytes(data)
            with mock.patch.object(video, "prepare_browser_video", new=mock.AsyncMock(return_value=output)):
                request = mock.Mock(headers={"range": "bytes=123-456"})
                response = await video.browser_video_response(output, request, Path(temporary), "ffmpeg")
                body = b"".join([chunk async for chunk in response.body_iterator])
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.headers["content-range"], "bytes 123-456/4096")
                self.assertEqual(response.headers["content-length"], "334")
                self.assertEqual(body, data[123:457])
                request.headers = {"range": "bytes=5000-"}
                invalid = await video.browser_video_response(output, request, Path(temporary), "ffmpeg")
                self.assertEqual(invalid.status_code, 416)
                self.assertEqual(invalid.headers["content-range"], "bytes */4096")
                request.headers = {"range": "bytes=123-456", "if-range": '"old-source"'}
                changed = await video.browser_video_response(output, request, Path(temporary), "ffmpeg")
                self.assertEqual(changed.status_code, 200)
                self.assertEqual(changed.headers["content-length"], "4096")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe are required")
class RealConversionTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unsupported_codec_becomes_h264_aac_and_repeated_requests_share_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "legacy.mkv"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000",
                            "-t", "1", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)], check=True)
            prepared, repeated = await asyncio.gather(
                video.prepare_browser_video(source, folder / "cache", "ffmpeg", gain_db=6.5),
                video.prepare_browser_video(source, folder / "cache", "ffmpeg", gain_db=6.5))
            self.assertEqual(prepared, repeated)
            raw = prepared.read_bytes()
            self.assertLess(raw.index(b"moov"), raw.index(b"mdat"))
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(prepared)],
                                   check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout)["streams"]
            picture = next(row for row in streams if row["codec_type"] == "video")
            sound = next(row for row in streams if row["codec_type"] == "audio")
            self.assertEqual((picture["codec_name"], picture["pix_fmt"], sound["codec_name"]),
                             ("h264", "yuv420p", "aac"))
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(prepared), "-f", "null", "-"], check=True)

    async def test_a_silent_video_prepares_even_when_a_nonzero_gain_was_requested(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "silent.mkv"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12",
                            "-t", "1", "-an", "-c:v", "ffv1", str(source)], check=True)
            prepared = await video.prepare_browser_video(source, folder / "cache", "ffmpeg", gain_db=5)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(prepared)],
                                   check=True, capture_output=True, text=True)
            streams = json.loads(probe.stdout)["streams"]
            self.assertEqual(len(streams), 1)
            self.assertEqual(streams[0]["codec_name"], "h264")
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(prepared), "-f", "null", "-"], check=True)


if __name__ == "__main__":
    unittest.main()
