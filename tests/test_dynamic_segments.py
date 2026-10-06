import copy
import tempfile
import unittest
from pathlib import Path

import dynamic_segments as dynamic
import segment_prompts as prompts
from segment_contract import (build_segment_contract, evaluate_segment_contract,
                              book_time_bookends, preparation_tasks)


class PromptPairs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {name: getattr(prompts, name) for name in
                    ('_HOST', '_PATH', '_BOOK', '_READ', '_MEMO', '_RIDES', '_RECENT')}
        self.addCleanup(self.restore)
        prompts._HOST = {}
        prompts._PATH = Path(self.tmp.name) / 'segment_prompts.json'
        prompts._BOOK = {'kinds': {}, 'uses': [], 'at': 0.0}
        prompts._READ = [False]
        prompts._MEMO, prompts._RIDES, prompts._RECENT = {}, {}, []
        self.calls = []

        def expand(texts, *, kind, key, stamp):
            self.calls.append((list(texts), kind, key, stamp))
            values = {'book': 'The Actual Book', 'booksentence': 'One exact short sentence.',
                      'bookchapter': '7'}
            filled = []
            for text in texts:
                for token, value in values.items():
                    text = text.replace('{' + token + '}', value)
                filled.append(text)
            return {'texts': filled, 'source': {'book_id': 'actual', 'title': values['book']},
                    'rolls': [{'key': 'book.title', 'index': 2}],
                    'expanded': [{'cmd': 'book', 'doc': values['book'], 'head': values['book']}]}
        prompts.install({'expand_book_tokens': expand})

    def restore(self):
        for name, value in self.old.items():
            setattr(prompts, name, value)

    def test_pair_is_saved_recalled_patched_and_used_in_one_source_draw(self):
        saved = prompts.put_alternative('book_time', {'name': 'First', 'text': 'Discuss {book}.',
                'generation_prompt': 'Read chapter {bookchapter}: {booksentence}.'})
        view = prompts.dial_preview('book_time')
        self.assertEqual(view['generation_prompt'], 'Read chapter {bookchapter}: {booksentence}.')
        result = prompts.govern('book_time', 'shelf', 'book_time|slot|occurrence')
        self.assertIn('Discuss The Actual Book.', result)
        self.assertIn('GENERATION PROMPT:\nRead chapter 7: One exact short sentence..', result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.calls[0][0]), 2)
        self.assertTrue(self.calls[0][3])
        self.assertEqual(prompts.govern('book_time', 'shelf', 'book_time|slot|occurrence'), result)
        self.assertEqual(len(self.calls), 1, 'polling cannot reroll an occurrence')
        use = prompts.uses_for('book_time')[0]
        self.assertEqual(use['book_source']['book_id'], 'actual')
        self.assertEqual(use['book_rolls'][0]['key'], 'book.title')
        prompts.patch_alternative('book_time', saved['id'], {'generation_prompt': 'Changed {book}.'})
        changed = prompts.govern('book_time', 'shelf', 'book_time|slot|occurrence')
        self.assertIn('GENERATION PROMPT:\nChanged The Actual Book.', changed)
        self.assertEqual(len(self.calls), 2)
        prompts.read(fresh=True)
        self.assertEqual(prompts.entry_view('book_time')['alternatives'][0]['generation_prompt'], 'Changed {book}.')

    def test_previews_expand_both_fields_without_spending_or_writing(self):
        prompts.put_alternative('book_time', {'text': 'Discuss {book}.', 'generation_prompt': 'Quote {booksentence}.'})
        before = prompts.path().read_bytes()
        pair = prompts.expand_pair('Discuss {book}.', 'Quote {booksentence}.', 'book_time', key='preview')
        self.assertEqual(pair['source']['book_id'], 'actual')
        self.assertEqual(self.calls[0][3], False)
        self.assertEqual(prompts.path().read_bytes(), before)
        self.assertFalse(prompts._MEMO)
        prompts.expand('{book} {booksentence}', 'banter', stamp=False)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.calls[1][3])

    def test_generating_only_alternative_and_legacy_alternative_both_work(self):
        gen = prompts.put_alternative('one', {'generation_prompt': 'Write about {book}.'})
        self.assertEqual(gen['text'], '')
        self.assertIn('GENERATION PROMPT:', prompts.govern('one', '', 'one-key'))
        legacy = prompts.put_alternative('two', {'text': 'Plain old system prompt.'})
        self.assertEqual(legacy['generation_prompt'], '')
        self.assertEqual(prompts.govern('two', '', 'two-key'), 'Plain old system prompt.')

    def test_missing_or_bad_source_hook_preserves_the_operator_words(self):
        for fill in (None, lambda *_a, **_kw: None,
                     lambda *_a, **_kw: {'texts': []}):
            prompts.install({'expand_book_tokens': fill})
            pair = prompts.expand_pair('Typed {book}.', 'Typed {booksentence}.', 'book_time')
            self.assertEqual(pair['system_prompt'], 'Typed {book}.')
            self.assertEqual(pair['generation_prompt'], 'Typed {booksentence}.')

    def test_defaults_are_installed_once_and_never_overwrite_custom_alternatives(self):
        self.assertEqual(dynamic.ensure_defaults(prompts), ['book_time', 'sfx_supercut'])
        first = prompts.entry_view('book_time')['alternatives'][0]
        prompts.patch_alternative('book_time', first['id'], {'text': 'Custom words', 'generation_prompt': 'Custom generation'})
        self.assertEqual(dynamic.ensure_defaults(prompts), [])
        self.assertEqual(prompts.entry_view('book_time')['alternatives'][0]['text'], 'Custom words')
        self.assertIn('{book}', first['generation_prompt'])
        self.assertEqual(prompts.entry_view('book_time')['mode'], 'fixed:' + first['id'])


    def test_controls_are_bounded_saved_recalled_and_bound_to_the_chosen_occurrence(self):
        calls = []
        def fill(texts, *, kind, key, stamp, config):
            calls.append(config)
            return {"texts": texts, "source": {}, "rolls": []}
        prompts.install({"expand_book_tokens": fill})
        row = prompts.put_alternative('book_time', {'text': 'Discuss the source',
            'generation_prompt': 'Generate it', 'config': {'target_seconds': 450,
                'min_seconds': 300, 'max_seconds': 600, 'book_binding': 'A Specific Book',
                'starts_at_minutes': [15, 45, float('nan'), 60],
                'unique_book_each_segment': True, 'unsafe': {'nested': 'omitted'}}})
        expected = {'target_seconds': 450.0, 'min_seconds': 300.0, 'max_seconds': 600.0,
            'book_binding': 'A Specific Book', 'starts_at_minutes': [15.0, 45.0],
            'unique_book_each_segment': True}
        self.assertEqual(row['config'], expected)
        prompts.govern('book_time', '', 'actual-occurrence')
        self.assertEqual(calls, [expected])
        self.assertEqual(prompts.occurrence_view('book_time', 'actual-occurrence')['config'], expected)
        self.assertIsNone(prompts.occurrence_view('book_time', 'another-occurrence'))
        prompts.read(fresh=True)
        self.assertEqual(prompts.dial_preview('book_time')['config'], expected)
        prompts.put_alternative('book_time', {'id': row['id'], 'text': 'Legacy edit without controls'})
        current = prompts.entry_view('book_time')['alternatives'][0]
        self.assertEqual(current['config'], expected, 'an older editor cannot erase saved controls')
        self.assertEqual(current['generation_prompt'], 'Generate it')


