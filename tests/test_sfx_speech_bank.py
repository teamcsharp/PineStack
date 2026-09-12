import asyncio
from contextlib import ExitStack
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sfx_speech_bank import SfxSpeechBank


class SfxSpeechBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = [1000.0]
        self.bank = SfxSpeechBank(self.root / "bank.json", self.root, clock=lambda: self.now[0])

    def ready(self, text="I hear you clear, keep talking here.", generic=True, voice="drop-one"):
        self.bank.seed(voice, "crystal-one", [{"text": text, "generic": generic}])
        row = next(row for row in self.bank.rows(voice) if row["text"] == text)
        filename = row["id"] + ".wav"
        (self.root / filename).write_bytes(b"a real fixture file")
        row.update(state="ready", clip={"path": "/media/" + filename, "seconds": 3})
        self.bank.put(row)
        return row

    def test_distinct_reservations_commit_once_and_survive_restart(self):
        self.ready()
        self.ready("Keep that thought, I heard a lot.")
        first = self.bank.pick("anything", "drop-one", "crystal-one", lambda row: True)
        second = self.bank.pick("anything", "drop-one", "crystal-one", lambda row: True)
        self.assertNotEqual(first["entry_id"], second["entry_id"])
        self.assertIsNone(self.bank.pick("anything", "drop-one", "crystal-one", lambda row: True))
        restored = SfxSpeechBank(self.bank.path, self.root, clock=lambda: self.now[0])
        self.assertTrue(restored.finish(first["id"], heard=True))
        self.assertFalse(restored.finish(first["id"], heard=True))
        self.assertTrue(restored.finish(second["id"], heard=False))
        self.assertEqual(sum(row.get("plays", 0) for row in restored.rows()), 1)
        picked = restored.pick("anything", "drop-one", "crystal-one", lambda row: True)
        self.assertEqual(picked["entry_id"], second["entry_id"])

    def test_missing_media_wrong_voice_profile_and_failed_proof_cannot_air(self):
        row = self.ready()
        self.assertIsNone(self.bank.pick("", "other", "crystal-one", lambda row: True))
        self.assertIsNone(self.bank.pick("", "drop-one", "new-crystal", lambda row: True))
        self.assertIsNone(self.bank.pick("", "drop-one", "crystal-one", lambda row: False))
        (self.root / Path(row["clip"]["path"]).name).unlink()
        self.assertIsNone(self.bank.pick("", "drop-one", "crystal-one", lambda row: True))
        self.assertEqual(len(self.bank.rows()), 1)

    def test_topical_takes_need_context_and_generic_remains_fallback(self):
        topical = self.ready("The carburetor rattles loud, the engine draws a crowd.", generic=False)
        self.assertIsNone(self.bank.pick("I heard the weather forecast", "drop-one", "crystal-one", lambda row: True))
        generic = self.ready()
        pick = self.bank.pick("The engine carburetor needs work", "drop-one", "crystal-one", lambda row: True)
        self.assertEqual(pick["entry_id"], topical["id"])
        self.assertEqual(self.bank.pick("weather", "drop-one", "crystal-one", lambda row: True)["entry_id"], generic["id"])

    def test_abandoned_lease_expires_without_counting_audio_as_heard(self):
        self.ready()
        old = self.bank.pick("", "drop-one", "crystal-one", lambda row: True, lease_seconds=5)
        self.now[0] += 6
        new = self.bank.pick("", "drop-one", "crystal-one", lambda row: True)
        self.assertNotEqual(old["id"], new["id"])
        self.assertFalse(self.bank.finish(old["id"], heard=True))
        self.assertEqual(self.bank.rows()[0].get("plays", 0), 0)

    def test_save_failure_is_atomic_and_async_update_preserves_recent_ack(self):
        row = self.ready()
        saved = self.bank.path.read_bytes()
        with mock.patch.object(Path, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.bank.pick("", "drop-one", "crystal-one", lambda row: True)
        self.assertEqual(self.bank.path.read_bytes(), saved)
        self.assertNotIn("reservation", self.bank.rows()[0])
        reservation = self.bank.pick("", "drop-one", "crystal-one", lambda row: True)
        self.bank.finish(reservation["id"], heard=True)
        self.bank.put(row)
        self.assertEqual(self.bank.rows()[0]["plays"], 1)
        self.assertEqual(len(self.bank.protected_files()), 1)

    def test_source_words_are_not_clipped_and_ownership_cannot_change(self):
        self.assertEqual(self.bank.seed("drop-one", "crystal-one", [{"text": "word " * 90}]), 0)
        row = self.ready()
        row["voice"] = "wrong actor"
        with self.assertRaises(ValueError):
            self.bank.put(row)

    def test_stale_preparation_cannot_resurrect_released_or_committed_reservation(self):
        self.ready()
        for heard in (False, True):
            picked = self.bank.pick("", "drop-one", "crystal-one", lambda row: True)
            stale = self.bank.rows()[0]
            self.assertTrue(stale.get("reservation"))
            self.bank.finish(picked["id"], heard=heard)
            self.bank.put(stale)
            current = self.bank.rows()[0]
            self.assertNotIn("reservation", current)
            self.assertNotIn("reserved_until", current)
            self.assertEqual(current.get("plays", 0), int(heard))
            if heard:
                self.assertEqual(current["last_played"], self.now[0])

    def test_different_sources_cannot_reserve_or_repeat_identical_recorded_words(self):
        first = self.ready()
        second = self.ready("Another original source.")
        second["text"] = first["text"]
        self.bank.put(second)
        picked = self.bank.pick("", "drop-one", "crystal-one", lambda row: True)
        self.assertIsNone(self.bank.pick("", "drop-one", "crystal-one", lambda row: True))
        self.bank.finish(picked["id"], heard=True)
        self.assertIsNone(self.bank.pick("", "drop-one", "crystal-one", lambda row: True))


class SfxSpeechPreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import app
        self.app = app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bank = SfxSpeechBank(self.root / "bank.json", self.root)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {"drop_voice": "vl_31d384e6", "sfxguy_rate": 40}
        self.clips = {}
        self.text = "I hear you clear, keep talking here."

        async def render(text, who, voice, kind):
            key = app.pantry_key(text, voice, "xtts")
            filename = key + ".wav"
            (self.root / filename).write_bytes(b"fixture audio")
            self.clips[key] = {"path": "/media/" + filename, "seconds": 3.2}
            return {"key": key, "voice": voice, "engine": "xtts", "seconds": 3.2}

        values = {"_SFX_READY_BANK": self.bank, "_SFX_READY_LOCK": asyncio.Lock(),
            "_SFX_READY_STATE": {}, "dj_settings": lambda: self.settings,
            "_sfxguy_ready_profile": lambda: "current", "sfxguy_quips": lambda voice: [],
            "voice_engine_for": lambda voice: "xtts", "prep_should_stop": lambda: "",
            "pantry_window": lambda: "spare", "dialogue_tint_wanted": lambda: True,
            "tint_coverage_ready": lambda report: bool(report and report.get("ok")),
            "_tint_paper": lambda got: copy.deepcopy(got), "looks_english": lambda text: True,
            "_looks_meta": lambda text: False, "rap_rhyme_evidence": lambda text: {"ok": True},
            "crystal_tint": mock.AsyncMock(return_value={"ok": True, "script": self.text}),
            "prep_render_line": mock.AsyncMock(side_effect=render),
            "pantry_get": lambda key: self.clips.get(key),
            "ask_model": mock.AsyncMock(side_effect=AssertionError("No live model")),
            "voice_render_any": mock.AsyncMock(side_effect=AssertionError("No live TTS"))}
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    async def test_rejected_head_does_not_starve_next_source_and_no_untinted_tts(self):
        self.app.crystal_tint.side_effect = [{"ok": False, "script": "failed", "progress": {"kept": "source"}},
                                           {"ok": True, "script": self.text}]
        result = await self.app.sfxguy_ready_prepare(2)
        self.assertEqual(result["made"], 1)
        self.app.prep_render_line.assert_awaited_once_with(self.text, "drop", "vl_31d384e6", kind="sfxguy")
        failed = next(row for row in self.bank.rows() if row.get("attempts") == 1)
        self.assertEqual(failed["tint_progress"], {"kept": "source"})
        self.assertGreater(failed["retry_at"], failed["last_attempt"])

    async def test_deferred_writer_keeps_progress_without_spending_quality_attempt(self):
        self.app.crystal_tint.return_value = {"deferred": True, "progress": {"turn": 1}}
        await self.app.sfxguy_ready_prepare()
        self.app.prep_render_line.assert_not_awaited()
        row = next(row for row in self.bank.rows() if row.get("tint_progress"))
        self.assertEqual(row["attempts"], 0)
        self.assertEqual(row["tint_progress"], {"turn": 1})

    async def test_cancelled_recording_keeps_exact_accepted_source_and_proof(self):
        self.app.prep_render_line.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.app.sfxguy_ready_prepare()
        row = next(row for row in SfxSpeechBank(self.bank.path, self.root).rows() if row.get("tint_ok"))
        self.assertEqual(row["text"], self.text)
        self.assertTrue(row["text_plain"])
        self.assertNotEqual(row["text_plain"], row["text"])

    async def test_overlapping_prepare_has_one_owner_and_voice_switch_refuses_recording(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def tint(*args, **kwargs):
            entered.set()
            await release.wait()
            return {"ok": True, "script": self.text}
        self.app.crystal_tint.side_effect = tint
        task = asyncio.create_task(self.app.sfxguy_ready_prepare())
        await entered.wait()
        self.assertEqual((await self.app.sfxguy_ready_prepare())["made"], 0)
        self.settings["drop_voice"] = "another-voice"
        release.set()
        await task
        self.app.prep_render_line.assert_not_awaited()
        self.assertEqual(self.app.crystal_tint.await_count, 1)

    async def test_pick_is_model_free_full_voice_bound_and_text_mutation_refuses(self):
        await self.app.sfxguy_ready_prepare()
        calls = self.app.crystal_tint.await_count
        pick = self.app.sfxguy_ready_pick("anything", "vl_31d384e6")
        self.assertIsNotNone(pick)
        self.assertEqual((pick["text"], pick["voice"], pick["who"]), (self.text, "vl_31d384e6", "drop"))
        self.assertTrue(self.app.sfxguy_ready_release(pick["id"]))
        self.assertIsNone(self.app.sfxguy_ready_pick("anything", "wrong-voice"))
        row = next(row for row in self.bank.rows() if row.get("clip"))
        row["text"] += " Extra unrecorded words."
        self.bank.put(row)
        self.assertIsNone(self.app.sfxguy_ready_pick("anything", "vl_31d384e6"))
        self.assertEqual(self.app.crystal_tint.await_count, calls)
        self.app.ask_model.assert_not_awaited()
        self.app.voice_render_any.assert_not_awaited()

    async def test_status_read_counts_reserved_ready_and_missing_media_without_work(self):
        await self.app.sfxguy_ready_prepare()
        calls = self.app.crystal_tint.await_count
        pick = self.app.sfxguy_ready_pick("", "vl_31d384e6")
        status = self.app._sfxguy_ready_status()
        self.assertEqual((status["ready"], status["reserved"], status["heard"]), (1, 1, 0))
        self.assertEqual(status["last_ready"]["voice"], "vl_31d384e6")
        self.app.sfxguy_ready_commit(pick["id"])
        self.assertEqual(self.app._sfxguy_ready_status()["heard"], 1)
        (self.root / Path(pick["clip"]["path"]).name).unlink()
        self.assertEqual(self.app._sfxguy_ready_status()["ready"], 0)
        self.assertEqual(self.app.crystal_tint.await_count, calls)
        self.assertEqual(self.app.prep_render_line.await_count, 1)


if __name__ == "__main__":
    unittest.main()
