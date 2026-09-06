import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from station_flow import FlowJournal, clean_detail


class ConversationParsingTests(unittest.TestCase):
    def test_explicit_order_words_and_voices_survive_repeated_speaker_and_unpunctuated_tail(self):
        text = "A: The first thought.\nA: Still the same host.\nB: A reply without a final stop"
        expected = [("A", "The first thought."), ("A", "Still the same host."),
                    ("B", "A reply without a final stop")]
        with (mock.patch.object(app, "dj_settings", return_value=app.DEFAULT_DJ),
              mock.patch.object(app, "seat_away_who", return_value="dj"),
              mock.patch.object(app, "_prep_intro_pad", side_effect=lambda turns, name: turns),
              mock.patch.object(app, "performance_vector", return_value={}),
              mock.patch.object(app, "inject_disfluencies", side_effect=lambda text, *a, **kw: text)):
            turns = app.banter_turns(text)
            self.assertEqual(turns, expected)
            plan = app._round_chunks(turns, {"dj": "host-voice", "cohost": "cohost-voice"})
        self.assertEqual([who for text, voice, who in plan], ["dj", "dj", "cohost"])
        self.assertEqual([voice for text, voice, who in plan], ["host-voice", "host-voice", "cohost-voice"])
        self.assertEqual([text for text, voice, who in plan], [body for marker, body in expected])

    def test_parser_keeps_incomplete_draft_while_writer_validation_refuses_it(self):
        body = ("The station has a copper plate waiting in the workshop before midnight. " * 7).strip()
        complete = "\n".join(("A" if i % 2 == 0 else "B") + ": " + body for i in range(8))
        unfinished = complete.rstrip(".")
        with mock.patch.object(app, "dj_settings", return_value={**app.DEFAULT_DJ, "reply_max_chars": 6500}):
            self.assertEqual(len(app.banter_turns(unfinished)), 8)
            self.assertEqual(app.banter_turns(unfinished)[-1][1], body.rstrip("."))
            self.assertTrue(app.substantial_radio_script(complete, 8))
            self.assertFalse(app.substantial_radio_script(unfinished, 8))


class PlaybackAcknowledgmentTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch.object(app, "_PAGE_DELIVERIES", {}),
            mock.patch.object(app, "_PAGE_ACK_EVENTS", []),
            mock.patch.object(app, "_PAGE_ACKED_LINES", set()),
            mock.patch.object(app, "_PAGE_AIR_UNTIL", [0.0]),
            mock.patch.object(app, "_RADIO", {"voice_clips": [], "chat": []}),
            mock.patch.object(app, "_LAST_SAID", [0.0]),
            mock.patch.object(app, "_TALK_ACK", {}),
            mock.patch.object(app, "_TALK_ACK_BASE", [100.0]),
            mock.patch.object(app, "station_flow_event"),
            mock.patch.object(app, "listener_note"),
            mock.patch.object(app, "air_remember"),
            mock.patch.object(app, "_stream_now_set"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.row = {"id": "a", "who": "dj", "kind": "banter",
                    "text": "The host's full opening.", "aired": "published"}
        app._RADIO["chat"].append(self.row)
        self.delivery = app.page_feed_append({"row_id": "a", "text": self.row["text"],
            "who": "dj", "kind": "banter", "speech": True,
            "remember_text": self.row["text"], "url": "/media/test.wav"})
        self.sequence = 0

    def ack(self, event, position=0, **kwargs):
        self.sequence += 1
        return app.page_playback_ack({"delivery_id": self.delivery,
            "listener_id": "listener-one", "event": event,
            "sequence": self.sequence, "current_time": position,
            "volume": 0.8, "audible_volume": 0.8, **kwargs})

    def test_publication_receipt_and_buffering_do_not_claim_air(self):
        self.assertTrue(self.delivery)
        self.ack("received")
        self.ack("canplay")
        self.assertEqual(self.row["aired"], "published")
        self.assertEqual(app._LAST_SAID[0], 0)
        app.air_remember.assert_not_called()

    def test_muted_playback_does_not_reset_talk_watchdog(self):
        self.ack("playing", muted=True)
        self.assertEqual(self.row["aired"], "published")
        self.assertEqual(app._LAST_SAID[0], 0)

    def test_playing_progress_confirms_once_and_stall_does_not_refresh(self):
        with mock.patch.object(app.time, "time", return_value=200):
            self.ack("playing", 0)
        self.assertEqual(self.row["aired"], "stream")
        self.assertEqual(app._TALK_ACK["listener"], "listener-one")
        with mock.patch.object(app.time, "time", return_value=210):
            self.ack("playing", 0)
            self.assertEqual(app.talk_quiet_for(), 10)
            self.ack("playing", 2)
            self.assertEqual(app.talk_quiet_for(), 0)
        app.air_remember.assert_called_once_with(self.row["text"], "dj", "banter")

    def test_stream_ring_does_not_credit_future_caller_or_ending(self):
        clip = app._PAGE_DELIVERIES[self.delivery]["clip"]
        app._RADIO["chat"].extend([
            {"id": "c", "who": "caller", "text": "My topic", "aired": "published"},
            {"id": "z", "who": "dj", "text": "Thank you and goodbye", "aired": "published"}])
        clip["stream"] = {"length": 32, "rows": [
            {"id": "a", "who": "dj", "text": "Opening", "from": 2, "until": 10},
            {"id": "c", "who": "caller", "text": "My topic", "from": 10, "until": 25},
            {"id": "z", "who": "dj", "text": "Goodbye", "from": 25, "until": 32}]}
        self.ack("playing", 0)
        self.assertEqual(app._LAST_SAID[0], 0)
        self.ack("playing", 3)
        self.assertEqual([r["aired"] for r in app._RADIO["chat"]],
                         ["stream", "published", "published"])
        self.ack("error", 3, error="network stopped")
        self.assertEqual(app._RADIO["chat"][-1]["aired"], "published")

    def test_out_of_order_ack_is_ignored_and_other_listener_cannot_erase_play(self):
        self.ack("playing", 1, sequence=10)
        result = self.ack("error", 1, sequence=9)
        self.assertIn("ignored", result)
        self.ack("error", 0, listener_id="muted-tab", error="autoplay blocked")
        self.assertEqual(app._PAGE_DELIVERIES[self.delivery]["state"], "playing")
        self.assertEqual(self.row["aired"], "stream")

    def test_new_show_without_any_ack_still_accumulates_gap(self):
        with mock.patch.object(app.time, "time", return_value=119):
            self.assertEqual(app.talk_quiet_for(), 19)

    def test_non_speech_delivery_cannot_satisfy_talk(self):
        app._PAGE_DELIVERIES[self.delivery]["speech"] = False
        self.ack("playing", 1)
        self.assertEqual(app._LAST_SAID[0], 0)

    def test_explicit_stream_reserves_full_duration_before_next_line(self):
        app._PAGE_AIR_UNTIL[0] = 0
        first = {"broadcast_ms": 200000, "stream": {"length": 90},
                 "speech": True, "text": "A complete conversation"}
        with mock.patch.object(app.time, "time", return_value=100):
            app.page_feed_append(first)
            next_line = {"text": "The next line", "seconds": 12}
            app.page_feed_append(next_line)
        self.assertEqual(next_line["broadcast_ms"], 290000)
        self.assertEqual(app._PAGE_AIR_UNTIL[0], 302)

    def test_audit_distinguishes_unheard_rows_from_completed_delivery(self):
        audit = app.page_playback_state()["line_audit"][0]
        self.assertEqual(audit["scheduled_lines"], 1)
        self.assertEqual(audit["unconfirmed_line_ids"], ["a"])
        self.ack("playing", 0)
        self.assertFalse(app.page_playback_state()["line_audit"][0]["complete"])
        self.ack("ended", 3)
        self.assertTrue(app.page_playback_state()["line_audit"][0]["complete"])


class FlowJournalTests(unittest.TestCase):
    def test_history_survives_memory_rotation_and_supports_cursors(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = FlowJournal(Path(folder) / "flow.db", keep=2)
            entries = [journal.record("rewrite", "ok", f"line {i}",
                       {"source": f"source {i}"}, trace_id="call-one") for i in range(5)]
            journal.pending.join()
            recent = journal.read(limit=2)
            self.assertEqual([r["id"] for r in recent["events"]],
                             [r["id"] for r in entries[-2:]])
            earlier = journal.read(before=recent["events"][0]["id"], limit=2)
            self.assertEqual([r["summary"] for r in earlier["events"]], ["line 1", "line 2"])
            next_page = journal.read(after=entries[0]["id"], limit=2)
            self.assertEqual(next_page["cursor"], entries[2]["id"])
            self.assertTrue(next_page["truncated"])
            restored = FlowJournal(journal.path).read(limit=10)
            self.assertEqual(len(restored["events"]), 5)

    def test_event_details_redact_keys_and_signed_urls(self):
        result = clean_detail({"api_key": "private", "url": "/media/a?t=private",
                               "text": "Bearer private"})
        self.assertNotIn("private", str(result))
        self.assertIn("[redacted]", str(result))


if __name__ == "__main__":
    unittest.main()
