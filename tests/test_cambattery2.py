"""[cambattery2] time left, learned per level; the camera going dark.

The block edit_cambattery2_station.py writes into app.py, exec'd with
app.py's names stubbed (data_path, note_action) and a local HTTP server as
the camera. Run (dry tree): PYTHONPATH=tests:. python3 -m unittest tests.test_cambattery2
"""
import http.server
import importlib.util
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "edit_cambattery2_station.py"
SPEC = importlib.util.spec_from_file_location("edit_cambattery2_station", TOOL)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

XML = ('<?xml version="1.0" encoding="UTF-8" ?>\n<Function>\n<Cmd>3019</Cmd>\n'
       '<Status>%d</Status>\n<Value>%d</Value>\n</Function>')
T0 = 1_800_000_000.0
MIN = 60.0


def build(tmp: Path) -> dict:
    notes: list = []
    ns: dict = {"__name__": "cambattery2_under_test", "json": json, "os": os,
                "re": re, "time": time, "Any": Any,
                "data_path": lambda name: tmp / name,
                "note_action": lambda text, extra="": notes.append(text)}
    exec(compile(tool.BLOCK, "cambattery2_block", "exec"), ns)
    ns["_notes"] = notes
    return ns


def feed(ns, code, a, b, step=45):
    """A reading every 45 s from T0+a to T0+b (as polled); also the link live."""
    t = a
    while t < b:
        ns["pinelink_battery_note"](code, T0 + t)
        ns["_PINELINK_BATT"]["live_seen_at"] = T0 + t
        t += step
    return t


class PatchTool(unittest.TestCase):
    V1 = ('def pinelink_state():\n    got["battery"] = pinelink_battery(got)\n    return got\n'
          '\n\n# ------------------------------------------------------------ [cambattery]\n'
          '# old\ndef pinelink_battery(link=None):\n    return {}\n'
          '\n\nPINELINK_IFACE = "wlx984827b6b478"\n')

    def test_replaces_v1_block_idempotent_crlf(self):
        code, out, _ = tool.patch(self.V1)
        self.assertEqual(code, 0)
        self.assertIn(tool.MARK, out)
        self.assertNotIn("# old\n", out)
        self.assertEqual(out.count("def pinelink_battery(link"), 1)
        self.assertIn('\n\n\nPINELINK_IFACE = "wlx984827b6b478"', out)
        self.assertEqual(tool.patch(out)[0], 2)
        self.assertEqual(tool.patch("no v1 here")[0], 1)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.py"
            p.write_bytes(self.V1.replace("\n", "\r\n").encode())
            self.assertEqual(tool.main(["x", "--apply", str(p)]), 0)
            raw = p.read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            self.assertEqual(tool.main(["x", "--check", str(p)]), 2)
            compile(raw.decode().replace("\r\n", "\n"), "patched", "exec")


