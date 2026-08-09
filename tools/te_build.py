#!/usr/bin/env python3
"""Build the offline gear knowledge base used by spark-agent's tech feed.

Host-side tool (needs poppler-utils: pdftotext / pdftoppm / pdfinfo).

  python3 te_build.py --out ./build                     # every teenage
                                                        # engineering guide
  python3 te_build.py --out ./build --only op-1,op-xy   # a subset
  python3 te_build.py --out ./build --extras            # hichord, ko ii, ...

Per device it writes:
  <out>/te/<slug>/doc.json      pages: heading + text + image + block boxes
  <out>/te/<slug>/pages/*.png   one image per manual page (or .svg artwork)
  <out>/te/<slug>/guide.pdf     the source manual, when there is one
  <out>/te/index.json           device list with spoken-name aliases
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from urllib.parse import urljoin
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://teenage.engineering"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) spark-agent-gear-cache/1.0"}
DPI = 100
MAX_FIGURES = 400
# Guide pages embed empty panel outlines, checkmarks and arrows alongside the
# real drawings; anything this small is chrome, not documentation.
MIN_ARTWORK_BYTES = 3000
# Byte size alone is not enough: an empty page outline can be 34 KB of one
# big path. Real illustrations carry dozens of drawing elements.
MIN_ARTWORK_ELEMENTS = 25

# What people actually say out loud, mapped to the guide slug.
ALIASES = {
    "op-1": ["op1", "op 1", "op-1 field", "op1 field", "op one"],
    "op-1-original": ["original op-1", "op-1 original", "op1 original"],
    "op-xy": ["opxy", "op xy", "op exwhy"],
    "op-z": ["opz", "op z"],
    "tp-7": ["tp7", "tp 7", "field recorder"],
    "tx-6": ["tx6", "tx 6", "field mixer"],
    "ep-133": ["ep133", "ko ii", "ko 2", "k.o. ii", "k.o.2", "koii", "ko2"],
    "ep-1320": ["ep1320", "medieval", "ko ii medieval", "ko2 medieval"],
    "ep-133-supreme": ["ko ii supreme", "ep-133 supreme"],
    "ep-136": ["ep136"],
    "ob-4": ["ob4", "ob 4", "magic radio"],
    "cm-15": ["cm15", "cm 15"],
    "od-11": ["od11", "od 11", "cloud speaker"],
    "or-1": ["or1", "or 1"],
    "m-1": ["m1", "m 1"],
    "po-12": ["po12", "rhythm"],
    "po-14": ["po14", "sub"],
    "po-16": ["po16", "factory"],
    "po-20": ["po20", "arcade"],
    "po-24": ["po24", "office"],
    "po-28": ["po28", "robot"],
    "po-32": ["po32", "tonic"],
    "po-33": ["po33", "pocket operator ko"],
    "po-35": ["po35", "speak"],
    "po-80": ["po80", "record"],
    "po-128": ["po128", "mega man"],
    "po-133": ["po133", "street fighter"],
    "po-137": ["po137", "rick and morty"],
    "oplab": ["op lab", "oplab module"],
    "fieldkit": ["field kit"],
    "choir": ["te choir"],
    "hichord": ["hi chord", "high chord", "hichord"],
    "lemondrop": ["lemon drop", "nanobox lemondrop", "nanobox lemon drop"],
    "minichord": ["mini chord", "minichord"],
    "nsx-39": ["nsx39", "pocket miku", "gakken miku", "miku stylophone"],
    "mpc-live-3": [
        "mpc live 3", "mpc live iii", "mpc live three", "mpclive3",
        "live 3", "live iii", "akai mpc live",
    ],
    "mpc-sample": [
        "mpc sample", "mpcsample", "akai mpc sample", "mpc sampler",
    ],
    "mpc-os": [
        "mpc os", "mpc standalone os", "mpc firmware", "mpc software",
    ],
    "sc500": [
        "sc 500", "sc-500", "sc500", "portablism", "portablism gear",
        "portablismgear", "scratch instrument", "digital scratch instrument",
        "portable scratch", "scratch box",
    ],
}

# Devices with no manual on teenage.engineering (or not TE at all).
EXTRAS = [
    {
        "slug": "hichord",
        "title": "HiChord chord synthesizer manual",
        "source": "https://manual.hichord.shop/",
        "pdf": "https://images.equipboard.com/uploads/item/manual/159320/"
        "pocket-audio-hichord-manual.pdf",
        "web": ["https://manual.hichord.shop/"],
    },
    {
        "slug": "lemondrop",
        "title": "1010music nanobox lemondrop user guide",
        "source": "https://1010music.com/lemondropdocs",
        "pdf": "https://1010music.com/wp-content/uploads/2022/02/"
        "nanobox-lemondrop-User-Guide.pdf",
    },
    {
        "slug": "minichord",
        "title": "minichord synthesizer user manual",
        "source": "https://minichord.com/user_manual/",
        "web": ["https://minichord.com/user_manual/"],
    },
    {
        "slug": "nsx-39",
        "title": "Gakken NSX-39 Pocket Miku user's manual (English)",
        "source": "https://sandsoftwaresound.net/pocket-miku-software-resources/",
        "pdf": "http://sandsoftwaresound.net/wp-content/uploads/2017/07/"
        "pocket_miku.pdf",
        "web": ["https://kamodamusic.com/synth/PocketMiku.htm"],
    },
    {
        "slug": "mpc-live-3",
        "title": "Akai MPC Live III user guide",
        "source": "https://www.akaipro.com/mpc-live-iii/",
        "pdf": "https://cdn.inmusicbrands.com/akai/"
        "MPC%20Live%20III%20-%20User%20Guide%20-%203.6.pdf",
    },
    {
        "slug": "mpc-sample",
        "title": "Akai MPC Sample user guide",
        "source": "https://www.akaipro.com/mpc-sample/",
        "pdf": "https://cdn.inmusicbrands.com/akai/sample/"
        "MPC%20Sample%20-%20User%20Guide%20-%20v1.3.0%20(RevA).pdf",
    },
    {
        # The OS guide is where the actual workflow lives — chopping,
        # sequencing, sampling — and it applies to every standalone MPC, so
        # both boxes above answer better with it in the library.
        "slug": "mpc-os",
        "title": "Akai MPC Standalone OS user guide",
        "source": "https://www.akaipro.com/mpc-manuals/",
        "pdf": "https://cdn.inmusicbrands.com/akai/MPC3-NI/"
        "MPC%20Standalone%20OS%20-%20User%20Guide%20-%20v3.4.pdf",
    },
    {
        # No PDF exists for the SC500 — Rasteri documents it on the product
        # pages and in a video guide, so this one is web-sourced.
        "slug": "sc500",
        "title": "PortablismGear SC500 Digital Scratch Instrument",
        "source": "https://www.portablismgear.com/en-us/collections/sc500",
        "web": [
            "https://www.portablismgear.com/en-us/products/"
            "sc500-digital-scratch-instrument-transparent",
            "https://www.portablismgear.com/en-us/collections/sc500",
            "https://www.portablismgear.com/en-us/collections/"
            "digital-scratch-instrument",
        ],
    },
]


def get(url: str, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


class PageScan(HTMLParser):
    """Split a guide page into sections at its anchor ids, keeping the text and
    the artwork that belong to each one."""

    SLUG = re.compile(r"^[a-z0-9][a-z0-9\-\.]{1,60}$")
    BAD = re.compile(
        r"^(c\d+$|clip|cls-|bag|chevron|icon|mask|logo|search$|menu$|cart$"
        r"|checkout$|contact|deals$|designs$|store$|newsletter$|instagram$"
        r"|now$|latest$|guides$|support$|product$|app$|intro$|header$|cover$)"
    )
    DROP = {"script", "style", "svg", "noscript", "head", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict[str, Any]] = [{"id": "top", "text": [], "images": []}]
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.DROP:
            self.skip += 1
            return
        if self.skip:
            return
        a = {k: (v or "") for k, v in attrs}
        sid, cls = a.get("id", ""), a.get("class", "")
        if tag == "img":
            src = a.get("src", "")
            if src.startswith("http") and "/_img/" in src:
                self.sections[-1]["images"].append(src)
            return
        if sid and self.SLUG.match(sid) and not self.BAD.match(sid) and "boximg" not in cls:
            self.sections[-1]["id"] = self.sections[-1]["id"] or sid
            self.sections.append({"id": sid, "text": [], "images": []})

    def handle_endtag(self, tag: str) -> None:
        if tag in self.DROP and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.sections[-1]["text"].append(data.strip())


def clean_text(parts: list[str]) -> str:
    text = html.unescape(re.sub(r"\s+", " ", " ".join(parts))).strip()
    return re.sub(r"\b(back to|return to) index\b", "", text).strip()


def flat_text(raw: str) -> tuple[str, list[dict[str, str]]]:
    scan = PageScan()
    scan.feed(raw)
    text = clean_text([t for s in scan.sections for t in s["text"]])
    images = [
        {"src": src, "label": s["id"]}
        for s in scan.sections
        for src in s["images"]
    ]
    return text, images


def guide_sections(raw: str) -> list[dict[str, Any]]:
    """Sections with their artwork. A bare numbered heading ('11.5 filter')
    titles the block that follows it."""
    scan = PageScan()
    scan.feed(raw)
    out: list[dict[str, Any]] = []
    pending = ""
    for sec in scan.sections:
        text = clean_text(sec["text"])
        title = sec["id"].replace("-", " ").strip()
        if re.match(r"^\d+([\.\-]\d+)*[\s\-]", title):
            title = re.sub(r"^[\d\.\-]+\s*", "", title).strip() or title
        if not sec["images"] and len(text) <= 70:
            # A heading on its own: hand it to the next block with content.
            if text:
                pending = re.sub(r"^[\d\.\s]+", "", text).strip() or pending
            continue
        if not text and not sec["images"]:
            continue
        heading = pending or title
        pending = ""
        out.append({"heading": heading[:60].lower(), "text": text, "images": sec["images"]})
    return out


def sub_pages(slug: str, raw: str = "") -> list[str]:
    """Guides split across sub-routes list them in the page and in the router
    payload behind it."""
    bodies = [raw]
    try:
        bodies.append(get(f"{BASE}/guides/{slug}.data", tries=2).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        pass
    pattern = rf"guides/{re.escape(slug)}/([a-z0-9][a-z0-9\-]*)"
    found: set[str] = set()
    for body in bodies:
        found.update(re.findall(pattern, body))
    skip = {"jp", "fr", "de", "se", "credits", "software-licenses"}
    return sorted(f for f in found if f not in skip)


def dedupe(text: str) -> str:
    """TE ships OCR'd PDFs whose lines overlap: every line repeats a word from
    the one before it, and words stutter inside a line. Collapse both."""
    out: list[str] = []
    carry = ""
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        words: list[str] = []
        for word in line.split(" "):
            if words and word and word.lower() == words[-1].lower():
                continue
            words.append(word)
        if words and carry and len(words[0]) > 1 and words[0].lower() == carry:
            words = words[1:]
        if not words:
            carry = ""
            out.append("")
            continue
        line = " ".join(words)
        if out and line == out[-1]:
            continue
        carry = words[-1].lower()
        out.append(line)
    return "\n".join(out).strip()


def pdf_meta(path: Path) -> tuple[int, str, float, float]:
    try:
        out = subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True, timeout=90
        ).stdout
    except Exception:  # noqa: BLE001
        return 0, "", 0.0, 0.0
    pages = int(m.group(1)) if (m := re.search(r"^Pages:\s+(\d+)", out, re.M)) else 0
    title = m.group(1).strip() if (m := re.search(r"^Title:\s+(.+)$", out, re.M)) else ""
    size = re.search(r"^Page size:\s+([\d.]+) x ([\d.]+)", out, re.M)
    w, h = (float(size.group(1)), float(size.group(2))) if size else (0.0, 0.0)
    return pages, title, w, h


def page_blocks(pdf: Path) -> list[list[dict]]:
    """Per-page text blocks with bounding boxes, for cropping snips."""
    try:
        xml = subprocess.run(
            ["pdftotext", "-bbox-layout", str(pdf), "-"],
            capture_output=True,
            text=True,
            timeout=900,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    pages: list[list[dict]] = []
    for pchunk in re.split(r"<page\b", xml)[1:]:
        blocks: list[dict] = []
        for bchunk in re.split(r"<block\b", pchunk)[1:]:
            box = re.match(
                r'[^>]*xMin="([\d.]+)"\s+yMin="([\d.]+)"\s+xMax="([\d.]+)"\s+yMax="([\d.]+)"',
                bchunk,
            )
            if not box:
                continue
            words = re.findall(r"<word[^>]*>(.*?)</word>", bchunk, re.S)
            text = dedupe(html.unescape(" ".join(words)))
            if not text:
                continue
            blocks.append(
                {
                    "x": round(float(box.group(1)), 1),
                    "y": round(float(box.group(2)), 1),
                    "w": round(float(box.group(3)) - float(box.group(1)), 1),
                    "h": round(float(box.group(4)) - float(box.group(2)), 1),
                    "text": text[:600],
                }
            )
        pages.append(blocks)
    return pages


def render(pdf: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), str(pdf), str(dest / "p")],
        check=True,
        timeout=3600,
    )
    return sorted(p.name for p in dest.glob("p-*.png"))


def heading_for(text: str, blocks: list[dict]) -> str:
    """A page's title: its shortest tall-standing first block, else first line."""
    for block in blocks[:3]:
        line = block["text"].split("\n")[0].strip()
        if 2 <= len(line) <= 48 and not re.fullmatch(r"[\d.\s]+", line):
            return line.lower()
    for line in text.splitlines():
        line = line.strip()
        if 2 <= len(line) <= 48 and not re.fullmatch(r"[\d.\s]+", line):
            return line.lower()
    return ""


