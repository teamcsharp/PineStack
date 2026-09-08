"""Bounded, serial rewrite trials through the authenticated production workbench.

Selection and exact evidence are checkpointed before any POST. Only /try may
be posted; this tool never votes, applies wording, changes settings, records
audio or requests playback. --run is explicit. --resume reuses request IDs.
"""
import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


BASE = '/api/orchestrator/rejections'
STAGES = {'turn_cut', 'turn_rewrite', 'grade', 'batch_rewrite', 'batch_retry', 'turn_retry', 'turn_yield', 'whole_turn_rejected'}


class ApiError(RuntimeError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f'HTTP {status}: {detail}')


def request(path, body=None, timeout=25):
    if body is not None and not (path.startswith(BASE + '/') and path.endswith('/try')):
        raise ValueError('The benchmark permits only isolated /try POSTs.')
    payload = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request('http://127.0.0.1:8096' + path, data=payload,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY'],
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get('detail', 'Request refused')
        except Exception:
            detail = 'Request refused'
        raise ApiError(error.code, str(detail)) from None


def source_hash(row):
    return hashlib.sha256(' '.join(str(row.get('source') or '').split()).encode('utf-8')).hexdigest()


def length_band(row):
    length = len(row.get('source') or '')
    return 'short' if length <= 200 else 'medium' if length <= 600 else 'long'


def reasons(row):
    return {('semantic' if 'semantic' in reason or 'meaning' in reason else
             'rhyme' if 'rhyme' in reason else
             'transformation' if 'transform' in reason else
             'copying' if 'copied' in reason else 'other')
            for reason in (row.get('reasons') or [])}


def select_cases(pool, count):
    """Greedy coverage of kinds, failure families and complete source lengths."""
    selected, kinds, faults, lengths, sources = [], set(), set(), set(), set()
    remaining = list(pool)
    while remaining and len(selected) < count:
        def score(row):
            kind = (row.get('context') or {}).get('kind') or 'unspecified'
            return (5 * (kind not in kinds) + 3 * len(reasons(row) - faults)
                    + 2 * (length_band(row) not in lengths), row.get('event_seq') or 0)
        row = max(remaining, key=score)
        selected.append(row)
        kinds.add((row.get('context') or {}).get('kind') or 'unspecified')
        faults.update(reasons(row))
        lengths.add(length_band(row))
        sources.add(source_hash(row))
        remaining = [item for item in remaining if source_hash(item) not in sources]
    return selected


def discover(count, detail_limit=160):
    summaries, before = [], 0
    for _ in range(10):
        query = urllib.parse.urlencode({'status': 'pending', 'gate': 'tint', 'limit': 200, 'before': before})
        page = request(BASE + '?' + query)
        summaries.extend(row for row in page.get('items') or [] if not row.get('technical'))
        if not page.get('has_more'):
            break
        before = page['next_before']
    groups = defaultdict(deque)
    for row in summaries:
        groups[row.get('kind') or 'unspecified'].append(row)
    candidates, checked, unavailable = [], 0, Counter()
    while groups and checked < detail_limit:
        for kind in list(groups):
            if checked >= detail_limit:
                break
            summary = groups[kind].popleft()
            if not groups[kind]:
                del groups[kind]
            seq = summary.get('event_seq') or summary.get('seq')
            path = BASE + '/' + urllib.parse.quote(summary['id'], safe='') + '?event_seq=' + str(seq)
            checked += 1
            try:
                row = request(path)
            except ApiError as error:
                unavailable['http_' + str(error.status)] += 1
                continue
            if row.get('technical') or row.get('occurrence_current') is False or row.get('review_status') != 'pending':
                unavailable['not_current_pending_editorial'] += 1
            elif (row.get('context') or {}).get('stage') not in STAGES:
                unavailable['unsupported_stage'] += 1
            elif not 25 <= len(row.get('source') or '') <= 1800:
                unavailable['outside_source_length_25_1800'] += 1
            else:
                candidates.append(row)
    return select_cases(candidates, count), {'summaries': len(summaries), 'details_checked': checked,
        'eligible': len(candidates), 'skipped': dict(unavailable), 'detail_limit': detail_limit}


def checkpoint(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def scope_path(case):
    return BASE + '/' + urllib.parse.quote(case['before']['id'], safe='')


def inspect(case, **query):
    return request(scope_path(case) + '/workbench?' + urllib.parse.urlencode({
        'event_seq': case['before']['event_seq'], **query}))


def retain_trace(case, operation):
    trace_id = (operation.get('result') or {}).get('trace_id')
    if not trace_id:
        return
    records, before = [], 0
    for _ in range(8):
        page = inspect(case, trace_id=trace_id, trace_before=before)['trace']
        records = page['items'] + records
        if not page['has_more']:
            break
        before = page['next_before']
    case['trace'] = {'trace_id': trace_id, 'items': records,
                     'complete': not page['has_more'], 'next_before': page.get('next_before')}
    details = [row['record'] for row in records]
    case['model_evidence'] = {'request_count': sum(row.get('kind') == 'model_request' for row in details),
        'wire_request_count': sum(row.get('kind') == 'model_wire_request' for row in details),
        'response_count': sum(row.get('kind') == 'model_response' for row in details),
        'elapsed_ms': [row.get('details', {}).get('elapsed_ms') for row in details
                       if row.get('kind') in {'model_response', 'model_error'}],
        'models': sorted({row.get('details', {}).get('model') for row in details
                          if row.get('kind') == 'model_request' and row.get('details', {}).get('model')})}


def trial_verdict(trial):
    """Separate permission under policy from the unchanged machine checks."""
    trial = trial or {}
    evaluation = trial.get('evaluation') or {}
    tint = evaluation.get('tint') or {}
    editorial = tint.get('editorial') or {}
    raw = tint.get('machine_ok')
    raw = raw if isinstance(raw, bool) else None
    caller = evaluation.get('call_contract') or {}
    if caller.get('ok') is False:
        raw = False
    accepted = evaluation.get('ok') is True
    raw_faults = list(tint.get('machine_faults') or []) + list(caller.get('faults') or [])
    return {'accepted': accepted,
            'accepted_with_advisories': accepted and editorial.get('accepted_with_advisories') is True,
            'raw_machine_ok': raw, 'raw_machine_faults': raw_faults}


def trial_metadata(trial):
    trial = trial or {}
    baseline, provenance = trial.get('baseline') or {}, trial.get('provenance') or {}
    return {key: baseline.get(key, provenance.get(key)) for key in
            ('grader_version', 'prompt_version', 'learning_revision', 'acceptance_mode')}


def summary(report):
    cases = report['cases']
    completed = [case for case in cases if case.get('status') == 'completed' and case.get('trial')]
    verdicts = [trial_verdict(case['trial']) for case in completed]
    return {'selected': len(cases), 'completed_trials': len(completed),
            'accepted': sum(row['accepted'] for row in verdicts),
            'accepted_with_advisories': sum(row['accepted_with_advisories'] for row in verdicts),
            'not_accepted': sum(not row['accepted'] for row in verdicts),
            'machine_passed': sum(row['raw_machine_ok'] is True for row in verdicts),
            'machine_failed': sum(row['raw_machine_ok'] is False for row in verdicts),
            'machine_unavailable': sum(row['raw_machine_ok'] is None for row in verdicts),
            'machine_basis': 'Raw tint.machine_ok plus caller structure; policy acceptance is counted separately.',
            'operation_states': dict(Counter(case.get('status', 'selected') for case in cases)),
            'faults': dict(Counter(fault for case in completed for fault in case['trial']['evaluation'].get('faults') or [])),
            'machine_faults': dict(Counter(fault for row in verdicts for fault in row['raw_machine_faults'])),
            'kinds': dict(Counter((case['before'].get('context') or {}).get('kind') or 'unspecified' for case in cases)),
            'source_lengths': dict(Counter(length_band(case['before']) for case in cases)),
            'interpretation': 'Selected retained failures repaired once with the deployed production turn prompt; this is not a station-wide generation pass rate or a before/after controlled model experiment.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Create isolated model trials after selection is checkpointed.')
    parser.add_argument('--resume', action='store_true', help='Reuse the exact saved selection and request IDs.')
    parser.add_argument('--count', type=int, default=8, choices=range(1, 11))
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--output', default='/app/docs/crystal-rewrite-benchmark.json')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 900:
        parser.error('--seconds must be30..900')
    destination = Path(args.output)
    if destination.exists() and not args.resume:
        raise SystemExit('The output already exists. Use --resume to retain its original cases and request IDs, or choose a new output path.')
    if args.resume:
        report = json.loads(destination.read_text(encoding='utf-8'))
    else:
        selected, selection = discover(args.count)
        if not selected:
            raise SystemExit('No current pending nontechnical supported tint turn was available.')
        run_id = uuid.uuid4().hex
        report = {'run_id': run_id, 'at_utc': datetime.now(timezone.utc).isoformat(),
            'votes': 0, 'applies': 0, 'settings_writes': 0, 'playback_requests': 0,
            'selection': selection, 'requested_count': args.count, 'cases': [],
            'policy_before': request('/api/orchestrator/rejection-policy')}
        state = request('/api/dj')
        report['station_before'] = {key: state.get(key) for key in ('on', 'paused')}
        for index, row in enumerate(selected):
            report['cases'].append({'before': row, 'source_sha256': source_hash(row), 'status': 'selected',
                'request': {'request_id': f'crystal-benchmark-{run_id}-{index}',
                            'event_seq': row['event_seq'], 'expected_revision': row['revision'],
                            'instruction': ''}})
        first = inspect(report['cases'][0])
        report['settings_before'] = first['settings']
        report['deployed_crystal'] = first['diagnostics']['crystal']
        checkpoint(destination, report)
    if not args.run:
        report['summary'] = summary(report)
        checkpoint(destination, report)
        print(json.dumps({'prepared_only': True, **report['summary']}))
        return
    deadline = time.monotonic() + args.seconds
    report.setdefault('runs', []).append({'started_utc': datetime.now(timezone.utc).isoformat(), 'budget_seconds': args.seconds})
    try:
        for case in report['cases']:
            if case.get('status') in {'completed', 'failed', 'stale', 'refused'}:
                continue
            if time.monotonic() >= deadline:
                break
            if not case.get('operation_id'):
                # Recheck exactly the saved occurrence; never silently switch
                # the benchmark to new source words or an updated decision.
                current = request(scope_path(case) + '?event_seq=' + str(case['request']['event_seq']))
                if (current.get('occurrence_current') is False or current.get('technical')
                        or current.get('review_status') != 'pending'
                        or current['revision'] != case['request']['expected_revision']):
                    case.update(status='stale', skipped_reason='Saved occurrence changed before its trial.')
                    checkpoint(destination, report)
                    continue
                case.setdefault('started_at', time.time())
                case['status'] = 'posting'
                checkpoint(destination, report)  # Full original and request precede every POST.
                try:
                    response = request(scope_path(case) + '/try', case['request'])
                except ApiError as error:
                    case['last_http_error'] = str(error)
                    case['status'] = 'waiting_for_diagnostic_room' if error.status == 429 else 'refused'
                    checkpoint(destination, report)
                    # A busy diagnostic owner is not another model attempt.
                    # Stop and let an explicit resume reuse this same request.
                    if error.status == 429:
                        break
                    continue
                case['operation_id'] = response['operation']['id']
                case['status'] = response['operation']['status']
                checkpoint(destination, report)
            while time.monotonic() < deadline:
                lab = inspect(case)
                operation = next((row for row in lab['operations'] if row['id'] == case['operation_id']), None)
                if operation is not None and (operation['status'] != 'pending' or operation.get('lease_expired')):
                    case.update(status=operation['status'], operation=operation,
                                elapsed_seconds=round(time.time() - case['started_at'], 3))
                    if operation.get('lease_expired'):
                        case['status'] = 'interrupted'
                    case['trial'] = next((row for row in lab['trials']['items'] if row.get('operation_id') == operation['id']), None)
                    if case['trial']:
                        case['verdict'] = trial_verdict(case['trial'])
                        case['trial_metadata'] = trial_metadata(case['trial'])
                    retain_trace(case, operation)
                    checkpoint(destination, report)
                    print(json.dumps({'case': case['before']['id'], 'seq': case['before']['event_seq'],
                        'status': case['status'], 'elapsed_seconds': case['elapsed_seconds'],
                        'verdict': case.get('verdict'), 'trial_metadata': case.get('trial_metadata')}), flush=True)
                    break
                time.sleep(min(2, max(0, deadline - time.monotonic())))
            if case.get('status') == 'pending':
                case['poll_budget_exhausted'] = True
                break  # Do not admit a second job while the first is unobserved.
    except Exception as error:
        report['runner_error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        report['summary'] = summary(report)
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            report['policy_after'] = request('/api/orchestrator/rejection-policy')
            report['policy_unchanged'] = report['policy_before'] == report['policy_after']
            report['settings_after'] = inspect(report['cases'][0])['settings']
            report['settings_unchanged'] = report['settings_before'] == report['settings_after']
            state = request('/api/dj')
            report['station_after'] = {key: state.get(key) for key in ('on', 'paused')}
        except Exception as error:
            report['final_observation_error'] = type(error).__name__ + ': ' + str(error)
        checkpoint(destination, report)
        print(json.dumps(report['summary'], ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
