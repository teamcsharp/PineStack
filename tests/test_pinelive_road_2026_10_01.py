"""[plroad] An ended set leaves no road behind.

"The spark is unable to detect my interface" (2026-10-01): the last set ran
on the network road, and its source outlived it - the panel fell back to it,
every later start and Detect took the network road, and the K.O. Sidekick sat
ready on USB with nothing opening it.

  ssh host: cd ~/pinevoice-stack/spark-agent &&
      python3 -m unittest tests.test_pinelive_road_2026_10_01 -v
"""
import json
import time
import unittest

import pinelive
from tests.test_pinelive_toggles import _Base


class EndedSetForgetsItsRoad(_Base):
    def test_a_stopped_network_set_reports_no_road(self):
        pl = self.booted()
        self.arm(pl)
        with pl.lock:
            pl.source_kind = "network"
        pl.stop("test")
        self.assertIsNone(pl.source_kind)
        control = json.loads(pl.control_path.read_text())
        self.assertEqual(control.get("source"), "")
        self.assertNotEqual((pl.state().get("source") or {}).get("kind"), "network")

    def test_the_sidekick_is_named_for_what_it_is(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "pinelive_host", Path(__file__).resolve().parents[1] / "tools" / "pinelive_host.py")
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        self.assertIn("Sidekick", host.KNOWN_NAMES["2367:9420"])
        self.assertNotIn("K.O. II", host.KNOWN_NAMES["2367:9420"])


if __name__ == "__main__":
    unittest.main()
