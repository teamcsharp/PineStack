"""Recover real-shaped bare shelf text in its retained voice, never on air."""
import asyncio
import copy
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import httpx
import app as station
from line_review import LineReviewStore


class ShelfReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviews.sqlite3"
        self.store = LineReviewStore(self.path)
        self.source = ("An original description of a blue doorway and the shadows across its wooden floor. " * 4).strip()
        self.candidate = "SPEAKER: " + ("The blue door stays in view; floor shadows gather in a darker hue. " * 4).strip()
        self.original = {"text": "Earlier active shelf wording.", "text_plain": self.source,
            "voice": "original-explicit-voice", "kind": "ad", "sid": "ad-original",
            "product": "Original painting", "cast": "original-cast", "at": 10,
            "key": "earlier-paid-take", "seconds": 12.5, "tint_ok": True,
            "tint": {"ok": True, "coverage": {"met": True, "version": 4}}}
        self.shelf = copy.deepcopy(self.original)
        self.render = mock.AsyncMock(return_value={"key": "new-complete-take", "seconds": 17.2})
        def parse(text, *_names):
            return [(m.group(1), m.group(2).strip()) for m in re.finditer(
                r"(?:^|\n)([A-E]):\s*(.*?)(?=\n[A-E]:|$)", text, re.S)]
        patches = {
            "_LINE_REVIEW": self.store, "_LARDER": [], "_SHELF": {"ad": [self.shelf]},
            "_TRACK_TALK": {}, "_LINE_REVIEW_REFRESH": [False], "_INVENTORY_PLAN": {}, "_COMMITS": {},
            "SPARK_AGENT_API_KEY": "shelf-test-key", "banter_turns": parse,
            "_larder_profile_signature": lambda: "test-profile", "alt_sid": lambda kind, row: row.get("sid", "test-row"),
            "_larder_save": mock.Mock(), "_pantry_save": mock.Mock(), "track_talk_save": mock.Mock(),
            "station_flow_event": mock.Mock(), "pipeline_log": mock.Mock(), "_tint_output_note": mock.Mock(),
            "segment_audit": mock.Mock(return_value={"checked": True, "ok": True}),
            "dialogue_tint_required": lambda: True, "engine_inflight": lambda: False,
            "crystal_force": lambda: 0.8, "crystal_coverage_target": lambda: 100,
            "prep_render_line": self.render, "tint_evaluate": mock.Mock(side_effect=self.grade),
            "ask_model": mock.AsyncMock(side_effect=AssertionError("No live model call in shelf recovery tests")),
            "larder_prepare": mock.AsyncMock(side_effect=AssertionError("Bare shelf text cannot use the larder recorder")),
        }
        for name, value in patches.items():
            patch = mock.patch.object(station, name, value)
            patch.start(); self.addCleanup(patch.stop)
        self.review = self.store.record("tint", self.source, self.candidate,
            reasons=["semantic preservation failed"], context={"kind": "ad", "stage": "whole_turn_rejected",
                "script_plain": self.source, "script": self.candidate, "turn": 1, "marker": "",
                "chunks": [{"text": "The retained original passage."}], "crystal": "Original world"})

    def grade(self, source, candidate, _chunks, **kwargs):
        verdict = station._LINE_REVIEW.evaluate("tint", source, candidate,
            ["semantic preservation failed"], context={"kind": kwargs.get("kind", "")})
        return {"ok": verdict["allowed"], "machine_ok": False,
                "faults": ["semantic preservation failed"], "operator_accepted": verdict["operator_approved"]}

    async def vote(self, action, review=None, note=""):
        review = review or self.review
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=station.app), base_url="http://test") as client:
            return await client.post("/api/orchestrator/rejections/" + review["id"],
                json={"action": action, "note": note}, headers={"Authorization": "Bearer shelf-test-key"})

    async def sweep_once(self):
        async def sleep(delay):
            if delay == 15:
                raise asyncio.CancelledError
        with mock.patch.object(station.asyncio, "sleep", side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await station.line_review_recovery_loop()

    async def test_bulk_once_records_exact_shelf_words_without_approving_future_repeats(self):
        batch = self.store.approve_current("shelf-once-batch")
        grant_id = batch["items"][0]["instance_id"]
        await self.sweep_once()
        self.render.assert_awaited_once()
        args = self.render.call_args
        self.assertIn(self.candidate, args.args)
        self.assertEqual(args.kwargs["voice"], self.original["voice"])
        self.assertEqual(self.store.get(grant_id)["effect"]["status"], "recorded")
        self.assertFalse(self.store.evaluate("tint", self.source, self.candidate,
            ["semantic preservation failed"], context={"kind": "ad"})["allowed"])
        await self.sweep_once()
        self.render.assert_awaited_once()

    async def test_allow_real_shaped_text_keeps_row_voice_sid_and_has_no_stale_take(self):
        response = await self.vote("allow")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["effect"]["status"], "queued_shelf")
        self.assertIs(station._SHELF["ad"][0], self.shelf)
        self.assertEqual(self.shelf["sid"], self.original["sid"])
        self.assertEqual(self.shelf["voice"], self.original["voice"])
        self.assertEqual(self.shelf["text"], self.candidate)
        self.assertEqual(self.shelf["text_plain"], self.source)
        self.assertEqual(self.shelf["who"], "")
        self.assertNotIn("key", self.shelf)
        self.assertNotIn("prepared", self.shelf)
        self.assertFalse(self.shelf["tint_ok"])
        self.assertEqual(station._LARDER, [])
        self.render.assert_not_awaited()
        same = copy.deepcopy(self.shelf)
        retry = await self.vote("allow")
        self.assertFalse(retry.json()["changed"])
        self.assertEqual(self.shelf, same)
        self.assertEqual(len(station._SHELF["ad"]), 1)

    async def test_recording_uses_full_candidate_and_original_voice_after_effective_regrade(self):
        await self.vote("allow")
        async def render(text, who, **kwargs):
            self.assertEqual(text, self.candidate)
            self.assertEqual(who, "")
            self.assertEqual(kwargs, {"voice": "original-explicit-voice", "kind": "ad"})
            self.assertFalse(self.shelf.get("prepared"))
            self.assertFalse(self.shelf.get("tint_ok"))
            self.assertNotIn("key", self.shelf)
            return {"key": "new-complete-take", "seconds": 17.2}
        self.render.side_effect = render
        self.assertTrue(await station.line_review_prepare_shelf("ad", self.shelf))
        self.render.assert_awaited_once()
        station.tint_evaluate.assert_called_once_with(self.source, self.candidate,
            [{"text": "The retained original passage."}], kind="ad")
        self.assertEqual(self.shelf["key"], "new-complete-take")
        self.assertTrue(self.shelf["tint_ok"])
        self.assertFalse(self.shelf["tint"]["evaluation"]["machine_ok"])
        self.assertTrue(self.shelf["tint"]["evaluation"]["operator_accepted"])
        self.assertEqual(self.store.get(self.review["id"])["effect"]["status"], "recorded")

    async def test_wrong_kind_or_ambiguous_source_does_not_infer_a_voice(self):
        station._SHELF = {"news": [self.shelf]}
        response = await self.vote("allow")
        self.assertEqual(response.json()["effect"]["status"], "needs_context")
        self.assertEqual(self.shelf, self.original)
        station._SHELF = {"ad": [self.shelf, copy.deepcopy(self.shelf)]}
        self.assertIsNone(station.line_review_matching(self.store.get(self.review["id"])))
        effect = station.line_review_recover(self.store.get(self.review["id"]))
        self.assertEqual(effect["status"], "needs_context")
        self.render.assert_not_awaited()

    async def test_keep_before_recording_restores_original_text_and_paid_audio(self):
        await self.vote("allow")
        response = await self.vote("keep")
        self.assertEqual(response.json()["effect"]["status"], "kept")
        for key in ("text", "text_plain", "key", "seconds", "voice", "tint", "tint_ok"):
            self.assertEqual(self.shelf[key], self.original[key])
        self.assertFalse(self.shelf.get("review_shelf_pending"))
        await self.sweep_once()
        self.render.assert_not_awaited()

    async def test_keep_during_render_discards_new_take_and_restores_prior_row(self):
        await self.vote("allow")
        async def render(*_args, **_kwargs):
            response = await self.vote("keep")
            self.assertEqual(response.json()["effect"]["status"], "kept")
            self.assertTrue(self.shelf.get("review_cancel_pending"))
            return {"key": "must-not-be-published", "seconds": 17.2}
        self.render.side_effect = render
        self.assertFalse(await station.line_review_prepare_shelf("ad", self.shelf))
        for key in ("text", "text_plain", "key", "seconds", "voice", "tint_ok"):
            self.assertEqual(self.shelf[key], self.original[key])
        self.assertFalse(self.shelf.get("review_cancel_pending"))
        self.assertFalse(self.shelf.get("review_shelf_pending"))
        self.assertEqual(self.store.get(self.review["id"])["effect"]["status"], "kept")

    async def test_technical_failure_cannot_be_approved_or_sent_to_tts(self):
        bad = self.store.record("recording_requirement", "A retained source", "",
            ["missing original voice"], context={"kind": "ad"}, technical=True)
        response = await self.vote("allow", bad)
        self.assertEqual(response.status_code, 400)
        self.render.assert_not_awaited()
        await self.vote("allow")
        for field in ("text", "text_plain", "voice"):
            with self.subTest(field=field):
                broken = copy.deepcopy(self.shelf); broken[field] = ""
                self.assertFalse(await station.line_review_prepare_shelf("ad", broken))
        self.render.assert_not_awaited()

    async def test_restart_restores_missing_shelf_from_durable_snapshot_once(self):
        await self.vote("allow")
        stored = self.store.get(self.review["id"])
        self.assertEqual(stored["effect"]["shelf_snapshot"]["voice"], self.original["voice"])
        station._SHELF.clear()
        station._LINE_REVIEW = LineReviewStore(self.path)
        self.render.return_value = None  # Keep accepted work pending for a later recorder visit.
        await self.sweep_once()
        self.assertEqual(len(station._SHELF["ad"]), 1)
        restored = station._SHELF["ad"][0]
        self.assertEqual(restored["text"], self.candidate)
        self.assertEqual(restored["voice"], self.original["voice"])
        self.assertEqual(restored["sid"], self.original["sid"])
        self.assertTrue(restored["review_shelf_pending"])
        await self.sweep_once()
        self.assertEqual(len(station._SHELF["ad"]), 1)

    async def test_tint_then_brief_approval_reuses_both_exact_decisions_and_original_source(self):
        def brief(kind, candidate, *, product=""):
            verdict = station._LINE_REVIEW.evaluate("segment_brief", candidate, "",
                ["product connection failed"], context={"kind": kind})
            return {"checked": True, "ok": verdict["allowed"], "machine_ok": False,
                    "why": "product connection failed", "operator_accepted": verdict["operator_approved"]}
        station.segment_audit.side_effect = brief
        await self.vote("allow")
        self.assertFalse(await station.line_review_prepare_shelf("ad", self.shelf))
        self.render.assert_not_awaited()
        pending = self.store.summaries(gate="segment_brief")["items"]
        self.assertEqual(len(pending), 1)
        review = self.store.get(pending[0]["id"])
        self.assertEqual(review["source"], self.candidate)
        self.assertEqual(review["candidate"], "")
        self.assertEqual(review["context"]["script_plain"], self.source)
        response = await self.vote("allow", review)
        self.assertEqual(response.json()["effect"]["status"], "queued_shelf", response.text)
        self.assertEqual(self.shelf["text"], self.candidate)
        self.assertEqual(self.shelf["text_plain"], self.source)
        self.assertTrue(await station.line_review_prepare_shelf("ad", self.shelf))
        self.render.assert_awaited_once_with(self.candidate, "", voice="original-explicit-voice", kind="ad")
        for grade_call in station.tint_evaluate.call_args_list:
            self.assertEqual(grade_call.args[:2], (self.source, self.candidate))
        self.assertFalse(self.shelf["tint"]["evaluation"]["machine_ok"])
        self.assertTrue(self.shelf["tint"]["evaluation"]["operator_accepted"])
        self.assertFalse(self.shelf["brief"]["machine_ok"])
        self.assertTrue(self.shelf["brief"]["operator_accepted"])
        for review_id in (self.review["id"], review["id"]):
            self.assertEqual(self.store.get(review_id)["effect"]["status"], "recorded")

    async def test_multiple_once_grants_keep_one_shelf_row_and_rollback_to_original_paid_take(self):
        retained = {**copy.deepcopy(self.original), "text": self.candidate}
        second = self.store.record("segment_brief", self.candidate, "",
            ["product connection failed"], context={"kind": "ad", "script": self.candidate,
                "script_plain": self.source, "entry": retained, "entry_id": retained["sid"]})
        batch = self.store.approve_current("shelf-multiple-grants-rollback")
        grants = {item["id"]: item["instance_id"] for item in batch["items"]}
        for review in (self.review, second):
            grant_id = grants[review["id"]]
            effect = station.line_review_recover(self.store.get(grant_id))
            self.store.track_effect(grant_id, effect)
            self.assertEqual(effect["status"], "queued_shelf")
        self.assertEqual(station._SHELF["ad"], [self.shelf])
        self.assertEqual(set(self.shelf["review_ids"]), set(grants.values()))
        self.assertEqual(self.shelf["text"], self.candidate)
        self.assertNotIn("key", self.shelf, "Original audio cannot advertise readiness for replacement words")
        self.assertEqual(self.shelf["review_shelf_before"]["text"], self.original["text"])
        self.assertEqual(self.shelf["review_shelf_before"]["key"], self.original["key"])

        response = await self.vote("keep", self.review)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(station._SHELF["ad"], [self.shelf])
        for key in ("text", "text_plain", "voice", "key", "seconds", "sid", "cast"):
            self.assertEqual(self.shelf[key], self.original[key], key)
        self.assertNotIn("review_shelf_pending", self.shelf)
        self.assertEqual(self.store.get(grants[self.review["id"]])["review_status"], "kept")
        await self.sweep_once()
        self.assertEqual(station._SHELF["ad"], [self.shelf])
        self.assertFalse(self.shelf.get("review_recovery_pending"), "A remaining grant cannot reclassify withdrawn bare shelf work as dialogue")
        self.assertNotEqual(self.store.get(grants[second["id"]])["effect"].get("status"), "queued")
        for key in ("text", "text_plain", "voice", "key", "seconds", "sid", "cast"):
            self.assertEqual(self.shelf[key], self.original[key], key)
        self.render.assert_not_awaited()
        station.ask_model.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