def build_from_pdf(doc: dict, pdf: Path, gdir: Path) -> None:
    pages, _title, pw, ph = pdf_meta(pdf)
    doc["page_size"] = {"w": pw, "h": ph}
    doc["dpi"] = DPI
    doc["text_source"] = "pdf"
    raw = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, timeout=900
    ).stdout
    texts = [dedupe(chunk) for chunk in raw.split("\f")]
    blocks = page_blocks(pdf)
    images = render(pdf, gdir / "pages")
    shutil.copy(pdf, gdir / "guide.pdf")
    for i in range(max(len(texts), len(images))):
        text = texts[i] if i < len(texts) else ""
        bl = blocks[i] if i < len(blocks) else []
        img = images[i] if i < len(images) else ""
        if not text and not img:
            continue
        doc["pages"].append(
            {
                "n": i + 1,
                "heading": heading_for(text, bl),
                "text": text[:8000],
                "image": img,
                "blocks": bl[:40],
            }
        )
    print(f"    pdf {pages}p · {len(doc['pages'])} pages, {len(images)} images")


def download_images(
    images: list[dict], dest: Path, marker: str = "/_img/"
) -> list[dict]:
    """marker keeps TE runs to the guide CDN; pass "" for other manuals."""
    dest.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    picked: list[dict] = []
    for img in images:
        if img["src"] in seen or (marker and marker not in img["src"]):
            continue
        seen.add(img["src"])
        picked.append(img)
    picked = picked[:MAX_FIGURES]

    def one(item: tuple[int, dict]) -> dict | None:
        idx, img = item
        ext = ".svg" if img["src"].endswith(".svg") else (Path(img["src"]).suffix or ".png")
        label = re.sub(r"[^a-z0-9-]+", "-", (img["label"] or "fig").lower()).strip("-")
        name = f"{idx:03d}-{label[:40] or 'fig'}{ext}"
        try:
            (dest / name).write_bytes(get(img["src"], tries=2))
        except Exception:  # noqa: BLE001
            return None
        return {"file": name, "label": img["label"], "src": img["src"]}

    saved: list[dict] = []
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        for rec in pool.map(one, enumerate(picked, 1)):
            if rec:
                saved.append(rec)
    return sorted(saved, key=lambda r: r["file"])


