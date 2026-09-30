# -*- coding: utf-8 -*-
"""[mix-lane] a listener dragging the tune page's sliders must not fill the
lane cap with lanes it has left (2026-09-30, #1418-#1420: the fourth mix in a
minute was refused and the phone sat on an empty buffer).

Runs real lanes (ffmpeg) in a scratch spool, so it runs in the container:
    docker exec -w /app spark-agent python3 -m unittest tests.test_mix_lane_2026_09_30
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# A scratch spool and lanes file, set BEFORE the import reads them: a test
# stream must never write the live station's data/hls_lanes.json or spool.
SCRATCH = Path(tempfile.mkdtemp(prefix="mixlane-"))
os.environ["PINEBOX_HLS_SPOOL"] = str(SCRATCH / "spool")
os.environ["STREAM_HLS_LANES"] = str(SCRATCH / "hls_lanes.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import station_stream as ss  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg") or getattr(ss, "_ffmpeg_exe", None),
                     "no ffmpeg here")
class MixLaneTest(unittest.TestCase):
    def setUp(self):
        self.stream = ss.StationStream(
            lambda: {"on": False, "paused": False, "music": None, "clips": []},
            bitrate=64)
        self.assertTrue(str(self.stream._hls_root).startswith(str(SCRATCH)),
                        "the test stream must spool in its scratch dir")
        self.mixes = [(10 * i, 100, 100) for i in range(1, ss.HLS_MAX_LANES + 1)]

    def tearDown(self):
        for mix in self.mixes + [(5, 5, 5)]:
            try:
                self.stream.hls_release(mix=mix)
            except Exception:  # noqa: BLE001
                pass
        if hasattr(self.stream, "stop"):
            self.stream.stop()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_cap_refuses_then_release_frees_a_slot(self):
        for mix in self.mixes:
            self.assertFalse(self.stream.hls_lane(False, mix).retired)
        # every lane was asked for just now: busy, so the next is refused
        refused = self.stream.hls_lane(False, (5, 5, 5))
        self.assertTrue(refused.retired)
        self.assertIn("busy", refused.last_error)
        # the listener that LEFT a lane releases it: the next mix gets in
        self.assertTrue(self.stream.hls_release(mix=self.mixes[0]))
        admitted = self.stream.hls_lane(False, (5, 5, 5))
        self.assertFalse(admitted.retired)

    def test_default_and_unknown_lanes_are_never_released(self):
        self.assertFalse(self.stream.hls_release(mix=(100, 100, 100)))
        self.assertFalse(self.stream.hls_release(mix=(1, 2, 3)))


if __name__ == "__main__":
    unittest.main()
