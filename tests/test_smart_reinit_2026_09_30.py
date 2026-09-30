"""[smart-reinit] the station's half of "Get the broadcast back".

Every silence the PineTab has actually had (measured 2026-09-30 or in the
notes) that the STATION can see must come out named, with the smallest cure,
and nothing the operator set may ever be offered as a silent fix."""
import json
import tempfile
import unittest
from pathlib import Path

import broadcast_doctor as bd

ROOT = Path(__file__).resolve().parents[1]


def snap(**over):
    base = {
        "on": True, "paused": False, "paused_for_s": 0.0, "playing": True,
        "music_here": True,
        "routing": {"music": "here", "voice": "here", "reply": "here"},
        "pulse": {"stalls": 0, "worst_s": 0.0, "stalling_now": False,
                  "reading": "steady"},
        "talk_quiet_s": 5.0, "rounds_ready": 240, "consumer_why": "",
        "listener": "pbtab", "device": "pinetab",
        "terminal": {"name": "PineTab", "play": True},
        "owner": "pbtab", "owner_what": "the PineTab", "hushed": False,
        "roster": [{"listener": "pbtab", "ids": ["pbtab"], "what": "the PineTab",
                    "device": "pinetab", "owns_air": True, "hushed": False}],
        "triage": {},
    }
    base.update(over)
    return base


def keys(found):
    return [f["key"] for f in found]


class StationFindings(unittest.TestCase):
    def test_healthy_station_names_nothing(self):
        self.assertEqual(bd.station_findings(snap()), [])

    def test_switched_off_and_paused_come_first_and_alone(self):
        got = bd.station_findings(snap(on=False, talk_quiet_s=900))
        self.assertEqual(keys(got), ["off_air"])
        self.assertEqual(got[0]["cure"], "onair")
        got = bd.station_findings(snap(paused=True, paused_for_s=600, talk_quiet_s=900))
        self.assertEqual(keys(got), ["paused"])
        self.assertEqual(got[0]["cure"], "onair")

    def test_boot_road_dj_silence_is_reported_in_plain_words(self):
        # measured 2026-09-30: ~4.5 min before the first line, 243 banked
        got = bd.station_findings(snap(talk_quiet_s=270, rounds_ready=243))
        self.assertEqual(keys(got), ["dj_silent"])
        self.assertIn("has not spoken for 4.5 min although 243 round(s) are ready",
                      got[0]["say"])
        # the cure is the owed-air road, not a reload or a restart
        self.assertEqual(got[0]["cure"], "stock")
        self.assertEqual(got[0]["where"], "station")

    def test_the_operators_answer_lowers_the_dj_threshold(self):
        self.assertEqual(bd.station_findings(snap(talk_quiet_s=60)), [])
        self.assertEqual(keys(bd.station_findings(snap(talk_quiet_s=60), "no_djs")),
                         ["dj_silent"])
        # "no music" is not a DJ fault
        self.assertEqual(bd.station_findings(snap(talk_quiet_s=900), "no_music"), [])

    def test_nothing_ready_asks_for_a_round(self):
        got = bd.station_findings(snap(talk_quiet_s=400, rounds_ready=0))
        self.assertEqual(keys(got), ["dj_nothing_ready"])
        self.assertEqual(got[0]["cure"], "bank")

    def test_another_owner_gags_this_tablet(self):
        got = bd.station_findings(snap(
            owner="desk1", owner_what="the Pine Box app",
            roster=[{"listener": "pbtab", "ids": ["pbtab"], "device": "pinetab"},
                    {"listener": "desk1", "ids": ["desk1", "desk2"], "device": "desktop",
                     "owns_air": True}]))
        self.assertEqual(keys(got), ["gagged"])
        self.assertEqual(got[0]["cure"], "solo")
        self.assertIn("the Pine Box app holds the air", got[0]["say"])

    def test_the_same_device_under_a_new_id_is_not_a_gag(self):
        got = bd.station_findings(snap(
            owner="pbold", listener="pbnew",
            roster=[{"listener": "pbnew", "ids": ["pbnew", "pbold"], "device": "pinetab"}]))
        self.assertEqual(got, [])

    def test_play_switch_off_is_offered_never_flipped(self):
        got = bd.station_findings(snap(terminal={"name": "PineTab", "play": False},
                                       owner="desk1"))
        self.assertEqual(keys(got), ["play_off"])
        self.assertTrue(got[0]["consent"])
        self.assertEqual(got[0]["where"], "you")
        got = bd.station_findings(snap(hushed=True))
        self.assertEqual(keys(got), ["hushed"])
        self.assertTrue(got[0]["consent"])

    def test_two_surfaces_and_no_owner_play_over_each_other(self):
        got = bd.station_findings(snap(owner="", roster=[
            {"listener": "pbtab", "ids": ["pbtab"], "device": "pinetab"},
            {"listener": "desk1", "ids": ["desk1"], "device": "desktop"}]))
        self.assertEqual(keys(got), ["overlap"])
        self.assertEqual(got[0]["cure"], "solo")

    def test_routing_is_reported_and_left_alone(self):
        got = bd.station_findings(snap(routing={"music": "box", "voice": "here"}))
        self.assertEqual(keys(got), ["music_routed_away"])
        self.assertEqual(got[0]["kind"], "note")
        self.assertEqual(got[0]["cure"], "")
        got = bd.station_findings(snap(routing={"music": "here", "voice": "box"}), "no_djs")
        self.assertEqual(keys(got), ["voice_routed_away"])
        self.assertEqual(got[0]["cure"], "")

    def test_a_stalling_loop_is_relieved(self):
        got = bd.station_findings(snap(pulse={"worst_s": 9.2, "stalls": 3,
                                              "reading": "3 stall(s)"}))
        self.assertEqual(keys(got), ["air_stalled"])
        self.assertEqual(got[0]["cure"], "relieve")

    def test_this_page_not_starting(self):
        got = bd.station_findings(snap(triage={"cause": "not_started", "why": "3 clips",
                                               "listener": ""}))
        self.assertEqual(keys(got), ["page_not_starting"])
        self.assertEqual(got[0]["cure"], "flush")
        got = bd.station_findings(snap(triage={"cause": "never_starts", "why": "x",
                                               "listener": "pbtab"}))
        self.assertEqual(got[0]["cure"], "reload_page")
        # another page's fault is not this one's
        self.assertEqual(bd.station_findings(snap(triage={
            "cause": "never_starts", "listener": "someone"})), [])

    def test_no_record_only_matters_when_music_is_missing(self):
        self.assertEqual(bd.station_findings(snap(playing=False)), [])
        self.assertEqual(keys(bd.station_findings(snap(playing=False), "no_music")),
                         ["no_record"])


