import unittest
from unittest import mock

from fastapi import HTTPException

import app


class DirectorRetiredScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_sid_uses_latest_ledger_block_and_listener_receipts(self):
        sid = 'aired-gallery'
        written = [
            {'sid': sid, 'block': 4, 'ord': 0, 'line_id': 'old',
             'round': 'gallery', 'who': 'dj', 'kind': 'dialogue',
             'text': 'An earlier play.', 'seconds': 4},
            {'sid': sid, 'block': 5, 'ord': 1, 'line_id': 'published',
             'round': 'gallery', 'who': 'cohost', 'kind': 'dialogue',
             'text': 'Waiting to be heard.', 'seconds': 5},
            {'sid': sid, 'block': 5, 'ord': 0, 'line_id': 'heard',
             'round': 'gallery', 'who': 'dj', 'kind': 'dialogue',
             'text': 'Heard first.', 'seconds': 6},
            {'sid': sid, 'block': 5, 'ord': 2, 'line_id': 'withdrawn',
             'round': 'gallery', 'who': 'board', 'kind': 'sfx',
             'text': 'A cancelled sting.', 'seconds': 2},
        ]
        air = [
            {'sid': sid, 'id': 'heard', 'aired': 'stream', 'heard_ack_at': 100},
            {'sid': sid, 'id': 'published', 'aired': 'published'},
            {'sid': sid, 'id': 'withdrawn', 'aired': 'withdrawn'},
        ]
        with (mock.patch.object(app, 'director_resolve',
                                side_effect=HTTPException(404, 'retired')),
              mock.patch.object(app, 'script_ledger_rows', return_value=written),
              mock.patch.object(app, 'airlog_rows', return_value=air)):
            detail = await app.api_director_script(sid)
        self.assertTrue(detail['archived'])
        self.assertTrue(detail['read_only'])
        self.assertEqual(detail['source'], 'script-ledger')
        self.assertEqual(detail['block'], 5)
        self.assertEqual([turn['line'] for turn in detail['turns']],
                         ['heard', 'published', 'withdrawn'])
        self.assertEqual([turn['air_state'] for turn in detail['turns']],
                         ['heard', 'published', 'withdrawn'])
        self.assertEqual(detail['heard_lines'], 1)
        self.assertEqual(detail['seconds'], 13)

    async def test_missing_sid_still_returns_404(self):
        with (mock.patch.object(app, 'director_resolve',
                                side_effect=HTTPException(404, 'retired')),
              mock.patch.object(app, 'script_ledger_rows', return_value=[])):
            with self.assertRaises(HTTPException) as caught:
                await app.api_director_script('unknown')
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
