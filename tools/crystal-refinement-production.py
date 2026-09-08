"""Read-only production observations across a deployment; no trigger endpoints."""
import argparse
from collections import Counter, defaultdict
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time


def hashed(value):
    return hashlib.sha256(' '.join(str(value or '').split()).encode()).hexdigest()[:24]


def read_db(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN')
    return db


def review_snapshot(path, after):
    db = read_db(path)
    rows = []
    for raw in db.execute('SELECT seq,review_id,at,body FROM review_events WHERE seq>? ORDER BY seq', (after,)):
        body = json.loads(raw['body'])
        context = body.get('context') or {}
        evaluation = body.get('evaluation') or {}
        rows.append({'seq': raw['seq'], 'id': raw['review_id'], 'at': raw['at'],
            'gate': body.get('gate'), 'stage': context.get('stage'), 'kind': context.get('kind'),
            'disposition': body.get('disposition'), 'technical': bool(body.get('technical')),
            'source_chars': len(body.get('source') or ''), 'candidate_chars': len(body.get('candidate') or ''),
            'source_hash': hashed(body.get('source')), 'candidate_hash': hashed(body.get('candidate')),
            'reasons': body.get('reasons'), 'grader_version': evaluation.get('version'),
            'trace_id': context.get('lab_trace_id'),
            'parent_id': str((context.get('entry') or {}).get('sid') or (context.get('entry') or {}).get('at') or ''),
            'turn': context.get('turn')})
    result = {'latest_cursor': db.execute('SELECT COALESCE(MAX(seq),0) FROM review_events').fetchone()[0],
              'counts': dict(db.execute('SELECT review_status,COUNT(*) FROM line_reviews GROUP BY review_status')),
              'events': rows}
    db.close()
    return result


def trace_snapshot(path, after):
    db = read_db(path)
    rows = [dict(raw) for raw in db.execute('SELECT seq,trace_id,operation_id,at,record FROM lab_traces WHERE seq>? ORDER BY seq', (after,))]
    excluded = set()
    for row in rows:
        row['record'] = json.loads(row['record'])
        details = row['record'].get('details') or {}
        if row['operation_id'] or str(details.get('purpose') or '').startswith('interactive'):
            excluded.add(row['trace_id'])
    # Runtime records and completed diagnostic receipts can share a trace even
    # when the runtime records themselves have no operation_id column value.
    for raw in db.execute('SELECT body FROM lab_trials'):
        trace_id = (json.loads(raw[0]).get('provenance') or {}).get('trace_id')
        if trace_id:
            excluded.add(trace_id)
    public = []
    for row in rows:
        record = row['record']; details = record.get('details') or {}
        item = {key: row[key] for key in ('seq', 'trace_id', 'at')}
        item.update(kind=record.get('kind'), diagnostic=row['trace_id'] in excluded)
        if record.get('kind') in ('stage_started', 'stage_finished', 'stage_failed'):
            item.update(stage=details.get('stage'), elapsed_ms=details.get('elapsed_ms'), error_type=details.get('error_type'))
            result = details.get('result')
            if isinstance(result, dict):
                item.update(ok=result.get('ok'), deferred=bool(result.get('deferred')),
                            accepted=(result.get('coverage') or {}).get('accepted'),
                            required=(result.get('coverage') or {}).get('required'))
                reports = (result.get('evaluation') or {}).get('turns') or []
                item['completed_grade_reports'] = [{k: report.get(k) for k in ('version', 'ok', 'machine_ok')}
                                                    for report in reports if isinstance(report, dict)]
        if record.get('kind') in ('model_request', 'model_wire_request'):
            body = details.get('body') or details
            messages = body.get('messages') or []
            item.update(call_id=details.get('call_id'), purpose=details.get('purpose'), model=body.get('model'),
                shared_prompt_v2=any('Rewrite retained radio dialogue. Apply these priorities in order:' in str(m.get('content') or '') for m in messages),
                source_contract_present=any('SOURCE CONTRACT' in str(m.get('content') or '') for m in messages),
                messages=[{'role': m.get('role'), 'chars': len(str(m.get('content') or '')),
                           'hash': hashed(m.get('content'))} for m in messages])
            if record.get('kind') == 'model_wire_request':
                turns, budgets = [], []
                for message in messages:
                    content = str(message.get('content') or '')
                    budgets.extend(int(value) for value in re.findall(
                        r'Output budget for this group:\s*(\d+)\s*characters', content))
                    for line in content.splitlines():
                        if not line.startswith('[{"id":'):
                            continue
                        try:
                            parsed = json.loads(line)
                            turns.extend(row for row in parsed if isinstance(row, dict) and 'requested' in row)
                        except (ValueError, TypeError):
                            pass
                requested = [row for row in turns if row.get('requested')]
                item.update(think=body.get('think'), num_predict=(body.get('options') or {}).get('num_predict'),
                    group_budget_chars=budgets, original_turns=len(turns), requested_turns=len(requested),
                    requested_source_chars=[len(str(row.get('source') or '')) for row in requested],
                    compact_source_contracts=sum(isinstance(row.get('source_contract'), dict) for row in requested),
                    no_retained_candidate_statuses=sum(row.get('attempt_status') == 'no_retained_candidate' for row in requested))
        if record.get('kind') in ('model_response', 'model_error'):
            item.update(call_id=details.get('call_id'), elapsed_ms=details.get('elapsed_ms'), error_type=details.get('error_type'))
            response = details.get('response') or {}
            if isinstance(response, dict):
                item.update(done=response.get('done'), done_reason=response.get('done_reason'),
                    admission_deferred=bool(response.get('deferred')),
                    prompt_tokens=response.get('prompt_eval_count'), output_tokens=response.get('eval_count'),
                    prefill_seconds=round(response.get('prompt_eval_duration', 0) / 1e9, 3),
                    decode_seconds=round(response.get('eval_duration', 0) / 1e9, 3))
        if record.get('kind') == 'tint_judge':
            grade = (details.get('details') or {}).get('evaluation') or {}
            item.update(ok=grade.get('ok'), grader_version=grade.get('version'), faults=grade.get('faults'))
        public.append(item)
    result = {'latest_cursor': db.execute('SELECT COALESCE(MAX(seq),0) FROM lab_traces').fetchone()[0],
              'diagnostic_trace_ids_excluded': sorted(excluded & {row['trace_id'] for row in rows}), 'events': public}
    db.close()
    return result


def recording_summary(samples, start):
    after = [s for s in samples if s['phase'] == 'after']
    receipts = {}
    for sample in after:
        for row in sample['pantry']['rows']:
            if (row.get('media_mtime') or 0) >= start and row.get('media_bytes', 0) > 0:
                receipts[row['media_id']] = row
    fresh = [row for row in receipts.values() if row.get('receipt_matches_media')
             and (row.get('render_ms') or 0) > 0 and not row.get('cached')]
    return {'media_created_since_deployment': len(receipts),
            'positive_uncached_synthesis_receipts': len(fresh),
            'fresh_by_kind': dict(Counter(row.get('kind') or 'unknown' for row in fresh)),
            'fresh_by_engine': dict(Counter(row.get('engine') or 'unknown' for row in fresh)),
            'fresh_audio_seconds': round(sum(row.get('seconds') or 0 for row in fresh), 2),
            'samples_with_active_preparation': sum((s.get('booths') or {}).get('preparing', 0) > 0 for s in after),
            'first_observed_stages': after[0]['pipeline'].get('stages'),
            'latest_stages': after[-1]['pipeline'].get('stages'),
            'limits': ['No immediate predeploy media baseline was captured; production proof here requires file mtime after this deployment plus a matching uncached positive synthesis receipt.',
                       'Pantry API returns at most 400 newest rows; older or removed receipts can be missed.',
                       'Playback take/shelf counters are not preparation render counters.']}


def call_receipts(events):
    calls = {}
    for event in events:
        identity = event.get('call_id')
        if not identity:
            continue
        row = calls.setdefault(identity, {'call_id': identity, 'trace_id': event['trace_id']})
        if event['kind'] == 'model_request':
            row.update(request_at=event['at'], purpose=event.get('purpose'), model=event.get('model'))
        elif event['kind'] == 'model_wire_request':
            row.update(wire_at=event['at'], **{key: event.get(key) for key in
                ('think', 'num_predict', 'group_budget_chars', 'original_turns', 'requested_turns',
                 'requested_source_chars', 'compact_source_contracts', 'no_retained_candidate_statuses')})
            row['message_chars'] = sum(message['chars'] for message in event.get('messages', []))
        elif event['kind'] == 'model_response':
            row.update(response_at=event['at'], **{key: event.get(key) for key in
                ('done', 'done_reason', 'admission_deferred', 'prompt_tokens', 'output_tokens',
                 'prefill_seconds', 'decode_seconds')})
        elif event['kind'] == 'model_error':
            row.update(error_at=event['at'], error_type=event.get('error_type'))
    for row in calls.values():
        if 'request_at' in row and 'wire_at' in row:
            row['queue_before_wire_seconds'] = round(row['wire_at'] - row['request_at'], 3)
        if 'wire_at' in row and 'response_at' in row:
            row['wire_to_response_seconds'] = round(row['response_at'] - row['wire_at'], 3)
    return list(calls.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=('before', 'after'))
    parser.add_argument('--output', default='docs/crystal-refinement-production.json')
    args = parser.parse_args()
    output = Path(args.output)
    data = json.loads(output.read_text())
    baseline = data['baseline_cursor']
    data_dir = Path(os.environ.get('SPARK_AGENT_DATA_DIR', '/app/data'))
    spec = importlib.util.spec_from_file_location('recording_observation', Path(__file__).with_name('rejection-workbench-recording-check.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    snap = module.snapshot('http://127.0.0.1:8096', args.phase)
    snap['review'] = review_snapshot(data_dir / 'line_review.sqlite3', baseline['line_review']['latest_cursor'])
    snap['trace'] = trace_snapshot(data_dir / 'rejection_lab.sqlite3', baseline['rejection_lab']['latest_cursor'])
    snap['file_sha256'].update({name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                               for name in ('crystal_prompts.py', 'crystal_contract.py', 'crystal_source.py', 'segment_contract.py')})
    snap['source_hash_scope'] = 'On-disk source at observation time; later edits need not be loaded by this process. Wire traces establish active prompt and evaluator behavior.'
    data['snapshots'].append(snap)
    after = [s for s in data['snapshots'] if s['phase'] == 'after']
    if after:
        start = after[0]['container_start_epoch'] or after[0]['at']
        latest = after[-1]
        traces = [r for r in latest['trace']['events'] if r['at'] >= start and not r['diagnostic']]
        diagnostic_ids = set(latest['trace']['diagnostic_trace_ids_excluded'])
        reviews = [r for r in latest['review']['events'] if r['at'] >= start and r['trace_id'] not in diagnostic_ids]
        repeats = defaultdict(list)
        for row in reviews:
            key = (row['gate'], row['kind'], row['stage'], row['source_hash'], row['candidate_hash'],
                   tuple(sorted(row['reasons'] or [])), row['parent_id'], row['turn'])
            repeats[key].append(row)
        repeated = [{'count': len(group), 'review_ids': sorted({r['id'] for r in group}),
                     'sequences': [r['seq'] for r in group], 'stage': group[0]['stage'],
                     'seconds': round(group[-1]['at'] - group[0]['at'], 2)}
                    for group in repeats.values() if len(group) > 1]
        data['summary'] = {'deployment_epoch': start, 'samples': len(after), 'latest_at': latest['at'],
            'production_review_events': len(reviews),
            'review_dispositions': dict(Counter(r['disposition'] for r in reviews)),
            'review_stages': dict(Counter(str(r['stage']) for r in reviews)),
            'review_grader_versions': dict(Counter(str(r['grader_version']) for r in reviews)),
            'same_candidate_same_parent_recaptures': repeated,
            'slash_veto_events': sum(any('copied bars rather than radio speech' in str(reason)
                for reason in (row.get('reasons') or [])) for row in reviews),
            'production_trace_events': len(traces),
            'production_stage_finishes': dict(Counter(str(r.get('stage')) for r in traces if r['kind'] == 'stage_finished')),
            'production_deferred_finishes': sum(bool(r.get('deferred')) for r in traces),
            'wire_requests': sum(r['kind'] == 'model_wire_request' for r in traces),
            'wire_requests_shared_prompt_v2': sum(r['kind'] == 'model_wire_request' and r.get('shared_prompt_v2', False) for r in traces),
            'trace_grader_versions': dict(Counter(str(r['grader_version']) for r in traces if r.get('grader_version') is not None)),
            'completed_round_report_versions': dict(Counter(str(report.get('version'))
                for r in traces for report in r.get('completed_grade_reports', []))),
            'trace_grade_outcomes': dict(Counter(str(r.get('ok')) for r in traces if r['kind'] == 'tint_judge')),
            'production_call_receipts': call_receipts(traces),
            'recording': recording_summary(data['snapshots'], start),
            'limitations': ['Rejection events are not all model attempts; these counts do not establish an acceptance or improvement rate.',
                           'Shared prompt v2 is identified from the actual wire message template, not a guessed file version.',
                           'Diagnostic trial trace IDs and interactive-purpose traces are excluded, including the explicit live API benchmark.',
                           'Same text recaptures alone do not prove duplicate work when independent retained parent identities differ.',
                           'Source file hashes describe disk at sample time, not a guarantee that a running process imported later edits.',
                           'The two SQLite databases are each transaction-consistent; their snapshot moments may differ.']}
        data['status'] = 'observing'
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({'phase':args.phase,'at':snap['at'],'paused':snap['paused'],
        'review_cursor':snap['review']['latest_cursor'],'trace_cursor':snap['trace']['latest_cursor'],
        'booths':snap['booths'],'summary':data.get('summary')}))


if __name__ == '__main__':
    main()