def build_from_artwork(doc: dict, slug: str, raw: str, gdir: Path) -> None:
    """Web guides: the page shell plus every sub-route, section by section."""
    doc["text_source"] = "web-guide"
    subs = sub_pages(slug, raw)
    sources = [(f"{BASE}/guides/{slug}", raw)]
    for sub in subs:
        url = f"{BASE}/guides/{slug}/{sub}"
        try:
            sources.append((url, get(url, tries=2).decode("utf-8", "replace")))
        except Exception as exc:  # noqa: BLE001
            print(f"    sub failed {sub}: {exc}", file=sys.stderr)

    want: list[dict[str, Any]] = []
    for url, body in sources:
        for sec in guide_sections(body):
            sec["source_url"] = url
            want.append(sec)

    # One flat pass keeps the artwork numbered in reading order.
    flat = [
        {"src": src, "label": sec["heading"] or "fig"}
        for sec in want
        for src in sec["images"]
    ]
    saved = download_images(flat, gdir / "pages")
    by_src = {rec["src"]: rec["file"] for rec in saved}

    pages: list[dict[str, Any]] = []
    def weight(name: str) -> int:
        """Drawing complexity, used both to filter chrome and to rank."""
        path = gdir / "pages" / name
        try:
            if path.suffix.lower() != ".svg":
                return path.stat().st_size
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        elements = (body.count("<path") + body.count("<rect")
                    + body.count("<circle") + body.count("<text"))
        return elements if elements >= MIN_ARTWORK_ELEMENTS else 0

    for sec in want:
        files = [by_src[s] for s in sec["images"] if s in by_src]
        files = sorted((f for f in files if weight(f) > 0),
                       key=weight, reverse=True)
        if not sec["text"] and not files:
            continue
        pages.append(
            {
                "n": len(pages) + 1,
                "heading": sec["heading"],
                "text": sec["text"][:6000],
                "image": files[0] if files else "",
                "images": files,
                "blocks": [],
                "source_url": sec["source_url"],
            }
        )
    doc["pages"] = pages
    chars = sum(len(p["text"]) for p in pages)
    print(
        f"    web-guide · {len(subs)} subs, {len(pages)} sections, "
        f"{len(saved)} images, {chars} chars"
    )


