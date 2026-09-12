"""One GET-only station/process snapshot, without app imports or provider calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def get(path):
    started = time.time()
    request = urllib.request.Request('http://127.0.0.1:8096' + path, method='GET',
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY']})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {'http_status': response.status, 'at': time.time(),
                    'seconds': round(time.time() - started, 3), 'data': json.load(response)}
    except Exception as error:
        return {'http_status': getattr(error, 'code', None), 'at': time.time(),
                'seconds': round(time.time() - started, 3), 'error': type(error).__name__}


def pick(row, keys):
    return {key: row.get(key) for key in keys if key in row}


def clean(value):
    """Retain resource/counter structure without scripts or private prompt bodies."""
    if isinstance(value, list):
        return [clean(item) for item in value[:100]]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()
                if key.lower() not in {'prompt', 'messages', 'script', 'text', 'candidate',
                                       'source', 'authorization', 'api_key', 'token', 'password'}}
    return value


def processes():
    boot = next(float(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
    hz = os.sysconf('SC_CLK_TCK')
    rows = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            command = (directory / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if not any(word in command for word in ('uvicorn', 'app:app', 'app.py', 'ollama', 'system2-test.py')):
                continue
            # Never serialize cmdline: provider credentials may be arguments.
            stat = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            status = dict(line.split(':', 1) for line in (directory / 'status').read_text().splitlines() if ':' in line)
            rows.append({'pid': int(directory.name), 'comm': (directory / 'comm').read_text().strip(),
                'state': status.get('State', '').strip(), 'threads': int(status.get('Threads', '0')),
                'rss_kib': int(status.get('VmRSS', '0 kB').split()[0]),
                'started_at': boot + int(stat[19]) / hz,
                'role': 'isolated_tests' if 'system2-test.py' in command else 'backend' if any(w in command for w in ('uvicorn', 'app:app', 'app.py')) else 'model_service'})
        except (OSError, ValueError, IndexError):
            continue
    return sorted(rows, key=lambda row: row['pid'])


def main():
    paths = ['/health', '/api/dj', '/api/settings', '/api/coordinator/resources',
             '/api/orchestrator/logic', '/api/tint', '/api/system2/status', '/api/pinebox/status']
    started = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = dict(zip(paths, pool.map(get, paths)))
    data = lambda path: responses[path].get('data') or {}
    station, settings = data('/api/dj'), data('/api/settings')
    dj = settings.get('dj') or {}
    logic = data('/api/orchestrator/logic')
    box = data('/api/pinebox/status')
    report = {'started_at': started, 'finished_at': time.time(), 'read_only': True,
        'requests': {path: {key: value for key, value in response.items() if key != 'data'} for path, response in responses.items()},
        'post_requests': 0, 'model_requests': 0, 'provider_requests': 0,
        'station': pick(station, ('on', 'paused', 'playing', 'music_to', 'voice_to', 'reply_to', 'voice_device',
                                   'box_talk', 'nabu_music_level', 'nabu_voice_level', 'nabu_reply_level')),
        'speech': {key: pick(station.get(key) or {}, ('id', 'key', 'who', 'kind', 'at', 'length', 'until', 'state'))
                   for key in ('speaking_now', 'stream_now')},
        'settings': {'model': settings.get('model'), **pick(dj, ('model_fast', 'crystal_tint_model', 'model_ctx',
            'talk_radio', 'talk_radio_mode', 'prepare_hours', 'dialogue_reserve_target', 'clone_engine',
            'crystal_tint_hold', 'crystal_coverage', 'sfx_every_units', 'sfxguy_every_units', 'sfxguy_rate',
            'sfx_max_seconds', 'nabu_music_level', 'nabu_voice_level', 'nabu_reply_level', 'box_volume_control'))},
        'capacity': clean(pick(logic, ('at', 'on', 'paused', 'hours_ready', 'target_hours', 'roads', 'order', 'workshop', 'pipeline'))),
        'resources': clean(data('/api/coordinator/resources').get('snapshot') or {}),
        'tint': clean(pick(data('/api/tint'), ('hold', 'grade', 'force', 'coverage', 'coverage_target', 'evaluator'))),
        'system2': clean(data('/api/system2/status')),
        'box': clean(pick(box, ('healthy', 'spoken', 'sounds_right', 'diag_error', 'routing', 'delivery', 'cause'))),
        'processes': processes(),
        'limitations': ['Point-in-time configuration, queue, resource, and transport evidence; not an acoustic observation.',
                       'Stored readiness can differ from immediately selectable stock because of slot, cast, cooldown, and repeat rules.',
                       'Unavailable predeployment System2 endpoint is reported explicitly, not replaced with local source output.',
                       'No environment or full process command line is serialized.']}
    path = ROOT / 'docs/system2-predeploy-live.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(path), 'station': report['station'],
        'http_status': {p: r.get('http_status') for p, r in responses.items()},
        'pipeline_total': (logic.get('pipeline') or {}).get('total'),
        'processes': report['processes']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
