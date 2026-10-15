"""Exercise picture identity through durable storage, replay and retiming."""
import asyncio
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_sfx_turn_resume_2026_10_11 import actual
from sfx_cadence import SfxCadence


class ReplayPictures(unittest.TestCase):
    def station(self):
        pictures, deliveries = [], []
        def append_picture(row, at_ms):
            pictures.append(dict(row, broadcast_ms=at_ms))
        def append_delivery(row):
            deliveries.append(row)
            return "new-delivery"
        ns = {
            "asyncio": asyncio,
            "time": SimpleNamespace(time=lambda: 100), "hashlib": hashlib,
            "_RADIO": {"voice_clips": pictures}, "_PAGE_RESERVATION_UPDATES": {},
            "media_sign": lambda key: "signed", "page_picture_append": append_picture,
            "page_feed_append": append_delivery,
            "_broadcast_replayable": lambda row: {"key": row["clip_media"], "sig": "signed"},
            "AIRLOG_TURN_ROUNDS": set(), "HEARD_STAMP": "heard_at",
            "HEARD_STAMP_BY": "heard_by", "turn_edge_row_text": lambda r: r["text"],
            "line_repeat": SimpleNamespace(fingerprint=lambda text: text),
            "modifiers_for_sid": lambda sid: [],
            "_SFX_CADENCE": SimpleNamespace(samples_for=lambda ids: {}),
            "sfx_db_path_of": lambda key: Path(key + ".mp4"),
            "sfx_is_video": lambda path: path.suffix == ".mp4",
        }
        actual(["_sfx_picture_metadata", "airlog_row_from", "airlog_row_hash",
                "_sfx_replay_picture_rows", "_broadcast_replay", "_sfx_cadence_pictures"], ns)
        return ns, pictures, deliveries

    def test_legacy_round_recovers_exact_video_from_durable_receipt(self):
        ns, _, deliveries = self.station()
        with TemporaryDirectory() as directory:
            ledger = SfxCadence(Path(directory) / "receipts.sqlite3")
            ledger.record([dict(id="old-row", units=0, sample="exact-video")])
            ns["_SFX_CADENCE"] = ledger
            old = dict(id="old-row", who="board", text="ambiguous clip name",
                       clip_media="old.wav", clip_from=10, clip_until=15)
            asyncio.run(ns["_broadcast_replay"]([old], [old], []))
            restored = deliveries[0]["stream"]["rows"][0]
            self.assertEqual(restored["sfx_video_id"], "exact-video")
            self.assertEqual(restored["sfx_video_seconds"], 5)
            self.assertNotIn("sfx_video_id", old, "reading a replay must not mutate history")

    def test_legacy_audio_sample_does_not_become_a_video(self):
        ns, _, _ = self.station()
        ns["_SFX_CADENCE"] = SimpleNamespace(samples_for=lambda ids: {"row": "audio"})
        ns["sfx_db_path_of"] = lambda key: Path("clip.wav")
        row = ns["_sfx_replay_picture_rows"]([dict(id="row", who="board")])[0]
        self.assertNotIn("sfx_video_id", row)

    def test_restart_cue_sheet_recovers_original_timing(self):
        ns, _, _ = self.station()
        ns["_SFX_CADENCE"] = SimpleNamespace(samples_for=lambda ids: {"row": "video"})
        original = {"id": "row", "who": "board", "from": 12.5, "until": 18.25}
        restored = ns["_sfx_replay_picture_rows"]([original])[0]
        self.assertEqual(restored["sfx_video_seconds"], 5.75)
        self.assertEqual(restored["from"], 12.5)

    def test_welded_video_survives_log_and_replay_at_exact_audio_offset(self):
        ns, pictures, deliveries = self.station()
        original = dict(id="board-row", who="board", kind="sfx", text="a clip",
                        clip_media="round.wav", clip_from=12.125, clip_until=18.375,
                        sfx_sample_id="sample", sfx_video_id="video",
                        sfx_video_seconds=6.25, sfx_match_why="matched the caller")
        stored = ns["airlog_row_from"](original)
        asyncio.run(ns["_broadcast_replay"]([stored], [stored], []))
        replay = deliveries[0]["stream"]
        ns["_sfx_cadence_pictures"](replay["rows"], 100, occurrence="replay-1")
        self.assertEqual(pictures[0]["id"], "video")
        self.assertEqual(pictures[0]["broadcast_ms"], 112125)
        self.assertEqual(pictures[0]["seconds"], 6.25)
        self.assertTrue(pictures[0]["silent_picture"])
        self.assertEqual(replay["rows"][0]["until"], 18.375)

    def test_repeated_round_is_new_picture_but_receipt_retime_is_not(self):
        ns, pictures, _ = self.station()
        rows = [dict(id="same-row", sfx_video_id="video", from_=0)]
        ns["_sfx_cadence_pictures"](rows, 100, occurrence="first")
        ns["_sfx_cadence_pictures"](rows, 200, occurrence="replay")
        ns["_sfx_cadence_pictures"](rows, 201, retime=True, occurrence="replay")
        self.assertEqual(len(pictures), 2)
        self.assertNotEqual(pictures[0]["delivery_id"], pictures[1]["delivery_id"])
        self.assertEqual(pictures[0]["broadcast_ms"], 100000)
        self.assertEqual(pictures[1]["broadcast_ms"], 201000)

    def test_picture_identity_change_is_written_to_existing_log_row(self):
        ns, _, _ = self.station()
        self.assertNotEqual(ns["airlog_row_hash"]({"id": "row"}),
                            ns["airlog_row_hash"]({"id": "row", "sfx_video_id": "video"}))

    def test_audio_only_rows_do_not_invent_a_picture(self):
        ns, pictures, _ = self.station()
        ns["_sfx_cadence_pictures"]([{"id": "audio", "sfx_sample_id": "audio"}], 100)
        self.assertEqual(pictures, [])


if __name__ == "__main__":
    unittest.main()