class HourPlacement(unittest.TestCase):
    def slots(self):
        minutes = [4, 3, 3, 2, 3, 2, 4, 5, 2, 3, 4, 3, 2, 4, 3, 4, 3, 2, 3, 1]
        return [{'id': f'hour-{index + 1:02d}', 'kind': 'banter', 'label': f'Original {index}',
                 'minutes': mins, 'enabled': True, 'prompt_id': f'prompt-{index}',
                 'pinned_id': f'item-{index}', 'notes': 'operator note',
                 'flow': [{'type': 'scripted_line', 'text': 'Keep the exact source'}],
                 'track_id': 'track-one', 'custom': {'nested': [1, 2]}}
                for index, mins in enumerate(minutes)]

    def clock_rows(self, slots):
        cursor, result = 0, []
        for row in slots:
            if not row.get('enabled', True):
                continue
            result.append((cursor, row))
            cursor += row['minutes']
        return cursor, result

    def test_twice_hourly_books_and_hourly_supercut_preserve_hour_and_input(self):
        source = self.slots()
        before = copy.deepcopy(source)
        placed = dynamic.overlay_hour(source)
        minutes, clock = self.clock_rows(placed)
        self.assertAlmostEqual(minutes, 60)
        inserted = [(at, row['minutes'], row['kind']) for at, row in clock
                    if row['kind'] in dynamic.TEMPLATES]
        self.assertEqual(inserted, [(15, 7.5, 'book_time'), (45, 7.5, 'book_time'),
                                    (58, 1.25, 'sfx_supercut')])
        supercut = next(row for row in placed if row['kind'] == 'sfx_supercut')
        self.assertEqual(supercut['dynamic_config']['target_seconds'], 45)
        self.assertGreaterEqual(supercut['minutes'] * 60,
                                supercut['dynamic_config']['target_seconds'] + 30,
                                'the reusable default includes its dispatch reserve')
        self.assertEqual(source, before, 'no live schedule or input queue mutation')
        self.assertEqual(placed[0], source[0], 'untouched entries retain identity and metadata')
        remainders = [row for row in placed if row.get('source_slot_id') == 'hour-08']
        self.assertEqual(len(remainders), 1)
        for key in ('prompt_id', 'pinned_id', 'notes', 'flow', 'track_id', 'custom'):
            self.assertEqual(remainders[0][key], source[7][key], key)
        self.assertNotEqual(remainders[0]['id'], 'hour-08')
        placed[0]['custom']['nested'].append(3)
        self.assertEqual(source, before, 'returned metadata is detached')

    def test_overlay_is_idempotent_and_config_is_detached(self):
        first = dynamic.overlay_hour(self.slots())
        self.assertEqual(dynamic.overlay_hour(first), first)
        book = next(row for row in first if row['kind'] == 'book_time')
        book['dynamic_config']['starts_at_minutes'].append(1)
        self.assertEqual(dynamic.template('book_time')['config']['starts_at_minutes'], [15, 45])

    def test_disabled_entries_do_not_consume_the_clock_and_keep_identity(self):
        rows = self.slots()
        disabled = {'id': 'off', 'enabled': False, 'kind': 'banter', 'minutes': 60, 'notes': 'keep this'}
        rows.insert(2, disabled)
        placed = dynamic.overlay_hour(rows)
        self.assertEqual(next(row for row in placed if row['id'] == 'off'), disabled)
        self.assertAlmostEqual(self.clock_rows(placed)[0], 60)

    def test_small_remainders_do_not_expand_the_hour_under_the_scheduler_floor(self):
        rows = [{'id': 'a', 'kind': 'banter', 'minutes': 14.9},
                {'id': 'b', 'kind': 'ad', 'minutes': .2},
                {'id': 'c', 'kind': 'banter', 'minutes': 44.9}]
        placed = dynamic.overlay_hour(rows)
        self.assertTrue(all(row['minutes'] >= .25 for row in placed))
        self.assertAlmostEqual(self.clock_rows(placed)[0], 60)

    def test_invalid_overlaps_or_partial_hour_are_rejected_without_changing_input(self):
        source = self.slots()
        before = copy.deepcopy(source)
        for windows in (((15, 10, 'book_time'), (20, 5, 'book_time')),
                        ((59, 3, 'book_time'),), ((15, 5, 'unknown'),)):
            with self.assertRaises(ValueError):
                dynamic.overlay_hour(source, windows)
        with self.assertRaises(ValueError):
            dynamic.overlay_hour(source[:2])
        self.assertEqual(source, before)


