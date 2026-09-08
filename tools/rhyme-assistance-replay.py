"""Read retained events and replay exact tint evidence without model/actions.

Runs inside spark-agent. Imports the app only after assigning an isolated data
directory; the live review DB is opened with SQLite mode=ro and one snapshot.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest import mock


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def verdict(report):
    return {'accepted':report.get('ok') is True,
        'raw':report.get('machine_ok',report.get('ok')) is True,
        'semantic':(report.get('semantic') or {}).get('ok') is True,
        'rhyme':((report.get('rhyme') or {}).get('rap') or {}).get('ok') is True,
        'advisory':(report.get('editorial') or {}).get('accepted_with_advisories') is True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',default='/app/data/line_review.sqlite3')
    parser.add_argument('--after',type=int,default=5433)
    parser.add_argument('--through',type=int,default=0,help='Optional fixed snapshot cursor for a reproducible replay')
    parser.add_argument('--output',default='/app/docs/rhyme-assistance-rejection-replay.json')
    parser.add_argument('--vocabulary',default='/app/docs/rejection-learning-baseline-v8-crossgrade-vocabulary.json')
    args=parser.parse_args()
    live=sqlite3.connect('file:'+args.database+'?mode=ro',uri=True)
    live.row_factory=sqlite3.Row;live.execute('BEGIN')
    cursor=live.execute('SELECT MAX(seq) FROM review_events').fetchone()[0]
    if args.through:cursor=min(cursor,args.through)
    scopes={name:{'events':0,'gates':Counter(),'reasons':Counter(),'stored_versions':Counter()}
            for name in ('all_history','since_5433')}
    rows=[]
    for raw in live.execute('SELECT seq,review_id,at,body FROM review_events WHERE seq<=? ORDER BY seq',(cursor,)):
        body=json.loads(raw['body']);row={**body,'seq':raw['seq'],'review_id':raw['review_id'],'at':raw['at']}
        groups=['all_history']+(['since_5433'] if raw['seq']>args.after else [])
        for group in groups:
            s=scopes[group];s['events']+=1;s['gates'][body.get('gate','unknown')]+=1
            s['reasons'].update(str(x) for x in body.get('reasons') or [])
            if body.get('gate')=='tint':s['stored_versions'][str((body.get('evaluation') or {}).get('version'))]+=1
        if raw['seq']>args.after:rows.append(row)
    current={}
    for row in live.execute("SELECT * FROM line_reviews WHERE gate='tint' AND review_status='pending' AND technical=0"):
        current[row['id']]=dict(row)
    live.rollback();live.close()
    frozen=json.loads(Path(args.vocabulary).read_text())
    vocabulary=set(frozen['words'])
    os.environ['SPARK_AGENT_DATA_DIR']=tempfile.mkdtemp(prefix='rhyme-assistance-replay-')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import app
    for row in rows:
        for chunk in (row.get('context') or {}).get('chunks') or []:
            vocabulary.update(app._tint_content(chunk.get('text','') if isinstance(chunk,dict) else str(chunk)))
    token=app._REJECTION_LAB_PREVIEW.set(True)
    variants={};pairs=defaultdict(list);pair_texts={};events=[];changes=Counter()
    try:
        with ExitStack() as stack:
            for name,value in [('_crystal_vocab',mock.Mock(return_value=frozenset(vocabulary))),
                ('crystal_acceptance_mode',mock.Mock(return_value='fluid')),
                ('line_review_capture',mock.Mock(side_effect=AssertionError('No live review writes'))),
                ('ask_model',mock.AsyncMock(side_effect=AssertionError('No model calls'))),
                ('_embed_texts',mock.AsyncMock(side_effect=AssertionError('No embedding calls')))]:
                stack.enter_context(mock.patch.object(app,name,value))
            for row in rows:
                original=row.get('evaluation') or {};context=row.get('context') or {}
                source=str(row.get('source') or '');candidate=str(row.get('candidate') or '')
                pair=digest([source,candidate]);pairs[pair].append(row['seq'])
                pair_texts[pair]={'source':source,'candidate':candidate}
                event={'seq':row['seq'],'review_id':row['review_id'],'gate':row.get('gate'),
                    'pair_id':pair,'stored_version':original.get('version'),'reasons':row.get('reasons') or [],
                    'stored_evaluation':original,'stage':context.get('stage'),
                    'source_trace':{'trace_id':context.get('lab_trace_id'),'cut_step':context.get('lab_cut_step')}}
                fault_tags=[]
                if not candidate.strip():fault_tags.append('no_candidate')
                if source.strip()=='NONE':fault_tags.append('sentinel_as_content')
                if source.strip()==candidate.strip() and source.strip():fault_tags.append('unchanged_source_candidate')
                if (original.get('semantic') or {}).get('missing_names'):fault_tags.append('name_heuristic_or_omitted_name')
                if (original.get('semantic') or {}).get('question') is False:fault_tags.append('question_role')
                if (original.get('semantic') or {}).get('negation') is False:fault_tags.append('negative_constraint')
                if ((original.get('rhyme') or {}).get('rap') or {}).get('ok') is False:fault_tags.append('no_rap_evidence')
                if (original.get('transformation') or {}).get('ok') is False:fault_tags.append('style_transformation')
                event['diagnostic_categories']=fault_tags
                if (row.get('gate')!='tint' or not source.strip() or not candidate.strip()
                    or not isinstance(original.get('strength'),(float,int)) or not context.get('chunks')):
                    event['replay']='not_comparable_tint_evidence';events.append(event);continue
                grade=original.get('grade') or 'meaning'
                key=digest([pair,context.get('kind'),context.get('answering'),context['chunks'],original['strength'],grade])
                if key not in variants:
                    with mock.patch.object(app,'crystal_grade_strict',return_value=grade=='strict'):
                        made=app.tint_evaluate(source,candidate,context['chunks'],context.get('answering') or '',
                            original['strength'],context.get('kind') or '')
                    variants[key]={'pair_id':pair,'source':source,'candidate':candidate,
                        'kind':context.get('kind'),'force':original['strength'],'grade':grade,
                        'answering':context.get('answering') or '', 'chunks':context['chunks'],
                        'current_evaluation':made,'current_verdict':verdict(made),'seqs':[]}
                variants[key]['seqs'].append(row['seq'])
                old,new=verdict(original),variants[key]['current_verdict']
                event.update(replay='graded',variant_id=key,stored_verdict=old,current_verdict=new)
                changes['graded_events']+=1
                for keyname in old:
                    changes['stored_'+keyname]+=old[keyname];changes['current_'+keyname]+=new[keyname]
                event['newly_accepted']=not old['accepted'] and new['accepted']
                event['newly_held']=old['accepted'] and not new['accepted']
                changes['newly_accepted']+=event['newly_accepted'];changes['newly_held']+=event['newly_held']
                events.append(event)
    finally:app._REJECTION_LAB_PREVIEW.reset(token)
    curated={5711:'A real short terminal rhyme was previously missed; keep the attempted search and do not give thin air new agency.',
             5753:'A gerund was mistaken for a name; retain reclaiming and the question, without adding an unsupported affliction.',
             5750:'A discourse tag is optional; express the same suspicion as suspicion, without inventing a new transaction.',
             5735:'Repeated unchanged/man-tag attempts need fresh source-grounded rhyme landings, not pan/space filler.',
             5709:'Source spelling/gerund and negation are difficult; preserve explicit not-knowing and do not invent a cost.',
             5714:'Keep trying rather than asserting accomplished action; frame shapelessness as the supplied metaphor.'}
    plans=[]
    for seq,why in curated.items():
        row=next((x for x in rows if x['seq']==seq),None)
        held=current.get(row['review_id']) if row else None
        if not held:continue
        plans.append({'audit_seq':seq,'review_id':held['id'],'event_seq':held['latest_seq'],
            'source':held['source'],'candidate':held['candidate'],'source_sha256':hashlib.sha256(held['source'].encode()).hexdigest(),
            'context':json.loads(held['context']),'evaluation':json.loads(held['evaluation']),
            'why_selected':why,'before_post':'Fetch pinned live occurrence and verify source/event/status again.',
            'instructions':'','reasoning':False,'request_id':'rhyme-assist-v5-'+held['id']+'-'+str(held['latest_seq'])})
    output={'captured_at':time.time(),'cursor':cursor,'after':args.after,'read_only':True,'model_requests':0,
        'grader_version':app.CRYSTAL_GRADER_VERSION,'historical_categories':scopes,
        'summary':dict(changes),'graded_context_variants':len(variants),
        'unique_graded_pairs':len({r['pair_id'] for r in variants.values()}),
        'new_unique_pairs_all_gates':len(pairs),
        'vocabulary':{'base_file':args.vocabulary,'base_sha256':hashlib.sha256(Path(args.vocabulary).read_bytes()).hexdigest(),
            'words':len(vocabulary),'added_current_chunks':True,'sha256':digest(sorted(vocabulary))},
        'limitations':['All-history categories count retained events, including repeat/regrade records, not independent model attempts.',
            'New events span older grader versions; exact stored grades are kept separately from current counterfactual grades.',
            'Original live vocabulary-cache completeness is unknown. Replay freezes the retained full DOOM vocabulary plus exact new style passages.',
            'Only tint rows with nonempty source/candidate, retained force and style passages are regraded; other gates remain explicitly classified.',
            'Any new acceptance is a machine counterfactual, not proof of faithful wording or improved generation.'],
        'events':events,'variants':variants,
        'pairs':[{'pair_id':key,**pair_texts[key],'seqs':value,'occurrences':len(value)} for key,value in pairs.items()]}
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    planpath=Path(args.output).with_name('rhyme-assistance-live-plan.json')
    planpath.write_text(json.dumps({'prepared_only':True,'model_requests':0,'prompt_version':5,'grader_version':9,
        'case_count':len(plans),'cases':plans,'limits':'Run at most these six after root deployment approval; no applies/votes/settings/playback. These are debugging cases, not a blind holdout.'},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':args.output,'cursor':cursor,'summary':changes,'variants':len(variants),
        'unique_pairs':output['unique_graded_pairs'],'prepared_cases':len(plans)},indent=2))


if __name__=='__main__':main()
