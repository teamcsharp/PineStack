"""Read-only routing, speaker and SFX evidence; run inside the station container."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request


def get(path):
    req = urllib.request.Request('http://127.0.0.1:8096' + path,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY']})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.load(response)
    except Exception as exc:
        return {'error': type(exc).__name__ + ': ' + str(exc)[:200]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/nabu-sfx-before.json')
    args = parser.parse_args()
    paths = ['/api/dj', '/api/dj/flow', '/api/pinebox/speaker',
             '/api/routing/moves', '/api/sfx/history', '/api/settings',
             '/api/pinebox/status']
    with ThreadPoolExecutor(max_workers=5) as pool:
        raw = dict(zip(paths, pool.map(get, paths)))
    station = raw['/api/dj']
    settings = raw['/api/settings'].get('dj') or {}
    report = {'at': time.time(), 'reads_only': True,
        'station': {k: station.get(k) for k in ('on', 'paused', 'voice_to',
            'voice_device', 'music_to', 'reply_to', 'box_talk', 'speaking',
            'speaking_remaining', 'activity_log', 'last_delivery')},
        'flow': raw['/api/dj/flow'], 'speaker': raw['/api/pinebox/speaker'],
        'routing_moves': raw['/api/routing/moves'],
        'sfx': raw['/api/sfx/history'], 'status': raw['/api/pinebox/status'],
        'settings': {k: v for k, v in settings.items() if k.startswith(
            ('sfx', 'drop', 'talk', 'crystal', 'box_', 'tint'))}}
    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('flow', 'sfx')},
                     ensure_ascii=False))
    print(json.dumps({'flow_keys': list(report['flow']),
                      'health': {k: v for k, v in (report['flow'].get('health') or {}).items()
                                 if k != 'last_delivery'},
                      'sfx_summary': {k: v for k, v in report['sfx'].items()
                                      if not isinstance(v, list)}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
