"""Soft-failing news article dossier helpers."""
from __future__ import annotations

import asyncio
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse


def public_url(url: str) -> str:
    raw = str(url or "").strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/",
                       "", parsed.query, ""))


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def fetch_service(
    url: str,
    *,
    title: str = "",
    search: Callable[..., Any] | None = None,
    extract: Callable[..., Any] | None = None,
    budget_seconds: float = 12.0,
) -> dict[str, Any]:
    clean = public_url(url)
    if not clean:
        return {"title": title, "url": "", "source_url": "", "availability": "invalid url",
                "method": "none", "excerpt": "", "article_text": "", "evidence_links": []}
    try:
        text = ""
        if extract:
            got = await asyncio.wait_for(_maybe_await(extract(clean)),
                                         timeout=max(1.0, float(budget_seconds or 1.0)))
            if isinstance(got, dict):
                text = str(got.get("text") or got.get("article_text") or got.get("excerpt") or "")
            else:
                text = str(got or "")
        return {"title": title, "url": clean, "source_url": clean,
                "availability": "article extracted" if text else "headline only",
                "method": "extract" if text else "headline",
                "excerpt": " ".join(text.split())[:1800],
                "article_text": text[:12000],
                "evidence_links": [clean]}
    except Exception as exc:  # noqa: BLE001
        return {"title": title, "url": clean, "source_url": clean,
                "availability": type(exc).__name__, "method": "failed",
                "excerpt": "", "article_text": "", "evidence_links": [clean]}
