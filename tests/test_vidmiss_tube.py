"""[vidmiss] ONE TUBE: the SFX guy does not ring a picture on top of a picture.

The ring recorded off /api/dj/video on 2026-09-28 (SFX guy at 100% MP4):
c2d58d05 booked 3045.3-3076.4 (31.06 s) and b667d23c booked at 3061.5 while
it was still on the tube. Every set holds one picture, so b667d23c would wait
16 s behind it and be thrown away (the set's LATE is 8 s) - its sound too.

    docker exec spark-agent sh -c "cd /app && python3 -m unittest tests.test_vidmiss_tube"
"""
import asyncio
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app

T0 = 1790650000.0          # the recorded window's seconds are T0 + (s mod 10000)


def ring_row(key, start, seconds, **extra):
    row = {"url": "/sfx/%s?t=x" % key, "video": True, "seconds": seconds,
           "broadcast_ms": int((T0 + start) * 1000), "ts": int((T0 + start - 6) * 1000)}
    row.update(extra)
    return row


class TubeFreeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"voice_clips": [], "voice_cut_ms": 0}
        self.deliveries = {}
        self.stack.enter_context(mock.patch.object(app, "_RADIO", self.radio))
        self.stack.enter_context(mock.patch.object(app, "_PAGE_DELIVERIES", self.deliveries))

    def test_the_recorded_overlap_reads_the_tube_busy_until_the_long_clip_ends(self):
        self.radio["voice_clips"] = [
            ring_row("48f42c7d", 3012.3, 13.75, delivery_id="d1"),
            ring_row("c2d58d05", 3045.3, 31.06, delivery_id="d2"),
            {"url": "/voice/x.wav", "text": "a line", "broadcast_ms": int((T0 + 3050) * 1000),
             "seconds": 90.0, "delivery_id": "d3"},            # speech is not the tube
        ]
        self.deliveries["d2"] = {"state": "playing"}
        free = app.sfx_tube_free_at(now=T0 + 3055.6)          # when b667d23c was picked
        self.assertAlmostEqual(free, T0 + 3045.3 + 31.06, places=2)

    def test_board_pictures_count_and_a_finished_or_refused_picture_holds_nothing(self):
        self.radio["voice_clips"] = [
            ring_row("0e9ce7eb", 2954.4, 5.99, silent_picture=True, picture_only=True, length=5.99),
            ring_row("1c1de84b", 2980.2, 12.28, delivery_id="gone"),
            ring_row("wall", 2990.0, 30.0, endless=True),       # the cycle keeps its own plan
        ]
        self.deliveries["gone"] = {"state": "error"}
        self.assertAlmostEqual(app.sfx_tube_free_at(now=T0 + 2956.0), T0 + 2954.4 + 5.99, places=2)
        self.assertEqual(app.sfx_tube_free_at(now=T0 + 2981.0), 0.0)

    def test_a_cut_programme_holds_nothing(self):
        self.radio["voice_clips"] = [ring_row("old", 100.0, 60.0)]
        self.radio["voice_cut_ms"] = int((T0 + 99.0) * 1000)
        self.assertEqual(app.sfx_tube_free_at(now=T0 + 110.0), 0.0)


class StingWaitsTests(unittest.IsolatedAsyncioTestCase):
    """dj_sting itself, every door around it stubbed: the picture is stamped
    after the one on the tube, or the slot is let go when that is too far."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"voice_clips": [], "voice_cut_ms": 0, "chat": [], "voice_to": "here"}
        self.fed = []
        self.logged = []
        self.now = T0 + 3055.6

        async def seconds(_s):
            return 7.94

        async def level(_s, *_a):
            return (_s, "levelled")

        async def s3_stamp(*_a, **_k):
            return None

        patches = {
            "_RADIO": self.radio, "_PAGE_DELIVERIES": {}, "_PAGE_AIR_UNTIL": [0.0],
            "dj_settings": mock.Mock(return_value={"drop_voice": ""}),
            "sting_recent": mock.Mock(return_value=False),
            "sfx_video_on_cooldown": mock.Mock(return_value=False),
            "sting_remember": mock.Mock(), "sfx_is_video": mock.Mock(return_value=True),
            "sfx_id": mock.Mock(return_value="b667d23c00000000"),
            "media_sign": mock.Mock(return_value="sig"),
            "sfx_match_why_for": mock.Mock(return_value=("", 0.0)),
            "sfx_video_mode_on": mock.Mock(return_value=False),
            "sfx_db_seconds_async": seconds, "sfx_level_for_air": level,
            "_sfx_roll_carry": mock.Mock(), "_s3_loose_board_stamp": s3_stamp,
            "note_activity": mock.Mock(),
            "admission_admit_line": mock.Mock(return_value="occ"),
            "admission_controller": mock.Mock(return_value=None),
            "pipeline_log": lambda *a, **k: self.logged.append(a),
            "sfx_history_add": mock.Mock(), "sfx_note_play": mock.Mock(),
            "sfx_video_note_played": mock.Mock(), "air_at_set": mock.Mock(),
            "_s3_active": mock.Mock(return_value=True),
            "page_feed_append": lambda clip: self.fed.append(clip) or "delivery",
        }
        for name, value in patches.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.stack.enter_context(mock.patch.object(app.time, "time", lambda: self.now))

    async def sting(self):
        return await app.dj_sting(False, after="a line", who="dj",
                                  sample=Path("/samples/vine/84 car. One minute.mp4"))

    async def test_a_picture_is_stamped_after_the_one_on_the_tube(self):
        self.radio["voice_clips"] = [ring_row("c2d58d05", 3045.3, 31.06, delivery_id="d2")]
        got = await self.sting()
        self.assertTrue(got)
        self.assertEqual(len(self.fed), 1)
        want = (T0 + 3045.3 + 31.06 + app.SFX_TUBE_GAP_S) * 1000
        self.assertAlmostEqual(self.fed[0]["broadcast_ms"], want, delta=2)
        self.assertGreaterEqual(self.radio["chat"][-1]["air_at"], T0 + 3076.0)

    async def test_a_free_tube_changes_nothing(self):
        got = await self.sting()
        self.assertTrue(got)
        self.assertNotIn("broadcast_ms", self.fed[0])

    async def test_a_tube_booked_too_far_ahead_lets_the_slot_go(self):
        self.radio["voice_clips"] = [ring_row("long", 3050.0, 300.0, delivery_id="d9")]
        got = await self.sting()
        self.assertEqual(got, "")
        self.assertEqual(self.fed, [])
        self.assertTrue(any("tube is booked" in str(a) for a in self.logged))


if __name__ == "__main__":
    unittest.main()
