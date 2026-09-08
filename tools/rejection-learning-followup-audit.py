"""Read-only consistent rejection snapshots and exact follow-up corpus analysis."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.request


def norm(text):
    return ' '.join(str(text or '').split())


def digest(value):
    return hashlib.sha256(norm(value).encode()).hexdigest()[:24]


def count(rows, key):
    return dict(Counter(key(row) for row in rows).most_common())


def get(route):
    req = urllib.request.Request('http://127.0.0.1:8096' + route,
        headers={'Authorization': 'Bearer ' + os.environ.get('SPARK_AGENT_API_KEY', '')})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except Exception as exc:
        return {'error_type': type(exc).__name__}


def capture(output, after):
    started = time.time()
    folder = Path('/app/data/rejection_followup_audit') / str(int(started))
    folder.mkdir(parents=True)
    path = folder / 'line_review.sqlite3'
    source = sqlite3.connect('file:/app/data/line_review.sqlite3?mode=ro', uri=True)
    dest = sqlite3.connect(path)
    source.backup(dest)
    source.close()
    first = dest.execute('SELECT at FROM review_events WHERE seq>? ORDER BY seq LIMIT 1', (after,)).fetchone()
    latest = dest.execute('SELECT MAX(seq) FROM review_events').fetchone()[0]
    statuses = dict(dest.execute('SELECT review_status,COUNT(*) FROM line_reviews GROUP BY review_status'))
    dest.close()
    traces = folder / 'traces.jsonl'
    lab = sqlite3.connect('file:/app/data/rejection_lab.sqlite3?mode=ro', uri=True)
    lab.execute('BEGIN')
    # Include trace starts before the first new refusal without copying unrelated history.
    since = float(first[0]) - 1800 if first else started
    with traces.open('w') as stream:
        for seq, trace, operation, stamp, body in lab.execute(
                'SELECT seq,trace_id,operation_id,at,record FROM lab_traces WHERE at>=? ORDER BY seq', (since,)):
            stream.write(json.dumps({'seq': seq, 'trace_id': trace, 'operation_id': operation,
                                    'at': stamp, 'record': json.loads(body)}) + '\n')
    trials = [json.loads(row[0]) for row in lab.execute('SELECT body FROM lab_trials')]
    lab.close()
    (folder / 'trials.json').write_text(json.dumps(trials))
    manifest = {'captured_at': started, 'completed_at': time.time(), 'after_cursor': after,
        'snapshot': str(path), 'traces': str(traces), 'trials': str(folder / 'trials.json'),
        'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'snapshot_latest_cursor': latest, 'trace_since_epoch': since,
        'state': {route: get(route) for route in ('/api/orchestrator/prompt-learning',
            '/api/orchestrator/rejections/policy', '/api/coordinator/logic', '/api/dj/flow')},
        'source_hashes': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                          for name in ('app.py', 'crystal_prompts.py', 'crystal_acceptance.py', 'prompt_learning.py')}}
    output.write_text(json.dumps({'status': 'captured', 'manifest': manifest}, indent=2))
    print(json.dumps({'snapshot': str(path), 'traces': str(traces), 'latest_cursor': latest,
                      'current_status': statuses}))


def analyze(output):
    manifest = json.loads(output.read_text())['manifest']
    db = sqlite3.connect(Path(manifest['snapshot']).as_uri() + '?mode=ro', uri=True)
    events = []
    for seq, identity, stamp, body in db.execute('SELECT seq,review_id,at,body FROM review_events WHERE seq>? ORDER BY seq', (manifest['after_cursor'],)):
        row = json.loads(body)
        row.update(seq=seq, id=identity, at=stamp)
        events.append(row)
    current = [dict(id=identity, gate=gate, status=status, count=occurrences)
               for identity, gate, status, occurrences in db.execute('SELECT id,gate,review_status,occurrences FROM line_reviews')]
    policy = json.loads(db.execute('SELECT body FROM review_policy').fetchone()[0])
    db.close()
    traces = [json.loads(line) for line in Path(manifest['traces']).read_text().splitlines()]
    diagnostic = {row['trace_id'] for row in traces if row.get('operation_id')}
    diagnostic.update((trial.get('provenance') or {}).get('trace_id')
                      for trial in json.loads(Path(manifest['trials']).read_text()))
    trace_map = defaultdict(list)
    for row in traces:
        trace_map[row['trace_id']].append(row)
    sources, exact, parents = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in events:
        ctx = row.get('context') or {}; entry = ctx.get('entry') or {}
        source_key = (row['gate'], ctx.get('kind'), digest(row.get('source')))
        sources[source_key].append(row)
        exact[(*source_key, digest(row.get('candidate')))].append(row)
        parent = str(entry.get('sid') or entry.get('at') or '')
        if not parent:
            parent = digest(ctx.get('script_plain') or entry.get('script_plain') or ctx.get('script') or row.get('source'))
        parents[(ctx.get('kind'), parent)].append(row)
    def summary(rows):
        return {'events': len(rows), 'distinct_review_ids': len({r['id'] for r in rows}),
            'gates': count(rows, lambda r:r['gate']),
            'stages': count(rows, lambda r:str((r.get('context') or {}).get('stage') or '(unspecified)')),
            'kinds': count(rows, lambda r:str((r.get('context') or {}).get('kind') or '(unspecified)')),
            'dispositions': count(rows, lambda r:str(r.get('disposition') or '(unspecified)')),
            'technical': sum(bool(r.get('technical')) for r in rows),
            'reasons': dict(Counter(reason for r in rows for reason in set(r.get('reasons') or [])).most_common())}
    wires = []
    for row in traces:
        record = row['record']; details = record.get('details') or {}
        if record.get('kind') != 'model_wire_request':
            continue
        body = details.get('body') or {}
        messages = body.get('messages') or []
        text = '\n'.join(str(m.get('content') or '') for m in messages)
        wires.append({'seq': row['seq'], 'trace_id': row['trace_id'], 'at': row['at'],
            'call_id': details.get('call_id'), 'diagnostic': row['trace_id'] in diagnostic,
            'model': body.get('model'), 'think': body.get('think'), 'message_chars': len(text),
            'fluid': 'ORCHESTRATOR FLUID ACCEPTANCE' in text,
            'learning_revisions': sorted(set(int(x) for x in re.findall(r'learning revision (\d+)', text))),
            'num_predict': (body.get('options') or {}).get('num_predict'),
            'group_budget_chars': re.findall(r'Output budget for this group:\s*(\d+)\s*characters', text),
            'messages_sha256': digest(text)})
    examples = []
    for row in events:
        ctx = row.get('context') or {}; evaluation = row.get('evaluation') or {}
        trace_id = ctx.get('lab_trace_id')
        entry = ctx.get('entry') or {}
        compact_context = {key: ctx[key] for key in ('kind', 'stage', 'turn', 'marker', 'who',
            'speaker', 'lab_trace_id', 'source_original', 'script', 'script_plain', 'chunks',
            'world', 'crystal', 'verbatim', 'answering', 'caller_name', 'product') if key in ctx}
        compact_context['entry'] = {key:entry[key] for key in ('kind', 'prep_kind', 'at', 'sid',
            'seed', 'product', 'who', 'voice', 'caller_name', 'caller_voice') if key in entry}
        report = {**{key:row.get(key) for key in ('seq','id','at','gate','disposition','technical',
            'source','candidate','reasons','evaluation')}, 'context': compact_context,
                  'full_context_keys_in_private_snapshot': sorted(ctx),
                  'source_chars': len(row.get('source') or ''),
                  'candidate_chars': len(row.get('candidate') or ''),
                  'source_hash': digest(row.get('source')), 'candidate_hash': digest(row.get('candidate')),
                  'trace_records': len(trace_map.get(trace_id, [])),
                  'trace_diagnostic': trace_id in diagnostic,
                  'trace_wires': [w for w in wires if w['trace_id'] == trace_id],
                  'raw_faults': evaluation.get('machine_faults'),
                  'effective_faults': evaluation.get('faults'), 'editorial': evaluation.get('editorial')}
        examples.append(report)
    repeated = [{'gate': key[0], 'kind': key[1], 'source_hash': key[2],
                 'candidate_hash': key[3], 'events': len(group), 'sequences': [r['seq'] for r in group],
                 'stages': count(group, lambda r:str((r.get('context') or {}).get('stage'))),
                 'traces': sorted({str((r.get('context') or {}).get('lab_trace_id')) for r in group}),
                 'technical': sum(bool(r.get('technical')) for r in group)}
                for key, group in exact.items() if len(group)>1]
    result = {'status': 'analyzed_pending_manual_review', 'manifest': manifest,
        'policy_at_snapshot': policy, 'current_records': len(current),
        'current_status': count(current, lambda r:r['status']),
        'current_pending_gates': count([r for r in current if r['status']=='pending'], lambda r:r['gate']),
        'window': summary(events), 'cuts': summary([r for r in events if r.get('disposition')=='cut']),
        'refusals': summary([r for r in events if r.get('disposition')!='cut']),
        'distinct_gate_kind_source_groups': len(sources), 'distinct_source_candidate_pairs': len(exact),
        'distinct_parent_groups_approximate': len(parents),
        'source_families': [{'gate': key[0], 'kind': key[1], 'source_hash': key[2], 'events':len(group),
                             'candidates':len({digest(r.get('candidate')) for r in group}),
                             'sequences':[r['seq'] for r in group]} for key,group in sources.items()],
        'repeated_exact_pairs': sorted(repeated,key=lambda r:-r['events']),
        'all_new_events': examples, 'wire_requests': wires,
        'trace_kinds': count(traces, lambda r:r['record'].get('kind')),
        'diagnostic_traces_excluded': sorted(x for x in diagnostic if x in trace_map),
        'limits': ['Each database view is internally consistent; API state and trace capture are adjacent rather than atomic with rejection backup.',
                   'Refusal-only records do not measure a pass rate across all generated output.',
                   'Distinct normalized pairs identify retained wording, not necessarily distinct model calls. Multiple stages can report the same failed attempt.',
                   'Parent groups use retained sid/at where available, otherwise full-script hashes; identical script instances can merge in that fallback.',
                   'The private JSONL keeps complete actual trace messages/responses; the report preserves all rejection source/candidate/context/evaluation evidence.']}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({key:result[key] for key in ('current_status','window','cuts','distinct_gate_kind_source_groups','distinct_source_candidate_pairs','distinct_parent_groups_approximate')}))


def finish(output):
    data = json.loads(output.read_text())
    events = data['all_new_events']; start = min(row['at'] for row in events); end = max(row['at'] for row in events)
    diagnostic = set(data['diagnostic_traces_excluded'])
    traces = [json.loads(line) for line in Path(data['manifest']['traces']).read_text().splitlines()]
    production = [row for row in traces if start <= row['at'] <= end and row['trace_id'] not in diagnostic]
    calls = {}
    for row in production:
        record = row['record']; details = record.get('details') or {}; identity = details.get('call_id')
        if not identity or not record.get('kind', '').startswith('model_'):
            continue
        call = calls.setdefault(identity, {'id':identity, 'trace_id':row['trace_id']})
        if record['kind']=='model_request':call.update(request_at=row['at'], purpose=details.get('purpose'))
        if record['kind']=='model_wire_request':call.update(wire_at=row['at'])
        if record['kind']=='model_response':
            response=details.get('response') or {}
            call.update(response_at=row['at'], deferred=bool(response.get('deferred')),
                        finish_reason=response.get('done_reason'), prompt_tokens=response.get('prompt_eval_count'),
                        output_tokens=response.get('eval_count'), decode_seconds=response.get('eval_duration',0)/1e9,
                        response_chars=len(str((response.get('message') or {}).get('content') or '')))
        if record['kind']=='model_error':call.update(error_at=row['at'],error_type=details.get('error_type'))
    for call in calls.values():
        if 'wire_at' in call and 'request_at' in call:call['queue_seconds']=round(call['wire_at']-call['request_at'],3)
        if 'wire_at' in call and 'response_at' in call:call['wire_seconds']=round(call['response_at']-call['wire_at'],3)
    wires=[row for row in data['wire_requests'] if start<=row['at']<=end and not row['diagnostic']]
    tint=[row for row in events if row['gate']=='tint']
    data['actual_prompt_and_call_evidence']={
        'window_start':start,'window_end':end,'hours':round((end-start)/3600,3),
        'production_wire_requests':len(wires),'wire_learning_revisions':count(wires,lambda r:str(r['learning_revisions'])),
        'wire_fluid_instruction':sum(row['fluid'] for row in wires),
        'events_with_trace_pointer':sum(bool(row['context'].get('lab_trace_id')) for row in events),
        'events_with_captured_wire_in_scope':sum(bool(row['trace_wires']) for row in events),
        'gate_trace_pointers':{gate:sum(bool(row['context'].get('lab_trace_id')) for row in events if row['gate']==gate)
                              for gate in data['window']['gates']},
        'raw_grader_versions':count(tint,lambda r:str(r['evaluation'].get('version'))),
        'effective_editorial_modes':count(tint,lambda r:str((r.get('editorial') or {}).get('mode'))),
        'raw_faults':dict(Counter(f for row in tint for f in set(row.get('raw_faults') or [])).most_common()),
        'effective_faults':dict(Counter(f for row in tint for f in set(row.get('effective_faults') or [])).most_common()),
        'unique_model_request_ids_in_window':len(calls),
        'admission_deferred_responses':sum(row.get('deferred',False) for row in calls.values()),
        'completed_wire_responses':sum('wire_at' in row and 'response_at' in row and not row.get('deferred') for row in calls.values()),
        'calls':list(calls.values()),
        'denominator_limit':'Calls include successful neighbours and multiple stages in each scope. They are not one-to-one with failed candidates or a generation success-rate denominator.'}
    db=sqlite3.connect(Path(data['manifest']['snapshot']).as_uri()+'?mode=ro',uri=True)
    churn={}
    for seq,body in db.execute('SELECT seq,body FROM review_events WHERE seq>? ORDER BY seq',(data['manifest']['after_cursor'],)):
        row=json.loads(body)
        if row.get('source')!='Just get to the point, man. We got records to spin.':continue
        ctx=row.get('context') or {};entry=ctx.get('entry') or {};parent=str(entry.get('at') or entry.get('sid') or '')
        group=churn.setdefault(parent,{'events':0,'first_seq':seq,'first_at':row['at'],'traces':set(),'candidates':set()})
        group['events']+=1;group.update(last_seq=seq,last_at=row['at'])
        group['traces'].add(ctx.get('lab_trace_id'));group['candidates'].add(digest(row.get('candidate')))
        group['latest_entry']={key:entry.get(key) for key in ('at','sid','tint_fails','tint_tried','use','off_brief','tint_lesson')}
        group['latest_coverage']=(entry.get('tint') or {}).get('coverage')
        group['latest_call_quality']=(entry.get('call') or {}).get('quality')
    db.close()
    for group in churn.values():group['trace_count']=len(group.pop('traces'));group['candidate_variants']=len(group.pop('candidates'))
    data['chronic_caller_parent_evidence']=churn
    data['manual_findings']=[
        {'mechanism':'lost_bar_boundaries','sequences':[5323,5426,5428,5431],
         'finding':'Actual model responses use slash-delimited bars; retained candidates flatten these to commas. Short line endpoints can cease to be bars before grading. The separately owned handler repair preserves explicit boundaries without changing the rhyme requirement.'},
        {'mechanism':'incomplete_tint_not_bounded_by_completed_strikes','sequences':[3913,5259,5260,5323],
         'finding':'439 chronic-source events belong to one parent over6.44h and115 trace scopes. Latest failed coverage is20/21 with tint_fails3. ensure_entry_tinted returns on incomplete coverage; retire_rejected_call_entry checks only a complete active script_tinted. Therefore completion-only strikes never cap a last-line repair loop. Plain call approval must be preserved; rotate or adapt unsuccessful turn repairs while retaining accepted work.'},
        {'mechanism':'control_result_treated_as_spoken_draft','sequences':[3589,4680],
         'finding':'14 NONE fragments are a sentinel explicitly requested by track reception, but generic ask_model checks prose punctuation first. Use an explicit caller result contract for NONE rather than relaxing spoken-line validation.'},
        {'mechanism':'repair_echo_cleaned_after_generic_trimming','sequences':[3547,4928],
         'finding':'10 copies of a punctuation-repair instruction prefix were retained by draft_trimming while the unpunctuated actual source tail was removed. speakbox_harvest cleans exact instruction echoes only after ask_model trims. Clean the specific raw repair result before prose handling and retain raw provenance.'},
        {'mechanism':'short_english_ambiguous_foreign_token','sequences':[4046,4047,4048,4049,4050,4051,4052,4975],
         'finding':'Seven Yo greetings and Hero fail, fall, die trying are intelligible English. looks_english treats yo/die as foreign markers while its English-function list misses contractions/content verbs. Preserve true foreign-language tests when correcting this narrow ambiguity.'},
        {'mechanism':'wrong_ad_source_not_a_threshold_problem','sequences':[4899,5039,5305,5321,5361],
         'finding':'These ads discuss phone interruptions, static, GPU heat or general systems and omit the required product/sale. Product-aware brief refusal is protective. The upstream draft must prioritize its product over unrelated station/style context.'},
        {'mechanism':'blend_discards_protected_material','sequences':[5397],
         'finding':'Latest blend drops the medical-news discussion and rewrites a protected passage into a generic people/systems exchange. All30 blend records are rejected proposals, not cuts of the retained originals. Turn-count/passage/length failures should remain protective.'},
        {'mechanism':'semantic_protection_still_needed','sequences':[4310,5325,4899,5039],
         'finding':'Dale rewrite adds no brakes/certainty; manager rewrite invents how-we-act as the explanation. The latter passed the old semantic subcheck, so grade success alone is insufficient. Separate quantity-classifier ambiguities (impersonal make one wonder and another one/one more) do not justify approving otherwise off-topic copy.'},
        {'mechanism':'non_tint_trace_gap','sequences':[4680,4928,5260,5433],
         'finding':'None of the draft_fragment, draft_trimming, segment_brief, call_contract, radio_draft or blend events in this window retains a lab_trace_id. Their full wording and reports exist, but exact prompt causation cannot be reconstructed by fuzzy temporal matching.'}]
    data['status']='complete_read_only_audit'
    data['completed_at']=time.time()
    data['frozen_evaluation_cases']='docs/rejection-learning-followup-cases.json'
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(json.dumps({'status':data['status'],'calls':len(calls),'wires':len(wires),'chronic_parents':len(churn)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--finish', action='store_true')
    parser.add_argument('--after', type=int, default=3537)
    parser.add_argument('--output', type=Path, default=Path('docs/rejection-learning-followup-audit.json'))
    args = parser.parse_args()
    if args.capture:
        capture(args.output, args.after)
    elif args.finish:
        finish(args.output)
    else:
        analyze(args.output)