def add_web_pages(doc: dict, urls: list[str], gdir: Path | None = None) -> None:
    """Long-form web manuals: chunk the text so retrieval can hit a topic, and
    keep the drawings so the pages aren't walls of prose."""
    for url in urls:
        try:
            raw = get(url).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"    web failed {url}: {exc}", file=sys.stderr)
            continue
        text, _ = flat_text(raw)

        saved: list[dict] = []
        if gdir is not None:
            found = [
                {"src": urljoin(url, m), "label": "figure"}
                for m in re.findall(r'<img[^>]+src="([^"]+)"', raw)
                if not m.startswith("data:")
            ]
            if found:
                saved = download_images(found, gdir / "pages", marker="")

        chunks = [
            text[i : i + 2800]
            for i in range(0, len(text), 2500)
            if len(text[i : i + 2800]) >= 200
        ]
        for idx, chunk in enumerate(chunks):
            # Spread the drawings across the manual in reading order.
            mine = [
                rec["file"]
                for j, rec in enumerate(saved)
                if chunks and j * len(chunks) // max(1, len(saved)) == idx
            ]
            doc["pages"].append(
                {
                    "n": len(doc["pages"]) + 1,
                    "heading": " ".join(chunk.split()[:6]).lower(),
                    "text": chunk,
                    "image": mine[0] if mine else "",
                    "images": mine,
                    "blocks": [],
                    "source_url": url,
                }
            )
        print(f"    web · {url.split('/')[2]} · {len(chunks)} chunks, "
              f"{len(saved)} images")


