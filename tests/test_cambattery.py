"""[cambattery] the Pine Cam battery block, executed as the patch writes it.

The block edit_cambattery_station.py inserts into app.py is exec'd here with
app.py's own names (data_path, note_action) stubbed, and a local HTTP server
standing in for the camera's Novatek door - so what is tested is the very
text the patch writes, not a copy of it.

Run (dry tree): PYTHONPATH=tests:. python3 -m unittest tests.test_cambattery
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
TOOL = HERE.parent / "tools" / "edit_cambattery_station.py"
SPEC = importlib.util.spec_from_file_location("edit_cambattery_station", TOOL)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

XML = ('<?xml version="1.0" encoding="UTF-8" ?>\n<Function>\n<Cmd>3019</Cmd>\n'
       '<Status>%d</Status>\n<Value>%d</Value>\n</Function>')


def build(tmp: Path) -> dict:
    notes: list = []
    ns: dict = {"__name__": "cambattery_under_test", "json": json, "os": os,
                "re": re, "time": time, "Any": Any,
                "data_path": lambda name: tmp / name,
                "note_action": lambda text, extra="": notes.append(text)}
    exec(compile(tool.BLOCK, "cambattery_block", "exec"), ns)
    ns["_notes"] = notes
    return ns


class Camera(http.server.BaseHTTPRequestHandler):
    status, value, hits = 0, 2, []

    def do_GET(self):  # noqa: N802
        Camera.hits.append(self.path)
        body = (XML % (Camera.status, Camera.value)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class PatchTool(unittest.TestCase):
    def test_idempotent_and_crlf(self):
        src = ('def pinelink_state():\n    got = {}\n'
               + tool.A1 + tool.A2 + '\n')
        code, out, _ = tool.patch(src)
        self.assertEqual(code, 0)
        self.assertEqual(out.count(tool.MARK) >= 2, True)
        self.assertEqual(tool.patch(out)[0], 2)
        self.assertEqual(tool.patch("nothing here")[0], 1)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.py"
            p.write_bytes(src.replace("\n", "\r\n").encode())
            self.assertEqual(tool.main(["x", "--check", str(p)]), 0)
            self.assertEqual(tool.main(["x", "--apply", str(p)]), 0)
            raw = p.read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            self.assertEqual(tool.main(["x", "--check", str(p)]), 2)
            compile(raw.decode().replace("\r\n", "\n"), "patched", "exec")


class Battery(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.tmp = Path(self.d.name)
        self.ns = build(self.tmp)

    def tearDown(self):
        self.d.cleanup()

    def test_parse(self):
        p = self.ns["pinelink_battery_parse"]
        self.assertEqual(p(XML % (0, 3)), 3)
        self.assertEqual(p(XML % (0, 5)), 5)
        self.assertIsNone(p(XML % (-1, 3)))      # refused command
        self.assertIsNone(p(XML % (0, 9)))       # off the table
        self.assertIsNone(p("<html>302</html>"))

    def test_not_read_yet_is_not_a_meter(self):
        v = self.ns["pinelink_battery"]({"state": "down", "fresh": True})
        self.assertFalse(v["ok"])
        self.assertFalse(v["polling"])
        self.assertIn("not read yet", v["say"])

    def test_levels_tones_and_time_left(self):
        ns, t0 = self.ns, 1_000_000.0
        note, view = ns["pinelink_battery_note"], ns["pinelink_battery_view"]

        def feed(code, a, b):             # a reading every 45 s, as polled
            for t in range(int(a), int(b), 45):
                note(code, t0 + t)

        feed(1, 0, 600)                   # first seen: not an edge
        v = view(t0 + 590)
        self.assertEqual((v["word"], v["tone"], v["bars"]), ("half", "ok", 3))
        self.assertIsNone(v["left_s"])    # nothing watched whole yet
        feed(2, 600, 3000)                # a seen drop, then low for 40 min
        v = view(t0 + 610)
        self.assertEqual((v["tone"], v["pct"]), ("amber", 30))
        self.assertEqual(len(ns["_notes"]), 0)
        feed(3, 3000, 3100)               # low was watched whole: 2400 s
        v = view(t0 + 3000 + 60)
        self.assertEqual((v["word"], v["tone"], v["pulse"]), ("last bar", "red", False))
        self.assertEqual(v["left_s"], 2400 - 60)
        self.assertEqual(v["left_say"], "39 m")
        self.assertIn("levels, not a percentage", v["say"])
        self.assertEqual(len(ns["_notes"]), 1)       # the notice, once
        self.assertIn("about 40 m left", ns["_notes"][0])
        note(4, t0 + 5400)                # across a blind gap
        v = view(t0 + 5400)
        self.assertTrue(v["pulse"])
        self.assertEqual(len(ns["_notes"]), 1)       # still once this discharge

    def test_charging_and_a_fresh_battery_rearm(self):
        ns, t0 = self.ns, 2_000_000.0
        ns["pinelink_battery_note"](3, t0)
        self.assertEqual(len(ns["_notes"]), 1)
        ns["pinelink_battery_note"](5, t0 + 30)
        v = ns["pinelink_battery_view"](t0 + 31)
        self.assertTrue(v["charging"])
        self.assertIsNone(v["left_s"])
        self.assertFalse(v["low"])
        ns["pinelink_battery_note"](0, t0 + 60)
        ns["pinelink_battery_note"](3, t0 + 90)
        self.assertEqual(len(ns["_notes"]), 2)

    def test_blind_gap_is_not_a_step(self):
        ns, t0 = self.ns, 3_000_000.0
        note = ns["pinelink_battery_note"]
        note(0, t0)
        note(1, t0 + 100)
        note(1, t0 + 100 + 3600)          # blind for an hour on 'half'
        note(2, t0 + 100 + 3700)
        self.assertIsNone(ns["pinelink_battery_view"](t0 + 3900)["left_s"])

    def test_stale_after_three_minutes(self):
        ns, t0 = self.ns, 4_000_000.0
        ns["pinelink_battery_note"](1, t0)
        self.assertFalse(ns["pinelink_battery_view"](t0 + 170)["stale"])
        v = ns["pinelink_battery_view"](t0 + 181)
        self.assertTrue(v["stale"])
        self.assertIn("STALE", v["say"])

    def test_poll_only_while_live_and_persist(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Camera)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            ns = self.ns
            ns["PINELINK_BATTERY_URL"] = "http://127.0.0.1:%d/?custom=1&cmd=3019" % srv.server_port
            Camera.hits, Camera.value = [], 2
            ns["pinelink_battery"]({"state": "live", "fresh": False})
            ns["pinelink_battery"]({"state": "searching", "fresh": True})
            time.sleep(0.3)
            self.assertEqual(Camera.hits, [])        # not live: never asked
            v = ns["pinelink_battery"]({"state": "live", "fresh": True})
            self.assertTrue(v["polling"])
            for _ in range(50):
                if not ns["_PINELINK_BATT"]["busy"]:
                    break
                time.sleep(0.05)
            ns["pinelink_battery"]({"state": "live", "fresh": True})   # inside 45 s
            time.sleep(0.2)
            self.assertEqual(Camera.hits, ["/?custom=1&cmd=3019"])
            v = ns["pinelink_battery_view"]()
            self.assertEqual(v["word"], "low")
            saved = json.loads((self.tmp / "pinelink_battery.json").read_text())
            self.assertEqual(saved["code"], 2)
            fresh = build(self.tmp)                  # a restart keeps the ledger
            self.assertEqual(fresh["pinelink_battery"](None)["word"], "low")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_camera_away_keeps_last_reading(self):
        ns = self.ns
        ns["PINELINK_BATTERY_URL"] = "http://127.0.0.1:9/?custom=1&cmd=3019"
        ns["pinelink_battery_note"](1, time.time() - 400)
        ns["_pinelink_battery_poll"]()
        v = ns["pinelink_battery_view"]()
        self.assertTrue(v["ok"])
        self.assertTrue(v["stale"])
        self.assertIn("did not answer", v["say"])


if __name__ == "__main__":
    unittest.main()
