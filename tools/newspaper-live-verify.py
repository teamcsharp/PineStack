"""Use normal paper APIs; --print starts one extra, otherwise inspect only.

Run inside spark-agent so credentials remain in its environment. There is no
poll loop and no automatic retry of the publication request.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from newspaper_city import sentences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--print', action='store_true', dest='publish')
    parser.add_argument('--edition')
    parser.add_argument('--output', default='/app/data/paper_verification/1061')
    args = parser.parse_args()
    key = os.environ.get('SPARK_AGENT_API_KEY', '')
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    with httpx.Client(base_url='http://127.0.0.1:8096', headers=headers, timeout=45) as client:
        shelf_response = client.get('/api/paper')
        shelf_response.raise_for_status()
        shelf = shelf_response.json()
        report = {k: shelf.get(k) for k in ('latest', 'running', 'started', 'verdict')}
        report['steps'] = (shelf.get('steps') or [])[-4:]
        if args.publish:
            response = client.post('/api/paper/print', json={'kind': 'extra',
                'reason': 'Request 1061: verify distinct source-grounded city image stories'})
            response.raise_for_status()
            report['publication_request'] = response.json()
            print(json.dumps(report, ensure_ascii=False))
            return
        if not args.edition:
            print(json.dumps(report, ensure_ascii=False))
            return
        response = client.get('/api/paper/' + args.edition)
        response.raise_for_status()
        edition = response.json()
        rows = []
        for article in edition.get('articles') or []:
            meta = article.get('meta') or {}
            if meta.get('copy_origin') and meta.get('gallery_subjects'):
                rows.append({'head': meta.get('headline'), 'body': article.get('body'),
                    'source_image': meta['gallery_subjects'][0].get('image'),
                    'source_seed': meta.get('source_seed'), 'copy_origin': meta['copy_origin']})
            rows.extend(row for row in meta.get('classifieds') or [] if row.get('source_image'))
        seen, repeated, provenance = set(), [], []
        stamp = re.compile(r'^\s*[\[(]?\d{1,3}:\d{2}(?::\d{2})?[\])]?\s*')
        for row in rows:
            repeated.extend(sorted(seen & sentences(row['body'])))
            seen.update(sentences(row['body']))
            seed = row.get('source_seed') or {}
            name, text = str(seed.get('file') or ''), str(seed.get('text') or '')
            path = Path('/app/data/speakbox') / Path(name).name
            raw = path.read_text(errors='replace') if path.is_file() else ''
            source = ' '.join(stamp.sub('', ' '.join(para.split())) for para in raw.split('\n\n'))
            provenance.append({'file': name, 'mind': seed.get('mind'),
                'exact_passage': bool(text and text in source),
                'hash_matches': bool(text and hashlib.sha256(text.encode()).hexdigest()[:20] == seed.get('hash'))})
        report.update(edition=args.edition, image_stories=len(rows),
            unique_images=len({r['source_image'] for r in rows}),
            source_files=len({p['file'] for p in provenance if p['file']}),
            repeated_sentences=repeated, unique_sentences=len(seen),
            presenter_patter=any(re.search(r'Listen up|holding up|Available to talk|Owners and neighbours', str(r['body']), re.I) for r in rows),
            provenance=provenance,
            origins={origin: sum(r.get('copy_origin') == origin for r in rows)
                     for origin in {r.get('copy_origin') for r in rows}},
            stories=rows)
        html = client.get('/api/paper/' + args.edition + '/html')
        html.raise_for_status()
        output = Path(args.output) / args.edition
        output.mkdir(parents=True, exist_ok=True)
        (output / 'edition.html').write_text(html.text.replace('src="/api/', 'src="http://10.89.1.246:8096/api/'), encoding='utf-8')
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
