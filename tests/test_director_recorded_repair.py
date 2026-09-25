import copy
import time
import unittest
from unittest import mock

import app


class DirectorRecordedRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = {'sid': 'banter-old', 'prep_kind': 'banter',
                       'script': 'A: The old opening.\nB: The old reply.',
                       'seconds': 10.0}
        self.original = copy.deepcopy(self.source)
        self.order = {'road': 'banter', 'candidate_id': 'banter-old',
                      'slot_id': 'future:banter', 'hour_id': 'future',
                      'revision': 1, 'signature': 'original-proof',
                      'row': self.source, 'seconds': 10.0,
                      'prompt': 'THE SUBJECT OF THIS CALL: The missing portrait.',
                      'failures': ['topic_continuity']}
        self.shelf = [self.source]
        self.runtime = mock.Mock()
        self.runtime.replace_future_allocation = mock.AsyncMock()
        self.runtime._rows = {}
        self.written = (
            'A: The missing portrait was found behind the studio wall and I remember '
            'the frame, the note, the color, and the person who hid it there.\n'
            'B: That portrait belongs to the caller, so we should name the discovery, '
            'ask how it vanished, and keep this whole conversation on that subject.')

    async def run_repair(self, *, recorded, review=True):
        async def prepare(draft):
            if recorded:
                draft.update(seconds=12.0, prepared=True, made=2, chunks=2)

        def preview(road, row):
            spoken = ' '.join(text for _, text in app.banter_turns(row['script']))
            return {'id': row['sid'], 'slot_id': self.order['slot_id'], 'kind': road,
                    'script': row['script'], 'ready': True, 'eligible': True,
                    'seconds': 12.0, 'audio_hashes': ['a' * 64],
                    'lines': [{'text': spoken if review else 'Different recorded words.',
                               'seconds': 12.0, 'audio_hash': 'a' * 64}]}
        self.runtime.candidate.side_effect = preview
        with (mock.patch.object(app, 'director_review_repair_valid', return_value=True),
              mock.patch.object(app, 'alt_window', return_value='quiet'),
              mock.patch.object(app, 'pantry_window', return_value='quiet'),
              mock.patch.object(app, 'prep_should_stop', return_value=False),
              mock.patch.object(app, 'dialogue_topic_review',
                                return_value={'checked': True, 'ok': True}),
              mock.patch.object(app, 'ask_model', new=mock.AsyncMock(return_value=self.written)),
              mock.patch.object(app, 'larder_prepare', new=mock.AsyncMock(side_effect=prepare)),
              mock.patch.object(app, 'dialogue_row_ready', return_value=recorded),
              mock.patch.object(app, 'pantry_order_quality_save'),
              mock.patch.object(app, '_system2', return_value=self.runtime),
              mock.patch.object(app, '_LARDER', self.shelf)):
            await app.director_review_repair('repair-test', self.order)

    async def test_failed_recording_keeps_original_take_and_never_swaps(self):
        await self.run_repair(recorded=False)
        self.assertEqual(self.source['script'], self.original['script'])
        self.assertEqual(self.shelf, [self.source])
        self.runtime.replace_future_allocation.assert_not_awaited()

    async def test_failed_recorded_review_keeps_original_take(self):
        await self.run_repair(recorded=True, review=False)
        self.assertEqual(self.source['script'], self.original['script'])
        self.assertEqual(self.shelf, [self.source])
        self.runtime.replace_future_allocation.assert_not_awaited()

    async def test_promotion_preserves_original_and_publishes_recorded_shadow(self):
        async def promote(*args):
            args[6]()

        self.runtime.replace_future_allocation.side_effect = promote
        await self.run_repair(recorded=True)
        self.runtime.replace_future_allocation.assert_awaited_once()
        self.assertEqual(self.source['script'], self.original['script'])
        self.assertEqual(len(self.shelf), 2)
        self.assertIs(self.shelf[0], self.source)
        self.assertNotEqual(self.shelf[1]['sid'], self.source['sid'])
        self.assertEqual(self.shelf[1]['script'], self.written)

    async def test_failed_promotion_withdraws_shadow_and_keeps_original(self):
        async def reject(*args):
            publish, withdraw = args[6:8]
            publish()
            withdraw()
            raise RuntimeError('slot changed')

        self.runtime.replace_future_allocation.side_effect = reject
        await self.run_repair(recorded=True)
        self.assertEqual(self.source['script'], self.original['script'])
        self.assertEqual(self.shelf, [self.source])

    async def test_only_future_bound_review_failure_is_commissioned(self):
        candidate = {'id': 'banter-old', 'kind': 'banter', 'signature': 'signed',
                     'script': 'A: The old opening.', 'seconds': 10.0,
                     'ready': True, 'eligible': True,
                     'lines': [{'text': 'The old opening.', 'seconds': 10.0,
                                'audio_hash': 'a' * 64}]}
        slot = {'id': 'future:banter', 'hour_id': 'future', 'revision': 1,
                'kind': 'banter', 'prompt': 'THE SUBJECT OF THIS CALL: The portrait.',
                'start': time.time() + 500, 'deadline': time.time() + 620,
                'allocations': [{'state': 'ready', 'candidate': candidate,
                                 'planned_start': time.time() + 500}]}
        self.runtime.enabled = True
        self.runtime._plans = [{'slots': [slot]}]
        self.runtime._rows = {'banter-old': ('banter', self.source)}
        with (mock.patch.object(app, '_system2', return_value=self.runtime),
              mock.patch.object(app, 'dialogue_row_ready', return_value=True),
              mock.patch.object(app, 'dialogue_topic_review',
                                return_value={'checked': True, 'ok': False})):
            found = app.director_review_repair_target()
            self.assertEqual(found['candidate_id'], 'banter-old')
            self.assertEqual(found['failures'], ['topic_continuity'])
            slot['start'] = time.time() + 80
            self.assertIsNone(app.director_review_repair_target())
