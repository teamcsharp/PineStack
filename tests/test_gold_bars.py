"""Gold bars, spoken routing synonyms, and spelled-out numbers."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app

BAR = "Copper plate by midnight or the lights go dark, that's the spark."


class GoldBarTests(unittest.TestCase):
    def test_numbers_spelled_out_keep_the_numbers(self):
        source = "The 10 PM hour kicked off at 9:59 with a memo."
        bar = "Ten PM on that frequency / it kicked off at nine-fifty-nine with a memo, no delinquency."
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            report = app.tint_evaluate(source, bar, [], force=0.88, strict=False)
        self.assertTrue(report["semantic"]["entities"], report["semantic"])
        dropped = app.tint_evaluate(source, "That hour kicked off with a memo, no delinquency.", [], force=0.88, strict=False)
        self.assertFalse(dropped["semantic"]["entities"])

    def test_spoken_routing_knows_the_device_and_the_computer(self):
        got = app.parse_broadcast_command("broadcast to the nabu device")
        self.assertEqual(got["voice"], "nabu")
        got = app.parse_broadcast_command("send the broadcast to the application")
        self.assertEqual(got["voice"], "here")
        got = app.parse_broadcast_command("broadcast the station to my computer")
        self.assertEqual(got["music"], "here")
        got = app.parse_broadcast_command("switch the show to the speaker")
        self.assertEqual(got["voice"], "nabu")
        self.assertIsNone(app.parse_broadcast_command("play something by DOOM"))

    def test_a_rhymed_take_is_gold_and_fires_from_the_other_seat(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "media"
            media.mkdir()
            (media / "bar.wav").write_bytes(b"x")
            with (mock.patch.object(app, "GOLD_PATH", Path(tmp) / "gold.json"),
                  mock.patch.object(app, "_GOLD", {"loaded": False, "rows": []}),
                  mock.patch.object(app, "VOICE_MEDIA_DIR", media)):
                self.assertFalse(app.gold_note("dj", "A plain line with no rhyme in it at all.", "/voice/bar.wav", 3.0))
                self.assertTrue(app.gold_note("dj", BAR, "/voice/bar.wav", 3.0))
                self.assertTrue(app.gold_note("dj", BAR, "/voice/bar.wav", 3.0))   # upsert, no duplicate
                self.assertEqual(len(json.load(open(Path(tmp) / "gold.json"))), 1)
                self.assertIsNone(app.gold_pick(exclude_who="dj"))                # not the same seat
                row = app.gold_pick(exclude_who="cohost")
                self.assertEqual(row["text"], BAR)
                app.gold_fired(row)
                self.assertIsNone(app.gold_pick(exclude_who="cohost"))            # rests
                self.assertIn("bar.wav", app.gold_protected_files())

    def test_gold_rows_live_twice_as_long_and_come_round_twice_as_often(self):
        now = int(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "line_prints.json"
            path.write_text("[]")
            with (mock.patch.object(app, "LINE_PRINTS_PATH", path),
                  mock.patch.object(app, "_LINE_ROWS", {"at": -1, "rows": []}),
                  mock.patch.object(app, "repeat_window", return_value=4 * 3600.0),
                  mock.patch.object(app, "_repeat_flow_verdict", side_effect=lambda t, w, k, v, *a: v)):
                app.print_remember(BAR, "dj", "banter")
                app.print_remember("A plain line with no rhyme in it at all.", "dj", "banter")
                rows = app.line_prints()
                self.assertTrue(next(r for r in rows if "spark" in r["key"])["gold"])
                self.assertFalse(next(r for r in rows if "plain" in r["key"])["gold"])
                # three hours later: the gold bar is outside its (halved) window, the plain line is not
                for r in rows:
                    r["last"] = now - 3 * 3600
                app._prints_write(rows)
                self.assertFalse(app.air_repeat_check(BAR, "dj")["block"])
                self.assertTrue(app.air_repeat_check("A plain line with no rhyme in it at all.", "dj")["block"])
                # thirty hours later the plain row is gone from the ledger, the gold row remains
                for r in rows:
                    r["last"] = now - 30 * 3600
                app._prints_write(rows)
                kept = app.line_prints()
                self.assertEqual([bool(r.get("gold")) for r in kept], [True])


if __name__ == "__main__":
    unittest.main()
