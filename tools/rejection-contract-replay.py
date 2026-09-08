"""Replay retained semantic evidence without models, station mutation or grading journals."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crystal_contract import compare_contract


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def transitions(rows):
    return dict(Counter(row['transition'] for row in rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='')
    parser.add_argument('--output', default=str(ROOT / 'docs' / 'rejection-contract-replay.json'))
    args = parser.parse_args()
    data = os.environ.get('SPARK_AGENT_DATA_DIR', '')
    if not data or Path(data).resolve() == (ROOT / 'data').resolve():
        raise SystemExit('Set SPARK_AGENT_DATA_DIR to an isolated temporary directory before importing station constants.')
    import app
    audit = json.loads((ROOT / 'docs' / 'rejection-corpus-audit.json').read_text(encoding='utf-8'))
    snapshot = Path(args.snapshot or audit['private_snapshot_path'])
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        raw = []
        for seq, review_id, at, body in db.execute('SELECT seq,review_id,at,body FROM review_events ORDER BY seq'):
            row = json.loads(body)
            if row.get('gate') == 'tint' and str(row.get('candidate') or '').strip():
                raw.append({**row, 'id': review_id, 'seq': seq, 'at': at})
    stops = frozenset(app._TINT_EVAL_STOP)
    # Freeze the union of passages retained alongside all selected cases.
    # It is an approximation to the live full crystal vocabulary, not a
    # fresh retrieval or a read of today's mutable crystal configuration.
    vocabulary = set()
    passage_count = 0
    for row in raw:
        for chunk in (row.get('context') or {}).get('chunks') or []:
            text = chunk.get('text') if isinstance(chunk, dict) else ''
            if text:
                passage_count += 1
                vocabulary.update(word for word in re.findall(r"[a-z0-9']+", text.lower())
                                  if len(word) > 2 and word not in stops)
    vocabulary = frozenset(vocabulary)
    results, details = [], {}
    for row in raw:
        source, candidate = str(row.get('source') or ''), str(row.get('candidate') or '')
        evaluation, context = row.get('evaluation') or {}, row.get('context') or {}
        old = evaluation.get('semantic') or {}
        force = evaluation.get('strength')
        inferred_force = force is None
        force = float(force if force is not None else .88)
        floor = .2 if force >= .75 else .35 if force >= .45 else .5
        new = compare_contract(source, candidate, stops, vocabulary, anchor_floor=floor)
        old_ok = old.get('ok') if isinstance(old.get('ok'), bool) else None
        transition = ('unrecorded_semantic' if old_ok is None else
                      'newly_true' if not old_ok and new['ok'] else
                      'newly_false' if old_ok and not new['ok'] else
                      'retained_true' if old_ok else 'retained_false')
        pair_hash = digest(json.dumps([source, candidate], ensure_ascii=False))
        item = {'id': row['id'], 'seq': row['seq'], 'pair_sha256': pair_hash,
                'kind': context.get('kind') or '', 'stage': context.get('stage') or '',
                'force': force, 'force_assumed': inferred_force, 'anchor_floor': floor,
                'source_chars': len(source), 'candidate_chars': len(candidate),
                'old_semantic': old, 'new_contract': new, 'transition': transition,
                'technical': bool(row.get('technical')), 'stored_reasons': row.get('reasons') or []}
        results.append(item)
        details[row['seq']] = {'source': source, 'candidate': candidate}
    pairs = {}
    for row in results:
        pair = pairs.setdefault(row['pair_sha256'], {'latest': row, 'count': 0, 'old_states': set()})
        pair['latest'] = row
        pair['count'] += 1
        pair['old_states'].add(row['old_semantic'].get('ok'))
    latest = [pair['latest'] for pair in pairs.values()]
    worsened = [row for row in results if row['transition'] == 'newly_false']
    improved = [row for row in results if row['transition'] == 'newly_true']
    def failure_parts(row):
        new = row['new_contract']
        return [key for key in ('entities', 'question', 'negation') if not new[key]] + (
            ['anchor_recall'] if new['anchor_recall'] < row['anchor_floor'] else [])
    examples = []
    chosen = set()
    for category, rows in [('newly_false', worsened), ('newly_true', improved)]:
        grouped = {}
        for row in rows:
            key = (row['pair_sha256'], tuple(failure_parts(row)))
            grouped.setdefault(key, row)
        for row in list(grouped.values())[:60]:
            if row['seq'] not in chosen:
                examples.append({**row, **details[row['seq']]})
                chosen.add(row['seq'])
    report = {'at_utc': datetime.now(timezone.utc).isoformat(),
        'snapshot': str(snapshot), 'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'contract_sha256': hashlib.sha256((ROOT / 'crystal_contract.py').read_bytes()).hexdigest(),
        'scope': 'All retained nonempty tint candidate occurrences in the fixed SQLite snapshot.',
        'method': 'Compare stored semantic.ok with pure compare_contract using recorded strength floors; no model, audio or production journal calls.',
        'vocabulary': {'basis': 'Frozen union of retained context.chunks text over selected occurrences; approximate live full crystal vocabulary.',
                       'words': len(vocabulary), 'passage_occurrences': passage_count,
                       'sha256': digest('\n'.join(sorted(vocabulary)))},
        'events': {'count': len(results), 'transitions': transitions(results),
                   'newly_true_kinds': dict(Counter(row['kind'] for row in improved)),
                   'newly_true_changed_old_components': dict(Counter(key for row in improved
                       for key in ('entities', 'question', 'negation') if not row['old_semantic'].get(key))),
                   'new_refusal_components': dict(Counter(part for row in worsened for part in failure_parts(row))),
                   'new_refusal_missing_names': dict(Counter(name['normalized'] for row in worsened for name in row['new_contract']['missing_names'])),
                   'new_refusal_number_changes': sum(bool(row['new_contract']['missing_numbers'] or row['new_contract']['added_numbers']) for row in worsened)},
        'distinct_pairs': {'count': len(pairs), 'basis': 'Exact source/candidate pair; use latest retained occurrence for one transition per pair.',
                           'transitions': transitions(latest),
                           'pairs_with_inconsistent_stored_semantic': sum(len(pair['old_states']) > 1 for pair in pairs.values())},
        'noncaller_subset': {'basis': 'Exclude context.kind=caller to avoid comparing its additional caller-specific gate with the pure contract; empty kind remains explicitly included.',
                             'events': len([row for row in results if row['kind'] != 'caller']),
                             'transitions': transitions([row for row in results if row['kind'] != 'caller']),
                             'distinct_pairs': len([row for row in latest if row['kind'] != 'caller']),
                             'distinct_pair_transitions': transitions([row for row in latest if row['kind'] != 'caller'])},
        'limitations': ['This compares a semantic subcheck, not the complete current or historical live acceptance grade.',
                       'Stored caller semantic.ok can include additional call-contract checks which pure compare_contract does not run.',
                       'Stored name inference used a different full crystal vocabulary; the frozen retained-passage union is an explicit approximation.',
                       'Cases without stored semantic/strength stay labeled unrecorded_semantic/force_assumed, not counted as fixed refusals.',
                       'A newly true contract is not proof of semantic equivalence or permission to publish; rhyme, transformation, copying, roles and technical gates still apply.'],
        'rows': results, 'transition_examples': examples,
        'manual_new_refusal_review': [
            {'seqs': [586, 1338, 1353, 1378, 2243, 2558, 2908],
             'finding': 'False numeric obligations: one more symptom, ordinal second/third one, which one, demonstrative this one, and no one are pronominal or indefinite, not explicit item counts.',
             'status': 'Corrected in the replayed contract with dedicated regressions; remaining polarity or content faults still stand.',
             'action': 'Preserve explicit digits and actual item counts. This classification does not approve the complete candidate.'},
            {'seqs': [2383],
             'finding': 'Malformed source Is we’re getting closer is spuriously inferred to be a question.',
             'status': 'Corrected in the replayed contract with a dedicated regression.',
             'action': 'Retain explicit question-mark obligations; malformed double auxiliaries do not prove an interrogative.'},
            {'seqs': [209, 216, 586, 1869, 2243],
             'finding': 'Newly recognized contractions create polarity deltas against lexical paraphrases such as couldn’t remember→forget, don’t feel like→skip, and instead of a symptom→ain’t a symptom.',
             'action': 'Inspect in context; do not add universal synonym exceptions. Normalized contraction detection fixes missed polarity but is not a semantic entailment check.'},
        ]}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('events', 'distinct_pairs', 'noncaller_subset', 'vocabulary')}))


if __name__ == '__main__':
    main()
