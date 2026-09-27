"""[h3-hourly] The hourly H3 door is in app.py, and its clock arithmetic is
right: minute 3 of this hour until it has fired, then minute 3 of the next.
The arithmetic is exec'd out of app.py's own text so this test needs no
station."""
import importlib.util
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("h3_hourly_door_patch", ROOT / "tools" / "h3_hourly_door_patch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _next_at():
    text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
    m = re.search(r"\ndef h3_hourly_next_at\(.*?\n(?=\n\ndef )", text, re.S)
    assert m, "h3_hourly_next_at is not in app.py"
    ns = {"time": time, "_H3_HOURLY_MINUTE": 3, "_H3_HOURLY_PERIOD_S": 3600}
    exec(m.group(0), ns)  # noqa: S102 - the station's own function, out of its own file
    return ns["h3_hourly_next_at"]


class H3HourlyDoor(unittest.TestCase):
    def test_every_edit_is_in_app_py(self):
        mod = _tool()
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        self.assertIn('@app.get("/api/h3/hourly")', text)
        self.assertIn('@app.post("/api/h3/hourly")', text)
        self.assertIn("h3_hourly_render(state)", text)

    def test_the_clock_names_the_next_fire(self):
        next_at = _next_at()
        hour = time.mktime((2026, 9, 27, 10, 0, 0, 0, 0, -1))
        # 10:01, nothing fired this hour: 10:03
        self.assertEqual(next_at(hour + 60, ""), hour + 180)
        # 10:01 but this hour's marker already fired (a restart inside the minute): 11:03
        self.assertEqual(next_at(hour + 60, "2026092710"), hour + 3600 + 180)
        # 10:05, fired: 11:03
        self.assertEqual(next_at(hour + 300, "2026092710"), hour + 3600 + 180)
        # 10:05, not fired (the station was off at :03): the clock fires at its next tick, so :03 is past -> 11:03
        self.assertEqual(next_at(hour + 300, "2026092709"), hour + 3600 + 180)
        # 10:02:59 with last hour's marker: 10:03
        self.assertEqual(next_at(hour + 179, "2026092709"), hour + 180)


if __name__ == "__main__":
    unittest.main()
