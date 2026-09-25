"""The trace trash action bars one complete line across future carriers."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from line_blacklist import Blacklist


class ForgetLineTests(unittest.IsolatedAsyncioTestCase):
    async def test_forget_withdraws_unpublished_carriers_but_keeps_history(self):
        spoken = "Please don't say this."
        other = "A different thought stays."
        larder = [{"script": "HOST: " + spoken}, {"script": "HOST: " + other}]
        shelf = {"news": [{"script": "HOST: " + spoken},
                          {"script": "HOST: " + other}]}
        gold = [{"text": spoken}, {"text": other}]
        aired = {"text": spoken, "aired": "aired", "sid": "past"}
        prepared = {"text": spoken, "aired": "prepared", "sid": "next"}
        companion = {"text": other, "aired": "prepared", "sid": "next"}
        radio = {"chat": [aired, prepared, companion]}
        request = mock.Mock()
        request.json = mock.AsyncMock(return_value={"line_id": "line-7", "text": "spoofed"})
        planner = mock.Mock(refresh=mock.AsyncMock())
        withdrawn = []
        with tempfile.TemporaryDirectory() as directory:
            blacklist = Blacklist(Path(directory) / "lines.json")
            with (mock.patch.object(app, "LINE_BLACKLIST", blacklist),
                  mock.patch.object(app, "_LARDER", larder),
                  mock.patch.object(app, "_SHELF", shelf),
                  mock.patch.object(app, "_RADIO", radio),
                  mock.patch.object(app, "_INVENTORY_PLAN", {"at": 1}),
                  mock.patch.object(app, "_gold_rows", return_value=gold),
                  mock.patch.object(app, "_gold_save"),
                  mock.patch.object(app, "_larder_save"),
                  mock.patch.object(app, "_pantry_save"),
                  mock.patch.object(app, "_radio_entry_rejected"),
                  mock.patch.object(app, "dialogue_entry", side_effect=lambda row: row),
                  mock.patch.object(app, "_burst_withdraw", side_effect=lambda rows, why: withdrawn.extend(rows)),
                  mock.patch.object(app, "said_forget"),
                  mock.patch.object(app, "line_row_of", return_value={"text": spoken}),
                  mock.patch.object(app, "_system2", return_value=planner),
                  mock.patch.object(app, "pipeline_log"),
                  mock.patch.object(app, "require_auth")):
                result = await app.api_said_forget(request)
                self.assertTrue(result["ok"])
                self.assertEqual(result["text"], spoken)
                self.assertTrue(blacklist.contains(spoken))
                self.assertFalse(blacklist.contains(other))
                self.assertEqual(larder, [{"script": "HOST: " + other}])
                self.assertEqual(shelf["news"], [{"script": "HOST: " + other}])
                self.assertEqual(gold, [{"text": other}])
                self.assertEqual(withdrawn, [prepared, companion])
                self.assertIn(aired, radio["chat"])
                self.assertTrue(app.script_has_forgotten_line("HOST: " + spoken))
                self.assertFalse(app.script_has_forgotten_line("HOST: " + other))
                planner.refresh.assert_awaited_once_with(force=True, want_status=False)


if __name__ == "__main__":
    unittest.main()
