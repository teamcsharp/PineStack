"""[publish-stamp] a line handed to the page carries its clip's own air moment.

Round e0711596 (2026-09-30) aired as three welded renders, strictly one after
another, and the Script view drew them interleaved: every line still wore the
render estimate when page_delivery_apply moved it to `published`, and #1288
froze it there. The clip's honest broadcast_ms - chained behind everything
already sold - never reached the lines.
"""
import unittest

import app


class PublishStamp(unittest.TestCase):

    def setUp(self):
        self.ids = []

    def tearDown(self):
        for did in self.ids:
            app._PAGE_DELIVERIES.pop(did, None)

    def deliver(self, did, start, rows):
        self.ids.append(did)
        app._PAGE_DELIVERIES[did] = {
            "delivery_id": did, "at": start - 30, "state": "published",
            "listeners": {}, "speech": True,
            "clip": {"broadcast_ms": int(start * 1000),
                     "stream": {"length": 40.0, "rows": rows}}}

    def test_line_takes_the_clip_start_plus_its_window(self):
        self.deliver("ps-a", 1_000_100.0, [{"id": "a"}, {"id": "b"}])
        entry = {"id": "b", "aired": "prepared", "air_at": 1_000_000.0,
                 "clip_from": 12.5}
        app.page_delivery_apply(entry, "ps-a")
        self.assertEqual(entry["aired"], "published")
        self.assertAlmostEqual(entry["air_at"], 1_000_112.5)

    def test_a_later_render_sorts_after_the_one_in_front(self):
        # render 1 sounds 0..36 s; render 2 was rendered while it played
        self.deliver("ps-1", 2_000_000.0, [{"id": "x"}, {"id": "y"}])
        self.deliver("ps-2", 2_000_036.0, [{"id": "z"}, {"id": "w"}])
        last_of_1 = {"id": "y", "aired": "prepared", "air_at": 2_000_028.0,
                     "clip_from": 28.0}
        first_of_2 = {"id": "z", "aired": "prepared", "air_at": 2_000_022.0,
                      "clip_from": 0.0}
        app.page_delivery_apply(last_of_1, "ps-1")
        app.page_delivery_apply(first_of_2, "ps-2")
        self.assertLess(last_of_1["air_at"], first_of_2["air_at"])

    def test_a_heard_line_is_not_moved(self):
        self.deliver("ps-h", 3_000_100.0, [{"id": "h"}])
        entry = {"id": "h", "aired": "prepared", "air_at": 3_000_050.0,
                 "air_at_by": "heard", "clip_from": 0.0}
        app.page_delivery_apply(entry, "ps-h")
        self.assertEqual(entry["air_at"], 3_000_050.0)

    def test_a_line_without_a_window_in_a_burst_keeps_its_estimate(self):
        self.deliver("ps-n", 4_000_100.0, [{"id": "p"}, {"id": "q"}])
        entry = {"id": "q", "aired": "prepared", "air_at": 4_000_010.0}
        app.page_delivery_apply(entry, "ps-n")
        self.assertEqual(entry["air_at"], 4_000_010.0)

    def test_a_single_line_clip_starts_at_the_clip(self):
        self.deliver("ps-s", 5_000_100.0, [{"id": "s"}])
        entry = {"id": "s", "aired": "prepared", "air_at": 5_000_010.0}
        app.page_delivery_apply(entry, "ps-s")
        self.assertAlmostEqual(entry["air_at"], 5_000_100.0)


if __name__ == "__main__":
    unittest.main()
