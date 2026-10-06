"""[supercut-fresh] 2026-10-06: supercut footage rests 48 hours; never-played, freshly studied clips first.

"I want the SFX guy using different clips each time... footage to have a 48 hour cooldown...
content that is being actively explored that has never gotten play... pushing further and
farther into the 300k clips."
"""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import sfx_supercut
import supercut_campaigns

COLUMNS = ("path", "sid", "name", "folder", "video", "bytes", "mtime", "seconds", "playable",
           "seen_at", "said", "said_at", "seen_desc", "seen_desc_at", "deck_cycle", "seen_frames")


def _book(rows):
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "sfx_clips.db"
    con = sqlite3.connect(path)
    con.execute("create table clips (%s)" % ", ".join(COLUMNS))
    for row in rows:
        full = {c: None for c in COLUMNS}
        full.update(row)
        con.execute("insert into clips (%s) values (%s)" % (", ".join(COLUMNS), ", ".join("?" for _ in COLUMNS)),
                    [full[c] for c in COLUMNS])
    con.commit()
    con.close()
    return path


def _clip(sid, said, **extra):
    row = {"path": "/samples/" + sid + ".mp4", "sid": sid, "name": sid + " clip", "folder": "f", "video": 1,
           "bytes": 1000, "mtime": time.time() - 9000, "seconds": 2.0, "playable": 1, "said": said}
    row.update(extra)
    return row


class TheScan(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.book = _book([
            _clip("ident001", "this is pine box fm the station", said_at=now - 30 * 86400),
            _clip("played01", "listen to the radio station music", said_at=now - 30 * 86400),
            _clip("fresh001", "listen to the radio station music", said_at=now - 3600),
            _clip("rested01", "listen to the radio station music", said_at=now - 3600),
            _clip("plain001", "listen to the radio station music", said_at=now - 30 * 86400),
        ])
        self.cfg = sfx_supercut.config({"station": "Pine Box FM", "item": "Pine Box FM"})

    def _scan(self, **kw):
        return sfx_supercut.scan_catalog(self.book, None, self.cfg, **kw)

    def test_resting_footage_is_left_out_and_counted_and_identities_never_rest(self):
        scan = self._scan(exclude={"rested01", "ident001"}, played={"played01"})
        sells = {row["sid"] for row in scan["roles"]["sell"]}
        self.assertNotIn("rested01", sells)
        self.assertEqual(scan["coverage"]["rested_sources"], 1)
        self.assertEqual([row["sid"] for row in scan["identities"]], ["ident001"], "the tag is never rested")
        self.assertEqual(scan["coverage"]["played_known"], 1)

    def test_never_played_freshly_studied_footage_wins(self):
        scan = self._scan(played={"played01"})
        score = {row["sid"]: row["score"] for row in scan["roles"]["sell"]}
        self.assertGreater(score["fresh001"], score["plain001"], "studied this week beats the rest")
        self.assertGreater(score["plain001"], score["played01"], "never played beats played")
        self.assertAlmostEqual(score["played01"] / score["plain001"], sfx_supercut.PLAYED_GAIN, places=3)
        self.assertAlmostEqual(score["fresh001"] / score["plain001"], sfx_supercut.FRESH_GAIN, places=3)
        why = next(row["why"] for row in scan["roles"]["sell"] if row["sid"] == "fresh001")
        self.assertEqual(why["fresh_gain"], sfx_supercut.FRESH_GAIN)
        self.assertGreaterEqual(scan["coverage"]["explored_recently"], 2)

    def test_the_cooldown_defaults_to_two_days(self):
        self.assertEqual(sfx_supercut.COOLDOWN_HOURS, 48.0)
        self.assertGreaterEqual(sfx_supercut.FRESH_DAYS, 1.0)


class TheCooldown(unittest.TestCase):
    def _runtime(self):
        data = Path(tempfile.mkdtemp())
        host = {"DATA_DIR": str(data), "SFX_ADS_DIR": str(data / "ads"), "_SFX_VIDEO_PLAYED": {"p1": 1.0, "p2": 2.0}}
        return sfx_supercut.SupercutRuntime(host), data

    def test_cooled_reads_the_archive_and_the_saved_plans_inside_the_window(self):
        runtime, data = self._runtime()
        now = time.time()
        with runtime.archive.connection() as con:
            con.execute("insert into archive (id, plan_id, created_at, product, station, audio_name, sha256, reusable_ad_id, metadata) values (?,?,?,?,?,?,?,?,?)",
                        ("sca-" + "a" * 24, "sc-" + "b" * 24, now - 3600, "p", "s", "a.wav", "x", "",
                         json.dumps({"cues": [{"sid": "arch_new"}], "source_plan": {"clips": [{"sid": "arch_plan"}]}})))
            con.execute("insert into archive (id, plan_id, created_at, product, station, audio_name, sha256, reusable_ad_id, metadata) values (?,?,?,?,?,?,?,?,?)",
                        ("sca-" + "c" * 24, "sc-" + "d" * 24, now - 80 * 3600, "p", "s", "b.wav", "y", "",
                         json.dumps({"cues": [{"sid": "arch_old"}]})))
        fresh_plan = runtime.root / ("sc-" + "e" * 24 + ".json")
        fresh_plan.write_text(json.dumps({"id": "sc-" + "e" * 24, "rendered_at": now - 600, "clips": [{"sid": "plan_new"}]}), encoding="utf-8")
        old_plan = runtime.root / ("sc-" + "f" * 24 + ".json")
        old_plan.write_text(json.dumps({"id": "sc-" + "f" * 24, "rendered_at": now - 80 * 3600, "clips": [{"sid": "plan_old"}]}), encoding="utf-8")
        got = runtime.cooled()
        self.assertEqual(got, {"arch_new", "arch_plan", "plan_new"})
        self.assertEqual(runtime.cooled(hours=100), {"arch_new", "arch_plan", "plan_new", "arch_old", "plan_old"})

    def test_the_note_names_the_rule_and_the_numbers(self):
        runtime, data = self._runtime()
        note = runtime.fresh_note()
        self.assertIn("48 hours", note)
        self.assertIn("never had play", note)
        self.assertIn("(2 have)", note)
        self.assertEqual(runtime.played_sids(), {"p1", "p2"})

    def test_the_writer_gets_the_note_and_the_host_offers_it(self):
        src = Path(supercut_campaigns.__file__).read_text(encoding="utf-8")
        self.assertIn('host.get("supercut_fresh_note")', src)
        src2 = Path(sfx_supercut.__file__).read_text(encoding="utf-8")
        self.assertIn('host["supercut_fresh_note"] = runtime.fresh_note', src2)
        self.assertIn("exclude=cooled, played=played", src2)
        self.assertIn('freshness["relaxed"] = True', src2)


if __name__ == "__main__":
    unittest.main()
