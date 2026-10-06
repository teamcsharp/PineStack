"""Passive book previews preserving EPUB typography and original PDF pages.

This module never reads narration text or changes BookMode state. EPUB markup is
untrusted: scripts/forms/remote URLs are removed, local assets use signed routes,
and every HTML response must carry PREVIEW_CSP and run in a script-free iframe.
"""
from __future__ import annotations
import hashlib, html, io, json, math, posixpath, re, zipfile
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

PREVIEW_VERSION = 3
MAX_DOCUMENT = 16 * 1024 * 1024
MAX_RESOURCE = 64 * 1024 * 1024
PREVIEW_CSP = "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'"
RESOURCE_MIMES = {'.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp','.svg':'image/svg+xml','.avif':'image/avif','.bmp':'image/bmp','.woff':'font/woff','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.eot':'application/vnd.ms-fontobject'}
VOID_TAGS = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BLOCK_TAGS = {'script','iframe','object','embed','form','button','input','textarea','select','option','audio','video','foreignobject','animate','animatetransform','set'}
DROP_TAGS = {'base','meta'}
ALLOWED_TAGS = set(('html head title body style link div span p h1 h2 h3 h4 h5 h6 a abbr acronym address article aside b bdi bdo blockquote br caption center cite code col colgroup dd del details dfn dl dt em figcaption figure footer header hr i img ins kbd li main mark nav ol pre q rp rt ruby s samp section small strong sub summary sup table tbody td th thead time tr tt u ul var wbr svg g path rect circle ellipse line polyline polygon text tspan defs clippath mask lineargradient radialgradient stop use image symbol math mrow mi mn mo mfrac msqrt mroot msub msup msubsup munder mover munderover mtable mtr mtd mtext semantics annotation').split())
SVG_NAMES = {'clippath':'clipPath','lineargradient':'linearGradient','radialgradient':'radialGradient'}
SVG_ATTRS = {'viewbox':'viewBox','preserveaspectratio':'preserveAspectRatio','gradientunits':'gradientUnits','gradienttransform':'gradientTransform','patternunits':'patternUnits','markerwidth':'markerWidth','markerheight':'markerHeight','refx':'refX','refy':'refY','textlength':'textLength','lengthadjust':'lengthAdjust','clippathunits':'clipPathUnits'}


def _local_name(tag):return tag.rsplit('}',1)[-1].split(':')[-1].lower()


def _member(name):
    """Resolve archive names while rejecting traversal, schemes and ambiguity."""
    name=unquote(str(name)).replace('\\','/')
    if not name or name.startswith('/') or '\x00' in name:raise ValueError('Invalid book resource path')
    normalized=posixpath.normpath(name)
    if normalized in ('.','..') or normalized.startswith('../') or ':' in normalized:raise ValueError('Invalid book resource path')
    return normalized


def _read_member(archive,name,maximum=MAX_DOCUMENT):
    info=archive.getinfo(_member(name))
    if info.file_size>maximum or info.flag_bits&1:raise ValueError('Book preview resource is too large or encrypted')
    return archive.read(info)


def _decode(data):
    encoding=re.search(br'encoding=[\"\']([^\"\']+)',data[:240],re.I)
    try:return data.decode(encoding.group(1).decode('ascii') if encoding else 'utf-8-sig')
    except (UnicodeError,LookupError):return data.decode('utf-8',errors='replace')


def _url(base,suffix):
    parts=urlsplit(base)
    return parts.path.rstrip('/')+'/'+suffix+('?' + parts.query if parts.query else '')


