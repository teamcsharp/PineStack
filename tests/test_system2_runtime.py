"""Real planner/adapter contracts with local media and isolated provider stubs."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

import httpx
from fastapi import FastAPI, HTTPException

import system2_runtime as adapter


class Host:
    def __init__(self, directory, now):
        self.DATA_DIR = Path(directory)
        self.VOICE_MEDIA_DIR = self.DATA_DIR / 'voice'
        self.VOICE_MEDIA_DIR.mkdir()
        self.PRODUCED_ADS_DIR = self.DATA_DIR / 'ads'
        self.PRODUCED_ADS_DIR.mkdir()
        self.now = now
        self._RADIO = {'on': True, 'history': [], 'chat': []}
        self._PANTRY = {}
        self._TRACK_TALK = {}
        self._READY_SHELF_BUSY = set()
        self.ALT_PREP_KINDS = ('news', 'caller', 'banter', 'gallery')
        self.NEWS_PREP_LIFE = 3600
        self.SCHED_PREP_KIND = {}
        self.SCHEDULE_KIND_NAMES = {}
        self.rows = {}
        self._LARDER = self.rows.setdefault('banter', [])
        self.paused = False
        self.templates = [{'id': 'news-slot', 'kind': 'news', 'minutes': 2}]
        self.pipeline_log = mock.Mock()
        self.prep_context_set = mock.Mock()
        self.prep_context_clear = mock.Mock()
        self.alt_brief_set = mock.Mock()
        self.alt_brief_clear = mock.Mock()
        self._pantry_save = mock.Mock()
        self._clip_seconds = mock.Mock(side_effect=self.clip_duration)
        self.larder_prepare = mock.AsyncMock(side_effect=self.finish)
        self.prep_measure = mock.AsyncMock(side_effect=self.measure)
        self._banter_air = mock.AsyncMock(side_effect=self.air)
        self.alt_prep_road = mock.Mock(side_effect=self.road)
        self.dj_banter = mock.AsyncMock(side_effect=AssertionError('Unexpected separate writer'))
        self._schedule_pin_record = mock.Mock()
        self.track_may_cut = mock.Mock(return_value=False)
        self.dj_skip = mock.Mock()
        self.read_guests = mock.Mock(return_value=[{'id': 'guest-one', 'name': 'Actual guest', 'voice': 'guest-voice'}])
        self.caller_line_voice = mock.AsyncMock(return_value='actual-caller-voice')
        self.music_track = mock.Mock(side_effect=lambda identity: {'id': identity, 'title': 'A library recording'} if identity == 'record-one' else None)
        self.now_really_playing = mock.Mock(return_value=True)
        self.track_talk_part_ready = lambda row: bool(row and row.get('ready'))
        self.dialogue_tint_required = lambda: True
        self.is_binned = lambda text: False
        self.station_name_scrub = lambda text: text
        self.pantry_key = lambda text, voice, engine: hashlib.sha256((text + voice + engine).encode()).hexdigest()
        self.aired = []

    def radio_paused(self): return self.paused
    def media_sign(self, name): return 'isolated-signature'
    def clip_duration(self, path):
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() / audio.getframerate()
    def alt_candidates(self, kind): return self.rows.setdefault(kind, [])
    def alt_sid(self, kind, row): return row['id']
    def dialogue_entry(self, row): return row.get('entry', row if row.get('script') else None)
    def dialogue_row_viable(self, kind, row): return self.dialogue_entry(row).get('viable', True)
    def dialogue_row_ready(self, kind, row): return self.dialogue_entry(row).get('ready', False)
    def dialogue_tint_ready(self, kind, row): return self.dialogue_entry(row).get('tint_ready', True)
    def tint_retry_due(self, entry, kind): return not entry.get('waiting')
    def _ready_round_takes(self, kind, row):
        entry = self.dialogue_entry(row)
        return copy.deepcopy(entry['takes']) if entry.get('ready') else []
    def banter_turns(self, script, *args): return [tuple(line.split(': ', 1)) for line in script.splitlines()]
    def schedule_read(self): return {'enabled': True}
    def _sched_hour_key(self, hour=None): return str(int(self.now() if hour is None else hour))
    def _sched_hour_epoch(self, key): return float(key)
    def schedule_hour_slots(self, settings, key): return ('configured', copy.deepcopy(self.templates), False)
    def schedule_prompt_for(self, settings, slot): return 'The exact configured source and topic.'
    def _schedule_clause(self, preset, slot, brief): return slot['id'] + ': ' + brief
    def shelf_put(self, kind, row): self.rows.setdefault(kind, []).append(row)

    def add(self, identity, kind='news', ready=True, **extra):
        takes = []
        for i, (who, seconds) in enumerate((('dj', 3), ('cohost', 4))):
            path = self.VOICE_MEDIA_DIR / (identity + '-' + str(i) + '.wav')
            sample = int(hashlib.sha256((identity + str(i)).encode()).hexdigest()[:4], 16) % 16000
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                output.writeframes(sample.to_bytes(2, 'little', signed=True) * (8000 * seconds))
            text = f'Exact {identity} words for {who}.'
            takes.append({'i': i, 'who': who, 'voice': 'voice-' + who, 'key': identity + str(i),
                          'text': text, 'clip': {'path': '/media/' + path.name, 'seconds': seconds}})
        script = '\n'.join(('A' if i == 0 else 'B') + ': ' + row['text'] for i, row in enumerate(takes))
        entry = {'id': identity, 'ready': ready, 'at': self.now(), 'script': script,
                 'script_plain': script, 'takes': takes, 'made': 2 if ready else 0, **extra}
        self.rows.setdefault(kind, []).append(entry)
        return entry

    def add_link(self, track_id, part, seconds=12):
        self.ALT_PREP_KINDS = tuple(dict.fromkeys(self.ALT_PREP_KINDS + ('track_talk',)))
        who = 'dj' if part == 'intro' else 'cohost'
        voice = 'exact-' + who
        text = 'Actual ' + track_id + ' ' + part + ' words.'
        name = track_id + '-' + part + '.wav'
        with wave.open(str(self.VOICE_MEDIA_DIR / name), 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes((37 if part == 'intro' else 91).to_bytes(2, 'little', signed=True) * int(seconds * 8000))
        key = self.pantry_key(text, voice, 'piper')
        self._PANTRY[key] = {'text': text, 'voice': voice, 'who': who, 'clip': {'path': '/media/' + name, 'seconds': 999}}
        row = {'text': text, 'voice': voice, 'who': who, 'key': key, 'ready': True, 'brief': {'ok': True}, 'at': self.now()}
        self._TRACK_TALK.setdefault(track_id, {'track': {'id': track_id}})[part] = row
        return row

    async def finish(self, entry):
        entry['ready'] = True
        return True

    async def measure(self, kind, work): return await work

    def road(self, kind):
        async def run():
            work = adapter.current_work()
            adapter.capture_model_request([{'role': 'user', 'content': self.alt_brief_set.call_args.args[0]}],
                                          {'temperature': .4}, 'fake-local-writer', response='Exact local response')
            self.add('new-' + kind, kind=kind, ready=False,
                     system2_trace_id=work['trace_id'], system2_job=work['job_id'], system2_slot=work['slot_id'])
            return True
        return run()

    async def air(self, entry, now, *, ready_takes, on_handoff, can_handoff):
        self.aired.append(copy.deepcopy(entry))
        if not can_handoff(): return False
        on_handoff()
        return True

    def require_read_auth(self, authorization):
        if authorization != 'Bearer isolated-test': raise HTTPException(401, 'Authentication required')
    require_auth = require_read_auth


class System2RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.now = 10000.0
        timer = mock.patch.object(adapter.time, 'time', side_effect=lambda: self.now)
        timer.start(); self.addCleanup(timer.stop)
        self.host = Host(self.temp.name, lambda: self.now)
        self.runtime = adapter.System2Runtime(self.host)
        self.runtime.store.now = lambda: self.now
        self.runtime.config.update(engine='system2', horizon_hours=1)

    async def test_actual_media_fingerprints_durations_order_and_binding_are_preserved(self):
        row = self.host.add('bound', system2_slot='hour-10000000:news-slot')
        result = self.runtime.candidate('news', row)
        self.assertTrue(result['ready'])
        self.assertEqual(result['seconds'], 7)
        self.assertEqual(result['slot_id'], row['system2_slot'])
        self.assertEqual([x['text'] for x in result['lines']], [x['text'] for x in row['takes']])
        self.assertEqual([x['voice'] for x in result['lines']], ['voice-dj', 'voice-cohost'])
        for line in result['lines']:
            expected = hashlib.sha256((self.host.VOICE_MEDIA_DIR / line['name']).read_bytes()).hexdigest()
            self.assertEqual(line['audio_hash'], expected)
        (self.host.VOICE_MEDIA_DIR / result['lines'][0]['name']).unlink()
        self.assertFalse(self.runtime.candidate('news', row)['ready'])

    async def test_unfinished_script_cannot_be_ready_from_cached_audio_or_unrelated_stock(self):
        self.host.add('news', ready=True)
        self.host.add('caller', kind='caller', ready=False)
        self.host.templates = [{'id': 'n', 'kind': 'news', 'minutes': 2},
                               {'id': 'c', 'kind': 'caller', 'minutes': 2}]
        status = await self.runtime.refresh()
        news, caller = status['hours'][0]['slots']
        self.assertGreater(news['ready_seconds'], 0)
        self.assertEqual(caller['ready_seconds'], 0)
        self.assertEqual(caller['debt_seconds'], 120)
        self.assertFalse(status['hours'][0]['all_segments_present'])

    async def test_disabled_or_off_station_cannot_prepare_or_dispatch(self):
        self.runtime.config['engine'] = 'legacy'
        await self.runtime.prepare()
        self.assertFalse(await self.runtime.dispatch())
        self.runtime.config['engine'] = 'system2'
        self.host._RADIO['on'] = False
        await self.runtime.prepare()
        self.host.prep_measure.assert_not_awaited()
        self.host.larder_prepare.assert_not_awaited()
        self.host._banter_air.assert_not_awaited()

    async def test_paused_station_prepares_without_resuming_or_airing(self):
        self.host.paused = True
        self.host.add('retained', ready=False)
        await self.runtime.prepare()
        self.host.larder_prepare.assert_awaited_once()
        self.assertTrue(self.host.paused)
        self.assertFalse(await self.runtime.dispatch())
        self.host._banter_air.assert_not_awaited()

    async def test_retained_work_is_finished_before_new_generation_and_other_slot_is_skipped(self):
        wrong = self.host.add('wrong', ready=False, made=20, system2_slot='different-slot')
        waiting = self.host.add('waiting', ready=False, made=15, waiting=True)
        useful = self.host.add('useful', ready=False, made=1)
        await self.runtime.prepare()
        self.host.larder_prepare.assert_awaited_once_with(useful)
        self.host.alt_prep_road.assert_not_called()
        self.assertFalse(wrong['ready'])
        self.assertFalse(waiting['ready'])
        self.assertTrue(useful['ready'])
        self.assertIsNone(adapter.current_work())
        self.host.alt_brief_clear.assert_called_once()

    async def test_new_producer_coroutine_uses_actual_ledger_and_exact_slot_prompt(self):
        await self.runtime.prepare()
        self.host.prep_measure.assert_awaited_once()
        self.assertEqual(self.host.prep_measure.call_args.args[0], 'news')
        row = self.host.rows['news'][0]
        self.assertEqual(row['system2_slot'], 'hour-10000000:news-slot')
        self.assertFalse(row['ready'])
        self.assertEqual(self.runtime._work['state'], 'retained')
        saved = json.loads((self.host.DATA_DIR / 'system2-traces' / (row['system2_trace_id'] + '.json')).read_text())
        self.assertEqual(saved['calls'][0]['model'], 'fake-local-writer')
        self.assertIn('The exact configured source and topic.', saved['calls'][0]['messages'][0]['content'])
        self.assertEqual(saved['calls'][0]['response'], 'Exact local response')
        self.assertIsNone(adapter.current_work())

    async def test_concurrent_prepare_has_one_owner_and_one_provider_visit(self):
        row = self.host.add('held', ready=False)
        started = asyncio.Event(); finish = asyncio.Event()
        async def pending(entry):
            started.set(); await finish.wait(); entry['ready'] = True; return True
        self.host.larder_prepare.side_effect = pending
        first = asyncio.create_task(self.runtime.prepare())
        await asyncio.wait_for(started.wait(), 3)
        await self.runtime.prepare()
        self.host.larder_prepare.assert_awaited_once_with(row)
        finish.set(); await first

    async def test_publication_is_not_heard_and_duplicate_complete_ack_is_idempotent(self):
        row = self.host.add('ready')
        self.assertTrue(await self.runtime.dispatch())
        entry = self.host.aired[0]
        proof = entry['_system2']
        reserved = self.runtime.store.get_reservation(proof['reservation_id'])
        self.assertEqual(reserved['state'], 'playing')
        self.assertEqual(reserved['heard_seconds'], 0)
        self.assertNotIn('aired', row)
        self.now += 7
        self.runtime.acknowledge(entry)
        self.runtime.acknowledge(entry)
        self.assertEqual(row['aired'], 1)
        self.assertEqual(self.runtime.store.get_reservation(proof['reservation_id'])['heard_seconds'], 7)
        self.assertFalse(self.runtime.store.can_play([row['takes'][0]['text']])['allowed'])
        self.assertFalse(await self.runtime.dispatch())

    async def test_late_policy_withdrawal_never_publishes_or_consumes_the_ready_row(self):
        row = self.host.add('withdrawn')
        async def withdrawn(entry, now, *, ready_takes, on_handoff, can_handoff):
            row['ready'] = False
            self.assertFalse(can_handoff())
            return False
        self.host._banter_air.side_effect = withdrawn
        self.assertFalse(await self.runtime.dispatch())
        self.assertNotIn('aired', row)
        self.assertEqual(self.runtime.store.reservations()[0]['state'], 'released')
        self.assertEqual(self.host._READY_SHELF_BUSY, set())

    async def test_transient_unpublished_failure_can_get_a_new_dispatch_intent(self):
        row = self.host.add('retry')
        self.host._banter_air.side_effect = mock.AsyncMock(return_value=False)
        self.assertFalse(await self.runtime.dispatch())
        self.host._banter_air.side_effect = self.host.air
        self.assertTrue(await self.runtime.dispatch())
        states = [x['state'] for x in self.runtime.store.reservations()]
        self.assertEqual(sorted(states), ['playing', 'released'])
        self.assertNotIn('aired', row)

    async def test_cancelled_preparation_preserves_entry_and_releases_job_for_retry(self):
        row = self.host.add('cancel', ready=False)
        started = asyncio.Event()
        async def pending(entry):
            started.set(); await asyncio.Event().wait()
        self.host.larder_prepare.side_effect = pending
        running = asyncio.create_task(self.runtime.prepare())
        await asyncio.wait_for(started.wait(), 3); running.cancel()
        with self.assertRaises(asyncio.CancelledError): await running
        self.assertIn(row, self.host.rows['news'])
        self.assertFalse(row['ready'])
        self.assertIsNone(adapter.current_work())
        self.assertNotEqual(self.runtime.store.jobs()[0]['state'], 'working')

    async def test_new_work_does_not_claim_concurrent_unrelated_producer_entry(self):
        ordinary = self.host.road
        async def measured(kind, work):
            self.host.add('unrelated', kind=kind, ready=False)
            return await work
        self.host.prep_measure.side_effect = measured
        await self.runtime.prepare()
        unrelated = next(row for row in self.host.rows['news'] if row['id'] == 'unrelated')
        self.assertNotIn('system2_slot', unrelated)
        self.assertNotIn('system2_trace_id', unrelated)
        self.assertEqual(self.runtime._work['candidate_ids'], ['new-news'])

    async def test_retried_default_event_is_same_intent_and_music_queue_is_not_heard(self):
        payload = {'kind': 'music_request', 'request_id': 'stable-request', 'track_id': 'record-one'}
        original = self.runtime.queue_event(payload)
        self.now += 1
        repeated = self.runtime.queue_event(payload)
        self.assertEqual(repeated['id'], original['id'])
        self.assertEqual(repeated['payload']['air_at'], original['payload']['air_at'])
        await self.runtime.events_tick()
        await self.runtime.events_tick()
        event = self.runtime.store.get_event(original['id'])
        self.assertTrue(event['result']['queued'])
        self.assertFalse(event['result']['heard'])
        self.assertEqual(len(self.host._RADIO['requests']), 1)
        self.host._banter_air.assert_not_awaited()

    async def test_event_microplan_cannot_borrow_generic_ready_or_unfinished_caller(self):
        self.host.templates = [{'id': 'record', 'kind': 'record', 'minutes': 5}]
        generic = self.host.add('old-caller', kind='caller', ready=True)
        partial = self.host.add('old-partial-caller', kind='caller', ready=False)
        event = self.runtime.queue_event({'kind': 'call_in', 'request_id': 'fresh-call', 'caller_name': 'Named caller',
                                          'brief': 'Explain the newly requested purple bicycle', 'seconds': 60})
        await self.runtime.refresh()
        self.assertEqual(self.runtime._event_plans[0]['slots'][0]['allocations'], [])
        self.host.dj_banter.side_effect = None
        self.host.dj_banter.return_value = None
        await self.runtime.prepare()
        self.host.dj_banter.assert_awaited_once()
        kwargs = self.host.dj_banter.call_args.kwargs
        self.assertEqual(kwargs['caller_name'], 'Named caller')
        self.assertEqual(kwargs['caller_voice'], 'actual-caller-voice')
        self.assertIn('purple bicycle', kwargs['angle'])
        self.host.larder_prepare.assert_not_awaited()
        self.assertNotIn('system2_slot', partial)
        self.assertNotIn('system2_slot', generic)

    async def test_due_event_transient_no_handoff_releases_event_and_preserves_wallclock(self):
        self.host.templates = [{'id': 'record', 'kind': 'record', 'minutes': 5}]
        event = self.runtime.queue_event({'kind': 'call_in', 'request_id': 'dispatch-call', 'caller_name': 'Named caller',
                                          'brief': 'A specific scene', 'seconds': 60})
        binding = 'event-' + event['id'] + ':scene'
        self.host.add('actual-event', kind='caller', system2_slot=binding)
        self.host._banter_air.side_effect = mock.AsyncMock(return_value=False)
        self.assertFalse(await self.runtime.dispatch())
        released = self.runtime.store.get_event(event['id'])
        self.assertEqual(released['state'], 'pending')
        self.now += 3
        self.host._banter_air.side_effect = self.host.air
        self.assertTrue(await self.runtime.dispatch())
        played = self.host.aired[-1]
        self.assertEqual(played['_system2']['event_id'], event['id'])
        self.assertEqual(played['_ready_slot']['deadline'], 10900)
        self.now += 7
        self.runtime.acknowledge(played)
        self.assertTrue(self.runtime.store.get_event(event['id'])['result']['heard'])

    async def test_current_record_intro_uses_exact_saved_voice_and_only_actual_link_duration(self):
        self.host.templates = [{'id': 'track', 'kind': 'track_talk', 'minutes': 3}]
        self.host._RADIO.update(now={'id': 'record-one', 'seconds': 300}, started=9990)
        self.host.add_link('record-one', 'intro', seconds=12)
        self.host.add_link('wrong-record', 'intro', seconds=12)
        state = await self.runtime.refresh()
        slot = state['hours'][0]['slots'][0]
        self.assertEqual(slot['coverage_mode'], 'one_performance')
        self.assertEqual(slot['target_seconds'], 15)
        self.assertEqual(slot['ready_seconds'], 0)
        self.assertTrue(await self.runtime.dispatch())
        entry = self.host.aired[-1]
        self.assertEqual(entry['_system2_track_position']['track_id'], 'record-one')
        self.assertEqual(entry['_system2_track_position']['part'], 'intro')
        self.assertEqual(entry['_ready_slot']['deadline'], 10035)
        takes = self.host._banter_air.call_args.kwargs['ready_takes']
        self.assertEqual(takes[0]['voice'], 'exact-dj')
        self.assertEqual(takes[0]['seconds'], 12)
        self.assertIn('record-one', takes[0]['text'])
        self.host.prep_measure.assert_not_awaited()
        self.host.larder_prepare.assert_not_awaited()

    async def test_current_record_outro_and_late_identity_change_are_safe(self):
        self.host.templates = [{'id': 'track', 'kind': 'track_talk', 'minutes': 3}]
        self.host._RADIO.update(now={'id': 'record-one', 'seconds': 300}, started=9730)
        self.host.add_link('record-one', 'outro', seconds=12)
        async def swap(entry, now, *, ready_takes, on_handoff, can_handoff):
            self.assertEqual(entry['_system2_track_position']['part'], 'outro')
            self.assertEqual(ready_takes[0]['voice'], 'exact-cohost')
            self.host._RADIO['now'] = {'id': 'changed-record', 'seconds': 300}
            self.assertFalse(can_handoff())
            return False
        self.host._banter_air.side_effect = swap
        self.assertFalse(await self.runtime.dispatch())
        self.assertEqual(self.runtime.store.reservations()[0]['state'], 'released')
        self.assertEqual(self.runtime.store.reservations()[0]['heard_seconds'], 0)

    async def test_midtrack_stale_clock_or_whole_link_not_fitting_never_dispatches(self):
        self.host.templates = [{'id': 'track', 'kind': 'track_talk', 'minutes': 3}]
        self.host.add_link('record-one', 'intro', seconds=12)
        self.host.add_link('record-one', 'outro', seconds=12)
        for started in (9900, 9000, 10010, 9960, 9705):
            self.host._RADIO.update(now={'id': 'record-one', 'seconds': 300}, started=started)
            self.runtime._last_refresh = 0
            self.assertFalse(await self.runtime.dispatch(), str(started))
        self.host._RADIO['started'] = 9990
        self.host.now_really_playing.return_value = False
        self.assertFalse(await self.runtime.dispatch())
        self.host._banter_air.assert_not_awaited()

    async def test_authenticated_script_and_full_line_reads_do_not_execute_providers(self):
        row = self.host.add('retained')
        app = FastAPI()
        namespace = {key: getattr(self.host, key) for key in dir(self.host) if not key.startswith('__')}
        factory = adapter.install(app, namespace)
        runtime = factory(); runtime.store.now = lambda: self.now
        runtime.config.update(engine='legacy', horizon_hours=1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated') as client:
            self.assertEqual((await client.get('/api/system2/status')).status_code, 401)
            headers = {'Authorization': 'Bearer isolated-test'}
            state = await client.get('/api/system2/status', headers=headers)
            self.assertEqual(state.status_code, 200, state.text)
            hour = state.json()['hours'][0]['id']
            script = await client.get('/api/system2/script', params={'hour': hour}, headers=headers)
            self.assertEqual(script.status_code, 200, script.text)
            self.assertEqual(script.json()['slots'][0]['performances'][0]['script'], row['script'])
            line = await client.get('/api/system2/line', params={'candidate': 'retained', 'line': '0'}, headers=headers)
            self.assertEqual(line.status_code, 200, line.text)
            self.assertEqual(line.json()['lines'][0]['text'], row['takes'][0]['text'])
            self.assertIn('historical', line.json()['provenance'].lower())
        self.host.prep_measure.assert_not_awaited()
        self.host._banter_air.assert_not_awaited()


class System2ColdImportTests(unittest.TestCase):
    def test_actual_app_cold_import_registers_system2_routes_without_booting_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, SPARK_AGENT_DATA_DIR=directory)
            code = "import app; paths={r.path for r in app.app.routes}; assert '/api/system2/status' in paths; assert '/api/system2/line' in paths; print('system2 routes registered')"
            result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                    env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            self.assertIn('system2 routes registered', result.stdout)
