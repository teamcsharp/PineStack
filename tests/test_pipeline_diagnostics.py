"""The coordinator reports actual stage debt without treating pause as failure."""
import copy
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app


class PipelineDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.patch("_LARDER", [])
        self.patch("_SHELF", {})
        self.patch("dialogue_tint_required", mock.Mock(return_value=True))
        self.patch("crystal_coverage_target", mock.Mock(return_value=100))
        self.patch("crystal_force", mock.Mock(return_value=.88))
        self.patch("_larder_current", lambda row: row.get("profile") != "old")
        self.patch("_pantry_key_ready", lambda key: key == "present")
        self.patch("writing_room_state", mock.Mock(return_value={"active": 1, "waiting": 1}))
        self.patch("recording_booths", mock.Mock(return_value={"preparing": 0}))
        self.patch("call_entry_contract", mock.Mock(return_value=True))
        self.patch("require_read_auth", mock.Mock())
        self.proof = {"coverage": {"met": True, "target": 100, "version": 4, "strength": .88}}

    def patch(self, name, value):
        return self.stack.enter_context(mock.patch.object(app, name, value))

    def raw(self, **changes):
        return {"text": "The complete recorded words.", "key": "present",
                "tint_ok": True, "tint": copy.deepcopy(self.proof), **changes}

    def test_stored_flags_do_not_award_readiness_or_hide_real_ready_audio(self):
        app._SHELF["ad"] = [self.raw(prepared=False), self.raw(prepared=True, key="missing"),
                            self.raw(prepared=True, tint_ok=False)]
        got = app.orchestrator_pipeline_state()
        self.assertEqual(got["total"], 3)
        self.assertEqual(got["stages"]["ready"], 1)
        self.assertEqual(got["recording_waiting"], 1)
        self.assertEqual(got["tint_waiting"], 1)
        self.assertIn("no preparation render", got["bottleneck"])

    def test_stage_counts_are_exclusive_and_shared_entries_are_not_counted_twice(self):
        entry = {"script": "A: A complete original line.", "prepared": True,
                 "profile": "old"}
        app._LARDER.append(entry)
        app._SHELF["banter"] = [{"entry": entry}]
        app._SHELF["ad"] = [self.raw(tint_ok=False, tinting=True),
                            self.raw(tint_ok=False), self.raw(key="missing", preparing=True),
                            self.raw(review_cancel_pending=True), self.raw(off_brief=True)]
        got = app.orchestrator_pipeline_state()
        self.assertEqual(got["total"], 6)
        self.assertEqual(got["stages"], {"ready": 1, "awaiting_tint": 1, "rewriting": 1,
            "awaiting_recording": 0, "recording": 1, "needs_replacement": 1,
            "withdrawal_pending": 1})
        self.assertEqual(got["roads"]["banter"]["needs_replacement"], 1)

    def test_editorial_hold_is_not_reported_as_a_failed_recording_engine(self):
        app._SHELF["ad"] = [self.raw(prepared=True, tint_ok=False)]
        got = app.orchestrator_pipeline_state()
        self.assertEqual(got["recording_waiting"], 0)
        self.assertIn("tint approval", got["bottleneck"])
        self.assertIn("Rejected lines", got["next_step"])

    def test_no_progress_wait_is_visible_without_changing_stage_debt_or_entry(self):
        row = self.raw(tint_ok=False, tint_retry_budget={"stagnant_model_responses": 4})
        app._SHELF["ad"] = [row]
        before = copy.deepcopy(row)
        retry = self.patch("tint_retry_status", mock.Mock(return_value={
            "waiting": True, "remaining_seconds": 300, "accepted_highwater": 20,
            "blocking_faults": ["no rhyme evidence"]}))
        got = app.orchestrator_pipeline_state()
        self.assertEqual(got["repair_wait_count"], 1)
        self.assertEqual(got["repair_waits"][0]["accepted_highwater"], 20)
        self.assertEqual(got["repair_waits"][0]["remaining_seconds"], 300)
        self.assertEqual(got["tint_waiting"], 1)
        self.assertEqual(got["recording_waiting"], 0)
        self.assertEqual(row, before)
        retry.assert_called_once_with(row, "ad")

    def brief_fixture(self, paused):
        self.patch("_COORD_BRIEF", {})
        self.patch("_RADIO", {"on": True, "voice_to": "box"})
        self.patch("radio_paused", mock.Mock(return_value=paused))
        self.patch("resource_brief", mock.Mock(return_value={}))
        self.patch("_RESOURCE_STATE", {})
        self.patch("_GAP_OPEN", {"seconds": 200, "label": "the current slot"})
        self.patch("air_quiet_for", mock.Mock(return_value=200))
        self.patch("_BOX_HOLD", [{}, {}, {}, {}])
        self.patch("box_talk_ok", mock.Mock(return_value=True))
        self.patch("coord_upcoming", mock.Mock(return_value=[]))
        self.patch("render_relief", mock.Mock(return_value=False))
        self.patch("prepared_seconds", mock.Mock(return_value=3600))
        self.patch("prepare_target_seconds", mock.Mock(return_value=3600))
        self.patch("brief_state", mock.Mock(return_value={}))
        self.patch("coord_capacity", mock.Mock(return_value={"over": 1}))

    def test_pause_is_not_dead_air_or_a_wedged_device_and_mode_change_invalidates_cache(self):
        self.brief_fixture(False)
        live = app.coord_brief()
        self.assertTrue(any("playing none" in text for text in live["worries"]))
        self.assertEqual(live["gap_open"], 200)
        app.radio_paused.return_value = True
        paused = app.coord_brief()
        self.assertEqual(paused["quiet_for"], 0)
        self.assertEqual(paused["gap_open"], 0)
        self.assertEqual(paused["worries"], [])
        self.assertIn("paused", paused["say"])
        self.assertEqual(paused["held"], 4)

    async def test_flow_does_not_age_a_talk_gap_while_paused_or_off(self):
        self.patch("_STATION_FLOW", mock.Mock(read=mock.Mock(return_value={})))
        self.patch("page_playback_state", mock.Mock(return_value={}))
        self.patch("_floor_busy", mock.Mock(return_value=False))
        self.patch("talk_quiet_limit", mock.Mock(return_value=12))
        quiet = self.patch("talk_quiet_for", mock.Mock(return_value=999))
        self.patch("_RADIO", {"on": True})
        self.patch("radio_paused", mock.Mock(return_value=True))
        for on, paused, monitoring in [(True, True, False), (False, False, False), (True, False, True)]:
            app._RADIO["on"] = on
            app.radio_paused.return_value = paused
            result = await app.station_flow_api(authorization="test")
            self.assertEqual(result["health"]["talk_gap_monitoring"], monitoring)
            self.assertEqual(result["health"]["talk_gap_seconds"], 999 if monitoring else 0)
        self.assertEqual(quiet.call_count, 1)

    async def test_lean_flow_omits_static_graph_without_losing_events(self):
        self.patch("_STATION_FLOW", mock.Mock(read=mock.Mock(return_value={
            "events": [{"id": 1}], "nodes": [{"id": "draft"}],
            "edges": [{"id": "draft:tts"}]})))
        self.patch("page_playback_state", mock.Mock(return_value={}))
        self.patch("_floor_busy", mock.Mock(return_value=False))
        self.patch("talk_quiet_limit", mock.Mock(return_value=12))
        self.patch("talk_quiet_for", mock.Mock(return_value=0))
        self.patch("_RADIO", {"on": False})
        self.patch("radio_paused", mock.Mock(return_value=False))
        result = await app.station_flow_api(lean=1, authorization="test")
        self.assertEqual(result["events"], [{"id": 1}])
        self.assertNotIn("nodes", result)
        self.assertNotIn("edges", result)

    async def test_review_room_counts_match_current_contract_and_include_single_reads(self):
        app._SHELF["ad"] = [self.raw(prepared=False), self.raw(prepared=True, tint_ok=False),
                            self.raw(prepared=True, key="missing")]
        pipeline = app.orchestrator_pipeline_state()
        self.patch("api_orch_logic", mock.AsyncMock(return_value={"pipeline": pipeline}))
        self.patch("line_review_policy", mock.Mock(return_value={}))
        self.patch("crystal_tint_holds", mock.Mock(return_value=True))
        self.patch("crystal_grade_strict", mock.Mock(return_value=False))
        result = await app.api_line_review_context(authorization="test")
        self.assertEqual(result["writing"]["scripts"], 3)
        self.assertEqual(result["writing"]["awaiting_tint"], 1)
        self.assertEqual(result["recording"]["waiting"], 1)
        self.assertEqual(result["recording"]["ready"], 1)
        self.assertEqual(result["recording"]["in_progress"], 0)

    async def test_generic_stocking_cannot_rewrite_an_operator_approved_single_read(self):
        row = self.raw(text="The exact approved candidate.", text_plain="The complete original.",
                       review_shelf_pending=True, tint_ok=False)
        before = copy.deepcopy(row)
        rewrite = self.patch("crystal_tint", mock.AsyncMock(side_effect=AssertionError("must preserve operator wording")))
        revalidate = self.patch("legacy_tint_revalidate", mock.AsyncMock(side_effect=AssertionError("owned by review worker")))
        self.assertFalse(await app.ensure_shelf_row_tinted("ad", row))
        self.assertEqual(row, before)
        rewrite.assert_not_awaited()
        revalidate.assert_not_awaited()

    def test_produced_id_cannot_reserve_or_claim_a_missing_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            self.patch("PRODUCED_ADS_DIR", Path(folder))
            self.patch("ad_list", mock.Mock(return_value=[]))
            row = self.raw(produced="spot", audio="spot.mp3", prepared=True)
            app._SHELF["ad"] = [row]
            self.assertFalse(app.dialogue_row_ready("ad", row))
            self.assertFalse(app.dialogue_row_viable("ad", row))
            self.assertEqual(app.orchestrator_pipeline_state()["stages"]["needs_replacement"], 1)
            audio = Path(folder) / "spot.mp3"
            audio.touch()
            self.assertFalse(app.dialogue_audio_ready("ad", row))
            audio.write_bytes(b"isolated nonempty audio fixture")
            self.assertTrue(app.dialogue_row_ready("ad", row))
            self.assertTrue(app.dialogue_row_viable("ad", row))
            audio.unlink()
            self.assertFalse(app.dialogue_row_ready("ad", row))

    def test_legacy_produced_row_resolves_only_existing_audio_from_its_own_id(self):
        with tempfile.TemporaryDirectory() as folder:
            self.patch("PRODUCED_ADS_DIR", Path(folder))
            (Path(folder) / "valid.mp3").write_bytes(b"isolated fixture")
            self.patch("ad_list", mock.Mock(return_value=[{"id": "other", "audio": "valid.mp3"}]))
            row = self.raw(produced="wanted")
            self.assertFalse(app.dialogue_audio_ready("ad", row))
            app.ad_list.return_value.append({"id": "wanted", "audio": "valid.mp3"})
            self.assertTrue(app.dialogue_audio_ready("ad", row))


if __name__ == "__main__":
    unittest.main()