class _EpubUrls:
    def __init__(self,member,base_url,resources,chapters):self.member=member;self.base_url=base_url;self.resources=resources;self.chapters=chapters
    def resolve(self,value,navigation=False):
        value=html.unescape(str(value)).strip()
        if not value or any(ord(char)<32 for char in value):return ''
        if value.startswith('#'):return value if navigation else ''
        parts=urlsplit(value)
        if parts.scheme=='data' and not navigation:
            return value if re.match(r'^data:(?:image/(?:png|jpeg|gif|webp|avif)|font/[a-z0-9.+-]+);base64,[a-z0-9+/=\s]+$',value,re.I) else ''
        if parts.scheme or parts.netloc or parts.query or parts.path.startswith(('/','\\')):return ''
        try:name=_member(posixpath.join(posixpath.dirname(self.member),unquote(parts.path)))
        except ValueError:return ''
        if navigation and name in self.chapters:target=_url(self.base_url,'chapter/'+str(self.chapters[name]))
        elif name in self.resources:target=_url(self.base_url,'resource/'+quote(name,safe='/'))
        else:return ''
        return target+('#'+quote(parts.fragment,safe='-_.~') if parts.fragment else '')


def _css(source,urls):
    """Keep publication CSS while rewriting every local URL through signed routes."""
    source=re.sub(r'/\*.*?\*/','',source,flags=re.S)
    source=re.sub(r'\\([0-9a-fA-F]{1,6})\s?',lambda match:chr(int(match.group(1),16)) if int(match.group(1),16)<=0x10ffff else '',source)
    source=re.sub(r'\\([^\r\n0-9a-fA-F])',r'\1',source)
    source=re.sub(r'(?:expression|behavior|-moz-binding)\s*[:(][^;}]*[;}]?','',source,flags=re.I)
    def replace_url(match):
        raw=match.group(1).strip().strip('\"\'')
        target=raw if re.match(r'^#[a-zA-Z0-9_.:-]+$',raw) else urls.resolve(raw)
        return 'url("'+target.replace('"','%22')+'")' if target else 'none'
    # Quoted imports are normalized first; url imports use the generic rewrite.
    source=re.sub(r'@import\s+(?:\"([^\"]+)\"|\'([^\']+)\')([^;]*);?',lambda match:'@import url("'+(match.group(1) or match.group(2))+'")'+match.group(3)+';',source,flags=re.I)
    source=re.sub(r'url\(\s*([^)]*)\s*\)',replace_url,source,flags=re.I)
    source=re.sub(r'@import\s+none[^;]*;?','',source,flags=re.I)
    return source


class _Markup(HTMLParser):
    def __init__(self,urls):
        super().__init__(convert_charrefs=True);self.urls=urls;self.parts=[];self.blocked=None;self.block_depth=0;self.style=False;self.has_html=False
    def handle_starttag(self,tag,attrs):
        tag=_local_name(tag)
        if self.blocked:
            if tag==self.blocked:self.block_depth+=1
            return
        if tag in BLOCK_TAGS:
            if tag not in VOID_TAGS:self.blocked=tag;self.block_depth=1
            return
        if tag in DROP_TAGS or tag not in ALLOWED_TAGS:return
        if tag=='html':self.has_html=True
        safe=[];properties=dict(attrs)
        for key,value in attrs:
            key=key.lower()
            if value is None or key.startswith('on') or key in ('srcdoc','action','formaction','form','target','download','ping','autofocus','contenteditable','srcset'):continue
            if key=='style':value=_css(value,self.urls)
            elif key in ('src','href','xlink:href','poster','background'):
                if tag=='link' and (properties.get('rel') or '').lower()!='stylesheet':continue
                value=value if tag=='use' and re.fullmatch(r'#[a-zA-Z0-9_.:-]+',value) else self.urls.resolve(value,navigation=tag=='a' and key=='href')
                if not value:continue
            elif key=='http-equiv':continue
            safe.append((SVG_ATTRS.get(key,key),value))
        rendered=''.join(' '+key+'="'+html.escape(value,quote=True)+'"' for key,value in safe)
        self.parts.append('<'+SVG_NAMES.get(tag,tag)+rendered+'>')
        if tag=='style':self.style=True
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if _local_name(tag) not in VOID_TAGS:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        tag=_local_name(tag)
        if self.blocked:
            if tag==self.blocked:
                self.block_depth-=1
                if self.block_depth==0:self.blocked=None
            return
        if tag=='style':self.style=False
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:self.parts.append('</'+SVG_NAMES.get(tag,tag)+'>')
    def handle_data(self,data):
        if self.blocked:return
        self.parts.append(_css(data,self.urls).replace('</','<\\/') if self.style else html.escape(data,quote=False))
    def result(self):
        body=''.join(self.parts)
        if not self.has_html:body='<html><head><meta charset="utf-8"></head><body>'+body+'</body></html>'
        else:body=re.sub(r'<head\b[^>]*>',lambda match:match[0]+'<meta charset="utf-8">',body,count=1,flags=re.I)
        return '<!doctype html>'+body


