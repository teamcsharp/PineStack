"""#1322: EVERY VIDEO CLIP, WHEREVER IT WAS FIRED, ON EVERY SURFACE.

The operator: "when a video clip is played, show a PiP overlay on the
application as well ... the same as on the pinetab where it can be
dragged and relocated and it is an overlay."

Two of the three roads to a picture were already shared, because both go
through the station and land in the ring `/api/dj/video` serves: an SFX
sting with a picture (#1263) and the operator's video button (#1306). The
third does not. A sampler pad holding an mp4 pops its picture with a
LOCAL `PineSfxTv.cut` (#1310) - the clip is already decoded on the pad,
nothing is asked of the station - so a pad pressed on the tablet popped
nothing on the app, and a pad pressed on the app popped nothing on the
tablet. Neither surface had any way to know.

`/api/sfx/video/cut` is that road's door, and `page_picture_append` is
what it rings through. The tests worth having are the ones whose failure
is SILENT:

  * A picture that went through the ordinary feed door would be CHAINED
    behind whatever audio the page has already been promised. It would
    still appear - seconds or minutes after the pad was pressed, over
    whatever was airing by then - and nothing would report it as late.

  * That same door RESERVES the clip's length on top. A performance of
    twenty pad presses would mortgage a minute of the show's air for
    pictures that have already been and gone, and the symptom is a show
    that goes quiet for reasons no desk names.

  * A url that is not the station's own would send every other surface
    to fetch a picture from somewhere nobody vetted, and the only
    evidence would be on the tablet's screen.
"""
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class ThePictureDoor(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"on": True, "voice_clips": [], "chat": [], "voice_cut_ms": 0}
        for name, value in {
            "_RADIO": self.radio, "_PAGE_DELIVERIES": {}, "_PAGE_AIR_UNTIL": [0],
            "_PAGE_RESERVATION_UPDATES": {}, "_CLIP_SECS_CACHE": {},
            "station_flow_event": mock.Mock(),
            "radio_paused": mock.Mock(return_value=False),
            "note_activity": mock.Mock(), "require_auth": mock.Mock(),
            "require_read_auth": mock.Mock(),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def pad(self, **over):
        clip = {"url": "/sfx/pad.mp4?t=sig", "sting": "pad", "id": "pad.mp4",
                "seconds": 2}
        clip.update(over)
        return clip

    # ---------------------------------------------------------------- now

    def promised(self, seconds=40):
        """Forty seconds of real audio the page has already been given.

        Set as a clip in the RING, not as a number in `_PAGE_AIR_UNTIL`:
        page_feed_append repairs that cursor from the ring before it
        stamps anything, so a hand-set figure with no audio behind it is
        wiped on the way in - which is a trap this test fell into first
        time out, and would have read as the feature working.
        """
        self.radio["voice_clips"].append({
            "delivery_id": "promised", "url": "/media/long.wav",
            "seconds": seconds, "ts": 999 * 1000, "broadcast_ms": 1000 * 1000})
        app._PAGE_DELIVERIES["promised"] = {"state": "playing", "listeners": {}}

    def test_a_picture_is_stamped_now_and_never_chained_behind_the_feed(self):
        """The sound is already in the room; the picture cannot wait."""
        self.promised(40)
        with mock.patch.object(app.time, "time", return_value=1000):
            rung = app.page_picture_append(self.pad())
        self.assertEqual(rung["broadcast_ms"], 1000 * 1000)
        self.assertEqual(rung["ts"], 1000 * 1000)

        # ...and the contrast, measured rather than asserted: the SAME
        # clip through page_feed_append IS chained behind those forty
        # seconds, which is right for everything the station is
        # broadcasting and wrong for a clip already sounding.
        with mock.patch.object(app.time, "time", return_value=1000):
            app.page_feed_append(dict(self.pad()))
        self.assertEqual(self.radio["voice_clips"][-1]["broadcast_ms"], 1040 * 1000)

    def test_a_burst_of_pictures_claims_no_more_air_than_one(self):
        """Twenty pad presses must not mortgage a minute of the show.

        Measured against the SAME pass over one picture rather than
        against an arithmetic of its own: the cursor never falls below a
        standing lead floor, so an absolute figure here would pass on a
        door that stacked every clip under that floor and fail the day
        the lead changed.
        """
        with mock.patch.object(app.time, "time", return_value=1000):
            for _ in range(20):
                app.page_picture_append(self.pad())
            app.page_reservation_repair()
            twenty = app._PAGE_AIR_UNTIL[0]

            self.radio["voice_clips"] = []
            app._PAGE_AIR_UNTIL[0] = 0
            app.page_picture_append(self.pad())
            app.page_reservation_repair()
            one = app._PAGE_AIR_UNTIL[0]
        self.assertEqual(twenty, one)

        # And the meter moves: twenty of the same clip through the
        # ordinary door DOES stack, which is what a picture must not do.
        with mock.patch.object(app.time, "time", return_value=1000):
            self.radio["voice_clips"] = []
            app._PAGE_AIR_UNTIL[0] = 0
            for _ in range(20):
                app.page_feed_append(dict(self.pad()))
        self.assertGreater(app._PAGE_AIR_UNTIL[0], one + 20)

    # -------------------------------------------------------------- seen

    async def test_the_rung_picture_comes_back_out_of_the_video_door(self):
        """The door the sets actually poll - not the one we hope they do."""
        with mock.patch.object(app.time, "time", return_value=1000):
            rung = app.page_picture_append(self.pad())
            got = await app.dj_video_api(since=0)
        urls = [c["url"] for c in got["clips"]]
        self.assertEqual(urls, ["/sfx/pad.mp4?t=sig"])
        self.assertTrue(got["clips"][0]["video"])
        # The stamp handed back to the surface that fired it is the one
        # in the ring, or its mark cannot cover its own picture.
        self.assertEqual(got["clips"][0]["ts"], rung["ts"])

    async def test_a_picture_already_seen_is_not_offered_again(self):
        """`since` is how a set says "I have that one"."""
        with mock.patch.object(app.time, "time", return_value=1000):
            rung = app.page_picture_append(self.pad())
            again = await app.dj_video_api(since=rung["ts"])
        self.assertEqual(again["clips"], [])

    # -------------------------------------------------------------- door

    async def test_the_route_rings_the_clip_it_was_handed(self):
        with mock.patch.object(app.time, "time", return_value=1000):
            answer = await app.sfx_video_cut_api(payload=self.pad(
                **{"from": 0.5, "to": 1.8}))
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["clip"]["url"], "/sfx/pad.mp4?t=sig")
        self.assertEqual(answer["clip"]["from"], 0.5)
        self.assertEqual(answer["clip"]["to"], 1.8)
        self.assertEqual(len(self.radio["voice_clips"]), 1)

    async def test_only_the_stations_own_paths_are_rung(self):
        """The sets resolve a url against their own base."""
        for bad in ("http://elsewhere/clip.mp4", "//elsewhere/clip.mp4",
                    "/sfx/../../etc/passwd", "clip.mp4", ""):
            answer = await app.sfx_video_cut_api(payload={"url": bad})
            self.assertFalse(answer["ok"], bad)
            self.assertIsNone(answer["clip"])
        self.assertEqual(self.radio["voice_clips"], [])

    async def test_a_paused_station_shows_nobody_a_picture(self):
        """#1146's rule reaches this road too, for free - proved, not assumed."""
        with mock.patch.object(app.time, "time", return_value=1000):
            app.page_picture_append(self.pad())
        with mock.patch.object(app, "radio_paused", return_value=True):
            got = await app.dj_video_api(since=0)
        self.assertEqual(got["clips"], [])
        self.assertTrue(got["paused"])


if __name__ == "__main__":
    unittest.main()
