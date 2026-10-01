"""[why-quiet] the station says why the DJs are quiet."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import why_quiet as wq  # noqa: E402

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")


class Findings(unittest.TestCase):
    def test_linear_backlog_is_the_first_cause(self):
        now = time.time()
        f = {"on": True, "paused": False, "playout_mode": "linear",
             "playout_verdict": "LINEAR (enforcing) · air free · queued asks: 304",
             "engines": {"xtts": True, "voxtral": False}, "last_dj": {"ts": now - 1800}, "talk": 100}
        got = wq.findings(f, now)
        self.assertEqual(got[0]["level"], "stop")
        self.assertIn("LINEAR with 304 queued asks", got[0]["what"])
        self.assertIn("echo shadow", got[0]["do"])
        self.assertTrue(any("for 30 min" in r["what"] for r in got))

    def test_paused_off_engines_backoff(self):
        now = time.time()
        f = {"on": False, "paused": True, "paused_for": 600, "engines": {"xtts": False, "voxtral": False},
             "roads_out": {"ad": now + 300}, "last_dj": None, "talk": 0}
        whats = " | ".join(r["what"] for r in wq.findings(f, now))
        for bit in ("radio is off", "paused (10 min)", "Neither voice engine", "ad road is sitting out",
                    "since this boot", "talk dial is at 0%"):
            self.assertIn(bit, whats)

    def test_all_well(self):
        now = time.time()
        got = wq.findings({"on": True, "paused": False, "playout_mode": "shadow", "playout_verdict": "shadow",
                           "engines": {"xtts": True}, "last_dj": {"ts": now - 20}, "talk": 50}, now)
        self.assertEqual([r["level"] for r in got], ["info"])

    def test_reasons_and_text(self):
        ev = [{"ts": 1, "kind": "air", "text": "fine"},
              {"ts": 2000, "kind": "drop", "text": "[door-why] banter: no planned takes"},
              {"ts": 3000, "kind": "ads", "text": "[road-backoff] the ad road was refused 2 times"}]
        said = wq.reasons(ev)
        self.assertEqual(len(said), 2)
        out = wq.text({"playout_verdict": "shadow", "last_dj": {"ts": 0, "name": "Ash", "text": "hi"}},
                      [{"level": "stop", "what": "X", "do": "Y"}], said)
        self.assertIn("[STOP] X", out)
        self.assertIn("do: Y", out)
        self.assertIn("[door-why] banter", out)

    def test_wired(self):
        self.assertIn('@app.get("/api/dj/why-quiet", response_model=None)', APP_TEXT)
        self.assertIn("why-quiet?text=1", (ROOT / "tools" / "why-quiet.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
