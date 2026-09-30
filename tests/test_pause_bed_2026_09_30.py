# -*- coding: utf-8 -*-
"""[pause-bed] while the station is paused the broadcast airs the endless
set's own clip instead of silence (2026-09-30: listeners heard five hours of
4.5 KB silent segments while the operator heard the set on the tablet).

The pick is pure; the mixer run needs ffmpeg and two video clips, so it is
skipped where the container's clip shelf is not mounted."""
import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import station_stream as ss  # noqa: E402


def row(key, at, slot=3.0, path="/nonexistent.mp4"):
    return {"key": key, "air_at": at, "slot": slot, "length": slot, "path": path}


class PickTest(unittest.TestCase):
    def test_current_and_next(self):
        rows = [row("a", 100.0), row("b", 103.0)]
        cur, nxt = ss._pause_set_pick(rows, 101.5)
        self.assertEqual(cur["key"], "a")
        self.assertEqual(nxt["key"], "b")

    def test_nothing_before_the_set_starts(self):
        cur, nxt = ss._pause_set_pick([row("a", 100.0)], 90.0)
        self.assertIsNone(cur)
        self.assertIsNone(nxt)

    def test_nothing_after_the_last_slot(self):
        cur, _ = ss._pause_set_pick([row("a", 100.0)], 103.5)
        self.assertIsNone(cur)

    def test_replanned_clip_wins_over_the_withdrawn_one(self):
        rows = [row("old", 100.0, slot=10.0), row("new", 102.0)]
        cur, _ = ss._pause_set_pick(rows, 102.5)
        self.assertEqual(cur["key"], "new")

    def test_bad_rows_are_skipped(self):
        rows = [{"key": "x", "air_at": "soon"}, {"key": "y"}, row("a", 100.0)]
        cur, _ = ss._pause_set_pick(rows, 100.5)
        self.assertEqual(cur["key"], "a")

    def test_missing_file_opens_nothing(self):
        self.assertIsNone(ss._pause_set_open(row("a", 100.0), 0.0))


GLUED = Path("/app/data/sfx/glued")


@unittest.skipUnless(GLUED.is_dir() and len(list(GLUED.glob("*.mp4"))[:2]) == 2,
                     "no clip shelf here (run inside spark-agent)")
class MixerTest(unittest.TestCase):
    def test_paused_mixer_airs_the_set_then_silence(self):
        clips = [str(p) for p in sorted(GLUED.glob("*.mp4"))[:2]]
        t0 = time.time() + 0.5
        rows = [row("set|a|1", t0, path=clips[0]),
                row("set|b|2", t0 + 3.0, path=clips[1])]
        state = {"on": True, "paused": True, "music": None, "clips": [],
                 "pause_set": rows}
        stream = ss.StationStream(lambda: state, bitrate=64)
        got = []
        stream.add_tap(lambda frame, live, info: got.append((time.time(), frame)))
        stream.ensure_running()
        time.sleep(6.5)
        state["pause_set"] = []
        time.sleep(1.5)
        if hasattr(stream, "stop"):
            stream.stop()

        def peak(lo, hi):
            frames = [f for t, f in got if lo <= t < hi]
            if not frames:
                return 0
            return int(np.abs(np.frombuffer(b"".join(frames), dtype="<i2")).max())

        self.assertEqual(peak(0, t0 - 0.1), 0, "silence before the set")
        self.assertGreater(peak(t0 + 0.3, t0 + 5.8), 0, "the set sounds")
        self.assertEqual(peak(t0 + 7.3, t0 + 60), 0, "silence once it empties")
        self.assertGreater(int(stream.stats.get("pause_set_frames") or 0), 0)


if __name__ == "__main__":
    unittest.main()
