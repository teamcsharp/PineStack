"""The real legacy clock entry points must respect System2 ownership."""
import ast
import asyncio
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import system2_runtime as adapter
from test_system2_runtime import Host


def clock_functions(namespace):
    tree = ast.parse(Path('app.py').read_text('utf-8'))
    names = {'schedule_take', '_ready_slot_window', '_ready_round_fits'}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    # Synthesised nodes carry no source positions; compile() requires them.
    module = ast.fix_missing_locations(ast.Module(
        body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + body,
        type_ignores=[]))
    exec(compile(module, 'app.py', 'exec'), namespace)
    return namespace


class System2ClockTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = clock_functions({})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.now = 10000.0
        patch = mock.patch.object(adapter.time, 'time', side_effect=lambda: self.now)
        patch.start(); self.addCleanup(patch.stop)
        self.host = Host(self.temp.name, lambda: self.now)
        self.runtime = adapter.System2Runtime(self.host)
        self.runtime.store.now = lambda: self.now
        self.runtime.config.update(engine='system2', horizon_hours=1)
        self.host.templates = [{'id': 'n', 'kind': 'news', 'minutes': 2},
                               {'id': 'c', 'kind': 'caller', 'minutes': 1}]
        self.ns = self.functions
        self.ns.update(_system2=lambda: self.runtime, _RADIO=self.host._RADIO, time=time,
                       schedule_read=mock.Mock(return_value={'enabled': False}),
                       _sched_pos_restore=mock.Mock(side_effect=AssertionError('Legacy restore')),
                       _sched_pos_save=mock.Mock(side_effect=AssertionError('Legacy save')),
                       SCHED_PREP_KIND={}, _PAGE_AIR_UNTIL=[0], _BOX_DOWN={}, _BOX_HOLD=[],
                       VOICE_BROADCAST_LEAD_MS=0, page_carries_live=lambda *args: False)

    async def test_poll_uses_wall_clock_and_never_legacy_position_or_alias(self):
        await self.runtime.refresh()
        self.host._RADIO['sched_pos'] = {'preset': 'old', 'started': 9000}
        for offset in (0, 15, 119):
            self.now = 10000 + offset
            slot = self.ns['schedule_take']()
            self.assertEqual((slot['id'], slot['kind']), ('n', 'news'))
            self.assertEqual(self.host._RADIO['sched_pos']['started'], 10000)
            self.assertEqual(self.ns['_ready_slot_window']('news')['deadline'], 10120)
        self.now = 10120
        slot = self.ns['schedule_take']()
        self.assertEqual((slot['id'], slot['kind']), ('c', 'caller'))
        self.assertEqual(self.host._RADIO['sched_pos']['occurrence'], 'hour-10000000:c')
        self.ns['schedule_read'].assert_not_called()
        self.ns['_sched_pos_save'].assert_not_called()
        self.ns['_sched_pos_restore'].assert_not_called()

    async def test_empty_or_expired_system2_plan_is_blocked_without_legacy_fallback(self):
        self.assertEqual(self.ns['schedule_take'](), {})
        self.assertEqual(self.ns['_ready_slot_window']('news')['deadline'], 0)
        await self.runtime.refresh()
        self.now = 10180
        self.assertEqual(self.ns['schedule_take'](), {})
        self.assertEqual(self.host._RADIO['sched_slot'], {})
        self.assertFalse(self.ns['_ready_round_fits']('news', [{}], seconds=1))

    async def test_due_event_needs_owned_performance_and_uses_canonical_kind(self):
        event = self.runtime.queue_event({'kind': 'call_in', 'request_id': 'clock-event',
                                          'brief': 'An actual caller question', 'seconds': 30})
        await self.runtime.refresh(force=True)
        slot = self.runtime._event_plans[0]['slots'][0]
        self.host.add('event-call', kind='caller', system2_slot=slot['id'])
        await self.runtime.refresh(force=True)
        slot = self.runtime._event_plans[0]['slots'][0]
        self.assertEqual(self.ns['schedule_take']()['kind'], 'news')
        reservation = self.runtime.store.reserve(slot['id'], 'event-call', 'system2-air')
        claimed = self.runtime.store.claim_event('system2-air', event_id=event['id'])
        expected = {'occurrence': slot['id'], 'slot_id': 'scene', 'kind': 'caller', 'deadline': 10900.0}
        current = self.ns['schedule_take']()
        self.assertEqual(current['kind'], 'caller')
        self.assertEqual(current['slot_kind'], 'call_in')
        self.assertEqual(self.ns['_ready_slot_window']('caller'), expected)
        self.assertTrue(self.ns['_ready_round_fits']('caller', [{}], expected, seconds=7))
        self.runtime.store.mark_dispatched(reservation['id'], 'system2-air')
        self.assertEqual(self.ns['schedule_take']()['occurrence'], slot['id'])
        self.runtime.store.release(reservation['id'], 'system2-air', reason='Known refused handoff')
        self.runtime.store.release_event(event['id'], 'system2-air', claimed['token'], reason='Refused')
        self.assertEqual(self.ns['schedule_take']()['kind'], 'news')
        self.assertFalse(self.ns['_ready_round_fits']('caller', [{}], expected, seconds=7))

    async def test_explicit_shorter_record_window_and_occurrence_replacement_still_refuse(self):
        await self.runtime.refresh()
        window = self.ns['_ready_slot_window']('news')
        window['deadline'] = self.now + 9
        self.assertTrue(self.ns['_ready_round_fits']('news', [{}], window, seconds=7))
        self.assertFalse(self.ns['_ready_round_fits']('news', [{}], window, seconds=9))
        self.now = 10120
        self.assertFalse(self.ns['_ready_round_fits']('news', [{}], window, seconds=1))

    def test_legacy_mode_keeps_existing_disabled_schedule_behavior(self):
        self.runtime.config['engine'] = 'legacy'
        self.host._RADIO['sched_pos'] = {'started': 9000}
        self.assertEqual(self.ns['schedule_take'](), {})
        self.ns['schedule_read'].assert_called_once()
        self.assertNotIn('sched_pos', self.host._RADIO)


if __name__ == '__main__':
    unittest.main()
