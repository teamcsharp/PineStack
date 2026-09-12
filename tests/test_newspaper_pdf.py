import copy
import unittest
from unittest import mock

import app


@unittest.skipIf(app.pdf_engine() is None, 'fpdf2 is unavailable')
class NewspaperPdfStyleTests(unittest.TestCase):
    def render(self, style='broadsheet', missing_font=False):
        from fpdf import FPDF
        from PIL import Image

        documents = []

        class ObservedPdf(FPDF):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.drawn_text = []
                self.drawn_images = []
                self.drawn_rects = []
                documents.append(self)

            def text(self, x, y, text='', *args, **kwargs):
                self.drawn_text.append((self.page, x, y, text, self.font_family))
                return super().text(x, y, text, *args, **kwargs)

            def image(self, *args, **kwargs):
                self.drawn_images.append((self.page, kwargs.copy()))
                return super().image(*args, **kwargs)

            def rect(self, x, y, w, h, *args, **kwargs):
                self.drawn_rects.append((self.page, x, y, w, h))
                return super().rect(x, y, w, h, *args, **kwargs)

            def add_font(self, *args, **kwargs):
                if missing_font:
                    raise FileNotFoundError('optional display font absent')
                return super().add_font(*args, **kwargs)

        paragraphs = [f'PARAGRAPH{i:02d} ' + ('The neighbours planted trees beside the riverside garden. ' * 12)
                      for i in range(18)]
        edition = {'id': 'pdf-reference', 'kind': 'hourly', 'at': 1788758400,
                   'station': 'A & B FM', 'articles': [
            {'file': 'lead.md', 'meta': {'headline': 'Residents open the riverside garden',
                'priority': 1, 'section': 'front', 'image': '/api/image/garden.png',
                'caption': 'GARDENCAPTION at dawn.', 'deck': 'A new place to meet.'},
             'body': '\n\n'.join(paragraphs)},
            {'file': 'second.md', 'meta': {'headline': 'Music on the square',
                'section': 'news', 'image': '/api/image/square.png',
                'caption': 'SQUARECAPTION before the concert.'},
             'body': 'FINALARTICLE The orchestra rehearsed beside the station before the evening concert.'}]}
        before = copy.deepcopy(edition)
        picture = Image.new('RGB', (64, 48), '#88aabb')
        with (mock.patch.object(app, 'pdf_engine', return_value=ObservedPdf),
              mock.patch.object(app, 'paper_masthead', return_value={
                  'masthead': 'The A & B FM Gazette', 'motto': 'Printed on the hour',
                  'sections': list(app.PAPER_SECTIONS), 'founded': '2026-09-04'}),
              mock.patch.object(app, 'pdf_plate_image', return_value=picture),
              mock.patch.object(app, 'pdf_story', wraps=app.pdf_story) as stories):
            blob = app.paper_pdf(edition, style)
        self.assertEqual(edition, before)
        self.assertTrue(blob.startswith(b'%PDF-'))
        self.assertEqual([c.args[1]['file'] for c in stories.call_args_list], ['lead.md', 'second.md'])
        document = documents[0]
        words = ' '.join(row[3] for row in document.drawn_text)
        for i in range(18):
            self.assertEqual(words.count(f'PARAGRAPH{i:02d}'), 1)
        for phrase in ('FINALARTICLE', 'SQUARECAPTION'):
            self.assertEqual(words.count(phrase), 1)
        if style == 'broadsheet':
            self.assertEqual(words.count('GARDENCAPTION'), 1)
        self.assertEqual(len(document.drawn_images), 2)
        for _, x, y, _, _ in document.drawn_text:
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x, document.w)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y, document.h)
        return blob, document, words

    def test_broadsheet_portrait_embedded_masthead_and_complete_content(self):
        blob, document, words = self.render()
        self.assertAlmostEqual(document.w, 220)
        self.assertAlmostEqual(document.h / document.w, 1.55)
        self.assertEqual(app.PAPER_PDF_GEOM['broadsheet'][5], 5)
        self.assertTrue(any(text == 'Gazette' and family == 'pineblackletter'
                            for _, _, _, text, family in document.drawn_text))
        self.assertTrue('The A & B FM' in words)
        self.assertIn(b'/FontFile2', blob)
        backgrounds = [r for r in document.drawn_rects
                       if r[1:3] == (0, 0) and abs(r[3] - 220) < .01 and abs(r[4] - 341) < .01]
        self.assertEqual(len(backgrounds), document.pages_count)

    def test_tabloid_keeps_a4_geometry_and_existing_faces(self):
        _, document, _ = self.render('tabloid')
        self.assertAlmostEqual(document.w, 210, places=2)
        self.assertAlmostEqual(document.h, 297, places=2)
        self.assertEqual(app.PAPER_PDF_GEOM['tabloid'][5], 3)
        self.assertFalse(any(row[4] == 'pineblackletter' for row in document.drawn_text))

    def test_missing_optional_masthead_font_keeps_complete_native_pdf(self):
        _, document, words = self.render(missing_font=True)
        self.assertIn('Gazette', words)
        self.assertTrue('The A & B FM' in words)
        self.assertEqual(document._pine_masthead_family, 'times')


if __name__ == '__main__':
    unittest.main()
