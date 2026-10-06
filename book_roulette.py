"""Source-bound book roulette for FM and H3; independent of book playback.

A generation shares one result in context['book_roulette']. Scheduled occurrence
receipts survive restarts; inspecting a prompt with persist=False never advances
that history. All passages are extracted locally, not invented by a model.

weighted(key, labels, weights, label) uses the station's System 3 dice door.
note(name, key, labels, picked) optionally records a renderer's slot receipt.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
import time
import zipfile
from collections import OrderedDict
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from typing import Any, Callable

import library_extract

VERSION = 3
NAMES = ('book', 'booktopic', 'bookchapter', 'booksegment', 'booksentence', 'booksentences')
TOKEN = re.compile(r'(?<!\{)\{(booksentences|booksentence|booksegment|bookchapter|booktopic|book)(?::([^{}\n]{1,240}))?\}(?!\})')
SENTENCE_TOKEN = re.compile(r'(?<!\{)\{sentence\}(?!\})')
BOOKTIME_TOKEN = re.compile(TOKEN.pattern + '|' + SENTENCE_TOKEN.pattern)
MAX_QUOTE_WORDS = 35
MAX_QUOTES_WORDS = 100
MAX_PASSAGE_WORDS = 180
MAX_PASSAGE_SENTENCES = 5
MAX_SECTIONS = 4096
MAX_RECEIPTS = 256


# Exact structural labels and split-member stems, never prose substrings.
_STRUCTURAL_LABELS = {
    'index', 'general index', 'subject index', 'name index', 'index of names',
    'contents', 'table of contents', 'toc', 'bibliography', 'references',
    'works cited', 'copyright', 'copyright page', 'title page', 'titlepage',
    'half title', 'halftitle', 'dedication', 'acknowledgments', 'acknowledgements',
    'glossary', 'endnotes', 'footnotes', 'list of illustrations', 'list of figures',
    'list of tables', 'about the author', 'about the authors', 'also by the author',
}
_STRUCTURAL_TYPES = {'index', 'toc', 'bibliography', 'copyright-page', 'titlepage',
                     'halftitlepage', 'dedication', 'acknowledgments', 'glossary',
                     'endnotes', 'footnotes', 'loi', 'lot'}


def _structural_section(*labels, source='', types=()):
    for label in labels:
        normalized = re.sub(r'\s+', ' ', str(label or '').strip()).casefold().strip(' .:-')
        if normalized in _STRUCTURAL_LABELS:
            return True
    semantic = {str(value).casefold().removeprefix('doc-') for value in types}
    if semantic & _STRUCTURAL_TYPES:
        return True
    stem = Path(str(source or '').split('#', 1)[0]).stem.casefold()
    # Calibre's real index_split_014.html and equivalent numbered matter files.
    stem = re.sub(r'[_-](?:split|part)[_-]?\d+$', '', stem)
    stem = re.sub(r'[_-]\d+$', '', stem)
    return re.sub(r'[_-]+', ' ', stem) in _STRUCTURAL_LABELS


def discussion_source_allowed(source):
    """Metadata-only guard for a saved source; never replaces a frozen receipt."""
    return not _structural_section(source.get('chapter'), source=source.get('member', ''),
                                   types=source.get('section_types') or ())


class BookRouletteError(ValueError):
    pass


class WeightedPick(int):
    """An index carrying effective desk weights for the durable source trace."""
    def __new__(cls, value: int, weights: list[float]):
        obj = int.__new__(cls, value)
        obj.weights = list(weights)
        return obj


def _clean(value: Any) -> str:
    return ' '.join(str(value or '').split())


def _identity(row: dict[str, Any]) -> str:
    return _clean(row.get('title')).casefold() + '\x1f' + _clean(row.get('author')).casefold()


def _words(text: str) -> int:
    return len(text.split())


def _split(text: str) -> list[str]:
    """Fold whitespace, retaining whole source sentences and abbreviation stops."""
    text = _clean(text)
    stop = '\ue180BOOKSTOP\ue181'
    while stop in text:
        stop += '\ue181'
    protect = re.compile(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\.', re.I)
    text = protect.sub(lambda m: m[0].replace('.', stop), text)
    text = re.sub(r'(?<=\d)\.(?=\d)', lambda _match: stop, text)
    text = re.sub(r'\b([A-Z])\.(?=\s+[A-Z])', lambda m: m[0].replace('.', stop), text)
    parts, start = [], 0
    for match in re.finditer(r"[.!?][\"\u201d\u2019')\]]*\s+(?=[\w\"\u201c\u2018])", text):
        parts.append(text[start:match.end()].strip())
        start = match.end()
    parts.append(text[start:].strip())
    return [part.replace(stop, '.') for part in parts if part]


def _complete(text: str) -> bool:
    return bool(re.search(r'[.!?]["\u201d\u2019\x27)\]]*$', text))


class _ChapterText(HTMLParser):
    """Readable blocks and original heading spelling; executable markup is data."""
    DROP = {'head', 'script', 'style', 'nav', 'noscript', 'svg', 'template'}
    BREAK = {'p', 'div', 'br', 'li', 'tr', 'section', 'article', 'blockquote', 'pre', 'td', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.heading = ''
        self.section_types = set()
        self.in_heading = False
        self.parts = []
        self.blocks = []

    def flush(self):
        text = _clean(''.join(self.parts))
        self.parts = []
        if text:
            if self.in_heading and not self.heading:
                self.heading = text
            if not self.in_heading:
                self.blocks.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in {'html', 'body'} or (tag in {'section', 'article'} and not self.blocks and not self.heading):
            for key, value in attrs:
                if key in {'epub:type', 'role'}:
                    self.section_types.update(str(value or '').split())
        if tag in self.DROP:
            self.skip += 1
        elif not self.skip:
            if tag in self.BREAK:
                self.flush()
            if tag.startswith('h') and tag[1:].isdigit():
                self.in_heading = True

    def handle_startendtag(self, tag, attrs):
        if tag not in self.DROP:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.DROP:
            self.skip = max(0, self.skip - 1)
        elif not self.skip:
            if tag in self.BREAK:
                self.flush()
            if tag.startswith('h') and tag[1:].isdigit():
                self.in_heading = False

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def _sentences(blocks: list[str], page: int) -> list[dict[str, Any]]:
    rows = []
    for paragraph, block in enumerate(blocks):
        for text in _split(block):
            rows.append(dict(index=len(rows), page=page, paragraph=paragraph, text=text))
    return rows


def _sections(rows: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Small consecutive windows, each containing a complete short quotation."""
    out, seen = [], set()
    for i, row in enumerate(rows):
        if not _complete(row['text']) or not 2 <= _words(row['text']) <= MAX_QUOTE_WORDS:
            continue
        start, end, total = i, i + 1, _words(row['text'])
        # Keep the surrounding passage contiguous and within the same paragraph.
        while end < len(rows) and end - start < MAX_PASSAGE_SENTENCES:
            nxt = rows[end]
            if nxt['paragraph'] != row['paragraph'] or total + _words(nxt['text']) > MAX_PASSAGE_WORDS:
                break
            total += _words(nxt['text']); end += 1
        while start > 0 and end - start < MAX_PASSAGE_SENTENCES:
            prev = rows[start - 1]
            if prev['paragraph'] != row['paragraph'] or total + _words(prev['text']) > MAX_PASSAGE_WORDS:
                break
            total += _words(prev['text']); start -= 1
        pair = (start, end)
        if pair not in seen:
            seen.add(pair); out.append(dict(index=len(out), start=start, end=end))
    if len(out) > MAX_SECTIONS:
        # Evenly sample an unusually large chapter; never truncate a passage.
        out = [out[round(i * (len(out) - 1) / (MAX_SECTIONS - 1))] for i in range(MAX_SECTIONS)]
    return out


