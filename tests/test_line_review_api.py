"""Operator votes recover work, preserve audio contracts and never play it."""
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import httpx
import app as station
from line_review import LineReviewStore


class ReviewApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LineReviewStore(Path(self.temp.name) / "review.sqlite3")
        replacements = {
            "_LINE_REVIEW": self.store, "_LARDER": [], "_SHELF": {},
            "_TRACK_TALK": {}, "_INVENTORY_PLAN": {}, "_COMMITS": {},
            "_LINE_REVIEW_REFRESH": [False], "SPARK_AGENT_API_KEY": "review-test-key",
            "_larder_profile_signature": lambda: "test-profile",
            "_larder_save": mock.Mock(), "_pantry_save": mock.Mock(),
            "track_talk_save": mock.Mock(), "station_flow_event": mock.Mock(),
            "pipeline_log": mock.Mock(), "call_entry_regrade": mock.Mock(),
            "segment_audit": mock.Mock(return_value={"checked": False, "ok": True}),
            "engine_inflight": mock.Mock(return_value=False),
            "larder_prepare": mock.AsyncMock(), "prep_track_talk": mock.AsyncMock(return_value=False),
            "ask_model": mock.AsyncMock(side_effect=AssertionError("API tests must not call a live writer")),
            "alt_sid": lambda kind, row: "review-test-entry",
            "banter_turns": lambda script, *args: [tuple(line.split(": ", 1))
                                                    for line in script.strip().splitlines()],
        }
        for name, value in replacements.items():
            patch = mock.patch.object(station, name, value)
            patch.start(); self.addCleanup(patch.stop)
        self.script = "A: The red door creaks at night.\nB: The room is cold."
        self.row = self.store.record("tint", "The red door creaks at night.",
            "Red door squeaks; moonlit floor speaks.", ["meaning drift"],
            context={"kind": "banter", "script": self.script,
                     "marker": "A", "turn": 1, "chunks": ["Reference rhyme."]})

    async def request(self, method, path, body=None, authenticated=True):
        headers = {"Authorization": "Bearer review-test-key"} if authenticated else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=station.app),
                                     base_url="http://test") as client:
            return await client.request(method, path, json=body, headers=headers)

    async def sweep_once(self):
        async def sleep(delay):
            if delay == 15:
                raise asyncio.CancelledError
        with mock.patch.object(station.asyncio, "sleep", side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await station.line_review_recovery_loop()

    def track_review(self):
        return self.store.record("track_talk", "The road bends around the blue hill.", "",
            ["off topic"], context={"kind": "track_talk", "track": {"id": "review-track"},
                "part": "intro", "script": "The road bends around the blue hill.",
                "script_plain": "The road bends around the blue hill."})

    async def test_allow_recovers_original_order_and_retry_does_not_duplicate(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        body = {"action": "allow", "note": "The meaning works here.",
                "expected_revision": self.row["revision"]}
        result = await self.request("POST", endpoint, body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["effect"]["status"], "queued")
        self.assertEqual(len(station._LARDER), 1)
        entry = station._LARDER[0]
        self.assertEqual(entry["script_plain"], self.script)
        self.assertEqual(entry["tint_progress"]["turns"][0]["text"], self.row["candidate"])
        self.assertNotIn("prepared", entry)
        self.assertNotIn("keys", entry)
        again = await self.request("POST", endpoint, body)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertFalse(again.json()["changed"])
        self.assertEqual(len(station._LARDER), 1)

    async def test_note_endpoint_keeps_rejection_pending_and_checks_revision(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"] + "/note"
        body = {"note": "Try the host's original wording next time.",
                "expected_revision": self.row["revision"],
                "expected_event_seq": self.row["event_seq"]}
        denied = await self.request("POST", endpoint, body, authenticated=False)
        self.assertIn(denied.status_code, (401, 403))
        saved = await self.request("POST", endpoint, body)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["row"]["review_status"], "pending")
        detail = await self.request("GET", "/api/orchestrator/rejections/" + self.row["id"])
        self.assertEqual(detail.json()["operator_notes"][0]["note"], body["note"])
        self.assertEqual((await self.request("POST", endpoint, body)).status_code, 409)
        self.assertEqual((await self.request("POST", endpoint, {"note": " "})).status_code, 400)
        self.assertEqual(station._LARDER, [])

    async def test_review_detail_explains_profile_compatibility(self):
        stored = '{"reply":6500,"turns":[6,8],"plot":["older",1],"tint":[]}'
        current = '{"reply":6500,"turns":[12,16],"plot":["newer",2],"tint":[]}'
        row = self.store.record("call_contract", "A separate call", "A revised call",
            ["repeated premise"], context={"kind": "caller", "entry": {"profile": stored}})
        with mock.patch.object(station, "_larder_profile_signature", return_value=current):
            response = await self.request("GET", "/api/orchestrator/rejections/" + row["id"])
        self.assertEqual(response.status_code, 200, response.text)
        check = response.json()["profile_check"]
        self.assertTrue(check["compatible"])
        self.assertEqual(check["differences"], [])
        self.assertEqual(check["ignored_fields"], ["turns", "plot"])
        self.assertEqual(check["stored"]["reply"], 6500)

    async def test_bulk_snapshot_is_authenticated_idempotent_and_never_runs_rooms_in_request(self):
        endpoint = "/api/orchestrator/rejections/approve-current"
        body = {"request_id": "api-current-batch"}
        denied = await self.request("POST", endpoint, body, authenticated=False)
        self.assertIn(denied.status_code, (401, 403))
        for invalid in ({}, {"request_id": "short"}, {**body, "enabled": False}):
            response = await self.request("POST", endpoint, invalid)
            self.assertEqual(response.status_code, 400, response.text)
        technical = self.store.record("recording_requirement", "Missing audio.", reasons=["no audio"], technical=True)
        policy = self.store.policy()
        with mock.patch.object(station, "line_review_recover", side_effect=AssertionError("Recovery belongs to the worker")):
            result = await self.request("POST", endpoint, body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["approved"], 1)
        # #1088 (2026-09-08): a row the machine handled itself never reaches
        # the operator's queue at all, so the batch has nothing to skip - it
        # used to arrive pending and be skipped here for being technical.
        self.assertEqual(result.json()["skipped"], 0)
        self.assertEqual(result.json()["awaiting_recovery"], 1)
        self.assertEqual(self.store.get(technical["id"])["review_status"], "noted")
        late = self.store.record("tint", "A later source.", "A later candidate.", ["meaning"])
        retry = await self.request("POST", endpoint, body)
        self.assertEqual(result.json(), retry.json())
        self.assertEqual(self.store.get(late["id"])["review_status"], "pending")
        self.assertEqual(self.store.policy(), policy)
        self.assertFalse(station._LINE_REVIEW_REFRESH[0])
        self.assertEqual(station._LARDER, [])
        station.larder_prepare.assert_not_awaited()
        station.ask_model.assert_not_awaited()

    async def test_bulk_worker_recovers_once_after_restart_and_preserves_later_occurrence(self):
        result = self.store.approve_current("api-restart-batch")
        grant_id = result["items"][0]["instance_id"]
        later_context = {**self.row["context"], "script": "A: A new occurrence of the same words."}
        later = self.store.record(self.row["gate"], self.row["source"], self.row["candidate"],
                                 self.row["reasons"], later_context)
        reopened = LineReviewStore(self.store.path)
        with mock.patch.object(station, "_LINE_REVIEW", reopened):
            await self.sweep_once()
            self.assertEqual(len(station._LARDER), 1)
            entry = station._LARDER[0]
            self.assertEqual(entry["script_plain"], self.script)
            self.assertEqual(entry["review_ids"], [grant_id])
            self.assertEqual(reopened.get(later["id"])["review_status"], "pending")
            await self.sweep_once()
            self.assertEqual(len(station._LARDER), 1)
            self.assertEqual(reopened.get(grant_id)["effect"]["status"], "queued")

    async def test_bulk_keep_revokes_and_withdraws_unrecorded_grant(self):
        grant_id = self.store.approve_current("api-keep-batch")["items"][0]["instance_id"]
        await self.sweep_once()
        self.assertEqual(station._LARDER[0]["review_ids"], [grant_id])
        result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"], {"action": "keep"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.store.get(grant_id)["review_status"], "kept")
        self.assertEqual(station._LARDER, [])
        await self.sweep_once()
        self.assertEqual(station._LARDER, [])

    async def test_once_proof_cannot_escape_entry_scope_or_survive_revocation(self):
        grant_id = self.store.approve_current("api-proof-batch")["items"][0]["instance_id"]
        report = {"ok": True, "operator_accepted": True, "version": 4, "strength": 1}
        with mock.patch.object(station, "_TINT_OUTPUT_READY", {}), mock.patch.object(station, "crystal_force", return_value=1):
            with self.store.instance_scope([grant_id]):
                station._tint_output_note(self.row["candidate"], report)
                self.assertTrue(station.tint_output_ready(self.row["candidate"]))
            self.assertFalse(station.tint_output_ready(self.row["candidate"]))
            with self.store.instance_scope([grant_id]):
                self.store.decide(self.row["id"], "keep")
                self.assertFalse(station.tint_output_ready(self.row["candidate"]))

    async def test_once_scope_follows_decorated_async_entry_and_resets_on_failure(self):
        grant_id = self.store.approve_current("api-decorator-batch")["items"][0]["instance_id"]
        seen = []
        @station._with_review_instances
        async def prepare(row):
            await asyncio.sleep(0)
            seen.append(self.store.scoped_instances())
            raise RuntimeError("interrupted recording")
        with self.assertRaises(RuntimeError):
            await prepare({"entry": {"review_ids": [grant_id]}})
        self.assertEqual(seen, [(grant_id,)])
        self.assertEqual(self.store.scoped_instances(), ())

    async def test_one_time_recovery_does_not_attach_to_a_later_identical_round(self):
        grant_id = self.store.approve_current("api-match-batch")["items"][0]["instance_id"]
        snapshot = self.store.get(grant_id)
        future = {"script_plain": self.script, "script": self.script, "at": snapshot["last_at"] + 60}
        station._LARDER.append(future)
        self.assertIsNone(station.line_review_matching(snapshot))
        effect = station.line_review_recover(snapshot)
        self.assertEqual(effect["status"], "queued")
        self.assertNotIn("review_ids", future)
        self.assertEqual(len(station._LARDER), 2)

    async def test_allow_existing_round_invalidates_old_audio_references(self):
        entry = {"script_plain": self.script, "script": "A: Old cut version.",
                 "script_tinted": "A: Old cut version.", "use": "tinted",
                 "prepared": True, "keys": ["old-take"], "takes": [{"key": "old-take"}],
                 "tint": {"coverage": {"met": True}}, "profile": "test-profile"}
        station._LARDER.append(entry)
        result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"],
                                    {"action": "allow"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(station._LARDER), 1)
        self.assertIs(station._LARDER[0], entry)
        for key in ("prepared", "keys", "takes", "script_tinted", "tint"):
            self.assertNotIn(key, entry)
        self.assertEqual(entry["script"], self.script)

    async def test_active_round_is_deferred_without_mutation(self):
        entry = {"script_plain": self.script, "script": self.script, "preparing": True}
        station._LARDER.append(entry)
        before = copy.deepcopy(entry)
        result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"],
                                    {"action": "allow"})
        self.assertEqual(result.json()["effect"]["status"], "awaiting_recovery")
        self.assertEqual(entry, before)

    async def test_withdrawn_approval_cannot_survive_in_live_tint_cache(self):
        proofs = {"operator": {"ok": True, "operator_accepted": True},
                  "machine": {"ok": True, "machine_ok": True}}
        with mock.patch.object(station, "_TINT_OUTPUT_READY", proofs):
            result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"],
                                        {"action": "keep"})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("operator", proofs)
        self.assertIn("machine", proofs)

    async def test_keep_and_technical_reviews_do_not_queue_content(self):
        result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"],
                                    {"action": "keep", "note": "Meaning was lost."})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["row"]["review_status"], "kept")
        bad = self.store.record("recording_requirement", "Words.", reasons=["no audio"], technical=True)
        result = await self.request("POST", "/api/orchestrator/rejections/" + bad["id"], {"action": "allow"})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(station._LARDER, [])

    async def test_votes_and_policy_require_auth_and_validate_input(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        result = await self.request("POST", endpoint, {"action": "allow"}, authenticated=False)
        self.assertIn(result.status_code, (401, 403))
        result = await self.request("POST", endpoint, {"action": "unknown"})
        self.assertEqual(result.status_code, 400)
        result = await self.request("POST", "/api/orchestrator/rejection-policy", {"max_faults": 11})
        self.assertEqual(result.status_code, 400)
        result = await self.request("POST", "/api/orchestrator/rejection-policy", {"enabled": False})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(station.crystal_tint_holds())
        self.assertEqual(station._LARDER, [])

    async def test_stale_conflicting_decision_is_rejected(self):
        self.store.decide(self.row["id"], "keep", "correct")
        result = await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"],
                                    {"action": "allow", "expected_revision": self.row["revision"]})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(station._LARDER, [])

    async def test_read_and_regrade_do_not_make_new_cuts_or_start_work(self):
        before = self.store.summaries(status="all")["latest_cursor"]
        for _ in range(3):
            station._repeat_flow_verdict("Some repeated words.", "dj", "banter",
                                        {"block": True, "why": "said before"}, "exact")
            result = await self.request("GET", "/api/orchestrator/rejections/" + self.row["id"])
            self.assertEqual(result.status_code, 200)
        self.assertEqual(self.store.summaries(status="all")["latest_cursor"], before)
        self.assertEqual(station._LARDER, [])

    async def test_unchanged_but_explicitly_accepted_ad_uses_its_audited_tint_proof(self):
        words = "Try Acme's useful kettle today, for a warm drink every night."
        tinted = {"ok": True, "script": words,
                  "evaluation": {"ok": True, "machine_ok": False, "operator_accepted": True}}
        with (mock.patch.object(station, "speakbox_quote", new_callable=mock.AsyncMock, return_value={}),
              mock.patch.object(station, "ad_avoid_note", return_value=""),
              mock.patch.object(station, "dj_line", new_callable=mock.AsyncMock, return_value=words),
              mock.patch.object(station, "prep_air_text", side_effect=lambda text, *_: text),
              mock.patch.object(station, "dialogue_tint_wanted", return_value=True),
              mock.patch.object(station, "dialogue_tint_required", return_value=True),
              mock.patch.object(station, "crystal_tint", new_callable=mock.AsyncMock, return_value=tinted),
              mock.patch.object(station, "segment_audit", return_value={"checked": True, "ok": True}),
              mock.patch.object(station, "ad_repeat_check", return_value={"block": False})):
            result = await station.ad_write_fresh("Acme", tries=1)
        self.assertEqual(result["text"], words)
        self.assertTrue(result["tint_ok"])
        self.assertFalse(result["tint"]["evaluation"]["machine_ok"])

    async def test_recorded_effect_requires_the_reviewed_words(self):
        self.store.decide(self.row["id"], "allow")
        entry = {"review_ids": [self.row["id"]], "script": "A: Something different.", "made": 1}
        station.line_review_recorded(entry)
        self.assertEqual(self.store.get(self.row["id"])["effect"]["status"], "needs_context")
        entry["script"] = "A: " + self.row["candidate"]
        station.line_review_recorded(entry)
        self.assertEqual(self.store.get(self.row["id"])["effect"]["status"], "recorded")

    async def test_keep_withdraws_new_unrecorded_round_and_durable_pending_state(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        await self.request("POST", endpoint, {"action": "allow"})
        self.assertTrue(station._LARDER[0]["review_recovery_pending"])
        result = await self.request("POST", endpoint, {"action": "keep"})
        self.assertEqual(result.json()["effect"]["status"], "kept")
        self.assertEqual(station._LARDER, [])
        await self.sweep_once()
        station.larder_prepare.assert_not_awaited()
        self.assertEqual(LineReviewStore(self.store.path).get(self.row["id"])["effect"]["status"], "kept")

    async def test_keep_existing_unrecorded_round_clears_recovery_without_deleting_original(self):
        entry = {"script": self.script, "script_plain": self.script, "prep_kind": "banter"}
        station._LARDER.append(entry)
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        await self.request("POST", endpoint, {"action": "allow"})
        await self.request("POST", endpoint, {"action": "keep"})
        self.assertEqual(station._LARDER, [entry])
        self.assertNotIn(self.row["id"], entry.get("review_ids", []))
        self.assertFalse(entry.get("review_recovery_pending"))
        await self.sweep_once()
        station.larder_prepare.assert_not_awaited()

    async def test_keep_during_active_recovery_is_applied_before_completed_audio_can_queue(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        await self.request("POST", endpoint, {"action": "allow"})
        entry = station._LARDER[0]
        entry["preparing"] = True
        await self.request("POST", endpoint, {"action": "keep"})
        self.assertTrue(entry.get("review_cancel_pending"))
        entry.pop("preparing")
        entry.update(prepared=True, keys=["take-completed-after-withdrawal"])
        await self.sweep_once()
        self.assertTrue(entry not in station._LARDER or not entry.get("prepared"))
        self.assertEqual(self.store.get(self.row["id"])["effect"]["status"], "kept")

    async def test_matching_does_not_attach_same_words_to_a_different_road_or_caller(self):
        wrong_road = {"script_plain": self.script, "script": self.script}
        station._SHELF["news"] = [{"entry": wrong_road}]
        self.assertIsNone(station.line_review_matching(self.row))
        station._SHELF.clear()
        source = "A: Welcome.\nC: My blue bicycle.\nB: Thank you."
        row = self.store.record("tint", "My blue bicycle.", "Blue wheels make bright deals.",
            ["rhyme"], context={"kind": "caller", "script_plain": source, "marker": "C", "turn": 2,
                "entry": {"caller_name": "Mara", "caller_voice": "mara-voice"}})
        wrong_caller = {"script_plain": source, "caller_name": "Jo", "caller_voice": "jo-voice"}
        station._SHELF["caller"] = [{"entry": wrong_caller}]
        self.assertIsNone(station.line_review_matching(row))
        wrong_caller["caller_name"] = "Mara"
        self.assertIsNone(station.line_review_matching(row))
        wrong_caller.update(caller_name="Mara", caller_voice="mara-voice")
        self.assertIs(station.line_review_matching(row)[2], wrong_caller)
        station._SHELF["caller"].append({"entry": copy.deepcopy(wrong_caller)})
        self.assertIsNone(station.line_review_matching(row), "Identical retained rounds need an entry ID")

    async def test_same_approval_new_note_does_not_duplicate_or_reset_prepared_receipts(self):
        endpoint = "/api/orchestrator/rejections/" + self.row["id"]
        await self.request("POST", endpoint, {"action": "allow", "note": "First reason"})
        entry = station._LARDER[0]
        await self.request("POST", endpoint, {"action": "allow", "note": "Clearer reason"})
        self.assertEqual(station._LARDER, [entry])
        entry.update(script="A: " + self.row["candidate"], prepared=True, keys=["finished-take"], made=1)
        station.line_review_recorded(entry)
        before = copy.deepcopy(entry)
        result = await self.request("POST", endpoint, {"action": "allow", "note": "Final explanation"})
        self.assertTrue(result.json()["changed"])
        self.assertEqual(result.json()["effect"]["status"], "recorded")
        self.assertEqual(entry, before)
        self.assertEqual(station._LARDER, [entry])

    async def test_queued_missing_entry_is_rebuilt_once_after_store_restart(self):
        await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"], {"action": "allow"})
        station._LARDER.clear()
        station._LINE_REVIEW = LineReviewStore(self.store.path)
        await self.sweep_once()
        self.assertEqual(len(station._LARDER), 1)
        self.assertEqual(station._LARDER[0]["script_plain"], self.script)
        self.assertTrue(station._LARDER[0]["review_recovery_pending"])
        await self.sweep_once()
        self.assertEqual(len(station._LARDER), 1)

    async def test_queued_retained_entry_recovers_missing_pending_flag_after_restart(self):
        await self.request("POST", "/api/orchestrator/rejections/" + self.row["id"], {"action": "allow"})
        entry = station._LARDER[0]
        entry.pop("review_recovery_pending")
        await self.sweep_once()
        self.assertEqual(station._LARDER, [entry])
        self.assertTrue(entry.get("review_recovery_pending"))
        station.larder_prepare.assert_awaited_once_with(entry)

    async def test_keep_withdraws_track_side_without_changing_another_track_or_side(self):
        row = self.track_review()
        endpoint = "/api/orchestrator/rejections/" + row["id"]
        result = await self.request("POST", endpoint, {"action": "allow"})
        self.assertEqual(result.json()["effect"]["status"], "queued_track")
        other_side = {"text": "A separately accepted outro", "key": "retain-outro"}
        station._TRACK_TALK["review-track"]["outro"] = other_side
        station._TRACK_TALK["other-track"] = {"intro": {"text": "Keep this track", "key": "keep"}}
        before_other = copy.deepcopy(station._TRACK_TALK["other-track"])
        result = await self.request("POST", endpoint, {"action": "keep"})
        self.assertEqual(result.json()["effect"]["status"], "kept")
        self.assertFalse(station._TRACK_TALK["review-track"].get("intro"))
        self.assertEqual(station._TRACK_TALK["review-track"]["outro"], other_side)
        self.assertEqual(station._TRACK_TALK["other-track"], before_other)

    async def test_queued_track_missing_side_is_recovered_after_restart(self):
        row = self.track_review()
        await self.request("POST", "/api/orchestrator/rejections/" + row["id"], {"action": "allow"})
        station._TRACK_TALK.clear()
        station._LINE_REVIEW = LineReviewStore(self.store.path)
        await self.sweep_once()
        self.assertEqual(station._TRACK_TALK["review-track"]["intro"]["text"], row["source"])
        self.assertEqual(station._LINE_REVIEW.get(row["id"])["effect"]["status"], "queued_track")

    async def test_active_track_recovery_kept_before_recording_finishes_is_withdrawn(self):
        row = self.track_review()
        endpoint = "/api/orchestrator/rejections/" + row["id"]
        await self.request("POST", endpoint, {"action": "allow"})
        track = station._TRACK_TALK["review-track"]
        side = track["intro"]
        side["preparing"] = True
        await self.request("POST", endpoint, {"action": "keep"})
        self.assertTrue(side.get("review_cancel_pending"))
        side.pop("preparing")
        side.update(key="newly-completed-track-take", duration=2.1, tint_ok=True)
        await self.sweep_once()
        self.assertTrue(not track.get("intro") or not track["intro"].get("key"))
        self.assertEqual(self.store.get(row["id"])["effect"]["status"], "kept")

    async def test_pending_withdrawal_is_not_ready_during_the_interval_before_worker_sweep(self):
        entry = {"script": self.script, "prepared": True, "review_cancel_pending": True}
        with mock.patch.object(station, "_larder_current", return_value=True), \
                mock.patch.object(station, "dialogue_tint_ready", return_value=True), \
                mock.patch.object(station, "dialogue_audio_ready", return_value=True):
            self.assertFalse(station.dialogue_row_ready("banter", entry))
        side = {"text": "A recorded track intro.", "key": "paid-take", "tint_ok": True,
                "review_cancel_pending": True}
        with mock.patch.object(station, "_pantry_key_ready", return_value=True):
            self.assertFalse(station.track_talk_part_ready(side))

    async def test_raw_shelf_tint_capture_retains_voice_evidence_without_inventing_speaker(self):
        for who in (None, "cohost"):
            with self.subTest(who=who):
                row = {"text_plain": "A retained shelf source.", "text": "An earlier draft.",
                       "voice": "original-explicit-voice", "sid": "ad-original",
                       "kind": "ad", "product": "Original product"}
                if who:
                    row["who"] = who
                captured = []
                async def tint(*_args, **_kwargs):
                    captured.append(station.line_review_capture("tint", row["text_plain"], "Reviewed rewrite.",
                        reasons=["meaning"], context={"kind": "ad", "stage": "whole_turn_rejected"}))
                    return {"ok": False}
                with mock.patch.object(station, "legacy_tint_revalidate", new=mock.AsyncMock()), \
                        mock.patch.object(station, "dialogue_tint_required", return_value=True), \
                        mock.patch.object(station, "crystal_tint", side_effect=tint):
                    self.assertFalse(await station.ensure_shelf_row_tinted("ad", row))
                context = captured[0]["context"]
                self.assertEqual(context["entry_id"], "ad-original")
                self.assertEqual(context["entry"]["voice"], "original-explicit-voice")
                self.assertEqual(context["script_plain"], "A retained shelf source.")
                if who:
                    self.assertEqual(context["speaker"], who)
                else:
                    self.assertNotIn("speaker", context)
                row["voice"] = "later-voice"
                self.assertEqual(context["entry"]["voice"], "original-explicit-voice")
                self.assertEqual(station._LINE_REVIEW_CONTEXT.get(), {})

    async def test_same_batch_missing_programme_merges_both_cut_candidates_and_grants(self):
        second = self.store.record("tint", "The room is cold.", "The cold room holds a silver gloom.",
            ["meaning drift"], context={"kind": "banter", "script": self.script, "marker": "B", "turn": 2})
        batch = self.store.approve_current("same-missing-programme")
        grants = {item["id"]: item["instance_id"] for item in batch["items"]}
        await self.sweep_once()
        self.assertEqual(len(station._LARDER), 1)
        entry = station._LARDER[0]
        self.assertEqual(set(entry["review_ids"]), {grants[self.row["id"]], grants[second["id"]]})
        self.assertEqual([row["text"] for row in entry["tint_progress"]["turns"]],
                         [self.row["candidate"], second["candidate"]])
        await self.sweep_once()
        self.assertEqual(station._LARDER, [entry])

    async def test_same_batch_missing_programme_preserves_shared_retained_sid_and_birth(self):
        retained = {"sid": "original-retained-position", "at": 12345, "script_plain": self.script}
        context = {**self.row["context"], "entry_id": retained["sid"], "entry": retained}
        first = self.store.record(self.row["gate"], self.row["source"], self.row["candidate"],
                                  self.row["reasons"], context=context)
        second = self.store.record("tint", "The room is cold.", "The cold room holds a silver gloom.",
            ["meaning drift"], context={**context, "marker": "B", "turn": 2})
        batch = self.store.approve_current("same-identified-missing-programme")
        grants = {item["id"]: item["instance_id"] for item in batch["items"]}
        await self.sweep_once()
        self.assertEqual(len(station._LARDER), 1)
        entry = station._LARDER[0]
        self.assertEqual(set(entry["review_ids"]), {grants[first["id"]], grants[second["id"]]})
        self.assertEqual([row["text"] for row in entry["tint_progress"]["turns"]],
                         [first["candidate"], second["candidate"]])
        # A new row with the same script never inherits the recovered origin.
        later = {"script_plain": self.script, "script": self.script,
                 "sid": retained["sid"], "at": self.store.get(grants[first["id"]])["last_at"] + 60}
        station._LARDER[:] = [later]
        self.assertIsNone(station.line_review_matching(self.store.get(grants[second["id"]])))

    async def test_same_batch_origin_does_not_join_distinct_retained_identity(self):
        batch = self.store.approve_current("same-script-separate-origin")
        first = self.store.get(batch["items"][0]["instance_id"])
        effect = station.line_review_recover(first)
        self.assertEqual(effect["status"], "queued")
        entry = station._LARDER[0]
        sibling = copy.deepcopy(first)
        sibling["id"] = "different-cut"
        self.assertTrue(station._line_review_batch_origin(sibling, entry))
        for change in ({"kind": "gallery"}, {"script": "A: A different programme."},
                       {"caller_name": "Another caller"}, {"caller_voice": "different-voice"}):
            with self.subTest(change=change):
                changed = copy.deepcopy(sibling)
                changed["context"].update(change)
                self.assertFalse(station._line_review_batch_origin(changed, entry))
        # When captures retain identity, matching text cannot erase it.
        first["context"]["entry"] = {"sid": "original-position", "at": 100, "voice": "original-voice"}
        with mock.patch.object(self.store, "get", return_value=first):
            for change in ({"sid": "another-position"}, {"at": 200}, {"voice": "another-voice"}):
                changed = copy.deepcopy(sibling)
                changed["context"]["entry"] = {**first["context"]["entry"], **change}
                self.assertFalse(station._line_review_batch_origin(changed, entry))

    async def test_same_track_part_accumulates_compatible_grants_and_retains_conflicting_copy(self):
        first = self.track_review()
        second = self.store.record("track_talk_fidelity", first["source"], first["source"],
            ["fidelity flag"], context=first["context"])
        conflict_context = {**first["context"], "script": "A different link for that track."}
        conflict = self.store.record("track_talk", conflict_context["script"], "",
            ["topic flag"], context=conflict_context)
        batch = self.store.approve_current("same-track-part-grants")
        ids = {item["id"]: item["instance_id"] for item in batch["items"]}
        for row in (first, second):
            effect = station.line_review_recover(self.store.get(ids[row["id"]]))
            self.assertEqual(effect["status"], "queued_track")
        side = station._TRACK_TALK["review-track"]["intro"]
        self.assertEqual(set(side["review_ids"]), {ids[first["id"]], ids[second["id"]]})
        before = copy.deepcopy(side)
        effect = station.line_review_recover(self.store.get(ids[conflict["id"]]))
        self.assertEqual(effect["status"], "needs_context")
        self.assertEqual(station._TRACK_TALK["review-track"]["intro"], before)

    async def test_real_track_preparer_keep_during_render_cannot_republish_detached_take(self):
        review = self.track_review()
        batch = self.store.approve_current("track-real-render-withdrawal")
        grant_id = next(item["instance_id"] for item in batch["items"] if item["id"] == review["id"])
        station.line_review_recover(self.store.get(grant_id))
        track = {"id": "review-track", "title": "Bounded test record"}
        seen = {}
        async def render(*_args, **_kwargs):
            side = station._TRACK_TALK[track["id"]]["intro"]
            seen["side"] = side
            seen["owned_during_render"] = bool(side.get("preparing"))
            seen["scope_during_render"] = self.store.scoped_instances()
            result = await self.request("POST", "/api/orchestrator/rejections/" + review["id"], {"action": "keep"})
            seen["keep_status"] = result.status_code
            return {"key": "late-mocked-take", "seconds": 2.4}
        with (mock.patch.object(station, "track_talk_on", return_value=True),
              mock.patch.object(station, "track_lookahead", return_value=[track]),
              mock.patch.object(station, "track_talk_get", side_effect=lambda item, part: station._TRACK_TALK[item["id"]].get(part)),
              mock.patch.object(station, "track_talk_track_snapshot", side_effect=copy.deepcopy),
              mock.patch.object(station, "track_talk_part_ready", side_effect=lambda side: bool(side and side.get("key"))),
              mock.patch.object(station, "dialogue_tint_wanted", return_value=False),
              mock.patch.object(station, "track_talk_text_report", return_value={"ok": True}),
              mock.patch.object(station, "session_voices", new=mock.AsyncMock(return_value={"dj": "test-voice"})),
              mock.patch.object(station, "prep_render_line", side_effect=render),
              mock.patch.object(station, "_track_talk_prune", return_value=None)):
            self.assertFalse(await _production_prep_track_talk())
        self.assertTrue(seen["owned_during_render"])
        self.assertEqual(seen["keep_status"], 200)
        self.assertIn(grant_id, seen["scope_during_render"])
        self.assertFalse(seen["side"].get("preparing"))
        self.assertFalse(station._TRACK_TALK[track["id"]].get("intro"))
        self.assertEqual(self.store.get(grant_id)["review_status"], "kept")
        self.assertEqual(self.store.scoped_instances(), ())

    async def test_real_track_preparer_cancellation_releases_owner_and_instance_scope(self):
        review = self.track_review()
        batch = self.store.approve_current("track-render-cancel-cleanup")
        grant_id = next(item["instance_id"] for item in batch["items"] if item["id"] == review["id"])
        station.line_review_recover(self.store.get(grant_id))
        track = {"id": "review-track"}
        with (mock.patch.object(station, "track_talk_on", return_value=True),
              mock.patch.object(station, "track_lookahead", return_value=[track]),
              mock.patch.object(station, "track_talk_get", side_effect=lambda item, part: station._TRACK_TALK[item["id"]].get(part)),
              mock.patch.object(station, "track_talk_track_snapshot", side_effect=copy.deepcopy),
              mock.patch.object(station, "track_talk_part_ready", return_value=False),
              mock.patch.object(station, "dialogue_tint_wanted", return_value=False),
              mock.patch.object(station, "track_talk_text_report", return_value={"ok": True}),
              mock.patch.object(station, "session_voices", new=mock.AsyncMock(return_value={"dj": "test-voice"})),
              mock.patch.object(station, "prep_render_line", side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await _production_prep_track_talk()
        side = station._TRACK_TALK[track["id"]]["intro"]
        self.assertNotIn("key", side)
        self.assertFalse(side.get("preparing"))
        self.assertEqual(side["review_ids"], [grant_id])
        self.assertEqual(self.store.scoped_instances(), ())


    async def test_track_restart_releases_stale_owner_and_regrades_only_with_its_persisted_grant(self):
        import json
        review = self.track_review()
        batch = self.store.approve_current("track-startup-scoped-grant")
        grant_id = next(item["instance_id"] for item in batch["items"] if item["id"] == review["id"])
        now = station.time.time()
        side = {"text": review["source"], "text_plain": review["source"], "tint_ok": True,
                "review_ids": [grant_id], "preparing": True}
        rows = {
            "review-track": {"id": "review-track", "at": now, "intro": side,
                "outro": {**copy.deepcopy(side), "review_cancel_pending": True}},
            "unrelated-track": {"id": "unrelated-track", "at": now,
                "intro": {"text": review["source"], "preparing": True}},
            "technical-track": {"id": "technical-track", "at": now, "intro": copy.deepcopy(side)},
        }
        path = Path(self.temp.name) / "track-startup.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        reopened = LineReviewStore(self.store.path)
        observed = []
        def report(text, track, part):
            grade = reopened.evaluate("track_talk", text, "", ["off topic"], {"kind": "track_talk"},
                                      technical=track["id"] == "technical-track")
            observed.append((track["id"], part, grade["allowed"], reopened.scoped_instances()))
            return {"ok": grade["allowed"], "machine_ok": False}
        with (mock.patch.object(station, "TRACK_TALK_PATH", path),
              mock.patch.object(station, "_TRACK_TALK_LOADED", [False]),
              mock.patch.object(station, "_LINE_REVIEW", reopened),
              mock.patch.object(station, "track_talk_text_report", side_effect=report),
              mock.patch.object(station, "track_talk_tint_govern", side_effect=lambda text, track, part, plain: (text, report(text, track, part)))):
            station.track_talk_load()
        self.assertEqual(set(station._TRACK_TALK), {"review-track"})
        restored = station._TRACK_TALK["review-track"]
        self.assertEqual(restored["intro"]["text"], review["source"])
        self.assertFalse(restored["intro"].get("preparing"))
        self.assertFalse(restored["intro"]["off_brief"])
        self.assertFalse(restored["outro"].get("preparing"))
        self.assertTrue(restored["outro"]["review_cancel_pending"])
        self.assertIn(("review-track", "intro", True, (grant_id,)), observed)
        self.assertIn(("unrelated-track", "intro", False, ()), observed)
        self.assertTrue(all(not allowed for track, _, allowed, _ in observed if track == "technical-track"))
        self.assertTrue(all(part != "outro" for _, part, _, _ in observed), "Pending withdrawal is left for the recovery worker")
        self.assertEqual(reopened.scoped_instances(), ())
        station.track_talk_save.assert_called_with(True)


# Retain the production coroutine before fixtures replace its public binding.
_production_prep_track_talk = station.prep_track_talk


if __name__ == "__main__":
    unittest.main()
