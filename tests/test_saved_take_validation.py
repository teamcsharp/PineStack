"""Independent saved-recording integrity checks; no live files or synthesis."""
import asyncio
import copy
from contextlib import ExitStack
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app


class SavedTakeValidationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.pantry = {}
        self.forbidden = {}
        for name, value in {
            "_PANTRY": self.pantry, "VOICE_MEDIA_DIR": self.folder,
            "_MEDIA_THERE": {},
            "dialogue_row_ready": mock.Mock(return_value=True),
            "_larder_current": mock.Mock(return_value=True),
            "voice_engine_for": mock.Mock(return_value="piper"),
            "is_binned": mock.Mock(return_value=False),
            "station_name_scrub": mock.Mock(side_effect=lambda text: text),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        for name in ("voice_render_any", "session_voices", "freshen_script", "crystal_tint", "ask_model"):
            fn = mock.AsyncMock(side_effect=AssertionError("Saved take validation must not do production work"))
            self.forbidden[name] = fn
            self.stack.enter_context(mock.patch.object(app, name, fn))
        self.turns = [
            ("A", "The copper kettle whistles beside the window.", "dj", "stored-host"),
            ("B", "The evening train has reached the old platform.", "cohost", "stored-cohost"),
            ("A", "The copper kettle whistles beside the window.", "dj", "stored-host"),
        ]
        self.entry = {"script": "\n".join(f"{marker}: {text}" for marker, text, _, _ in self.turns),
                      "prep_kind": "gallery", "chunks": 3, "made": 3, "prepared": True}
        self.entry["takes"] = [self.take(i, text, who, voice)
                               for i, (_, text, who, voice) in enumerate(self.turns)]
        self.entry["keys"] = list(dict.fromkeys(t["key"] for t in self.entry["takes"]))
        self.row = {"entry": self.entry, "sid": "isolated-gallery"}

    def tearDown(self):
        for fn in self.forbidden.values():
            fn.assert_not_called()

    def take(self, index, text, who, voice):
        key = app.pantry_key(text, voice, "piper")
        path = self.folder / (key + ".wav")
        path.write_bytes(b"isolated nonempty test media")
        self.pantry[key] = {"text": text, "voice": voice, "who": who,
                            "clip": {"path": "/api/voice/media/" + path.name,
                                     "seconds": 2.0, "engine": "piper"}}
        return {"i": index, "text": text, "voice": voice, "who": who,
                "key": key, "seconds": 2.0}

    def validate(self):
        return app._ready_round_takes("gallery", self.row)

    def test_complete_legacy_takes_keep_repeated_positions_and_stored_voices(self):
        before = copy.deepcopy(self.row)
        saved = self.validate()
        self.assertEqual(len(saved), 3)
        self.assertEqual([t["voice"] for t in saved], ["stored-host", "stored-cohost", "stored-host"])
        self.assertEqual([t.get("text") or t.get("chunk") for t in saved], [t[1] for t in self.turns])
        self.assertEqual(self.row, before)

    def test_source_turn_order_cannot_be_changed_by_reindexing_takes(self):
        takes = self.entry["takes"]
        takes[0], takes[1] = takes[1], takes[0]
        for i, take in enumerate(takes):
            take["i"] = i
        self.assertEqual(self.validate(), [])

    def test_missing_position_is_rejected_despite_optimistic_ready_counters(self):
        self.entry["takes"].pop(1)
        self.assertEqual(self.validate(), [])

    def test_duplicate_index_cannot_replace_a_missing_position(self):
        self.entry["takes"][1]["i"] = 0
        self.assertEqual(self.validate(), [])

    def test_wrong_saved_voice_cannot_use_another_voices_key(self):
        self.entry["takes"][0]["voice"] = "different-speaker"
        self.assertEqual(self.validate(), [])

    def test_wrong_saved_words_cannot_use_another_texts_key(self):
        self.entry["takes"][0]["text"] = "The kettle is silent."
        self.assertEqual(self.validate(), [])

    def test_source_word_omission_is_rejected_even_with_matching_audio_metadata(self):
        self.entry["takes"][1] = self.take(1, "The train has reached the old platform.", "cohost", "stored-cohost")
        self.assertEqual(self.validate(), [])

    def test_new_factual_claim_cannot_hide_inside_allowed_recording_extra_words(self):
        text = self.turns[1][1] + " Five passengers died."
        self.entry["takes"][1] = self.take(1, text, "cohost", "stored-cohost")
        self.assertEqual(self.validate(), [])

    def test_known_short_recording_filler_keeps_the_complete_source(self):
        text = "Um, " + self.turns[1][1]
        self.entry["takes"][1] = self.take(1, text, "cohost", "stored-cohost")
        self.assertEqual(len(self.validate()), 3)

    def test_source_hash_alone_cannot_certify_reordered_or_incomplete_takes(self):
        self.entry["take_source"] = hashlib.sha1(self.entry["script"].strip().encode()).hexdigest()
        self.entry["takes"][1] = self.take(1, "The train has reached the old platform.", "cohost", "stored-cohost")
        self.assertEqual(self.validate(), [])

    def test_deleted_or_empty_media_is_rejected_without_mutating_queued_row(self):
        path = self.folder / (self.entry["takes"][1]["key"] + ".wav")
        before = copy.deepcopy(self.row)
        path.unlink()
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.row, before)
        path.write_bytes(b"")
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.row, before)

    def test_adjacent_chunks_may_cover_one_whole_source_turn(self):
        self.entry["script"] = "A: The copper kettle whistles beside the window."
        self.entry["takes"] = [self.take(0, "The copper kettle whistles", "dj", "stored-host"),
                               self.take(1, "beside the window.", "dj", "stored-host")]
        self.entry.update(chunks=2, made=2)
        self.entry["keys"] = [t["key"] for t in self.entry["takes"]]
        self.assertEqual(len(self.validate()), 2)

    def test_long_legacy_pantry_preview_can_be_truncated_when_full_take_key_proves_words(self):
        text = " ".join(["The copper kettle whistles beside the window."] * 19)
        take = self.take(0, text, "dj", "stored-host")
        self.entry.update(script="A: " + text, takes=[take], keys=[take["key"]], chunks=1, made=1)
        self.pantry[take["key"]]["text"] = text[:600]
        self.assertGreater(len(text), 600)
        self.assertEqual(len(self.validate()), 1)


class SavedTakeHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.row = {"sid": "retained-gallery", "entry": {"script": "A: Every word remains owed."}}
        self.rows = [self.row]
        self.takes = [{"i": 0, "text": "Every word remains owed.", "voice": "stored-host", "who": "dj", "key": "saved"}]
        self.took = mock.Mock()
        self.save = mock.Mock()
        for name, value in {
            "_ready_shelf_row": mock.Mock(return_value=self.row),
            "_ready_round_takes": mock.Mock(return_value=self.takes),
            "shelf_rows": mock.Mock(return_value=self.rows),
            "SHELF_REUSABLE": set(), "alt_took": self.took, "_pantry_save": self.save,
            "_INVENTORY_PLAN": {}, "_COMMITS": {}, "_PREPARED_KIND_MEMO": {}, "_RADIO": {},
            "_READY_SHELF_BUSY": set(), "_floor_take": mock.AsyncMock(return_value=True),
            "_floor_drop": mock.Mock(),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        for name in ("voice_render_any", "session_voices", "freshen_script", "ask_model"):
            self.stack.enter_context(mock.patch.object(app, name, mock.AsyncMock(
                side_effect=AssertionError("Handoff must not commission work"))))

    async def test_transport_refusal_retains_unheard_row_without_aired_stamp(self):
        with mock.patch.object(app, "_banter_air", new=mock.AsyncMock(return_value=[])):
            self.assertEqual(await app._ready_shelf_air("gallery"), [])
        self.assertEqual(self.rows, [self.row])
        self.assertNotIn("ready_air_inflight", self.row)
        self.assertNotIn("taken_at", self.row)
        self.took.assert_not_called()
        self.save.assert_not_called()

    async def test_operator_cancellation_after_floor_acquisition_blocks_first_handoff(self):
        def current_takes(_kind, row):
            return [] if row.get("review_cancel_pending") else self.takes

        async def cancelled_at_transport(*_args, **kwargs):
            self.assertTrue(kwargs["can_handoff"]())
            self.row["review_cancel_pending"] = True
            self.assertFalse(kwargs["can_handoff"]())
            return []

        with (mock.patch.object(app, "_ready_round_takes", side_effect=current_takes),
              mock.patch.object(app, "_banter_air", new=mock.AsyncMock(side_effect=cancelled_at_transport))):
            self.assertEqual(await app._ready_shelf_air("gallery"), [])
        self.assertEqual(self.rows, [self.row])
        self.assertTrue(self.row["review_cancel_pending"])
        self.assertNotIn("taken_at", self.row)
        self.assertNotIn(id(self.row), app._READY_SHELF_BUSY)
        self.took.assert_not_called()
        self.save.assert_not_called()

    async def test_cancel_before_handoff_releases_reservation_and_keeps_every_row(self):
        started = asyncio.Event()

        async def wait_for_transport(*_args, **_kwargs):
            self.assertIn(self.row, self.rows)
            self.assertIn(id(self.row), app._READY_SHELF_BUSY)
            started.set()
            await asyncio.Future()

        with mock.patch.object(app, "_banter_air", new=mock.AsyncMock(side_effect=wait_for_transport)):
            task = asyncio.create_task(app._ready_shelf_air("gallery"))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.rows, [self.row])
        self.assertNotIn("ready_air_inflight", self.row)
        self.assertNotIn(id(self.row), app._READY_SHELF_BUSY)
        self.assertNotIn("taken_at", self.row)
        self.took.assert_not_called()

    async def test_queue_acceptance_commits_once_after_handoff_and_preserves_saved_takes(self):
        async def accept(*_args, **kwargs):
            self.assertEqual(kwargs["ready_takes"], self.takes)
            self.assertIn(self.row, self.rows)
            self.took.assert_not_called()
            kwargs["on_handoff"]()
            kwargs["on_handoff"]()
            self.assertNotIn(self.row, self.rows)
            return ["Every word remains owed."]

        with mock.patch.object(app, "_banter_air", new=mock.AsyncMock(side_effect=accept)):
            self.assertEqual(await app._ready_shelf_air("gallery"), ["Every word remains owed."])
        self.took.assert_called_once_with("gallery", self.row)
        self.save.assert_called_once_with(True)
        self.assertNotIn("ready_air_inflight", self.row)


if __name__ == "__main__":
    unittest.main()
