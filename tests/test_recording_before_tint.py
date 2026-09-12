"""A real keeper pass must reach accepted recordings behind blocked writing."""
import asyncio
from contextlib import ExitStack
import copy
import unittest
from unittest import mock

import app as station


class RecordingBeforeTintTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.shelf, self.larder = {}, []
        self.tint_gate = asyncio.Event()
        self.rendered = []
        self.visited = []

        async def blocked_tint(*args, **kwargs):
            await self.tint_gate.wait()
            return False

        async def stop_pass(*args, **kwargs):
            raise asyncio.CancelledError

        async def measure(kind, work):
            return await work

        replacements = {
            '_RADIO': {'on': True}, '_SHELF': self.shelf, '_LARDER': self.larder,
            '_PREP_DEADLINE': [0.0], '_PAUSE_FINISH_SAID': [station.time.time()],
            'pantry_burn': mock.Mock(), 'recast_sweep': mock.AsyncMock(),
            'pantry_window': mock.Mock(return_value='paused recording window'),
            'prepare_target_seconds': mock.Mock(return_value=3600),
            'prepared_seconds': mock.Mock(return_value=0),
            'calls_short': mock.Mock(return_value=False),
            'hour_short_kinds': mock.Mock(return_value=[]),
            'radio_paused': mock.Mock(return_value=True),
            '_pause_unfinished_rows': mock.Mock(return_value=0),
            'pantry_bytes': mock.Mock(return_value=0),
            'prep_room_left': mock.Mock(return_value=120),
            'committed_stock_ids': mock.Mock(side_effect=lambda **kwargs: {
                row['sid'] for rows in self.shelf.values() for row in rows} |
                {row['sid'] for row in self.larder}),
            'alt_sid': lambda kind, row: row['sid'],
            'dialogue_row_ready': mock.Mock(return_value=False),
            'dialogue_tint_required': mock.Mock(return_value=True),
            'tint_coverage_ready': mock.Mock(side_effect=lambda report: bool(report and report.get('ok'))),
            '_larder_current': mock.Mock(return_value=True),
            'larder_floor': mock.Mock(return_value=4),
            'pipeline_log': mock.Mock(),
            'ensure_shelf_row_tinted': mock.AsyncMock(side_effect=blocked_tint),
            'ensure_entry_tinted': mock.AsyncMock(side_effect=blocked_tint),
            'prep_render_line': mock.AsyncMock(side_effect=stop_pass),
            'recording_sitting': mock.AsyncMock(side_effect=stop_pass),
            'larder_prepare': mock.AsyncMock(side_effect=stop_pass),
            'prep_measure': mock.AsyncMock(side_effect=measure),
            'coord_order': mock.Mock(side_effect=asyncio.CancelledError),
            'ask_model': mock.AsyncMock(side_effect=AssertionError('No live writing in a recording test')),
            'voice_render_any': mock.AsyncMock(side_effect=AssertionError('No live TTS in a keeper test')),
            '_pantry_save': mock.Mock(), '_larder_save': mock.Mock(),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(station, name, value))

    def raw(self, sid, *, accepted=False, off_brief=False, technical=False):
        return {'sid': sid, 'text': 'Complete original read ' + sid + '.', 'voice': 'original-voice',
                'tint_ok': accepted, 'tint': {'ok': accepted, 'technical': technical},
                'off_brief': off_brief}

    def dialogue(self, sid, *, accepted=True, off_brief=False, technical=False):
        text = 'A: Complete first line.\nB: Complete second line.'
        return {'sid': sid, 'script': text, 'script_plain': text,
                'script_tinted': text if accepted else '', 'use': 'tinted',
                'tint': {'ok': accepted, 'technical': technical},
                'off_brief': off_brief}

    async def keeper_once(self):
        sleeps = 0
        async def sleep(delay):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError
        with mock.patch.object(station.asyncio, 'sleep', side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(station.pantry_keeper(), timeout=1)

    def assert_no_writing(self):
        station.ensure_shelf_row_tinted.assert_not_awaited()
        station.ensure_entry_tinted.assert_not_awaited()
        station.ask_model.assert_not_awaited()
        station.voice_render_any.assert_not_awaited()
        self.assertFalse(self.tint_gate.is_set())

    async def test_blocked_committed_ad_does_not_delay_accepted_gallery_and_manager_sitting(self):
        self.shelf['ad'] = [self.raw('waiting-ad')]
        gallery = self.dialogue('accepted-gallery')
        manager = self.dialogue('accepted-manager')
        self.shelf['gallery'] = [
            {'sid': 'off-brief-gallery', 'entry': self.dialogue('off-brief-gallery', off_brief=True)},
            {'sid': 'technical-gallery', 'entry': self.dialogue('technical-gallery', accepted=False, technical=True)},
            {'sid': gallery['sid'], 'entry': gallery},
        ]
        self.shelf['manager'] = [{'sid': manager['sid'], 'entry': manager}]
        before = copy.deepcopy(self.shelf)
        await self.keeper_once()
        station.recording_sitting.assert_awaited_once()
        entries, budget = station.recording_sitting.call_args.args
        self.assertEqual({entry['sid'] for entry in entries}, {'accepted-gallery', 'accepted-manager'})
        self.assertGreaterEqual(budget, 120)
        station.prep_render_line.assert_not_awaited()
        station.larder_prepare.assert_not_awaited()
        self.assertEqual(self.shelf, before)
        self.assert_no_writing()

    async def test_single_round_fallback_skips_unaccepted_and_off_brief_rows_before_recording(self):
        # 2026-09-10: this used `manager` for the unaccepted rows, and the
        # manager road is now on `crystal_tint_must_flow` - the operator's
        # rule that a memo from upstairs airs whether or not the crystal
        # reached it, because a tint hold on a road that runs twice an hour
        # is an off switch. The rule THIS test exists for - an untinted row
        # is not recorded - is unchanged for every road that is not exempt,
        # so it is asserted on one of those instead. The exemption has its
        # own test below.
        self.shelf['ad'] = [self.raw('waiting-ad')]
        selected = self.dialogue('accepted-gallery')
        self.shelf['news'] = [
            {'sid': 'waiting-news', 'entry': self.dialogue('waiting-news', accepted=False)},
            {'sid': 'off-brief-news', 'entry': self.dialogue('off-brief-news', off_brief=True)},
        ]
        self.shelf['gallery'] = [{'sid': selected['sid'], 'entry': selected}]
        await self.keeper_once()
        station.recording_sitting.assert_not_awaited()
        station.larder_prepare.assert_awaited_once_with(selected)
        self.assertEqual(station._PREP_DEADLINE[0], 0)
        self.assert_no_writing()

    async def test_must_flow_road_is_recorded_without_its_tint(self):
        """A memo from upstairs goes out whether or not the crystal landed.

        The operator, 2026-09-10: "messages from the manager have to go
        through. So it's nice if they were tinted, but if they aren't able
        to, they need to still go through." The pass is still wanted and
        still attempted; it simply stops being the reason the road is
        silent."""
        # Shaped like the accepted-rows test above: a sitting is convened
        # for the ready rows of the hour, and the question here is only
        # whether the UNTINTED memo is among them. On its own the memo
        # takes the single-round fallback, which is a different branch and
        # would answer a different question.
        self.shelf['ad'] = [self.raw('waiting-ad')]
        gallery = self.dialogue('accepted-gallery')
        memo = self.dialogue('untinted-manager', accepted=False)
        self.shelf['gallery'] = [{'sid': gallery['sid'], 'entry': gallery}]
        self.shelf['manager'] = [{'sid': memo['sid'], 'entry': memo}]
        await self.keeper_once()
        station.recording_sitting.assert_awaited_once()
        entries, _budget = station.recording_sitting.call_args.args
        self.assertIn('untinted-manager',
                      {entry['sid'] for entry in entries})
        self.assert_no_writing()

    async def test_must_flow_exemption_is_scoped_to_its_own_road(self):
        """The exemption is a list, not a hole. An untinted round on a road
        that is not on it still waits, which is what stops "the memo may
        go" quietly becoming "anything may go"."""
        self.assertTrue(station.tint_must_flow('manager'))
        for road in ('gallery', 'caller', 'news', 'banter'):
            self.assertFalse(station.tint_must_flow(road), road)

    async def test_banter_pass_reaches_accepted_round_after_blocked_and_off_brief_originals(self):
        self.shelf['ad'] = [self.raw('waiting-ad')]
        selected = self.dialogue('accepted-banter')
        self.larder.extend([self.dialogue('waiting-banter', accepted=False),
                            self.dialogue('off-brief-banter', off_brief=True), selected])
        await self.keeper_once()
        station.larder_prepare.assert_awaited_once_with(selected)
        station.prep_measure.assert_awaited_once()
        self.assertEqual(station.prep_measure.call_args.args[0], 'banter')
        self.assertEqual(station._PREP_DEADLINE[0], 0)
        self.assert_no_writing()

    async def test_raw_accepted_read_retains_exact_voice_and_words_after_blocked_rows(self):
        selected = self.raw('accepted-ad', accepted=True)
        self.shelf['ad'] = [self.raw('waiting-ad'), self.raw('technical-ad', technical=True),
                            self.raw('off-brief-ad', accepted=True, off_brief=True), selected]
        await self.keeper_once()
        station.prep_render_line.assert_awaited_once_with(
            selected['text'], 'dj', selected['voice'], kind='ad')
        station.recording_sitting.assert_not_awaited()
        station.larder_prepare.assert_not_awaited()
        self.assert_no_writing()


if __name__ == '__main__':
    unittest.main()
