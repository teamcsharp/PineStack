"""Book token integration at the final model/H3 doors; no model or playback."""
import asyncio
import copy
import re
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import book_prompt_runtime as R
import book_roulette as B
import h3_slots
import air_norepeat
import system3_runtime
import system3
import gazette_prompt
import tests.test_book_roulette as fixtures


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BookRouletteTests(); self.fixture.setUp()
        self.mode = self.fixture.mode
        self.calls = []; self.pools = []; self.notes = []; self.preparations = []; self.commits = []; self.hours = []
        self.desk = {}; self.direct_inputs = []
        async def original_direct(**ctx):
            self.direct_inputs.append(ctx)
            return dict(topic=str(ctx.get('angle') or '')[:400], inputs=ctx)
        self.g = {'re': re, 'asyncio': asyncio, 'BOOK_MODE': self.mode, 'dj_settings': lambda: {'station_name': 'Pine Garden FM'},
                  'system3_direct_banter': original_direct, 's3_weighted': self.pick, 's3_pool': self.pool, 'system3_pool_items': lambda key: self.desk.get(key),
                  '_h3_slot_note': lambda *args: self.notes.append(args)}
        def old_fill(template, quiet=False, **values):
            text = re.sub(r'\{([^{}|]+)\|([^{}]+)\}', lambda match: match[1], str(template))
            values.setdefault('station', 'Pine Garden FM'); values.setdefault('hour', '15:00')
            for key, value in values.items():
                text = text.replace('{' + key + '}', str(value or ''))
            return re.sub(r'\{[^{}]+\}', '', text)
        async def old_preroll(*texts):
            found = h3_slots.tokens(*texts)
            self.preparations.append(found)
            return {name: 'generic ' + name for name in found}
        def offloop(fn, *args):
            fn(*args)
        def commit(entry):
            self.commits.append(copy.deepcopy(entry))
        def hour(conversation, record='', speak=None):
            fields = self.fields
            entry = {'hour': 'h3-test', 'fields': dict(fields), 'goal': self.g['h3_speak_fill'](fields['goal']), 'conversation': conversation}
            self.hours.append(entry)
            self.g['_h3_prompts_offloop'](self.g['h3_prompts_commit_hour'], dict(entry))
            return entry
        def words(hour, road, speech=''):
            fields = hour['fields']
            return {'fields': dict(fields), 'direction': self.g['h3_speak_fill'](fields[road], goal=hour['goal']),
                    'speech': self.g['h3_speak_fill'](fields.get('speech') or speech),
                    'style': fields.get('style', ''), 'constraints': fields.get('constraints', ''), 'audio_direction': ''}
        self.g.update(h3_speak_fill=old_fill, h3_slots_preroll=old_preroll, _h3_prompts_offloop=offloop,
                      h3_prompts_commit_hour=commit, h3_prompts_hour=hour, h3_prompts_words=words,
                      h3_prompts_hour_for=lambda text: next((h for h in self.hours if str(text or '').endswith(h['goal'])), None))
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.g['_QUOTED_TITLE'] = re.compile(r'["“]([^"“”]{2,60})[”"]')
        self.g['s3_chance'] = lambda *args, **kwargs: False
        self.g.update(Any=object, NOREPEAT=air_norepeat.Book(self.fixture.root / 'norepeat.json'),
                      NOREPEAT_EXEMPT_KINDS=frozenset(), norepeat_on=lambda: True,
                      norepeat_refuse=lambda *args, **kwargs: {'why': 'heard inside the day'})
        self.g.update(gazette_prompt=gazette_prompt, _PB_OPEN='\ue000', _PB_MID='\ue001', _PB_CLOSE='\ue002',
                      _PB_TOKEN=re.compile('(\ue000[a-z0-9_]{1,40}\ue001|\ue002)'),
                      _PB_NAME=re.compile('\ue000([a-z0-9_]{1,40})\ue001'),
                      dialogue_tint_wanted=lambda: False,
                      pipeline_log=lambda *args: None, h3_slot_shelf=lambda name: {})
        for name in ('names_only', 'station_name_scrub', 'norepeat_line_gate', 'norepeat_text_used',
                     '_pb_unmark', 'prompt_blocks_resolve', 'gazette_prompt_messages'):
            start = source.index(('async def ' if name == 'gazette_prompt_messages' else 'def ') + name + '(')
            end = source.index('\n\n\n@_LAB_RUNTIME.model_call', start + 5) if name == 'gazette_prompt_messages' else source.index('\ndef ', start + 5)
            exec(compile(source[start:end], 'app.py', 'exec'), self.g)
        self.old_copy_mask = system3.BOOK_COPY_MASK
        self.runtime = R.install(None, self.g)

    def tearDown(self):
        system3.BOOK_COPY_MASK = self.old_copy_mask
        self.fixture.tearDown()

    def pick(self, key, labels, weights, label=''):
        self.calls.append(dict(key=key, labels=list(labels), weights=list(weights), thread=threading.get_ident()))
        return next(i for i, weight in enumerate(weights) if weight > 0)

    def pool(self, key, labels, label=''):
        self.pools.append((key, list(labels)))
        return labels

    def run_messages(self, messages):
        return asyncio.run(self.g['book_prompt_messages'](messages))

    def literal_book(self):
        self.fixture.write_epub('literal.epub', 'The Literal Book', 'Code Reader', 'Template Examples', [
            ('Printed Commands', '<p>The printed label says {gazette} and {sfxclip}. The example keeps {book} in literal braces. The manual also prints {stationname} and {sentence}.</p>')])
        self.mode.scan()

    def test_model_system_and_current_user_bind_one_title_without_changing_history(self):
        messages = [{'role': 'system', 'content': 'Talk about {booktopic} and quote {booksentence} on {stationname}.'},
                    {'role': 'user', 'content': 'Old {book:Signals at Night}'},
                    {'role': 'assistant', 'content': 'Old {book}'},
                    {'role': 'user', 'content': 'Discuss {booksegment} from {book:River Gardens}.'}]
        original = copy.deepcopy(messages)
        result = self.run_messages(messages)
        self.assertEqual(messages, original); self.assertEqual(result[1:3], original[1:3])
        self.assertIn('Pine Garden FM', result[0]['content'])
        self.assertIn('Dr. Rowan opened the gate.', result[0]['content'])
        self.assertIn('River Gardens', result[3]['content'])
        self.assertIn('BOOK SOURCE:', result[0]['content'])
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(call['thread'] == threading.get_ident() for call in self.calls))

    def test_booktime_marker_is_removed_binds_retry_and_scopes_sentence(self):
        tag = R.marker('book_time', '2026-10-04:15:book_time', {'book_binding': 'River Gardens'})
        messages = [{'role': 'system', 'content': 'Welcome to {stationname}. {book} {bookchapter} {sentence}\n' + tag},
                    {'role': 'user', 'content': 'Discuss {booksegment} and close the segment.'}]
        result = self.run_messages(messages)
        count = len(self.calls)
        again = self.run_messages(messages)
        self.assertEqual(result, again); self.assertEqual(len(self.calls), count)
        self.assertNotIn('PINE_BOOK_CONTEXT', result[0]['content'])
        self.assertIn('The River Garden', result[0]['content'])
        self.assertNotIn('{sentence}', result[0]['content'])
        ordinary = self.run_messages([{'role': 'user', 'content': 'Keep {sentence} ordinary.'}])
        self.assertEqual(ordinary[0]['content'], 'Keep {sentence} ordinary.')

    def test_literal_book_braces_are_not_recursively_expanded_in_fm(self):
        self.literal_book()
        result = self.run_messages([{'role': 'user', 'content': 'Quote {booksegment} from {book:The Literal Book} on {stationname}.'}])
        text = result[-1]['content']
        self.assertIn('{gazette}', text); self.assertIn('{sfxclip}', text); self.assertIn('{book}', text)
        self.assertIn('prints {stationname} and {sentence}.', text)
        self.assertIn('on Pine Garden FM.', text)
        self.assertNotIn('PINEBOOK', text)

    def test_booktime_alias_does_not_reexpand_braces_inside_inserted_source(self):
        self.literal_book()
        context = {'kind': 'book_time', 'occurrence': 'literal-alias', 'config': {'book_binding': 'The Literal Book'}}
        token = self.runtime.context.set(context)
        try:
            result = self.run_messages([{'role': 'user', 'content': '{booksegment} Then quote {sentence}.'}])
            self.assertIn('prints {stationname} and {sentence}.', result[-1]['content'])
            self.assertIn('keeps {book} in literal braces.', result[-1]['content'])
            self.assertIn('Then quote The printed label says {gazette} and {sfxclip}.', result[-1]['content'])
        finally:
            self.runtime.context.reset(token)

    def test_prebound_context_prepares_source_once_before_the_model_call(self):
        context = {'kind': 'book_time', 'occurrence': 'prepared', 'config': {'book_binding': 'River Gardens'}}
        result = asyncio.run(self.g['book_resolver']().resolve_async('{book} {booksegment}', weighted=self.runtime.weighted,
                                                                   context=context, binding='River Gardens', scheduled=True,
                                                                   occurrence='prepared', booktime=True))
        before = len(self.calls)
        token = self.g['book_prompt_context'].set(context)
        try:
            out = self.run_messages([{'role': 'system', 'content': 'Review {book} {sentence}.'}, {'role': 'user', 'content': '{booksegment}'}])
            self.assertIn(result['values']['booksentence'], out[0]['content'])
            self.assertEqual(len(self.calls), before)
        finally:
            self.g['book_prompt_context'].reset(token)

    def test_per_turn_writer_receives_full_custom_pair_and_actual_source_without_tokens(self):
        self.literal_book()
        context = {'kind': 'book_time', 'occurrence': 'custom-no-tokens', 'book_phase': 'discussion',
                   'config': {'book_binding': 'The Literal Book'},
                   'book_prompts': {'system': 'Custom system rule: debate {calmly|boldly} on {stationname} about {book}.',
                                    'generation': 'Custom generation: compare {booktopic}; react to {sentence}.',
                                    'phase': 'Continue discussion; do not close.', 'production': 'Write fifty words.',
                                    'continuation': 'Prior quote: The example keeps {book} in literal braces.'}}
        result = asyncio.run(self.runtime.resolver().resolve_async('{book}', weighted=self.runtime.weighted,
                            context=context, binding='The Literal Book', scheduled=True, occurrence='custom-no-tokens', booktime=True))
        token = self.runtime.context.set(context)
        try:
            messages = [{'role': 'system', 'content': 'Write the next directed turn.'}, {'role': 'user', 'content': 'Answer the question.'}]
            out = self.run_messages(messages)
            system = out[0]['content']
            self.assertIn('Custom system rule: debate calmly on Pine Garden FM about The Literal Book.', system)
            self.assertIn('Custom generation: compare Template Examples;', system)
            self.assertIn(result['values']['booksegment'], system)
            self.assertIn(result['values']['booksentence'], system)
            self.assertIn('Prior quote: The example keeps {book} in literal braces.', system)
            self.assertIn('prints {stationname} and {sentence}.', system)
            self.assertTrue(system.endswith('Continue discussion; do not close.'))
            self.assertEqual(out[-1], messages[-1])
            self.assertEqual(out, self.run_messages(messages))
        finally:
            self.runtime.context.reset(token)

    def test_previous_source_quote_keeps_command_braces_on_later_model_requests(self):
        self.literal_book()
        context = {'kind': 'book_time', 'occurrence': 'literal-again', 'config': {'book_binding': 'The Literal Book'}}
        asyncio.run(self.runtime.resolver().resolve_async('{book}', weighted=self.runtime.weighted, context=context,
            binding='The Literal Book', scheduled=True, occurrence='literal-again', booktime=True))
        token = self.runtime.context.set(context)
        try:
            source = 'The example keeps {book} in literal braces. The manual also prints {stationname} and {sentence}.'
            out = self.run_messages([{'role': 'user', 'content': 'We just quoted: ' + source + ' Now discuss {book}.'}])
            self.assertIn(source, out[-1]['content'])
            self.assertTrue(out[-1]['content'].endswith('Now discuss The Literal Book.'))
        finally:
            self.runtime.context.reset(token)

    def test_saved_host_cast_outlives_a_later_live_voice_swap(self):
        self.g['dj_settings'] = lambda: {'station_name': 'Pine Garden FM', 'host_name': 'New Host', 'cohost_name': 'New Co-host'}
        context = {'kind': 'book_time', 'book_phase': 'opening', 'book_cast': {'A': 'Dill', 'B': 'Skip'}}
        asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        token = self.runtime.context.set(context)
        try:
            self.assertEqual(self.g['book_repeat_material']("I'm Dill."), '')
            self.assertEqual(self.g['book_repeat_material']("I'm Skip."), '')
            self.assertEqual(self.g['book_repeat_material']("I'm New Host."), "I'm New Host.")
        finally:
            self.runtime.context.reset(token)

    def test_recurring_protocol_and_exact_quotes_are_scoped_and_discussion_is_still_checked(self):
        self.g['dj_settings'] = lambda: {'station_name': 'Pine Garden FM', 'host_name': 'Dill', 'cohost_name': 'Bird'}
        context = {'kind': 'book_time', 'book_phase': 'opening'}
        result = asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        quote = result['values']['booksentence']
        welcome = 'Welcome to Book Time on Pine Garden FM.'
        closing = 'Thanks for Book Time on Pine Garden FM; back to the music.'
        intro = "I'm Dill."
        opinion = 'We should protect every garden owner.'
        for line in (welcome, closing, intro, quote, opinion):
            self.g['NOREPEAT'].note_text(line)
        token = self.runtime.context.set(context)
        try:
            self.assertEqual(self.g['norepeat_line_gate'](welcome, 'dj'), '')
            self.assertEqual(self.g['norepeat_line_gate'](intro, 'dj'), '')
            self.assertEqual(self.g['norepeat_line_gate'](quote, 'dj'), '')
            self.assertFalse(self.g['norepeat_text_used'](quote))
            self.assertEqual(self.g['book_repeat_material']('"' + quote + '" ' + opinion), opinion)
            self.assertTrue(self.g['norepeat_text_used']('"' + quote + '" ' + opinion))
            self.assertTrue(self.g['norepeat_line_gate'](opinion, 'dj'))
            self.assertTrue(self.g['norepeat_line_gate'](closing, 'dj'))
            context['book_phase'] = 'closing'
            self.assertEqual(self.g['norepeat_line_gate'](closing, 'dj'), '')
            self.assertTrue(self.g['norepeat_line_gate'](welcome, 'dj'))
            context['book_phase'] = 'complete'
            self.assertEqual(self.g['norepeat_line_gate'](welcome, 'dj'), '')
            self.assertEqual(self.g['norepeat_line_gate'](closing, 'dj'), '')
            mixed = welcome[:-1] + ', but every garden owner must obey us.'
            self.assertEqual(self.g['book_repeat_material'](mixed), mixed)
        finally:
            self.runtime.context.reset(token)
        self.assertTrue(self.g['norepeat_line_gate'](welcome, 'dj'))
        self.assertTrue(self.g['norepeat_line_gate'](quote, 'dj'))
        self.assertTrue(self.g['norepeat_text_used'](opinion))

    def copy_gate_book(self, phase='opening'):
        chapter = 'Eliminating the Foreigners: the John Hull-Miami Cuban Connection'
        short = 'Military narco-corruption, however, appears to have gone way beyond the military zone commanders.'
        long = ('The archive described an extensive arrangement in which public officials, military officers, '
                'private contractors, local intermediaries, foreign representatives, and several unnamed participants '
                'each performed a separate duty over many consecutive months while the official investigation '
                'continued to gather documents, interview witnesses, compare accounts, and examine the consequences '
                'for communities living near the border.')
        self.fixture.write_epub('war.epub', 'War On Drugs', 'A Historian', 'Drug Policy', [
            (chapter, '<p>' + short + ' ' + long + ' The later inquiry raised further questions.</p>')])
        self.mode.scan()
        context = {'kind': 'book_time', 'book_phase': phase, 'book_cast': {'A': 'Dill', 'B': 'Skip'},
                   'book_prompts': {'system': 'Review {book} in chapter {bookchapter}.',
                                    'generation': 'Discuss {booksentence}.',
                                    'phase': 'Introduce this title and chapter; do not close.'}}
        result = asyncio.run(self.runtime.resolver().resolve_async('{book:War On Drugs}',
                             weighted=self.runtime.weighted, context=context))
        self.assertEqual(result['source']['chapter'], chapter)
        self.assertEqual(result['values']['booksentence'], short)
        self.assertIn(long, result['values']['booksegment'])
        return context, result, chapter, short, long

    def test_real_copy_gate_accepts_verified_opening_chapter_but_keeps_phase_and_receipt_guards(self):
        context, result, chapter, short, long = self.copy_gate_book()
        text = 'Today we are diving into War On Drugs, specifically chapter ' + chapter + '.'
        conv = {'inputs': {}, 'subject': {}, 'turns': [
            {'index': 9, 'topic_override': 'Book Time, War On Drugs: ' + chapter}]}
        baseline = system3.gate_check(conv, None, text)
        self.assertEqual(baseline['rule'], 'topic')
        self.assertEqual(baseline['how'], '9 of its words in a row')
        token = self.runtime.context.set(context)
        try:
            self.assertIsNone(system3.gate_check(conv, None, text))
            self.assertEqual(conv['turns'][0]['topic_override'], 'Book Time, War On Drugs: ' + chapter)
            prepared = self.run_messages([{'role': 'system', 'content': 'Write the next directed turn.'},
                                          {'role': 'user', 'content': 'Answer the preceding host.'}])
            self.assertIn('Review War On Drugs in chapter ' + chapter, prepared[0]['content'])
            self.assertIn(context['book_prompts']['phase'], prepared[0]['content'])
            context['book_phase'] = 'discussion'
            self.assertEqual(system3.gate_check(conv, None, text)['rule'], 'topic')
            context['book_phase'] = 'opening'
            context['book_roulette'] = copy.deepcopy(result)
            context['book_roulette']['source']['content_hash'] = 'unverified'
            self.assertEqual(system3.gate_check(conv, None, text)['rule'], 'topic')
            context['book_roulette'] = {'source': 'malformed', 'values': result['values']}
            self.assertEqual(system3.gate_check(conv, None, text)['rule'], 'topic')
            context.pop('book_roulette')
            context['book_source'] = result['source']
            self.assertEqual(system3.gate_check(conv, None, text)['rule'], 'topic')
        finally:
            self.runtime.context.reset(token)
        self.assertEqual(system3.gate_check(conv, None, text), baseline)

    def test_real_copy_gate_allows_only_short_source_spans_and_reviews_remaining_opinions(self):
        context, result, chapter, short, long = self.copy_gate_book('discussion')
        conv = {'inputs': {}, 'subject': {}, 'turns': [
            {'index': 24, 'topic_override': short}, {'index': 25, 'topic_override': long}]}
        self.assertEqual(system3.gate_check(conv, None, short)['rule'], 'topic')
        opinion = 'Every border community deserves independent scrutiny and permanent protection from these officials.'
        unknown = 'Nobody returned to the distant village after the armed patrol left the old checkpoint.'
        token = self.runtime.context.set(context)
        try:
            # The bound source is available after turn twenty as well as in the opening.
            self.assertIsNone(system3.gate_check(conv, None, short))
            self.assertIsNone(system3.gate_check(conv, None, 'The author writes: "' + short + '" I question those institutions.'))
            caught = system3.gate_check(conv, None, '"' + short + '" ' + opinion,
                                       [('the previous opinion', opinion)])
            self.assertEqual(caught['rule'], 'copy')
            self.assertEqual(caught['what'], 'the previous opinion')
            self.assertEqual(system3.gate_check(conv, None, long)['rule'], 'topic')
            self.assertEqual(system3.gate_check(conv, None, short + ' ' + long)['rule'], 'topic')
            self.assertEqual(system3.gate_check(conv, None, unknown, [('another quote', unknown)])['rule'], 'copy')
            # Matching a real heading does not excuse the rest of a copied topic card.
            context['book_phase'] = 'opening'
            copied = chapter + '. ' + opinion
            topic = {'inputs': {}, 'subject': {}, 'turns': [{'index': 9, 'topic_override': copied}]}
            self.assertEqual(system3.gate_check(topic, None, copied)['rule'], 'topic')
        finally:
            self.runtime.context.reset(token)
        self.assertEqual(system3.gate_check(conv, None, short)['rule'], 'topic')

    def test_real_system3_reservation_allows_bound_quotes_across_part_cids_only(self):
        context = {'kind': 'book_time', 'book_phase': 'discussion'}
        result = asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        quote = result['values']['booksentence']
        opinion = 'Every private garden needs our protection.'
        unknown_quote = 'Nobody returned to that ruined village.'
        owner = SimpleNamespace(host=SimpleNamespace(norepeat_text_used=self.g['norepeat_text_used'],
                                                     book_repeat_material=self.g['book_repeat_material']),
                                lock=threading.RLock(), rewrite_material=lambda handle: None,
                                _gate_flush=lambda handle: None, fail=lambda *args: None)
        def call(cid, text):
            handle = SimpleNamespace(gate={'active': True}, config={}, conv={'identity': {'conversation_id': cid}})
            with patch.object(system3_runtime.system3, 'gate_next', side_effect=lambda conv, run: {'repeat': run['repeat_check'](text)}):
                return system3_runtime.System3Runtime.turn_gate_next(owner, handle)['repeat']
        token = self.runtime.context.set(context)
        try:
            self.assertFalse(call('opening-part', quote))
            self.assertFalse(call('continuation-part', quote))
            self.assertFalse(call('opinion-part', opinion))
            self.assertTrue(call('other-opinion-part', opinion))
            self.assertTrue(call('quote-plus-old-opinion', '"' + quote + '" ' + opinion))
            self.assertFalse(call('unknown-quote-part', unknown_quote))
            self.assertTrue(call('repeated-unknown-quote-part', unknown_quote))
        finally:
            self.runtime.context.reset(token)
        self.assertFalse(call('ordinary-quote-first', quote))
        self.assertTrue(call('ordinary-quote-repeat', quote))

    def test_actual_earlier_gazette_and_prompt_block_parsers_preserve_completed_book_quote(self):
        pb = '\ue000printed\ue001literal content\ue002'
        self.fixture.write_epub('controls.epub', 'The Control Book', 'Code Reader', 'Printed Controls', [
            ('Printed Commands', '<p>The source prints {gazette} as an example. The source also prints ' + pb + ' as literal text.</p>')])
        self.mode.scan()
        context = {'kind': 'book_time', 'occurrence': 'earlier-parser', 'book_phase': 'discussion', 'config': {'book_binding': 'The Control Book'}}
        result = asyncio.run(self.runtime.resolver().resolve_async('{book}', weighted=self.runtime.weighted, context=context,
                            binding='The Control Book', scheduled=True, occurrence='earlier-parser', booktime=True))
        literal = result['values']['booksegment']
        self.assertIn(pb, literal)
        prompt = 'COMPLETED TRANSCRIPT - A has just said - ' + literal + '\nGenuine Gazette command: {gazette}. '
        prompt += '\ue000real_block\ue001Keep this real block.\ue002'
        token = self.runtime.context.set(context)
        try:
            with patch.object(gazette_prompt, 'draw', return_value={'prompt': 'REAL ARTICLE'}) as draw:
                expanded = asyncio.run(self.g['gazette_prompt_messages']([{'role': 'user', 'content': prompt}]))[0]['content']
                self.assertEqual(draw.call_count, 1)
                self.assertIn(literal, expanded)
                self.assertIn('Genuine Gazette command: REAL ARTICLE.', expanded)
                blocked, _decisions = self.g['prompt_blocks_resolve'](expanded)
                self.assertIn(literal, blocked)
                self.assertIn('Keep this real block.', blocked)
                self.assertNotIn('\ue000real_block\ue001', blocked)
                repeated = asyncio.run(self.g['gazette_prompt_messages']([{'role': 'user', 'content': blocked}]))[0]['content']
                self.assertEqual(draw.call_count, 1)
                wire = self.g['_pb_unmark'](repeated)
                self.assertIn(literal, wire)
                final = self.run_messages([{'role': 'user', 'content': wire}])[-1]['content']
                self.assertIn(literal, final)
                self.assertNotIn('BOOKLITERAL', final)
        finally:
            self.runtime.context.reset(token)
        with patch.object(gazette_prompt, 'draw', return_value={'prompt': 'ORDINARY ARTICLE'}) as draw:
            ordinary = asyncio.run(self.g['gazette_prompt_messages']([{'role': 'user', 'content': 'Ordinary {gazette}.'}]))[0]['content']
            self.assertEqual(ordinary, 'Ordinary ORDINARY ARTICLE.')
            self.assertEqual(draw.call_count, 1)
        self.assertEqual(self.g['_pb_unmark'](pb), 'literal content')

    def test_preview_uses_operator_weights_without_live_rolls_or_pool_changes(self):
        self.desk['book.source'] = [{'text': 'River Gardens — Ada Reader', 'enabled': False, 'weight': 5},
                                   {'text': 'Signals at Night — Bea Writer', 'weight': 7}]
        before = copy.deepcopy(self.g['book_resolver']().state)
        result = asyncio.run(self.g['book_resolver']().resolve_async('{book}', weighted=self.runtime.preview_weighted, persist=False))
        self.assertEqual(result['values']['book'], 'Signals at Night')
        self.assertEqual(self.calls, []); self.assertEqual(self.pools, []); self.assertEqual(self.runtime.candidate_pools, {})
        self.assertEqual(self.g['book_resolver']().state, before)
        self.assertEqual(result['rolls'][0]['candidates'][1]['weight'], 7)

    def test_actual_rolls_honor_and_record_effective_desk_weights(self):
        self.desk['book.source'] = [{'text': 'River Gardens — Ada Reader', 'enabled': False},
                                   {'text': 'Signals at Night — Bea Writer', 'weight': 7}]
        result = asyncio.run(self.g['book_resolver']().resolve_async('{book}', weighted=self.runtime.weighted))
        self.assertEqual(result['values']['book'], 'Signals at Night')
        self.assertEqual(self.calls[0]['weights'], [0, 7])
        self.assertEqual(result['rolls'][0]['candidates'][0]['weight'], 0)
        self.assertEqual(result['rolls'][0]['candidates'][1]['weight'], 7)
        self.assertEqual(self.runtime.candidate_pools['book.source']['total'], 2)

    def test_separate_generation_tasks_keep_independent_bindings(self):
        async def generate(title):
            context = {}
            result = await self.g['book_resolver']().resolve_async('{book:' + title + '}', weighted=self.runtime.weighted, context=context)
            token = self.g['book_prompt_context'].set(context)
            try:
                await asyncio.sleep(0)
                return await self.g['book_prompt_messages']([{'role': 'user', 'content': 'Title {book}, quotation {booksentence}'}])
            finally:
                self.g['book_prompt_context'].reset(token)
        async def go():
            return await asyncio.gather(generate('River Gardens'), generate('Signals at Night'))
        results = asyncio.run(go())
        self.assertIn('River Gardens', results[0][-1]['content'])
        self.assertIn('Signals at Night', results[1][-1]['content'])
        self.assertIsNone(self.g['book_prompt_context'].get())

    def test_h3_manual_payload_prepares_all_fields_once_and_preserves_source_braces(self):
        self.literal_book()
        original = {'mode': 'text', 'prompt': 'Show {funny|grim} DJs reviewing {book:The Literal Book}: {booksegment}',
                    'speech': 'On {stationname}: {booksentence}', 'h3_brief': {'constraints': 'Use {booktopic} imagery.'}}
        payload = asyncio.run(self.g['book_h3_prepare'](original))
        self.assertEqual(original['speech'], 'On {stationname}: {booksentence}')
        self.assertIn('funny DJs', payload['prompt'])
        self.assertIn('{gazette}', payload['prompt']); self.assertIn('{sfxclip}', payload['prompt']); self.assertIn('{book}', payload['prompt'])
        self.assertIn('{stationname}', payload['prompt']); self.assertIn('{sentence}', payload['prompt'])
        self.assertIn('Pine Garden FM', payload['speech'])
        self.assertEqual(payload['h3_prompts']['book_roulette']['source']['title'], 'The Literal Book')
        self.assertEqual(len(self.calls), 4)
        # Existing h3_prompts_dress's truthy-record guard skips a second fill.
        self.assertTrue(payload['h3_prompts'])

    def test_h3_preroll_protects_books_and_hour_receipt_survives_later_worker(self):
        self.literal_book()
        self.fields = {'goal': 'Review {book:The Literal Book} and {booktopic}.',
                       'speech': 'Welcome to {stationname}; {booksentence}',
                       'gallery': 'DJs discuss {booksegment} in a {funny|grim} studio.', 'style': 'ink', 'constraints': 'Quote briefly.'}
        async def prepare_hour():
            await self.g['h3_slots_preroll'](*self.fields.values())
            return self.g['h3_prompts_hour']('They are on air.')
        entry = asyncio.run(prepare_hour())
        self.assertEqual(self.preparations, [[]], 'legacy named shelf must never try to roll book placeholders')
        self.assertIn('book_roulette', entry)
        self.assertIn('book_roulette', self.commits[-1])
        before = len(self.calls)
        self.g['book_prompt_context'].set(None)
        payload = asyncio.run(self.g['book_h3_prepare']({'hourly': True, 'mode': 'reference', 'source_type': 'gallery',
                                                       'prompt': 'Create the queued stinger. ' + entry['goal']}))
        self.assertEqual(len(self.calls), before)
        self.assertEqual(payload['book_roulette'], entry['book_roulette'])
        words = self.g['h3_prompts_words'](entry, 'gallery')
        self.assertIn('{gazette}', words['direction']); self.assertIn('{sfxclip}', words['direction']); self.assertIn('{book}', words['direction'])
        self.assertIn('{stationname}', words['direction']); self.assertIn('{sentence}', words['direction'])
        self.assertIn('funny studio', words['direction'])
        self.assertEqual(words['book_roulette'], entry['book_roulette'])
        self.assertEqual(len(self.calls), before)

    def test_booktime_system3_plan_uses_concrete_metadata_and_raw_quote_tokens(self):
        context = {'kind': 'book_time', 'occurrence': 's3-plan', 'config': {'book_binding': 'River Gardens'}}
        async def plan():
            await self.runtime.resolver().resolve_async('{book}', weighted=self.runtime.weighted, context=context,
                                                        binding='River Gardens', scheduled=True, occurrence='s3-plan', booktime=True)
            token = self.runtime.context.set(context)
            try:
                return await self.g['system3_direct_banter'](angle=R.marker('book_time', 's3-plan', context['config']) + '\nDiscuss {booksegment}, quote {booksentence}.', road='book_time')
            finally:
                self.runtime.context.reset(token)
        result = asyncio.run(plan())
        self.assertTrue(result['topic'].startswith('Book Time: reviewing River Gardens by Ada Reader'))
        self.assertIn('The River Garden', result['topic']); self.assertIn('Water and Gardens', result['topic'])
        self.assertIn('{booksegment}', result['inputs']['angle']); self.assertIn('{booksentence}', result['inputs']['angle'])
        self.assertNotIn('Dr. Rowan opened the gate.', result['inputs']['angle'])
        self.assertNotIn('PINE_BOOK_CONTEXT', result['inputs']['angle'])
        self.assertEqual(result['inputs']['road'], 'banter')
        self.assertEqual(result['inputs']['dynamic_kind'], 'book_time')
        self.assertEqual(result['inputs']['book_source']['book_id'], self.fixture.ids['River Gardens'])

    def test_booktime_topics_stay_inside_the_selected_book(self):
        class FakeSystem3:
            def _topic_bank(self, ctx):
                return [{'id': 'global-news', 'text': 'An unrelated station topic', 'used': 0, 'reply': ''}]
        system3 = FakeSystem3()
        self.g['_system3'] = lambda: system3
        context = {'kind': 'book_time'}
        receipt = asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        token = self.runtime.context.set(context)
        try:
            asyncio.run(self.g['system3_direct_banter'](angle='Review {book}.'))
            rows = system3._topic_bank({})
            self.assertEqual(len(rows), 3)
            self.assertTrue(all('River Gardens' in row['text'] for row in rows))
            self.assertFalse(any(row['id'] == 'global-news' for row in rows))
            self.assertTrue(all('Dr. Rowan' not in row['text'] for row in rows))
        finally:
            self.runtime.context.reset(token)
        self.assertEqual(system3._topic_bank({})[0]['id'], 'global-news')

    def test_ordinary_system3_banter_is_unchanged(self):
        raw = dict(angle='The lights flickered.', road='banter', bank=True)
        result = asyncio.run(self.g['system3_direct_banter'](**raw))
        self.assertEqual(result['inputs'], raw)

    def test_real_record_title_guard_accepts_only_bound_source_quotes(self):
        context = {'kind': 'book_time'}
        asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        token = self.runtime.context.set(context)
        try:
            allowed = ['Knowledge by Iacon']
            self.assertTrue(self.g['names_only']('We are reviewing "River Gardens" today.', allowed))
            self.assertTrue(self.g['names_only']('It says "Dr. Rowan opened the gate."', allowed))
            self.assertTrue(self.g['names_only']('Chapter "The River Garden" starts the argument.', allowed))
            self.assertFalse(self.g['names_only']('Now playing "Blue Monday" after "River Gardens".', allowed))
            self.assertFalse(self.g['names_only']('We prefer "Signals at Night" today.', allowed))
            self.assertFalse(self.g['names_only']('He says "They destroyed the garden."', allowed))
        finally:
            self.runtime.context.reset(token)
        self.assertFalse(self.g['names_only']('We are reviewing "River Gardens" today.', ['Knowledge by Iacon']))
        self.assertTrue(self.g['names_only']('Now playing "Knowledge".', ['Knowledge by Iacon']))

    def test_real_station_governor_preserves_bookends_but_still_governs_other_lines(self):
        context = {'kind': 'book_time'}
        asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        welcome = 'Welcome to Book Time on Pine Garden FM.'
        closing = 'Thanks for Book Time on Pine Garden FM; back to the music.'
        token = self.runtime.context.set(context)
        try:
            self.assertEqual(self.g['station_name_scrub'](welcome), welcome)
            self.assertEqual(self.g['station_name_scrub'](closing), closing)
            self.assertEqual(self.g['station_name_scrub']('Pine Garden FM has a garden.'), 'the station has a garden.')
        finally:
            self.runtime.context.reset(token)
        self.assertEqual(self.g['station_name_scrub'](welcome), 'Welcome to Book Time on the station.')

    def test_restored_source_guard_does_not_need_to_reopen_the_resolver(self):
        context = {'kind': 'book_time'}
        asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        restored = R.BookPromptRuntime(self.g)
        restored.original = self.runtime.original
        token = restored.context.set(context)
        try:
            self.assertIsNone(restored._resolver)
            self.assertTrue(restored.names_only('Review "River Gardens".', ['Knowledge by Iacon']))
            self.assertEqual(restored.station_scrub('Welcome to Book Time on Pine Garden FM.'),
                             'Welcome to Book Time on Pine Garden FM.')
            self.assertFalse(restored.names_only('Now play "Blue Monday".', ['Knowledge by Iacon']))
            self.assertIsNone(restored._resolver)
        finally:
            restored.context.reset(token)

    def test_source_guard_rejects_a_tampered_receipt(self):
        context = {'kind': 'book_time'}
        asyncio.run(self.runtime.resolver().resolve_async('{book:River Gardens}', weighted=self.runtime.weighted, context=context))
        context['book_roulette']['values']['booksegment'] = 'This passage was invented.'
        token = self.runtime.context.set(context)
        try:
            self.assertFalse(self.g['names_only']('Review "River Gardens".', ['Knowledge by Iacon']))
        finally:
            self.runtime.context.reset(token)

    def test_station_name_with_backslashes_is_inserted_as_text(self):
        self.g['dj_settings'] = lambda: {'station_name': r'Pine \1 FM'}
        result = self.run_messages([{'role': 'user', 'content': 'Welcome to {stationname}.'}])
        self.assertEqual(result[0]['content'], r'Welcome to Pine \1 FM.')

    def test_invalid_context_marker_does_not_generate_fake_book_content(self):
        with self.assertRaises(B.BookRouletteError):
            self.run_messages([{'role': 'user', 'content': '{book}\n[[PINE_BOOK_CONTEXT not_json]]'}])

    def test_unprepared_sync_h3_fill_never_reads_documents_on_the_event_loop(self):
        with self.assertRaisesRegex(B.BookRouletteError, 'asynchronously'):
            self.g['h3_speak_fill']('Review {book}.')
        self.assertIsNone(self.runtime._resolver)

    def test_app_model_h3_and_install_hooks_are_present(self):
        text = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn('messages = await book_prompt_messages(messages)', text)
        self.assertIn('payload = await book_h3_prepare(payload)', text)
        self.assertGreater(text.index('book_prompt_runtime.install(app, globals())'), text.index('book_mode.register(app, globals())'))
        call = text[text.index('async def call_ollama('):text.index('async def generate_answer(')]
        self.assertGreater(call.index('book_prompt_messages'), call.index('gazette_prompt_messages'))
        self.assertGreater(call.index('book_prompt_messages'), call.index('_pb_unmark'))


if __name__ == '__main__':
    unittest.main()