class RunLog(unittest.TestCase):
    def test_rows_are_sanitised_and_repeats_count_runs(self):
        row = bd.log_row({"run": "r1", "step": 2, "hint": "No DJs",
                          "findings": ["dj_silent", ""], "cure": "stock",
                          "did": "asked", "answer": "yes", "junk": 1}, now=100.0)
        self.assertEqual(row["event"], "reinit")
        self.assertEqual(row["hint"], "no_djs")
        self.assertEqual(row["findings"], ["dj_silent"])
        self.assertEqual(row["answer"], "yes")
        self.assertNotIn("junk", row)
        self.assertEqual(bd.log_row({"answer": "rm -rf"})["answer"], "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "air_fixes.jsonl"
            lines = [
                {"at": 50.0, "event": "recovered", "after": "relieve"},
                bd.log_row({"run": "r1", "findings": ["dj_silent"]}, now=100.0),
                bd.log_row({"run": "r1", "findings": ["dj_silent"], "answer": "no_djs"}, now=110.0),
                bd.log_row({"run": "r2", "findings": ["dj_silent", "gagged"]}, now=200.0),
            ]
            path.write_text("".join(json.dumps(r) + "\n" for r in lines) + "not json\n",
                            encoding="utf-8")
            rows = bd.read_runs(path, since=0.0)
            self.assertEqual(len(rows), 3)
            self.assertEqual(bd.repeats(rows), {"dj_silent": 2, "gagged": 1})
            self.assertEqual(len(bd.read_runs(path, since=150.0)), 1)
            got = bd.summary(rows)
            self.assertEqual(got["runs"][0]["run"], "r2")
            self.assertEqual(got["runs"][1]["answer"], "no_djs")
        self.assertEqual(bd.read_runs(Path("/nonexistent/x.jsonl")), [])


class AppContract(unittest.TestCase):
    """The patch is on the file, and the ladder it sits behind is intact."""

    def test_routes_and_ladder(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        for route in ('@app.get("/api/broadcast/diagnose")',
                      '@app.post("/api/broadcast/reinit/log")',
                      '@app.get("/api/broadcast/reinit/log")',
                      '@app.post("/api/broadcast/fix/{step}")'):
            self.assertEqual(text.count(route), 1, route)
        for step in ("onair", "relieve", "floor", "flush", "drain", "stock",
                     "release", "reload_pages", "kiosk", "stream", "engines",
                     "deep", "steward", "disk", "restart", "bank", "handover"):
            self.assertTrue(('step == "%s"' % step) in text, step)


if __name__ == "__main__":
    unittest.main()