def _epub(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    chapters, subjects = [], []
    with zipfile.ZipFile(path) as archive:
        order, titles, _ = library_extract._epub_spine(archive)
        for name in archive.namelist():
            if name.lower().endswith('.opf') and archive.getinfo(name).file_size <= 2 * 1024 * 1024:
                try:
                    from xml.etree import ElementTree as ET
                    package = ET.fromstring(archive.read(name))
                    subjects.extend(_clean(''.join(el.itertext())) for el in package.iter()
                                    if el.tag.rsplit('}', 1)[-1] == 'subject')
                except (ValueError, ET.ParseError):
                    pass
        members = {library_extract._norm_href(name): name for name in archive.namelist()}
        spent = 0
        for i, source in enumerate(order[:library_extract.MAX_PAGES]):
            name = members.get(source, source)
            size = archive.getinfo(name).file_size
            if size > 4 * 1024 * 1024 or spent + size > 64 * 1024 * 1024:
                continue
            spent += size
            parser = _ChapterText()
            parser.feed(archive.read(name).decode('utf-8', 'replace')); parser.close(); parser.flush()
            if _structural_section(parser.heading, titles.get(source), source=source, types=parser.section_types):
                continue
            rows = _sentences(parser.blocks, i + 1)
            sections = _sections(rows)
            if sections:
                chapters.append(dict(index=i + 1, title=parser.heading or titles.get(source) or f'Section {i + 1}',
                                     basis='epub_spine', source=source, page=i + 1, sentences=rows, sections=sections))
    return chapters, list(dict.fromkeys(s for s in subjects if s))[:64]


def _pdf(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    # The station extractor normalizes PDF line-wrap and repeated text once.
    document = library_extract.read_pdf(path)
    outlines, subjects = [], []
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        metadata = reader.metadata or {}
        keywords = _clean(metadata.get('/Keywords') or metadata.get('/Subject'))
        subjects = [_clean(part) for part in re.split(r'[,;]', keywords) if _clean(part)]
        def walk(items):
            for item in items:
                if isinstance(item, list):
                    walk(item)
                else:
                    try:
                        page = reader.get_destination_page_number(item) + 1
                        title = _clean(item.title)
                        if page > 0 and title:
                            outlines.append((page, title))
                    except (AttributeError, TypeError, ValueError):
                        pass
        walk(reader.outline)
    except Exception:
        pass
    outlines = sorted(set(outlines), key=lambda pair: pair[0])
    chapters = []
    for page in document['pages']:
        n = int(page['n'])
        available = [(j, p, title) for j, (p, title) in enumerate(outlines) if p <= n]
        if available:
            j, _p, title = available[-1]
            index, basis = j + 1, 'pdf_outline'
        else:
            index, title, basis = n, f'Page {n}', 'page'
        if basis == 'pdf_outline' and _structural_section(title):
            continue
        blocks = [_clean(b) for b in re.split(r'\n\s*\n', page['text']) if _clean(b)]
        rows = _sentences(blocks, n)
        sections = _sections(rows)
        if sections:
            # A page remains a bounded source unit even inside a named chapter.
            chapters.append(dict(index=index, title=title, basis=basis, source=f'page:{n}',
                                 page=n, sentences=rows, sections=sections))
    return chapters, list(dict.fromkeys(subjects))[:64]


_STOP = frozenset('the a an and or but for of to in on with by from as at is was are were be been that this these those it its i you he she they we his her their our not so if then there here when what which who how'.split())


def _topics(source: dict[str, Any], chapter: dict[str, Any], passage: str) -> list[dict[str, str]]:
    out = [dict(id='subject:' + str(i), label=s, basis='book_metadata')
           for i, s in enumerate(source.get('subjects') or [])]
    if chapter['basis'] != 'page' and not re.fullmatch(r'(chapter|section)\s+[\divxlc]+', chapter['title'], re.I):
        out.append(dict(id='heading', label=chapter['title'], basis='chapter_heading'))
    # Source phrases supplement missing subject metadata, without model guesses.
    for i, match in enumerate(re.finditer(r"\b[\w]+(?:['\u2019-][\w]+)*\s+[\w]+(?:['\u2019-][\w]+)*\b", passage, re.UNICODE)):
        phrase = match.group(0)
        pair = phrase.split()
        if all(w.casefold() not in _STOP and len(w) > 2 for w in pair):
            out.append(dict(id='phrase:' + str(i), label=phrase, basis='source_phrase'))
            if len(out) >= 12:
                break
    if not out:
        quote = next((line for line in _split(passage) if _complete(line) and _words(line) <= MAX_QUOTE_WORDS), passage)
        out = [dict(id='source', label=quote, basis='source_sentence')]
    seen = set()
    return [row for row in out if not (row['label'].casefold() in seen or seen.add(row['label'].casefold()))]


class BookRoulette:
    def __init__(self, mode: Any, data: Path | str | None = None):
        self.mode = mode
        self.data = Path(data) if data is not None else Path(mode.data) / 'roulette'
        self.lock = RLock()
        self.async_lock = asyncio.Lock()
        self.cache = OrderedDict()
        self.state = self._read(self.data / 'state.json', dict(version=VERSION, recent=[], recent_titles=[], receipts={}, failures={}))
        if not isinstance(self.state, dict):
            self.state = {}
        changed = self.state.get('version') != VERSION
        # Extractor versions invalidate source caches, never a frozen episode.
        # Recorded parts retain the original exact passage across deployments.
        for key, empty in (('recent', []), ('recent_titles', []), ('receipts', {}), ('failures', {})):
            if not isinstance(self.state.get(key), type(empty)):
                self.state[key] = copy.deepcopy(empty)
        self.state['version'] = VERSION
        if changed:
            self.state['failures'] = {}  # the new extractor can retry prior failures
            self._write(self.data / 'state.json', self.state)

    @staticmethod
    def _read(path: Path, fallback: Any):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return copy.deepcopy(fallback)

    @staticmethod
    def _write(path: Path, value: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    def _load(self, row: dict[str, Any]) -> dict[str, Any]:
        key = str(row['id']) + ':' + str(row['stamp'])
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        path = self.data / 'sources' / (str(row['id']) + '.json')
        source = self._read(path, {})
        if source.get('version') != VERSION or source.get('stamp') != row['stamp']:
            actual = Path(row['path'])
            if not actual.is_file():
                raise BookRouletteError('The selected book source is unavailable')
            if actual.stat().st_size > library_extract.MAX_BYTES:
                raise BookRouletteError('The selected book is too large to extract')
            chapters, subjects = _epub(actual) if row['kind'] == 'epub' else _pdf(actual)
            if not chapters:
                raise BookRouletteError('No readable passage with a complete short sentence; scanned PDFs require OCR')
            source = dict(version=VERSION, stamp=row['stamp'], chapters=chapters, subjects=subjects)
            with self.lock:
                self._write(path, source)
        with self.lock:
            self.cache[key] = source
            while len(self.cache) > 3:
                self.cache.popitem(last=False)
        return source

    def source_for(self, occurrence: str) -> dict[str, Any]:
        """A saved occurrence receipt; does not extract or draw another source."""
        with self.lock:
            return copy.deepcopy(self.state.get('receipts', {}).get(str(occurrence), {}))

    def restore_receipt(self, occurrence: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Restore a real persisted part's authority, without drawing or rewriting it.

        This recovery door is used before any new authoring after a restart.
        It accepts only a complete source receipt whose exact passage verifies.
        The caller must own the earliest persisted part of this occurrence.
        """
        occurrence = str(occurrence or '').strip()
        source = receipt.get('source') if isinstance(receipt, dict) else None
        values = receipt.get('values') if isinstance(receipt, dict) else None
        if (not occurrence or not isinstance(source, dict) or not isinstance(values, dict)
                or not source.get('book_id') or not source.get('title')
                or str(values.get('book') or '') != str(source['title'])
                or not values.get('booksegment')
                or hashlib.sha256(str(values['booksegment']).encode()).hexdigest()[:20] != source.get('content_hash')):
            raise BookRouletteError('The persisted Book Time source receipt cannot be verified')
        with self.lock:
            if self.state['receipts'].get(occurrence) != receipt:
                previous = self.state['receipts'].get(occurrence)
                if previous:
                    self.state.setdefault('source_recoveries', []).append(dict(
                        occurrence=occurrence, at=time.time(), previous=copy.deepcopy(previous.get('source') or {}),
                        canonical=copy.deepcopy(source)))
                    self.state['source_recoveries'] = self.state['source_recoveries'][-100:]
                self.state['receipts'][occurrence] = copy.deepcopy(receipt)
                self.state['receipts'] = dict(list(self.state['receipts'].items())[-MAX_RECEIPTS:])
                # Recover missing history too, without consuming a roulette draw.
                if source['book_id'] not in self.state['recent']:
                    self.state['recent'].append(source['book_id'])
                identity = _identity(source)
                if identity not in self.state['recent_titles']:
                    self.state['recent_titles'].append(identity)
                self._write(self.data / 'state.json', self.state)
        return copy.deepcopy(receipt)

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = list(self.state.get('receipts', {}).values())[-max(1, min(100, int(limit))) :]
            return [dict(occurrence=row['occurrence'], at=row['at'], source=copy.deepcopy(row['source'])) for row in reversed(rows)]

    def status(self) -> dict[str, Any]:
        with self.lock:
            return dict(version=VERSION, books=len(self.mode.catalog), receipts=len(self.state.get('receipts', {})),
                        recent_books=len(set(self.state.get('recent') or [])), cached_sources=len(self.cache),
                        failures=copy.deepcopy(self.state.get('failures') or {}), history=self.history(5))

    def catalog_options(self) -> list[dict[str, Any]]:
        """Metadata-only live source options, suitable for System 3's wheel UI."""
        return [dict(id=row['id'], title=row['title'], author=row.get('author', ''), kind=row['kind'],
                     label=str(row['title']) + (' — ' + str(row['author']) if row.get('author') else ''))
                for row in sorted(self.mode.catalog.values(), key=lambda row: (str(row['title']).casefold(), row['id']))
                if row.get('kind') in ('epub', 'pdf')]

    def _binding(self, texts: tuple[Any, ...], binding: Any) -> str:
        if any(m.group(2) and m.group(1) != 'book' for text in texts for m in TOKEN.finditer(str(text or ''))):
            raise BookRouletteError('Only {book:Title or ID} accepts an explicit book binding')
        requested = [_clean(binding)] if binding else []
        requested += [_clean(m.group(2)) for text in texts for m in TOKEN.finditer(str(text or ''))
                      if m.group(1) == 'book' and m.group(2)]
        if not requested:
            return ''
        ids = []
        catalog = dict(self.mode.catalog)
        for name in requested:
            matches = [str(row['id']) for row in catalog.values()
                       if str(row['id']) == name or _clean(row['title']).casefold() == name.casefold()]
            if not matches:
                raise BookRouletteError('Book title or ID is unavailable: ' + name)
            if len(matches) > 1:
                raise BookRouletteError('Book title is ambiguous; bind its library ID: ' + name)
            ids.append(matches[0])
        if len(set(ids)) > 1:
            raise BookRouletteError('One generation can bind only one book; use separate generations for different titles')
        return ids[0]

    @staticmethod
    def _pick(key: str, rows: list[dict[str, Any]], label: str, weighted: Callable,
              note: Callable | None, rolls: list[dict[str, Any]], weights: Any):
        if not rows:
            raise BookRouletteError('No eligible options for ' + key)
        labels = [str(row['label']) for row in rows]
        mapping = (weights or {}).get(key, {}) if isinstance(weights, dict) else {}
        values = []
        for row in rows:
            try:
                value = float(mapping.get(str(row.get('id', '')), mapping.get(row['label'], 1.0)))
            except (TypeError, ValueError):
                value = 1.0
            values.append(max(0.0, value) if math.isfinite(value) else 0.0)
        if not any(values):
            raise BookRouletteError('All roulette options are disabled for ' + key)
        index = weighted(key, labels, values, label)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(rows) or values[index] <= 0:
            # A broken callback is not permission to silently invent a new draw.
            raise BookRouletteError('System 3 returned an invalid book roulette choice for ' + key)
        effective = getattr(index, 'weights', values)
        if len(effective) == len(values):
            values = list(effective)
        chosen = rows[index]
        rolls.append(dict(key=key, label=label, index=int(index), total=len(rows), picked=labels[index],
                          picked_id=str(chosen.get('id', '')), candidates=[dict(id=str(r.get('id', '')), label=r['label'], weight=w)
                          for r, w in list(zip(rows, values))[:64]], candidates_truncated=len(rows) > 64))
        if note:
            note('slot_' + key.replace('.', '_'), key, labels, labels[index])
        return chosen

    def _steps(self, texts, weighted, note, context, binding, occurrence, scheduled, persist, booktime, weights):
        needed = any(TOKEN.search(str(text or '')) for text in texts)
        if booktime:
            needed = needed or any(SENTENCE_TOKEN.search(str(text or '')) for text in texts)
        if not needed and not binding and not scheduled:
            return {}
        book_id = self._binding(texts, binding)
        memo = context.get('book_roulette') if isinstance(context, dict) else None
        if memo:
            if book_id and memo['source']['book_id'] != book_id:
                raise BookRouletteError('Book binding conflicts with the existing generation context')
            return copy.deepcopy(memo)
        occurrence = str(occurrence or '').strip()
        if scheduled and not occurrence:
            raise BookRouletteError('A scheduled Book Time draw requires its occurrence ID')
        with self.lock:
            receipt = self.state['receipts'].get(occurrence) if occurrence else None
            failures = dict(self.state.get('failures') or {})
            recent = list(self.state.get('recent') or [])
            recent_titles = list(self.state.get('recent_titles') or [])
        if receipt:
            if book_id and receipt['source']['book_id'] != book_id:
                raise BookRouletteError('Book binding conflicts with the saved scheduled occurrence')
            if isinstance(context, dict):
                context['book_roulette'] = copy.deepcopy(receipt)
            return copy.deepcopy(receipt)
        catalog = sorted((dict(row) for row in self.mode.catalog.values()), key=lambda row: (str(row['title']).casefold(), row['id']))
        catalog = [row for row in catalog if row.get('kind') in ('epub', 'pdf')]
        if not catalog:
            raise BookRouletteError('The book library has no available EPUB or PDF titles')
        if book_id:
            catalog = [row for row in catalog if row['id'] == book_id]
            if scheduled and recent_titles and catalog and _identity(catalog[0]) == recent_titles[-1]:
                raise BookRouletteError('A different readable title is required for the next Book Time segment')
        elif scheduled:
            # Avoid the immediately preceding title even after a full-library cycle.
            fresh = [row for row in catalog if row['id'] not in recent and _identity(row) not in recent_titles]
            if not fresh:
                fresh = [row for row in catalog if (not recent or row['id'] != recent[-1])
                         and (not recent_titles or _identity(row) != recent_titles[-1])]
            catalog = fresh
            if not catalog:
                raise BookRouletteError('A different readable title is required for the next Book Time segment')
        rows = [dict(row, label=str(row['title']) + (' — ' + str(row['author']) if row.get('author') else ''))
                for row in catalog if failures.get(row['id'], {}).get('stamp') != row['stamp']
                or time.time() - float(failures.get(row['id'], {}).get('at') or 0) > float(failures.get(row['id'], {}).get('ttl') or 86400)]
        if not rows and book_id:
            # An explicit selection can retry a transient source error.
            rows = [dict(row, label=str(row['title'])) for row in catalog]
        rolls, skipped, source, chosen = [], [], None, None
        attempts = min(12, len(rows))
        for _ in range(attempts):
            chosen = rows[0] if book_id else self._pick('book.source', rows, 'Which book supplies this generation', weighted, note, rolls, weights)
            try:
                source = yield chosen
                break
            except Exception as exc:
                skipped.append(dict(book_id=chosen['id'], title=chosen['title'], reason=str(exc)[:240]))
                if book_id:
                    raise BookRouletteError(str(exc)) from exc
                # Cache extraction failures by version; changed files become eligible.
                if persist:
                    with self.lock:
                        self.state.setdefault('failures', {})[chosen['id']] = dict(stamp=chosen['stamp'], reason=str(exc)[:240], at=time.time(), ttl=60 if isinstance(exc, OSError) or 'unavailable' in str(exc).lower() else 86400)
                        self.state['failures'] = dict(list(self.state['failures'].items())[-4096:])
                        self._write(self.data / 'state.json', self.state)
                rows = [row for row in rows if row['id'] != chosen['id']]
        if source is None or chosen is None:
            raise BookRouletteError('No readable book passage is currently available' + (': ' + skipped[-1]['reason'] if skipped else ''))
        chapter_rows = [dict(id=str(i), label=str(c['title']) + (f" · page {c['page']}" if chosen['kind'] == 'pdf' else ''), value=c)
                        for i, c in enumerate(source['chapters'])]
        chapter = self._pick('book.chapter', chapter_rows, 'Which chapter or source page supplies the discussion', weighted, note, rolls, weights)['value']
        sentences = chapter['sentences']
        section_rows = [dict(id=str(i), label=_clean(' '.join(r['text'] for r in sentences[s['start']:s['end']]))[:240], value=s)
                        for i, s in enumerate(chapter['sections'])]
        section = self._pick('book.segment', section_rows, 'Which short consecutive passage the DJs discuss', weighted, note, rolls, weights)['value']
        passage_rows = sentences[section['start']:section['end']]
        quote_rows = [dict(id=str(r['index']), label=r['text'], value=r) for r in passage_rows
                      if _complete(r['text']) and 2 <= _words(r['text']) <= MAX_QUOTE_WORDS]
        quote = self._pick('book.sentence', quote_rows, 'Which complete short sentence is quoted', weighted, note, rolls, weights)['value']
        cluster = []
        for r in sentences[quote['index']:section['end']]:
            if not _complete(r['text']) or len(cluster) >= 3 or _words(' '.join(x['text'] for x in cluster) + ' ' + r['text']) > MAX_QUOTES_WORDS:
                break
            cluster.append(r)
        passage = ' '.join(r['text'] for r in passage_rows)
        topic = self._pick('book.topic', _topics(source, chapter, passage), 'Which source-backed book topic shapes the discussion', weighted, note, rolls, weights)
        locator = chapter['title'] if chapter['basis'] != 'page' else f"page {chapter['page']} (chapter not supplied)"
        values = dict(book=str(chosen['title']), booktopic=topic['label'], bookchapter=locator,
                      booksegment=passage, booksentence=quote['text'], booksentences=' '.join(r['text'] for r in cluster))
        if booktime:
            values['sentence'] = quote['text']
        result = dict(version=VERSION, values=values, occurrence=occurrence, scheduled=bool(scheduled), at=time.time(),
                      source=dict(book_id=chosen['id'], title=chosen['title'], author=chosen.get('author', ''), kind=chosen['kind'], stamp=chosen['stamp'],
                                  chapter=chapter['title'], chapter_index=chapter['index'], chapter_basis=chapter['basis'], member=chapter['source'], page=quote['page'],
                                  section_index=section['index'], sentence_index=quote['index'], sentence_indices=[r['index'] for r in cluster],
                                  passage_sentence_indices=[r['index'] for r in passage_rows], topic_basis=topic['basis'],
                                  content_hash=hashlib.sha256(passage.encode()).hexdigest()[:20]), rolls=rolls, skipped=skipped)
        if persist and scheduled:
            with self.lock:
                self.state['recent'] = (self.state.get('recent', []) + [chosen['id']])[-max(64, len(self.mode.catalog)) :]
                self.state['recent_titles'] = (self.state.get('recent_titles', []) + [_identity(chosen)])[-max(64, len(self.mode.catalog)) :]
                self.state['receipts'][occurrence] = copy.deepcopy(result)
                self.state['receipts'] = dict(list(self.state['receipts'].items())[-MAX_RECEIPTS:])
                self._write(self.data / 'state.json', self.state)
        if isinstance(context, dict):
            context['book_roulette'] = copy.deepcopy(result)
        return result

    def resolve(self, *texts: Any, weighted: Callable, note: Callable | None = None, context: dict | None = None,
                binding: Any = '', occurrence: str = '', scheduled: bool = False, persist: bool = True,
                booktime: bool = False, weights: dict | None = None) -> dict[str, Any]:
        """Synchronous H3 fill. Prefer resolve_async when already on the station loop."""
        steps = self._steps(texts, weighted, note, context, binding, occurrence, scheduled, persist, booktime, weights)
        value, error = None, None
        while True:
            try:
                row = steps.throw(error) if error is not None else steps.send(value)
            except StopIteration as done:
                return done.value
            try:
                value, error = self._load(row), None
            except Exception as exc:
                value, error = None, exc

    async def resolve_async(self, *texts: Any, weighted: Callable, note: Callable | None = None, context: dict | None = None,
                            binding: Any = '', occurrence: str = '', scheduled: bool = False, persist: bool = True,
                            booktime: bool = False, weights: dict | None = None) -> dict[str, Any]:
        """Extract off the loop; System 3 draws and slot receipts run on its task."""
        async with self.async_lock:
            steps = self._steps(texts, weighted, note, context, binding, occurrence, scheduled, persist, booktime, weights)
            value, error = None, None
            while True:
                try:
                    row = steps.throw(error) if error is not None else steps.send(value)
                except StopIteration as done:
                    return done.value
                try:
                    value, error = await asyncio.to_thread(self._load, row), None
                except Exception as exc:
                    value, error = None, exc


def expand(text: Any, result: dict[str, Any], *, booktime: bool = False) -> str:
    values = result.get('values') or {}
    pattern = BOOKTIME_TOKEN if booktime else TOKEN
    return pattern.sub(lambda match: str(values.get(match.group(1) or 'booksentence', '[Book source unavailable]')),
                       str(text or ''))


async def expand_messages(messages: list[dict[str, Any]], resolver: BookRoulette, *, weighted: Callable,
                          context: dict | None = None, booktime: bool = False, **options) -> list[dict[str, Any]]:
    """Only the current request's system and final user messages are expanded."""
    users = [i for i, row in enumerate(messages) if isinstance(row, dict) and row.get('role') == 'user']
    last = users[-1] if users else -1
    selected = [i for i, row in enumerate(messages) if isinstance(row, dict)
                and (row.get('role') == 'system' or i == last) and isinstance(row.get('content'), str)
                and (TOKEN.search(row['content']) or (booktime and SENTENCE_TOKEN.search(row['content'])))]
    if not selected:
        return messages
    result = await resolver.resolve_async(*[messages[i]['content'] for i in selected], weighted=weighted,
                                          context=context, booktime=booktime, **options)
    out = list(messages)
    for i in selected:
        out[i] = dict(messages[i], content=expand(messages[i]['content'], result, booktime=booktime))
    return out
