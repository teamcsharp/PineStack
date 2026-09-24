"""Recovered page speech and board-audio evidence in the gap report."""

import unittest
from contextlib import ExitStack
from unittest import mock

import app


class RecoveredPlainLineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"chat": []}
        self.deliveries = {"new-delivery": {"state": "published"}}
        for name, value in {
            "_RADIO": self.radio,
            "_PAGE_DELIVERIES": self.deliveries,
            "_PAGE_ACKED_LINES": set(),
            "_sfx_cadence_audible": mock.Mock(),
            "_system2_acknowledge_row": mock.Mock(),
            "air_remember": mock.Mock(),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def clip(self, row_id="plain-line"):
        return {"row_id": row_id, "who": "cohost", "kind": "interject",
                "text": "A recovered line", "speech": True, "seconds": 4.0,
                "url": "/media/plain.wav?t=signed", "broadcast_ms": 100000}

    def test_plain_recovery_reuses_unheard_row_and_ack_stamps_it(self):
        old = {"id": "plain-line", "who": "cohost", "kind": "interject",
               "text": "A recovered line", "aired": "published", "air_at": 20.0}
        self.radio["chat"].append(old)
        clip = self.clip()
        app.page_recovery_prepare_row(clip)
        app.page_recovery_chat_rows(clip, "new-delivery")
        self.assertEqual(len(self.radio["chat"]), 1)
        row = self.radio["chat"][0]
        self.assertEqual(row["id"], "plain-line")
        self.assertEqual(row["delivery_id"], "new-delivery")
        self.assertEqual(row["clip_media"], "plain.wav")
        self.assertEqual(row["air_at"], 100.0)
        self.assertEqual(row["seconds"], 4.0)
        self.assertTrue(row["recovery"])

        with mock.patch.object(app.time, "time", return_value=101.0):
            self.assertTrue(app._acknowledge_delivery_lines(
                "new-delivery", clip, position=1.0, previous=0.0))
        self.assertEqual(row[app.HEARD_STAMP], 100.0)
        self.assertEqual(row["aired"], "stream")
        self.assertEqual(self.deliveries["new-delivery"]["played_rows"],
                         {"plain-line"})
        self.assertEqual(len(app.gap_lines(self.radio["chat"], basis="heard")), 1)

    def test_already_heard_line_gets_new_occurrence_id(self):
        old = {"id": "plain-line", "who": "cohost", "kind": "interject",
               "text": "A recovered line", app.HEARD_STAMP: 20.0,
               "aired": "stream"}
        self.radio["chat"].append(old)
        clip = self.clip()
        app.page_recovery_prepare_row(clip)
        self.assertNotEqual(clip["row_id"], "plain-line")
        self.assertEqual(clip["recovered_from_row_id"], "plain-line")
        app.page_recovery_chat_rows(clip, "new-delivery")
        self.assertEqual(len(self.radio["chat"]), 2)
        self.assertEqual(old[app.HEARD_STAMP], 20.0)
        self.assertEqual(self.radio["chat"][-1]["id"], clip["row_id"])

    def test_failed_publication_does_not_create_a_ghost_row(self):
        app.page_recovery_chat_rows(self.clip(), "")
        self.assertEqual(self.radio["chat"], [])

    def test_stream_recovery_keeps_board_cue_duration_and_media(self):
        clip = {"url": "/media/round.wav?t=signed", "broadcast_ms": 100000,
                "stream": {"length": 25.0, "rows": [
                    {"id": "board", "who": "board", "kind": "sfx",
                     "text": "sample", "from": 4.0, "until": 23.0,
                     "clip_tail": 0.2}]}}
        app.page_recovery_chat_rows(clip, "new-delivery")
        row = self.radio["chat"][0]
        self.assertEqual(row["air_at"], 104.0)
        self.assertEqual(row["clip_media"], "round.wav")
        self.assertAlmostEqual(app._gap_row_len(row), 18.8)


class RecoveryStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_reconciles_plain_clip_into_chat_before_acks(self):
        radio = {"on": True, "voice_to": "here", "voice_cut_ms": 0,
                 "chat": [{"id": "plain-line", "who": "dj", "kind": "interject",
                           "text": "Recovered", "aired": "published"}]}
        deliveries = {"new-delivery": {"state": "published"}}
        saved = [{"delivery_id": "old-delivery", "row_id": "plain-line",
                  "who": "dj", "kind": "interject", "text": "Recovered",
                  "speech": True, "seconds": 3.0,
                  "url": "/media/voice.wav?t=signed"}]

        def publish(clip):
            clip["broadcast_ms"] = 100000
            return "new-delivery"

        with (mock.patch.object(app, "_RADIO", radio),
              mock.patch.object(app, "_PAGE_DELIVERIES", deliveries),
              mock.patch.object(app, "_PAGE_AIR_UNTIL", [100.0]),
              mock.patch.object(app, "page_recovery_read", return_value=saved),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "_floor_take", new=mock.AsyncMock(return_value=True)),
              mock.patch.object(app, "_floor_drop"),
              mock.patch.object(app, "_paged_settle", new=mock.AsyncMock()),
              mock.patch.object(app, "admission_admit_line"),
              mock.patch.object(app, "page_feed_append", side_effect=publish)):
            await app.page_recovery_start()

        self.assertEqual(len(radio["chat"]), 1)
        self.assertEqual(radio["chat"][0]["delivery_id"], "new-delivery")
        self.assertTrue(radio["chat"][0]["recovery"])


class GapAudioCoverageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {
            "_GAP_MARKS": [], "_GAP_ROUNDS": [], "_TAKES": [],
            "_PULSE": {"stalls": []}, "radio_paused": lambda: False,
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    @staticmethod
    def speech(row_id, at):
        return {"id": row_id, "who": "dj", "kind": "call", "text": row_id,
                "aired": "stream", app.HEARD_STAMP: at, "air_at": at,
                "seconds": 5.0}

    @staticmethod
    def board(row_id="board", at=110.0, seconds=20.0, heard=True):
        row = {"id": row_id, "who": "board", "kind": "sfx",
               "text": "sample", "aired": "stream", "air_at": at,
               "clip_from": 0.0, "clip_until": seconds}
        if heard:
            row[app.HEARD_STAMP] = at
        return row

    def test_board_audio_is_not_counted_as_full_channel_silence(self):
        chat = [self.speech("before", 100), self.board(),
                self.speech("after", 135)]
        row, = app.gap_rows(chat, least=10, basis="heard")
        self.assertEqual(row["seconds"], 30.0)
        self.assertEqual(row["speech_absent_s"], 30.0)
        self.assertEqual(row["board_sfx_s"], 20.0)
        self.assertEqual(row["no_known_audio_s"], 10.0)
        self.assertEqual(row["possible_full_channel_s"], 10.0)
        self.assertIsNone(row["full_channel_s"])
        report = app.gap_report(hours=0.1, chat=chat, file_rows=[], now=140)
        self.assertEqual(report["audio_coverage"]["board_sfx_s"], 20.0)
        self.assertEqual(report["audio_coverage"]["no_known_audio_s"], 10.0)
        self.assertEqual(report["audio_coverage"]["possible_full_channel_s"], 10.0)

    def test_overlapping_board_rows_and_operator_pause_are_not_double_counted(self):
        app._GAP_MARKS.extend([{"what": "pause", "at": 115.0},
                               {"what": "resume", "at": 125.0}])
        chat = [self.speech("before", 100), self.board("a"),
                self.board("b", 112, 18), self.speech("after", 135)]
        row, = app.gap_rows(chat, least=10, basis="heard")
        self.assertEqual(row["paused_seconds"], 10.0)
        self.assertEqual(row["seconds"], 20.0)
        self.assertEqual(row["board_sfx_s"], 10.0)
        self.assertEqual(row["no_known_audio_s"], 10.0)

    def test_unheard_board_publication_is_not_audible_evidence(self):
        chat = [self.speech("before", 100), self.board(heard=False),
                self.speech("after", 135)]
        row, = app.gap_rows(chat, least=10, basis="heard")
        self.assertEqual(row["board_sfx_s"], 0.0)
        self.assertEqual(row["no_known_audio_s"], 30.0)

    def test_unheard_timeline_does_not_claim_board_was_audible(self):
        chat = [self.speech("before", 100), self.board(),
                self.speech("after", 135)]
        row, = app.gap_rows(chat, least=10, basis="published")
        self.assertIsNone(row["board_sfx_s"])
        self.assertIsNone(row["no_known_audio_s"])
        self.assertIsNone(row["possible_full_channel_s"])
        self.assertEqual(row["audio_coverage_basis"], "unverified")


if __name__ == "__main__":
    unittest.main()
