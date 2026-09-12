"""Check delivered diagnostic APIs; --preview asks two labelled, nonproduction model jobs.

Run inside spark-agent. Never votes, applies wording, changes settings, records
audio, or requests playback. The optional conversation/trial stay inspectable.
"""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def request(path, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request('http://127.0.0.1:8096' + path, data=payload,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY'],
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    destination = Path('/app/docs/rejection-workbench-' + ('model-check' if args.preview else 'deployment') + '.json')
    report = {'at': time.time(), 'ok': False, 'preview_requested': args.preview,
              'votes': 0, 'wording_applies': 0, 'settings_writes': 0, 'playback_requests': 0}

    def save():
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')

    try:
        state = request('/api/dj')
        report['station_before'] = {key: state.get(key) for key in ('on', 'paused')}
        paths = request('/openapi.json')['paths']
        base = '/api/orchestrator/rejections'
        expected = [base + '/{review_id}/' + suffix for suffix in ('workbench', 'discuss', 'try', 'apply')]
        expected.append('/api/orchestrator/rejection-lab/settings')
        report['routes'] = {path: path in paths for path in expected}
        assert all(report['routes'].values()), 'The running backend is missing diagnostic routes.'
        queue = request(base + '?status=all&gate=tint&limit=200')
        selected = None
        for summary in queue.get('items') or []:
            row = request(base + '/' + summary['id'])
            if (not row.get('technical') and row.get('context', {}).get('stage') in {'turn_cut', 'turn_rewrite', 'grade'}
                    and 20 < len(row.get('source') or '') < 1500 and row.get('review_status') in {'pending', 'kept'}):
                selected = row
                break
        assert selected, 'No supported natural crystal turn is available for inspection.'
        row = selected
        scope = base + '/' + row['id']
        read_path = scope + '/workbench?event_seq=' + str(row['event_seq'])
        lab = request(read_path)
        report['occurrence'] = {key: row.get(key) for key in ('id', 'event_seq', 'revision', 'gate')}
        report['inspection'] = {'trace_available': lab['trace']['available'], 'trace_note': lab['trace']['note'],
            'trace_sources': lab['trace_sources'], 'capabilities': lab['capabilities'],
            'crystal': lab['diagnostics']['crystal'], 'trace_capture': lab['diagnostics']['trace_capture'],
            'instruction_settings': lab['settings']}
        report['policy_before'] = request('/api/orchestrator/rejection-policy')
        save()
        if args.preview:
            report['operations'] = []
            jobs = [('discuss', {'message': '[Deployment check] Explain this exact cut: which checks failed, what the retained prompts prove, and one concrete way to preserve meaning while making the turn rhyme. Distinguish fresh recording work from cached playback counts. Do not change settings or approve anything.'}),
                    ('try', {'instruction': 'Keep the concrete content words, names, numbers, question or negation. Make a clear audible rhyme pair between two short bars. Do not add claims or merely repeat the same word.'})]
            for kind, content in jobs:
                current = request(scope)
                body = {'request_id': 'deployment-' + uuid.uuid4().hex, 'event_seq': row['event_seq'],
                        'expected_revision': current['revision'], **content}
                job = {'kind': kind, 'request_id': body['request_id'], 'started': time.time()}
                report['operations'].append(job)
                save()
                result = request(scope + '/' + kind, body)
                operation_id = result['operation']['id']
                job['id'] = operation_id
                save()
                deadline = time.monotonic() + 265
                while time.monotonic() < deadline:
                    lab = request(read_path)
                    operation = next((op for op in lab['operations'] if op['id'] == operation_id), None)
                    if operation and operation['status'] != 'pending':
                        break
                    time.sleep(2)
                assert operation and operation['status'] != 'pending', 'Diagnostic operation did not finish in its advertised time.'
                job.update(status=operation['status'], result=operation.get('result'), error=operation.get('error'),
                           elapsed_seconds=round(time.time() - job['started'], 2))
                if kind == 'discuss':
                    job['reply'] = next((message['content'] for message in reversed(lab['messages']['items'])
                                         if message.get('role') == 'assistant' and message.get('operation_id') == operation_id), '')
                else:
                    job['trial'] = next((trial for trial in lab['trials']['items'] if trial.get('operation_id') == operation_id), None)
                trace_id = (operation.get('result') or {}).get('trace_id')
                if trace_id:
                    traced = request(read_path + '&trace_id=' + trace_id)
                    job['trace_kinds'] = [step['record']['kind'] for step in traced['trace']['items']]
                save()
                assert operation['status'] == 'completed', 'Diagnostic job failed; retained error is in the report.'
        final = request(read_path)
        report['policy_unchanged'] = report['policy_before'] == request('/api/orchestrator/rejection-policy')
        report['instruction_unchanged'] = report['inspection']['instruction_settings'] == final['settings']
        report['review_revision_unchanged'] = row['revision'] == request(scope)['revision']
        state = request('/api/dj')
        report['station_after'] = {key: state.get(key) for key in ('on', 'paused')}
        assert report['policy_unchanged'] and report['instruction_unchanged'], 'Operator policy changed during the check.'
        report['ok'] = True
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        save()
        print(json.dumps({key: report.get(key) for key in ('ok', 'error', 'occurrence', 'station_before', 'station_after', 'policy_unchanged', 'instruction_unchanged')}, indent=2))


if __name__ == '__main__':
    main()
