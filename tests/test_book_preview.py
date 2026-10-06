"""Formatted previews use source layout without touching playback or narration."""
import io, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import book_preview


class BookPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.preview=book_preview.BookPreview(self.root/'cache');self.base='/api/books/test/preview?t=signature&v=version'
        self.path=self.root/'typeset.epub'
        with zipfile.ZipFile(self.path,'w') as archive:
            archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>')
            archive.writestr('OEBPS/book.opf','<package><manifest><item id="two" href="Text/chapter-2.xhtml" media-type="application/xhtml+xml"/><item id="one" href="Text/chapter-1.xhtml" media-type="application/xhtml+xml"/><item id="css" href="Styles/layout.css" media-type="text/css"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
            archive.writestr('OEBPS/Text/chapter-1.xhtml','''<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter One</title><link rel="stylesheet" href="../Styles/layout.css"/><style>h1{font-variant:small-caps}p{margin:1em 0}</style></head><body class="typeset"><h1 id="heading">Chapter One</h1><p class="dropcap">A <em>carefully</em> <strong>typeset</strong> paragraph.</p><blockquote>A quoted passage.</blockquote><ol><li>First item</li><li>Second item</li></ol><table><tr><th>Term</th><th>Meaning</th></tr><tr><td>Book</td><td>Volume</td></tr></table><img src="../Images/plate.png" alt="Illustration"/><a href="chapter-2.xhtml#next">Next chapter</a><script>fetch('/api/delete')</script><iframe src="https://example.org"></iframe><form action="/api/delete"><input name="x"/></form><p onclick="alert(1)" style="background:url(https://example.org/spy)">Safe text after controls.</p><img src="https://example.org/spy"/><a href="javascript:alert(1)">Bad link</a></body></html>''')
            archive.writestr('OEBPS/nav.xhtml','<html xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="Text/chapter-1.xhtml#heading">Opening &amp; Introduction</a></li><li><a href="Text/chapter-2.xhtml#next">The Next Chapter</a></li></ol></nav></body></html>')
            archive.writestr('OEBPS/Text/chapter-2.xhtml','<html><body><h1 id="next">Chapter Two</h1><p>The next chapter.</p></body></html>')
            archive.writestr('OEBPS/Styles/layout.css','''@import "more.css"; @import url(https://example.org/spy.css); @font-face{font-family:Publication;src:url(../Fonts/Book.woff2)}p{font-family:Publication;line-height:1.6;text-indent:1.2em}figure{background-image:url(../Images/plate.png)}body{background:url(\\68 ttps://example.org/spy)}''')
            archive.writestr('OEBPS/Styles/more.css','h1{font-size:2em}table{border-collapse:collapse}')
            archive.writestr('OEBPS/Fonts/Book.woff2',b'localfont')
            image=Image.new('RGB',(30,40),'orange');buffer=io.BytesIO();image.save(buffer,format='PNG')
            archive.writestr('OEBPS/Images/plate.png',buffer.getvalue())
            archive.writestr('OEBPS/Images/vector.svg','<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><script>alert(1)</script><rect x="0" y="0" width="100" height="100" fill="red"/><image href="https://example.org/spy"/><foreignObject><p onclick="x()">unsafe</p></foreignObject></svg>')
            archive.writestr('../escape.png',b'not an image')
        self.row=dict(id='test',kind='epub',title='A Typeset Book',path=str(self.path),stamp='first-edition')
    def tearDown(self):self.tmp.cleanup()
    def test_source_spine_and_signed_manifest_without_private_paths(self):
        result=self.preview.manifest(self.row,self.base)
        self.assertEqual(result['kind'],'epub');self.assertEqual(result['title'],'A Typeset Book');self.assertEqual(result['chapter_count'],2)
        self.assertEqual(result['chapters'][0]['title'],'Opening & Introduction');self.assertEqual(result['chapters'][1]['title'],'The Next Chapter');self.assertEqual(result['chapters'][0]['index'],0);self.assertIn('/chapter/0?t=signature&v=version',result['chapters'][0]['url'])
        self.assertNotIn('path',result['chapters'][0]);self.assertNotIn('resources',result)
        self.assertIn('Chapter One',self.preview.chapter(self.row,0,self.base).decode())
        self.assertIn('Chapter Two',self.preview.chapter(self.row,1,self.base).decode())
    def test_epub_keeps_headings_paragraphs_emphasis_lists_tables_and_local_assets(self):
        output=self.preview.chapter(self.row,0,self.base).decode()
        for expected in ('<h1 id="heading">','<p class="dropcap">','<em>carefully</em>','<strong>typeset</strong>','<blockquote>','<ol>','<li>First item</li>','<table>','<th>Term</th>','font-variant:small-caps','class="typeset"'):
            self.assertIn(expected,output)
        self.assertIn('/resource/OEBPS/Styles/layout.css?t=signature&amp;v=version',output)
        self.assertIn('/resource/OEBPS/Images/plate.png?t=signature&amp;v=version',output)
        self.assertIn('/chapter/1?t=signature&amp;v=version#next',output)
        self.assertIn('alt="Illustration"',output)
    def test_untrusted_markup_and_remote_urls_are_removed(self):
        output=self.preview.chapter(self.row,0,self.base).decode()
        for unexpected in ('<script','<iframe','<form','<input','onclick','javascript:','example.org','/api/delete','fetch('):self.assertNotIn(unexpected,output)
        self.assertIn('Safe text after controls.',output)
        self.assertIn("script-src 'none'",book_preview.PREVIEW_CSP)
        self.assertIn("connect-src 'none'",book_preview.PREVIEW_CSP)
    def test_css_keeps_internal_imports_fonts_typography_and_removes_network(self):
        payload,mime=self.preview.resource(self.row,'OEBPS/Styles/layout.css',self.base);css=payload.decode()
        self.assertEqual(mime,'text/css');self.assertIn('line-height:1.6;text-indent:1.2em',css)
        self.assertIn('/resource/OEBPS/Styles/more.css?t=signature&v=version',css)
        self.assertIn('/resource/OEBPS/Fonts/Book.woff2?t=signature&v=version',css)
        self.assertIn('/resource/OEBPS/Images/plate.png?t=signature&v=version',css)
        self.assertNotIn('example.org',css);self.assertNotIn('@import none',css)
        font,media=self.preview.resource(self.row,'OEBPS/Fonts/Book.woff2',self.base)
        self.assertEqual((font,media),(b'localfont','font/woff2'))
    def test_resource_authorization_rejects_traversal_html_and_non_resources(self):
        for name in ('../escape.png','%2e%2e/escape.png','../../etc/passwd','/OEBPS/Images/plate.png','https://example.org/a.png','OEBPS/Text/chapter-1.xhtml','OEBPS/book.opf'):
            with self.subTest(name=name),self.assertRaises((KeyError,ValueError)):self.preview.resource(self.row,name,self.base)
        with self.assertRaises(KeyError):self.preview.chapter(self.row,99,self.base)
        with self.assertRaises(ValueError):self.preview.manifest({**self.row,'id':'../unsafe'},self.base)
    def test_svg_keeps_original_vector_geometry_without_active_elements(self):
        payload,mime=self.preview.resource(self.row,'OEBPS/Images/vector.svg',self.base);svg=payload.decode()
        self.assertEqual(mime,'image/svg+xml');self.assertIn('viewBox="0 0 100 100"',svg);self.assertIn('<rect',svg)
        self.assertNotIn('<script',svg);self.assertNotIn('foreignObject',svg);self.assertNotIn('example.org',svg);self.assertNotIn('onclick',svg)
    def test_source_stamp_invalidates_manifest_and_signed_urls_are_never_cached(self):
        first=self.preview.manifest(self.row,self.base)
        changed=self.preview.manifest({**self.row,'stamp':'second-edition'},self.base)
        self.assertNotEqual(first['version'],changed['version'])
        another=self.preview.manifest(self.row,'/api/books/test/preview?t=another')
        self.assertIn('t=another',another['chapters'][0]['url']);self.assertNotIn('signature',another['chapters'][0]['url'])
        with patch.object(self.preview,'_epub_metadata',side_effect=AssertionError('manifest rescanned')):
            self.assertEqual(self.preview.manifest(self.row,self.base),first)
    def test_standard_idpf_and_adobe_embedded_fonts_render_with_original_bytes(self):
        import hashlib,uuid
        original=bytes(range(256))*7
        uid='urn:uuid:9B3705F6-B1D3-4F47-9142-7185DAA4CD1B'
        for flavor,algorithm,key,count in (
            ('idpf','http://www.idpf.org/2008/embedding',hashlib.sha1(uid.encode()).digest(),1040),
            ('adobe','http://ns.adobe.com/pdf/enc#RC',uuid.UUID(uid[9:]).bytes,1024),
        ):
            with self.subTest(flavor=flavor):
                path=self.root/(flavor+'.epub')
                with zipfile.ZipFile(self.path) as archive:members={name:archive.read(name) for name in archive.namelist()}
                package=members['OEBPS/book.opf'].decode().replace('<package>','<package unique-identifier="bookid"><metadata><identifier id="bookid">  '+uid+'  </identifier></metadata>')
                members['OEBPS/book.opf']=package.encode()
                members['META-INF/encryption.xml']=('<encryption><EncryptedData><EncryptionMethod Algorithm="'+algorithm+'"/><CipherData><CipherReference URI="OEBPS/Fonts/Book.woff2"/></CipherData></EncryptedData></encryption>').encode()
                members['OEBPS/Fonts/Book.woff2']=bytes(byte^key[index%len(key)] for index,byte in enumerate(original[:count]))+original[count:]
                with zipfile.ZipFile(path,'w') as archive:
                    for name,payload in members.items():archive.writestr(name,payload)
                row=dict(id=flavor,kind='epub',title='Embedded typography',path=str(path),stamp=flavor)
                font,mime=self.preview.resource(row,'OEBPS/Fonts/Book.woff2',self.base)
                self.assertEqual(mime,'font/woff2');self.assertEqual(font,original)
                self.assertNotIn('font_obfuscation',self.preview.manifest(row,self.base))

    def test_damaged_source_documents_have_readable_preview_errors(self):
        for kind,payload in (('epub',b'not a zip archive'),('pdf',b'not a PDF')):
            path=self.root/('damaged.'+kind);path.write_bytes(payload)
            row=dict(id='damaged-'+kind,kind=kind,title='Damaged Book',path=str(path),stamp='damaged')
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'damaged or unsupported'):
                self.preview.manifest(row,self.base)
        path=self.root/'broken-package.epub'
        with zipfile.ZipFile(path,'w') as archive:archive.writestr('book.opf','<package><broken')
        row=dict(id='malformed',kind='epub',title='Broken package',path=str(path),stamp='malformed')
        with self.assertRaisesRegex(ValueError,'damaged or unsupported'):self.preview.manifest(row,self.base)
    def test_pdf_crop_and_rotation_match_original_rendered_page_dimensions(self):
        from pypdf import PdfWriter
        from pypdf.generic import RectangleObject
        path=self.root/'rotated.pdf';writer=PdfWriter();page=writer.add_blank_page(width=500,height=700)
        page.cropbox=RectangleObject([100,100,400,600]);page.rotate(90)
        with path.open('wb') as output:writer.write(output)
        row=dict(id='rotated',kind='pdf',title='Rotated crop',path=str(path),stamp='one')
        manifest=self.preview.manifest(row,self.base)
        self.assertEqual((manifest['pages'][0]['width'],manifest['pages'][0]['height']),(500,300))
        payload,_=self.preview.pdf_page(row,0)
        with Image.open(io.BytesIO(payload)) as image:self.assertEqual(image.size,(1000,600))

    def test_pdf_manifest_and_original_pages_render_lazily_and_cache(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject,NameObject
        path=self.root/'layout.pdf';writer=PdfWriter()
        page=writer.add_blank_page(width=300,height=420)
        content=DecodedStreamObject();content.set_data(b'q 0.8 0.1 0.1 rg 20 20 160 80 re f Q')
        page[NameObject('/Contents')]=writer._add_object(content)
        writer.add_blank_page(width=420,height=300)
        with path.open('wb') as source:writer.write(source)
        row=dict(id='pdf-test',kind='pdf',title='Original PDF',path=str(path),stamp='one')
        manifest=self.preview.manifest(row,self.base)
        self.assertEqual(manifest['page_count'],2);self.assertEqual(manifest['pages'][0]['width'],300)
        self.assertIn('/page/0?t=signature&v=version',manifest['pages'][0]['url'])
        folder=self.preview._folder(row);self.assertFalse(list(folder.glob('page-*.png')))
        payload,mime=self.preview.pdf_page(row,0);self.assertEqual(mime,'image/png')
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.size,(600,840));self.assertNotEqual(image.getpixel((100,740))[:3],(255,255,255))
        self.assertTrue((folder/'page-0.png').is_file());self.assertFalse((folder/'page-1.png').exists())
        with patch('pypdfium2.PdfDocument',side_effect=AssertionError('cached page rerendered')):self.assertEqual(self.preview.pdf_page(row,0)[0],payload)
        with self.assertRaises(KeyError):self.preview.pdf_page(row,2)
        with self.assertRaises(KeyError):self.preview.pdf_page(self.row,0)


