"""Bounded deployment observations; only explicit after-phase evidence refresh may POST.

Run inside the station container. Existing samples are retained under a file lock.
No model, vote, recovery, station control or playback endpoint is callable here.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request


LEARNING = '/api/orchestrator/prompt-learning'
READS = {'learning': LEARNING,
         'rejections': '/api/orchestrator/rejections?status=all&limit=1',
         'station': '/api/dj', 'logic': '/api/orchestrator/logic',
         'recording': '/api/recording-room'}


def request(path, body=None):
    if body is not None and (path != LEARNING + '/refresh' or set(body) != {'expected_revision'}):
        raise ValueError('Only an explicit current-revision evidence refresh is permitted.')
    if body is None and path not in READS.values():
        raise ValueError('Unlisted read endpoint.')
    req = urllib.request.Request('http://127.0.0.1:8096' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY'],
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return {'observation_error': type(error).__name__, 'http_status': error.code}
    except Exception as error:
        return {'observation_error': type(error).__name__}


def started():
    parts = Path('/proc/1/stat').read_text().rsplit(')', 1)[1].split()
    boot = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines()
                if line.startswith('btime '))
    return boot + int(parts[19]) / os.sysconf('SC_CLK_TCK')


def database(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN')
    return db


def sqlite_snapshot(data_dir, since, trace_cache):
    result = {'since_restart_epoch': since}
    try:
        with closing(database(data_dir / 'prompt_learning.sqlite3')) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompt_outcomes'").fetchone()
            if exists:
                rows = [{'seq': row['seq'], 'at': row['at'], **json.loads(row['body'])}
                        for row in db.execute('SELECT seq,at,body FROM prompt_outcomes WHERE at>=? ORDER BY seq', (since,))]
                result['learning_outcomes'] = {'available': True, 'since_restart': rows,
                    'retained_total': db.execute('SELECT COUNT(*) FROM prompt_outcomes').fetchone()[0],
                    'effective_results': dict(Counter(str(r.get('effective_ok')) for r in rows))}
            else:
                result['learning_outcomes'] = {'available': False, 'reason': 'not_present_on_this_server'}
    except Exception as error:
        result['learning_outcomes'] = {'observation_error': type(error).__name__}
    try:
        if trace_cache.get('start') != since:
            trace_cache.clear(); trace_cache.update(start=since, cursor=0, rows=[])
        with closing(database(data_dir / 'rejection_lab.sqlite3')) as db:
            # The journal serializes sorted keys; root kind is the final field.
            # Inspect bounded tails first so unrelated full prompts are not loaded.
            heads = list(db.execute('SELECT seq,trace_id,operation_id,at,substr(record,-160) AS tail '
                'FROM lab_traces WHERE seq>? AND at>=? ORDER BY seq', (trace_cache['cursor'], since)))
            ids = [r for r in heads if re.search(r'"kind":\s*"learning_(?:attempt|outcome)"\s*}\s*$', r['tail'])]
            for head in ids:
                record = json.loads(db.execute('SELECT record FROM lab_traces WHERE seq=?', (head['seq'],)).fetchone()[0])
                details = record.get('details') or {}
                trace_cache['rows'].append({'seq': head['seq'], 'trace_id': head['trace_id'], 'at': head['at'],
                    'kind': record['kind'], 'diagnostic_operation': bool(head['operation_id']),
                    'details': {k: details.get(k) for k in ('request_id', 'attempt_id', 'prior_attempt_id',
                        'model', 'kind', 'stage', 'prompt_version', 'learning_revision', 'strategy_ids',
                        'machine_ok', 'effective_ok', 'semantic_ok', 'rhyme_ok', 'faults')}})
            trace_cache['cursor'] = db.execute('SELECT COALESCE(MAX(seq),0) FROM lab_traces').fetchone()[0]
        result['lab_learning'] = {'latest_trace_cursor': trace_cache['cursor'],
            'counts_since_restart': dict(Counter(r['kind'] for r in trace_cache['rows'])),
            'rows_since_restart': list(trace_cache['rows'])}
    except Exception as error:
        result['lab_learning'] = {'observation_error': type(error).__name__}
    return result


def fields(value, names):
    return {key: value.get(key) for key in names if key in value}


def snapshot(phase, data_dir, trace_cache):
    began = time.time()
    with ThreadPoolExecutor(max_workers=len(READS)) as executor:
        futures = {key: executor.submit(request, path) for key, path in READS.items()}
        responses = {key: future.result() for key, future in futures.items()}
    start = started()
    station, logic, room = (responses[key] for key in ('station', 'logic', 'recording'))
    station_fields = ('on', 'paused', 'music_to', 'voice_to', 'reply_to', 'voice_device',
        'box_talk', 'music_level', 'voice_level', 'box_volume', 'stream_remaining',
        'nabu_music_level', 'nabu_voice_level', 'nabu_reply_level', 'remaining', 'elapsed',
        'speaking', 'observation_error', 'http_status')
    state = fields(station, station_fields)
    if isinstance(station.get('settings'), dict):
        state['settings'] = fields(station['settings'], station_fields)
    if isinstance(station.get('stream'), dict):
        state['stream'] = fields(station['stream'], ('remaining', 'remaining_seconds', 'length', 'at', 'speaking'))
    if isinstance(station.get('stream_now'), dict):
        state['stream_now'] = fields(station['stream_now'], ('remaining', 'remaining_seconds', 'length', 'at', 'speaking'))
    review = fields(responses['rejections'], ('latest_cursor', 'unreviewed', 'total', 'policy',
        'observation_error', 'http_status'))
    pipeline = fields(logic.get('pipeline') or {}, ('at', 'total', 'stages', 'roads', 'bottleneck',
        'next_step', 'recording_waiting', 'tint_waiting', 'repair_waits', 'repair_wait_count'))
    recording = fields(room, ('booths', 'writers', 'shelf', 'takes', 'shelf_served',
        'observation_error', 'http_status'))
    recording['preparing'] = fields(room.get('preparing') or {}, ('kind', 'stage', 'at', 'made', 'lines', 'ago'))
    recording['recent_receipts'] = [fields(row, ('at', 'who', 'engine', 'chars', 'seconds', 'ms', 'cost', 'how'))
                                   for row in room.get('recent') or []]
    return {'phase': phase, 'at': began, 'utc': datetime.fromtimestamp(began, timezone.utc).isoformat(),
        'completed_at': time.time(), 'container_start_epoch': start, 'learning': responses['learning'],
        'rejections': review, 'station': state, 'pipeline': pipeline,
        'logic': fields(logic, ('on', 'paused', 'hours_ready', 'target_hours', 'observation_error', 'http_status')),
        'recording': recording, 'sqlite': sqlite_snapshot(data_dir, start, trace_cache),
        'source_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                          for name in ('app.py', 'prompt_learning.py', 'crystal_prompts.py', 'rejection_workbench.py')}}


def append(path, sample):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {'version': 1, 'samples': [],
            'method': 'Authenticated GETs plus transaction-consistent read-only SQLite snapshots. Optional explicit after-phase refresh recomputes retained evidence only.',
            'limits': ['Samples from separate endpoints/databases have different snapshot moments.',
                'Source hashes describe disk; deployed behavior is established separately by API and actual trace evidence.',
                'Playback takes and cached shelf receipts do not prove fresh preparation synthesis.',
                'Outcome rows contain observed grader results, not independent proof of meaning or production-wide improvement.',
                'Technical/empty/deferred/preview outputs are excluded from learner quality outcomes; lab attempt counts are a separate denominator.']}
        data['samples'].append(sample)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    parser.add_argument('--seconds', type=int, default=0)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--output', default='docs/rejection-learning-live.json')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 300:
        parser.error('--seconds must be 0 through 300')
    if args.refresh and args.phase != 'after':
        parser.error('--refresh is only available in the after phase')
    output = Path(args.output)
    data_dir = Path(os.environ.get('SPARK_AGENT_DATA_DIR', '/app/data'))
    cache = {}; end = time.monotonic() + args.seconds
    if args.refresh:
        inspected = request(LEARNING)
        revision = (inspected.get('status') or {}).get('revision')
        if not isinstance(revision, int):
            raise RuntimeError('Current learning revision unavailable; no refresh sent.')
        result = request(LEARNING + '/refresh', {'expected_revision': revision})
        append(output, {'phase': 'refresh', 'at': time.time(), 'expected_revision': revision, 'result': result})
        if result.get('observation_error'):
            raise RuntimeError('Evidence refresh did not return a known success; it was not retried.')
    while True:
        sample = snapshot(args.phase, data_dir, cache); append(output, sample)
        status = (sample['learning'].get('status') or {})
        print(json.dumps({'phase': args.phase, 'at': sample['at'], 'station': sample['station'],
            'learning_revision': status.get('revision'), 'hints': len(status.get('hints') or []),
            'learning_errors': sample['learning'].get('errors'), 'review': sample['rejections'].get('latest_cursor'),
            'pipeline': sample['pipeline'].get('stages'),
            'learning_trace_counts': sample['sqlite'].get('lab_learning', {}).get('counts_since_restart')}), flush=True)
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(15, remaining))


if __name__ == '__main__':
    main()
