import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import app


class NewspaperTests(unittest.IsolatedAsyncioTestCase):
    async def test_tint_cannot_reintroduce_another_image_story_sentence(self):
        original = 'The woman brought a repair plan to the courtyard meeting before neighbours offered their suggestions.'
        repeated = 'The red bicycle carried the tools to the station while the repair team opened the gates.'
        story = {'slug': 'local-life', 'body': original, 'meta': {'copy_origin': 'local fallback',
            'gallery_subjects': [{'image': 'woman.png'}], 'tint': {'required': 1, 'changed': 0,
                'attempted': 0, 'eligible': 1, 'paragraphs': []}}}
        with (mock.patch.dict(app._PAPER_PRESS, {'attempted_stories': 0, 'attempted_paras': 0,
                'city_copy': {'woman.png': original, 'bike.png': repeated}}),
              mock.patch.object(app, 'PAPER_TINT_STORIES', 100),
              mock.patch.object(app, 'PAPER_TINT_PARAS', 100),
              mock.patch.object(app, 'paper_tint_left', return_value=100),
              mock.patch.object(app, 'crystal_tint_two_pass', return_value=True),
              mock.patch.object(app, 'crystal_active', return_value=[{}]),
              mock.patch.object(app, 'tint_should_stop', return_value=''),
              mock.patch.object(app, 'paper_tint_units', return_value=[{'key': 'body:0', 'text': original}]),
              mock.patch.object(app, 'crystal_line', return_value=repeated),
              mock.patch.object(app, 'tint_output_ready', return_value=True),
              mock.patch.object(app, '_tint_flow')):
            self.assertFalse(await app.paper_tint_story(story, 'verify'))
        self.assertEqual(story['body'], original)
        self.assertFalse(story['meta']['tint']['paragraphs'][0]['ok'])
        self.assertEqual(story['meta']['tint']['changed'], 0)

    def test_image_source_receipts_round_trip_and_recover_old_string_rows(self):
        seed = {'file': 'sample.md', 'mind': 'main', 'text': 'A neighbour said, "That is ours."', 'hash': 'abc'}
        for receipt in (seed, repr(seed)):
            meta = {'source_seed': seed, 'classifieds': [{'head': 'A local notice', 'source_seed': receipt}]}
            loaded, body, error = app._fm_load(app._fm_dump(meta) + '\nAn actual story.')
            self.assertEqual(error, '')
            self.assertEqual(loaded['source_seed'], seed)
            self.assertEqual(loaded['classifieds'][0]['source_seed'], seed)

    async def test_city_batch_has_one_unambiguous_json_contract(self):
        response = [{'index': 0, 'headline': 'A neighbourhood event', 'body': 'The woman helped with water repairs.'}]
        with (mock.patch.object(app, 'load_settings', return_value={'model': 'writer'}),
              mock.patch.object(app, 'PAPER_MODEL', 'writer'),
              mock.patch.object(app, 'paper_press_left', return_value=100),
              mock.patch.dict(app._PAPER_PRESS, {'writer_calls': 0}),
              mock.patch.object(app, 'model_ctx', return_value=8192),
              mock.patch.object(app, '_paper_say'),
              mock.patch.object(app, 'call_ollama', new=mock.AsyncMock(return_value={'message': {'content': json.dumps(response)}})) as writer):
            got = await app._paper_write_inner('City Correspondents', 'Make local situations.', 'Exact source material.', (250, 800))
        self.assertEqual(json.loads(got['body']), response)
        system = writer.call_args.kwargs['messages'][0]['content']
        self.assertIn('ONLY a valid JSON array', system)
        self.assertNotIn('EXACTLY this shape', system)
        self.assertIn('invented city situations are permitted', system)

    def test_printed_classified_copy_is_not_recycled_as_sidebar_filler(self):
        body = 'The red bicycle reached the station for the neighbourhood repair meeting.'
        edition = {'station': 'Pine Box FM', 'articles': [{'body': 'Local report.',
            'meta': {'classifieds': [{'head': 'Bicycle meeting', 'body': body, 'image': '/api/image/bike.png'}]}}]}
        self.assertNotIn(body, [r['body'] for r in app._paper_filler_rows(edition)])

    def test_exhausted_filler_pool_does_not_repeat_copy_to_fill_the_page(self):
        pool, used = [{'head': 'One unique notice', 'body': 'One unique body.'}], set()
        with mock.patch.object(app, '_paper_filler_html', return_value=('<div>Unique</div>', 40)):
            first, _ = app._paper_fill(800, 200, {}, pool, used)
            second, _ = app._paper_fill(800, 200, {}, pool, used)
        self.assertEqual(first, ['<div>Unique</div>'])
        self.assertEqual(second, [])

    async def test_source_passages_remain_distinct_when_press_writer_budget_is_gone(self):
        docs = [Path("water.md"), Path("music.md")]
        bodies = {docs[0]: "Water from the community faucet stopped flowing across the courtyard during the evening meeting.",
                  docs[1]: "The band rehearsed its music beside the station while neighbours carried instruments through the square."}
        with (mock.patch.dict(app._PAPER_PRESS, {"deadline": 1, "seed_hashes": set(), "seed_files": set(), "seed_bag": []}),
              mock.patch.object(app, 'mind_id', return_value='selected'),
              mock.patch.object(app, 'speakbox_files', return_value=docs),
              mock.patch.object(app, 'speakbox_body', side_effect=bodies.get),
              mock.patch.object(app, 'speakbox_quote', new=mock.AsyncMock()) as harvest):
            seeds = await app.paper_seeds(2)
        self.assertEqual(len(seeds), 2)
        self.assertEqual(len({s['hash'] for s in seeds}), 2)
        self.assertTrue(all(s['mind'] == 'selected' and s['text'] == bodies[Path(s['file'])] for s in seeds))
        harvest.assert_not_awaited()

    async def test_late_writer_falls_back_without_waiting_for_model_queue(self):
        async def late(*args):
            await asyncio.sleep(100)
        with (mock.patch.object(app, '_PAPER_WRITER_GATE', asyncio.Semaphore(1)),
              mock.patch.object(app, 'paper_press_left', return_value=0.01),
              mock.patch.object(app, '_paper_say'),
              mock.patch.object(app, '_paper_write_inner', side_effect=late)):
            self.assertEqual(await app.paper_write('City Correspondents', 'brief', 'material'), {})

    async def test_concurrent_writer_desks_wait_in_order_and_keep_material(self):
        entered, completed = [], []
        release = asyncio.Event()
        active, peak = 0, 0

        async def write(desk, brief, material, words, reserve):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.append((desk, brief, material, words, reserve))
            try:
                await release.wait()
                await asyncio.sleep(0)
                completed.append(desk)
                return {'headline': desk, 'body': material}
            finally:
                active -= 1

        with (mock.patch.object(app, '_PAPER_WRITER_GATE', asyncio.Semaphore(1)),
              mock.patch.object(app, '_paper_write_inner', side_effect=write)):
            pending = [asyncio.create_task(app.paper_write(
                f'desk-{i}', f'brief-{i}', f'full material {i}', (40, 80), i == 3))
                for i in range(4)]
            await asyncio.sleep(0)
            self.assertEqual(len(entered), 1)
            self.assertTrue(all(not task.done() for task in pending))
            release.set()
            result = await asyncio.gather(*pending)
        self.assertEqual(peak, 1)
        self.assertEqual(completed, [f'desk-{i}' for i in range(4)])
        self.assertEqual([row['body'] for row in result],
                         [f'full material {i}' for i in range(4)])
        self.assertEqual(entered[-1], ('desk-3', 'brief-3', 'full material 3', (40, 80), True))

    def test_reader_keeps_short_paragraphs_lists_quotes_and_repeated_text(self):
        document = '<nav><p>Unrelated navigation is long enough to look like prose.</p></nav><article><h1>Brief report</h1><p>It stopped.</p><h2>Afterward</h2><p>Yes.</p><ul><li>One</li><li>Two</li></ul><blockquote>Go on.</blockquote><p>Yes.</p></article>'
        row = app.newsread_extract(document, 'https://example.org/report')
        self.assertEqual(row['paragraphs'], ['It stopped.', 'Afterward', 'Yes.', 'One', 'Two', 'Go on.', 'Yes.'])
        self.assertFalse(row['truncated'])
        self.assertEqual(row['notice'], '')

    def test_reader_uses_complete_publisher_article_body(self):
        body = 'First paragraph.\n\nThe full middle paragraph that the visible preview omitted.\n\nThe last sentence.'
        data = {'@graph': [{'@type': 'NewsArticle', 'headline': 'Complete report',
            'articleBody': body, 'author': {'name': 'Reporter'}, 'datePublished': '2026-09-06'}]}
        row = app.newsread_extract('<article><p>Preview only.</p></article><script type="application/ld+json">' + json.dumps(data) + '</script>', 'https://example.org/report')
        self.assertEqual(row['paragraphs'], body.split('\n\n'))
        self.assertEqual(row['byline'], 'Reporter')
        self.assertEqual(row['title'], 'Complete report')

    def test_reader_discloses_limits_and_fixes_relative_images(self):
        with mock.patch.object(app, 'NEWSREAD_CHARS', 10):
            row = app.newsread_extract('<article><p>A paragraph that reaches the cap.</p><p>The ending.</p></article>', 'https://example.org/news/story')
        self.assertTrue(row['truncated'])
        self.assertIn('size limit', row['notice'])
        self.assertEqual(app._newsread_abs('https://example.org/news/story', '../photo.png?a=1&amp;b=2'), 'https://example.org/photo.png?a=1&b=2')
        for url in ('http://127.0.0.1/x', 'http://[::1]/x', 'http://[fd00::1]/x', 'http://localhost./x', 'http://user:password@example.org/x'):
            self.assertEqual(app.newsread_allow(url), '', url)

    async def test_reader_rechecks_redirect_before_any_private_connection(self):
        requested = []
        def handler(request):
            requested.append(str(request.url))
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with mock.patch.object(app, '_newsread_public', side_effect=[True, False]):
                with self.assertRaisesRegex(ValueError, 'public web address'):
                    await app._newsread_fetch(client, 'https://example.org/story')
        self.assertEqual(requested, ['https://example.org/story'])

    async def test_reader_enforces_download_limit(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='x' * 101))) as client:
            with (mock.patch.object(app, '_newsread_public', return_value=True),
                  mock.patch.object(app, 'NEWSREAD_HTML_MAX', 100)):
                with self.assertRaisesRegex(ValueError, 'size limit'):
                    await app._newsread_fetch(client, 'https://example.org/story')

    def test_reader_caches_original_and_redirected_url_and_versions(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(app, 'NEWSREAD_DIR', Path(folder)):
            row = {'ok': True, 'reader_version': app.NEWSREAD_VERSION, 'fetched_at': app.time.time(),
                   'url': 'https://example.org/new', 'requested_url': 'https://example.org/old'}
            app.newsread_save(row)
            self.assertIsNotNone(app.newsread_cached(row['url']))
            self.assertIsNotNone(app.newsread_cached(row['requested_url']))
            with mock.patch.object(app, 'NEWSREAD_VERSION', 999):
                self.assertIsNone(app.newsread_cached(row['url']))

    async def test_classifieds_keep_every_subject_when_photographs_are_already_used(self):
        pictures = [
            {'name': 'resident.png', 'url': '/image/resident.png', 'kind': 'described', 'desc': 'A woman in a copper apron'},
            {'name': 'bicycle.png', 'url': '/image/bicycle.png', 'kind': 'shown', 'desc': 'A red bicycle with a wicker basket'},
            {'name': 'cat.png', 'url': '/image/cat.png', 'kind': 'shown', 'desc': 'A cat with a blue collar'},
        ]
        material = {'pictures': pictures, 'since': 1, 'station': 'Pine Box', 'host': 'Tony', 'cohost': 'Skip',
                    '_pictures_used': {p['name'] for p in pictures}}
        with (mock.patch.dict(app._PAPER_PRESS, {'gallery_subjects': []}),
              mock.patch.object(app, 'paper_seeds', return_value=[]),
              mock.patch.object(app, 'paper_write', return_value={}),
              mock.patch.object(app, 'paper_seeds_used')):
            story = await app._desk_classifieds(material)
            city = await app._desk_city(material)
        notices = story['meta']['classifieds']
        self.assertEqual({n['source_image'] for n in notices}, {p['name'] for p in pictures})
        resident = next(n for n in notices if n['source_image'] == 'resident.png')
        self.assertTrue(resident['head'].startswith('SERVICES:'))
        self.assertNotIn('image', story['meta'], 'an already printed photograph is not printed twice')
        self.assertIsNone(city, 'image stories already printed on the noticeboard are not repeated')
        for picture in pictures:
            self.assertTrue(any(picture['desc'].lower() in row['body'].lower() for row in notices))
        from newspaper_city import sentences
        seen = set()
        for notice in notices:
            self.assertFalse(seen & sentences(notice['body']))
            seen.update(sentences(notice['body']))

    def test_newspaper_discussion_rotates_article_details_and_expires(self):
        original = copy.deepcopy(app._PAPER_DISCUSSION)
        try:
            app._PAPER_DISCUSSION.clear()
            edition = {'at': 1000, 'articles': [
                {'file': f'{i}.md', 'meta': {'headline': f'Story {i}', 'section': 'news'},
                 'body': f'The neighbourhood story {i} has concrete facts, named places, and a consequence for the next hour.'}
                for i in range(4)]}
            with (mock.patch.object(app, 'paper_latest_id', return_value='edition'),
                  mock.patch.object(app, 'paper_edition_read', return_value=edition),
                  mock.patch.object(app, '_tint_flow'),
                  mock.patch.object(app.time, 'time', return_value=2000)):
                first = app.paper_discussion_context()
                second = app.paper_discussion_context()
                self.assertTrue(first['articles'])
                self.assertTrue(set(r['file'] for r in first['articles']).isdisjoint(r['file'] for r in second['articles']))
                self.assertIn('concrete facts', first['prompt'])
                self.assertEqual(app.paper_discussion_context(), {})
                with mock.patch.object(app.time, 'time', return_value=1000 + 7 * 3600):
                    self.assertEqual(app.paper_discussion_context(), {})
        finally:
            app._PAPER_DISCUSSION.clear()
            app._PAPER_DISCUSSION.update(original)

    def test_image_notice_details_and_source_reach_later_dj_discussion(self):
        original = copy.deepcopy(app._PAPER_DISCUSSION)
        seed = {'file': 'water.md', 'text': 'The courtyard water supply needs a repair.'}
        try:
            app._PAPER_DISCUSSION.clear()
            edition = {'at': 1000, 'articles': [{'file': 'classifieds.md', 'body': '',
                'meta': {'classifieds': [{'source_image': 'bicycle.png',
                    'head': 'Bicycle owner joins the courtyard repair',
                    'body': 'The red bicycle owner brought tools to the courtyard water meeting and offered a delivery route.',
                    'source_seed': seed}]}}]}
            with (mock.patch.object(app, 'paper_latest_id', return_value='edition'),
                  mock.patch.object(app, 'paper_edition_read', return_value=edition),
                  mock.patch.object(app, '_tint_flow'),
                  mock.patch.object(app.time, 'time', return_value=2000)):
                context = app.paper_discussion_context()
            self.assertIn('brought tools to the courtyard water meeting', context['prompt'])
            self.assertEqual(context['articles'][0]['source_seed'], seed)
            self.assertEqual(context['articles'][0]['file'], 'classifieds.md#bicycle.png')
        finally:
            app._PAPER_DISCUSSION.clear()
            app._PAPER_DISCUSSION.update(original)

    async def test_sale_column_offers_visible_goods_and_never_portrait_subjects(self):
        material = {'station': 'Pine Box', 'pictures': [
            {'name': 'person.png', 'url': '/image/person.png', 'kind': 'selling', 'desc': 'A woman in a green coat', 'price': 50},
            {'name': 'bike.png', 'url': '/image/bike.png', 'kind': 'selling', 'desc': 'A photograph of a red bicycle', 'price': 40},
        ]}
        with (mock.patch.object(app, 'paper_seeds', return_value=[]),
              mock.patch.object(app, 'paper_write', return_value={}),
              mock.patch.object(app, 'paper_seeds_used')):
            story = await app._desk_forsale(material)
        self.assertIn('red bicycle', story['body'])
        self.assertNotIn('woman', story['body'])
        self.assertNotIn('photograph of', story['body'])
        self.assertEqual(story['meta']['image'], '/image/bike.png')


if __name__ == '__main__':
    unittest.main()
