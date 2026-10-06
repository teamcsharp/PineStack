"""Real-source book roulette behavior without FM playback or a model call."""
import asyncio
import copy
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import book_mode
import book_roulette as B
import h3_slots


class BookRouletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.shelf = self.root / 'shelf'; self.shelf.mkdir()
        self.write_epub('a.epub', 'River Gardens', 'Ada Reader', 'Water and Gardens', [
            ('The River Garden', '<p>Dr. Rowan opened the gate. The river fed the garden. They shared the harvest! Every visitor brought a new idea.</p>'),
            ('A Dry Season', '<p>The rain stopped early. The gardeners saved every drop. They repaired the old water tank. The village stayed green.</p>')])
        self.write_epub('b.epub', 'Signals at Night', 'Bea Writer', 'Radio and Music', [
            ('The Radio Workshop', '<p>The radio woke at midnight. Mara heard a distant voice. The workshop filled with music. She answered the signal.</p>')])
        self.mode = book_mode.BookMode(self.root / 'books', [str(self.shelf)]); self.mode.scan()
        self.service = B.BookRoulette(self.mode)
        self.calls = []; self.notes = []
        self.ids = {r['title']: r['id'] for r in self.mode.catalog.values()}

    def tearDown(self):
        self.tmp.cleanup()

    def write_epub(self, filename, title, author, subject, chapters):
        path = self.shelf / filename
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
            archive.writestr('book.opf', '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                            f'<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator><dc:subject>{subject}</dc:subject></metadata><manifest>'
                            + ''.join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(len(chapters)))
                            + '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine>'
                            + ''.join(f'<itemref idref="c{i}"/>' for i in range(len(chapters))) + '</spine></package>')
            archive.writestr('nav.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol>'
                            + ''.join(f'<li><a href="c{i}.xhtml">{label}</a></li>' for i, (label, _) in enumerate(chapters)) + '</ol></nav></body></html>')
            for i, (label, body) in enumerate(chapters):
                archive.writestr(f'c{i}.xhtml', f'<html><head><script>Invented quote. Bad claim.</script></head><body><h1>{label}</h1>{body}</body></html>')
        return path

    def pick(self, key, labels, weights, label):
        self.calls.append(dict(key=key, labels=labels, weights=weights, thread=threading.get_ident()))
        return next(i for i, weight in enumerate(weights) if weight > 0)

    def note(self, *args):
        self.notes.append(args)

    def resolve(self, *texts, **options):
        return self.service.resolve(*texts, weighted=self.pick, note=self.note, **options)

    def test_actual_index_split_member_is_excluded_from_discussion(self):
        path = self.write_epub('matter.epub', 'Battle Notes', 'A Historian', '', [
            ('I', '<p>Agincourt. See battle formations. This entry is alphabetized.</p>'),
            ('Introduction', '<p>The soldiers faced immediate uncertainty. Their choices shaped the battle.</p>')])
        with zipfile.ZipFile(path) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        data['index_split_014.html'] = data.pop('c0.xhtml')
        for name in ('book.opf', 'nav.xhtml'):
            data[name] = data[name].replace(b'c0.xhtml', b'index_split_014.html')
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in data.items():
                archive.writestr(name, body)
        self.mode.scan()
        result = self.resolve('{book:Battle Notes} {bookchapter} {booksentence}')
        self.assertEqual(result['values']['bookchapter'], 'Introduction')
        self.assertEqual(result['source']['member'], 'c1.xhtml')
        self.assertEqual(result['source']['chapter_index'], 2)
        self.assertEqual(result['values']['booksentence'], 'The soldiers faced immediate uncertainty.')
        self.assertFalse(B.discussion_source_allowed({'chapter': 'index', 'member': 'index_split_014.html'}))

    def test_structural_labels_are_exact_and_prose_introductions_remain(self):
        labels = ['Table of Contents', 'Copyright', 'Bibliography', 'References', 'Index',
                  'Introduction', 'The Index of Empire', 'Contents of the Atmosphere']
        path = self.write_epub('labels.epub', 'Structural Labels', 'A Writer', '',
            [(label, '<p>The observer studied the evidence. Every source contributed a different detail.</p>') for label in labels])
        chapters, _ = B._epub(path)
        self.assertEqual([row['title'] for row in chapters], labels[-3:])
        self.assertEqual([row['index'] for row in chapters], [6, 7, 8])
        self.assertTrue(B.discussion_source_allowed({'chapter': 'Introduction', 'member': 'intro.xhtml'}))
        self.assertTrue(B.discussion_source_allowed({'chapter': 'The Index of Empire', 'member': 'ch01.xhtml'}))

    def test_nav_label_and_document_semantics_exclude_structural_matter(self):
        path = self.write_epub('semantics.epub', 'Source Semantics', 'A Writer', '', [
            ('Appendix A', '<p>This list links names to their pages. The names are alphabetized.</p>'),
            ('Contents', '<p>This list links every heading. Read the following chapter.</p>'),
            ('Field Observations', '<p>The rain changed the valley. The farmers adapted their routines.</p>')])
        with zipfile.ZipFile(path) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        data['c0.xhtml'] = data['c0.xhtml'].replace(b'<body>', b'<body epub:type="index">')
        data['c1.xhtml'] = data['c1.xhtml'].replace(b'<h1>Contents</h1>', b'<h1>Opening Pages</h1>')
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in data.items():
                archive.writestr(name, body)
        chapters, _ = B._epub(path)
        self.assertEqual([row['title'] for row in chapters], ['Field Observations'])

    def test_pdf_structural_outline_pages_are_excluded_without_renaming_chapters(self):
        from pypdf import PdfWriter
        path = self.shelf / 'outline-filter.pdf'
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=300, height=420)
        writer.add_outline_item('Index', 0)
        writer.add_outline_item('Introduction', 1)
        writer.add_outline_item('Bibliography', 2)
        with path.open('wb') as file:
            writer.write(file)
        with patch.object(B.library_extract, 'read_pdf', return_value={'pages': [
            {'n': i, 'text': 'The observer studied the evidence. The argument developed from these facts.'} for i in range(1, 4)]}):
            chapters, _ = B._pdf(path)
        self.assertEqual([(row['title'], row['page'], row['index']) for row in chapters], [('Introduction', 2, 2)])

    def test_metadata_guard_preserves_a_frozen_structural_receipt(self):
        receipt = self.resolve('{book}', occurrence='frozen-structural', scheduled=True)
        receipt['source'].update(chapter='index', member='index_split_014.html')
        self.service.state['receipts'][receipt['occurrence']] = copy.deepcopy(receipt)
        before = copy.deepcopy(receipt)
        result = self.resolve('{book}', occurrence=receipt['occurrence'], scheduled=True)
        self.assertFalse(B.discussion_source_allowed(result['source']))
        self.assertEqual(result, before)
        self.assertEqual(self.service.state['receipts'][receipt['occurrence']], before)

    def test_all_fields_bind_to_one_actual_source_even_when_book_is_last(self):
        result = self.resolve('{booktopic} {booksentence} {booksegment} {bookchapter} {booksentences} {book}')
        self.assertEqual(result['values']['book'], 'River Gardens')
        self.assertEqual(result['source']['book_id'], self.ids['River Gardens'])
        self.assertEqual(result['values']['bookchapter'], 'The River Garden')
        self.assertEqual(result['source']['chapter_basis'], 'epub_spine')
        self.assertEqual(result['source']['member'], 'c0.xhtml')
        self.assertEqual(result['values']['booktopic'], 'Water and Gardens')
        self.assertIn('Dr. Rowan opened the gate.', result['values']['booksegment'])
        self.assertNotIn('Invented', json.dumps(result))
        self.assertEqual([c['key'] for c in self.calls], ['book.source', 'book.chapter', 'book.segment', 'book.sentence', 'book.topic'])
        self.assertEqual(len(self.notes), 5)

    def test_standalone_book_tokens_roll_one_random_source_book(self):
        for token in B.NAMES[1:]:
            with self.subTest(token=token):
                self.calls.clear()
                result = self.resolve('Discuss {' + token + '}')
                self.assertEqual(result['source']['book_id'], self.ids['River Gardens'])
                self.assertEqual(self.calls[0]['key'], 'book.source')

    def test_explicit_title_and_library_id_skip_title_roulette(self):
        for binding in ('Signals at Night', self.ids['Signals at Night']):
            with self.subTest(binding=binding):
                self.calls.clear()
                result = self.resolve('{book:' + binding + '} {booksentence}')
                self.assertEqual(result['values']['book'], 'Signals at Night')
                self.assertNotIn('book.source', [c['key'] for c in self.calls])
                self.assertIn('radio', result['values']['booksegment'])
        self.assertEqual(self.resolve('{booktopic}', binding='Signals at Night')['values']['book'], 'Signals at Night')

    def test_conflicting_or_unknown_bindings_never_silently_randomize(self):
        for text in ('{book:Missing Title}', '{book:River Gardens} {book:Signals at Night}'):
            with self.subTest(text=text), self.assertRaises(B.BookRouletteError):
                self.resolve(text)

    def test_ambiguous_title_requires_explicit_id(self):
        self.write_epub('duplicate.epub', 'River Gardens', 'Someone Else', '', [('Other Chapter', '<p>This is a different book. It has a different author.</p>')])
        self.mode.scan()
        with self.assertRaisesRegex(B.BookRouletteError, 'ambiguous'):
            self.resolve('{book:River Gardens}')
        self.assertEqual(self.resolve('{book}', binding=self.ids['River Gardens'])['source']['book_id'], self.ids['River Gardens'])

    def test_generation_context_reuses_quotes_and_all_rolls(self):
        context = {}
        first = self.resolve('{booksentence}', context=context)
        count = len(self.calls)
        second = self.resolve('{booksegment} {booksentences}', context=context)
        self.assertEqual(first, second); self.assertEqual(len(self.calls), count)
        with self.assertRaisesRegex(B.BookRouletteError, 'conflicts'):
            self.resolve('{book:Signals at Night}', context=context)

    def test_quotes_are_whole_short_exact_sentences_and_passage_is_bounded(self):
        result = self.resolve('{book} {booksentences}')
        source = self.service._load(self.mode.row(result['source']['book_id']))
        chapter = source['chapters'][0]
        text = ' '.join(r['text'] for r in chapter['sentences'])
        for key in ('booksentence', 'booksentences', 'booksegment'):
            self.assertIn(result['values'][key], text)
        self.assertLessEqual(len(result['values']['booksentence'].split()), 35)
        self.assertLessEqual(len(result['values']['booksentences'].split()), 100)
        self.assertLessEqual(len(result['values']['booksegment'].split()), 180)
        self.assertTrue(B._complete(result['values']['booksentence']))
        self.assertEqual(result['source']['passage_sentence_indices'], list(range(len(chapter['sentences']))))
        self.assertEqual(result['values']['booksentence'], 'Dr. Rowan opened the gate.')

    def test_one_long_sentence_is_not_truncated_into_a_fake_quote(self):
        long_sentence = ' '.join(['extraordinary'] * 90) + '.'
        self.write_epub('long.epub', 'Long Prose', '', '', [('Long Prose Chapter', f'<p>{long_sentence} This sentence is short. It is also true.</p>')])
        self.mode.scan()
        result = self.resolve('{book:Long Prose} {booksentence} {booksegment}')
        self.assertEqual(result['values']['booksentence'], 'This sentence is short.')
        self.assertIn(long_sentence, result['values']['booksegment'])
        self.assertTrue(B._complete(result['values']['booksentences']))

    def test_extractor_upgrade_preserves_frozen_receipts_and_title_history(self):
        first = self.resolve('{book}', occurrence='upgrade-frozen', scheduled=True)
        saved = copy.deepcopy(self.service.state)
        saved['version'] = 2
        saved['failures'] = {'old-extractor': {'reason': 'old parse failure'}}
        self.service._write(self.service.data / 'state.json', saved)
        reloaded = B.BookRoulette(self.mode)
        self.assertEqual(reloaded.state['version'], B.VERSION)
        self.assertEqual(reloaded.source_for(first['occurrence']), first)
        self.assertEqual(reloaded.state['recent'], saved['recent'])
        self.assertEqual(reloaded.state['recent_titles'], saved['recent_titles'])
        self.assertEqual(reloaded.state['failures'], {})
        self.assertEqual(reloaded.resolve('{book}', weighted=self.pick,
            occurrence=first['occurrence'], scheduled=True), first)
        second = reloaded.resolve('{book}', weighted=self.pick, occurrence='next-upgrade', scheduled=True)
        self.assertNotEqual(second['source']['title'], first['source']['title'])

    def test_restore_verified_persisted_part_overrides_a_new_wrong_pin_without_a_draw(self):
        first = self.resolve('{book}', occurrence='first-real-part', scheduled=True)
        other = self.resolve('{book}', occurrence='wrong-pin', scheduled=True)
        self.service.state['receipts']['first-real-part'] = copy.deepcopy(other)
        before = copy.deepcopy(first)
        calls = len(self.calls)
        self.assertEqual(self.service.restore_receipt('first-real-part', first), first)
        self.assertEqual(first, before)
        self.assertEqual(self.service.source_for('first-real-part'), first)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(self.service.state['source_recoveries'][-1]['previous'], other['source'])
        tampered = copy.deepcopy(first); tampered['values']['booksegment'] = 'A different passage.'
        with self.assertRaisesRegex(B.BookRouletteError, 'cannot be verified'):
            self.service.restore_receipt('first-real-part', tampered)
        reloaded = B.BookRoulette(self.mode)
        self.assertEqual(reloaded.source_for('first-real-part'), before)

    def test_scheduled_receipts_survive_reload_and_use_different_books(self):
        first = self.resolve('{book}', occurrence='2026-10-04T15:15/booktime', scheduled=True)
        count = len(self.calls)
        again = self.resolve('{book}', occurrence='2026-10-04T15:15/booktime', scheduled=True)
        self.assertEqual(first, again); self.assertEqual(len(self.calls), count)
        second = self.resolve('{book}', occurrence='2026-10-04T15:45/booktime', scheduled=True)
        self.assertNotEqual(first['source']['book_id'], second['source']['book_id'])
        reloaded = B.BookRoulette(self.mode)
        self.assertEqual(reloaded.resolve('{book}', weighted=self.pick, occurrence=first['occurrence'], scheduled=True), first)
        self.assertEqual(len(self.service.state['receipts']), 2)

    def test_previews_do_not_advance_scheduled_history(self):
        before = copy.deepcopy(self.service.state)
        self.resolve('{book}', scheduled=True, occurrence='preview', persist=False)
        self.assertEqual(self.service.state, before)
        self.assertFalse((self.service.data / 'state.json').exists())
        self.assertEqual(self.resolve('{book}', scheduled=True, occurrence='real')['values']['book'], 'River Gardens')

    def test_scheduled_draw_requires_occurrence_identity(self):
        with self.assertRaisesRegex(B.BookRouletteError, 'occurrence ID'):
            self.resolve('{book}', scheduled=True)

    def test_source_cache_reuses_extraction_and_invalidates_changed_stamp(self):
        first = self.resolve('{book:River Gardens}')
        with patch.object(B, '_epub', side_effect=AssertionError('unchanged file extracted twice')):
            self.resolve('{book:River Gardens}')
            reloaded = B.BookRoulette(self.mode)
            reloaded.resolve('{book:River Gardens}', weighted=self.pick)
        self.write_epub('a.epub', 'River Gardens', 'Ada Reader', 'New Source Topic', [('The Updated Chapter', '<p>The repaired gate swung wide. The river returned to its old course.</p>')])
        self.mode.scan()
        second = self.resolve('{book:River Gardens}')
        self.assertNotEqual(first['source']['stamp'], second['source']['stamp'])
        self.assertEqual(second['values']['bookchapter'], 'The Updated Chapter')
        self.assertEqual(second['values']['booktopic'], 'New Source Topic')

    def test_resolution_never_changes_book_mode_or_narration_progress(self):
        before = (self.mode.active, self.mode.book, self.mode.position, self.mode.epoch, copy.deepcopy(self.mode.store))
        self.resolve('{book}', scheduled=True, occurrence='no-playback')
        self.assertEqual((self.mode.active, self.mode.book, self.mode.position, self.mode.epoch, self.mode.store), before)
        self.assertEqual(self.mode.cache, {}, 'roulette should not populate narration/image cache')

    def test_weighted_title_and_section_options_are_traceable(self):
        weights = {'book.source': {self.ids['River Gardens']: 0, self.ids['Signals at Night']: 4}}
        result = self.resolve('{book}', weights=weights)
        self.assertEqual(result['values']['book'], 'Signals at Night')
        self.assertEqual(result['rolls'][0]['candidates'][0]['weight'], 0)
        self.assertEqual(result['rolls'][0]['candidates'][1]['weight'], 4)
        self.assertEqual(result['rolls'][0]['total'], 2)
        with self.assertRaisesRegex(B.BookRouletteError, 'disabled'):
            self.resolve('{book}', weights={'book.source': {r['id']: 0 for r in self.mode.catalog.values()}})

    def test_booktime_sentence_alias_is_scoped_and_literal_tokens_stay_literal(self):
        result = self.resolve('{book}', booktime=True)
        text = '{book} {sentence} {{book}} {one|two} {stationname}'
        ordinary = B.expand(text, result)
        self.assertIn('{sentence}', ordinary)
        special = B.expand(text, result, booktime=True)
        self.assertIn(result['values']['booksentence'], special)
        self.assertIn('{{book}}', special); self.assertIn('{one|two}', special); self.assertIn('{stationname}', special)
        self.assertNotIn('{booksentence}', B.expand('{booksentence}', result))

    def test_async_messages_bind_system_and_current_user_without_editing_history(self):
        messages = [{'role': 'system', 'content': 'Read {booksentence} from {book}'},
                    {'role': 'user', 'content': 'Old {book:Signals at Night}'},
                    {'role': 'assistant', 'content': 'Old {book}'},
                    {'role': 'user', 'content': 'Discuss {booksegment} from {book:River Gardens}'}]
        before = copy.deepcopy(messages)
        result = asyncio.run(B.expand_messages(messages, self.service, weighted=self.pick))
        self.assertEqual(messages, before)
        self.assertEqual(result[1:3], messages[1:3])
        self.assertIn('River Gardens', result[0]['content']); self.assertIn('River Gardens', result[3]['content'])
        self.assertNotIn('{booksentence}', result[0]['content'])
        self.assertTrue(all(c['thread'] == threading.get_ident() for c in self.calls))

    def test_token_catalogue_advertises_book_sources(self):
        labels = [r['slot'] for r in h3_slots.catalogue()]
        for name in B.NAMES:
            self.assertIn('{' + name + '}', labels)
        self.assertEqual(h3_slots.tokens('{book} {booksentence} {booktopic}'), ['book', 'booksentence', 'booktopic'])

    def test_pdf_without_outline_reports_page_and_preserves_exact_source(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter(); page = writer.add_blank_page(width=300, height=420)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 24 390 Td (The lighthouse guided the boats. The keeper watched the harbour. Every boat returned safely.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.add_metadata({'/Title': 'Harbour Notes', '/Subject': 'Coastal Navigation'})
        with (self.shelf / 'harbour.pdf').open('wb') as file:
            writer.write(file)
        self.mode.scan()
        result = self.resolve('{book:Harbour Notes} {bookchapter} {booksentence}')
        self.assertEqual(result['values']['bookchapter'], 'page 1 (chapter not supplied)')
        self.assertEqual(result['source']['chapter_basis'], 'page')
        self.assertEqual(result['values']['booksentence'], 'The lighthouse guided the boats.')
        self.assertEqual(result['values']['booktopic'], 'Coastal Navigation')

    def test_pdf_outline_uses_actual_chapter_label(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter(); page = writer.add_blank_page(width=300, height=420)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 24 390 Td (The lighthouse guided the boats. The keeper watched the harbour.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.add_outline_item('The Lighthouse Keepers', 0)
        writer.add_metadata({'/Title': 'The Keeper Guide'})
        with (self.shelf / 'outline.pdf').open('wb') as file:
            writer.write(file)
        self.mode.scan()
        result = self.resolve('{book:The Keeper Guide}')
        self.assertEqual(result['values']['bookchapter'], 'The Lighthouse Keepers')
        self.assertEqual(result['source']['chapter_basis'], 'pdf_outline')

    def test_unreadable_source_is_skipped_and_never_fabricated(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=300, height=420); writer.add_metadata({'/Title': 'A Blank Scanned Book'})
        with (self.shelf / 'scanned.pdf').open('wb') as file:
            writer.write(file)
        self.mode.scan()
        result = self.resolve('{book}')
        self.assertEqual(result['values']['book'], 'River Gardens')
        self.assertEqual(result['skipped'][0]['title'], 'A Blank Scanned Book')
        self.assertIn('OCR', result['skipped'][0]['reason'])
        calls = len(self.calls)
        self.resolve('{book}')
        self.assertEqual(self.calls[calls]['labels'][0], 'River Gardens — Ada Reader')

    def test_readonly_receipts_and_catalogue_do_not_reroll_sources(self):
        result = self.resolve('{book}', occurrence='receipt', scheduled=True)
        count = len(self.calls)
        self.assertEqual(self.service.source_for('receipt'), result)
        self.assertEqual(self.service.source_for('missing'), {})
        self.assertEqual(self.service.history()[0]['source'], result['source'])
        self.assertEqual(self.service.status()['receipts'], 1)
        self.assertEqual(self.service.catalog_options()[0]['id'], self.ids['River Gardens'])
        self.assertNotIn('path', self.service.catalog_options()[0])
        self.assertEqual(len(self.calls), count)

    def test_duplicate_editions_count_as_the_same_book_for_scheduled_rotation(self):
        self.write_epub('alternate-edition.epub', 'River Gardens', 'Ada Reader', 'Water and Gardens',
                        [('Different Edition', '<p>The river glowed in the moonlight. The gardeners watched the water.</p>')])
        self.mode.scan()
        first = self.resolve('{book}', occurrence='first-edition', scheduled=True)
        second = self.resolve('{book}', occurrence='next-segment', scheduled=True)
        self.assertEqual(first['values']['book'], 'River Gardens')
        self.assertEqual(second['values']['book'], 'Signals at Night')

    def test_only_one_title_cannot_silently_repeat_in_scheduled_booktime(self):
        self.mode.catalog = {self.ids['River Gardens']: self.mode.row(self.ids['River Gardens'])}
        self.resolve('{book}', occurrence='first', scheduled=True)
        with self.assertRaisesRegex(B.BookRouletteError, 'different readable title'):
            self.resolve('{book}', occurrence='second', scheduled=True)
        self.assertEqual(len(self.service.state['receipts']), 1)

    def test_async_parallel_occurrences_do_not_select_the_same_title(self):
        async def go():
            return await asyncio.gather(*[self.service.resolve_async('{book}', weighted=self.pick, occurrence=name, scheduled=True)
                                          for name in ('first', 'second')])
        results = asyncio.run(go())
        self.assertNotEqual(results[0]['source']['book_id'], results[1]['source']['book_id'])

    def test_source_phrases_are_actual_contiguous_text(self):
        passage = 'The light flickers. Silver boats follow the harbour lanterns.'
        rows = B._topics({'subjects': []}, {'basis': 'page'}, passage)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row['label'], passage)
        self.assertNotIn('flickers Silver', [row['label'] for row in rows])

    def test_closing_quotes_and_parentheses_do_not_merge_source_sentences(self):
        self.assertEqual(B._split('He said "Go home." Then he left. (The gate shut.) She stayed.'),
                         ['He said "Go home."', 'Then he left. (The gate shut.)', 'She stayed.'])
        self.assertEqual(B._split('Dr. Rowan whispered "Good night." The river slept.'),
                         ['Dr. Rowan whispered "Good night."', 'The river slept.'])

    def test_empty_library_does_not_create_a_fake_book(self):
        self.mode.catalog = {}
        with self.assertRaisesRegex(B.BookRouletteError, 'no available'):
            self.resolve('{book}')


if __name__ == '__main__':
    unittest.main()
