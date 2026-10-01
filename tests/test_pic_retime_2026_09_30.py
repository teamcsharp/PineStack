"""[pic-retime] a resumed clip moves its queued sting pictures instead of adding twins."""
import time
import unittest

import app


class PictureRetime(unittest.TestCase):
    def setUp(self):
        self.ring = list(app._RADIO.get("voice_clips") or [])
        self.updates = dict(app._PAGE_RESERVATION_UPDATES)
        app._RADIO["voice_clips"] = []

    def tearDown(self):
        app._RADIO["voice_clips"] = self.ring
        app._PAGE_RESERVATION_UPDATES.clear()
        app._PAGE_RESERVATION_UPDATES.update(self.updates)

    def rows(self):
        return [{"id": "row-1", "sfx_video_id": "abcdef0123456789", "from": 12.0, "text": "a sting"},
                {"id": "row-2", "text": "a line with no picture"}]

    def pictures(self):
        return [c for c in app._RADIO["voice_clips"] if c.get("picture_only")]

    def test_first_ring_carries_its_own_id(self):
        start = time.time() + 5
        app._sfx_cadence_pictures(self.rows(), start)
        got = self.pictures()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["delivery_id"], "pic:row-1")
        self.assertEqual(got[0]["broadcast_ms"], int((start + 12.0) * 1000))

    def test_a_resumed_page_moves_the_picture_and_adds_no_twin(self):
        first = time.time() + 5
        app._sfx_cadence_pictures(self.rows(), first)
        later = first + 30
        app._sfx_cadence_pictures(self.rows(), later, retime=True)
        got = self.pictures()
        self.assertEqual(len(got), 1, "one picture for one sting")
        self.assertEqual(got[0]["broadcast_ms"], int((later + 12.0) * 1000))
        self.assertEqual(app._PAGE_RESERVATION_UPDATES["pic:row-1"], int((later + 12.0) * 1000))

    def test_a_retime_with_nothing_queued_rings_it(self):
        app._sfx_cadence_pictures(self.rows(), time.time() + 5, retime=True)
        self.assertEqual(len(self.pictures()), 1)


if __name__ == "__main__":
    unittest.main()
