import copy
import re
import unittest
from unittest import mock

import app


class NewspaperReferenceStyleTests(unittest.TestCase):
    def edition(self, image=True):
        return {'id': '1067-reference', 'at': 1788758400, 'kind': 'hourly',
                'station': 'A & B FM', 'articles': [
                    {'file': '01-lead.md', 'meta': {'headline': 'Residents open the riverside garden',
                        'deck': 'An unchanged introduction to the story.', 'section': 'front', 'priority': 1,
                        **({'image': '/api/image/garden.png', 'caption': 'The riverside garden at dawn.'} if image else {})},
                     'body': '\n\n'.join('Paragraph %02d describes the garden opening and the neighbours who planted the trees. ' % i * 5 for i in range(18))},
                    {'file': '02-news.md', 'meta': {'headline': 'Musicians rehearse on the square', 'section': 'news'},
                     'body': 'The orchestra rehearsed on the square before the evening concert.'}]}

    def test_reference_layout_preserves_all_paragraphs_and_image_once(self):
        edition = self.edition()
        before = copy.deepcopy(edition)
        html = app.paper_render_html(edition, 'broadsheet')
        self.assertIn('reference-lead', html)
        self.assertIn('data:font/ttf;base64,', html)
        self.assertEqual(html.count('src="/api/image/garden.png"'), 1)
        for paragraph in edition['articles'][0]['body'].split('\n\n'):
            self.assertEqual(html.count(paragraph.strip()), 1)
        self.assertIn('The riverside garden at dawn.', html)
        self.assertEqual(edition, before)
        self.assertIn('height:1705px', html)

    def test_tabloid_remains_distinct_and_text_only_lead_is_usable(self):
        tabloid = app.paper_render_html(self.edition(), 'tabloid')
        self.assertNotIn('class="reference-photo"', tabloid)
        self.assertNotIn('Pine Gazette Blackletter', tabloid)
        self.assertIn('class="tabloid', tabloid)
        self.assertIn('height:1305px', tabloid)
        ordinary = app.paper_render_html(self.edition(False))
        self.assertNotIn('class="reference-photo"', ordinary)
        self.assertIn('Residents open the riverside garden', ordinary)

    def test_full_station_masthead_escaped_and_custom_identity_kept(self):
        title = 'The A & B <FM> Gazette'
        html = app._paper_reference_masthead(title)
        self.assertIn('The A &amp; B &lt;FM&gt;', html)
        self.assertIn('>Gazette</span>', html)
        custom = app._paper_reference_masthead('Daily Signal')
        self.assertIn('>Daily Signal</span>', custom)
        self.assertNotIn('>Gazette</span>', custom)

    def test_missing_optional_font_keeps_reference_layout_css(self):
        with mock.patch.object(app.Path, 'read_bytes', side_effect=OSError('unavailable')):
            css = app._paper_reference_css()
        self.assertIn('.reference-lead{display:grid', css)
        self.assertNotIn('data:font', css)


if __name__ == '__main__':
    unittest.main()
