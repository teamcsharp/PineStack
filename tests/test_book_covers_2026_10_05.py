"""[book-covers] The books show their own covers (#1587, 2026-10-05).

Small EPUBs are built in a temporary folder: one names its cover in the package, one carries the
cover as its first chapter's picture, one has no picture at all. The PDF side reuses the reader's
first-page render and is covered by the reader's own tests.

Run from the repo root (needs Pillow, as the station has):  python3 -m unittest tests.test_book_covers_2026_10_05
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the repo root, however this file is run

from book_preview import BookPreview  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the station has Pillow; a desk without it skips the picture checks
    Image = None

CONTAINER = ('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
             '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')


def picture(width=800, height=1200, colour=(200, 40, 60)):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), colour).save(buffer, format='PNG')
    return buffer.getvalue()


def opf(manifest_items, cover_meta=None, spine=('c1',)):
    meta = '<meta name="cover" content="%s"/>' % cover_meta if cover_meta else ''
    items = ''.join('<item id="%s" href="%s" media-type="%s"%s/>' % (i, h, m, (' properties="%s"' % p) if p else '') for i, h, m, p in manifest_items)
    refs = ''.join('<itemref idref="%s"/>' % s for s in spine)
    return ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="u">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="u">urn:uuid:1</dc:identifier><dc:title>T</dc:title>%s</metadata>'
            '<manifest>%s</manifest><spine>%s</spine></package>' % (meta, items, refs))


def epub(path, members):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', CONTAINER)
        for name, payload in members.items():
            archive.writestr(name, payload)


@unittest.skipIf(Image is None, 'Pillow is not installed here; the station has it')
class BookCoversTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.preview = BookPreview(self.root / 'data')

    def row(self, name, kind='epub'):
        return {'id': name, 'title': name, 'kind': kind, 'path': str(self.root / (name + '.epub')), 'stamp': 1}

    def chapter(self, body):
        return '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head><body>%s</body></html>' % body

    def test_the_cover_the_package_names_is_the_cover(self):
        epub(self.root / 'named.epub', {
            'OEBPS/content.opf': opf([('cov', 'images/front.png', 'image/png', None), ('c1', 'c1.xhtml', 'application/xhtml+xml', None)], cover_meta='cov'),
            'OEBPS/images/front.png': picture(), 'OEBPS/c1.xhtml': self.chapter('<p>Hello.</p>')})
        got = self.preview.cover(self.row('named'))
        self.assertIsNotNone(got)
        payload, mime = got
        self.assertEqual(mime, 'image/jpeg')
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.format, 'JPEG'); self.assertEqual(image.width, 420); self.assertEqual(image.height, 630)
            self.assertAlmostEqual(image.getpixel((200, 300))[0], 200, delta=12)
        kept = list((self.root / 'data' / 'named' / 'preview').rglob('cover.jpg'))
        self.assertEqual(len(kept), 1, 'kept beside the preview')
        again, _ = self.preview.cover(self.row('named'))
        self.assertEqual(again, kept[0].read_bytes(), 'served from what was kept')

    def test_the_cover_image_property_and_a_cover_named_item_count_too(self):
        epub(self.root / 'property.epub', {
            'OEBPS/content.opf': opf([('img9', 'art/x.jpg', 'image/jpeg', 'cover-image'), ('c1', 'c1.xhtml', 'application/xhtml+xml', None)]),
            'OEBPS/art/x.jpg': picture(600, 900, (20, 160, 90)), 'OEBPS/c1.xhtml': self.chapter('<p>Hello.</p>')})
        payload, _ = self.preview.cover(self.row('property'))
        with Image.open(io.BytesIO(payload)) as image:
            self.assertAlmostEqual(image.getpixel((100, 100))[1], 160, delta=12)
        epub(self.root / 'byname.epub', {
            'OEBPS/content.opf': opf([('pic', 'Cover.jpeg', 'image/jpeg', None), ('c1', 'c1.xhtml', 'application/xhtml+xml', None)]),
            'OEBPS/Cover.jpeg': picture(500, 700, (30, 30, 220)), 'OEBPS/c1.xhtml': self.chapter('<p>Hello.</p>')})
        payload, _ = self.preview.cover(self.row('byname'))
        with Image.open(io.BytesIO(payload)) as image:
            self.assertAlmostEqual(image.getpixel((100, 100))[2], 220, delta=12)

    def test_the_first_picture_of_the_first_chapter_is_the_last_resort(self):
        epub(self.root / 'firstpic.epub', {
            'OEBPS/content.opf': opf([('c1', 'text/c1.xhtml', 'application/xhtml+xml', None), ('p', 'images/plate.png', 'image/png', None)]),
            'OEBPS/text/c1.xhtml': self.chapter('<div><img src="../images/plate.png" alt=""/></div><p>Hello.</p>'),
            'OEBPS/images/plate.png': picture(300, 450, (250, 220, 10))})
        payload, _ = self.preview.cover(self.row('firstpic'))
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.width, 300, 'a small picture is not blown up')
            self.assertAlmostEqual(image.getpixel((100, 100))[0], 250, delta=12)

    def test_a_book_with_no_picture_says_so_once(self):
        epub(self.root / 'plain.epub', {
            'OEBPS/content.opf': opf([('c1', 'c1.xhtml', 'application/xhtml+xml', None)]),
            'OEBPS/c1.xhtml': self.chapter('<p>Only words.</p>')})
        self.assertIsNone(self.preview.cover(self.row('plain')))
        marker = list((self.root / 'data' / 'plain' / 'preview').rglob('cover.none'))
        self.assertEqual(len(marker), 1)
        self.assertIsNone(self.preview.cover(self.row('plain')))

    def test_a_tiny_or_broken_picture_is_no_cover(self):
        epub(self.root / 'tiny.epub', {
            'OEBPS/content.opf': opf([('cov', 'dot.png', 'image/png', None), ('c1', 'c1.xhtml', 'application/xhtml+xml', None)], cover_meta='cov'),
            'OEBPS/dot.png': picture(8, 8), 'OEBPS/c1.xhtml': self.chapter('<p>Hello.</p>')})
        self.assertIsNone(self.preview.cover(self.row('tiny')))
        epub(self.root / 'broken.epub', {
            'OEBPS/content.opf': opf([('cov', 'bad.jpg', 'image/jpeg', None), ('c1', 'c1.xhtml', 'application/xhtml+xml', None)], cover_meta='cov'),
            'OEBPS/bad.jpg': b'not a picture at all', 'OEBPS/c1.xhtml': self.chapter('<p>Hello.</p>')})
        self.assertIsNone(self.preview.cover(self.row('broken')))

    def test_the_shelf_asks_for_the_books_own_cover_and_the_road_exists(self):
        source = (Path(__file__).resolve().parent.parent / 'book_mode.py').read_bytes().decode('utf-8')
        self.assertIn("/cover.img?t={g['media_sign'](row['id'])}", source)
        self.assertIn("@app.get('/api/books/{book}/cover.img')", source)
        self.assertIn("found=await disk(preview.cover,row)", source)
        self.assertIn("@app.get('/api/books/{book}/cover.svg')", source, 'the title card road stays')


if __name__ == '__main__':
    unittest.main()
