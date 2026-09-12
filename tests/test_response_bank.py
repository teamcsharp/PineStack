import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from response_bank import PHRASES, ResponseBank, add_listening_responses, source_response


class ResponseBankTests(unittest.TestCase):
    def test_retirement_is_atomic_persistent_and_keeps_both_voices_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = ResponseBank(root / "bank.json", root)
            draft = source_response({"text": "How do gardens survive winter?",
                                     "keywords": ["gardens", "winter"]},
                                    {"file": "gardens.md", "text": "Gardens survive the winter."})
            bank.stage([draft])
            for voice in ("alice", "bob"):
                (root / f"{voice}.wav").write_bytes(voice.encode())
                clip = {"path": f"/media/{voice}.wav", "seconds": 2}
                bank.put(voice, "xtts", draft["text"], "topic", clip, draft)
                bank.put(voice, "xtts", "Mm-hmm.", "listening", clip)
            original_audio_store = bank.path.read_bytes()
            original_catalog = bank.catalog_path.read_bytes()
            original_replace = Path.replace
            with mock.patch.object(Path, "replace", autospec=True,
                    side_effect=original_replace) as replace:
                self.assertTrue(bank.retire("  " + draft["text"].upper() + "  ", "Reviewed wording is unsuitable."))
            replace.assert_called_once_with(bank.retired_path.with_suffix(".tmp"), bank.retired_path)
            restored = ResponseBank(bank.path, root)
            self.assertEqual(restored.retired()[0]["reason"], "Reviewed wording is unsuitable.")
            self.assertEqual(restored.catalog(), [])
            self.assertEqual(restored.stage([draft]), 0)
            variant = {**draft, "text": draft["text"].upper()}
            self.assertEqual(restored.stage([variant]), 0)
            for voice in ("alice", "bob"):
                self.assertEqual(restored.take(voice, "xtts", "Gardens survive winter.")["text"], "Mm-hmm.")
                self.assertNotIn(draft["text"], [r["text"] for r in restored.missing_entries(voice, "xtts")])
                status = restored.status({"voice": (voice, "xtts")})["voice"]
                self.assertEqual((status["ready"], status["source_ready"], status["source_drafts"]), (1, 0, 0))
                self.assertEqual((root / f"{voice}.wav").read_bytes(), voice.encode())
            self.assertEqual(restored.path.read_bytes(), original_audio_store)
            self.assertEqual(restored.catalog_path.read_bytes(), original_catalog)
            self.assertEqual(restored.protected_files(), {"alice.wav", "bob.wav"})
            # A failed atomic replacement neither corrupts prior decisions nor
            # claims an unpersisted retirement in this process.
            saved = restored.retired_path.read_bytes()
            with mock.patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    restored.retire("Mm-hmm.", "another reviewed response")
            self.assertEqual(restored.retired_path.read_bytes(), saved)
            self.assertEqual(restored.take("alice", "xtts")["text"], "Mm-hmm.")
            self.assertEqual(len(restored.retired()), 1)

    def test_full_retirement_ledger_never_revives_earlier_rejected_text(self):
        with tempfile.TemporaryDirectory() as folder:
            bank = ResponseBank(Path(folder) / "bank.json", Path(folder))
            bank.retirements = {str(i): {"text": f"Old reviewed response {i}."} for i in range(4096)}
            with self.assertRaisesRegex(ValueError, "full"):
                bank.retire("An additional reviewed response.", "capacity check")
            self.assertEqual(len(bank.retired()), 4096)
            self.assertEqual(bank.retired()[0]["text"], "Old reviewed response 0.")

    def test_generic_live_context_cannot_trigger_fire_or_quantity_question(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"audio fixture")
            bank = ResponseBank(root / "bank.json", root)
            clip = {"path": "/media/one.wav", "seconds": 2}
            bank.put("alice", "xtts", "Mm-hmm.", "listening", clip)
            fire = source_response({
                "text": "What are people talking about regarding those fires now?",
                "keywords": ["people", "now", "fire", "arsonist"]},
                {"file": "fires.md", "text": "People say arsonists started those fires, and now they debate conspiracy theories."})
            muffin = source_response({
                "text": "What about putting an equal amount in each muffin right now?",
                "keywords": ["amount", "each", "equal", "muffin", "now"]},
                {"file": "muffins.md", "text": "Put an equal amount of blueberries in each muffin right now."})
            self.assertEqual(muffin["anchors"], ["muffin"])
            for draft in (fire, muffin):
                self.assertTrue(bank.put("alice", "xtts", draft["text"], "topic", clip, draft))
            for context in ("People are listening to the radio now.",
                            "How long will it take for my repaired speaker to arrive?"):
                with self.subTest(context=context):
                    self.assertEqual(bank.take("alice", "xtts", context)["intent"], "listening")
            self.assertEqual(bank.take("alice", "xtts", "The fires are spreading.")["text"], fire["text"])
            self.assertEqual(bank.take("alice", "xtts", "This muffin tastes wonderful.")["text"], muffin["text"])
            vague = source_response({
                "text": "How long do you think it will take to get that amount done?",
                "keywords": ["amount", "long", "take"]},
                {"text": "How long it will take to put that equal amount in each muffin."})
            self.assertIsNone(vague)

    def test_old_unsuitable_source_rows_are_ineligible_without_losing_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "old.wav").write_bytes(b"preserved old recording")
            bank = ResponseBank(root / "bank.json", root)
            vague = {"text": "How long do you think it will take to get that amount done?",
                     "intent": "topic", "keywords": ["amount", "long", "take"],
                     "anchors": ["amount", "long", "take"],
                     "source": {"file": "muffins.md", "sampled_at": 123,
                                "text": "It takes a long time to get that amount done."}}
            old = {**vague, "voice": "alice", "engine": "xtts", "recorded_at": 456,
                   "clip": {"path": "/media/old.wav", "seconds": 2}}
            bank.path.write_text(json.dumps({bank.key("alice", "xtts", old["text"]): old}))
            bank.catalog_path.write_text(json.dumps([vague]))
            original_store = bank.path.read_bytes()
            original_catalog = bank.catalog_path.read_bytes()
            self.assertEqual(bank.catalog(), [])
            self.assertEqual(bank.ready("alice", "xtts"), [])
            self.assertIsNone(bank.take("alice", "xtts", "That amount takes a long time."))
            status = bank.status({"dj": ("alice", "xtts")})["dj"]
            self.assertEqual((status["ready"], status["source_ready"], status["source_drafts"]), (0, 0, 0))
            self.assertEqual(bank.path.read_bytes(), original_store)
            self.assertEqual(bank.catalog_path.read_bytes(), original_catalog)
            self.assertEqual(bank.protected_files(), {"old.wav"})
            self.assertEqual((root / "old.wav").read_bytes(), b"preserved old recording")

    def test_multiple_concrete_anchors_prevent_broad_person_or_filler_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"audio fixture")
            bank = ResponseBank(root / "bank.json", root)
            clip = {"path": "/media/one.wav", "seconds": 2}
            bank.put("alice", "xtts", "Mm-hmm.", "listening", clip)
            draft = source_response({"text": "Do you look at their toes when you find a woman?",
                                     "keywords": ["toes", "woman", "look"]},
                                    {"text": "I look at a woman's toes when meeting a woman."})
            bank.put("alice", "xtts", draft["text"], "topic", clip, draft)
            self.assertEqual(bank.take("alice", "xtts", "A woman repaired the radio.")["intent"], "listening")
            self.assertEqual(bank.take("alice", "xtts", "The woman's toes hurt.")["text"], draft["text"])
            for text, source in (
                ("What do you watch when you are fucking all day?", "I watch all day, fucking all day."),
                ("What are you trying to prove during those forty-five minutes?", "Forty-five minutes of trying to prove something."),
                ("How did you make millions from those videos and the site?", "Videos on the site made millions of dollars."),
            ):
                self.assertIsNone(source_response({"text": text, "keywords": ["watch", "trying", "minutes"]}, {"text": source}))

    def test_rejected_take_budget_persists_until_explicit_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = ResponseBank(root / "bank.json", root)
            for _ in range(3):
                bank.reject("alice", "piper", "Go on.", {"path": "/media/bad.wav", "seconds": 9}, "bad")
            restored = ResponseBank(bank.path, root)
            self.assertTrue(restored.retry_state("alice", "piper", "Go on.")["suspended"])
            with mock.patch("response_bank.time.time", return_value=1e12):
                self.assertNotIn("Go on.", [r["text"] for r in restored.missing_entries("alice", "piper", available_only=True)])
            self.assertEqual(restored.reset_retries({("bob", "piper")}), 0)
            self.assertEqual(restored.reset_retries({("alice", "piper")}), 1)
            self.assertIn("Go on.", [r["text"] for r in restored.missing_entries("alice", "piper", available_only=True)])

    def test_source_catalogue_and_matching_performances_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"audio fixture")
            bank = ResponseBank(root / "bank.json", root)
            source = {"file": "gardens.md", "text": "Gardens need seeds protected during winter."}
            draft = source_response({"text": "How do those gardens survive winter?",
                                     "keywords": ["gardens", "winter", "seeds"]}, source)
            self.assertEqual(bank.stage([draft, draft]), 1)
            clip = {"path": "/media/one.wav", "seconds": 2}
            bank.put("alice", "piper", "Mm-hmm.", "listening", clip)
            bank.put("alice", "piper", draft["text"], "topic", clip, draft)
            restored = ResponseBank(bank.path, root)
            self.assertEqual(restored.catalog()[0]["source"]["file"], "gardens.md")
            self.assertEqual(restored.catalog()[0]["source"]["text"], source["text"])
            self.assertEqual(restored.take("alice", "piper", "Winter makes the gardens hard to maintain.")["text"], draft["text"])
            self.assertEqual(restored.take("alice", "piper", "Winter makes the gardens hard to maintain.")["text"], "Mm-hmm.")
            self.assertEqual(restored.take("alice", "piper", "A caller is discussing a broken radio.")["text"], "Mm-hmm.")
            self.assertEqual(restored.status({"dj": ("alice", "piper")})["dj"]["target"], 64)

    def test_source_validation_rejects_ungrounded_tags_and_scene_claims(self):
        source = {"text": "Gardens need seeds protected during winter."}
        for text, keywords in [("I saw a mayor in those gardens.", ["gardens", "winter"]),
                               ("How do you fix a transmitter?", ["radio", "transmitter"]),
                               ("How do those gardens survive winter?", ["radio", "transmitter"]),
                               ("How do " + "those " * 20 + "gardens survive?", ["gardens", "winter"])]:
            got = source_response({"text": text, "keywords": keywords}, source)
            # Topic anchors occurring in the actual response can ground it
            # even when the model's extra tags are discarded.
            if text == "How do those gardens survive winter?":
                self.assertEqual(got["keywords"], ["garden", "winter"])
            else:
                self.assertIsNone(got)

    def test_mass_bank_retains_more_than_old_192_clip_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"audio fixture")
            bank = ResponseBank(root / "bank.json", root)
            clip = {"path": "/media/one.wav", "seconds": 1}
            for number in range(205):
                bank.put("alice", "piper", f"Response {number}.", "listening", clip)
            self.assertEqual(len(ResponseBank(bank.path, root).ready("alice", "piper")), 205)
            self.assertEqual(bank.protected_files(), {"one.wav"})

    def test_recorded_performances_survive_restart_and_match_the_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"audio fixture")
            bank = ResponseBank(root / "bank.json", root)
            clip = {"path": "/media/one.wav", "seconds": 1.2}
            self.assertTrue(bank.put("alice", "xtts", "Mm-hmm.", "listening", clip))
            restored = ResponseBank(bank.path, root)
            self.assertEqual(restored.take("alice", "xtts")["clip"], clip)
            self.assertIsNone(restored.take("bob", "xtts"))
            self.assertIsNone(restored.take("alice", "piper"))
            self.assertEqual(restored.protected_files(), {"one.wav"})
            (root / "one.wav").unlink()
            self.assertIsNone(restored.take("alice", "xtts"))

    def test_responses_preserve_all_words_and_original_speakers_in_order(self):
        original = [{"who": "dj", "chunk": f"Sentence {i}. " + "Words. " * 36,
                     "turn_end": i == 2} for i in range(3)]
        choose = mock.Mock(return_value={"text": "Mm-hmm.", "clip": {"path": "/media/one.wav"}})
        expanded = add_listening_responses(original, {"dj": "alice", "cohost": "bob"}, choose)
        self.assertEqual([r for r in expanded if not r.get("listening_response")], original)
        self.assertTrue(any(r.get("listening_response") for r in expanded))
        self.assertTrue(all(r["who"] == "cohost" for r in expanded if r.get("listening_response")))

    def test_no_recording_no_response_and_no_stealing_an_existing_reply(self):
        first = {"who": "dj", "chunk": "Sentence. " * 40}
        choose = mock.Mock(return_value=None)
        self.assertEqual(add_listening_responses([first], {"cohost": "bob"}, choose), [first])
        choose.reset_mock()
        exchange = [first, {"who": "cohost", "chunk": "Here is my answer."}]
        self.assertEqual(add_listening_responses(exchange, {"cohost": "bob"}, choose), exchange)
        choose.assert_not_called()
        self.assertEqual(add_listening_responses([first], {"cohost": "bob"}, choose, away="cohost"), [first])

    def test_damaged_response_store_cannot_prevent_original_dialogue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bank.json").write_text('{"bad": null, "wrong": {"clip": 42}}', encoding="utf-8")
            bank = ResponseBank(root / "bank.json", root)
            self.assertEqual(bank.ready("alice", "piper"), [])
        original = [{"who": "dj", "chunk": "Words. " * 50}]
        self.assertEqual(add_listening_responses(original, {"cohost": "bob"},
                         mock.Mock(side_effect=ValueError("bad optional store"))), original)

    def test_mid_turn_response_preserves_the_original_cut_boundary(self):
        original = [{"who": "dj", "chunk": "Words. " * 50, "turn_end": False},
                    {"who": "dj", "chunk": "And that is the ending.", "turn_end": True}]
        result = add_listening_responses(original, {"cohost": "bob"},
            mock.Mock(return_value={"text": "Hmm.", "clip": {"path": "/media/one.wav"}}))
        self.assertTrue(result[1]["continuation_response"])
        self.assertEqual(result[-1], original[-1])


class ResponsePreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        draft = mock.patch.object(app, "response_bank_draft", new=mock.AsyncMock(return_value=0))
        draft.start()
        self.addCleanup(draft.stop)
        settings = mock.patch.object(app, "dj_settings", return_value={})
        settings.start()
        self.addCleanup(settings.stop)

    async def test_authorized_prepare_api_passes_bounded_batch_and_source_refresh(self):
        with (mock.patch.object(app, "require_auth"),
              mock.patch.object(app, "response_bank_prepare", return_value={"made": 24}) as prepare):
            result = await app.response_bank_prepare_api(limit=24, draft=True, retry_rejected=True)
            prepare.assert_awaited_once_with(24, force_draft=True, retry_rejected=True)
            self.assertEqual(result["made"], 24)

    async def test_bad_cached_take_yields_to_later_phrases_then_recovers_fresh(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            for name in ("bad.wav", "good.wav"):
                (root / name).write_bytes(b"fixture")
            bank = ResponseBank(root / "bank.json", root)
            good = {"path": "/media/good.wav", "seconds": 1}
            bad = {"path": "/media/bad.wav", "seconds": 9}
            for text, intent in PHRASES[:3]:
                bank.put("alice", "piper", text, intent, good)
            bad_key = app.pantry_key("Go on.", "alice", "piper")
            pantry = {bad_key: {"clip": bad}, "other-use": {"clip": bad}}
            replay = {"bad-cache": dict(bad), "other-cache": dict(good)}
            rendered = []

            async def render(text, who, voice, **kwargs):
                key = app.pantry_key(text, voice, "piper")
                if key not in pantry:
                    rendered.append(text)
                    pantry[key] = {"clip": dict(good)}
                return {"key": key}

            replacements = {"_RESPONSES": bank, "_PANTRY": pantry,
                "_replay_cache": mock.Mock(return_value=replay), "_replay_save": mock.Mock(),
                "_pantry_save": mock.Mock(), "station_flow_event": mock.Mock(),
                "session_voices": mock.AsyncMock(return_value={"dj": "alice"}),
                "voice_engine_for": mock.Mock(return_value="piper"),
                "prep_should_stop": mock.Mock(return_value=""),
                "prep_render_line": mock.AsyncMock(side_effect=render),
                "pantry_get": mock.Mock(side_effect=lambda key: (pantry.get(key) or {}).get("clip"))}
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertEqual((await app.response_bank_prepare(1))["made"], 1)
            self.assertEqual(rendered, ["Hmm."])
            self.assertNotIn(bad_key, pantry)
            self.assertNotIn("bad-cache", replay)
            self.assertIn("other-cache", replay)
            self.assertIn("other-use", pantry)
            self.assertTrue((root / "bad.wav").is_file())
            restored = ResponseBank(bank.path, root)
            retry = restored.retry_state("alice", "piper", "Go on.")
            self.assertEqual(retry["attempts"], 1)
            self.assertNotIn("Go on.", [r["text"] for r in restored.missing_entries("alice", "piper", available_only=True)])
            app._RESPONSES = restored
            # A crash can restore an older pantry snapshot; the retry boundary
            # must invalidate that rejected identity again before synthesis.
            pantry[bad_key] = {"clip": bad}
            replay["bad-cache"] = dict(bad)
            with mock.patch("response_bank.time.time", return_value=retry["retry_after"] + 1):
                self.assertEqual((await app.response_bank_prepare(1))["made"], 1)
            self.assertEqual(rendered, ["Hmm.", "Go on."])
            self.assertEqual(restored.retry_state("alice", "piper", "Go on."), {})
            self.assertEqual(next(row for row in restored.ready("alice", "piper") if row["text"] == "Go on.")["clip"], good)

    async def test_both_presenters_warm_fairly_across_single_clip_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"fixture")
            bank = ResponseBank(root / "bank.json", root)
            with (mock.patch.object(app, "_RESPONSES", bank),
                  mock.patch.object(app, "session_voices", new=mock.AsyncMock(return_value={"dj": "alice", "cohost": "bob"})),
                  mock.patch.object(app, "voice_engine_for", return_value="piper"),
                  mock.patch.object(app, "prep_should_stop", return_value=""),
                  mock.patch.object(app, "prep_render_line", new=mock.AsyncMock(return_value={"key": "one"})),
                  mock.patch.object(app, "pantry_get", return_value={"path": "/media/one.wav", "seconds": 1}),
                  mock.patch.object(app, "station_flow_event")):
                for _ in range(4):
                    await app.response_bank_prepare(1)
            self.assertEqual(len(bank.ready("alice", "piper")), 2)
            self.assertEqual(len(bank.ready("bob", "piper")), 2)

    async def test_unavailable_host_engine_does_not_starve_cohost(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"fixture")
            bank = ResponseBank(root / "bank.json", root)
            async def render(text, who, voice, **kwargs):
                if who == "dj":
                    raise RuntimeError("host engine is offline")
                return {"key": "one"}
            with (mock.patch.object(app, "_RESPONSES", bank),
                  mock.patch.object(app, "session_voices", new=mock.AsyncMock(return_value={"dj": "alice", "cohost": "bob"})),
                  mock.patch.object(app, "voice_engine_for", return_value="piper"),
                  mock.patch.object(app, "prep_should_stop", return_value=""),
                  mock.patch.object(app, "prep_render_line", side_effect=render),
                  mock.patch.object(app, "pantry_get", return_value={"path": "/media/one.wav", "seconds": 1}),
                  mock.patch.object(app, "station_flow_event")):
                self.assertEqual((await app.response_bank_prepare(2))["made"], 2)
            self.assertEqual(len(bank.ready("bob", "piper")), 2)

    async def test_paused_preparation_stores_real_clips_and_reuses_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.wav").write_bytes(b"fixture")
            bank = ResponseBank(root / "bank.json", root)
            with (mock.patch.object(app, "_RESPONSES", bank),
                  mock.patch.object(app, "session_voices", new=mock.AsyncMock(return_value={"dj": "alice"})),
                  mock.patch.object(app, "voice_engine_for", return_value="piper"),
                  mock.patch.object(app, "prep_should_stop", return_value=""),
                  mock.patch.object(app, "prep_render_line", new=mock.AsyncMock(return_value={"key": "one"})) as render,
                  mock.patch.object(app, "pantry_get", return_value={"path": "/media/one.wav", "seconds": 1}),
                  mock.patch.object(app, "station_flow_event")):
                self.assertEqual((await app.response_bank_prepare(1))["made"], 1)
                self.assertEqual(len(bank.ready("alice", "piper")), 1)
                first = render.await_args.args[0]
                await app.response_bank_prepare(1)
                self.assertNotEqual(render.await_args.args[0], first)

    async def test_busy_engine_leaves_response_owed_without_faking_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            bank = ResponseBank(Path(folder) / "bank.json", Path(folder))
            with (mock.patch.object(app, "_RESPONSES", bank),
                  mock.patch.object(app, "session_voices", new=mock.AsyncMock(return_value={"dj": "alice"})),
                  mock.patch.object(app, "voice_engine_for", return_value="piper"),
                  mock.patch.object(app, "prep_should_stop", return_value="the engine is full"),
                  mock.patch.object(app, "prep_render_line", new=mock.AsyncMock()) as render):
                self.assertEqual((await app.response_bank_prepare())["made"], 0)
                render.assert_not_awaited()
                self.assertEqual(bank.ready("alice", "piper"), [])


class SourceResponseDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_saturation_and_busy_global_gate_still_use_reserved_writer_admission(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            bank = ResponseBank(Path(folder) / "bank.json", Path(folder))
            output = [{"source": 0, "text": "How do gardens survive winter?",
                       "keywords": ["gardens", "winter"]}]
            replacements = {"_RESPONSES": bank, "_RESPONSE_DRAFT_STATE": {"last_at": 0},
                "_OLLAMA_GATE": asyncio.Semaphore(0),
                "prep_should_stop": mock.Mock(return_value="the engine is full"),
                "response_bank_sources": mock.Mock(return_value=[
                    {"file": "gardens.md", "text": "Gardens need seeds protected during winter."}]),
                "load_settings": mock.Mock(return_value={"model": "local"}),
                "model_ctx": mock.Mock(return_value=8192), "task_note": mock.Mock(),
                "station_flow_event": mock.Mock(),
                "call_ollama": mock.AsyncMock(return_value={"message": {"content": json.dumps(output)}})}
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertEqual(await app.response_bank_draft(force=True), 1)
            app.call_ollama.assert_awaited_once()
            self.assertEqual(app.call_ollama.await_args.kwargs["purpose"], "response_bank")

    async def test_one_model_batch_stages_grounded_sources_for_both_voices(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            bank = ResponseBank(Path(folder) / "bank.json", Path(folder))
            output = [{"source": 0, "text": "How do gardens survive winter?",
                       "keywords": ["gardens", "winter", "seeds"]},
                      {"source": 1, "text": "What protects seeds in winter?",
                       "keywords": ["gardens", "winter", "seeds"]},
                      {"source": 90, "text": "How do radios work?", "keywords": ["radios"]}]
            replacements = {"_RESPONSES": bank, "_RESPONSE_DRAFT_STATE": {"last_at": 0},
                "_OLLAMA_GATE": asyncio.Semaphore(1), "prep_should_stop": mock.Mock(return_value=""),
                "response_bank_sources": mock.Mock(return_value=[{"file": "gardens.md", "text": "Gardens need seeds protected during winter."}] * 4),
                "load_settings": mock.Mock(return_value={"model": "local"}),
                "model_ctx": mock.Mock(return_value=8192), "task_note": mock.Mock(),
                "station_flow_event": mock.Mock(),
                "call_ollama": mock.AsyncMock(return_value={"message": {"content": json.dumps(output)}})}
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertEqual(await app.response_bank_draft(), 2)
            self.assertEqual(await app.response_bank_draft(), 0)
            self.assertEqual(app.call_ollama.await_count, 1)
            self.assertEqual(len(bank.missing("alice", "piper")), 10)
            self.assertEqual(len(bank.missing("bob", "xtts")), 10)
            self.assertEqual(bank.catalog()[0]["source"]["file"], "gardens.md")

    async def test_source_failure_preserves_existing_recordings_and_catalogue(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            bank = ResponseBank(Path(folder) / "bank.json", Path(folder))
            replacements = {"_RESPONSES": bank, "_RESPONSE_DRAFT_STATE": {"last_at": 0},
                "_OLLAMA_GATE": asyncio.Semaphore(1), "prep_should_stop": mock.Mock(return_value=""),
                "response_bank_sources": mock.Mock(side_effect=RuntimeError("source unavailable"))}
            for name, value in replacements.items():
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertEqual(await app.response_bank_draft(), 0)
            self.assertEqual(len(bank.missing("alice", "piper")), 8)
            self.assertIn("retry", app._RESPONSE_DRAFT_STATE["why"])

    def test_reference_draw_needs_no_model_or_unused_gems(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = ResponseBank(root / "bank.json", root)
            docs = [root / name for name in ("garden.md", "railway.md", "empty.md")]
            bodies = {docs[0]: "Gardens and winter seeds grow beside a warm greenhouse. " * 40,
                      docs[1]: "Railway passengers travel across the valley on the morning train. " * 40,
                      docs[2]: ""}
            with (mock.patch.object(app, "_RESPONSES", bank),
                  mock.patch.object(app, "mind_id", return_value="selected"),
                  mock.patch.object(app, "speakbox_files", return_value=docs) as files,
                  mock.patch.object(app, "speakbox_body", side_effect=bodies.get),
                  mock.patch.object(app, "looks_english", return_value=True),
                  mock.patch.object(app, "speakbox_harvest", new=mock.AsyncMock()) as harvest,
                  mock.patch.object(app, "call_ollama", new=mock.AsyncMock()) as model):
                seeds = app.response_bank_sources()
            self.assertEqual({row["file"] for row in seeds}, {"garden.md", "railway.md"})
            self.assertTrue(all(row["mind"] == "selected" and len(row["text"]) <= 650 for row in seeds))
            self.assertTrue(all(row["text"] in bodies[root / row["file"]] for row in seeds))
            files.assert_called_once_with("selected")
            harvest.assert_not_awaited()
            model.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
