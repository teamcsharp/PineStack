from __future__ import annotations

import re
from typing import Any, Callable

TOKEN = re.compile(r"(?<!\{)\{(gazette(?:topic)?\d?)\}(?!\})")


def articles(edition: dict[str, Any]) -> list[dict[str, Any]]:
    """Only real, readable articles from the selected published edition."""
    rows = []
    for article in edition.get("articles") or []:
        if not isinstance(article, dict) or article.get("error"):
            continue
        meta = article.get("meta") or {}
        text = str(article.get("body") or "").strip()
        if not text:
            continue
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = " ".join(text.replace("**", "").split())
        rows.append({"edition": str(edition.get("id") or ""),
                     "fictional": bool(meta.get("editorial")),
                     "topic": dict((meta.get("editorial") or {}).get("topic") or {}) if isinstance(meta.get("editorial"), dict) else {},
                     "section": str(meta.get("section") or article.get("slug") or "general").strip(),
                     "headline": str(meta.get("headline") or article.get("headline_hint") or article.get("file") or "Untitled article"),
                     "file": str(article.get("file") or ""), "text": text[:2400]})
    return rows


def draw(rows: list[dict[str, Any]], weighted: Callable, note: Callable | None = None,
         token: str = "gazette") -> dict[str, Any]:
    """Section first, then an article inside it; both use System 3's dice."""
    if not rows:
        return {}
    sections = list(dict.fromkeys(r["section"] for r in rows))

    def pick(key, labels, label, stage):
        index = weighted(key, labels, [1.0] * len(labels), label)
        index = index if isinstance(index, int) and 0 <= index < len(labels) else 0
        if note:
            note("slot_" + token + ("_section" if stage == "section" else ""), key, labels, labels[index])
        return index

    section = sections[pick("gazette.section", sections, "which Gazette section {gazette} uses", "section")]
    candidates = [r for r in rows if r["section"] == section]
    selected = candidates[pick("gazette.article", [r["headline"] for r in candidates],
                               "which article from the rolled Gazette section {gazette} uses", "article")]
    return dict(selected, prompt=phrase(selected))


def phrase(row: dict[str, Any]) -> str:
    return (('fictional Pinebox city satire from ' if row.get('fictional') else '')
            + 'the Pine Box Gazette, edition %s, section "%s", article "%s": %s'
            % (row["edition"], row["section"], row["headline"].replace('"', "'"), row["text"]))