class PreviewApiTests(unittest.TestCase):
    def setUp(self):
        BookPreviewTests.setUp(self)
        import book_mode
        from fastapi import FastAPI,HTTPException
        from fastapi.testclient import TestClient
        self.app=FastAPI();self.pauses=[]
        def auth(value):
            if value!='Bearer test':raise HTTPException(401,detail='Unauthorized')
        self.g=dict(data_path=lambda _:self.root/'api-cache',require_auth=auth,require_read_auth=auth,radio_paused=lambda:False,radio_pause_set=lambda on,why='':self.pauses.append((on,why)),media_sign=lambda _:'signature')
        with patch.dict('os.environ',{'PINE_BOOK_FOLDERS':str(self.root)}):self.mode=book_mode.register(self.app,self.g)
        self.mode.scan();self.book=next(iter(self.mode.catalog));self.client=TestClient(self.app);self.headers={'Authorization':'Bearer test'}
    def tearDown(self):BookPreviewTests.tearDown(self)
    def test_preview_routes_require_signature_or_read_key(self):
        routes=[f'/books/read/{self.book}',f'/api/books/{self.book}/preview',f'/api/books/{self.book}/preview/chapter/0',f'/api/books/{self.book}/preview/resource/OEBPS/Styles/layout.css',f'/api/books/{self.book}/preview/page/0',f'/api/books/{self.book}/preview/assets/book-preview.js',f'/api/books/{self.book}/preview/assets/book-preview.css']
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code,401)
                self.assertEqual(self.client.get(route+'?t=wrong').status_code,401)
        self.assertEqual(self.client.get(f'/api/books/{self.book}/preview',headers=self.headers).status_code,200)
    def test_document_points_to_same_formatted_viewer_and_signed_assets(self):
        route=f'/api/books/{self.book}/document'
        self.assertEqual(self.client.get(route).status_code,401)
        document=self.client.get(route,headers=self.headers).json()
        self.assertEqual(document['preview_url'],f'/books/read/{self.book}?t=signature')
        response=self.client.get(document['preview_url']);self.assertEqual(response.status_code,200,response.text)
        self.assertIn('book-preview.js?t=signature',response.text);self.assertIn('book-preview.css?t=signature',response.text)
        self.assertNotIn('__BOOK_PREVIEW_',response.text);self.assertIn("script-src 'self'",response.headers['content-security-policy'])
        for asset in ('book-preview.js','book-preview.css'):
            response=self.client.get(f'/api/books/{self.book}/preview/assets/{asset}?t=signature')
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertEqual(self.client.get(f'/api/books/{self.book}/preview/assets/book_mode.py?t=signature').status_code,404)
    def test_signed_manifest_chapter_css_font_and_image_are_accessible_without_key(self):
        result=self.client.get(f'/api/books/{self.book}/preview?t=signature').json()
        self.assertEqual(result['kind'],'epub');self.assertEqual(result['chapters'][0]['title'],'Opening & Introduction')
        response=self.client.get(result['chapters'][0]['url']);self.assertEqual(response.status_code,200,response.text)
        self.assertIn('<em>carefully</em>',response.text);self.assertIn('<table>',response.text)
        self.assertEqual(response.headers['content-security-policy'],book_preview.PREVIEW_CSP)
        self.assertNotIn('<script',response.text)
        for member,media in (('OEBPS/Styles/layout.css','text/css'),('OEBPS/Fonts/Book.woff2','font/woff2'),('OEBPS/Images/plate.png','image/png')):
            response=self.client.get(f'/api/books/{self.book}/preview/resource/{member}?t=signature')
            self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.headers['content-type'].startswith(media))
        for member in ('OEBPS/Text/chapter-1.xhtml','OEBPS/book.opf','missing.png'):
            self.assertEqual(self.client.get(f'/api/books/{self.book}/preview/resource/{member}?t=signature').status_code,404)
        self.assertEqual(self.client.get(f'/api/books/{self.book}/preview/chapter/99?t=signature').status_code,404)
        self.assertEqual(self.client.get(f'/api/books/{self.book}/preview/page/0?t=signature').status_code,404)
    def test_preview_cannot_activate_book_mode_pause_fm_extract_narration_or_advance_bookmark(self):
        before=self.mode.state();stored=dict(self.mode.store)
        patches=[patch.object(self.mode,name,side_effect=AssertionError('preview invoked '+name)) for name in ('lines','select','invalidate','receipt','save')]
        with patches[0],patches[1],patches[2],patches[3],patches[4],patch('library_extract.read_document',side_effect=AssertionError('preview extracted narration')):
            self.assertEqual(self.client.get(f'/books/read/{self.book}?t=signature').status_code,200)
            self.assertEqual(self.client.get(f'/api/books/{self.book}/document',headers=self.headers).status_code,200)
            result=self.client.get(f'/api/books/{self.book}/preview?t=signature').json()
            self.assertEqual(self.client.get(result['chapters'][0]['url']).status_code,200)
            self.assertEqual(self.client.get(f'/api/books/{self.book}/preview/resource/OEBPS/Styles/layout.css?t=signature').status_code,200)
        self.assertEqual(self.mode.state(),before);self.assertEqual(self.mode.store,stored);self.assertEqual(self.pauses,[])
        self.assertFalse(self.mode.active);self.assertEqual(self.mode.book,'');self.assertEqual(self.mode.store['books'],{})
    def test_pdf_page_route_renders_original_image_requires_auth_and_rejects_chapter_routes(self):
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=300,height=420);writer.add_blank_page(width=420,height=300)
        path=self.root/'reader.pdf'
        with path.open('wb') as output:writer.write(output)
        self.mode.scan();book=next(row['id'] for row in self.mode.catalog.values() if row['kind']=='pdf')
        result=self.client.get(f'/api/books/{book}/preview?t=signature').json()
        self.assertEqual(result['kind'],'pdf');self.assertEqual(result['page_count'],2)
        url=result['pages'][0]['url'];self.assertIn('t=signature',url)
        self.assertEqual(self.client.get(url.split('?')[0]).status_code,401)
        response=self.client.get(url);self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.headers['content-type'],'image/png')
        with Image.open(io.BytesIO(response.content)) as image:self.assertEqual(image.size,(600,840))
        self.assertEqual(self.client.get(f'/api/books/{book}/preview/page/2?t=signature').status_code,404)
        self.assertEqual(self.client.get(f'/api/books/{book}/preview/chapter/0?t=signature').status_code,404)
        self.assertEqual(self.client.get(f'/api/books/{book}/preview/resource/OEBPS/Styles/layout.css?t=signature').status_code,404)
        self.assertEqual(self.client.get(f'/books/read/{book}?t=signature').status_code,200)
        self.assertFalse(self.mode.active);self.assertEqual(self.pauses,[])


if __name__=='__main__':unittest.main()
