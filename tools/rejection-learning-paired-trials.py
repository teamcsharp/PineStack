"""Pinned, serial diagnostic trials; never apply, vote, record or play audio."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=('baseline', 'candidate'), required=True)
    p.add_argument('--seconds', type=int, default=900)
    args = p.parse_args()
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('serial_trials', root / 'tools/crystal-rewrite-benchmark.py')
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    output = root / ('docs/rejection-learning-' + args.phase + '-trials.json')
    if not output.exists():
        frozen = json.loads((root / 'docs/rejection-learning-followup-cases.json').read_text(encoding='utf-8'))
        run_id = uuid.uuid4().hex
        report = {'run_id': run_id, 'phase': args.phase, 'at_utc': datetime.now(timezone.utc).isoformat(),
            'votes': 0, 'applies': 0, 'settings_writes': 0, 'playback_requests': 0,
            'selection': {'method': 'Frozen source and parent cases; current retained occurrence must match full words and context.',
                          'snapshot_sha256': frozen['snapshot_sha256']},
            'cases': [], 'skipped': [], 'policy_before': bench.request('/api/orchestrator/rejection-policy')}
        previous = {}
        if args.phase == 'candidate':
            baseline = json.loads((root / 'docs/rejection-learning-baseline-trials.json').read_text(encoding='utf-8'))
            previous = {x['frozen_case_id']: x for x in baseline['cases'] if x.get('status') == 'completed'}
        for item in frozen['cases']:
            if args.phase == 'candidate' and item['case_id'] not in previous:
                continue
            row = bench.request(bench.BASE + '/' + item['review_id'])
            historical = bench.request(bench.BASE + '/' + item['review_id'] + '?event_seq=' + str(item['review_seq']))
            fields = ('kind', 'script_plain', 'turns', 'crystal', 'chunks', 'answering')
            if (row.get('source') != item['source'] or row.get('candidate') != item['candidate']
                    or any(row.get('context', {}).get(k) != historical.get('context', {}).get(k) for k in fields)
                    or row.get('review_status') != 'pending' or not bench.inspect({'before': row})['capabilities']['try_wording']):
                report['skipped'].append({'case_id': item['case_id'], 'reason': 'Current retained occurrence differs or is ineligible.'})
                continue
            if previous and any(row.get('context', {}).get(k) != previous[item['case_id']]['before'].get('context', {}).get(k) for k in fields):
                report['skipped'].append({'case_id': item['case_id'], 'reason': 'Context changed since baseline.'})
                continue
            report['cases'].append({'before': row, 'frozen_case_id': item['case_id'], 'split': item['split'],
                'source_sha256': bench.source_hash(row), 'status': 'selected',
                'request': {'request_id': 'learning-pair-' + run_id + '-' + item['case_id'],
                            'event_seq': row['event_seq'], 'expected_revision': row['revision'], 'instruction': ''}})
        if not report['cases']:
            raise SystemExit('No unchanged current cases remain; no trials submitted.')
        report['requested_count'] = len(report['cases'])
        state = bench.request('/api/dj')
        report['station_before'] = {k: state.get(k) for k in ('on', 'paused')}
        first = bench.inspect(report['cases'][0])
        report['settings_before'] = first['settings']
        report['deployed_crystal'] = first['diagnostics']['crystal']
        bench.checkpoint(output, report)
    sys.argv = ['serial_trials', '--run', '--resume', '--seconds', str(args.seconds), '--output', str(output)]
    bench.main()


if __name__ == '__main__':
    main()
