"""Camera handoff must release the actual association, never the house radio."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

SPEC = importlib.util.spec_from_file_location("pinelink_radio_release", Path(__file__).resolve().parents[1] / "tools/pinelink.py")
pl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pl)

CONNECTED = "Connected to 5c:8e:8b:dd:fa:b1\nSSID: camera\n"
FREE = "Not connected.\n"
NOW = 1_800_000_000.0
REPORT = {"at": NOW, "capable": True, "ip": "10.89.1.154", "link": {"joined": False}, "relay": {"listening": False}}


class Release(unittest.TestCase):
    def test_already_free_needs_no_disconnect(self):
        with patch.object(pl, "run", return_value=(0, FREE)) as run:
            self.assertEqual((True, ""), pl.release_dongle())
            run.assert_called_once_with(["iw", "dev", pl.SPARE_IF, "link"], 3)

    def test_failed_disconnect_does_not_mark_the_slot_free(self):
        run = Mock(side_effect=[(0, CONNECTED), (1, "disconnect refused"), (0, CONNECTED)])
        with patch.multiple(pl, run=run, relay_pref=Mock(return_value={"pref": "always", "mode": "udp"}),
                            relay_report=Mock(return_value=REPORT), camera_wanted=Mock(return_value=True),
                            _SRC={}, _SRC_MEM={}, _DONGLE_LET_GO=[True]), patch.object(pl.time, "time", return_value=NOW):
            got = pl.source_turn()
            self.assertFalse(got["dongle_released"])
            self.assertFalse(pl._DONGLE_LET_GO[0])
            self.assertIn("disconnect refused", got["dongle_release_error"])
            self.assertIn("disconnect failed", got["why"])

    def test_external_rejoin_is_released_after_prior_success(self):
        run = Mock(side_effect=[(0, FREE), (0, CONNECTED), (0, "disconnected"), (0, FREE)])
        with patch.multiple(pl, run=run, relay_pref=Mock(return_value={"pref": "always", "mode": "udp"}),
                            relay_report=Mock(return_value=REPORT), camera_wanted=Mock(return_value=True),
                            _SRC={}, _SRC_MEM={}, _DONGLE_LET_GO=[False]), patch.object(pl.time, "time", return_value=NOW):
            self.assertTrue(pl.source_turn()["dongle_released"])
            self.assertTrue(pl.source_turn()["dongle_released"])
            self.assertIn(call(["nmcli", "device", "disconnect", pl.SPARE_IF], 8), run.call_args_list)
            self.assertEqual(4, run.call_count)

    def test_successful_command_with_live_association_is_not_release(self):
        with patch.object(pl, "run", side_effect=[(0, CONNECTED), (0, "success"), (0, CONNECTED)]):
            released, why = pl.release_dongle()
            self.assertFalse(released)
            self.assertIn("still associated", why)

    def test_probe_failure_does_not_claim_verified_release(self):
        with patch.object(pl, "run", side_effect=[(1, "probe failed"), (0, "success"), (1, "probe failed")]):
            released, why = pl.release_dongle()
            self.assertFalse(released)
            self.assertIn("could not be verified", why)

    def test_association_is_released_even_before_ipv4_is_assigned(self):
        with patch.object(pl, "run", side_effect=[(0, CONNECTED), (0, "success"), (0, FREE)]) as run, patch.object(pl, "linked", return_value=False) as linked:
            self.assertEqual((True, ""), pl.release_dongle())
            linked.assert_not_called()
            self.assertIn(call(["nmcli", "device", "disconnect", pl.SPARE_IF], 8), run.call_args_list)

    def test_primary_station_interface_is_never_disconnected(self):
        with patch.object(pl, "SPARE_IF", pl.STATION_IF), patch.object(pl, "run") as run:
            released, why = pl.release_dongle()
            self.assertFalse(released)
            self.assertIn("refusing", why)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
