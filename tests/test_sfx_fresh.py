"""#1062: the station notices new samples and plays them.

First sightings are written down across restarts, a recent arrival is
always in the pool, and half the draws go to what is fresh.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app


class SfxFreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "sfx_seen.json"
        self.stack = [
            mock.patch.object(app, "SFX_ARRIVALS_PATH", self.ledger),
            mock.patch.object(app, "_SFX_ARRIVALS", {"loaded": False, "rows": {}}),
        ]
        for p in self.stack:
            p.start()
            self.addCleanup(p.stop)

    def test_first_walk_is_not_a_pile_of_arrivals(self):
        self.assertEqual(app._sfx_arrivals_note({"/s/a.wav", "/s/b.wav"}), [])
        rows = json.loads(self.ledger.read_text())
        self.assertEqual(rows, {"/s/a.wav": 0.0, "/s/b.wav": 0.0})
        self.assertEqual(app.sfx_arrivals_recent(), [])

    def test_a_later_arrival_is_stamped_and_remembered_across_restarts(self):
        app._sfx_arrivals_note({"/s/a.wav", "/s/b.wav"})
        fresh = app._sfx_arrivals_note({"/s/a.wav", "/s/b.wav", "/s/c.wav"})
        self.assertEqual(fresh, ["/s/c.wav"])
        self.assertEqual(app.sfx_arrivals_recent(), ["/s/c.wav"])
        # A new process reads the same ledger.
        app._SFX_ARRIVALS.update({"loaded": False, "rows": {}})
        self.assertEqual(app.sfx_arrivals_recent(), ["/s/c.wav"])
        # A file that has gone leaves the ledger.
        app._sfx_arrivals_note({"/s/a.wav", "/s/c.wav"})
        self.assertNotIn("/s/b.wav", json.loads(self.ledger.read_text()))

    def test_fresh_means_never_played_or_recently_arrived(self):
        old_played = Path("/s/old.wav")
        old_quiet = Path("/s/quiet.wav")
        new_played = Path("/s/new.wav")
        app._sfx_arrivals_note({str(old_played), str(old_quiet)})
        app._sfx_arrivals_note({str(old_played), str(old_quiet), str(new_played)})
        plays = {app.sfx_id(old_played): {"plays": 4},
                 app.sfx_id(new_played): {"plays": 1}}
        with mock.patch.object(app, "sfx_plays", return_value=plays):
            fresh = app.sfx_fresh_paths([old_played, old_quiet, new_played])
        self.assertEqual(set(fresh), {old_quiet, new_played})

    def test_half_the_draws_go_to_the_fresh_sample(self):
        pool = [Path(f"/s/{n}.wav") for n in ("a", "b", "c", "d")]
        fresh = [pool[2]]
        settings = {**app.DEFAULT_DJ, "sfx": True, "sfx_rate": 1.0, "sfx_gap": 0}
        with (mock.patch.object(app, "dj_settings", return_value=settings),
              mock.patch.object(app, "_STING_AT", [0.0]),
              mock.patch.object(app, "_SFX_POOL_AT", [time.time()]),
              mock.patch.object(app, "_SFX_POOL_CACHE", list(pool)),
              mock.patch.object(app, "sfx_bans", return_value=set()),
              mock.patch.object(app, "sfx_weights", return_value={}),
              mock.patch.object(app, "sfx_fresh_paths", return_value=fresh),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.dict(app._RADIO, {"recent": {}}),
              mock.patch.object(app.random, "random", return_value=0.1)):
            self.assertEqual(app.sting_due(), pool[2])
        with (mock.patch.object(app, "dj_settings", return_value=settings),
              mock.patch.object(app, "_STING_AT", [0.0]),
              mock.patch.object(app, "_SFX_POOL_AT", [time.time()]),
              mock.patch.object(app, "_SFX_POOL_CACHE", list(pool)),
              mock.patch.object(app, "sfx_bans", return_value=set()),
              mock.patch.object(app, "sfx_weights", return_value={}),
              mock.patch.object(app, "sfx_fresh_paths", return_value=fresh),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.dict(app._RADIO, {"recent": {}}),
              mock.patch.object(app.random, "random", return_value=0.9)):
            # The other half of the draws is the ordinary rotation.
            self.assertIn(app.sting_due(), pool)

    def test_plays_ledger_is_parsed_once_per_change(self):
        path = Path(self.tmp.name) / "sfx_plays.json"
        path.write_text(json.dumps({"x": {"plays": 1}}))
        with (mock.patch.object(app, "SFX_PLAYS_PATH", path),
              mock.patch.object(app, "_SFX_PLAYS_MEMO", {"at": -1, "rows": {}}),
              mock.patch.object(app.json, "loads", wraps=json.loads) as loads):
            self.assertEqual(app.sfx_plays()["x"]["plays"], 1)
            app.sfx_plays()
            self.assertEqual(loads.call_count, 1)


if __name__ == "__main__":
    unittest.main()
