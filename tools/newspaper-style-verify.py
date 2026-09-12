"""Render an existing edition off air, or fetch the bundled OFL display face."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', action='store_true')
    parser.add_argument('--live', action='store_true', help='Fetch the normal authenticated preview API; no publication')
    parser.add_argument('--wait-gap', action='store_true', help='Observe up to 45 seconds for an actual speech gap; never stop audio')
    parser.add_argument('--edition', default='2026-09-07-03')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/paper_verification/1067')
    args = parser.parse_args()
    if args.wait_gap:
        import httpx
        key = os.environ.get('SPARK_AGENT_API_KEY', '')
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        quiet, deadline = 0, time.monotonic() + 45
        with httpx.Client(base_url='http://127.0.0.1:8096', headers=headers, timeout=8) as client:
            while time.monotonic() < deadline:
                response = client.get('/api/dj')
                response.raise_for_status()
                state = response.json()
                speaking = state.get('speaking_now') or {}
                stream = state.get('stream_now') or {}
                remaining = max(0, float(stream.get('at') or 0) + float(stream.get('length') or 0) - time.time())
                quiet = quiet + 1 if not speaking.get('text') and remaining <= 0 else 0
                if quiet >= 2:
                    print(json.dumps({'speech_gap': True, 'observations': quiet, 'stream_remaining': remaining}), flush=True)
                    return
                time.sleep(1)
        print(json.dumps({'speech_gap': False, 'stream_remaining': remaining}), flush=True)
        raise SystemExit(2)
    if args.font:
        folder = ROOT / 'frontend/fonts'
        folder.mkdir(parents=True, exist_ok=True)
        base = 'https://raw.githubusercontent.com/google/fonts/main/ofl/unifrakturmaguntia/'
        for source, target in [('UnifrakturMaguntia-Book.ttf', 'UnifrakturMaguntia-Book.ttf'),
                               ('OFL.txt', 'UnifrakturMaguntia-OFL.txt')]:
            (folder / target).write_bytes(urllib.request.urlopen(base + source, timeout=30).read())
        print(json.dumps({'font': 'UnifrakturMaguntia', 'license': 'SIL OFL 1.1'}))
        return
    if args.live:
        import httpx
        key = os.environ.get('SPARK_AGENT_API_KEY', '')
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        with httpx.Client(base_url='http://127.0.0.1:8096', headers=headers, timeout=60) as client:
            response = client.get('/api/paper/' + args.edition)
            response.raise_for_status()
            before = response.json()
            args.output.mkdir(parents=True, exist_ok=True)
            styles = {}
            for style in ('broadsheet', 'tabloid'):
                response = client.get('/api/paper/' + args.edition + '/html', params={'style': style})
                response.raise_for_status()
                html = response.text
                assert '<!--PAPER_RENDER_VERSION=7 ' in html
                assert ('class="reference-photo"' in html) == (style == 'broadsheet')
                (args.output / (style + '.html')).write_text(
                    html.replace('src="/api/', 'src="http://10.89.1.246:8096/api/'), encoding='utf-8')
                styles[style] = {'bytes': len(response.content), 'sha256': hashlib.sha256(response.content).hexdigest()}
                response = client.get('/api/paper/' + args.edition + '/pdf', params={'style': style})
                response.raise_for_status()
                assert response.content.startswith(b'%PDF-')
                (args.output / (style + '.pdf')).write_bytes(response.content)
                styles[style]['pdf_bytes'] = len(response.content)
                styles[style]['pdf_sha256'] = hashlib.sha256(response.content).hexdigest()
            response = client.get('/api/paper/' + args.edition)
            response.raise_for_status()
            assert before['articles'] == response.json()['articles'], 'Preview altered article data'
        report = {'edition': args.edition, 'source': 'authenticated live preview API', 'styles': styles,
                  'articles': len(before['articles']), 'article_data_unchanged': True, 'publication_requests': 0}
        (args.output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
        return
    sys.path.insert(0, str(ROOT))
    import app
    folder = ROOT / 'data/paper/editions' / args.edition
    edition = json.loads((folder / 'edition.json').read_text(encoding='utf-8'))
    edition['articles'] = []
    for path in sorted((folder / 'articles').glob('*.md')):
        meta, body, error = app._fm_load(path.read_text(encoding='utf-8'))
        assert not error, (path.name, error)
        edition['articles'].append({'file': path.name, 'meta': meta, 'body': body})
    args.output.mkdir(parents=True, exist_ok=True)
    head = app.paper_masthead()
    station = edition['station']
    head['masthead'] = (station if station.lower().startswith('the ') else 'The ' + station) + ' Gazette'
    with mock.patch.object(app, 'paper_masthead', return_value=head):
        for style in app.PAPER_STYLES:
            html = app.paper_render_html(edition, style)
            html = html.replace('src="/api/', 'src="http://10.89.1.246:8096/api/')
            (args.output / (style + '.html')).write_text(html, encoding='utf-8')
    report = {'edition': args.edition, 'render_version': app.PAPER_RENDER_VERSION,
              'styles': list(app.PAPER_STYLES), 'articles': len(edition['articles']),
              'station_writes': 0, 'source': 'existing edition, unchanged article copy'}
    (args.output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
