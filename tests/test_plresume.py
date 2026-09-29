"""[plresume] A record a live set cut resumes where it was cut.

pinelive.PineLive._take_air() re-queues a COPY of the cut record carrying
`resume_s` (the position from _RADIO["started"]), never twice in an hour, and
not at all with under 20 s left; app.dj_on_air() pops `resume_s` and
back-dates _RADIO["started"] by it, which is what every road follows.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import pinelive

HERE = Path(__file__).resolve().parent.parent


def _dj_on_air_ns() -> dict[str, Any]:
    """dj_on_air() alone, out of app.py, over a stub _RADIO."""
    text = (HERE / "app.py").read_text(encoding="utf-8")
    at = text.index("\ndef dj_on_air(")
    end = text.index("\n\n\n", at)
    ns: dict[str, Any] = {
        "Any": Any, "time": time,
        "_RADIO": {"now": None, "started": 0.0, "coming": None, "history": []},
        "record_bound_cut": lambda *a, **k: None,
        "media_sign": lambda _id: "sig",
        "remember_played": lambda _t: None,
        "_music_log_append": lambda _t: None,
    }
    exec(compile(text[at:end], "app.py:dj_on_air", "exec"), ns)
    return ns


class TakeAirRequeue(unittest.TestCase):
    def setUp(self):
        self._saved = dict(pinelive._G)
        self.td = tempfile.TemporaryDirectory()
        self.pl = pinelive.PineLive(data_dir=Path(self.td.name))
        self.pl.event = {"id": "mxlive-t", "started_at": time.time(), "fallbacks": 0}
        self.skips = []
        pinelive._G["dj_skip"] = lambda: self.skips.append(1)

    def tearDown(self):
        pinelive._G.clear()
        pinelive._G.update(self._saved)
        self.td.cleanup()

    def _radio(self, played, seconds=240.0, queue=None):
        radio = {"now": {"id": "r1", "title": "Song", "artist": "A", "seconds": seconds},
                 "started": time.time() - played,
                 "queue": list(queue if queue is not None else [{"id": "r2"}])}
        pinelive._G["_RADIO"] = radio
        return radio

    def test_cut_record_comes_back_with_its_position(self):
        radio = self._radio(95.0)
        self.pl._take_air("test")
        head = radio["queue"][0]
        self.assertEqual(head["id"], "r1")
        self.assertAlmostEqual(head["resume_s"], 95.0, delta=1.0)
        self.assertEqual(radio["queue"][1]["id"], "r2")
        self.assertNotIn("resume_s", radio["now"])       # a copy, not the deck's dict
        self.assertTrue(radio["fast_skip"])
        self.assertEqual(self.skips, [1])
        self.assertEqual(self.pl.held_record["id"], "r1")

    def test_never_twice_in_an_hour(self):
        radio = self._radio(95.0)
        self.pl._take_air("first")
        radio["queue"].pop(0)                             # it aired again
        radio["started"] = time.time() - 30.0
        self.pl._take_air("second")
        self.assertEqual([r["id"] for r in radio["queue"]], ["r2"])
        self.assertIsNone(self.pl.held_record)

    def test_a_record_nearly_over_is_not_owed(self):
        radio = self._radio(225.0, seconds=240.0)
        self.pl._take_air("test")
        self.assertEqual([r["id"] for r in radio["queue"]], ["r2"])
        self.assertIsNone(self.pl.held_record)

    def test_barely_started_plays_from_the_top(self):
        radio = self._radio(1.0)
        self.pl._take_air("test")
        self.assertEqual(radio["queue"][0]["resume_s"], 0.0)

    def test_already_at_the_head_is_replaced_not_doubled(self):
        radio = self._radio(60.0, queue=[{"id": "r1", "title": "Song"}, {"id": "r2"}])
        self.pl._take_air("test")
        self.assertEqual([r["id"] for r in radio["queue"]], ["r1", "r2"])
        self.assertAlmostEqual(radio["queue"][0]["resume_s"], 60.0, delta=1.0)


class OnAirResume(unittest.TestCase):
    def test_resume_back_dates_started_once(self):
        ns = _dj_on_air_ns()
        track = {"id": "r1", "title": "Song", "seconds": 240, "resume_s": 95.0}
        t0 = time.time()
        ns["dj_on_air"](track)
        radio = ns["_RADIO"]
        self.assertAlmostEqual(t0 - radio["started"], 95.0, delta=1.0)
        self.assertNotIn("resume_s", track)
        self.assertEqual(track["resumed_from_s"], 95.0)
        # the same dict aired again later (a pause put it back) starts afresh
        ns["dj_on_air"](track)
        self.assertLess(time.time() - radio["started"], 1.0)
        self.assertNotIn("resumed_from_s", track)

    def test_a_resume_past_the_end_plays_from_the_top(self):
        ns = _dj_on_air_ns()
        track = {"id": "r1", "seconds": 100, "resume_s": 97.0}
        ns["dj_on_air"](track)
        self.assertLess(time.time() - ns["_RADIO"]["started"], 1.0)
        self.assertNotIn("resumed_from_s", track)

    def test_plain_record_untouched(self):
        ns = _dj_on_air_ns()
        track = {"id": "r1", "seconds": 100}
        ns["dj_on_air"](track)
        self.assertLess(time.time() - ns["_RADIO"]["started"], 1.0)
        self.assertEqual(set(track), {"id", "seconds"})

    def test_the_loop_waits_only_what_is_left(self):
        text = (HERE / "app.py").read_text(encoding="utf-8")
        self.assertIn('if track.get("resumed_from_s"):          # [plresume] what is left', text)
        self.assertIn('if spin_first or track.get("resumed_from_s"):   # [plresume]', text)
        self.assertIn('resume=bool(track.get("resumed_from_s")),   # [plresume]', text)


if __name__ == "__main__":
    unittest.main()
