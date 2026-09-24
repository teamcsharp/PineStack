import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app


class ManagerPreparedPageTests(unittest.IsolatedAsyncioTestCase):
    def test_manager_clip_keeps_upstairs_playout_priority(self):
        self.assertEqual(app.playout_clip_road({"kind": "manager"}),
                         ("manager", True))

    def test_selector_requires_recorded_file_and_prefers_unplayed_page(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "aaa111.mp3").write_bytes(b"ready")
            (folder / "bbb222.mp3").write_bytes(b"ready")
            rows = [
                {"id": "missing", "text": "No file", "audio": "ccc333.mp3",
                 "last": 0, "uses": 0, "ts": 30},
                {"id": "older", "text": "Recorded", "audio": "aaa111.mp3",
                 "last": 10, "uses": 1, "ts": 20},
                {"id": "fresh", "text": "Unplayed", "audio": "bbb222.mp3",
                 "last": 0, "uses": 0, "ts": 10},
                {"id": "unsafe", "text": "Bad path", "audio": "../bad.mp3",
                 "last": 0, "uses": 0, "ts": 40},
            ]
            with mock.patch.object(app, "UPSTAIRS_AUDIO_DIR", folder), \
                    mock.patch.object(app, "upstairs_list", return_value=rows):
                self.assertEqual(app.manager_prepared_page()["id"], "fresh")

    async def test_scheduled_round_airs_prepared_page_and_stamps_quota(self):
        page = {"id": "fresh", "text": "Actual message",
                "audio": "bbb222.mp3"}
        with mock.patch.object(app, "manager_prepared_page", return_value=page), \
                mock.patch.object(app, "dj_upstairs_page", new=mock.AsyncMock(
                    return_value=True)) as air, \
                mock.patch.object(app, "dj_manager_note", new=mock.AsyncMock()) as memo, \
                mock.patch.object(app, "quota_stamp") as quota:
            self.assertTrue(await app.dj_manager_scheduled_round(
                {"id": "track"}, shelf_only=True))
        air.assert_awaited_once_with(page)
        memo.assert_not_awaited()
        quota.assert_called_once_with("manager")

    async def test_missing_or_vanished_page_uses_existing_memo_road(self):
        track = {"id": "track"}
        with mock.patch.object(app, "manager_prepared_page", return_value=None), \
                mock.patch.object(app, "dj_upstairs_page", new=mock.AsyncMock()) as air, \
                mock.patch.object(app, "dj_manager_note", new=mock.AsyncMock(
                    return_value=["memo"])) as memo:
            self.assertTrue(await app.dj_manager_scheduled_round(
                track, shelf_only=True))
        air.assert_not_awaited()
        memo.assert_awaited_once_with(track, shelf_only=True)

        page = {"id": "vanished", "audio": "aaa111.mp3"}
        with mock.patch.object(app, "manager_prepared_page", return_value=page), \
                mock.patch.object(app, "dj_upstairs_page", new=mock.AsyncMock(
                    return_value=False)) as air, \
                mock.patch.object(app, "dj_manager_note", new=mock.AsyncMock(
                    return_value=["memo"])) as memo:
            self.assertTrue(await app.dj_manager_scheduled_round(track))
        air.assert_awaited_once_with(page)
        memo.assert_awaited_once_with(track, shelf_only=False)

    async def test_prepared_page_plays_and_reacts_without_write_or_render(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "abc123.mp3").write_bytes(b"recorded")
            page = {"id": "abc123", "audio": "abc123.mp3",
                    "text": "You two have lost the equipment budget.",
                    "uses": 0}
            radio = {"chat": [], "voice_to": "here", "now": None}
            events = []
            clips = []

            def publish(clip):
                events.append("publish")
                clip["broadcast_ms"] = int(time.time() * 1000)
                clips.append(clip)
                return "delivery"

            async def react(*args, **kwargs):
                events.append("react")
                return ["line"]

            with ExitStack() as stack:
                def patch(name, **kwargs):
                    return stack.enter_context(mock.patch.object(app, name, **kwargs))

                patch("UPSTAIRS_AUDIO_DIR", new=folder)
                patch("_RADIO", new=radio)
                write = patch("dj_upstairs_write", new=mock.AsyncMock())
                render = patch("dj_upstairs_render", new=mock.AsyncMock())
                banter = patch("dj_banter", new=mock.AsyncMock(side_effect=react))
                patch("_clip_seconds_async", new=mock.AsyncMock(return_value=2.0))
                patch("_episode_stage", new=mock.AsyncMock())
                patch("_paged_settle", new=mock.AsyncMock())
                patch("radio_paused", return_value=False)
                patch("manager_call_name", return_value="Manager")
                admit = patch("admission_admit_line", return_value="occ")
                feed = patch("page_feed_append", side_effect=publish)
                patch("_PAGE_DELIVERIES", new={"delivery": {}})
                patch("_PAGE_ACKED_LINES", new=set())
                use = patch("upstairs_update")
                patch("pipeline_log")
                patch("media_sign", return_value="sig")
                patch("_sfx_cadence_audible")
                system2 = patch("_system2_acknowledge_row")
                remember = patch("air_remember")
                patch("script_ledger_order", return_value={})
                commit = patch("script_ledger_commit", return_value=True)
                self.assertTrue(await app.dj_upstairs_page(page))
                entry = radio["chat"][0]
                self.assertEqual(events, ["publish", "react"])
                self.assertEqual(entry["aired"], "published")
                self.assertEqual(entry["who"], "manager")
                self.assertEqual(entry["text"], page["text"])
                self.assertEqual(clips[0]["row_id"], entry["id"])
                self.assertEqual(clips[0]["text"], page["text"])
                self.assertEqual(clips[0]["who"], "manager")
                self.assertTrue(clips[0]["speech"])
                self.assertEqual(admit.call_args.kwargs["line_id"], entry["id"])
                self.assertEqual(app.script_ledger_catch_up([entry]), 0)
                self.assertTrue(app._acknowledge_delivery_lines(
                    "delivery", clips[0], position=1.0))
                self.assertEqual(entry["aired"], "stream")
                self.assertTrue(entry[app.HEARD_STAMP])
                self.assertEqual(app.script_ledger_catch_up([entry]), 1)
                self.assertEqual(commit.call_args.args[1][0]["line_id"], entry["id"])
                system2.assert_called_once()
                remember.assert_called_once_with(page["text"], "manager", "manager")
            write.assert_not_awaited()
            render.assert_not_awaited()
            self.assertEqual(banter.await_count, 1)
            self.assertIn(page["text"], banter.await_args.kwargs["angle"])
            feed.assert_called_once()
            use.assert_called_once()

    async def test_declined_transports_do_not_use_page_or_prompt_reaction(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "abc123.mp3").write_bytes(b"recorded")
            page = {"id": "abc123", "audio": "abc123.mp3",
                    "text": "The manager's actual memo", "uses": 0}
            radio = {"chat": [], "voice_to": "box", "now": None}
            with mock.patch.object(app, "UPSTAIRS_AUDIO_DIR", folder), \
                    mock.patch.object(app, "_RADIO", radio), \
                    mock.patch.object(app, "radio_paused", return_value=False), \
                    mock.patch.object(app, "box_talk_ok", return_value=True), \
                    mock.patch.object(app, "_clip_seconds_async", new=mock.AsyncMock(
                        return_value=2.0)), \
                    mock.patch.object(app, "_play_on_box", new=mock.AsyncMock(
                        return_value="")) as box, \
                    mock.patch.object(app, "page_feed_append", return_value="") as feed, \
                    mock.patch.object(app, "admission_admit_line", return_value="occ"), \
                    mock.patch.object(app, "admission_withdraw") as withdraw, \
                    mock.patch.object(app, "dj_banter", new=mock.AsyncMock()) as banter, \
                    mock.patch.object(app, "upstairs_update") as use, \
                    mock.patch.object(app, "media_sign", return_value="sig"):
                self.assertFalse(await app.dj_upstairs_page(page))
            box.assert_awaited_once()
            feed.assert_called_once()
            withdraw.assert_called_once_with(
                "occ", "neither transport carried the manager page")
            banter.assert_not_awaited()
            use.assert_not_called()
            self.assertEqual(radio["chat"], [])

    async def test_box_acceptance_precedes_reaction_without_page_copy(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "abc123.mp3").write_bytes(b"recorded")
            page = {"id": "abc123", "audio": "abc123.mp3",
                    "text": "The manager's actual memo", "uses": 0}
            radio = {"chat": [], "voice_to": "box", "now": None}
            events = []

            async def play(*args):
                events.append("box")
                return "accepted"

            async def react(*args, **kwargs):
                events.append("react")
                return ["line"]

            with mock.patch.object(app, "UPSTAIRS_AUDIO_DIR", folder), \
                    mock.patch.object(app, "_RADIO", radio), \
                    mock.patch.object(app, "radio_paused", return_value=False), \
                    mock.patch.object(app, "box_talk_ok", return_value=True), \
                    mock.patch.object(app, "_clip_seconds_async", new=mock.AsyncMock(
                        return_value=2.0)), \
                    mock.patch.object(app, "_play_on_box", new=mock.AsyncMock(
                        side_effect=play)), \
                    mock.patch.object(app, "page_feed_append") as feed, \
                    mock.patch.object(app, "admission_admit_line", return_value="occ"), \
                    mock.patch.object(app, "dj_banter", new=mock.AsyncMock(
                        side_effect=react)), \
                    mock.patch.object(app, "upstairs_update") as use, \
                    mock.patch.object(app, "_episode_stage", new=mock.AsyncMock()), \
                    mock.patch.object(app, "pipeline_log"), \
                    mock.patch.object(app, "media_sign", return_value="sig"):
                self.assertTrue(await app.dj_upstairs_page(page))
            self.assertEqual(events, ["box", "react"])
            self.assertEqual(radio["chat"][0]["aired"], "box")
            self.assertEqual(radio["chat"][0]["who"], "manager")
            feed.assert_not_called()
            use.assert_called_once()

    async def test_due_break_in_prefers_recorded_page_to_shelf(self):
        page = {"id": "ready", "text": "Memo in his own voice"}
        radio = {"on": True, "now": None}
        with mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "_SPEAKING", [False]), \
                mock.patch.object(app, "_RESCUE_AT", [0]), \
                mock.patch.object(app, "_MANAGER_BREAK", {"broke": 0}), \
                mock.patch.object(app, "manager_break_on", return_value=True), \
                mock.patch.object(app, "radio_paused", return_value=False), \
                mock.patch.object(app, "manager_due_why", return_value="his entry"), \
                mock.patch.object(app, "manager_prepared_page", return_value=page), \
                mock.patch.object(app, "_ready_shelf_row", return_value=None), \
                mock.patch.object(app, "_floor_busy", return_value=False), \
                mock.patch.object(app, "dj_upstairs_page", new=mock.AsyncMock(
                    return_value=True)) as air, \
                mock.patch.object(app, "_ready_shelf_air", new=mock.AsyncMock()) as shelf, \
                mock.patch.object(app, "dj_speak", new=mock.AsyncMock()) as bridge, \
                mock.patch.object(app, "quota_stamp") as quota, \
                mock.patch.object(app, "pipeline_log"), \
                mock.patch.object(app, "note_action"):
            self.assertEqual(await app.manager_break_in(), "manager")
        air.assert_awaited_once_with(page)
        shelf.assert_not_awaited()
        bridge.assert_not_awaited()
        quota.assert_called_once_with("manager")
