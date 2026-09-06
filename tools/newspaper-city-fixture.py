"""Render real image descriptions with exhausted-writer fallbacks, off air.

Writes only the chosen output folder; never publishes or changes a live edition.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from newspaper_city import sentences


async def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    live_regression = '--live-regression' in sys.argv
    original = ROOT / "data/paper/editions" / ("2026-09-06-12x1324" if live_regression else "2026-09-06-11")
    source = next((original / "articles").glob("*classifieds.md"))
    meta, _, _ = app._fm_load(source.read_text(encoding="utf-8"))
    pictures = []
    for row in meta["classifieds"]:
        if not row.get("source_image"):
            continue
        description = re.split(r"Available to talk|Owners and neighbours|Enquiries about visits|Offered locally", row["body"])[0].strip()
        pictures.append({"name": row["source_image"], "url": row.get("image") or "/api/generations/image/" + row["source_image"],
                         "kind": "described", "desc": description})
    reviewed = json.loads((ROOT / "data/response_bank_reviewed_seeds_20260906.json").read_text(encoding="utf-8"))
    seeds = []
    for row in reviewed:
        seed = row["source"]
        if seed["file"] not in {s["file"] for s in seeds}:
            seeds.append(dict(seed))
    if live_regression:
        shelf = json.loads((ROOT / 'data/prep_shelf.json').read_text())
        descriptions, pending = {}, [shelf.get('gallery') or []]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                if value.get('name') and value.get('desc'):
                    descriptions[str(value['name'])] = str(value['desc'])
                pending.extend(v for v in value.values() if isinstance(v, (list, dict)))
        lead_path = next((original / 'articles').glob('*local-life.md'))
        lead, _, _ = app._fm_load(lead_path.read_text(encoding='utf-8'))
        rows = [{'source_image': lead['gallery_subjects'][0]['image'], 'source_seed': lead['source_seed']},
                *(r for r in meta['classifieds'] if r.get('source_image'))]
        pictures, seeds = [], []
        for row in rows:
            name = row['source_image']
            assert name in descriptions, name
            pictures.append({'name': name, 'url': '/api/generations/image/' + name,
                             'kind': 'described', 'desc': descriptions[name]})
            seeds.append(row['source_seed'])
    material = {"pictures": pictures, "since": 1, "hour_key": "1061-fixture",
                "station": "Pine Box FM", "host": "Tony", "cohost": "Skip"}
    with (mock.patch.dict(app._PAPER_PRESS, {"gallery_subjects": [], "deadline": 1}),
          mock.patch.object(app, "paper_seeds", side_effect=[seeds[:len(pictures)]] + [[]] * 20),
          mock.patch.object(app, "paper_write", return_value={}),
          mock.patch.object(app, "paper_plate_rank", return_value=(0, 0, 0)),
          mock.patch.object(app, "paper_seeds_used")):
        city = await app._desk_city(material)
        classified = await app._desk_classifieds(material)
    articles = [r for r in (city, classified) if r]
    for i, article in enumerate(articles):
        article["file"] = f"{i:02}-{article['slug']}.md"
    edition = json.loads((original / "edition.json").read_text(encoding="utf-8"))
    edition.update(id="1061-fixture", headline="New situations around Pine Box FM",
                   articles=articles, fillers=[], fillers_by_page={}, pages=3)
    html = app.paper_render_html(edition)
    html = html.replace('src="/api/', 'src="http://10.89.1.246:8096/api/')
    (output / "edition.html").write_text(html, encoding="utf-8")
    stories = material["_city_stories"]
    seen = set()
    for story in stories:
        assert not seen & sentences(story["body"]), story["headline"]
        assert not re.search(r"Listen up|holding up|Available to talk", story["body"], re.I)
        assert story["source"].get("text")
        seen.update(sentences(story["body"]))
    image_notices = [r for r in classified["meta"]["classifieds"] if r.get("source_image")]
    assert len(image_notices) + 1 == len(pictures)
    report = {"ok": True, "stories": len(stories),
              "source_files": sorted({s["source"]["file"] for s in stories}),
              "unique_sentences": len(seen), "writer_available": False,
              "station_writes": 0, "edition": edition}
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "edition"}))


if __name__ == "__main__":
    asyncio.run(main())