def _navigation_titles(archive,sources):
    """Use the publication's table of contents without changing chapter ordering."""
    titles={}
    for name in sources:
        try:tree=ET.fromstring(_read_member(archive,name,4*1024*1024))
        except (KeyError,ValueError,ET.ParseError):continue
        labels=[]
        if name.lower().endswith('.ncx'):
            for element in tree.iter():
                if _local_name(element.tag)!='navpoint':continue
                label=next((' '.join(''.join(child.itertext()).split()) for child in element if _local_name(child.tag)=='navlabel'),'')
                target=next((child.get('src','') for child in element if _local_name(child.tag)=='content'),'')
                labels.append((target,label))
        else:
            navs=[element for element in tree.iter() if _local_name(element.tag)=='nav' and any(_local_name(key)=='type' and 'toc' in value.split() for key,value in element.attrib.items())]
            for nav in navs or [tree]:
                labels.extend((element.get('href',''),' '.join(''.join(element.itertext()).split())) for element in nav.iter() if _local_name(element.tag)=='a')
        for target,label in labels:
            parsed=urlsplit(target)
            if not target or not label or parsed.scheme or parsed.netloc:continue
            try:member=_member(posixpath.join(posixpath.dirname(name),unquote(parsed.path)))
            except ValueError:continue
            titles.setdefault(member,label[:160])
    return titles


def _font_obfuscation(archive,package,resources):
    """Decode only the standard EPUB font embedding transforms, never DRM.

    IDPF: SHA-1 of the whitespace-stripped package unique identifier, XOR 1040
    bytes (https://www.w3.org/TR/epub-33/#sec-font-obfuscation). Adobe embedding:
    the first UUID identifier as 16 bytes, XOR 1024 bytes.
    """
    if 'META-INF/encryption.xml' not in archive.namelist():return {}
    tree=ET.fromstring(_read_member(archive,'META-INF/encryption.xml',2*1024*1024))
    identifiers=[element for element in package.iter() if _local_name(element.tag)=='identifier']
    unique=next((''.join(element.itertext()) for element in identifiers if element.get('id')==package.get('unique-identifier')),'')
    idpf=hashlib.sha1(re.sub(r'[ \t\r\n]','',unique).encode('utf-8')).digest() if unique else None
    adobe=None
    import uuid
    for element in identifiers:
        identifier=''.join(element.itertext()).strip()
        if not identifier.lower().startswith('urn:uuid:'):continue
        try:adobe=uuid.UUID(identifier[9:]).bytes;break
        except ValueError:continue
    result={}
    for element in tree.iter():
        if _local_name(element.tag)!='encrypteddata':continue
        algorithm=next((child.get('Algorithm','') for child in element.iter() if _local_name(child.tag)=='encryptionmethod'),'')
        uri=next((child.get('URI','') for child in element.iter() if _local_name(child.tag)=='cipherreference'),'')
        parsed=urlsplit(uri)
        if not uri or parsed.scheme or parsed.netloc:continue
        try:name=_member(parsed.path)
        except ValueError:continue
        if name not in resources or not (resources[name].startswith('font/') or Path(name).suffix.lower()=='.eot'):continue
        key,length=(idpf,1040) if algorithm=='http://www.idpf.org/2008/embedding' else (adobe,1024) if algorithm=='http://ns.adobe.com/pdf/enc#RC' else (None,0)
        if key:result[name]=dict(key=key.hex(),length=length)
    return result


