"""A deliberate DJ destination wakes that speaker without resetting its dial."""
import asyncio
from contextlib import ExitStack
import unittest
from unittest import mock

import app


class NabuRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {'on': True, 'voice_to': 'box', 'voice_device': 'nabu',
                      'music_to': 'here', 'reply_to': 'here', 'box_talk': False,
                      'voice_clips': []}
        for key, value in {
            '_RADIO': self.radio, '_BOX_DOWN': {'until': 0, 'fails': 0},
            '_BOX_HOLD': [], '_BOX_ROUTE_WAKE_TASK': None,
            'require_auth': mock.Mock(), '_routing_save': mock.Mock(),
            '_operator_routing_stamp': mock.Mock(), 'pipeline_log': mock.Mock(),
            '_routing_voice_device_set': mock.Mock(), '_box_hold_save': mock.Mock(),
            'request_box_route_wake': mock.Mock(), 'dj_state': mock.Mock(return_value={}),
            'box_level_send': mock.AsyncMock(), 'radio_paused': mock.Mock(return_value=False),
            '_WIRE_LAST': {}, '_HOLD_DRAIN_LOCK': asyncio.Lock(),
            '_FLOOR_LOCK': asyncio.Lock(), '_FLOOR_OWNER': {'task': None, 'at': 0, 'label': ''},
        }.items():
            self.stack.enter_context(mock.patch.object(app, key, value))

    async def route(self, body):
        request = mock.Mock(headers={}, client=mock.Mock(host='test-client'))
        request.json = mock.AsyncMock(return_value=body)
        await app.dj_output_api(request, 'test')
        app.box_level_send.assert_not_awaited()

    async def test_selecting_same_nabu_route_enables_output_and_wakes_held_audio(self):
        await self.route({'voice': 'nabu'})
        self.assertTrue(self.radio['box_talk'])
        self.assertEqual(self.radio['voice_to'], 'box')
        app._routing_voice_device_set.assert_called_once_with('nabu')
        app.request_box_route_wake.assert_called_once()

    async def test_bare_device_label_on_dj_selector_uses_current_nabu(self):
        await self.route({'voice': 'box'})
        self.assertTrue(self.radio['box_talk'])
        self.assertEqual(self.radio['voice_device'], 'nabu')
        app.request_box_route_wake.assert_called_once()

    async def test_explicit_master_off_is_preserved(self):
        await self.route({'voice': 'nabu', 'box_talk': False})
        self.assertFalse(self.radio['box_talk'])

    async def test_automatic_restore_never_overrules_master_off(self):
        await self.route({'voice': 'box', 'system': True})
        self.assertFalse(self.radio['box_talk'])
        app.request_box_route_wake.assert_not_called()

    async def test_music_and_reply_routes_leave_dj_master_unchanged(self):
        await self.route({'music': 'here', 'reply': 'nabu'})
        self.assertFalse(self.radio['box_talk'])
        app.request_box_route_wake.assert_not_called()

    async def test_online_route_wakes_finished_shelf_and_keeps_failed_head(self):
        self.radio['box_talk'] = True
        head = {'id': 'owed', 'tries': 4, 'retry_after': 9999999999}
        app._BOX_HOLD.append(head)
        with (mock.patch.object(app, 'satellite_status', mock.AsyncMock(
                return_value={'online': True, 'reachable': True})),
              mock.patch.object(app, 'box_recently_verified', return_value=False),
              mock.patch.object(app, '_replay_held', mock.AsyncMock(return_value=False)) as replay,
              mock.patch.object(app, 'render_backlog_top')):
            await app.box_route_wake()
        replay.assert_awaited_once_with(head)
        self.assertEqual(app._BOX_HOLD, [head])
        self.assertEqual(head['tries'], 5)

    async def test_route_changed_while_waiting_for_floor_keeps_shelf_unplayed(self):
        self.radio['box_talk'] = True
        head = {'id': 'owed'}
        app._BOX_HOLD.append(head)
        await app._FLOOR_LOCK.acquire()
        with mock.patch.object(app, '_replay_held', mock.AsyncMock()) as replay:
            task = asyncio.create_task(app.box_hold_drain_one())
            await asyncio.sleep(0)
            self.radio['voice_to'] = 'here'
            app._FLOOR_LOCK.release()
            self.assertIsNone(await task)
            replay.assert_not_awaited()
        self.assertEqual(app._BOX_HOLD, [head])
        self.assertNotIn('tries', head)

    async def test_continuous_talk_watcher_joins_the_floor_queue_instead_of_starving(self):
        self.radio['box_talk'] = True
        app._BOX_HOLD.append({'id': 'owed'})
        with (mock.patch.object(app, '_box_hold_load'),
              mock.patch.object(app, 'satellite_busy', mock.AsyncMock(return_value=False)),
              mock.patch.object(app, 'satellite_ready', mock.AsyncMock(return_value=True)),
              mock.patch.object(app, '_floor_busy', return_value=True),
              mock.patch.object(app, 'box_hold_drain_one', mock.AsyncMock(return_value=None)) as drain,
              mock.patch.object(app.asyncio, 'sleep', mock.AsyncMock(
                  side_effect=[None, asyncio.CancelledError()]))):
            with self.assertRaises(asyncio.CancelledError):
                await app.box_hold_watch()
            drain.assert_awaited_once()


class WakeCoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_clicks_share_pending_wake_then_allow_a_new_one(self):
        finished = asyncio.Event()
        async def wake():
            await finished.wait()
        with (mock.patch.object(app, '_BOX_ROUTE_WAKE_TASK', None),
              mock.patch.object(app, 'box_route_wake', side_effect=wake) as call):
            app.request_box_route_wake()
            first = app._BOX_ROUTE_WAKE_TASK
            app.request_box_route_wake()
            self.assertIs(app._BOX_ROUTE_WAKE_TASK, first)
            finished.set()
            await first
            app.request_box_route_wake()
            await app._BOX_ROUTE_WAKE_TASK
            self.assertEqual(call.call_count, 2)


if __name__ == '__main__':
    unittest.main()
