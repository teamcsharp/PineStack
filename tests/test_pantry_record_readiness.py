import json
import unittest
from unittest import mock

import app


OLD = json.dumps({"plot": ["same-story", 1], "reply": 6500,
                  "swath": [0.45, 3000], "tint": [], "turns": [16, 22]})
NOW = json.dumps({"plot": ["same-story", 2], "reply": 6500,
                  "swath": [0.45, 3000], "tint": [], "turns": [8, 11]})


class PantryRecordReadinessTests(unittest.IsolatedAsyncioTestCase):
    def test_bound_profile_uses_the_bank_compatibility_rule(self):
        entry = {"prep_kind": "gallery", "profile": OLD,
                 "script_plain": "A: Still useful", "script": "A: Still useful"}
        with (mock.patch.object(app, "_larder_profile_signature", return_value=NOW),
              mock.patch.object(app, "tinted_kept", return_value=False)):
            self.assertTrue(app._larder_current(entry))
            self.assertTrue(app.dialogue_row_viable("gallery", entry))
            entry["profile"] = OLD.replace('"reply": 6500', '"reply": 1000')
            self.assertFalse(app._larder_current(entry))

    def test_exact_committed_rows_allow_missing_audio_even_if_marked_prepared(self):
        manager = {"prep_kind": "manager", "profile": OLD,
                   "script_plain": "A: Written", "script": "A: Written",
                   "prepared": True, "chunks": 8, "made": 8,
                   "keys": ["lost-clip"]}
        gallery = {"prep_kind": "gallery", "profile": OLD,
                   "script_plain": "A: Written", "script": "A: Written",
                   "prepared": False, "chunks": 8, "made": 5}
        selected = [{"id": "manager-842469ac76", "kind": "manager",
                     "ready": False, "row": {"entry": manager}},
                    {"id": "gallery-f8b5b4af35", "kind": "gallery",
                     "ready": False, "row": {"entry": gallery}}]
        with (mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"selected": selected}),
              mock.patch.object(app, "_larder_profile_signature", return_value=NOW),
              mock.patch.object(app, "tinted_kept", return_value=False),
              mock.patch.object(app, "dialogue_row_ready", return_value=False),
              mock.patch.object(app, "dialogue_audio_ready", return_value=False),
              mock.patch.object(app, "dialogue_tint_ready", return_value=True)):
            for road, ident, entry in (("manager", "manager-842469ac76", manager),
                                       ("gallery", "gallery-f8b5b4af35", gallery)):
                self.assertEqual(app.pantry_order_record_target(
                    {"road": road, "item_id": ident}), ("round", entry))
            with mock.patch.object(app, "dialogue_audio_ready", return_value=True):
                self.assertEqual(app.pantry_order_record_target(
                    {"road": "manager", "item_id": "manager-842469ac76"}),
                                 ("", None))

    async def test_recording_sitting_repairs_prepared_row_with_lost_clips(self):
        entry = {"prep_kind": "manager", "script": "A: Written",
                 "prepared": True, "restored": False}

        async def restore(row, only_voice=""):
            row["restored"] = True
            return True

        with (mock.patch.object(app, "dialogue_audio_ready",
                                side_effect=lambda kind, row: row["restored"]),
              mock.patch.object(app, "dialogue_row_viable", return_value=True),
              mock.patch.object(app, "dialogue_tint_ready", return_value=True),
              mock.patch.object(app, "session_voices", new_callable=mock.AsyncMock,
                                return_value={"dj": "voice"}),
              mock.patch.object(app, "banter_turns", return_value=["Written"]),
              mock.patch.object(app, "_round_chunks",
                                return_value=[("Written", "voice", "dj")]),
              mock.patch.object(app, "pantry_key", return_value="lost-clip"),
              mock.patch.object(app, "pantry_get", return_value=None),
              mock.patch.object(app, "voice_engine_for", return_value="xtts"),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "voice_meta", return_value={"name": "DJ"}),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "_PREP_DEADLINE", [0.0]),
              mock.patch.object(app, "larder_prepare", new_callable=mock.AsyncMock,
                                side_effect=restore) as prepare):
            result = await app.recording_sitting([entry], 45.0)
        prepare.assert_awaited_once_with(entry, only_voice="voice")
        self.assertEqual(result["finished"], 1)


if __name__ == "__main__":
    unittest.main()
