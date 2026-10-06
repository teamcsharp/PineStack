"""Read-only caller diversity audit. Run inside the station container.

Uses transactions on each owned database; never changes station state.
Event counts measure retained occurrences. Row counts measure unique reports;
row lifetime occurrences are deliberately kept separate from window counts.
"""
from __future__ import annotations
import collections
import datetime
import json
import sqlite3
import time
import zlib
from pathlib import Path


def counter(values):
    return dict(collections.Counter(values).most_common())


def db(name):
    connection = sqlite3.connect('file:/app/data/' + name + '?mode=ro', uri=True, timeout=5)
    connection.execute('BEGIN')
    return connection


def audit():
    now = time.time()
    result = {'schema': 'caller-diversity-audit/1', 'at': now,
              'at_utc': datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(),
              'limitations': ['Database transactions are individually consistent, not atomic across stores.',
                             'Retained events cover a shorter period than cumulative unique reports.',
                             'Generated/compliant is not proof of recording, admission or broadcast.',
                             'Historical row occurrence totals are lifetime totals, not window rejection rates.']}
    c = db('line_review.sqlite3')
    events = [(s, at, json.loads(raw)) for s, at, raw in c.execute('SELECT seq,at,body FROM review_events ORDER BY seq')]
    result['retained_events'] = {'count': len(events), 'first_at': events[0][1] if events else None,
                                 'last_at': events[-1][1] if events else None}
    reviews = [(rid, gate, occurrences, first, last, json.loads(reasons), json.loads(ctx), json.loads(ev), source)
               for rid, gate, occurrences, first, last, reasons, ctx, ev, source in c.execute(
                   'SELECT id,gate,occurrences,first_at,last_at,reasons,context,evaluation,source FROM line_reviews')]
    for hours in (24, 72, 168):
        selected = [(s, at, b) for s, at, b in events if at >= now-hours*3600]
        unique = [r for r in reviews if r[4] >= now-hours*3600]
        repetitions = [(s, at, b) for s, at, b in selected if b.get('gate') == 'repetition']
        result[str(hours)+'h'] = {
            'events_by_gate': counter(b.get('gate') for s, at, b in selected),
            'unique_reports_by_gate': counter(r[1] for r in unique),
            'call_contract_unique_reasons': counter(f for r in unique if r[1]=='call_contract' for f in r[5]),
            'repetition_top_lines': collections.Counter(b.get('source') for s, at, b in repetitions).most_common(12),
            'repetition_by_speaker': counter((b.get('context') or {}).get('who') for s, at, b in repetitions),
            'radio_draft_reasons': counter(f for s, at, b in selected if b.get('gate')=='radio_draft' for f in b.get('reasons',[]))}
    calls = [r for r in reviews if r[1]=='call_contract']
    similar = [r for r in calls if any('similar to a stored call' in f for f in r[5])]
    result['historical_call_contract'] = {
        'unique_reports': len(calls), 'lifetime_occurrences': sum(r[2] for r in calls),
        'first_at': min((r[3] for r in calls),default=None), 'last_at': max((r[4] for r in calls),default=None),
        'reasons_unique': counter(f for r in calls for f in r[5]),
        'similarity_unique': len(similar), 'similarity_lifetime_occurrences': sum(r[2] for r in similar),
        'recent_similarity_samples': []}
    for r in sorted(similar,key=lambda r:r[4],reverse=True)[:12]:
        ev=r[7];flow=ev.get('flow') or ev
        result['historical_call_contract']['recent_similarity_samples'].append({
            'id':r[0],'last_at':r[4],'lifetime_occurrences':r[2],'reasons':r[5],
            'context_kind':r[6].get('kind'),'stage':r[6].get('stage'),
            'entry_id':(r[6].get('entry') or {}).get('id'),
            'novelty':flow.get('novelty') or ev.get('novelty'),
            'caller_excerpt':r[8][:1000]})
    classifications=collections.Counter(); occurrences=collections.Counter()
    for r in similar:
        ev=r[7];flow=ev.get('flow') or ev; nv=flow.get('novelty') or {}
        kind=('empty_script' if not r[8].strip() else 'exact_duplicate' if nv.get('exact') else
              'structural_similarity' if nv.get('matched_id') and nv.get('similarity',0)>=nv.get('limit',0.48) else 'other_or_missing_evidence')
        classifications[kind]+=1; occurrences[kind]+=r[2]
    result['historical_call_contract']['similarity_classification_unique']=dict(classifications)
    result['historical_call_contract']['similarity_classification_lifetime']=dict(occurrences)
    c.close()
    c=db('system3.sqlite3')
    settings=dict(c.execute('SELECT key,value FROM settings'))
    result['system3_settings']=json.loads(settings.get('settings','{}'))
    config=json.loads(zlib.decompress(c.execute('SELECT body FROM configs WHERE hash=?',(settings['config'],)).fetchone()[0]))
    result['system3_config_hash']=settings['config']
    result['caller_structure']=(config.get('structures') or {}).get('caller')
    relevant={'CALLARC','CALLSHIFT','RESOLVE','WRAP','ANGLE','RS','ES','CTS'}
    result['relevant_tables']=[{'id':t['id'],'family':t.get('family'),'enabled':t.get('enabled',True),
        'categories':[{'id':cat.get('id'),'weight':cat.get('weight'),
                       'items':[{'id':i.get('id'),'label':i.get('label'),'weight':i.get('weight')} for i in cat.get('items',[])]}
                       for cat in t.get('categories',[])]} for t in config.get('tables',[]) if t.get('family') in relevant]
    conversations=[(cid,at,status,verdict,json.loads(summary),json.loads(zlib.decompress(body)))
        for cid,at,status,verdict,summary,body in c.execute(
        "SELECT id,created,status,verdict,summary,body FROM conversations WHERE road='caller' AND created>=? ORDER BY created",
        (now-72*3600,))]
    for hours in (24,72):
        subset=[r for r in conversations if r[1]>=now-hours*3600]
        generated=[r for r in subset if r[2]=='generated']
        gates=[r[4].get('gate') or {} for r in generated]
        turns=[t for r in generated for t in r[5].get('turns',[]) if t.get('text')]
        result[str(hours)+'h']['system3_call_outcomes']={
            'count':len(subset),'status':counter(r[2] for r in subset),
            'generated_verdicts':counter(r[3] for r in generated),
            'withheld_reasons':counter((r[5].get('withheld') or {}).get('why') for r in subset if r[2]=='withheld'),
            'generated_gate_totals':{key:sum(int(g.get(key) or 0) for g in gates) for key in ['caught','rewritten','dropped','trimmed','visits','in_chain']},
            'generated_turns':len(turns),
            'top_answer_lines':collections.Counter(t.get('text') for t in turns if t.get('step')=='answer').most_common(8),
            'top_introduction_lines':collections.Counter(t.get('text') for t in turns if t.get('step')=='introduce').most_common(8),
            'premise_topics':counter((r[5].get('inputs',{}).get('call') or {}).get('topic') for r in generated),
            'speakerbox_material_calls':sum(bool((r[5].get('inputs',{}).get('call') or {}).get('speakerbox')) for r in generated),
            'topic_database_plan_calls':sum(bool(r[5].get('topic_plan')) for r in generated),
            'topic_database_option_ids':counter((r[5].get('topic_plan') or {}).get('id') or '(none)' for r in generated),
            'detour_sources':counter((r[5].get('callshift') or {}).get('source') or '(none)' for r in generated),
            'emotion_categories':counter(dec.get('category') for r in generated for t in r[5].get('turns',[]) for dec in t.get('decisions',[]) if dec.get('family')=='ES'),
            'cts_decision_events':c.execute("SELECT count(*) FROM events e JOIN conversations c ON c.id=e.conversation_id WHERE c.road='caller' AND c.status='generated' AND c.created>=? AND e.family='CTS'",(now-hours*3600,)).fetchone()[0],
            'arc_choices':counter((r[5].get('callarc') or {}).get('arc') for r in generated),
            'gate_rules':counter(t.get('rule') or t.get('why') for r in generated for t in (r[5].get('turn_gate') or {}).get('turns',[])),
            'withheld_classes':counter('writer_deferred' if 'writer was deferred' in str((r[5].get('withheld') or {}).get('why')) else 'copy_gate' if 'copy gate held' in str((r[5].get('withheld') or {}).get('why')) else 'other' for r in subset if r[2]=='withheld'),
            'conversations_with_script_receipts':c.execute("SELECT count(distinct c.id) FROM conversations c JOIN lines l ON l.conversation_id=c.id WHERE c.road='caller' AND c.created>=? AND l.block IS NOT NULL",(now-hours*3600,)).fetchone()[0]}
    result['recent_withheld']=[{'id':r[0],'created':r[1],'withheld':r[5].get('withheld')} for r in conversations if r[2]=='withheld'][-10:]
    result['gate_sample']=[{'id':r[0],'validation':r[5].get('validation'),'gate':r[5].get('turn_gate')} for r in conversations if r[2]=='generated'][-3:]
    c.close()
    return result

if __name__=='__main__':
    print(json.dumps(audit(),ensure_ascii=True,indent=2))
