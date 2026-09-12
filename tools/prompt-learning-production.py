"""Bounded GET-only learning/recording observations; no production triggers."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request


def hashed(value):
    return hashlib.sha256(' '.join(str(value or '').split()).encode()).hexdigest()[:24]


def reports(value, path='result'):
    if isinstance(value, dict):
        if value.get('version') == 6 and isinstance(value.get('editorial'), dict):
            yield path, value
        else:
            for key, child in value.items():
                yield from reports(child, path + '.' + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from reports(child, path + '[' + str(index) + ']')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete', action='store_true')
    args = parser.parse_args()
    output = Path('docs/prompt-learning-production.json')
    subprocess.run([sys.executable, 'tools/crystal-refinement-production.py', '--phase', 'after',
                    '--output', str(output)], check=True, stdout=subprocess.DEVNULL)
    data = json.loads(output.read_text())
    deployment = json.loads(Path('docs/prompt-learning-deployment.json').read_text())
    activated = deployment['activation']['status']['updated_at']
    headers = {'Authorization': 'Bearer ' + os.environ.get('SPARK_AGENT_API_KEY', '')}
    request = urllib.request.Request('http://127.0.0.1:8096/api/orchestrator/prompt-learning', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        learning = json.load(response)
    state = learning['status']
    db = sqlite3.connect('file:/app/data/rejection_lab.sqlite3?mode=ro', uri=True)
    db.execute('BEGIN')
    rows = [{'seq': seq, 'trace_id': trace, 'at': stamp, 'record': json.loads(body)}
            for seq, trace, stamp, body in db.execute(
                'SELECT seq,trace_id,at,record FROM lab_traces WHERE at>=? ORDER BY seq',
                (data['snapshots'][0]['container_start_epoch'],))]
    db.close()
    excluded = set(data['snapshots'][-1]['trace']['diagnostic_trace_ids_excluded'])
    sources, trace_started = {}, {}
    for row in rows:
        record = row['record']; details = record.get('details') or {}
        if record.get('kind') == 'stage_started':
            trace_started.setdefault(row['trace_id'], row['at'])
            sources.setdefault(row['trace_id'], []).extend(
                ' '.join(str(details[key]).split()) for key in ('text', 'script') if details.get(key))
    wires, grades, kinds, revisions = [], [], Counter(), []
    for row in rows:
        if row['at'] < activated or row['trace_id'] in excluded:
            continue
        record = row['record']; details = record.get('details') or {}
        kind = record.get('kind'); kinds[kind] += 1
        if kind == 'prompt_learning':
            revisions.append({'at': row['at'], 'trace_id': row['trace_id'],
                              'revision': details.get('revision'), 'reason': details.get('reason')})
        if kind == 'model_wire_request':
            body = details.get('body') or {}; messages = body.get('messages') or []
            text = '\n'.join(str(message.get('content') or '') for message in messages)
            units = []
            for line in text.splitlines():
                if line.startswith('[{"id":'):
                    try:
                        parsed = json.loads(line)
                        units.extend(item for item in parsed if isinstance(item, dict) and 'source' in item)
                    except (ValueError, TypeError):
                        pass
            parent = sources.get(row['trace_id'], [])
            originals = []
            for unit in units:
                source = str(unit['source'])
                normalized = ' '.join(source.split())
                originals.append({'id': unit.get('id'), 'speaker': unit.get('speaker'),
                    'requested': bool(unit.get('requested')), 'source_chars': len(source),
                    'source_hash': hashed(source), 'retained_parent_match':
                        any(normalized in original for original in parent) if parent else None,
                    'contract_keys': sorted((unit.get('source_contract') or {}).keys())})
            wires.append({'seq': row['seq'], 'at': row['at'], 'trace_id': row['trace_id'],
                'call_id': details.get('call_id'), 'model': body.get('model'), 'think': body.get('think'),
                'message_chars': len(text), 'fluid_instruction': 'ORCHESTRATOR FLUID ACCEPTANCE' in text,
                'learning_revisions': sorted(set(int(x) for x in re.findall(r'learning revision (\d+)', text))),
                'fixed_hints_present': list(dict.fromkeys(hint['text'] for hint in state.get('hints', []) if hint['text'] in text)),
                'trace_started_at': trace_started.get(row['trace_id']),
                'trace_started_before_activation': trace_started.get(row['trace_id'], row['at']) < activated,
                'originals': originals, 'original_ids_ordered':
                    [unit.get('id') for unit in units] == sorted(unit.get('id') for unit in units)})
        if kind in ('stage_finished', 'tint_judge'):
            value = details.get('result') if kind == 'stage_finished' else details
            for path, grade in reports(value):
                semantic = grade.get('semantic') or {}; editorial = grade['editorial']
                grades.append({'seq': row['seq'], 'at': row['at'], 'trace_id': row['trace_id'],
                    'path': path, 'grader_version': grade['version'], 'raw_ok': grade.get('machine_ok'),
                    'accepted': grade.get('ok'), 'accepted_with_advisories': editorial.get('accepted_with_advisories'),
                    'mode': editorial.get('mode'), 'editorial_version': editorial.get('version'),
                    'semantic_ok': semantic.get('ok'), 'entities_ok': semantic.get('entities'),
                    'question_ok': semantic.get('question'), 'negation_ok': semantic.get('negation'),
                    'caller_ok': (semantic.get('call_contract') or {}).get('ok'),
                    'rap_ok': (grade.get('rhyme') or {}).get('rap', {}).get('ok'),
                    'copying_ok': (grade.get('copying') or {}).get('ok'),
                    'raw_faults': grade.get('machine_faults'), 'blocking_faults': grade.get('faults')})
    last = data['snapshots'][-1]
    data['learning_observation'] = {'activation_epoch': activated, 'observed_until': time.time(),
        'mode': state['mode'], 'enabled': state['enabled'], 'revision': state['revision'],
        'hint_count': len(state.get('hints', [])), 'errors': learning.get('errors'),
        'observed_record_count': state.get('observation_count'),
        'hints': [{key: hint.get(key) for key in ('id', 'kind', 'pattern', 'text', 'sources', 'parents', 'eligible')}
                  for hint in state.get('hints', [])],
        'production_wire_count': len(wires), 'wire_with_fluid_instruction': sum(w['fluid_instruction'] for w in wires),
        'wire_with_fixed_hints': sum(bool(w['fixed_hints_present']) for w in wires),
        'wire_learning_revisions': dict(Counter(str(revision) for w in wires for revision in w['learning_revisions'])),
        'wires': wires, 'grade_report_occurrences': grades,
        'accepted_grade_report_occurrences': sum(g['accepted'] is True for g in grades),
        'advisory_grade_report_occurrences': sum(g['accepted_with_advisories'] is True for g in grades),
        'automatic_revision_trace_events': revisions,
        'production_trace_kinds': dict(kinds), 'diagnostic_trace_ids_excluded': sorted(excluded),
        'latest_stock': last['pipeline']['stages'], 'on': last['on'], 'paused': last['paused'],
        'source_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                          for name in ('app.py','crystal_acceptance.py','prompt_learning.py')},
        'limits': ['Learning chooses fixed catalog reminders from distinct retained failures; it is not an LLM prompt optimizer and schedules no separate learning model task.',
                   'Grade reports can recur within progress snapshots; report occurrences are not distinct attempts or an acceptance-rate denominator.',
                   'Original prompt text is compared with normalized retained trace input when available; positive lexical/entity checks do not prove every proposition.',
                   'Wire messages can have been drafted before activation while waiting in FIFO; missing hints on an early wire do not prove failed new-prompt construction.',
                   'Stock changes during natural playback do not isolate the effect of acceptance mode. Positive uncached synthesis proof is reported separately.']}
    data['status'] = 'complete_bounded_observation' if args.complete else 'observing'
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({'at':last['at'],'status':data['status'],'mode':state['mode'],'revision':state['revision'],
        'wires':len(wires),'wires_with_hints':sum(bool(w['fixed_hints_present']) for w in wires),
        'grade_reports':len(grades),'advisory_reports':sum(g['accepted_with_advisories'] is True for g in grades),
        'stock':last['pipeline']['stages'],'recording':data['summary']['recording']}))


if __name__ == '__main__':
    main()
