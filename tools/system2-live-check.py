"""Bounded deployed System2 GET checks; never generate, vote, apply, or play.

Prepared separately from execution. Run --run only after deployment notification.
The only downloads are text/JSON scripts; media URLs are never requested.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('app.py', 'system2.py', 'system2_runtime.py', 'system2_media.py', 'system2_writing.py',
           'rhyme_assistance.py', 'crystal_prompts.py', 'crystal_contract.py', 'crystal_rhyme.py',
           'frontend/system2.js', 'frontend/system2.css')


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def hashes():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCES if (ROOT / name).is_file()}


def pick(row, keys):
    return {key: row.get(key) for key in keys if key in row}


def request(path):
    if not path.startswith(('/api/', '/health')):
        raise ValueError('Only station JSON and script endpoints are allowed')
    started = time.time()
    req = urllib.request.Request('http://127.0.0.1:8096' + path, method='GET',
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY']})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read(20 * 1024 * 1024 + 1)
            if len(body) > 20 * 1024 * 1024:
                raise ValueError('Response exceeded the bounded inspection limit')
            result = {'path': path, 'at': time.time(), 'http_status': response.status,
                      'content_type': response.headers.get('Content-Type'),
                      'content_disposition': response.headers.get('Content-Disposition'),
                      'bytes': len(body), 'sha256': digest(body), 'body': body.decode('utf-8')}
            if 'json' in str(result['content_type']):
                result['data'] = json.loads(result['body'])
    except Exception as error:
        result = {'path': path, 'at': time.time(), 'http_status': getattr(error, 'code', None),
                  'error': type(error).__name__}
    result['seconds'] = round(time.time() - started, 3)
    return result


def receipt(response):
    return {key: value for key, value in response.items() if key not in ('body', 'data')}


def safe_status(status):
    return {**pick(status, ('version', 'enabled', 'config', 'on', 'paused', 'at', 'refreshed_at', 'inventory',
                           'errors', 'repeat_seconds', 'runtime', 'versions', 'rhyme_assistance')),
            'work': pick(status.get('work') or {}, ('kind', 'stage', 'slot_id', 'job_id', 'trace_id', 'started_at', 'state', 'deadline')),
            'jobs': [pick(row, ('id', 'slot_id', 'kind', 'state', 'deadline', 'hard_deadline', 'attempts',
                               'coverage_missing', 'estimated_work_seconds', 'retry_at')) for row in status.get('jobs') or []]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output', default='docs/system2-live-check.json')
    parser.add_argument('--max-hours', type=int, default=12)
    args = parser.parse_args()
    if not args.run:
        print('Prepared only. Use --run after the backend deployment notification.')
        return 0
    if not 1 <= args.max_hours <= 24:
        parser.error('--max-hours must be 1..24')
    started = time.time(); before = hashes(); calls = []
    paths = ('/health', '/api/system2/status', '/api/dj', '/api/coordinator/resources', '/api/tint')
    with ThreadPoolExecutor(max_workers=4) as pool:
        initial = dict(zip(paths, pool.map(request, paths)))
    calls.extend(receipt(r) for r in initial.values())
    status = initial['/api/system2/status'].get('data') or {}
    station = initial['/api/dj'].get('data') or {}
    tint = initial['/api/tint'].get('data') or {}
    hours = []; candidates = []
    supplied = status.get('hours') or []
    for hour in supplied[:args.max_hours]:
        response = request('/api/system2/script?' + urllib.parse.urlencode({'hour': hour['id']})); calls.append(receipt(response))
        script = response.get('data') or {}
        by_slot = {row['slot_id']: row for row in script.get('slots') or []}
        expected = {row['id'] for row in hour.get('slots') or []}
        slots = []
        for slot in hour.get('slots') or []:
            section = by_slot.get(slot['id']) or {}
            performances = section.get('performances') or []
            drafts = section.get('drafts') or []
            candidates.extend(row for row in performances + drafts if row.get('id') and row.get('lines'))
            slots.append({**pick(slot, ('id', 'kind', 'status', 'start', 'deadline', 'target_seconds',
                'ready_seconds', 'debt_seconds', 'heard_seconds', 'delivered_seconds', 'coverage_mode')),
                'script_endpoint_has_slot': slot['id'] in by_slot,
                'performances': [{'id': row.get('id'), 'script_chars': len(row.get('script') or ''),
                    'script_sha256': digest(row.get('script') or ''), 'lines': len(row.get('lines') or [])} for row in performances],
                'drafts': [{'id': row.get('id'), 'script_chars': len(row.get('script') or ''),
                    'script_sha256': digest(row.get('script') or ''), 'ready': row.get('ready')} for row in drafts]})
        hours.append({**pick(hour, ('id', 'start', 'revision')), 'slots': slots,
            'script_http_status': response.get('http_status'),
            'script_all_slot_ids_match': set(by_slot) == expected,
            'script_response_complete': response.get('http_status') == 200 and set(by_slot) == expected})
    sample = {'available': False, 'reason': 'No candidate with retained line IDs was available in inspected hours.'}
    if candidates:
        candidate = candidates[0]; line = (candidate.get('lines') or [])[0]
        if line.get('id') is not None:
            scope = {'candidate': candidate['id'], 'line': line['id']}
            detail = request('/api/system2/line?' + urllib.parse.urlencode(scope)); calls.append(receipt(detail))
            txt = request('/api/system2/download?' + urllib.parse.urlencode({**scope, 'format': 'txt'})); calls.append(receipt(txt))
            js = request('/api/system2/download?' + urllib.parse.urlencode({**scope, 'format': 'json'})); calls.append(receipt(js))
            data = detail.get('data') or {}; saved = js.get('data') or {}
            words = data.get('lines') or []
            expected_text = '\n\n'.join(str(row.get('who') or row.get('voice') or 'Speaker') + ': ' + row['text'] for row in words) + '\n'
            sample = {'available': True, **scope, 'line_count': len(words),
                'line_source_match': [row.get('text') for row in words] == [line.get('text')],
                'detail_http_status': detail.get('http_status'), 'captured_call_count': len(data.get('calls') or []),
                'provenance': data.get('provenance'), 'limitations': data.get('limitations'),
                'text_download': {**receipt(txt), 'exact_text_matches_detail': txt.get('body') == expected_text},
                'json_download': {**receipt(js), 'exact_lines_match_detail': saved.get('lines') == words},
                'text_chars': sum(len(row.get('text') or '') for row in words)}
    module_spec = importlib.util.spec_from_file_location('system2_predeploy_processes', ROOT / 'tools/system2-predeploy.py')
    observer = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(observer)
    after = hashes()
    runtime_meta = {**pick(tint, ('runtime', 'versions', 'grader_version', 'prompt_version', 'contract_version', 'rhyme_assistance')),
                    **pick(status, ('runtime', 'versions', 'rhyme_assistance'))}
    report = {'started_at': started, 'finished_at': time.time(), 'read_only': True, 'get_requests': len(calls),
        'post_requests': 0, 'model_requests': 0, 'provider_requests': 0, 'media_requests': 0,
        'requests': calls, 'system2': safe_status(status),
        'station': pick(station, ('on', 'paused', 'playing', 'music_to', 'voice_to', 'reply_to', 'voice_device',
                                 'box_talk', 'nabu_music_level', 'nabu_voice_level', 'nabu_reply_level')),
        'resources': observer.clean(initial['/api/coordinator/resources'].get('data', {}).get('snapshot') or {}),
        'hours': hours, 'hours_omitted_by_bound': max(0, len(supplied) - len(hours)), 'sample_line': sample,
        'runtime_metadata': runtime_meta or {'available': False, 'reason': 'The delivered endpoint did not expose loaded versions/corpus status.'},
        'processes': observer.processes(), 'source_sha256_start': before, 'source_sha256_end': after,
        'changed_during_check': sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name)),
        'limitations': ['Disk hashes are separate from loaded runtime metadata; neither is substituted for the other.',
            'Status/script reads do not prove an entire slot has aired; debt and actual readiness are reported separately.',
            'Only text/JSON downloads were inspected. No media was requested or played.',
            'The normal status GET may refresh its persisted plan; this observer sends no control or job-creation request.',
            'This is a bounded point-in-time check. Production can update allocations between GETs.']}
    destination = Path(args.output)
    if not destination.is_absolute(): destination = ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(destination), 'health': initial['/health'].get('http_status'),
        'system2': initial['/api/system2/status'].get('http_status'), 'hours': len(hours),
        'all_inspected_scripts_complete': all(h['script_response_complete'] for h in hours) if hours else False,
        'sample_available': sample['available'], 'runtime_metadata_available': bool(runtime_meta),
        'changed_during_check': report['changed_during_check']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
