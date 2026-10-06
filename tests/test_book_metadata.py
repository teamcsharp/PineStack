"""Regressions for identifier metadata and unchanged-source title-card migration."""
import hashlib, json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
import book_mode


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.shelf = self.root / 'shelf'
        self.shelf.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def epub(self, filename, title='0312421729', author='Unknown', front=None):
        path = self.shelf / filename
        front = front if front is not None else [
            ('cover.xhtml', '<html><head><title>Cover</title></head><body>cover</body></html>'),
            ('front.xhtml', '<html><head><title>Letters to a Young Novelist</title></head><body>front</body></html>'),
            ('chapter.xhtml', '<html><head><title>Chapter 1</title></head><body>chapter text</body></html>')
        ]
        manifest = ''.join(f'<item id="p{i}" href="{name}" media-type="application/xhtml+xml"/>' for i, (name, _) in enumerate(front))
        spine = ''.join(f'<itemref idref="p{i}"/>' for i in range(len(front)))
        opf = f'<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            archive.writestr('OPS/book.opf', opf)
            for name, content in front:
                archive.writestr('OPS/' + name, content)
        return path

    def test_identifier_package_uses_front_title_and_unambiguous_filename_author(self):
        path = self.epub('Letters to a Young Novelist_Mario Vargas Llosa_liber3.epub')
        reads = []
        original = zipfile.ZipExtFile.read
        def bounded_read(source, size=-1):
            reads.append((source.name, size))
            return original(source, size)
        with patch('zipfile.ZipExtFile.read', bounded_read), patch('library_extract.read_document', side_effect=AssertionError('full book extraction')):
            metadata = book_mode.book_metadata(path)
        self.assertEqual(metadata['title'], 'Letters to a Young Novelist')
        self.assertEqual(metadata['author'], 'Mario Vargas Llosa')
        self.assertEqual(metadata['title_source'], 'frontmatter')
        front_reads = [(name, size) for name, size in reads if name.endswith('.xhtml')]
        self.assertEqual([name for name, _ in front_reads], ['OPS/cover.xhtml', 'OPS/front.xhtml'])
        self.assertTrue(all(0 < size <= 65536 for _, size in front_reads))

    def test_ambiguous_author_and_translator_filename_stays_unknown(self):
        path = self.epub('Letters to a Young Novelist_Mario Vargas Llosa, Natasha Wimmer_liber3.epub')
        metadata = book_mode.book_metadata(path)
        self.assertEqual(metadata['title'], 'Letters to a Young Novelist')
        self.assertEqual(metadata['author'], 'Unknown')
        with zipfile.ZipFile(path) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        members['OPS/front.xhtml'] = b'<html><head><title>Letters to a Young Novelist</title><meta name="author" content="Mario Vargas Llosa"/></head><body><p class="translator">Natasha Wimmer</p></body></html>'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        self.assertEqual(book_mode.book_metadata(path)['author'], 'Mario Vargas Llosa')

    def test_isbn13_and_large_generic_front_use_readable_filename(self):
        path = self.epub('A Real Title_Jane Author_liber7.epub', title='ISBN-13: 978-0-306-40615-7', front=[
            (f'part{i}.xhtml', '<html><head><title>Contents</title></head><body>' + 'x' * 70000 + '</body></html>')
            for i in range(4)
        ])
        reads = []
        original = zipfile.ZipExtFile.read
        def bounded_read(source, size=-1):
            reads.append((source.name, size))
            return original(source, size)
        with patch('zipfile.ZipExtFile.read', bounded_read):
            metadata = book_mode.book_metadata(path)
        self.assertEqual(metadata['title'], 'A Real Title')
        self.assertEqual(metadata['author'], 'Jane Author')
        self.assertEqual(metadata['title_source'], 'filename')
        front_reads = [(name, size) for name, size in reads if name.endswith('.xhtml')]
        self.assertEqual(len(front_reads), 3)
        self.assertTrue(all(0 < size <= 65536 for _, size in front_reads))

    def test_1984_and_non_identifier_numeric_titles_keep_metadata_without_front_reads(self):
        for title in ('1984', '0312421728', '9780306406158'):
            with self.subTest(title=title):
                path = self.epub(f'download_{title}.epub', title=title, author='George Orwell')
                opened = []
                original = zipfile.ZipFile.open
                def track(archive, name, *args, **kwargs):
                    opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
                    return original(archive, name, *args, **kwargs)
                with patch('zipfile.ZipFile.open', track):
                    metadata = book_mode.book_metadata(path)
                self.assertEqual(metadata['title'], title)
                self.assertEqual(metadata['author'], 'George Orwell')
                self.assertEqual(metadata['title_source'], 'metadata')
                self.assertFalse(any(name.endswith('.xhtml') for name in opened))

    def test_declared_latin1_front_title_keeps_accents(self):
        path = self.epub('generic_download.epub', front=[
            ('front.xhtml', '<?xml version="1.0" encoding="ISO-8859-1"?><html><head><title>El sueño del celta</title><meta name="author" content="Mario Vargas Llosa"/></head><body>front</body></html>'.encode('iso-8859-1'))
        ])
        metadata = book_mode.book_metadata(path)
        self.assertEqual(metadata['title'], 'El sueño del celta')
        self.assertEqual(metadata['author'], 'Mario Vargas Llosa')
        self.assertEqual(metadata['title_source'], 'frontmatter')

    def test_cache_version_migrates_same_stamp_and_rebuilds_identifier_card(self):
        path = self.epub('Letters to a Young Novelist_Mario Vargas Llosa_liber3.epub')
        stat = path.stat()
        stamp = f'{stat.st_size}:{stat.st_mtime_ns}'
        book = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        cache = self.root / 'cache'
        cache.mkdir()
        old = dict(id=book, path=str(path), kind='epub', stamp=stamp, title='0312421729', author='Unknown', title_source='metadata', metadata_version=2)
        (cache / 'catalog.json').write_text(json.dumps({book: old}), encoding='utf-8')
        mode = book_mode.BookMode(cache, [str(self.shelf)])
        old_version = mode.cover_version(book)
        old_cover = mode.cover(book)
        self.assertIn(b'0312421729', old_cover)
        mode.scan()
        row = mode.row(book)
        self.assertEqual(row['stamp'], stamp)
        self.assertEqual(row['title'], 'Letters to a Young Novelist')
        self.assertEqual(row['metadata_version'], book_mode.CATALOG_VERSION)
        self.assertGreater(book_mode.CATALOG_VERSION, 2)
        self.assertNotEqual(mode.cover_version(book), old_version)
        cover = mode.cover(book)
        self.assertNotIn(b'0312421729', cover)
        self.assertIn(b'Letters to a Young Novelist', cover)
        self.assertIn(b'Mario Vargas Llosa', cover)
        saved = json.loads((cache / book / 'cover.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['stamp'], stamp)
        self.assertEqual(saved['title'], row['title'])
        with patch('book_mode.book_metadata', side_effect=AssertionError('corrected metadata reread')):
            reloaded = book_mode.BookMode(cache, [str(self.shelf)])
            reloaded.scan()
        self.assertEqual(reloaded.cover(book), cover)


if __name__ == '__main__':
    unittest.main()

