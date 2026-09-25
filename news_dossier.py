"""Bounded, evidence-first article retrieval for the station news desk.

`fetch_service` accepts the station's `newsread_extract` and `search_searxng`
as callbacks. The small built-in extractor is for callers outside app.py; it
never claims a complete article when it can only identify metadata.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import os
import re
import socket
import sys
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx


MAX_RESPONSE_BYTES = 1_500_000
MAX_ARTICLE_CHARS = 24_000
MAX_EXCERPT_CHARS = 1_400
MAX_REDIRECTS = 3
DEFAULT_BUDGET_SECONDS = 18.0

Fetch = Callable[[str], Awaitable[Any]]
Search = Callable[[str], Awaitable[list[dict[str, Any]]]]
Extract = Callable[[str, str], dict[str, Any]]
Resolve = Callable[[str], Awaitable[list[str]]]


def public_url(value: str) -> str:
    """Reject local, credentialed, non-web and non-standard-port targets."""
    url = str(value or "").strip()
    if len(url) > 2048 or any(ord(ch) < 32 for ch in url):
        return ""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
        if (parts.scheme.lower() not in ("http", "https") or not host
                or parts.username or parts.password or "\\" in url
                or port not in (None, 80, 443)):
            return ""
        if host in ("localhost", "localhost.localdomain") or host.endswith(
                (".local", ".internal", ".localhost", ".test", ".invalid")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
                return ""
    except ValueError:
        return ""
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/",
                       parts.query, ""))


async def _resolve_public(host: str) -> list[str]:
    rows = await asyncio.to_thread(socket.getaddrinfo, host, None)
    return [row[4][0] for row in rows]


async def _safe_destination(url: str, resolve: Resolve) -> bool:
    allowed = public_url(url)
    if not allowed:
        return False
    host = urlsplit(allowed).hostname or ""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        addresses = await asyncio.wait_for(resolve(host), 2.0)
        return bool(addresses) and all(ipaddress.ip_address(ip).is_global
                                       for ip in addresses)
    except (OSError, ValueError, asyncio.TimeoutError):
        return False


class _Document(HTMLParser):
    """Small metadata/alternate-link fallback; app.py can inject its reader."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.alternates: list[str] = []
        self.in_title = False
        self.article_depth = 0
        self.in_paragraph = False
        self.paragraph = ""
        self.paragraphs: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in ("script", "style", "nav", "aside", "footer"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key == "og:title" and attributes.get("content"):
                self.title = attributes["content"] or ""
            if key in ("description", "og:description") and attributes.get("content"):
                self.description = attributes["content"] or ""
        if tag == "link":
            kind = (attributes.get("type") or "").lower()
            rel = (attributes.get("rel") or "").lower()
            if "alternate" in rel and any(x in kind for x in ("rss", "atom", "json")):
                if attributes.get("href"):
                    self.alternates.append(attributes["href"] or "")
        if tag == "article":
            self.article_depth += 1
        if tag == "p" and self.article_depth and not self.skip:
            self.in_paragraph = True
            self.paragraph = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.in_paragraph:
            text = _clean(self.paragraph)
            if text:
                self.paragraphs.append(text)
            self.in_paragraph = False
        if tag == "article":
            self.article_depth = max(0, self.article_depth - 1)
        if tag == "title":
            self.in_title = False
        if tag in ("script", "style", "nav", "aside", "footer"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data: str) -> None:
        if self.in_title and not self.skip and not self.title:
            self.title = data
        if self.in_paragraph and not self.skip:
            self.paragraph += data


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _document(html: str) -> _Document:
    parser = _Document()
    parser.feed(html[:MAX_RESPONSE_BYTES])
    return parser


def _default_extract(html: str, url: str) -> dict[str, Any]:
    station = sys.modules.get("app")
    reader = getattr(station, "newsread_extract", None) if station else None
    if callable(reader):
        return reader(html, url)
    page = _document(html)
    return {"title": page.title, "paragraphs": page.paragraphs,
            "description": page.description}


def _blocked_page(html: str, extracted: dict[str, Any]) -> bool:
    notice = str(extracted.get("notice") or "").lower()
    head = html[:30000].lower()
    return ("subscriber content" in notice
            or bool(re.search(r'"isaccessibleforfree"\s*:\s*(?:false|"false")', head))
            or any(marker in head for marker in (
                "subscribe to continue reading", "sign in to continue reading",
                "this article is for subscribers")))


def _article(extracted: dict[str, Any]) -> str:
    paragraphs = extracted.get("paragraphs") or []
    if not isinstance(paragraphs, list):
        paragraphs = []
    return "\n\n".join(_clean(paragraph) for paragraph in paragraphs
                       if _clean(paragraph))[:MAX_ARTICLE_CHARS]


def _feed_entry(body: str, content_type: str, wanted_url: str,
                wanted_title: str) -> tuple[str, str, str]:
    """Return only a feed item traceable to the requested story."""
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        return "", "", ""
    candidates: list[tuple[str, str, str]] = []
    if "json" in content_type or body.lstrip().startswith("{"):
        try:
            data = json.loads(body)
            items = data.get("items") or data.get("articles") or []
            if isinstance(items, list):
                for item in items[:100]:
                    if isinstance(item, dict):
                        candidates.append((str(item.get("url") or item.get("external_url") or ""),
                                           _clean(item.get("title")),
                                           _clean(item.get("summary") or item.get("description") or "")))
        except (ValueError, TypeError):
            return "", "", ""
    else:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return "", "", ""
        for item in list(root.iter())[:500]:
            if item.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
                continue
            fields: dict[str, str] = {}
            for child in list(item):
                name = child.tag.rsplit("}", 1)[-1]
                if name == "link":
                    fields[name] = child.attrib.get("href") or child.text or ""
                elif name in ("title", "description", "summary"):
                    fields[name] = "".join(child.itertext())
            candidates.append((fields.get("link", ""), _clean(fields.get("title")),
                               _clean(fields.get("description") or fields.get("summary"))))
    target = public_url(wanted_url)
    title_words = set(re.findall(r"[a-z0-9]{4,}", wanted_title.lower()))
    for link, title, excerpt in candidates:
        candidate = public_url(link)
        same_url = bool(candidate and target and candidate.rstrip("/") == target.rstrip("/"))
        words = set(re.findall(r"[a-z0-9]{4,}", title.lower()))
        same_title = len(title_words & words) >= 3 and len(title_words & words) >= len(title_words) * .6
        if same_url or (same_title and candidate and urlsplit(candidate).hostname == urlsplit(target).hostname):
            return title, excerpt[:MAX_EXCERPT_CHARS], candidate
    return "", "", ""


def _as_response(reply: Any, requested: str) -> tuple[int, str, str, str, str]:
    if isinstance(reply, dict):
        status = int(reply.get("status_code", 200))
        url = str(reply.get("url") or requested)
        headers = reply.get("headers") or {}
        body = str(reply.get("text") or "")
    else:
        status = int(reply.status_code)
        url = str(reply.url)
        headers = reply.headers
        body = reply.text
    if len(body.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds the dossier size limit")
    return status, url, str(headers.get("content-type") or "").lower(), body, str(headers.get("location") or "")


async def _http_fetch(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    async with client.stream("GET", url) as reply:
        chunks: list[bytes] = []
        size = 0
        async for chunk in reply.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds the dossier size limit")
            chunks.append(chunk)
        encoding = reply.encoding or "utf-8"
        body = b"".join(chunks).decode(encoding, "replace")
        return {"status_code": reply.status_code, "url": str(reply.url),
                "headers": dict(reply.headers), "text": body}


async def fetch_service(
    url: str, *, title: str = "", fetch: Fetch | None = None,
    search: Search | None = None, extract: Extract | None = None,
    resolve: Resolve | None = None, searxng_url: str | None = None,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
) -> dict[str, Any]:
    """Get a public-source dossier without bypassing access controls.

    Callbacks: `fetch(url)` returns an httpx.Response or response-shaped dict;
    `search(query)` returns SearXNG-style result dicts; `extract(html, url)`
    accepts app.newsread_extract's contract. A failed rung falls through.
    `method` is publisher, publisher_feed, public_archive, search_index, or
    metadata. `availability` is full, excerpt, metadata, or unavailable.
    """
    original = public_url(url)
    result: dict[str, Any] = {
        "title": _clean(title)[:300], "url": original or str(url or "")[:2048],
        "source_url": "", "method": "metadata", "article_text": "",
        "excerpt": "", "evidence_links": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "availability": "unavailable", "confidence": "low", "attempts": [],
    }
    if not original:
        result["attempts"].append("invalid_public_url")
        return result
    result["evidence_links"] = [original]
    resolver = resolve or _resolve_public
    extractor = extract or _default_extract
    deadline = time.monotonic() + max(0.1, min(float(budget_seconds), 30.0))
    client = (httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0),
                                follow_redirects=False, trust_env=False)
              if fetch is None or search is None else None)

    async def request(target: str) -> tuple[int, str, str, str]:
        for _ in range(MAX_REDIRECTS + 1):
            left = deadline - time.monotonic()
            if left <= 0:
                raise asyncio.TimeoutError
            if not await asyncio.wait_for(_safe_destination(target, resolver),
                                          min(left, 2.1)):
                raise ValueError("not a public web destination")
            left = deadline - time.monotonic()
            if left <= 0:
                raise asyncio.TimeoutError
            reply = await asyncio.wait_for(
                fetch(target) if fetch else _http_fetch(client, target),
                min(left, 6.0))
            status, final_url, kind, body, location = _as_response(reply, target)
            if public_url(final_url) != public_url(target):
                raise ValueError("fetcher followed an unchecked redirect")
            if status in (301, 302, 303, 307, 308):
                target = urljoin(target, location)
                continue
            return status, target, kind, body
        raise ValueError("too many redirects")

    async def search_news(query: str) -> list[dict[str, Any]]:
        left = deadline - time.monotonic()
        if left <= 0:
            return []
        if search:
            return await asyncio.wait_for(search(query), min(left, 5.0))
        endpoint = (searxng_url or os.getenv("SEARXNG_URL") or
                    "http://127.0.0.1:8081").rstrip("/")
        # The station-owned SearXNG endpoint is configuration, never derived
        # from the article URL or a publisher response.
        async def query_index() -> list[dict[str, Any]]:
            for category in ("news", "general"):
                if deadline - time.monotonic() <= 0:
                    return []
                async with client.stream("GET", endpoint + "/search",
                                         params={"q": query, "format": "json",
                                                 "language": "en", "safesearch": 1,
                                                 "categories": category}) as reply:
                    reply.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in reply.aiter_bytes():
                        size += len(chunk)
                        if size > 256_000:
                            return []
                        chunks.append(chunk)
                data = json.loads(b"".join(chunks))
                hits = data.get("results", []) if isinstance(data, dict) else []
                if isinstance(hits, list) and hits:
                    return hits[:8]
            return []

        return await asyncio.wait_for(query_index(), min(left, 5.0))

    try:
        page = None
        denied = False
        try:
            status, final, kind, body = await request(original)
            denied = status in (401, 403, 451)
            if final not in result["evidence_links"]:
                result["evidence_links"].append(final)
            if status < 400 and (not kind or "html" in kind):
                page = _document(body)
                row = extractor(body, final)
                text = _article(row)
                result["title"] = _clean(row.get("title") or page.title or title)[:300]
                denied = _blocked_page(body, row)
                if not denied and len(text) >= 180:
                    result.update(source_url=final, method="publisher",
                                  article_text=text, excerpt=text[:MAX_EXCERPT_CHARS],
                                  availability="full", confidence="high")
                    if final not in result["evidence_links"]:
                        result["evidence_links"].append(final)
                    return result
                snippet = _clean(row.get("description") or page.description)
                if snippet:
                    result.update(excerpt=snippet[:MAX_EXCERPT_CHARS],
                                  availability="excerpt", source_url=final,
                                  method="publisher", confidence="medium")
                result["attempts"].append("publisher_unreadable")
            else:
                result["attempts"].append(f"publisher_http_{status}")
        except (httpx.HTTPError, OSError, ValueError, asyncio.TimeoutError) as exc:
            if isinstance(exc, ValueError) and "public web destination" in str(exc):
                denied = True
            result["attempts"].append(f"publisher_{type(exc).__name__}")

        # Only publisher-advertised feeds/APIs are followed. A feed item must
        # match this URL or a strong same-publisher title match.
        if page:
            for href in page.alternates[:3]:
                feed_url = public_url(urljoin(original, href))
                if not feed_url or urlsplit(feed_url).hostname != urlsplit(original).hostname:
                    continue
                try:
                    status, final, kind, body = await request(feed_url)
                    if status >= 400:
                        continue
                    feed_title, excerpt, link = _feed_entry(
                        body, kind, original, result["title"])
                    if feed_title:
                        result["title"] = feed_title[:300]
                    if excerpt:
                        result.update(source_url=final, method="publisher_feed",
                                      excerpt=excerpt, availability="excerpt",
                                      confidence="medium")
                        result["evidence_links"].extend([final, link])
                        return result
                except (httpx.HTTPError, OSError, ValueError, asyncio.TimeoutError):
                    pass
        result["attempts"].append("publisher_feed_unavailable")

        # A denied or subscriber-only publisher is not sent through an archive
        # to obtain its prose. Public archive lookup is for unavailable pages.
        if not denied and result["availability"] != "full":
            try:
                lookup = "https://archive.org/wayback/available?" + urlencode({"url": original})
                status, _, _, body = await request(lookup)
                if status < 400:
                    capture = json.loads(body).get("archived_snapshots", {}).get("closest", {})
                    archive_url = public_url(str(capture.get("url") or ""))
                    if (capture.get("available") and archive_url and
                            urlsplit(archive_url).hostname == "web.archive.org"):
                        status, final, kind, body = await request(archive_url)
                        if (status < 400 and urlsplit(final).hostname == "web.archive.org"
                                and (not kind or "html" in kind)):
                            row = extractor(body, final)
                            text = _article(row)
                            if not _blocked_page(body, row) and len(text) >= 180:
                                result.update(title=_clean(row.get("title") or result["title"])[:300],
                                              source_url=final, method="public_archive",
                                              article_text=text,
                                              excerpt=text[:MAX_EXCERPT_CHARS],
                                              availability="full", confidence="medium")
                                result["evidence_links"].append(final)
                                return result
            except (httpx.HTTPError, OSError, ValueError, KeyError,
                    TypeError, asyncio.TimeoutError):
                pass
        result["attempts"].append("public_archive_unavailable")

        try:
            query = (result["title"] or urlsplit(original).path.rsplit("/", 1)[-1])[:160]
            query += " site:" + (urlsplit(original).hostname or "")
            hits = await search_news(query)
            target_host = urlsplit(original).hostname
            title_words = set(re.findall(r"[a-z0-9]{4,}", result["title"].lower()))
            for hit in hits[:8]:
                link = public_url(str(hit.get("url") or ""))
                if not link or urlsplit(link).hostname != target_host:
                    continue
                hit_title = _clean(hit.get("title"))
                words = set(re.findall(r"[a-z0-9]{4,}", hit_title.lower()))
                same_url = link.rstrip("/") == original.rstrip("/")
                common = len(title_words & words)
                same_title = bool(title_words and words and common >= 3
                                  and common >= len(title_words) * .75
                                  and common >= len(words) * .75)
                if not (same_url or same_title):
                    continue
                snippet = _clean(hit.get("snippet") or hit.get("content"))[:MAX_EXCERPT_CHARS]
                result["title"] = result["title"] or hit_title[:300]
                if snippet:
                    result.update(source_url=link, method="search_index",
                                  excerpt=snippet, availability="excerpt",
                                  confidence="low")
                    result["evidence_links"].append(link)
                    return result
        except (httpx.HTTPError, OSError, ValueError, TypeError,
                asyncio.TimeoutError):
            pass
        result["attempts"].append("search_index_unavailable")
        if result["availability"] == "excerpt":
            result["confidence"] = "low"
        elif result["title"]:
            result["availability"] = "metadata"
        return result
    finally:
        if client is not None:
            await client.aclose()
