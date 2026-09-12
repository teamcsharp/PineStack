"""2026-09-09: "Make sure the broadcast is unified and that there is only one
mainline stream. I want all listeners tuning into the same singular broadcast."

#1118 gave the VOICE one destination and wrote down why - two clocks on one
source is two broadcasts. The music never got the rule, and the music was the
worse half: the page's follower plays whatever the radio clock names with no
route test in it at all, so `music_to: box` did not move the record to the box,
it copied it. The page seeked its own /music/<id> while the device ground
through a FLAC cut from an offset, alone, to the end of the track.
"""
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class PageCarriesMusicTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"music_to": "here", "monitor": False,
                      "now": {"id": "track-1"}}
        # The box has provably been given THIS record; without that receipt
        # the page keeps it whatever the route says.
        self.on = {"track": "track-1", "at": 0.0, "ok": True}
        for name, value in {
                "_RADIO": self.radio, "_NABU_MUSIC_ON": self.on,
                "_BOX_DOWN": {"until": 0, "fails": 0},
                "box_talk_ok": lambda *a, **k: True,
                "box_firmware_down_now": lambda: False}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def test_the_page_plays_the_record_when_it_is_the_destination(self):
        self.assertTrue(app.page_carries_music())

    def test_the_page_does_not_play_a_second_copy_while_the_box_has_it(self):
        for where in ("box", "both"):
            with self.subTest(where=where):
                self.radio["music_to"] = where
                self.assertFalse(app.page_carries_music())

    def test_the_page_keeps_the_record_until_the_box_has_taken_it(self):
        # 2026-09-09: the live outage. Pointed at the box, page stopped the
        # record, the device never started, and the station went silent with
        # a full bank. Being POINTED at the box is not a note coming out of
        # it; the station's receipt for this exact record is.
        self.radio["music_to"] = "box"
        for broken in ({"track": "", "at": 0.0, "ok": False},
                       {"track": "track-1", "at": 0.0, "ok": False},
                       {"track": "an-older-record", "at": 0.0, "ok": True}):
            with self.subTest(receipt=broken):
                self.on.clear(); self.on.update(broken)
                self.assertTrue(app.page_carries_music())

    def test_a_box_marked_down_never_takes_the_record_off_the_page(self):
        self.radio["music_to"] = "box"
        with mock.patch.object(app, "_BOX_DOWN",
                               {"until": app.time.time() + 60, "fails": 3}):
            self.assertTrue(app.page_carries_music())

    def test_the_rescues_are_the_same_rescues(self):
        self.radio["music_to"] = "box"
        with mock.patch.object(app, "box_talk_ok", lambda *a, **k: False):
            self.assertTrue(app.page_carries_music())    # the switch is off
        with mock.patch.object(app, "box_firmware_down_now", lambda: True):
            self.assertTrue(app.page_carries_music())    # the box is dead
        self.radio["monitor"] = True
        self.assertTrue(app.page_carries_music())        # hearing both on purpose

    def test_any_doubt_keeps_the_record(self):
        with mock.patch.object(app, "box_talk_ok", side_effect=RuntimeError):
            self.radio["music_to"] = "box"
            self.assertTrue(app.page_carries_music())


class OneDestinationRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"on": True, "voice_to": "box", "voice_device": "nabu",
                      "music_to": "here", "reply_to": "here", "box_talk": True,
                      "voice_clips": []}
        for key, value in {
                "_RADIO": self.radio, "_BOX_DOWN": {"until": 0, "fails": 0},
                "_BOX_HOLD": [], "_BOX_ROUTE_WAKE_TASK": None,
                "require_auth": mock.Mock(), "_routing_save": mock.Mock(),
                "_operator_routing_stamp": mock.Mock(), "pipeline_log": mock.Mock(),
                "_routing_voice_device_set": mock.Mock(), "_box_hold_save": mock.Mock(),
                "request_box_route_wake": mock.Mock(),
                "dj_state": mock.Mock(return_value={}),
                "box_level_send": mock.AsyncMock(),
                "music_box_stop_now": mock.AsyncMock(),
                "music_play_on_box": mock.AsyncMock(),
                "radio_paused": mock.Mock(return_value=False),
        }.items():
            self.stack.enter_context(mock.patch.object(app, key, value))

    async def route(self, body):
        request = mock.Mock(headers={}, client=mock.Mock(host="test-client"))
        request.json = mock.AsyncMock(return_value=body)
        return await app.dj_output_api(request, "test")

    async def test_the_music_follows_the_voice_to_the_page(self):
        self.radio.update(voice_to="box", music_to="box")
        await self.route({"voice": "here"})
        self.assertEqual(self.radio["voice_to"], "here")
        self.assertEqual(self.radio["music_to"], "here")

    async def test_the_music_follows_the_voice_to_the_box(self):
        await self.route({"voice": "box"})
        self.assertEqual(self.radio["music_to"], "box")

    async def test_a_split_asked_for_outright_is_refused(self):
        await self.route({"voice": "here", "music": "box"})
        self.assertEqual(self.radio["music_to"], "here")

    async def test_moving_only_the_music_is_pulled_back_to_the_voice(self):
        # The voice is already on the box; asking for the records here alone
        # would be two broadcasts, so they go where the show is.
        await self.route({"music": "here"})
        self.assertEqual(self.radio["music_to"], "box")

    async def test_off_is_a_mute_not_a_place(self):
        await self.route({"voice": "here", "music": "off"})
        self.assertEqual(self.radio["music_to"], "off")
        self.assertEqual(self.radio["voice_to"], "here")


if __name__ == "__main__":
    unittest.main()
