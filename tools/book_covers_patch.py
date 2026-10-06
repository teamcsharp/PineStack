#!/usr/bin/env python3
"""[book-covers] [book-shelf] The books show their own covers, on a wall of covers. 2026-10-05, #1587.

"The book tab is poorly formatted. Also it's hardly readable and I'm not able to
see the covers of the books. The books don't show their covers at all. I want
it formatted more like the second image. and third."

The shelf drew a generated title card for every book and laid the cards out as
a thin strip with a tilt. Two changes:

[book-covers]  the station serves each book's OWN cover: a PDF's first page as
               the reader already renders it, an EPUB's cover image from its
               package (the cover meta, the cover-image item, an item named
               cover, or the first picture of the first chapter), reduced to a
               420 px JPEG and kept beside the preview. A book with no cover of
               its own still gets the title card. Route: /api/books/{book}/cover.img
[book-shelf]   the desk lays the library out as a grid of covers with the title
               and author beneath, like a bookstore, and scrolls down through it.

book_preview.py and book_mode.py are the station: they take effect at its next
restart. The two renderer files are hot-copied; the desk takes them at its next
reload, the tablet at its next kiosk build.

Usage:  book_covers_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        book_covers_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- book_preview.py
PREVIEW_OLD = '''            output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix('.png.tmp')
            temporary.write_bytes(payload);temporary.replace(output)
            return payload,'image/png'
'''
PREVIEW_NEW = PREVIEW_OLD + '''    # [book-covers] THE BOOK'S OWN COVER.
    # A PDF's is its first page, as the reader renders it; an EPUB's is the cover image its
    # package names, or failing that an image item called cover, or the first picture of
    # the first chapter. Reduced to a 420 px JPEG and kept beside the preview, with a marker
    # for a book that has none, so no book is opened twice for the same answer.
    COVER_WIDTH=420
    def cover(self,row):
        """(bytes, mime) of the book's own cover, or None when it has none."""
        folder=self._folder(row)
        with self.cache_lock:
            kept=folder/'cover.jpg'
            if kept.is_file():return kept.read_bytes(),'image/jpeg'
            if (folder/'cover.none').is_file():return None
        try:
            if row['kind']=='pdf':payload,_mime=self.pdf_page(row,0)
            elif row['kind']=='epub':payload=self._epub_cover(row)
            else:payload=None
            picture=self._cover_jpeg(payload) if payload else None
        except Exception:
            picture=None
        folder.mkdir(parents=True,exist_ok=True)
        with self.cache_lock:
            if not picture:
                (folder/'cover.none').write_text('',encoding='utf-8');return None
            temporary=folder/'cover.jpg.tmp';temporary.write_bytes(picture);temporary.replace(folder/'cover.jpg')
        return picture,'image/jpeg'
    def _cover_jpeg(self,payload):
        from PIL import Image
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.width<40 or image.height<40:return None
            if image.mode not in ('RGB','L'):image=image.convert('RGB')
            scale=min(1.0,self.COVER_WIDTH/float(image.width))
            if scale<1.0:image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.LANCZOS)
            buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=84,optimize=True);return buffer.getvalue()
    def _epub_cover(self,row):
        """The bytes of an EPUB's cover image, or None."""
        metadata=self._metadata(row)
        if metadata['kind']!='epub':return None
        with zipfile.ZipFile(row['path']) as archive:
            members=set(archive.namelist())
            try:
                container=ET.fromstring(_read_member(archive,'META-INF/container.xml',2*1024*1024))
                package=next(element.get('full-path') for element in container.iter() if _local_name(element.tag)=='rootfile' and element.get('full-path'))
            except (KeyError,StopIteration):package=next((name for name in archive.namelist() if name.lower().endswith('.opf')),'')
            if not package:return None
            package=_member(package);root=ET.fromstring(_read_member(archive,package,4*1024*1024));base=posixpath.dirname(package)
            items={element.get('id'):element for element in root.iter() if _local_name(element.tag)=='item' and element.get('id') and element.get('href')}
            picked=[]
            named=next((element.get('content') for element in root.iter() if _local_name(element.tag)=='meta' and str(element.get('name') or '').lower()=='cover'),None)
            if named and named in items:picked.append(items[named])
            picked+=[element for element in items.values() if 'cover-image' in str(element.get('properties') or '').split()]
            picked+=[element for element in items.values() if str(element.get('media-type') or '').startswith('image/') and 'cover' in (str(element.get('id') or '')+str(element.get('href') or '')).lower()]
            def member_of(href,against):
                parsed=urlsplit(href)
                if parsed.scheme or parsed.netloc or not parsed.path:return ''
                try:return _member(posixpath.join(against,unquote(parsed.path)))
                except ValueError:return ''
            for element in picked:
                name=member_of(element.get('href'),base)
                mime=RESOURCE_MIMES.get(Path(name).suffix.lower()) or str(element.get('media-type') or '')
                if name in members and mime.startswith('image/') and mime!='image/svg+xml':return _read_member(archive,name,MAX_RESOURCE)
            chapters=metadata.get('chapters') or []
            if chapters:
                first=chapters[0]['path']
                found=re.search(r'<(?:img|image)\\b[^>]*?(?:src|href|xlink:href)=["\\']([^"\\']+)["\\']',_decode(_read_member(archive,first)),re.I)
                name=member_of(found.group(1),posixpath.dirname(first)) if found else ''
                mime=RESOURCE_MIMES.get(Path(name).suffix.lower(),'')
                if name in members and mime.startswith('image/') and mime!='image/svg+xml':return _read_member(archive,name,MAX_RESOURCE)
        return None
'''

# --------------------------------------------------------------------------- book_mode.py
LIST_OLD = '''            row['cover_url']=f"/api/books/{row['id']}/cover.svg?t={g['media_sign'](row['id'])}&v={row['cover_version']}"
'''
LIST_NEW = '''            row['cover_url']=f"/api/books/{row['id']}/cover.img?t={g['media_sign'](row['id'])}&v={row['cover_version']}"   # [book-covers] the book's own cover, the title card behind it
'''
ROUTE_OLD = '''    @app.get('/api/books/{book}/cover.svg')
    async def book_cover_image(book:str,t:str='',authorization:str|None=Header(default=None)):
        signed_read(book,t,authorization)
        svg=await disk(mode.cover,book);version=mode.cover_version(book)
        return Response(svg,media_type='image/svg+xml',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=300','ETag':f'"{version}"'})
'''
ROUTE_NEW = ROUTE_OLD + '''    @app.get('/api/books/{book}/cover.img')
    async def book_cover_picture(book:str,t:str='',authorization:str|None=Header(default=None)):
        """[book-covers] The book's own cover; the generated title card when it has none."""
        signed_read(book,t,authorization);row=await disk(mode.row,book);version=mode.cover_version(book)
        found=await disk(preview.cover,row)
        if found:
            payload,mime=found
            return Response(payload,media_type=mime,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400','ETag':f'"{version}-own"'})
        svg=await disk(mode.cover,book)
        return Response(svg,media_type='image/svg+xml',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=300','ETag':f'"{version}"'})
'''

# --------------------------------------------------------------------------- book-mode.js (both copies)
SCROLL_OLD = r'''ui.books.onscroll=function(){if(ui.books.scrollLeft<30&&shelfFirstOffset>0){library(true,Math.max(0,shelfFirstOffset-40)).catch(function(e){say(e.message);});return;}if(ui.books.scrollLeft+ui.books.clientWidth>ui.books.scrollWidth-250&&listOffset<listTotal)library(false).catch(function(e){say(e.message);});};'''
SCROLL_NEW = r'''ui.books.onscroll=function(){var b=ui.books;if(b.scrollTop<30&&b.scrollLeft<30&&shelfFirstOffset>0){library(true,Math.max(0,shelfFirstOffset-40)).catch(function(e){say(e.message);});return;}if((b.scrollTop+b.clientHeight>b.scrollHeight-250||b.scrollLeft+b.clientWidth>b.scrollWidth-250)&&listOffset<listTotal)library(false).catch(function(e){say(e.message);});};   /* [book-shelf] the wall scrolls down as well as along */'''
TRIM_OLD = r'''      while(ui.books.children.length>200){var width=ui.books.firstChild.getBoundingClientRect().width+16;ui.books.firstChild.remove();shelfFirstOffset++;ui.books.scrollLeft=Math.max(0,ui.books.scrollLeft-width);}'''
TRIM_NEW = r'''      while(ui.books.children.length>200){ui.books.firstChild.remove();shelfFirstOffset++;}   /* [book-shelf] */'''
JS = [
    ("the wall loads as it scrolls down", SCROLL_OLD, SCROLL_NEW, "/* [book-shelf] the wall scrolls down as well as along */", 1),
    ("trimming no longer assumes a strip", TRIM_OLD, TRIM_NEW, "ui.books.firstChild.remove();shelfFirstOffset++;}   /* [book-shelf] */", 1),
]

# --------------------------------------------------------------------------- book-mode.css (both copies)
CSS_NEW = r'''
/* [book-shelf] THE LIBRARY AS A WALL OF COVERS. "I want it formatted more like the second image":
   a grid of the books' own covers with the title and author beneath, that scrolls down. Every rule
   here comes after the strip's and wins by order; the markup is unchanged. */
.bm-books{display:grid;grid-template-columns:repeat(auto-fill,minmax(176px,1fr));gap:30px 24px;align-items:start;overflow-x:hidden;overflow-y:auto;scroll-snap-type:none;perspective:none;padding:20px 18px 26px;max-height:min(64vh,calc(100vh - 280px))}
.bm-card,.bm-card:hover,.bm-card:focus-within,.bm-card.bm-selected{flex-basis:auto;transform:none;scroll-snap-align:none;background:transparent;box-shadow:none;border-radius:0}
.bm-card{display:grid;grid-template-columns:1fr 1fr;gap:7px 8px;padding:0}
.bm-card>.bm-cover,.bm-card>.bm-card-title,.bm-card>small{grid-column:1/-1}
.bm-card .bm-cover{border:0;border-radius:3px 7px 7px 3px;background:linear-gradient(135deg,#2b4a46,#13262d);box-shadow:0 12px 26px #000b,0 2px 6px #0009;transition:transform .15s ease,box-shadow .15s ease}
.bm-card:hover .bm-cover,.bm-card:focus-within .bm-cover{transform:translateY(-4px);box-shadow:0 18px 30px #000c,0 2px 6px #0009}
.bm-card.bm-selected .bm-cover{outline:3px solid #8fd3bf;outline-offset:3px}
.bm-cover img{object-fit:cover;background:#fff}
.bm-cover-title{font-size:16px;padding:16px 12px}
.bm-card .bm-card-title{margin-top:4px;font:600 14px/1.35 system-ui,sans-serif;color:#f2efe6;min-height:0;-webkit-line-clamp:2}
.bm-card small{font:12px/1.35 system-ui,sans-serif;color:#a9bab8;min-height:0;-webkit-line-clamp:2}
.bm-card button:not(.bm-cover):not(.bm-card-title){min-height:26px;padding:3px 10px;font-size:12px;border-radius:999px;background:#1f333b;border-color:#4b6763}
.bm-card .bm-read{color:#a8eedb;border-color:#4f8d7e}
.bm-inline .bm-books{grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:20px 16px;max-height:40vh;padding:14px 10px 18px}
.bm-inline .bm-card .bm-card-title{font-size:13px}
@media(max-height:760px){.bm-card,.bm-inline .bm-card{flex-basis:auto}.bm-books{max-height:min(56vh,calc(100vh - 230px))}}
'''
CSS = [("a wall of covers", None, CSS_NEW, "/* [book-shelf] THE LIBRARY AS A WALL OF COVERS.", 1)]

EDITS = {
    "book_preview.py": [("the book's own cover", PREVIEW_OLD, PREVIEW_NEW, "    def _epub_cover(self,row):", 1)],
    "book_mode.py": [
        ("the shelf asks for the book's own cover", LIST_OLD, LIST_NEW, "cover.img?t={g['media_sign'](row['id'])}", 1),
        ("the cover road", ROUTE_OLD, ROUTE_NEW, "    @app.get('/api/books/{book}/cover.img')", 1),
    ],
    "desktop/renderer/book-mode.js": JS,
    "app/src/main/assets/pine-views/book-mode.js": JS,
    "desktop/renderer/book-mode.css": CSS,
    "app/src/main/assets/pine-views/book-mode.css": CSS,
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-44s (not in this tree - skipped)" % name[-44:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            if old is None:
                have = text.count(probe)
                state = "applied" if have == count else "ready" if not have else "missing (probe %d)" % have
                if state == "ready":
                    text = text.rstrip("\n") + "\n" + (new.replace("\n", "\r\n") if mode == "mixed" else new)
                    changed = True
            else:
                forms = [(old, new, probe)]
                if mode == "mixed":
                    forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
                state = ""
                for old_, new_, probe_ in forms:
                    have = text.count(probe_)
                    if have == count:
                        state = "applied"
                        break
                    if not have and text.count(old_) == count:
                        text = text.replace(old_, new_)
                        assert text.count(probe_) == count, (name, label, "probe after the edit")
                        state, changed = "ready", True
                        break
                if not state:
                    state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-44s %-40s %s" % (name[-44:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".covers.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
