"""Read-only station evidence collector. Credentials stay in local config."""
import argparse
import datetime
import json
import pathlib
import time
import urllib.error
import urllib.request


def configuration():
    p = pathlib.Path.home() / 'AppData/Roaming/pinebox-desktop/pinebox-desktop.json'
    cfg = json.loads(p.read_text(encoding='utf-8'))
    return cfg['baseUrl'].rstrip('/'), cfg.get('apiKey', '')


def scrub(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if k.lower() in {'apikey', 'api_key', 'key', 'token', 'authorization', 'server_key'} else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and value.startswith(('http:', 'https:', '/music/', '/sfx/', '/tape/')) and '?' in value:
        return value.split('?')[0] + '?[redacted]'
    return value


def request(route):
    base, key = configuration()
    req = urllib.request.Request(base + route, headers={'Authorization': 'Bearer ' + key} if key else {})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return {'elapsed_ms': round((time.monotonic() - start) * 1000), 'data': scrub(json.load(response))}
    except Exception as exc:
        return {'error': str(exc), 'elapsed_ms': round((time.monotonic() - start) * 1000)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('routes', nargs='*')
    parser.add_argument('--output', default='artifacts/broadcast-investigation/latest.json')
    args = parser.parse_args()
    routes = args.routes or ['/api/radio/listeners', '/api/settings', '/api/broadcast/health', '/api/dj/state', '/api/dj/flow?lean=1&limit=300', '/api/dj', '/api/broadcast/watch']
    result = {'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'routes': {}}
    for route in routes:
        result['routes'][route] = request(route)
        entry = result['routes'][route]
        data = entry.get('data', {})
        print(json.dumps({'route': route, 'elapsed_ms': entry['elapsed_ms'], 'error': entry.get('error'), 'keys': list(data) if isinstance(data, dict) else type(data).__name__}, ensure_ascii=False), flush=True)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Evidence saved: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
