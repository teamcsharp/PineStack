import asyncio
import copy
import hashlib
import unittest
from contextlib import ExitStack
from unittest import mock

import app
from tint_recovery import evaluate_legacy


class LegacyTintRecoveryTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {
            "dialogue_tint_required": True, "crystal_coverage_target": 100,
            "crystal_force": 1.0, "_larder_current": True,
            "_larder_profile_signature": "current", "_pantry_key_ready": True,
            "brief_note": {"checked": False}, "tint_should_stop": "",
            "committed_stock_ids": set(), "pantry_window": "",
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, return_value=value))
        for name in ("_pantry_save", "_larder_save", "station_flow_event", "pipeline_log"):
            self.stack.enter_context(mock.patch.object(app, name))
        self.stack.enter_context(mock.patch.object(app, "_TINT_RECOVERY_STATE",
            {"running": False, "checked": 0, "last_at": 0.0, "why": ""}))
        self.stack.enter_context(mock.patch.object(app, "_RADIO", {"on": True}))

    def entry(self):
        return {"script_plain": "A: " + self.SOURCE,
                "script_tinted": "A: " + self.TINTED,
                "script": "A: " + self.TINTED, "use": "tinted",
                "prep_kind": "banter", "profile": "current",
                "tint": {"ok": True, "chunks": copy.deepcopy(self.CHUNKS)},
                "keys": ["real-take"], "takes": [{"i": 0, "key": "real-take"}],
                "made": 1, "chunks": 1, "prepared": True, "seconds": 8.0}

    async def test_valid_legacy_evidence_restores_ready_without_rewriting_or_dropping_audio(self):
        entry = self.entry()
        takes = copy.deepcopy(entry["takes"])
        self.assertFalse(app.dialogue_row_ready("banter", entry))
        with mock.patch.object(app, "crystal_tint", new_callable=mock.AsyncMock) as rewrite:
            self.assertTrue(await app.ensure_entry_tinted(entry, "banter"))
            rewrite.assert_not_awaited()
        self.assertTrue(app.dialogue_row_ready("banter", entry))
        self.assertEqual(entry["takes"], takes)
        self.assertEqual(entry["seconds"], 8.0)
        self.assertEqual(entry["tint"]["coverage"]["changed"], 1)
        self.assertEqual(len(entry["tint"]["approved_lines"]), 1)

    async def test_valid_rewrite_cannot_replace_a_missing_audio_file(self):
        entry = self.entry()
        await app.legacy_tint_revalidate("banter", entry)
        with mock.patch.object(app, "_pantry_key_ready", return_value=False):
            self.assertFalse(app.dialogue_row_ready("banter", entry))

    async def test_old_ok_stamp_with_unchanged_words_remains_owed_and_keeps_takes(self):
        entry = self.entry()
        entry["script_tinted"] = entry["script"] = entry["script_plain"]
        self.assertFalse(await app.legacy_tint_revalidate("banter", entry))
        self.assertFalse(app.dialogue_tint_ready("banter", entry))
        self.assertEqual(entry["tint_revalidation"]["state"], "repair_required")
        self.assertEqual(entry["keys"], ["real-take"])
        self.assertEqual(len(entry["tint_progress"]["turns"]), 1)

    async def test_missing_source_passages_or_original_cannot_be_grandfathered(self):
        for missing in ("chunks", "script_plain"):
            entry = self.entry()
            if missing == "chunks":
                entry["tint"].pop("chunks")
            else:
                entry.pop("script_plain")
            self.assertFalse(await app.legacy_tint_revalidate("banter", entry))
            self.assertFalse(entry.get("tint_progress"))
            self.assertIn("missing", entry["tint_revalidation"]["why"])
            self.assertEqual(entry["seconds"], 8.0)

    async def test_failed_new_proof_is_not_certified_against_different_passages(self):
        entry = self.entry()
        entry["tint"]["coverage"] = {"version": 2, "met": False}
        self.assertFalse(await app.legacy_tint_revalidate("banter", entry))
        self.assertFalse(entry.get("tint_progress"))

    async def test_plain_active_version_is_not_marked_ready_by_a_valid_alternative(self):
        entry = self.entry()
        entry["script"], entry["use"] = entry["script_plain"], "plain"
        self.assertFalse(await app.legacy_tint_revalidate("banter", entry))
        self.assertFalse(app.dialogue_row_ready("banter", entry))

    async def test_operator_edit_during_evaluation_cannot_receive_old_proof(self):
        entry = self.entry()
        real_thread = asyncio.to_thread

        async def edit_then_evaluate(fn, *args, **kwargs):
            result = await real_thread(fn, *args, **kwargs)
            entry["script_tinted"] = entry["script"] = "A: Different ungraded words."
            return result

        with mock.patch.object(app.asyncio, "to_thread", side_effect=edit_then_evaluate):
            self.assertFalse(await app.legacy_tint_revalidate("banter", entry))
        self.assertNotIn("coverage", entry["tint"])
        self.assertNotIn("tint_revalidation", entry)
        self.assertNotIn("tinting", entry)

    def test_good_later_candidate_keeps_original_position_when_an_earlier_line_fails(self):
        result = evaluate_legacy("A: " + self.SOURCE + "\nB: " + self.SOURCE,
            "A: " + self.SOURCE + "\nB: " + self.TINTED, self.CHUNKS,
            app.banter_turns, app.tint_evaluate, target=100, force=1.0, kind="banter")
        self.assertEqual(result["state"], "repair_required")
        self.assertEqual(result["reusable_lines"], 1)
        self.assertEqual([t["marker"] for t in result["progress"]["turns"]], ["A", "B"])
        self.assertEqual(result["progress"]["turns"][1]["text"], self.TINTED)
        self.assertFalse(result["approved_lines"])

    def test_changed_turn_count_is_not_accepted(self):
        result = evaluate_legacy("A: " + self.SOURCE,
            "A: " + self.TINTED + "\nB: extra turn", self.CHUNKS,
            app.banter_turns, app.tint_evaluate, target=100, force=1.0, kind="banter")
        self.assertIn("turn count", result["why"])
        self.assertFalse(result["progress"])

    def test_restart_clears_stranded_tint_owner_without_removing_audio(self):
        entry = self.entry()
        entry["tinting"] = True
        app._unstrand(entry)
        self.assertNotIn("tinting", entry)
        self.assertEqual(entry["keys"], ["real-take"])

    async def test_repair_queue_retries_unknown_rows_with_cooldown_and_visible_progress(self):
        entry = self.entry()
        entry["tint"].pop("chunks")
        await app.legacy_tint_revalidate("banter", entry)
        with (mock.patch.object(app, "_LARDER", [entry]),
              mock.patch.object(app, "_SHELF", {}),
              mock.patch.object(app, "dialogue_row_viable", return_value=True),
              mock.patch.object(app, "ensure_shelf_row_tinted", return_value=False) as repair):
            self.assertFalse(await app.tint_recovery_step())
            repair.assert_awaited_once_with("banter", entry, critical=True)
            self.assertEqual(entry["tint_revalidation"]["attempts"], 1)
            self.assertFalse(await app.tint_recovery_step())
            self.assertEqual(repair.await_count, 1)
            status = app.tint_recovery_status()
            self.assertEqual(status["pending"][0]["attempts"], 1)
            self.assertTrue(status["pending"][0]["audio_preserved"])
            self.assertEqual(status["states"], {"repair_required": 1})

    async def test_deferred_writer_keeps_accepted_script_takes_and_prior_tint_evidence(self):
        entry = self.entry()
        entry["tint_revalidation"] = {"state": "repair_required"}
        prior = copy.deepcopy(entry["tint"])

        async def deferred(*args, **kwargs):
            app._WRITING_DEFERRED.set(app._WRITING_DEFERRED.get() + 1)
            return {"ok": False, "why": "no model slot", "progress": {"turns": [{"text": "saved candidate"}]}}

        with mock.patch.object(app, "crystal_tint", side_effect=deferred):
            self.assertFalse(await app.ensure_entry_tinted(entry, "banter"))
        self.assertEqual(entry["tint"], prior)
        self.assertEqual(entry["keys"], ["real-take"])
        self.assertEqual(entry["script"], "A: " + self.TINTED)
        self.assertEqual(entry["tint_revalidation"]["state"], "waiting")
        self.assertNotIn("tint_tried", entry)
        self.assertEqual(entry["tint_progress"]["turns"][0]["text"], "saved candidate")

    async def test_failed_resume_preserves_good_unvisited_tail_candidates(self):
        source = "A: " + self.SOURCE + "\nB: " + self.SOURCE
        progress = evaluate_legacy(source, "A: " + self.SOURCE + "\nB: " + self.TINTED,
            self.CHUNKS, app.banter_turns, app.tint_evaluate,
            target=100, force=1.0, kind="banter")["progress"]
        with ExitStack() as stack:
            for name, value in {"crystal_active": [{"name": "test"}],
                "crystal_world_prompt": "test", "task_cost": .1}.items():
                stack.enter_context(mock.patch.object(app, name, return_value=value))
            for name in ("task_note", "_tint_flow", "tint_spend_note", "trail_note", "chunk_answer"):
                stack.enter_context(mock.patch.object(app, name))
            stack.enter_context(mock.patch.object(app, "crystal_turn", return_value=""))
            got = await app.crystal_tint(source, "banter", progress=progress, critical=True)
        self.assertFalse(got["ok"])
        self.assertEqual(len(got["progress"]["turns"]), 2)
        self.assertEqual(got["progress"]["turns"][1]["text"], self.TINTED)


if __name__ == "__main__":
    unittest.main()
