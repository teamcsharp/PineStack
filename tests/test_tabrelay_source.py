"""[tabrelay] tools/pinelink.py's road to the camera: plan_source() and the edit.

Run from a DRY tree that has had edit_tabrelay_pinelink.py applied:
    PYTHONPATH=tests:. python3 -m unittest tests.test_tabrelay_source
Nothing here touches a radio: the host module is imported, never supervise()d.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("pinelink_tabrelay", ROOT / "tools" / "pinelink.py")
pl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pl)

NOW = 1_800_000_000.0


def rep(joined=True, capable=True, age=2.0, listening=True, ip="10.89.1.154", why=""):
    return {"at": NOW - age, "capable": capable, "ip": ip,
            "link": {"joined": joined, "signal": 78, "link_mbps": 65, "why": why},
            "relay": {"listening": listening}}


class Plan(unittest.TestCase):
    def plan(self, pref, r, mem=None, wanted=True, now=NOW):
        return pl.plan_source(pref, r, now, {} if mem is None else mem, wanted)

    def test_no_tablet_at_all_is_exactly_today(self):
        for pref in ("auto", "never"):
            p = self.plan(pref, {})
            self.assertEqual(("dongle", False, False), (p["use"], p["want_tablet"], p["release_dongle"]))

    def test_joined_tablet_is_preferred_and_the_dongle_lets_go(self):
        p = self.plan("auto", rep())
        self.assertEqual(("tablet", True, True, "10.89.1.154"), (p["use"], p["want_tablet"], p["release_dongle"], p["ip"]))

    def test_never_ignores_a_joined_tablet(self):
        self.assertEqual("dongle", self.plan("never", rep())["use"])

    def test_stale_or_incapable_report_falls_back_to_the_dongle(self):
        self.assertEqual("dongle", self.plan("auto", rep(age=pl.RELAY_FRESH_S + 1))["use"])
        p = self.plan("auto", rep(capable=False, joined=False, why="local-only STA+STA is off"))
        self.assertEqual(("dongle", False), (p["use"], p["want_tablet"]))
        self.assertIn("local-only", p["why"])
        # joined but the relay not listening is not a road
        self.assertEqual("dongle", self.plan("auto", rep(listening=False), wanted=False)["use"])

    def test_auto_handoff_mbb_then_bbm_then_backoff(self):
        mem = {}

        def at(t):      # a fresh, capable, not-yet-joined report at NOW + t
            return self.plan("auto", rep(joined=False, age=-t + 1), mem, now=NOW + t)
        p = at(0)
        self.assertEqual(("dongle", True, False), (p["use"], p["want_tablet"], p["release_dongle"]))
        p = at(pl.RELAY_MBB_S + 1)
        self.assertEqual(("wait", True, True), (p["use"], p["want_tablet"], p["release_dongle"]))
        p = at(pl.RELAY_MBB_S + pl.RELAY_BBM_S + 1)
        self.assertEqual(("dongle", False, False), (p["use"], p["want_tablet"], p["release_dongle"]))
        # backing off: the tablet is not asked again for RELAY_BACKOFF_S[0]
        p = at(pl.RELAY_MBB_S + pl.RELAY_BBM_S + 30)
        self.assertEqual(("dongle", False), (p["use"], p["want_tablet"]))

    def test_auto_does_not_send_the_tablet_hunting_for_an_unwanted_camera(self):
        p = self.plan("auto", rep(joined=False), wanted=False)
        self.assertEqual(("dongle", False), (p["use"], p["want_tablet"]))

    def test_loss_gets_a_grace_then_the_dongle_with_backoff(self):
        mem = {}
        self.assertEqual("tablet", self.plan("auto", rep(), mem, now=NOW)["use"])
        p = self.plan("auto", rep(joined=False), mem, now=NOW + 5)
        self.assertEqual(("wait", True), (p["use"], p["want_tablet"]))
        p = self.plan("auto", rep(joined=False), mem, now=NOW + pl.RELAY_LOSS_S + 1)
        self.assertEqual(("dongle", False), (p["use"], p["want_tablet"]))
        self.assertGreater(mem["fail_until"], NOW)

    def test_always_waits_for_the_tablet_and_keeps_the_dongle_off(self):
        p = self.plan("always", rep(joined=False))
        self.assertEqual(("wait", True, True), (p["use"], p["want_tablet"], p["release_dongle"]))
        p = self.plan("always", {})
        self.assertEqual(("wait", False, True), (p["use"], p["want_tablet"], p["release_dongle"]))


class Road(unittest.TestCase):
    def tearDown(self):
        pl._SRC.update({"use": "dongle", "ip": ""})

    def test_urls_and_transport_follow_the_road(self):
        pl._SRC.update({"use": "dongle", "ip": ""})
        self.assertEqual("rtsp://192.168.1.254:554/live", pl.cam_rtsp())
        self.assertIn(pl.rtsp_transport(), pl.TRANSPORTS)
        pl._SRC.update({"use": "tablet", "ip": "10.89.1.154"})
        self.assertEqual("rtsp://10.89.1.154:8554/live", pl.cam_rtsp())
        self.assertEqual("tcp", pl.rtsp_transport())
        cmd = pl.ffmpeg_cmd(None)
        self.assertEqual("rtsp://10.89.1.154:8554/live", cmd[cmd.index("-i") + 1])
        self.assertEqual("tcp", cmd[cmd.index("-rtsp_transport") + 1])
        cmd = pl.ffmpeg_cmd({"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
        self.assertEqual("rtsp://10.89.1.154:8554/live", cmd[cmd.index("-i") + 1])

    def test_pref_and_report_files(self):
        with tempfile.TemporaryDirectory() as d:
            pref, relay = Path(d) / "p.json", Path(d) / "r.json"
            old = (pl.RELAY_PREF_FILE, pl.RELAY_FILE)
            pl.RELAY_PREF_FILE, pl.RELAY_FILE = pref, relay
            try:
                self.assertEqual({"pref": "auto", "mode": "udp"}, pl.relay_pref())   # no file
                pref.write_text("{not json")
                self.assertEqual("auto", pl.relay_pref()["pref"])                 # unreadable
                pref.write_text(json.dumps({"pref": "never", "mode": "pass"}))
                self.assertEqual({"pref": "never", "mode": "pass"}, pl.relay_pref())
                self.assertEqual({}, pl.relay_report())
                relay.write_text(json.dumps(rep()))
                self.assertTrue(pl.relay_report()["capable"])
                v = pl.source_view()
                self.assertEqual(78, v["tablet_signal"])
            finally:
                pl.RELAY_PREF_FILE, pl.RELAY_FILE = old


class Tool(unittest.TestCase):
    def test_edit_is_idempotent_and_marked(self):
        spec = importlib.util.spec_from_file_location("edit_tabrelay_pinelink", ROOT / "tools" / "edit_tabrelay_pinelink.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        text = (ROOT / "tools" / "pinelink.py").read_text()
        self.assertIn(tool.MARK, text)
        self.assertEqual(1, text.count("def plan_source("))
        self.assertEqual(2, text.count('"-i", cam_rtsp(),'))


if __name__ == "__main__":
    unittest.main()
