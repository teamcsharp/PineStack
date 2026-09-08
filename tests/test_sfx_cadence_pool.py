import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


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
                    _SFX_CADENCE_STATUS=status,
                    dj_settings=mock.Mock(return_value={'sfx_drop_folders': ['samples_grabbed']}),
                    sfx_id=mock.Mock(side_effect=lambda p: p.name),
                    sfx_bans=mock.Mock(return_value={'banned.wav'}),
                    sfx_weights=mock.Mock(return_value={}),
                    sfx_cap_seconds=mock.Mock(return_value=4),
                    sfx_seconds=mock.Mock(side_effect=lambda p: 20 if p.name == 'long.wav' else 1)):
                self.assertEqual(app._sfx_cadence_pick(), paths[1])
                self.assertEqual(app._sfx_cadence_pick(), paths[0])

    def test_cold_or_broken_pool_does_not_walk_or_retry_without_a_bound(self):
        with mock.patch.multiple(app,
                SFX_ROOT=Path('/samples'), SFX_LOCAL_ROOT=Path('/local'),
                _SFX_POOL_CACHE=[Path('/samples/samples_grabbed') / f'{i}.wav' for i in range(1000)],
                _SFX_CADENCE_STATUS={'last_sample': ''},
                dj_settings=mock.Mock(return_value={'sfx_drop_folders': ['samples_grabbed']}),
                sfx_id=mock.Mock(side_effect=lambda p: p.name), sfx_bans=mock.Mock(return_value=set()),
                sfx_weights=mock.Mock(return_value={})), mock.patch.object(Path, 'is_file', return_value=False) as probe:
            self.assertIsNone(app._sfx_cadence_pick())
            self.assertEqual(probe.call_count, 64)


if __name__ == '__main__':
    unittest.main()
