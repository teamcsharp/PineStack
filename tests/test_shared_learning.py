import ast
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import system3_learning as sl


def conversation(cid='c1', feature='combination', revision=1, operation='repair', category='closing'):
    return {'mode': 'active', 'config_hash': 'config1', 'inputs': {'road': 'dj_banter'},
            'identity': {'conversation_id': cid, 'revision': revision, 'script_digest': 'script'},
            'dialogue_recovery_variant': {'operation': operation, 'failure_feedback': {'category': category}},
            'turns': [{'turn_id': 't1', 'speaker': 'dj', 'text': 'Hello there.'},
                      {'turn_id': 't2', 'speaker': 'cohost', 'text': 'Back to the music.'}],
            'decision_events': [{'turn_id': 't1', 'family': 'FL', 'rng': {'u': .1},
                                 'meta': {'shared_learning': {'combination': feature}}},
                                {'turn_id': 't2', 'family': 'FL', 'rng': {'u': .2},
                                 'meta': {'shared_learning': {'combination': feature + 'close'}}}]}


def committed(conv):
    return [{'line_id': conv['identity']['conversation_id'] + t['turn_id'],
             'system3': {'conversation_id': conv['identity']['conversation_id'],
                         'turn_id': t['turn_id'], 'revision': conv['identity']['revision']},
             'who': t['speaker'], 'text': t['text']} for t in conv['turns']]


def receipt(rows):
    return [{'id': r['line_id'], 'from': 0, 'until': 10} for r in rows]


class SharedLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'learning.sqlite3'
        self.learner = sl.SharedDialogueLearning(self.path)
        self.learner.start()
        self.learner.flush()
        self.assertTrue(self.learner.ready)

    def tearDown(self):
        self.learner.close()
        self.tmp.cleanup()

    def prepare(self, conv=None):
        conv = conv or conversation()
        rows = committed(conv)
        self.learner.prepared(conv)
        self.learner.committed(rows)
        self.learner.flush()
        return rows

    def win(self, conv):
        rows = self.prepare(conv)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()

    def test_noncreative_and_unattributed_failures_do_not_blame_roulette(self):
        for i, category in enumerate(('source_identity', 'source_missing', 'turn_structure', 'service', 'other', 'coherence', 'budget')):
            for j in range(4):
                self.learner.failure(conversation(str(i) + ':' + str(j)), category)
        self.learner.flush()
        self.assertEqual(self.learner.snapshot('config1', 'dj_banter')['weights'], {})
        self.assertEqual(self.learner.status()['attributed_failures'], 0)
        self.assertEqual(sum(self.learner.status()['failures'].values()), 28)

    def test_independent_failures_adjust_only_targeted_combination(self):
        for i in range(2):
            self.learner.failure(conversation('c' + str(i)), 'coherence', ['t1'])
        self.learner.flush()
        self.assertEqual(self.learner.snapshot('config1', 'dj_banter')['weights'], {})
        self.learner.failure(conversation('c2'), 'coherence', ['t1'])
        self.learner.flush()
        self.assertEqual(self.learner.snapshot('config1', 'dj_banter')['weights'], {'combination': .5})
        self.assertEqual(self.learner.snapshot('different-config', 'dj_banter')['weights'], {})
        self.assertEqual(self.learner.snapshot('config1', 'caller')['weights'], {})

    def test_retries_categories_and_operations_cannot_multiply_node_votes(self):
        c = conversation()
        for i in range(25):
            c['identity']['revision'] = i + 1
            self.learner.failure(c, 'coherence', ['t1'], sl.OPERATIONS[i % 4])
            self.learner.failure(c, 'budget', ['t1'], sl.OPERATIONS[i % 4])
        self.learner.flush()
        self.assertEqual(self.learner.status()['attributed_failures'], 1)
        self.assertEqual(self.learner.snapshot('config1', 'dj_banter')['weights'], {})

    def test_exploration_floor_and_success_counter_evidence(self):
        for i in range(30):
            self.learner.failure(conversation('failure' + str(i)), 'closing')
        self.learner.flush()
        self.assertEqual(self.learner.snapshot('config1', 'dj_banter')['weights']['combinationclose'], .25)
        for i in range(6):
            self.win(conversation('success' + str(i)))
        self.assertGreater(self.learner.snapshot('config1', 'dj_banter')['weights']['combinationclose'], .25)
        self.assertLessEqual(self.learner.snapshot('config1', 'dj_banter')['weights']['combination'], sl.WEIGHT_CEILING)

    def test_prepared_committed_and_started_are_not_successes(self):
        rows = self.prepare()
        self.learner.playback(receipt(rows), 2, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)
        self.assertEqual(self.learner.status()['prepared'], 1)

    def test_all_required_turns_must_finish_and_duplicate_listeners_count_once(self):
        rows = self.prepare()
        self.learner.playback(receipt(rows[:1]), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)
        self.learner.playback(receipt(rows[1:]), 10, 0)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 1)

    def test_seek_or_missing_audible_interval_cannot_fabricate_completion(self):
        rows = self.prepare()
        self.learner.playback(receipt(rows), 2, 0)
        self.learner.playback(receipt(rows), 10, 9)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)
        self.learner.playback(receipt(rows), 9, 2)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 1)

    def test_wrong_copy_speaker_revision_and_unreviewed_rows_never_win(self):
        for index, field, value in ((0, 'text', 'Missing words.'), (1, 'who', 'caller'), (2, 'revision', 99)):
            c = conversation('bad' + str(index))
            rows = committed(c)
            if field == 'revision':
                rows[0]['system3']['revision'] = value
            else:
                rows[0][field] = value
            self.learner.prepared(c)
            self.learner.committed(rows)
            self.learner.playback(receipt(rows), 10, 0)
        rows = committed(conversation('unreviewed'))
        self.learner.committed(rows)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)

    def test_split_turn_requires_every_matching_chunk(self):
        c = conversation()
        rows = committed(c)
        first = rows.pop(0)
        rows = [dict(first, line_id='part1', text='Hello'), dict(first, line_id='part2', text='there.')] + rows
        self.learner.prepared(c)
        self.learner.committed(rows)
        self.learner.playback(receipt(rows[1:]), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)
        self.learner.playback(receipt(rows[:1]), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 1)

    def test_station_symbolic_seats_match_playback_roles(self):
        c = conversation()
        c['inputs']['roles'] = {'A': 'dj', 'B': 'cohost'}
        c['turns'][0]['speaker'] = 'A'
        c['turns'][1]['speaker'] = 'B'
        rows = committed(c)
        rows[0]['who'], rows[1]['who'] = 'dj', 'cohost'
        self.learner.prepared(c)
        self.learner.committed(rows)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 1)

    def test_a_later_draft_uses_failure_learning_in_the_real_wheel(self):
        import system3
        config = {'tables': [{'id': 'FL1', 'family': 'FL', 'weight': 1, 'categories': [
            {'id': 'plain', 'weight': 1, 'items': [{'id': 'a', 'weight': 1}, {'id': 'b', 'weight': 1}]}]}]}
        settings = system3.normalise_settings({})
        for i in range(3):
            c = system3.new_conversation({'road': 'banter'}, config, settings, seed=i + 1)
            c['mode'] = 'active'
            c['inputs']['shared_learning'] = self.learner.snapshot(c['config_hash'], 'banter')
            ctx = {'conv': c, 'turn_id': 't1', 'speaker': 'A', 'phase': 'opening', 'turns_left': 3}
            # A single eligible item makes the failed combination unambiguous.
            spec, event = system3.weighted_decision(c, config, ctx, system3.DrawStream('same'), 'FL')
            self.learner.failure(c, 'coherence', ['t1'])
            self.learner.flush()
        fresh = system3.new_conversation({'road': 'banter'}, config, settings, seed=99)
        fresh['inputs']['shared_learning'] = self.learner.snapshot(fresh['config_hash'], 'banter')
        ctx['conv'] = fresh
        _, next_event = system3.weighted_decision(fresh, config, ctx, system3.DrawStream('same'), 'FL')
        weights = {r['id']: r['weight'] for r in next_event['stages'][-1]['candidates']}
        self.assertEqual(weights[spec['id']], .5)
        self.assertEqual(weights['b' if spec['id'] == 'a' else 'a'], 1)

    def test_rejection_invalidates_prepared_receipts(self):
        c = conversation()
        rows = self.prepare(c)
        self.learner.failure(c, 'source_identity')
        self.learner.prepared(c)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)

    def test_new_revision_invalidates_old_audio(self):
        c = conversation()
        rows = self.prepare(c)
        newer = copy.deepcopy(c)
        newer['identity']['revision'] = 2
        self.learner.prepared(newer)
        self.learner.playback(receipt(rows), 10, 0)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 0)

    def test_restart_preserves_partial_coverage_and_dedup(self):
        rows = self.prepare()
        self.learner.playback(receipt(rows), 5, 0)
        self.learner.flush()
        self.learner.close()
        self.learner = sl.SharedDialogueLearning(self.path)
        self.learner.start()
        self.learner.flush()
        self.learner.playback(receipt(rows), 10, 5)
        self.learner.flush()
        self.assertEqual(self.learner.status()['audible_successes'], 1)
        self.win(conversation())
        self.assertEqual(self.learner.status()['audible_successes'], 1)

    def test_boot_and_callbacks_never_do_disk_work_on_caller(self):
        c = conversation()
        gate = threading.Event()
        self.learner._submit(lambda: gate.wait(timeout=5))
        started = time.monotonic()
        self.learner.failure(c, 'closing')
        self.learner.prepared(c)
        self.learner.committed(committed(c))
        self.learner.playback(receipt(committed(c)), 1, 0)
        self.learner.snapshot('config1', 'dj_banter')
        self.learner.status()
        elapsed = time.monotonic() - started
        gate.set()
        self.learner.flush()
        self.assertLess(elapsed, .15)

    def test_queue_pressure_drops_evidence_instead_of_blocking(self):
        other = sl.SharedDialogueLearning(Path(self.tmp.name) / 'bounded.sqlite3', max_pending=1)
        other.start()
        other.flush()
        gate = threading.Event()
        other._submit(lambda: gate.wait(timeout=5))
        self.assertFalse(other.failure(conversation(), 'closing'))
        self.assertEqual(other.status()['dropped'], 1)
        gate.set()
        other.flush()
        other.close()

    def test_shadow_and_off_cannot_train(self):
        for mode in ('shadow', 'off'):
            c = conversation(mode)
            c['mode'] = mode
            self.assertFalse(self.learner.failure(c, 'closing'))
            self.assertFalse(self.learner.prepared(c))

    def test_no_raw_dialogue_is_persisted(self):
        self.win(conversation())
        self.learner.flush()
        for path in Path(self.tmp.name).glob('learning.sqlite3*'):
            self.assertNotIn(b'Back to the music.', path.read_bytes())

    def test_recovery_strategy_learns_from_actual_delivery(self):
        self.assertIsNone(self.learner.preferred_operation('dj_banter', 'closing', 'new', 0))
        for i in range(5):
            self.learner.failure(conversation('bad' + str(i)), 'closing', operation='repair')
            self.win(conversation('good' + str(i), operation='reroll'))
        results = [self.learner.preferred_operation('dj_banter', 'closing', 'new' + str(i), 0) for i in range(100)]
        self.assertGreater(results.count('reroll'), 60)
        self.assertGreater(len(set(results)), 1)