class BookPreview:
    def __init__(self,data):
        self.data=Path(data);self.pdf_lock=RLock();self.cache_lock=RLock()
    def version(self,row):return hashlib.sha256(json.dumps([PREVIEW_VERSION,row['stamp'],row['kind']],sort_keys=True).encode()).hexdigest()[:20]
    def _folder(self,row):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',row['id']):raise ValueError('Invalid book identifier')
        return self.data/row['id']/'preview'/self.version(row)
    def _metadata(self,row):
        path=self._folder(row)/'manifest.json'
        with self.cache_lock:
            if path.is_file():return json.loads(path.read_text(encoding='utf-8'))
            if row['kind']=='epub':result=self._epub_metadata(row)
            elif row['kind']=='pdf':result=self._pdf_metadata(row)
            else:raise ValueError('Only EPUB and PDF book previews are supported')
            path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');temporary.replace(path)
            return result
    def _pdf_metadata(self,row):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            with Path(row['path']).open('rb') as source:
                reader=PdfReader(source)
                if reader.is_encrypted and not reader.decrypt(''):raise ValueError('This PDF requires a password')
                pages=[]
                for index,page in enumerate(reader.pages):
                    width,height=float(page.cropbox.width),float(page.cropbox.height)
                    if int(page.get('/Rotate',0))%180:width,height=height,width
                    pages.append(dict(index=index,width=width,height=height))
                return dict(kind='pdf',pages=pages,page_count=len(pages))
        except PdfReadError as exc:raise ValueError('This PDF cannot be previewed; the file is damaged or unsupported') from exc
    def _epub_metadata(self,row):
        try:return self._read_epub_metadata(row)
        except (zipfile.BadZipFile,ET.ParseError) as exc:raise ValueError('This EPUB cannot be previewed; its package is damaged or unsupported') from exc
    def _read_epub_metadata(self,row):
        with zipfile.ZipFile(row['path']) as archive:
            try:
                container=ET.fromstring(_read_member(archive,'META-INF/container.xml',2*1024*1024))
                package=next(element.get('full-path') for element in container.iter() if _local_name(element.tag)=='rootfile' and element.get('full-path'))
            except (KeyError,StopIteration):package=next((name for name in archive.namelist() if name.lower().endswith('.opf')),'')
            if not package:raise ValueError('This EPUB has no package manifest')
            package=_member(package);root=ET.fromstring(_read_member(archive,package,4*1024*1024));items={};resources={};navigation=[]
            members=set(archive.namelist())
            for element in root.iter():
                if _local_name(element.tag)!='item' or not element.get('id') or not element.get('href'):continue
                href=urlsplit(element.get('href'))
                if href.scheme or href.netloc:continue
                try:name=_member(posixpath.join(posixpath.dirname(package),unquote(href.path)))
                except ValueError:continue
                if name not in members:continue
                media=element.get('media-type','');items[element.get('id')]=dict(path=name,media=media)
                if 'nav' in element.get('properties','').split() or name.lower().endswith('.ncx'):navigation.append(name)
                mime=RESOURCE_MIMES.get(Path(name).suffix.lower())
                if mime:resources[name]=mime
            # Some publishers omit secondary CSS/fonts/images from the OPF.
            for name in members:
                try:normalized=_member(name)
                except ValueError:continue
                if normalized==name and Path(name).suffix.lower() in RESOURCE_MIMES:resources.setdefault(name,RESOURCE_MIMES[Path(name).suffix.lower()])
            titles=_navigation_titles(archive,navigation)
            chapters=[]
            for element in root.iter():
                if _local_name(element.tag)!='itemref' or element.get('linear','yes')=='no':continue
                item=items.get(element.get('idref'))
                if item and (item['media'] in ('application/xhtml+xml','text/html') or Path(item['path']).suffix.lower() in ('.html','.xhtml','.htm')):
                    chapters.append(dict(index=len(chapters),path=item['path'],title=titles.get(item['path']) or Path(item['path']).stem.replace('_',' ').replace('-',' ')))
            if not chapters:raise ValueError('This EPUB has no readable chapter spine')
            return dict(kind='epub',chapters=chapters,resources=resources,chapter_count=len(chapters),font_obfuscation=_font_obfuscation(archive,root,resources))
    def manifest(self,row,base_url):
        saved=self._metadata(row);result=dict(kind=saved['kind'],title=row['title'],version=self.version(row))
        if saved['kind']=='pdf':result.update(page_count=saved['page_count'],pages=[{**page,'url':_url(base_url,'page/'+str(page['index']))} for page in saved['pages']])
        else:result.update(chapter_count=saved['chapter_count'],chapters=[{key:value for key,value in chapter.items() if key!='path'}|{'url':_url(base_url,'chapter/'+str(chapter['index']))} for chapter in saved['chapters']])
        return result
    def _urls(self,metadata,member,base_url):return _EpubUrls(member,base_url,metadata['resources'],{chapter['path']:chapter['index'] for chapter in metadata['chapters']})
    def chapter(self,row,index,base_url):
        metadata=self._metadata(row)
        if metadata['kind']!='epub' or not 0<=index<metadata['chapter_count']:raise KeyError('Book chapter is unavailable')
        member=metadata['chapters'][index]['path']
        with zipfile.ZipFile(row['path']) as archive:source=_decode(_read_member(archive,member))
        parser=_Markup(self._urls(metadata,member,base_url));parser.feed(source);parser.close()
        return parser.result().encode('utf-8')
    def resource(self,row,name,base_url):
        metadata=self._metadata(row);name=_member(name)
        if metadata['kind']!='epub' or name not in metadata['resources']:raise KeyError('Book resource is unavailable')
        media=metadata['resources'][name]
        with zipfile.ZipFile(row['path']) as archive:payload=_read_member(archive,name,MAX_RESOURCE)
        obfuscation=metadata.get('font_obfuscation',{}).get(name)
        if obfuscation:
            key=bytes.fromhex(obfuscation['key']);count=min(len(payload),obfuscation['length'])
            payload=bytes(byte^key[index%len(key)] for index,byte in enumerate(payload[:count]))+payload[count:]
        urls=self._urls(metadata,name,base_url)
        if media=='text/css':payload=_css(_decode(payload),urls).encode('utf-8')
        elif media=='image/svg+xml':
            parser=_Markup(urls);parser.feed(_decode(payload));parser.close();payload=''.join(parser.parts).encode('utf-8')
        return payload,media
    def pdf_page(self,row,index):
        metadata=self._metadata(row)
        if metadata['kind']!='pdf' or not 0<=index<metadata['page_count']:raise KeyError('Book page is unavailable')
        output=self._folder(row)/('page-'+str(index)+'.png')
        with self.pdf_lock:
            if output.is_file():return output.read_bytes(),'image/png'
            try:import pypdfium2 as pdfium
            except ImportError as exc:raise ValueError('PDF preview renderer is unavailable; install pypdfium2 from requirements.txt') from exc
            with pdfium.PdfDocument(row['path']) as document:
                document.init_forms()
                page=document[index]
                try:
                    width,height=page.get_size()
                    if not math.isfinite(width) or not math.isfinite(height) or min(width,height)<=0:raise ValueError('This PDF has invalid page dimensions')
                    scale=min(2.0,2000/max(width,height),math.sqrt(4_000_000/(width*height)))
                    bitmap=page.render(scale=scale)
                    try:
                        with bitmap.to_pil() as image:
                            buffer=io.BytesIO();image.save(buffer,format='PNG');payload=buffer.getvalue()
                    finally:bitmap.close()
                finally:page.close()
            output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix('.png.tmp')
            temporary.write_bytes(payload);temporary.replace(output)
            return payload,'image/png'
    # [book-covers] THE BOOK'S OWN COVER.
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
                found=re.search(r'<(?:img|image)\b[^>]*?(?:src|href|xlink:href)=["\']([^"\']+)["\']',_decode(_read_member(archive,first)),re.I)
                name=member_of(found.group(1),posixpath.dirname(first)) if found else ''
                mime=RESOURCE_MIMES.get(Path(name).suffix.lower(),'')
                if name in members and mime.startswith('image/') and mime!='image/svg+xml':return _read_member(archive,name,MAX_RESOURCE)
        return None
