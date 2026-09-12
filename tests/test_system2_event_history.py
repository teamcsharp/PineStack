"""Event deadlines, retained drafts, and production duration regressions."""
import json
import unittest
from unittest import mock

import test_system2_runtime as fixtures


class System2EventHistoryTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.System2RuntimeTests.setUp

    async def test_asap_event_can_finish_preparing_after_its_requested_scene_length(self):
        self.host.templates = [{'id': 'record', 'kind': 'record', 'minutes': 20}]
        event = self.runtime.queue_event({'kind': 'station_event', 'brief': 'A new message',
                                         'request_id': 'asap', 'seconds': 60})
        self.assertEqual(event['payload']['timing'], 'asap')
        self.assertEqual(event['deadline'], 10900)
        self.now += 120
        row = self.host.add('event-scene', kind='banter', system2_slot='event-' + event['id'] + ':scene')
        self.assertTrue(await self.runtime.dispatch())
        plan = self.runtime._event_plans[0]['slots'][0]
        self.assertEqual(plan['coverage_mode'], 'one_performance')
        self.assertEqual(plan['target_seconds'], 60)
        self.assertEqual(plan['ready_seconds'], 7)
        self.assertEqual(plan['debt_seconds'], 0)
        self.assertEqual(self.host.aired[0]['script'], row['script'])

    async def test_explicit_scheduled_event_keeps_its_hard_deadline(self):
        event = self.runtime.queue_event({'kind': 'station_event', 'brief': 'Scheduled message',
                                         'request_id': 'fixed', 'air_at': 10100, 'seconds': 60})
        self.assertEqual(event['payload']['timing'], 'scheduled')
        self.assertEqual(event['deadline'], 10160)
        self.now = 10161
        self.assertIsNone(self.runtime.store.claim_event('test', event_id=event['id']))

    async def test_long_retained_scene_is_preserved_and_a_shorter_scene_is_commissioned(self):
        row = self.host.add('oversized', ready=False, script='A: ' + 'long ' * 900 + '.')
        await self.runtime.prepare()
        self.host.larder_prepare.assert_not_awaited()
        self.host.prep_measure.assert_awaited_once()
        self.assertNotIn('system2_slot', row)
        self.assertIn(row, self.host.rows['news'])

    async def test_bound_drafts_and_full_source_evidence_survive_inventory_removal(self):
        row = self.host.add('draft', ready=False, system2_slot='hour-10000000:news-slot',
                            system2_source_evidence={'original': 'Full original source'},
                            system2_authoring_budget={'seconds': 70})
        state = await self.runtime.refresh()
        slot = state['hours'][0]['slots'][0]
        self.assertEqual(slot['allocations'], [])
        self.assertEqual(slot['drafts'][0]['script'], row['script'])
        self.assertEqual(slot['ready_seconds'], 0)
        self.assertEqual(self.runtime.scripts(state['hours'][0]['id'])['slots'][0]['drafts'][0]['id'], 'draft')
        self.runtime._candidates = []; self.runtime._plans = []
        self.runtime.store.sync_candidates([], replace=True)
        trace = self.runtime.trace('draft', '0')
        self.assertEqual(trace['source']['system2_source_evidence']['original'], 'Full original source')
        self.assertEqual(trace['source']['system2_authoring_budget']['seconds'], 70)

    async def test_resumed_banter_is_persisted_to_its_own_larder(self):
        self.host.templates = [{'id': 'banter', 'kind': 'banter', 'minutes': 3}]
        self.host._larder_save = mock.Mock()
        self.host.add('resumed', kind='banter', ready=False)
        await self.runtime.prepare()
        self.host._larder_save.assert_called_once()

    async def test_recap_begins_before_its_start_and_uses_only_observed_current_hour(self):
        self.host.templates = [{'id': 'record', 'kind': 'record', 'minutes': 3},
                               {'id': 'recap', 'kind': 'recap', 'minutes': 3}]
        self.host._RADIO['history'] = [{'title': 'Previous hour', 'at': 9900}, {'title': 'Current record', 'at': 10000}]
        self.host._RADIO['chat'] = [{'text': 'Unheard draft', 'air_at': 10000},
                                   {'text': 'Actually heard', 'air_at': 10000, 'aired': 'stream'},
                                   {'text': 'Old dialogue', 'air_at': 9000, 'aired': 'stream'}]
        self.host.dj_banter.side_effect = None
        await self.runtime.prepare()
        self.host.dj_banter.assert_awaited_once()
        snapshot = self.runtime._work['observed_hour']
        self.assertEqual([r['title'] for r in snapshot['records']], ['Current record'])
        self.assertEqual([r['text'] for r in snapshot['dialogue']], ['Actually heard'])
