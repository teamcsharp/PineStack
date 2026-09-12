"""Read a document off the shelf and hand back pages the station can use.

Every reader in here returns the SAME page shape the gear-manual corpus
already uses (app.py: te_doc / _te_page_score / te_section_text), so the
rankers, the citation lines and the doc browser all work unchanged:

    {"n": 1, "heading": "sampling", "text": "...", "blocks": [{"text": ...}],
     "source_url": ""}

Handled: .pdf .epub .zip(of html) .docx .txt .md .html .htm .rst

Nothing here imports app.py, nothing here touches the network, and nothing
here is async — the caller runs it inside asyncio.to_thread. The one optional
dependency is pypdf; poppler's pdftotext is preferred when the box has it
(the host does, the python:3.12-slim container does not).
"""
from __future__ import annotations

import hashlib
import html as _html
import re
import shutil
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# What we will open at all. Anything else on the shelf is left alone.
KINDS: dict[str, str] = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".zip": "zip",
    ".docx": "docx",
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
    ".rst": "text",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
}

# Windows leaves these all over an SMB share; they are not documents.
SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

MAX_BYTES = 400 * 1024 * 1024      # a document bigger than this is a mistake
MAX_PAGES = 6000                   # the MPC guide is ~500; this is headroom
MAX_PAGE_CHARS = 20000             # one "page" of a text file
TEXT_PAGE_CHARS = 6000             # how big a slice of a .md/.txt page is
MAX_FIGURES = 3000                 # epub images written out for display
MAX_FIGURE_BYTES = 96 * 1024 * 1024
MIN_PAGE_CHARS = 40                # under this a page carries no answer

_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")


class ExtractError(RuntimeError):
    """The document could not be read. Carries a line fit for the console."""


# --------------------------------------------------------------------------
# text tidying


