"""#1063: the tint yields to the air.

The second pass is wanted and attempted on every road, but only the
operator's hold (crystal_tint_hold) lets an unproved rewrite keep
dialogue off the air. Measured 2026-09-06 with the hold in force: 144
lines offered to the tint, 1 passed, every phone call lost before the
speaker, and the emergency host reading filler for three hours.
"""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app


class TintYieldTests(unittest.IsolatedAsyncioTestCase):
    def crystal_on(self, hold: bool):
        return (mock.patch.object(app, "crystal_active",
                                  return_value=[{"name": "test", "on": True}]),
                mock.patch.object(app, "dj_settings",
                                  return_value={**app.DEFAULT_DJ,
                                                "crystal_tint_pass": True,
                                                "crystal_coverage": 100,
                                                "crystal_tint_hold": hold}))

    @staticmethod
    def recorded_entry() -> dict:
        return {"profile": "current", "prep_kind": "banter",
                "script": "A: plain words", "script_plain": "A: plain words",
                "use": "plain", "chunks": 2, "made": 2, "keys": ["one", "two"],
                "tint_revalidation": {"state": "repair_required"}}

    def test_default_is_no_hold(self):
        self.assertFalse(app.DEFAULT_DJ["crystal_tint_hold"])
        base = copy.deepcopy(app.DEFAULT_SETTINGS)
        base["dj"] = {"crystal_tint_pass": True}
        self.assertFalse(app.validate_settings(base)["dj"]["crystal_tint_hold"])
        base["dj"] = {"crystal_tint_hold": 1}
        self.assertTrue(app.validate_settings(base)["dj"]["crystal_tint_hold"])

    def test_pass_is_wanted_but_not_required_without_the_hold(self):
        a, b = self.crystal_on(False)
        with a, b:
            self.assertTrue(app.crystal_tint_two_pass())
            self.assertTrue(app.dialogue_tint_wanted())
            self.assertFalse(app.dialogue_tint_required())
            self.assertFalse(app.crystal_tint_holds())

    def test_the_hold_restores_the_contract(self):
        a, b = self.crystal_on(True)
        with a, b:
            self.assertTrue(app.dialogue_tint_wanted())
            self.assertTrue(app.dialogue_tint_required())

    def test_a_mocked_requirement_still_means_the_pass_is_wanted(self):
        with mock.patch.object(app, "dialogue_tint_required", return_value=True):
            self.assertTrue(app.dialogue_tint_wanted())

    def test_recorded_round_is_ready_on_its_audio_without_the_hold(self):
        entry = self.recorded_entry()
        a, b = self.crystal_on(False)
        with (a, b,
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            self.assertIs(app.dialogue_entry(entry), entry)
            self.assertTrue(app.dialogue_tint_ready("banter", entry))
            self.assertTrue(app.dialogue_audio_ready("banter", entry))
            self.assertTrue(app.dialogue_row_ready("banter", entry))
        a, b = self.crystal_on(True)
        with (a, b,
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            self.assertTrue(app.dialogue_audio_ready("banter", entry))
            self.assertFalse(app.dialogue_row_ready("banter", entry))

    async def test_recovery_clock_stands_down_without_the_hold(self):
        a, b = self.crystal_on(False)
        with (a, b,
              mock.patch.object(app, "_RADIO", {"on": True}),
              mock.patch.object(app, "_TINT_RECOVERY_STATE",
                                {"running": False, "checked": 0,
                                 "last_at": 0.0, "why": ""}),
              mock.patch.object(app, "ensure_shelf_row_tinted",
                                new_callable=mock.AsyncMock) as repair):
            self.assertFalse(await app.tint_recovery_step())
            repair.assert_not_awaited()
            self.assertIn("yields to the air", app._TINT_RECOVERY_STATE["why"])

    def test_flow_state_names_held_rounds_only_under_the_hold(self):
        entry = self.recorded_entry()
        patches = [
            mock.patch.object(app, "_LARDER", [entry]),
            mock.patch.object(app, "_larder_current", return_value=True),
            mock.patch.object(app, "_pantry_key_ready", return_value=True),
            mock.patch.object(app, "_RADIO", {"on": True}),
            mock.patch.object(app, "hour_shortfall", return_value={}),
            mock.patch.object(app, "prepared_seconds", return_value=0.0),
            mock.patch.object(app, "prepared_by_kind", return_value={}),
            mock.patch.object(app, "prep_urgent", return_value=None),
            mock.patch.object(app, "prepare_target_seconds", return_value=3600.0),
        ]

        def state_with(hold: bool) -> dict:
            a, b = self.crystal_on(hold)
            for p in (a, b, *patches):
                p.start()
            try:
                return app._dialogue_flow_state_fresh()
            finally:
                for p in (a, b, *patches):
                    p.stop()

        held = state_with(True)
        self.assertTrue(held["tint_hold"])
        self.assertEqual(held["ready"], 0)
        self.assertTrue(any("held off the air for tint proof" in why
                            for why in held["blockers"]), held["blockers"])
        free = state_with(False)
        self.assertFalse(free["tint_hold"])
        self.assertEqual(free["ready"], 1)
        self.assertFalse(any("held off the air" in why
                             for why in free["blockers"]), free["blockers"])

    def test_line_prints_is_parsed_once_per_file_change(self):
        now = int(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "line_prints.json"
            path.write_text(json.dumps([{"key": "a line here", "last": now}]))
            with (mock.patch.object(app, "LINE_PRINTS_PATH", path),
                  mock.patch.object(app, "_LINE_ROWS", {"at": -1, "rows": []}),
                  mock.patch.object(app.json, "loads",
                                    wraps=json.loads) as loads):
                first = app.line_prints()
                second = app.line_prints()
                self.assertEqual(first, second)
                self.assertEqual(loads.call_count, 1)
                # A fresh list each call: appending does not touch the cache.
                first.append({"key": "another line here", "last": now})
                self.assertEqual(len(app.line_prints()), 1)
                # The writer refreshes the cache without a re-parse of the
                # ledger (it may parse the settings file for the window).
                app._prints_write(first)
                parsed = loads.call_count
                self.assertEqual(len(app.line_prints()), 2)
                self.assertEqual(loads.call_count, parsed)
                self.assertEqual(len(json.loads(path.read_text())), 2)


if __name__ == "__main__":
    unittest.main()
