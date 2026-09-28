import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


def quiet_memory(ring):
    """The cadence's memory, and only this test's.

    #1224 (0399ec0) moved "what went out last" from
    _SFX_CADENCE_STATUS["last_sample"] (still written, for readers) to the
    recency ring _RADIO["recent"]["sfx-cadence"], and #1225 loads that ring
    from the station's own book on disk (data/recent_picks.json) and writes
    it back every RECENT_SAVE_EVERY draws. Unpatched, this test drew against
    the LIVE station's memory - the seeded clip was never in it, so the
    first draw was a coin toss (it failed 3 runs in 6 on the same code) -
    and could have written its temp paths into the station's book."""
    return {"_RADIO": {"recent": {"sfx-cadence": list(ring)}},
            "_RECENT_LOADED": [True], "_RECENT_DIRTY": [0],
            "_recent_save": mock.Mock()}


class SfxCadencePoolTests(unittest.TestCase):
    def test_requested_drop_family_bans_duration_and_immediate_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grabbed = root / 'samples_grabbed'
            grabbed.mkdir()
            other = root / 'other'
            other.mkdir()
            paths = [grabbed / name for name in ['a.wav', 'b.wav', 'banned.wav', 'long.wav']]
            paths.append(other / 'elsewhere.wav')
            for path in paths:
                path.write_bytes(b'existing recorded media')
            status = {'last_sample': str(paths[0])}
            with mock.patch.multiple(app,
                    SFX_ROOT=root, SFX_LOCAL_ROOT=root / 'local', _SFX_POOL_CACHE=paths,
                    _SFX_CADENCE_STATUS=status, **quiet_memory([str(paths[0])]),
                    dj_settings=mock.Mock(return_value={'sfx_drop_folders': ['samples_grabbed']}),
                    sfx_id=mock.Mock(side_effect=lambda p: p.name),
                    sfx_bans=mock.Mock(return_value={'banned.wav'}),
                    sfx_weights=mock.Mock(return_value={}),
                    sfx_cap_seconds=mock.Mock(return_value=4),
                    sfx_seconds=mock.Mock(side_effect=lambda p: 20 if p.name == 'long.wav' else 1)):
                self.assertEqual(app._sfx_cadence_pick(), paths[1])
                self.assertEqual(app._sfx_cadence_pick(), paths[0])
                # [cadence-no-repeat] a family no bigger than the ring (24):
                # once a and b are both "recent" the draw is never the one
                # that just went out - and never long.wav, the one clip left
                # outside the ring, which no roll may air - so the two
                # alternate for as long as they last.
                drawn = [app._sfx_cadence_pick() for _ in range(8)]
                self.assertEqual(drawn, [paths[1], paths[0]] * 4)
                self.assertEqual(status['last_sample'], str(paths[0]))

    def test_cold_or_broken_pool_does_not_walk_or_retry_without_a_bound(self):
        with mock.patch.multiple(app,
                SFX_ROOT=Path('/samples'), SFX_LOCAL_ROOT=Path('/local'),
                _SFX_POOL_CACHE=[Path('/samples/samples_grabbed') / f'{i}.wav' for i in range(1000)],
                _SFX_CADENCE_STATUS={'last_sample': ''}, **quiet_memory([]),
                dj_settings=mock.Mock(return_value={'sfx_drop_folders': ['samples_grabbed']}),
                sfx_id=mock.Mock(side_effect=lambda p: p.name), sfx_bans=mock.Mock(return_value=set()),
                sfx_weights=mock.Mock(return_value={})), mock.patch.object(Path, 'is_file', return_value=False) as probe:
            self.assertIsNone(app._sfx_cadence_pick())
            self.assertEqual(probe.call_count, 64)


if __name__ == '__main__':
    unittest.main()
