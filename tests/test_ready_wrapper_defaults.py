"""Independent clocks respect zero-generation playback without blocking prep."""
from contextlib import ExitStack
import unittest
from unittest import mock

import app


class ReadyWrapperDefaultsTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_live_calls_at_full_talk_use_only_saved_rounds(self):
        track = {"id": "isolated-current-record"}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(app, "talk_is_incessant", return_value=True))
            stack.enter_context(mock.patch.object(app, "_RADIO", {"now": track}))
            ready = stack.enter_context(mock.patch.object(app, "_ready_shelf_air", new=mock.AsyncMock()))
            for name in ("shelf_take", "booth_hot"):
                stack.enter_context(mock.patch.object(app, name, side_effect=AssertionError("No live work")))
            for name in ("describe_gallery_image", "_news_once", "dj_banter", "ask_model", "voice_render_any"):
                stack.enter_context(mock.patch.object(app, name, new=mock.AsyncMock(
                    side_effect=AssertionError("No live work"))))
            for outcome in (["Complete saved round."], []):
                ready.return_value = outcome
                for name, kind, kwargs, expected_track in (
                    ("dj_gallery_round", "gallery", {}, None),
                    ("dj_news", "news", {"hourly": True}, track),
                    ("dj_manager_note", "manager", {"track": track}, track),
                ):
                    with self.subTest(kind=kind, stock=bool(outcome)):
                        ready.reset_mock()
                        self.assertEqual(await getattr(app, name)(**kwargs), outcome)
                        ready.assert_awaited_once_with(kind, expected_track)

    async def test_explicit_preparation_keeps_its_existing_production_path(self):
        with ExitStack() as stack:
            full_talk = stack.enter_context(mock.patch.object(app, "talk_is_incessant", return_value=True))
            ready = stack.enter_context(mock.patch.object(app, "_ready_shelf_air", new=mock.AsyncMock(
                side_effect=AssertionError("Preparation must not air a saved round"))))
            shelf = stack.enter_context(mock.patch.object(app, "shelf_take", side_effect=AssertionError(
                "Preparation must not consume the playback shelf")))
            image = stack.enter_context(mock.patch.object(app, "describe_gallery_image", new=mock.AsyncMock(
                return_value=("", ""))))
            news = stack.enter_context(mock.patch.object(app, "_news_once", new=mock.AsyncMock(return_value=[])))
            heat = stack.enter_context(mock.patch.object(app, "booth_hot", return_value=20))
            stack.enter_context(mock.patch.object(app, "station_disposition_text", return_value=""))
            stack.enter_context(mock.patch.object(app, "radio_prompt_instruction", return_value=""))
            for name in ("dj_gallery_round", "dj_news", "dj_manager_note"):
                with self.subTest(wrapper=name):
                    bank = []
                    self.assertEqual(await getattr(app, name)(bank_to=bank), [])
                    self.assertEqual(bank, [])
            image.assert_awaited()
            news.assert_awaited_once()
            self.assertEqual(news.await_args.args[1], [])
            heat.assert_called_once()
            ready.assert_not_awaited()
            shelf.assert_not_called()
            full_talk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