class Countdown(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.tmp = Path(self.d.name)
        self.ns = build(self.tmp)

    def tearDown(self):
        self.d.cleanup()

    def view(self, t, live=True):
        return self.ns["pinelink_battery_view"](T0 + t, live=live)

    def test_default_table_is_90_min_from_full(self):
        self.assertEqual(sum(tool_ns_default(self.ns).values()), 90 * MIN)

    def test_leads_with_time_left_estimate_and_counts_down(self):
        ns = self.ns
        feed(ns, 0, 0, 10)                     # first seen at full, mid-level
        v = self.view(0)
        # half of full taken as gone (15) + 27 + 20 + 10 + 3 = 75 min
        self.assertEqual(v["left_s"], 75 * MIN)
        self.assertEqual(v["label"], "~1 h 15 min left · estimate")
        self.assertTrue(v["estimate"])
        self.assertEqual(v["word"], "full")    # the word is still there, for the tooltip
        self.assertIn("full", v["what"])
        feed(ns, 0, 45, 10 * MIN)
        self.assertEqual(self.view(5 * MIN)["left_s"], 70 * MIN)   # counting down
        feed(ns, 1, 10 * MIN, 11 * MIN)        # a seen drop: half starts whole
        v = self.view(10 * MIN)
        self.assertEqual(v["left_s"], (27 + 20 + 10 + 3) * MIN)
        self.assertEqual(v["tone"], "ok")

    def test_never_below_under_5_min(self):
        ns = self.ns
        feed(ns, 2, 0, 45)
        feed(ns, 3, 45, 90)                    # last bar, seen dropping in
        v = self.view(45 + 11 * MIN)           # past its 10 min default
        self.assertEqual(v["left_s"], 3 * MIN)  # only the empty level remains
        self.assertEqual(v["label"], "under 5 min left · estimate")
        self.assertEqual((v["tone"], v["word"]), ("red", "last bar"))
        v = self.view(45 + 60 * MIN)         # far past: the floor holds
        self.assertLessEqual(v["left_s"], 3 * MIN)
        self.assertEqual(v["label"], "under 5 min left · estimate")

    def test_learns_a_whole_level_and_drops_estimate_for_it(self):
        ns = self.ns
        feed(ns, 0, 0, 45)
        feed(ns, 1, 45, 45 + 40 * MIN)          # half, watched whole: 40 min
        feed(ns, 2, 45 + 40 * MIN, 45 + 41 * MIN)
        learned = ns["_PINELINK_BATT"]["learned"]
        self.assertEqual(learned["1"]["n"], 1)
        self.assertEqual(learned["1"]["avg_s"], 40 * MIN)
        self.assertNotIn("0", learned)          # full was first seen: never whole
        v = self.view(45 + 40 * MIN)
        self.assertTrue(v["estimate"])          # low, last bar, empty still default
        # smoothing: a second discharge of 30 min -> 0.4*30 + 0.6*40 = 36 min
        ns["pinelink_battery_note"](5, T0 + 9000)        # charging resets the run
        ns["pinelink_battery_note"](0, T0 + 20000)
        feed(ns, 1, 20045, 20045 + 30 * MIN)
        ns["pinelink_battery_note"](2, T0 + 20045 + 30 * MIN)
        self.assertAlmostEqual(ns["_PINELINK_BATT"]["learned"]["1"]["avg_s"], 36 * MIN, places=0)
        self.assertEqual(ns["_PINELINK_BATT"]["learned"]["1"]["n"], 2)

    def test_all_levels_learned_is_not_an_estimate(self):
        ns = self.ns
        ns["_PINELINK_BATT"]["learned"] = {str(k): {"avg_s": 600.0, "n": 1} for k in range(5)}
        feed(ns, 1, 0, 45)
        feed(ns, 2, 45, 90)
        v = self.view(45 + 60)
        self.assertFalse(v["estimate"])
        self.assertEqual(v["left_s"], 600 - 60 + 600 + 600)
        self.assertEqual(v["label"], "~29 min left")

    def test_blind_gap_teaches_nothing(self):
        ns = self.ns
        feed(ns, 0, 0, 45)
        feed(ns, 1, 45, 90)
        ns["pinelink_battery_note"](1, T0 + 90 + 3600)   # blind an hour
        ns["pinelink_battery_note"](2, T0 + 90 + 3645)
        self.assertFalse(ns["_PINELINK_BATT"].get("learned"))

    def test_notice_at_last_level_says_minutes(self):
        ns = self.ns
        feed(ns, 2, 0, 45)
        feed(ns, 3, 45, 200)
        self.assertEqual(ns["_notes"], ["Pine Cam: about 13 min of battery left"])

    def test_charging_label_and_no_time_to_full(self):
        ns = self.ns
        feed(ns, 3, 0, 45)
        feed(ns, 5, 45, 10 * MIN)
        v = self.view(10 * MIN)
        self.assertEqual(v["label"], "charging")
        self.assertTrue(v["charging"])
        self.assertIsNone(v["left_s"])
        self.assertIn("time to full cannot be learned", v["what"])
        self.assertIn("charging, for 9 min", v["what"])

    def test_learning_persists_across_a_restart(self):
        ns = self.ns
        feed(ns, 0, 0, 45)
        feed(ns, 1, 45, 45 + 40 * MIN)
        feed(ns, 2, 45 + 40 * MIN, 45 + 41 * MIN)
        with ns["_PINELINK_BATT_LOCK"]:
            ns["_pinelink_battery_save"]()
        again = build(self.tmp)
        again["_pinelink_battery_load"]()
        self.assertEqual(again["_PINELINK_BATT"]["learned"]["1"]["avg_s"], 40 * MIN)
        v = again["pinelink_battery_view"](T0 + 45 + 41 * MIN, live=True)
        self.assertEqual([b["learned"] for b in v["basis"]], [False, False, False])
        self.assertIn("default", v["what"])

    def test_reads_a_wave_bb_ledger(self):
        now = time.time()
        (self.tmp / "pinelink_battery.json").write_text(json.dumps(
            {"code": 3, "at": now - 20, "ok_at": now - 20, "hist": [{"code": 3, "at": now - 90, "edge": False}],
             "noted": True, "error": ""}))
        v = self.ns["pinelink_battery"](None)
        self.assertTrue(v["ok"])
        self.assertIn("left", v["label"])
        self.assertFalse(v["dark"])


class WentDark(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.tmp = Path(self.d.name)
        self.ns = build(self.tmp)

    def tearDown(self):
        self.d.cleanup()

    def drop_link(self, at):
        self.ns["_pinelink_battery_dark_check"](T0 + at)

    def test_dark_on_last_bar_learns_and_tells_once(self):
        ns = self.ns
        feed(ns, 2, 0, 45)
        end = feed(ns, 3, 45, 45 + 7 * MIN)     # last bar watched from its drop, 7 min
        ns["_PINELINK_BATT"]["live_seen_at"] = T0 + end - 45 + 20
        self.drop_link(end + 30)
        B = ns["_PINELINK_BATT"]
        self.assertEqual(B["dies_at"], 3)
        self.assertAlmostEqual(B["learned"]["3"]["avg_s"], end - 45 + 20 - 45, places=0)
        v = ns["pinelink_battery_view"](T0 + end + 60, live=False)
        self.assertTrue(v["dark"])
        self.assertEqual(v["label"], "camera went dark – battery likely flat")
        self.assertEqual(v["tone"], "stale")
        self.assertFalse(v["pulse"])
        self.assertEqual(v["dark_was"], "~6 min left · estimate")
        self.assertIn("went dark", v["what"])
        dark_notes = [n for n in ns["_notes"] if "went dark" in n]
        self.assertEqual(len(dark_notes), 1)
        self.assertIn("battery likely flat", dark_notes[0])
        self.drop_link(end + 90)                 # asked again: still one notice
        self.assertEqual(len([n for n in ns["_notes"] if "went dark" in n]), 1)
        saved = json.loads((self.tmp / "pinelink_battery.json").read_text())
        self.assertEqual(saved["dies_at"], 3)
        self.assertTrue(saved["dark"])
        # the next discharge: dies_at=3 means empty (level 4) is not counted
        ns["pinelink_battery_note"](5, T0 + 9000)
        self.assertFalse(ns["pinelink_battery_view"](T0 + 9001, live=False)["dark"])
        ns["pinelink_battery_note"](2, T0 + 20000)
        ns["pinelink_battery_note"](2, T0 + 20045)
        v = ns["pinelink_battery_view"](T0 + 20045, live=True)
        self.assertEqual([b["code"] for b in v["basis"]], [2, 3])

    def test_not_dark_when_healthy_charging_or_old(self):
        ns = self.ns
        feed(ns, 1, 0, 200)                      # half: switched off, not flat
        self.drop_link(300)
        self.assertFalse(ns["_PINELINK_BATT"].get("dark"))
        ns2 = build(self.tmp)
        feed(ns2, 5, 0, 200)
        ns2["_pinelink_battery_dark_check"](T0 + 300)
        self.assertFalse(ns2["_PINELINK_BATT"].get("dark"))
        ns3 = build(self.tmp)
        ns3["pinelink_battery_note"](3, T0)
        ns3["_PINELINK_BATT"]["live_seen_at"] = T0 + 3600   # reading predates the stretch
        ns3["_pinelink_battery_dark_check"](T0 + 3700)
        self.assertFalse(ns3["_PINELINK_BATT"].get("dark"))

    def test_link_state_drives_it_and_live_hides_it(self):
        ns = self.ns
        now = time.time()
        ns["pinelink_battery_note"](2, now - 200)
        ns["pinelink_battery_note"](3, now - 100)
        ns["_PINELINK_BATT"]["live_seen_at"] = now - 5
        ns["_PINELINK_BATT"]["tried_at"] = now      # no poll from this test
        v = ns["pinelink_battery"]({"state": "no-link", "fresh": True})
        self.assertTrue(v["dark"])
        self.assertFalse(v["polling"])
        v = ns["pinelink_battery"]({"state": "live", "fresh": True})
        self.assertFalse(v["dark"])              # back on air: the poll will clear it


class Poll(unittest.TestCase):
    def test_poll_reads_the_camera_door(self):
        class Camera(http.server.BaseHTTPRequestHandler):
            hits = []

            def do_GET(self):  # noqa: N802
                Camera.hits.append(self.path)
                body = (XML % (0, 3)).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Camera)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            ns = build(Path(d))
            ns["PINELINK_BATTERY_URL"] = "http://127.0.0.1:%d/?custom=1&cmd=3019" % srv.server_port
            try:
                ns["pinelink_battery"]({"state": "down", "fresh": True})
                self.assertEqual(Camera.hits, [])
                ns["pinelink_battery"]({"state": "live", "fresh": True})
                for _ in range(60):
                    if not ns["_PINELINK_BATT"]["busy"]:
                        break
                    time.sleep(0.05)
                self.assertEqual(Camera.hits, ["/?custom=1&cmd=3019"])
                v = ns["pinelink_battery_view"](live=True)
                self.assertEqual(v["word"], "last bar")
                self.assertIn("left", v["label"])
                self.assertEqual(len(ns["_notes"]), 1)
            finally:
                srv.shutdown()
                srv.server_close()


def tool_ns_default(ns):
    return ns["PINELINK_BATTERY_DEFAULT_S"]


if __name__ == "__main__":
    unittest.main()