def squash(text: str) -> str:
    """One space per gap, at most one blank line, no trailing whitespace."""
    text = _html.unescape(str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _NL.sub("\n\n", text).strip()


def dedupe_lines(text: str) -> str:
    """Print-designed PDFs come out of the extractor with lines that repeat a
    word from the line before and stutter inside themselves. Collapse both.
    (The same trick tools/te_build.py plays on the OCR'd TE notebooks.)"""
    out: list[str] = []
    carry = ""
    for line in text.split("\n"):
        words: list[str] = []
        for word in line.split(" "):
            if words and word and word.lower() == words[-1].lower():
                continue
            words.append(word)
        words = [w for w in words if w]
        line = " ".join(words).strip()
        if words and carry and len(words[0]) > 1 and words[0].lower() == carry:
            words = words[1:]
            line = " ".join(words).strip()
        if not line:
            carry = ""
            if out and out[-1] != "":
                out.append("")
            continue
        if out and line == out[-1]:
            continue
        carry = words[-1].lower() if words else ""
        out.append(line)
    return "\n".join(out).strip()


def paragraphs(text: str, cap: int = 400) -> list[dict[str, str]]:
    """The page's blocks — what the snip picker and the chunker read."""
    out: list[dict[str, str]] = []
    for para in re.split(r"\n\s*\n", text):
        body = " ".join(para.split())
        if len(body) < 2:
            continue
        out.append({"text": body[:1200]})
        if len(out) >= cap:
            break
    return out


def guess_heading(text: str) -> str:
    """The first line that reads like a title, else nothing."""
    for line in text.split("\n"):
        line = " ".join(line.split())
        if not line:
            continue
        if 2 <= len(line) <= 70 and not line.endswith((".", ",", ";")):
            return line.strip("#* ").lower()[:60]
        return ""
    return ""


def page_row(n: int, heading: str, text: str, source: str = "") -> dict[str, Any]:
    text = squash(text)
    return {"n": int(n), "heading": squash(heading)[:60].lower(),
            "text": text[:MAX_PAGE_CHARS], "blocks": paragraphs(text),
            "source_url": str(source or "")}


# --------------------------------------------------------------------------
# html


class _Text(HTMLParser):
    """Readable text out of a chapter, plus its first real heading."""

    DROP = {"script", "style", "head", "nav", "noscript", "svg", "template"}
    BREAK = {"p", "div", "br", "li", "tr", "section", "article", "figure",
             "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading = ""
        self.images: list[str] = []
        self._skip = 0
        self._in_head = 0
        self._head_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.DROP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "img":
            src = dict(attrs).get("src") or ""
            if src:
                self.images.append(src)
            self.parts.append("\n")
            return
        if tag in {"h1", "h2", "h3"} and not self.heading:
            self._in_head += 1
        if tag in self.BREAK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs) -> None:  # type: ignore[no-untyped-def]
        # A self-closing <script src="..."/> has no body to skip. Routing it
        # through handle_starttag raised the skip counter with nothing to
        # lower it again, and every word after it in the chapter was dropped
        # — which is exactly how a 44-chapter book read as one blank page.
        if tag in self.DROP:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.DROP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in {"h1", "h2", "h3"} and self._in_head:
            self._in_head = max(0, self._in_head - 1)
            if not self._in_head and not self.heading:
                self.heading = " ".join("".join(self._head_buf).split())[:60].lower()
                self._head_buf = []
        if tag in {"p", "div", "li", "tr", "section", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        if self._in_head:
            self._head_buf.append(data)
        self.parts.append(data)

    def text(self) -> str:
        return squash("".join(self.parts))


class _Sanitize(HTMLParser):
    """Re-emit a chapter with everything executable taken out, so it can be
    dropped straight into the reader pane. Scripts, styles, frames, event
    handlers and javascript: urls do not survive; images are rewritten to the
    files we extracted beside the chapter."""

    DROP = {"script", "style", "link", "meta", "iframe", "object", "embed",
            "form", "input", "button", "base", "head", "html", "body", "title"}
    SILENT = {"head", "html", "body", "meta", "link", "base"}
    VOID = {"img", "br", "hr", "col", "source", "area", "wbr"}
    KEEP_ATTR = {"src", "alt", "title", "colspan", "rowspan", "id"}

    def __init__(self, assets: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.assets = assets
        self._skip = 0

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        bits: list[str] = []
        for key, raw in attrs:
            key = (key or "").lower()
            val = raw or ""
            if key.startswith("on") or key not in self.KEEP_ATTR:
                continue
            if key == "src":
                if tag != "img":
                    continue
                val = self.assets.get(_norm_href(val), "")
                if not val:
                    continue
            if "javascript:" in val.lower():
                continue
            bits.append(f' {key}="{_html.escape(val, quote=True)}"')
        return "".join(bits)

    def handle_starttag(self, tag, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in self.DROP:
            if tag not in self.SILENT:
                self._skip += 1
            return
        if self._skip:
            return
        if tag == "a":
            self.out.append("<span>")
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}>")

    def handle_startendtag(self, tag, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in self.DROP or self._skip:
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.DROP:
            if tag not in self.SILENT:
                self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag in self.VOID:
            return
        self.out.append("</span>" if tag == "a" else f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(_html.escape(data))

    def html(self) -> str:
        return "".join(self.out)


def _norm_href(href: str) -> str:
    """A chapter's relative link, flattened to a comparable key."""
    href = str(href or "").split("#", 1)[0].split("?", 1)[0].strip()
    href = _html.unescape(href)
    parts: list[str] = []
    for bit in href.replace("\\", "/").split("/"):
        if not bit or bit == ".":
            continue
        if bit == "..":
            if parts:
                parts.pop()
            continue
        parts.append(bit)
    return "/".join(parts)


def _resolve(base: str, href: str) -> str:
    """Resolve a chapter-relative href against the chapter's own zip path."""
    href = str(href or "").split("#", 1)[0].split("?", 1)[0]
    if not href or "://" in href:
        return ""
    if href.startswith("/"):
        return _norm_href(href)
    root = "/".join(base.split("/")[:-1])
    return _norm_href(f"{root}/{href}" if root else href)


def safe_asset_name(name: str) -> str:
    """A flat, boring filename for an extracted figure."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name.replace("/", "_")).strip("._")
    return (stem or "figure")[:100]


# --------------------------------------------------------------------------
# pdf


def _pdftotext(path: Path) -> list[str]:
    """poppler when the box has it — it reads print-designed layouts far
    better than anything pure-python. Pages arrive form-feed separated."""
    if not shutil.which("pdftotext"):
        return []
    try:
        run = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8",
                              str(path), "-"],
                             capture_output=True, timeout=900)
    except Exception:  # noqa: BLE001 - a missing/990-page pdf is not fatal
        return []
    if run.returncode != 0:
        return []
    return run.stdout.decode("utf-8", "replace").split("\f")


def _pypdf_pages(path: Path) -> list[str]:
    try:
        import logging                       # noqa: PLC0415
        from pypdf import PdfReader          # noqa: PLC0415 - optional dep
        # A print-designed manual makes pypdf grumble once per odd font and
        # once per damaged page. It recovers from all of it, and the station
        # log is not the place to hear about it - the console's `thin` flag
        # is how a badly-read document actually gets reported.
        logging.getLogger("pypdf").setLevel(logging.ERROR)
    except Exception as exc:  # noqa: BLE001
        raise ExtractError(
            "no pdf reader on this box (pdftotext missing and pypdf not "
            f"installed: {exc})") from exc
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ExtractError(f"the pdf would not open: {exc}") from exc
    out: list[str] = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page, not a dead document
            out.append("")
    return out


def read_pdf(path: Path) -> dict[str, Any]:
    raw = _pdftotext(path) or _pypdf_pages(path)
    pages: list[dict[str, Any]] = []
    for i, body in enumerate(raw[:MAX_PAGES], start=1):
        text = dedupe_lines(squash(body))
        if len(text) < MIN_PAGE_CHARS:
            continue
        pages.append(page_row(i, guess_heading(text), text))
    return {"pages": pages, "figures": 0}


# --------------------------------------------------------------------------
# epub / zip-of-html


def _zip_read(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        with zf.open(name) as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return b""


def _epub_spine(zf: zipfile.ZipFile) -> tuple[list[str], dict[str, str], str]:
    """(chapter paths in reading order, path -> title, book title)."""
    container = _zip_read(zf, "META-INF/container.xml")
    opf_path = ""
    if container:
        try:
            root = ET.fromstring(container)
            for el in root.iter():
                if el.tag.endswith("rootfile") and el.get("full-path"):
                    opf_path = _norm_href(el.get("full-path") or "")
                    break
        except ET.ParseError:
            pass
    if not opf_path:
        opf_path = next((n for n in zf.namelist()
                         if n.lower().endswith(".opf")), "")
    if not opf_path:
        raise ExtractError("no OPF inside the epub")
    try:
        opf = ET.fromstring(_zip_read(zf, opf_path))
    except ET.ParseError as exc:
        raise ExtractError(f"the epub's OPF is malformed: {exc}") from exc

    base = "/".join(opf_path.split("/")[:-1])

    def against_opf(href: str) -> str:
        return _norm_href(f"{base}/{href}" if base else href)

    title = ""
    manifest: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    nav_href = ""
    for el in opf.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "title" and not title:
            title = " ".join((el.text or "").split())[:120]
        elif tag == "item":
            iid, href = el.get("id") or "", el.get("href") or ""
            if iid and href:
                manifest[iid] = (against_opf(href), el.get("media-type") or "")
                if "nav" in (el.get("properties") or "").split():
                    nav_href = against_opf(href)
        elif tag == "itemref":
            idref = el.get("idref") or ""
            if idref:
                order.append(idref)

    chapters = [manifest[i][0] for i in order
                if i in manifest and manifest[i][0]
                and manifest[i][0] != nav_href]
    if not chapters:
        chapters = [p for p, _m in sorted(manifest.values())
                    if p.lower().endswith((".xhtml", ".html", ".htm"))]
    return chapters, _epub_titles(zf, nav_href, manifest), title


def _epub_titles(zf: zipfile.ZipFile, nav_href: str,
                 manifest: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Chapter titles out of the epub3 nav or the epub2 ncx, when there is one."""
    titles: dict[str, str] = {}
    sources = [nav_href] + [p for p, _m in manifest.values()
                            if p.lower().endswith(".ncx")]
    for src in [s for s in sources if s]:
        raw = _zip_read(zf, src)
        if not raw:
            continue
        root_dir = "/".join(src.split("/")[:-1])

        def key_for(href: str) -> str:
            return _norm_href(f"{root_dir}/{href}" if root_dir else href)

        try:
            tree = ET.fromstring(raw)
        except ET.ParseError:
            continue
        # epub3: the nav document is a list of <a href>text</a>
        for el in tree.iter():
            if el.tag.rsplit("}", 1)[-1] != "a":
                continue
            href = el.get("href") or ""
            label = " ".join("".join(el.itertext()).split())[:60].lower()
            if href and label:
                titles.setdefault(key_for(href), label)
        # epub2: navPoint carries the label beside the content element
        for el in tree.iter():
            if el.tag.rsplit("}", 1)[-1] != "navPoint":
                continue
            label, href = "", ""
            for kid in el.iter():
                kt = kid.tag.rsplit("}", 1)[-1]
                if kt == "text" and not label:
                    label = " ".join((kid.text or "").split())[:60].lower()
                elif kt == "content" and not href:
                    href = kid.get("src") or ""
            if href and label:
                titles.setdefault(key_for(href), label)
    return titles


def file_sha(path: Path | str, cap: int = 64 * 1024 * 1024) -> str:
    """A cheap identity for a file: sha1 of its first `cap` bytes and its
    size. Two shelves holding the same manual under different names agree."""
    h = hashlib.sha1()
    try:
        size = Path(path).stat().st_size
        with open(path, "rb") as fh:
            left = cap
            while left > 0:
                chunk = fh.read(min(1024 * 1024, left))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
        h.update(str(size).encode())
    except OSError:
        return ""
    return h.hexdigest()


def _read_zip_documents(path: Path, skip_shas: set[str]) -> dict[str, Any]:
    """A zip of documents rather than a website bundle: read each member that
    is itself something we open, one after another. A member already on the
    shelf under its own name is skipped, so a bundle that only repackages
    loose files does not get indexed twice."""
    pages: list[dict[str, Any]] = []
    read_ok = 0
    dupes = 0
    with zipfile.ZipFile(path) as zf:
        members = [n for n in sorted(zf.namelist())
                   if not n.endswith("/") and not n.startswith("__MACOSX/")
                   and doc_kind(n) and Path(n).suffix.lower() != ".zip"]
        if not members:
            raise ExtractError("nothing readable inside the archive")
        with tempfile.TemporaryDirectory(prefix="library-zip-") as tmp:
            for member in members:
                blob = _zip_read(zf, member)
                if not blob:
                    continue
                h = hashlib.sha1(blob)
                h.update(str(len(blob)).encode())   # same recipe as file_sha
                if h.hexdigest() in skip_shas:
                    dupes += 1
                    continue
                dest = Path(tmp) / safe_asset_name(member)
                try:
                    dest.write_bytes(blob)
                    got = read_document(dest, None)
                except (OSError, ExtractError):
                    continue
                read_ok += 1
                label = nice_title(member)
                for pg in got.get("pages") or []:
                    pg = dict(pg)
                    pg["n"] = len(pages) + 1
                    pg["heading"] = (pg.get("heading")
                                     or label[:60].lower())
                    pg["source_url"] = member
                    pages.append(pg)
    if not pages:
        if dupes:
            raise ExtractError(
                f"every document inside ({dupes}) is already on the shelf")
        raise ExtractError("nothing readable inside the archive")
    return {"pages": pages, "figures": 0,
            "title": "", "members": read_ok, "duplicates": dupes}


def _read_zip_chapters(path: Path, out_dir: Path | None, kind: str,
                       skip_shas: set[str] | None = None) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:  # noqa: BLE001
        raise ExtractError(f"the archive would not open: {exc}") from exc
    with zf:
        title = ""
        if kind == "epub":
            chapters, titles, title = _epub_spine(zf)
        else:
            chapters = sorted(
                _norm_href(n) for n in zf.namelist()
                if n.lower().endswith((".html", ".htm", ".xhtml"))
                and not n.startswith("__MACOSX/"))
            titles = {}
        if not chapters:
            if kind == "zip":
                # Not a website bundle — a bag of documents. (The OP-XY
                # guidebook zip on the shelf is exactly this: two PDFs.)
                return _read_zip_documents(path, set(skip_shas or ()))
            raise ExtractError("no readable chapters inside")

        inside = {_norm_href(n): n for n in zf.namelist()}
        assets: dict[str, str] = {}
        figures = 0
        spent = 0
        pages: list[dict[str, Any]] = []

        for i, chapter in enumerate(chapters[:MAX_PAGES], start=1):
            raw = _zip_read(zf, inside.get(chapter, chapter))
            if not raw:
                continue
            body = raw.decode("utf-8", "replace")
            scan = _Text()
            try:
                scan.feed(body)
                scan.close()
            except Exception:  # noqa: BLE001 - malformed markup, keep going
                pass
            text = scan.text()
            heading = titles.get(chapter) or scan.heading or guess_heading(text)

            local: dict[str, str] = {}
            for src in scan.images:
                key = _resolve(chapter, src)
                real = inside.get(key)
                if not real:
                    continue
                if key not in assets:
                    if figures >= MAX_FIGURES or spent >= MAX_FIGURE_BYTES:
                        continue
                    blob = _zip_read(zf, real)
                    if not blob:
                        continue
                    name = safe_asset_name(key)
                    if out_dir is not None:
                        img_dir = out_dir / "pages" / "img"
                        img_dir.mkdir(parents=True, exist_ok=True)
                        (img_dir / name).write_bytes(blob)
                    assets[key] = name
                    figures += 1
                    spent += len(blob)
                local[_norm_href(src)] = f"img/{assets[key]}"
                local[key] = f"img/{assets[key]}"

            if out_dir is not None:
                clean = _Sanitize(local)
                try:
                    clean.feed(body)
                    clean.close()
                except Exception:  # noqa: BLE001
                    pass
                pages_dir = out_dir / "pages"
                pages_dir.mkdir(parents=True, exist_ok=True)
                (pages_dir / f"{i:04d}.html").write_text(
                    clean.html(), encoding="utf-8")

            if len(text) < MIN_PAGE_CHARS and not local:
                continue
            pages.append(page_row(i, heading, text, chapter))

    return {"pages": pages, "figures": figures, "title": title}


# --------------------------------------------------------------------------
# docx / plain text


def read_docx(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as zf:
            raw = _zip_read(zf, "word/document.xml").decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise ExtractError(f"the docx would not open: {exc}") from exc
    if not raw:
        raise ExtractError("no document.xml inside the docx")
    body = re.sub(r"</w:p>", "\n\n", raw)
    body = re.sub(r"<w:tab[^>]*/>", "\t", body)
    body = re.sub(r"<w:br[^>]*/>", "\n", body)
    return _paged_text(squash(re.sub(r"<[^>]+>", "", body)))


def read_text(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExtractError(f"the file would not read: {exc}") from exc
    return _paged_text(squash(raw))


def read_html(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExtractError(f"the file would not read: {exc}") from exc
    scan = _Text()
    try:
        scan.feed(raw)
        scan.close()
    except Exception:  # noqa: BLE001
        pass
    out = _paged_text(scan.text())
    if scan.heading and out["pages"]:
        out["pages"][0]["heading"] = scan.heading
    return out


def _paged_text(text: str) -> dict[str, Any]:
    """A flat document cut into citable pages at paragraph boundaries. A
    markdown heading starts a new page, so a citation lands somewhere real."""
    pages: list[dict[str, Any]] = []
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        body = "\n\n".join(buf).strip()
        buf, size = [], 0
        if len(body) >= MIN_PAGE_CHARS:
            pages.append(page_row(len(pages) + 1, guess_heading(body), body))

    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if buf and (size + len(para) > TEXT_PAGE_CHARS or para.startswith("#")):
            flush()
        buf.append(para)
        size += len(para) + 2
        if len(pages) >= MAX_PAGES:
            break
    flush()
    return {"pages": pages, "figures": 0}


# --------------------------------------------------------------------------
# the one door


def doc_kind(path: Path | str) -> str:
    """What this file is, or "" when it is not a document we open."""
    name = Path(path).name
    if name.lower() in SKIP_NAMES or name.startswith("."):
        return ""
    return KINDS.get(Path(path).suffix.lower(), "")


def nice_title(path: Path | str) -> str:
    stem = Path(path).stem
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)          # "... (1)"
    stem = re.sub(r"[_]+", " ", stem)
    return " ".join(stem.split())[:120]


def read_document(path: Path | str, out_dir: Path | str | None = None,
                  skip_shas: set[str] | None = None) -> dict[str, Any]:
    """Read one document into pages. Raises ExtractError with a line fit for
    the console.

    `out_dir` is where chapter html and figures are written for the reader
    pane; pass None to extract text only. `skip_shas` are documents already
    on the shelf — a zip that only repackages them is refused rather than
    indexed a second time.
    """
    path = Path(path)
    kind = doc_kind(path)
    if not kind:
        raise ExtractError(f"not a document this shelf reads: {path.name}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ExtractError(f"the file is not there: {exc}") from exc
    if size > MAX_BYTES:
        raise ExtractError(f"too big to read ({size // (1024 * 1024)} MB)")
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    if kind == "pdf":
        got = read_pdf(path)
    elif kind in {"epub", "zip"}:
        got = _read_zip_chapters(path, out_dir, kind, skip_shas)
    elif kind == "docx":
        got = read_docx(path)
    elif kind == "html":
        got = read_html(path)
    else:
        got = read_text(path)

    pages = got.get("pages") or []
    if not pages:
        raise ExtractError("nothing readable came out of it")
    chars = sum(len(p["text"]) for p in pages)
    return {
        "kind": kind,
        "title": (got.get("title") or "").strip() or nice_title(path),
        "pages": pages,
        "figures": int(got.get("figures") or 0),
        "chars": chars,
        # A picture-only manual reads as pages with no words in them. Say so
        # rather than letting the shelf quietly hold an empty book.
        "thin": chars < max(400, 60 * len(pages)),
        "reader": ("pdftotext" if (kind == "pdf" and shutil.which("pdftotext"))
                   else ("pypdf" if kind == "pdf" else kind)),
    }


def scan_folder(folder: Path | str, depth: int = 1,
                cap: int = 4000) -> list[Path]:
    """Documents under a folder, one level of subfolders deep by default.

    Modelled on app.py's sfx_folders: every lookup is wrapped, because a dead
    SMB path must never take the show down with it.
    """
    root = Path(folder)
    found: list[Path] = []
    try:
        if not root.is_dir():
            return []
        base = root.resolve()
    except OSError:
        return []

    def walk(here: Path, left: int) -> None:
        if len(found) >= cap:
            return
        try:
            entries = sorted(here.iterdir())
        except OSError:
            return
        for entry in entries:
            if len(found) >= cap:
                return
            try:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    if left > 0 and entry.resolve().is_relative_to(base):
                        walk(entry, left - 1)
                    continue
                if not entry.is_file() or not doc_kind(entry):
                    continue
                if not entry.resolve().is_relative_to(base):
                    continue        # a symlink pointing off the shelf
                found.append(entry)
            except OSError:
                continue

    walk(root, max(0, int(depth)))
    return found


__all__ = ["ExtractError", "KINDS", "doc_kind", "file_sha", "nice_title",
           "read_document", "scan_folder", "squash", "dedupe_lines",
           "paragraphs", "guess_heading", "safe_asset_name"]