class PlannerLearningTests(unittest.TestCase):
    def test_frozen_context_has_no_conversation_or_text_identity(self):
        c = conversation()
        c['decision_events'] = []
        ctx = {'turn_id': 't1', 'speaker': 'dj', 'phase': 'opening', 'closes': False}
        spec = {'table': 'FL1', 'category': 'plain', 'id': 'concise'}
        key = sl.combination(c, ctx, 'FL', spec)
        c['identity']['conversation_id'] = 'different'
        c['turns'][0]['text'] = 'Different topic, same plan.'
        self.assertEqual(key, sl.combination(c, ctx, 'FL', spec))
        c['inputs']['shared_learning'] = {'version': 1, 'revision': 3, 'config_hash': 'config1', 'weights': {key: .01}}
        self.assertEqual(sl.candidate_feedback(c, ctx, 'FL', spec)['multiplier'], .25)
        self.assertIsNone(sl.candidate_feedback(c, ctx, 'TOPIC', spec))

    def test_pure_draw_records_weight_evidence_and_pins_bypass_learning(self):
        import system3
        config = {'tables': [{'id': 'FL1', 'family': 'FL', 'weight': 1, 'categories': [
            {'id': 'plain', 'weight': 1, 'items': [{'id': 'a', 'weight': 1}, {'id': 'b', 'weight': 1}]}]}]}
        settings = system3.normalise_settings({})
        c = system3.new_conversation({'road': 'dj_banter'}, config, settings, seed=7)
        c['mode'] = 'active'
        ctx = {'conv': c, 'turn_id': 't1', 'speaker': 'A', 'phase': 'opening', 'controls': {},
               'turns_left': 3, 'availability': {}, 'prev_keys': set(), 'personalities': {}}
        spec = system3._spec(config['tables'][0], config['tables'][0]['categories'][0], {'id': 'a'})
        key = sl.combination(c, dict(ctx, closes=False), 'FL', spec)
        c['inputs']['shared_learning'] = {'version': 1, 'config_hash': c['config_hash'], 'revision': 9, 'weights': {key: .25}}
        stream = system3.DrawStream('test')
        _spec, event = system3.weighted_decision(c, config, ctx, stream, 'FL')
        candidates = event['stages'][-1]['candidates']
        self.assertEqual(next(r for r in candidates if r['id'] == 'a')['weight'], .25)
        self.assertIn('shared_learning', event['meta'])
        _spec, pinned = system3.weighted_decision(c, config, ctx, stream, 'FL', fixed='a')
        self.assertNotIn('shared_learning', pinned['meta'])
        self.assertIsNone(pinned['rng'])

    def test_seeded_replay_uses_frozen_learning_snapshot(self):
        import system3
        config = system3.default_config()
        settings = system3.normalise_settings({})
        inputs = {'road': 'banter', 'seats': ['A', 'B'], 'turns': 4,
            'subject': {'topic': 'the evening'}, 'availability': {},
            'shared_learning': {'version': 1, 'revision': 55, 'config_hash': system3.config_hash(config), 'weights': {}}}
        c = system3.new_conversation(inputs, config, settings, seed=18)
        system3.plan_more(c, config)
        keys = sl.turn_features(c)
        inputs['shared_learning']['weights'] = {k: .25 for k in keys.values()}
        c = system3.new_conversation(inputs, config, settings, seed=18)
        system3.plan_more(c, config)
        replayed = system3.replay(c, config)
        self.assertTrue(replayed.get('ok'), str(replayed)[:250])

    def test_air_hook_runs_before_first_hearing_dedup(self):
        source = Path(sl.__file__).with_name('app.py').read_text(encoding='utf-8')
        source = source[source.index('def _acknowledge_delivery_lines('):]
        source = source[:source.index('\n\ndef ', 1)]
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_acknowledge_delivery_lines')
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'learner']
        dedup = [n for n in ast.walk(node) if isinstance(n, ast.If) and '_PAGE_ACKED_LINES' in ast.unparse(n.test)]
        self.assertEqual(len(calls), 1)
        self.assertLess(calls[0].lineno, min(n.lineno for n in dedup))

    def test_runtime_freezes_inputs_only_when_the_plan_is_rebuilt(self):
        source = Path(sl.__file__).with_name('system3_runtime.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'System3Runtime')
        finalizer = next(n for n in cls.body if getattr(n, 'name', None) == '_finalize_handoff_recovery')
        guard = next(n for n in ast.walk(finalizer) if isinstance(n, ast.If)
                     and ast.unparse(n.test) == "attempt['operation'] == 'rebuild'")
        self.assertIn('_learning_inputs', ast.unparse(guard))
        for name in ('direct', 'direct_line'):
            node = next(n for n in cls.body if getattr(n, 'name', None) == name)
            self.assertIn('_learning_inputs', ast.unparse(node))

    def test_page_receipt_preserves_zero_and_clamps_forward_seeks(self):
        source = Path(sl.__file__).with_name('app.py').read_text(encoding='utf-8')
        source = source[source.index('def page_playback_ack('):]
        source = source[:source.index('\n\ndef ', 1)]
        node = ast.parse(source)
        assignment = next(n for n in ast.walk(node) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'learning_interval' for t in n.targets))
        code = compile(ast.fix_missing_locations(ast.Module(body=[assignment], type_ignores=[])), 'interval', 'exec')
        ns = {'previous': {'current_time': 0, 'at': 8}, 'position': 2, 'now': 10}
        exec(code, ns)
        self.assertEqual(ns['learning_interval'], 0)
        ns['position'] = 100
        exec(code, ns)
        self.assertEqual(ns['learning_interval'], 97)
        ns['previous'] = {}
        exec(code, ns)
        self.assertEqual(ns['learning_interval'], 100)


if __name__ == '__main__':
    unittest.main()
