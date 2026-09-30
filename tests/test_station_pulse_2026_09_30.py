"""[station-pulse] the pressure relaxes when the hour is in the bank and fills when
everything is made live; the marquee says what the station and its rooms are doing."""
import unittest

import station_pulse as sp

BANK_FULL = {"owed_seconds": 3600, "rendered_ahead_seconds": 3600, "written_only_seconds": 0, "missing_seconds": 0,
             "totals": {"lines": {"rendered": 300, "live": 0}},
             "slots": [{"label": "Painting selling", "kind": "gallery", "current": True, "ready_seconds": 43.5},
                       {"label": "Different news story", "kind": "news", "in_seconds": 312}]}
BANK_EMPTY = {"owed_seconds": 3600, "rendered_ahead_seconds": 0, "written_only_seconds": 0, "missing_seconds": 3600,
              "totals": {"lines": {"rendered": 0, "live": 40}}, "slots": []}
CUP_IDLE = {"writers": {"active": 0, "waiting": 0, "deferred": {}}, "feed": []}
CUP_BUSY = {"writers": {"active": 2, "waiting": 6, "deferred": {"m": 240}},
            "preparing": {"kind": "gallery", "made": 19, "lines": 30},
            "feed": [{"at": 1, "text": "an older note"},
                     {"at": 2, "text": "100% talk found no zero-work larder round; live writing is refused"}]}


class Pulse(unittest.TestCase):
    def test_relaxed_when_the_hour_is_banked(self):
        got = sp.pulse(BANK_FULL, CUP_IDLE, [])
        self.assertEqual(got["pressure"], 0.0)
        self.assertEqual(got["state"], "relaxed")
        self.assertEqual(got["banked"], 1.0)

    def test_full_when_everything_is_made_live(self):
        got = sp.pulse(BANK_EMPTY, CUP_BUSY, list(range(9)))
        self.assertGreaterEqual(got["pressure"], 0.95)
        self.assertEqual(got["state"], "locked up")

    def test_marquee_says_what_is_happening(self):
        got = sp.pulse(BANK_FULL, CUP_BUSY, [1, 2])
        text = " | ".join(got["marquee"])
        self.assertIn("ON AIR - Painting selling (gallery)", text)
        self.assertIn("BANK - 60 min of the next 60 min rendered ahead", text)
        self.assertIn("ROOMS - 2 writers at work, 6 waiting, 240 deferred - recording gallery 19 of 30 lines", text)
        self.assertIn("VOICE - 2 lines waiting for a voice", text)
        self.assertIn("NEXT - Different news story in 5:12", text)
        self.assertIn("ORCHESTRATOR - 100% talk found no zero-work larder round", text)   # the newest note

    def test_nothing_known_is_calm_not_broken(self):
        got = sp.pulse(None, None, None)
        self.assertTrue(got["ok"])
        self.assertGreaterEqual(got["pressure"], 0.0)


if __name__ == "__main__":
    unittest.main()