class DynamicReadiness(unittest.TestCase):
    def book_supply(self, contract):
        script = ("I am Caine and this is Dill. Welcome to Book Time on Pine Box FM. "
                  "Today we are reviewing The Actual Book, chapter seven. "
                  "Thanks for listening to Book Time on Pine Box FM. Back to the music.")
        evidence = book_time_bookends(script, title='The Actual Book', station='Pine Box FM')
        for side in evidence.values():
            side['recorded'] = side['written']
        return {'scripted_seconds': 450, 'recorded_seconds': 450,
                'playable_seconds': 450, 'roles': ['dj', 'cohost'],
                'turns': contract['minimum_turns'], 'events': contract['minimum_events'],
                'bookends': evidence}

    def test_full_book_segment_needs_actual_open_close_and_measured_duration(self):
        contract = build_segment_contract({'kind': 'book_time', 'road': 'banter', 'minutes': 7.5})
        self.assertEqual(contract['required_roles'], ['dj', 'cohost'])
        self.assertEqual(contract['minimum_turns'], 30)
        self.assertEqual(contract['minimum_events'], 5)
        self.assertEqual(contract['required_bookends'], ['intro', 'outro'])
        supply = self.book_supply(contract)
        self.assertTrue(evaluate_segment_contract(contract, [supply])['ready'])
        missing = evaluate_segment_contract(contract, [dict(supply, bookends={})])
        self.assertFalse(missing['ready'])
        self.assertEqual(missing['missing_bookends'], ['intro', 'outro'])
        thin = evaluate_segment_contract(contract, [dict(supply, body_frames=60_000,
            speech_frames=60_000, sample_rate=1000)])
        self.assertFalse(thin['ready'])
        self.assertGreater(thin['duration_short_seconds'], 380)
        no_take = copy.deepcopy(supply)
        no_take['bookends']['outro']['recorded'] = False
        pending = evaluate_segment_contract(contract, [no_take])
        self.assertEqual(pending['missing_recorded_bookends'], ['outro'])
        self.assertFalse(next(task for task in preparation_tasks(contract, pending)
                              if task['room'] == 'recording')['ready'])

    def test_phase_flags_or_generic_thanks_are_not_bookend_evidence(self):
        for text in ('opening=true closing=true phase=complete',
                     'We talked about The Actual Book on Pine Box FM. Thank you.',
                     'Welcome to Book Time on Pine Box FM. Thanks for Book Time, stay here.'):
            evidence = book_time_bookends(text, title='The Actual Book', station='Pine Box FM')
            self.assertFalse(evidence['outro']['written'])
        welcome = book_time_bookends('Welcome to Book Time on Pine Box FM. The Wrong Book.',
                                    title='The Actual Book', station='Pine Box FM')
        self.assertFalse(welcome['intro']['written'])

    def sfx_supply(self):
        return {'playable_seconds': 45, 'body_frames': 45000, 'sample_rate': 1000,
                'source_plan': {'complete': True, 'source_only': True,
                    'clips': [{'sid': 'source-1', 'from_s': 0, 'until_s': 1}],
                    'structure': {'opening': True, 'sell': True, 'closing': True,
                                  'station_identity_verified': True}}}

    def test_supercut_needs_verified_complete_sources_and_audio_not_voice_quota(self):
        contract = build_segment_contract({'kind': 'sfx_supercut', 'minutes': .75})
        self.assertEqual(contract['speech_seconds'], 0)
        self.assertEqual(contract['minimum_turns'], 0)
        self.assertEqual(contract['word_target'], 0)
        complete = evaluate_segment_contract(contract, [self.sfx_supply()])
        self.assertTrue(complete['ready'], complete)
        self.assertTrue(all(task['ready'] for task in preparation_tasks(contract, complete)))
        duration_only = evaluate_segment_contract(contract, [{'playable_seconds': 45}])
        self.assertFalse(duration_only['ready'])
        self.assertEqual(len(duration_only['missing_source_structure']), 4)
        short = self.sfx_supply()
        short['body_frames'] = 20000
        self.assertFalse(evaluate_segment_contract(contract, [short])['ready'])

    def test_supercut_cannot_join_flags_from_partial_plans_or_accept_missing_source_clips(self):
        contract = build_segment_contract({'kind': 'sfx_supercut', 'minutes': .75})
        missing = self.sfx_supply()
        missing['source_plan']['clips'] = []
        self.assertFalse(evaluate_segment_contract(contract, [missing])['ready'])
        opening, closing = self.sfx_supply(), self.sfx_supply()
        opening['source_plan']['structure']['closing'] = False
        closing['source_plan']['structure']['opening'] = False
        self.assertFalse(evaluate_segment_contract(contract, [opening, closing])['ready'])
        for key in ('complete', 'source_only'):
            bad = self.sfx_supply()
            bad['source_plan'][key] = False
            self.assertFalse(evaluate_segment_contract(contract, [bad])['ready'])


if __name__ == '__main__':
    unittest.main()
