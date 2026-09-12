"""Inspect deployed learning; --activate enables the requested fluid/learning mode.

Run inside the station container. No model, review vote, recovery or playback
endpoint is permitted. Activation is explicit and records before/after evidence.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request


LEARNING = '/api/orchestrator/prompt-learning'


def request(path, body=None, raw=False):
    if body is not None and path not in {LEARNING, LEARNING + '/refresh'}:
        raise ValueError('Only the requested learning controls may be written.')
    req = urllib.request.Request('http://127.0.0.1:8096' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY'],
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read().decode('utf-8')
        return data if raw else json.loads(data)


def station_state():
    state = request('/api/dj')
    return {key: state.get(key) for key in ('on', 'paused')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--output', default='docs/prompt-learning-deployment.json')
    args = parser.parse_args()
    report = {'started_at': time.time(), 'at_utc': datetime.now(timezone.utc).isoformat(),
              'activation_requested': args.activate, 'votes': 0, 'wording_applies': 0,
              'playback_requests': 0, 'model_requests': 0, 'ok': False}
    path = Path(args.output)
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        report['station_before'] = station_state()
        report['rejection_policy_before'] = request('/api/orchestrator/rejection-policy')
        report['learning_before'] = request(LEARNING)
        report['source_sha256'] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
            'app.py', 'crystal_acceptance.py', 'prompt_learning.py', 'crystal_prompts.py',
            'rejection_workbench.py', 'frontend/rejection-review.js', 'frontend/rejection-review.css', 'package.json')}
        served = request('/orchestrator-review/rejection-review.js', raw=True)
        report['served_ui'] = {'learn_controls': 'Learn and improve' in served,
                               'learning_route': LEARNING in served,
                               'matches_source': served == Path('frontend/rejection-review.js').read_text(encoding='utf-8')}
        assert all(report['served_ui'].values()), 'Delivered learning controls differ from tested source.'
        save()
        if args.activate:
            report['evidence_refresh'] = request(LEARNING + '/refresh',
                {'expected_revision': request(LEARNING)['status']['revision']})
            report['activation'] = request(LEARNING, {
                'expected_revision': request(LEARNING)['status']['revision'],
                'enabled': True, 'mode': 'fluid'})
            assert report['activation']['status']['enabled'] is True
            assert report['activation']['status']['mode'] == 'fluid'
            assert report['evidence_refresh']['errors']['count'] == 0
        report['learning_after'] = request(LEARNING)
        report['rejection_policy_after'] = request('/api/orchestrator/rejection-policy')
        report['station_after'] = station_state()
        report['rejection_policy_unchanged'] = report['rejection_policy_before'] == report['rejection_policy_after']
        assert report['rejection_policy_unchanged'], 'The separate master rejection policy changed during observation.'
        assert report['station_before'] == report['station_after'], 'Station on/paused state changed during observation.'
        report['ok'] = True
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        report['finished_at'] = time.time()
        save()
        print(json.dumps({'ok': report['ok'], 'station': report.get('station_after'),
            'learning': {key: report.get('learning_after', {}).get('status', {}).get(key)
                         for key in ('revision', 'enabled', 'mode')},
            'hints': len(report.get('learning_after', {}).get('status', {}).get('hints') or []),
            'error': report.get('error')}))


if __name__ == '__main__':
    main()
