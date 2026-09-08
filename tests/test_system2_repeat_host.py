"""Only audible receipts enter the persistent hour window; all paths consult it."""
import asyncio
import ast
import copy
import inspect
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from system2 import System2Store
import tests.test_ready_stream_playback as stream_fixture


class Ledger:
    # The legacy admission window asks the runtime whether System2 owns the
    # clock; a ledger stub that only records receipts answers no.
    enabled = False

    def __init__(self, path):
        self.store = System2Store(path)
        self.calls = []
        self.full = []
    def repeat_allowed(self, texts, entry=None):
        self.calls.append((list(texts), entry))
        return self.store.can_play(texts, reservation_id=((entry or {}).get("_system2") or {}).get("reservation_id", ""))["allowed"]
    def acknowledge_line(self, clip, row, receipt):
        text = str(row.get("remember_text") or row.get("text") or "")
        if text:
            self.store.record_external(text, receipt_id=receipt)
    def acknowledge(self, entry):
        self.full.append(entry)


class RepeatStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = stream_fixture.ReadyStreamPlaybackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.stack.close)
        self.ledger = Ledger(self.fixture.root / "repeat.sqlite3")
        self.fixture.patch("_system2", mock.Mock(return_value=self.ledger))
        self.fixture.patch("_sfx_cadence_additions", mock.AsyncMock(return_value=[]))

    async def test_generic_recorded_manual_and_repeat_waiver_cannot_bypass(self):
        text = self.fixture.takes[0]["text"]
        self.ledger.store.record_external(text, receipt_id="earlier")
        self.fixture.patch("session_voices", mock.AsyncMock(return_value={"dj": "v", "cohost": "w"}))
        result = await app._speak_turns_floorless([("A", text)], None, 2,
            recorded=True, whole=True, by_hand=True, allow_repeat=True, render_stream=True)
        self.assertEqual(result, [])
        app._call_concat_blocking.assert_not_called()
        app._play_on_box.assert_not_called()
        self.assertEqual(self.fixture.radio["voice_clips"], [])

    async def test_recorded_banter_is_checked_before_freshening_or_other_work(self):
        text = self.fixture.takes[0]["text"]
        self.ledger.store.record_external(text, receipt_id="heard")
        entry = {"script": "A: " + text, "frozen": True, "lines": 1}
        self.assertEqual(await app._banter_air(entry, None), [])
        app.freshen_script.assert_not_called()
        app._play_on_box.assert_not_called()

    async def test_concurrent_heard_during_assembly_refuses_before_publication(self):
        def concat(*args, **kwargs):
            self.ledger.store.record_external(self.fixture.takes[0]["text"], receipt_id="concurrent")
            return b"joined existing takes"
        app._call_concat_blocking.side_effect = concat
        self.assertEqual(await self.fixture.play(), [])
        self.fixture.handoff.assert_not_called()
        self.assertEqual(self.fixture.radio["voice_clips"], [])
        app._play_on_box.assert_not_called()

    async def test_unrelated_interrupted_muted_and_false_device_receipts_never_credit(self):
        self.fixture.radio["voice_to"] = "box"
        app._play_on_box.return_value = "transport accepted"
        for receipt in ({"key": "unrelated.wav", "ok": True},
                        {"key": "joined.wav", "ok": True, "interrupted": True},
                        {"key": "joined.wav", "ok": True, "intentional_mute": True},
                        {"key": "joined.wav", "ok": True, "audible_gain": 0},
                        {"key": "joined.wav", "ok": False}):
            with self.subTest(receipt=receipt):
                app._LAST_PLAYOUT.clear()
                app._LAST_PLAYOUT.update(receipt)
                await self.fixture.play()
                self.assertTrue(self.ledger.repeat_allowed([self.fixture.takes[0]["text"]]))
                app.air_remember.assert_not_called()
                app.speakbox_remember.assert_not_called()

    async def test_exact_device_receipt_survives_process_store_reopen(self):
        self.fixture.radio["voice_to"] = "box"
        app._play_on_box.return_value = "transport accepted"
        app._LAST_PLAYOUT.update(key="joined.wav", ok=True, audible_gain=2)
        self.assertTrue(await self.fixture.play())
        reopened = System2Store(self.fixture.root / "repeat.sqlite3")
        for take in self.fixture.takes:
            self.assertFalse(reopened.can_play([take["text"]])["allowed"])
        app.speakbox_remember.assert_called_once()

    async def test_publication_and_muted_page_do_not_seed_the_ledger(self):
        await self.fixture.play()
        text = self.fixture.takes[0]["text"]
        self.assertTrue(self.ledger.repeat_allowed([text]))
        self.fixture.ack("playing", .2, 1, volume=0)
        self.assertTrue(self.ledger.repeat_allowed([text]))
        self.fixture.ack("playing", 1.0, 2)
        self.assertFalse(self.ledger.repeat_allowed([text]))

    def test_chunk_and_whole_turn_are_both_retained_from_a_real_receipt(self):
        row = {"text": "The first exact spoken chunk.",
               "remember_text": "The first exact spoken chunk. A final different sentence."}
        app._system2_acknowledge_row({}, row, "actual-receipt")
        self.assertFalse(self.ledger.repeat_allowed([row["text"]]))
        self.assertFalse(self.ledger.repeat_allowed([row["remember_text"]]))


class SingleBoxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ledger = Ledger(self.directory / "repeat.sqlite3")
        original = app._dj_speak_floorless
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(original))) if isinstance(n, ast.Name)}
        keep = {"_dj_speak_floorless", "_box_receipt_heard", "_box_receipt_audible",
                "_played_out_key", "_system2_repeat_rows", "_system2_acknowledge_row"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                cls = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                self.stack.enter_context(mock.patch.object(app, name, cls(return_value="")))
        self.radio = {"on": True, "voice_to": "box", "reply_to": "box", "chat": []}
        for name, value in {"_system2": mock.Mock(return_value=self.ledger), "_RADIO": self.radio,
                            "_LAST_PLAYOUT": {}, "_BOX_DOWN": {}, "_BOX_HOLD": [],
                            "_PAGE_ACKED_LINES": set(), "_SPEAKING": [0],
                            "_SILENT_HOLD_STREAK": [0], "_PAGE_AIR_UNTIL": [0],
                            "_SPEAK_LAST": {}, "_SPEAKING_NOW": {}, "_DIALOGUE_AT": [0]}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        app.spoken_text.side_effect = lambda text: text
        app.station_name_scrub.side_effect = lambda text: text
        app.performance_vector.return_value = {}
        app.configured_radio_voice.return_value = "recorded-voice"
        app.session_voices.return_value = {"dj": "recorded-voice"}
        app.voice_engine_for.return_value = "piper"
        app.box_talk_ok.return_value = True
        app._play_on_box.return_value = "transport accepted"
        app.page_carries_live.return_value = False
        app.dj_settings.return_value = dict(app.DEFAULT_DJ)
        app.load_settings.return_value = {}
        app._model_call_for.return_value = {}
        self.original = original
        self.text = "These are the actual exact recorded words."
        self.clip = {"path": "/media/exact.wav", "sig": "fixture", "seconds": 3}

    async def test_single_box_receipt_is_pinned_before_other_meter_changes(self):
        app._LAST_PLAYOUT.update(key="exact.wav", ok=True, audible_gain=2)
        self.assertTrue(await self.original("ad", line=self.text, voice="recorded-voice",
                                           clip=self.clip, sting=False, checked=True, by_hand=True))
        self.assertFalse(self.ledger.repeat_allowed([self.text]))

    async def test_unrelated_or_muted_single_box_meter_does_not_credit(self):
        for receipt in ({"key": "other.wav", "ok": True},
                        {"key": "exact.wav", "ok": True, "interrupted": True},
                        {"key": "exact.wav", "ok": True, "audible_gain": 0}):
            app._LAST_PLAYOUT.clear()
            app._LAST_PLAYOUT.update(receipt)
            await self.original("ad", line=self.text, voice="recorded-voice",
                                clip=self.clip, sting=False, checked=True, by_hand=True)
            self.assertTrue(self.ledger.repeat_allowed([self.text]))


if __name__ == "__main__":
    unittest.main()
