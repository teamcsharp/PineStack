import asyncio
import json
import struct
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app


class PageReservationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.radio = {"on": True, "voice_to": "here", "voice_clips": [], "chat": []}
        for name, value in {
            "PAGE_RECOVERY_PATH": self.root / "recovery.json", "VOICE_MEDIA_DIR": self.root,
            "_PAGE_RESERVATION_UPDATES": {}, "_PAGE_DELIVERIES": {},
            "_PAGE_AIR_UNTIL": [0], "_CLIP_SECS_CACHE": {}, "_RADIO": self.radio,
            "station_flow_event": mock.Mock(), "radio_paused": mock.Mock(return_value=False),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def wav(self, name="a.wav", seconds=2, streaming=False):
        pcm = b"\0\0" * (24000 * seconds)
        fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16)
        data = struct.pack("<4sI", b"data", 0xffffffff if streaming else len(pcm)) + pcm
        path = self.root / name
        path.write_bytes(b"RIFF" + struct.pack("<I", 0xffffffff if streaming else 4 + len(fmt + data))
                         + b"WAVE" + fmt + data)
        return path

    async def test_unfinalized_streaming_wav_uses_actual_pcm_bytes_not_four_gigabyte_header(self):
        streamed = self.wav("stream.wav", 13, True)
        normal = self.wav("normal.wav", 13)
        self.assertEqual(app._clip_seconds(str(streamed)), 13)
        self.assertEqual(app._clip_seconds(str(normal)), 13)
        with mock.patch.object(app.time, "time", return_value=1000):
            did = app.page_feed_append({"url": str(streamed), "text": "Host introduction."})
        self.assertTrue(did)
        self.assertEqual(app._PAGE_AIR_UNTIL[0], 1000 + app.VOICE_BROADCAST_LEAD_MS / 1000 + 13)

    async def test_repair_preserves_fifo_and_ids_and_never_retimes_started_audio(self):
        self.wav(seconds=2)
        active = {"delivery_id": "active", "url": str(self.root / "a.wav"), "broadcast_ms": 999000}
        first = {"delivery_id": "first", "url": str(self.root / "a.wav"), "broadcast_ms": 90000000}
        second = {"delivery_id": "second", "url": str(self.root / "a.wav"), "broadcast_ms": 90002000,
                  "stream": {"rows": [{"id": "last", "who": "cohost", "text": "The actual last line."}]}}
        self.radio["voice_clips"] = [active, first, second]
        app._PAGE_DELIVERIES.update({"active": {"state": "playing", "listeners": {"p": {"started": True}}},
                                    "first": {"state": "received"}, "second": {"state": "received"}})
        with mock.patch.object(app.time, "time", return_value=1000):
            updates = app.page_reservation_repair()
        self.assertEqual(active["broadcast_ms"], 999000)
        self.assertEqual([r["delivery_id"] for r in updates], ["first", "second"])
        self.assertEqual(second["broadcast_ms"] - first["broadcast_ms"], 2000)
        saved = app.page_recovery_read()
        self.assertEqual([r["delivery_id"] for r in saved], ["first", "second"])
        self.assertEqual(saved[-1]["stream"]["rows"][-1]["text"], "The actual last line.")

    async def test_correct_future_queue_is_unchanged_and_updates_ignore_since_filter(self):
        self.wav(seconds=2)
        clip = {"delivery_id": "waiting", "url": str(self.root / "a.wav"),
                "broadcast_ms": 1008000, "ts": 900000}
        self.radio["voice_clips"] = [clip]
        app._PAGE_DELIVERIES["waiting"] = {"state": "received"}
        app._PAGE_RESERVATION_UPDATES["waiting"] = 1008000
        with (mock.patch.object(app.time, "time", return_value=1000),
              mock.patch.object(app, "require_read_auth"), mock.patch.object(app, "low_note_rate")):
            feed = await app.dj_voice_api(since=999999999)
        self.assertEqual(feed["clips"], [])
        self.assertEqual(feed["reservation_updates"], [{"delivery_id": "waiting", "broadcast_ms": 1008000}])
        self.assertEqual(clip["broadcast_ms"], 1008000)

    async def test_saved_pending_delivery_survives_restart_until_actual_completion(self):
        self.wav(seconds=2)
        rows = [{"id": "one", "who": "dj", "text": "First.", "from": 0, "until": 1},
                {"id": "two", "who": "cohost", "text": "Last.", "from": 1, "until": 2}]
        app.page_recovery_write([{"delivery_id": "recover", "url": str(self.root / "a.wav"),
                                  "speech": True, "stream": {"rows": rows, "length": 2}}])
        with (mock.patch.object(app, "_floor_take", return_value=True),
              mock.patch.object(app, "_floor_drop"), mock.patch.object(app, "_paged_settle")):
            await app.page_recovery_start()
        self.assertEqual([r["text"] for r in self.radio["chat"]], ["First.", "Last."])
        self.assertEqual(self.radio["voice_clips"][0]["delivery_id"], "recover")
        self.assertEqual(len(app.page_recovery_read()), 1)
        with (mock.patch.object(app, "listener_note"), mock.patch.object(app, "air_remember"),
              mock.patch.object(app, "talk_said_now"), mock.patch.object(app, "_stream_now_set"),
              mock.patch.object(app, "render_backlog_ack")):
            for event, position, sequence in [("playing", 0, 1), ("playing", 1.2, 2), ("ended", 2, 3)]:
                app.page_playback_ack({"delivery_id": "recover", "listener_id": "actual-page",
                    "event": event, "current_time": position, "sequence": sequence,
                    "volume": .4, "audible_volume": .4})
        self.assertEqual(app.page_recovery_read(), [])


if __name__ == "__main__":
    unittest.main()
