import asyncio
import copy
import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from system2_media import System2Media


class MediaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.voice, self.ads = root / "voice", root / "ads"
        self.voice.mkdir()
        self.ads.mkdir()
        self.h = SimpleNamespace(
            VOICE_MEDIA_DIR=self.voice, PRODUCED_ADS_DIR=self.ads,
            _PANTRY={}, _TRACK_TALK={}, _RADIO={"on": True, "voice_to": "here"},
            _BOX_DOWN={}, _BOX_HOLD=[], _PAGE_AIR_UNTIL=[0], _PAGE_ACKED_LINES=set(),
            _LAST_PLAYOUT={}, VOICE_BROADCAST_LEAD_MS=0,
            media_sign=lambda name: "signed-" + name,
            pantry_key=lambda text, voice, engine: hashlib.sha256(
                (text + voice + engine).encode()).hexdigest(),
            is_binned=lambda text: False, station_name_scrub=lambda text: text,
            dialogue_row_ready=lambda kind, row: not row.get("refused"),
            dialogue_row_viable=lambda kind, row: not row.get("refused"),
            dialogue_entry=lambda row: row.get("entry"),
            _ready_round_takes=lambda kind, row: row["entry"]["takes"],
            track_talk_part_ready=lambda row: bool(row and row.get("tint_ok")),
            dialogue_tint_required=lambda: True,
            radio_paused=lambda: False,
            _banter_air=AsyncMock(return_value=["accepted"]),
            _floor_take=AsyncMock(return_value=True), _floor_drop=Mock(),
            page_carries_live=lambda route, box, down: route in ("here", "both"),
            page_feed_append=Mock(return_value="delivery-1"), page_delivery_apply=Mock(),
            _play_on_box=AsyncMock(return_value="played"),
            _played_out_key=lambda path: path.rsplit("/", 1)[-1],
            _box_receipt_audible=lambda r: not r.get("intentional_mute") and r.get("audible_gain", 1) > 0,
            _ready_round_ack=Mock(), air_remember=Mock(), ad_list=lambda: self.book,
            ask_model=AsyncMock(side_effect=AssertionError("writer on air")),
            voice_render_any=AsyncMock(side_effect=AssertionError("TTS on air")))
        self.book = []
        self.media = System2Media(self.h)

    def wav(self, root, name="take.wav", seconds=.2, sample=5):
        path = root / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(int(sample).to_bytes(2, "little", signed=True) * int(seconds * 8000))
        return path

    def single(self, text="This exact saved wording stays put.", who="dj", name="take.wav"):
        self.wav(self.voice, name)
        voice = "recorded-" + who
        key = self.h.pantry_key(text, voice, "piper")
        self.h._PANTRY[key] = {"text": text[:600], "voice": voice, "who": who,
                              "clip": {"path": "/media/" + name, "seconds": 999}}
        return {"text": text, "voice": voice, "who": who, "key": key, "tint_ok": True,
                "brief": {"ok": True}}

    def produced(self):
        self.wav(self.ads, "ad.wav")
        self.book = [{"id": "ad-1", "audio": "ad.wav", "text": "The exact finished advert.",
                      "voice": "original-ad-voice", "product": "Widget"}]
        return {"produced": "ad-1", "audio": "ad.wav", "text": self.book[0]["text"]}

    def test_proof_reads_bytes_duration_and_signed_canonical_url(self):
        path = self.wav(self.voice)
        proof = self.media.proof({"path": "/media/take.wav?old=signature", "seconds": 999})
        self.assertEqual(proof["audio_hash"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(proof["seconds"], .2)
        self.assertEqual(proof["url"], "/media/take.wav?t=signed-take.wav")
        self.wav(self.voice, seconds=.3, sample=9)
        changed = self.media.proof({"path": "/media/take.wav"})
        self.assertNotEqual(proof["audio_hash"], changed["audio_hash"])
        self.assertEqual(changed["seconds"], .3)

    def test_unrelated_routes_traversal_and_corrupt_audio_refuse(self):
        self.wav(self.voice)
        for path in ("https://elsewhere/media/take.wav", "/unrelated/take.wav",
                     "/media/../take.wav", "/media/sub/take.wav", "/media/missing.wav"):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.media.proof({"path": path})
        (self.voice / "broken.wav").write_bytes(b"not recorded audio")
        with self.assertRaises(ValueError):
            self.media.proof({"path": "/media/broken.wav", "seconds": 20})

    def test_raw_singles_support_all_three_roads_without_recasting(self):
        for kind, who in (("ad", "dj"), ("manager", "cohost"), ("station_id", "drop")):
            with self.subTest(kind=kind):
                row = self.single(who=who)
                got = self.media.resolve(kind, row)
                self.assertTrue(got["ready"], got["why"])
                self.assertIs(got["source_row"], row)
                self.assertEqual(got["takes"][0]["who"], who)
                self.assertEqual(got["takes"][0]["voice"], row["voice"])
                self.assertEqual(got["seconds"], .2)

    def test_changed_text_voice_speaker_or_contract_refuses(self):
        for change in ({"text": "Another line"}, {"voice": "recast"}, {"who": "cohost"}, {"refused": True}):
            row = self.single()
            row.update(change)
            self.assertFalse(self.media.resolve("ad", row)["ready"])

    def test_long_pantry_preview_is_bound_by_full_text_key(self):
        text = "Original words. " * 60
        row = self.single(text)
        self.assertTrue(self.media.resolve("ad", row)["ready"])
        row["text"] = text[:600] + "Different tail."
        self.assertFalse(self.media.resolve("ad", row)["ready"])

    def test_whole_round_keeps_duplicate_positions_and_actual_duration(self):
        row = self.single()
        take = self.media.resolve("ad", row)["takes"][0]
        entry = {"script": "A: " + row["text"] + "\nA: " + row["text"],
                 "takes": [take, {**copy.deepcopy(take), "i": 1}]}
        got = self.media.resolve("banter", {"entry": entry})
        self.assertTrue(got["ready"])
        self.assertEqual([t["i"] for t in got["takes"]], [0, 1])
        self.assertEqual(got["seconds"], .4)
        self.assertEqual(len(set(t["audio_hash"] for t in got["takes"])), 1)

    async def test_single_delivery_uses_exact_strict_player_and_proof(self):
        row = self.single(who="drop")
        resolved = self.media.resolve("station_id", row)
        proof = {"reservation_id": "r", "token": "secret-fixture-token"}
        result = await self.media.deliver(resolved, Mock(), lambda: True,
                                          {"_system2": proof})
        self.assertTrue(result)
        args, kw = self.h._banter_air.call_args
        self.assertEqual(args[0]["_system2"], proof)
        self.assertEqual(kw["ready_takes"][0]["text"], row["text"])
        self.assertEqual(kw["ready_takes"][0]["voice"], row["voice"])
        self.assertEqual(kw["ready_takes"][0]["who"], "drop")
        self.h.ask_model.assert_not_called()
        self.h.voice_render_any.assert_not_called()

    async def test_media_changed_since_inventory_refuses_before_handoff(self):
        row = self.single()
        resolved = self.media.resolve("ad", row)
        self.wav(self.voice, sample=100)
        commit = Mock()
        self.assertFalse(await self.media.deliver(resolved, commit, lambda: True))
        commit.assert_not_called()
        self.h._banter_air.assert_not_called()

    async def test_track_links_stay_bound_to_record_and_position(self):
        intro, outro = self.single(), self.single(who="cohost", name="outro.wav")
        self.h._TRACK_TALK["track-1"] = {"intro": intro, "outro": outro, "track": {"id": "track-1"}}
        items = self.media.inventory_track_talk()
        self.assertEqual([i for i, _ in items], ["track-talk:track-1:intro", "track-talk:track-1:outro"])
        resolved = self.media.resolve("track_talk", items[0][1])
        self.assertTrue(resolved["ready"])
        self.h._RADIO["now"] = {"id": "track-1"}
        self.assertFalse(await self.media.deliver(resolved, Mock(), lambda: True))
        for track, part, expected in (("track-2", "intro", False), ("track-1", "outro", False),
                                      ("track-1", "intro", True)):
            result = await self.media.deliver(resolved, Mock(), lambda: True,
                {"_system2_track_position": {"track_id": track, "part": part}})
            self.assertEqual(result, expected)
        self.h._TRACK_TALK["track-1"]["intro"] = dict(intro)
        self.assertFalse(self.media.resolve("track_talk", items[0][1])["ready"])

    def test_produced_ad_needs_exact_book_transcript_and_owned_audio(self):
        row = self.produced()
        resolved = self.media.resolve("ad", row)
        self.assertTrue(resolved["ready"], resolved["why"])
        self.assertEqual(resolved["media_kind"], "produced")
        self.assertTrue(resolved["takes"][0]["path"].startswith("/ads-audio/"))
        row["text"] += " altered"
        self.assertFalse(self.media.resolve("ad", row)["ready"])

    async def test_produced_page_handoff_is_pending_until_real_ack(self):
        resolved = self.media.resolve("ad", self.produced())
        commit = Mock()
        self.assertTrue(await self.media.deliver(resolved, commit, lambda: True,
                                                {"_system2": {"token": "fixture"}}))
        commit.assert_called_once()
        clip = self.h.page_feed_append.call_args.args[0]
        self.assertEqual(clip["ready_round"]["_system2"], {"token": "fixture"})
        self.assertEqual(clip["stream"]["length"], .2)
        self.assertEqual(clip["stream"]["rows"][0]["remember_text"], self.book[0]["text"])
        self.h._ready_round_ack.assert_not_called()
        self.h.air_remember.assert_not_called()

    async def test_produced_box_muted_interrupted_or_unrelated_meter_never_heard(self):
        self.h._RADIO["voice_to"] = "box"
        for extra in ({"intentional_mute": True}, {"audible_gain": 0},
                      {"interrupted": True}, {"key": "another.wav"}):
            self.h._LAST_PLAYOUT = {"key": "ad.wav", "ok": True, "audible_gain": 2, **extra}
            self.assertTrue(await self.media.deliver(self.media.resolve("ad", self.produced()),
                                                    Mock(), lambda: True))
        self.h._ready_round_ack.assert_not_called()
        self.h.air_remember.assert_not_called()

    async def test_produced_box_real_receipt_credits_once(self):
        self.h._RADIO["voice_to"] = "box"
        self.h._LAST_PLAYOUT = {"key": "ad.wav", "ok": True, "audible_gain": 2}
        commit = Mock()
        self.assertTrue(await self.media.deliver(self.media.resolve("ad", self.produced()), commit, lambda: True))
        commit.assert_called_once()
        self.h._ready_round_ack.assert_called_once()
        self.h.air_remember.assert_called_once_with(self.book[0]["text"], "dj", "ad")

    async def test_device_submission_is_reserved_before_duration_elapses(self):
        self.h._RADIO["voice_to"] = "box"
        self.h._LAST_PLAYOUT = {"key": "ad.wav", "ok": True, "audible_gain": 2}
        elapsed = [0]
        submitted = []
        def handoff():
            self.assertLess(elapsed[0], .2, "complete duration must not be charged twice")
            submitted.append("submitted")
        async def played(path, sig):
            self.assertEqual(submitted, ["submitted"])
            elapsed[0] = .2
            return "played"
        self.h._play_on_box.side_effect = played
        self.assertTrue(await self.media.deliver(self.media.resolve("ad", self.produced()), handoff, lambda: True))
        self.assertEqual(submitted, ["submitted"])
        self.h._ready_round_ack.assert_called_once()

    async def test_known_failed_device_submission_returns_false_without_heard_receipt(self):
        self.h._RADIO["voice_to"] = "box"
        self.h._play_on_box.return_value = ""
        handoff = Mock()
        self.assertFalse(await self.media.deliver(self.media.resolve("ad", self.produced()), handoff, lambda: True))
        handoff.assert_called_once()  # runtime must release this known failed submission
        self.h._ready_round_ack.assert_not_called()
        self.h.air_remember.assert_not_called()

    async def test_produced_missing_after_floor_preserves_stock(self):
        row = self.produced()
        resolved = self.media.resolve("ad", row)
        async def occupy(*args):
            (self.ads / "ad.wav").unlink()
            return True
        self.h._floor_take.side_effect = occupy
        commit = Mock()
        self.assertFalse(await self.media.deliver(resolved, commit, lambda: True))
        self.h._floor_drop.assert_called_once()
        commit.assert_not_called()
        self.h.page_feed_append.assert_not_called()
        self.h._play_on_box.assert_not_called()

    async def test_no_route_or_lost_admission_never_publishes_or_commits(self):
        resolved = self.media.resolve("ad", self.produced())
        commit = Mock()
        self.h._RADIO["voice_to"] = "off"
        self.assertFalse(await self.media.deliver(resolved, commit, lambda: True))
        self.h._RADIO["voice_to"] = "here"
        self.assertFalse(await self.media.deliver(resolved, commit, lambda: False))
        admission = [True]
        async def floor(*args):
            admission[0] = False
            return True
        self.h._floor_take.side_effect = floor
        self.assertFalse(await self.media.deliver(resolved, commit, lambda: admission[0]))
        commit.assert_not_called()
        self.h.page_feed_append.assert_not_called()
        self.h._play_on_box.assert_not_called()

    async def test_page_then_box_receipt_does_not_double_credit(self):
        self.h._RADIO["voice_to"] = "both"
        self.h._LAST_PLAYOUT = {"key": "ad.wav", "ok": True, "audible_gain": 2}
        def early_page_ack(clip):
            self.h._PAGE_ACKED_LINES.add(clip["stream"]["rows"][0]["id"])
            return "page-was-audible"
        self.h.page_feed_append.side_effect = early_page_ack
        commit = Mock()
        self.assertTrue(await self.media.deliver(self.media.resolve("ad", self.produced()), commit, lambda: True))
        commit.assert_called_once()
        self.h.air_remember.assert_not_called()
        self.h._ready_round_ack.assert_called_once()


if __name__ == "__main__":
    unittest.main()
