"""The operator's off switch bypasses prompt and second-pass tinting."""
import unittest
from unittest import mock

import app


class TintOffPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_switch_bypasses_active_crystal_and_model(self):
        with (mock.patch.object(app, "dj_settings", return_value={"crystal_tint_pass": False}),
              mock.patch.object(app, "crystals_read", return_value={
                  "doom": {"name": "DOOM", "on": True, "strength": 88}}),
              mock.patch.object(app, "ask_model", side_effect=AssertionError("tint model ran")),
              mock.patch.object(app, "orch_used") as used):
            self.assertEqual(app.crystal_active(), [])
            self.assertEqual(app.crystal_clause(), "")
            self.assertEqual(app.crystal_tint_note({"name": "DOOM", "on": True}), "")
            self.assertFalse(app.crystal_tint_two_pass())
            self.assertFalse(app.crystal_tint_holds())
            self.assertFalse(app.dialogue_tint_wanted())
            result = await app.crystal_tint("A: The station is live.", "banter")
            self.assertFalse(result["ok"])
            self.assertIn("off", result["why"])
            used.assert_not_called()


if __name__ == "__main__":
    unittest.main()