SEARX = os.getenv("SEARXNG_URL", "http://lilspark.local:8081").rstrip("/")
HARVEST_QUERIES = (
    "{name} user guide manual",
    "{name} tips and tricks hidden features",
    "{name} workflow tutorial how to",
    "{name} troubleshooting reset firmware",
)
HARVEST_PER_QUERY = 5
HARVEST_DELAY = 45  # seconds between searches; SearXNG suspends engines fast
HARVEST_CHUNKS = 18
HARVEST_SKIP = re.compile(
    r"(youtube\.com|youtu\.be|reddit\.com/r/[^/]+/?$|facebook|instagram|"
    r"tiktok|pinterest|ebay|amazon\.|/cart|/checkout)",
    re.I,
)


def search(query: str) -> list[str]:
    # Slow on purpose: a burst of queries gets every engine suspended for
    # hours, and this only ever runs as an offline top-up.
    time.sleep(HARVEST_DELAY)
    url = f"{SEARX}/search?format=json&q=" + urllib.parse.quote(query)
    try:
        data = json.loads(get(url, tries=2).decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        print(f"    search failed: {exc}", file=sys.stderr)
        return []
    out = []
    for res in data.get("results", []):
        link = res.get("url") or ""
        if link and not HARVEST_SKIP.search(link):
            out.append(link)
    return out[:HARVEST_PER_QUERY]


def fetch_readable(url: str, work: Path) -> str:
    """Page text — including third-party PDF manuals, which are often the only
    place a device's prose exists."""
    body = get(url, tries=1)
    if url.lower().endswith(".pdf") or body[:4] == b"%PDF":
        tmp = work / "harvest.pdf"
        tmp.write_bytes(body)
        if pdf_meta(tmp)[0] < 1:
            return ""
        raw = subprocess.run(
            ["pdftotext", str(tmp), "-"], capture_output=True, text=True, timeout=300
        ).stdout
        return dedupe(raw)
    return flat_text(body.decode("utf-8", "replace"))[0]


def harvest_web(doc: dict, work: Path) -> int:
    """Search the open web for the device and cache what it finds, so devices
    whose manual is unreadable artwork still have prose to answer from."""
    slug = doc["slug"]
    if "teenage.engineering" in doc.get("source", ""):
        name = "teenage engineering " + slug.replace("-en", "").upper()
    else:
        name = doc["title"]
    seen: set[str] = set()
    added = 0
    doc["pages"] = [p for p in doc["pages"] if p.get("kind") != "web"]
    for template in HARVEST_QUERIES:
        if added >= HARVEST_CHUNKS:
            break
        for url in search(template.format(name=name)):
            if added >= HARVEST_CHUNKS or url in seen:
                continue
            seen.add(url)
            try:
                text = fetch_readable(url, work)
            except Exception:  # noqa: BLE001 - a blocked host is not fatal
                continue
            if len(text) < 400:
                continue
            host = url.split("/")[2] if "//" in url else url
            for i in range(0, min(len(text), 12000), 2400):
                chunk = text[i : i + 2600].strip()
                if len(chunk) < 300 or added >= HARVEST_CHUNKS:
                    break
                doc["pages"].append(
                    {
                        "n": len(doc["pages"]) + 1,
                        "heading": f"{host} · web notes",
                        "text": chunk,
                        "image": "",
                        "blocks": [],
                        "kind": "web",
                        "source_url": url,
                    }
                )
                added += 1
    print(f"    web harvest · {added} chunks from {len(seen)} pages")
    return added


def harvest_product(doc: dict) -> int:
    """Teenage engineering's own product pages, which carry the plain-prose
    description and specs the artwork guides never spell out."""
    slug = doc["slug"]
    stems = [slug, slug.replace("-en", ""), slug.split("-modules-")[0]]
    if slug == "op-1":
        stems.insert(0, "op-1-field")
    tried: set[str] = set()
    added = 0
    doc["pages"] = [p for p in doc["pages"] if p.get("kind") != "product"]
    for stem in stems:
        for kind in ("products", "store"):
            url = f"{BASE}/{kind}/{stem}"
            if url in tried or added:
                continue
            tried.add(url)
            try:
                text = flat_text(get(url, tries=1).decode("utf-8", "replace"))[0]
            except Exception:  # noqa: BLE001
                continue
            text = re.sub(r"^(checkout menu|current image|go to image \d+|"
                          r"previous image|next image)\s*", "", text).strip()
            if len(text) < 600:
                continue
            for i in range(0, min(len(text), 14000), 2400):
                chunk = text[i : i + 2600].strip()
                if len(chunk) < 300:
                    break
                doc["pages"].append(
                    {
                        "n": len(doc["pages"]) + 1,
                        "heading": f"{stem} · product notes",
                        "text": chunk,
                        "image": "",
                        "blocks": [],
                        "kind": "product",
                        "source_url": url,
                    }
                )
                added += 1
    print(f"    product notes · {added} chunks")
    return added


def new_doc(slug: str, title: str, source: str) -> dict:
    return {
        "slug": slug,
        "title": title,
        "source": source,
        "aliases": ALIASES.get(slug, []),
        "fetched": time.strftime("%Y-%m-%d"),
        "text_source": "",
        "pages": [],
    }


def summarize(doc: dict) -> dict:
    return {
        "slug": doc["slug"],
        "title": doc["title"],
        "source": doc["source"],
        "aliases": doc["aliases"],
        "text_source": doc["text_source"],
        "pages": len(doc["pages"]),
        "images": sum(1 for p in doc["pages"] if p["image"]),
        "fetched": doc["fetched"],
    }


def guide_slugs() -> list[str]:
    raw = get(f"{BASE}/guides").decode("utf-8", "replace")
    found = sorted(set(re.findall(r'href="/guides/([^"?#]+)"', raw)))
    return [s for s in found if s.split("/")[-1] not in {"jp", "fr", "de", "se"}]


def build_guide(slug: str, out: Path, work: Path) -> dict | None:
    key = slug.replace("/", "-")
    print(f"  · {slug}")
    raw = get(f"{BASE}/guides/{slug}").decode("utf-8", "replace")
    title_m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(title_m.group(1)).split(" - ")[0].strip() if title_m else key

    gdir = out / key
    gdir.mkdir(parents=True, exist_ok=True)
    doc = new_doc(key, title, f"{BASE}/guides/{slug}")

    best: tuple[Path | None, str, int] = (None, "", 0)
    for i, url in enumerate(
        sorted(set(re.findall(r'https://assets\.teenage\.engineering/[^"\' ]+\.pdf', raw)))
    ):
        cand = work / f"{key}-{i}.pdf"
        try:
            cand.write_bytes(get(url))
        except Exception as exc:  # noqa: BLE001
            print(f"    pdf failed: {exc}", file=sys.stderr)
            continue
        n = pdf_meta(cand)[0]
        if n > best[2]:
            best = (cand, url, n)

    if best[0] and best[2] >= 4:
        doc["pdf_url"] = best[1]
        build_from_pdf(doc, best[0], gdir)
    else:
        build_from_artwork(doc, slug, raw, gdir)

    (gdir / "doc.json").write_text(json.dumps(doc, indent=1) + "\n")
    return summarize(doc)


def build_extra(spec: dict, out: Path, work: Path) -> dict | None:
    slug = spec["slug"]
    print(f"  · {slug} (extra)")
    gdir = out / slug
    gdir.mkdir(parents=True, exist_ok=True)
    doc = new_doc(slug, spec["title"], spec["source"])

    if spec.get("pdf"):
        pdf = work / f"{slug}.pdf"
        try:
            pdf.write_bytes(get(spec["pdf"]))
            if pdf_meta(pdf)[0] >= 2:
                doc["pdf_url"] = spec["pdf"]
                build_from_pdf(doc, pdf, gdir)
        except Exception as exc:  # noqa: BLE001
            print(f"    pdf failed: {exc}", file=sys.stderr)

    if spec.get("web"):
        add_web_pages(doc, spec["web"], gdir)
        doc["text_source"] = doc["text_source"] or "web"

    if not doc["pages"]:
        return None
    (gdir / "doc.json").write_text(json.dumps(doc, indent=1) + "\n")
    return summarize(doc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--extras", action="store_true", help="only the extra devices")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--products",
        action="store_true",
        help="only refresh teenage engineering product-page notes",
    )
    ap.add_argument(
        "--web",
        action="store_true",
        help="only harvest web notes into the devices already built",
    )
    args = ap.parse_args()

    for tool in ("pdftotext", "pdftoppm", "pdfinfo"):
        if not shutil.which(tool):
            print(f"missing {tool} (install poppler-utils)", file=sys.stderr)
            return 1

    out = Path(args.out) / "te"
    work = Path(args.out) / "_work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    built: list[dict] = []

    if args.products:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        for path in sorted(out.glob("*/doc.json")):
            doc = json.loads(path.read_text())
            if wanted and doc["slug"] not in wanted:
                continue
            print(f"  · {doc['slug']}")
            try:
                if harvest_product(doc):
                    path.write_text(json.dumps(doc, indent=1) + "\n")
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED {doc['slug']}: {exc}", file=sys.stderr)
            built.append(summarize(doc))

    if args.web:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        for path in sorted(out.glob("*/doc.json")):
            doc = json.loads(path.read_text())
            if wanted and doc["slug"] not in wanted:
                continue
            print(f"  · {doc['slug']}")
            try:
                if harvest_web(doc, work):
                    doc["text_source"] = doc["text_source"].split("+")[0] + "+web"
                    path.write_text(json.dumps(doc, indent=1) + "\n")
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED {doc['slug']}: {exc}", file=sys.stderr)
            built.append(summarize(doc))
        args.only = args.only or "none"

    if not args.extras and not args.web and not args.products:
        slugs = [s.strip() for s in args.only.split(",") if s.strip()] or guide_slugs()
        print(f"{len(slugs)} guides")
        for slug in slugs:
            key = slug.replace("/", "-")
            if args.skip_existing and (out / key / "doc.json").exists():
                built.append(summarize(json.loads((out / key / "doc.json").read_text())))
                continue
            try:
                rec = build_guide(slug, out, work)
            except Exception as exc:  # noqa: BLE001 - one bad guide can't stop the run
                print(f"    FAILED {slug}: {exc}", file=sys.stderr)
                continue
            if rec:
                built.append(rec)

    if not args.web and not args.products and (args.extras or not args.only):
        for spec in EXTRAS:
            if args.skip_existing and (out / spec["slug"] / "doc.json").exists():
                continue
            try:
                rec = build_extra(spec, out, work)
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED {spec['slug']}: {exc}", file=sys.stderr)
                continue
            if rec:
                built.append(rec)

    # Merge with anything already on disk so partial runs keep the index whole.
    index: dict[str, dict] = {}
    prev = out / "index.json"
    if prev.exists():
        for rec in json.loads(prev.read_text()).get("devices", []):
            index[rec["slug"]] = rec
    for rec in built:
        index[rec["slug"]] = rec
    prev.write_text(
        json.dumps(
            {
                "built": time.strftime("%Y-%m-%d %H:%M"),
                "devices": sorted(index.values(), key=lambda r: r["slug"]),
            },
            indent=1,
        )
        + "\n"
    )
    shutil.rmtree(work, ignore_errors=True)
    print(f"done · {len(index)} devices -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
