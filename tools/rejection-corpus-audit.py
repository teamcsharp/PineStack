"""Audit every retained rejection from a consistent, read-only SQLite copy."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time


def normalize(text):
    return ' '.join(str(text or '').split())


def digest(text):
    return hashlib.sha256(normalize(text).encode()).hexdigest()[:24]


def counts(rows, key):
    return dict(Counter(key(row) for row in rows).most_common())


def features(row):
    source, candidate = row.get('source') or '', row.get('candidate') or ''
    flags = []
    if len(source) > 1000:
        flags.append('source_over_1000_chars')
    if source and normalize(source) == normalize(candidate):
        flags.append('source_equals_candidate')
    if not candidate.strip():
        flags.append('empty_candidate')
    if '\ufffd' in source or any(s in source for s in ('â€™', 'â€œ', 'Ã©', 'ðŸ')):
        flags.append('source_encoding_artifact')
    if re.search(r'\b(\w+)(?:\s+\1){3,}\b', source, re.I):
        flags.append('source_word_repeated_4plus')
    if re.match(r'\s*(?:SPEAKER|SPEAKER_[A-Z0-9]+|HOST|CALLER)\s*:', source, re.I):
        flags.append('source_descriptive_label')
    return flags


def example(row):
    context = row.get('context') or {}
    return {'id': row['id'], 'seq': row.get('seq'), 'at': row.get('at'),
        'gate': row.get('gate'), 'stage': context.get('stage'), 'kind': context.get('kind'),
        'disposition': row.get('disposition'), 'technical': bool(row.get('technical')),
        'source_chars': len(row.get('source') or ''), 'candidate_chars': len(row.get('candidate') or ''),
        'source': (row.get('source') or '')[:1800], 'candidate': (row.get('candidate') or '')[:1800],
        'excerpts_complete': max(len(row.get('source') or ''), len(row.get('candidate') or '')) <= 1800,
        'reasons': row.get('reasons'), 'evaluation': row.get('evaluation'),
        'context_keys': sorted(context), 'flags': features(row),
        'lab_trace_id': context.get('lab_trace_id')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='/app/data/line_review.sqlite3')
    parser.add_argument('--output', default='docs/rejection-corpus-audit.json')
    args = parser.parse_args()
    stamp = time.time()
    snapshot_path = Path(tempfile.mkdtemp(prefix='pine-rejection-corpus-')) / 'snapshot.sqlite3'
    source = sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
    destination = sqlite3.connect(snapshot_path)
    source.backup(destination)
    source.close()
    destination.row_factory = sqlite3.Row
    current = []
    for raw in destination.execute('SELECT * FROM line_reviews ORDER BY latest_seq'):
        row = dict(raw)
        for key in ('reasons', 'context', 'evaluation', 'decision', 'effect'):
            row[key] = json.loads(row[key])
        row.update(seq=row['latest_seq'], at=row['last_at'])
        current.append(row)
    events = []
    for raw in destination.execute('SELECT seq,review_id,at,body FROM review_events ORDER BY seq'):
        row = json.loads(raw['body'])
        row.update(seq=raw['seq'], id=raw['review_id'], at=raw['at'])
        events.append(row)
    decisions = [json.loads(raw[0]) for raw in destination.execute('SELECT body FROM review_decisions')]
    policy = json.loads(destination.execute('SELECT body FROM review_policy').fetchone()[0])
    instances = [json.loads(raw[0]) for raw in destination.execute('SELECT body FROM review_instances')]
    destination.close()
    selected = {}
    def choose(label, candidates, limit=2):
        rows = list(candidates)
        for row in rows[-limit:]:
            selected.setdefault(row['seq'], {'selection_reasons': [], **example(row)})['selection_reasons'].append(label)
    for gate in {r['gate'] for r in events}:
        choose('gate:' + gate, (r for r in events if r['gate'] == gate))
    for stage in {str((r.get('context') or {}).get('stage') or '(unspecified)') for r in events}:
        choose('stage:' + stage, (r for r in events if str((r.get('context') or {}).get('stage') or '(unspecified)') == stage), 1)
    for flag in {f for r in events for f in features(r)}:
        choose('feature:' + flag, sorted((r for r in events if flag in features(r)), key=lambda r:len(r.get('source') or '')), 2)
    reason_counts = Counter(reason for row in events for reason in set(row.get('reasons') or []))
    for reason, _ in reason_counts.most_common(12):
        choose('reason:' + reason, (r for r in events if reason in (r.get('reasons') or [])), 1)
    families = defaultdict(list)
    for row in events:
        context = row.get('context') or {}
        families[(row['gate'], str(context.get('kind') or ''), digest(row.get('source')))].append(row)
    repeated = []
    for (gate, kind, source_hash), rows in families.items():
        if len(rows) < 2:
            continue
        repeated.append({'gate': gate, 'kind': kind, 'source_hash': source_hash,
            'events': len(rows), 'distinct_reviews': len({r['id'] for r in rows}),
            'distinct_candidates': len({normalize(r.get('candidate')) for r in rows}),
            'source_chars': len(rows[0].get('source') or ''),
            'first_seq': rows[0]['seq'], 'latest_seq': rows[-1]['seq'],
            'first_at': rows[0]['at'], 'last_at': rows[-1]['at'],
            'stages': counts(rows, lambda r:str((r.get('context') or {}).get('stage') or '(unspecified)')),
            'terminal_cut_events': sum(r.get('disposition') == 'cut' for r in rows),
            'review_ids': sorted({r['id'] for r in rows})})
    repeated.sort(key=lambda r:-r['events'])
    for family in repeated[:8]:
        choose('repeated-source:' + family['source_hash'],
               families[(family['gate'], family['kind'], family['source_hash'])], 1)
    def overview(rows):
        return {'count': len(rows), 'gates': counts(rows, lambda r:r['gate']),
            'stages': counts(rows, lambda r:str((r.get('context') or {}).get('stage') or '(unspecified)')),
            'kinds': counts(rows, lambda r:str((r.get('context') or {}).get('kind') or '(unspecified)')),
            'dispositions': counts(rows, lambda r:r.get('disposition') or '(unspecified)'),
            'technical': sum(bool(r.get('technical')) for r in rows),
            'reason_occurrences': dict(Counter(reason for row in rows for reason in set(row.get('reasons') or [])).most_common()),
            'features': dict(Counter(f for r in rows for f in features(r)).most_common()),
            'gate_stage': dict(Counter(r['gate'] + ' / ' + str((r.get('context') or {}).get('stage') or '(unspecified)') for r in rows).most_common())}
    result = {'at_utc': datetime.fromtimestamp(stamp, timezone.utc).isoformat(), 'read_only': True,
        'method': 'SQLite online backup through a read-only source connection; every review, occurrence and decision parsed from that consistent snapshot.',
        'private_snapshot_path': str(snapshot_path),
        'source_snapshot_sha256': hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        'snapshot_cursor': max((r['seq'] for r in events), default=0), 'policy': policy,
        'all_current_records': overview(current),
        'current_status': counts(current, lambda r:r['review_status']),
        'current_pending': overview([r for r in current if r['review_status'] == 'pending']),
        'all_occurrence_history': overview(events),
        'terminal_cut_occurrences': overview([r for r in events if r.get('disposition') == 'cut']),
        'terminal_cut_distinct_reviews': len({r['id'] for r in events if r.get('disposition') == 'cut'}),
        'tint_candidate_subsets': {label: overview([r for r in events if r['gate'] == 'tint' and
                                    bool(str(r.get('candidate') or '').strip()) == available])
                                  for label, available in [('empty', False), ('nonempty', True)]},
        'draft_fragment_shapes': {'slash_bars': sum(r['gate'] == 'draft_fragment' and ' / ' in r['source'] for r in events),
            'numbered_response': sum(r['gate'] == 'draft_fragment' and bool(re.match(r'\s*\d+\s*[:.)]', r['source'])) for r in events)},
        'history_first_at': min((r['at'] for r in events), default=0),
        'history_last_at': max((r['at'] for r in events), default=0),
        'recent_30_minutes': overview([r for r in events if r['at'] > stamp-1800]),
        'decision_count': len(decisions), 'instance_count': len(instances),
        'decisions_by_action': dict(Counter(d.get('action') or '(unspecified)' for d in decisions)),
        'repeated_source_families': repeated,
        'stratified_examples': sorted(selected.values(),key=lambda r:r['seq']),
        'limits': ['Every stored record was analyzed, but refusals are not a denominator of every generated candidate.',
                   'Terminal cuts are defined by stored disposition=cut; intermediate attempt rows remain separate.',
                   'Encoding and repetition features flag text for manual inspection; they do not prove an invalid source or a false rejection.',
                   'Examples preserve exact excerpts and IDs. Complete source, candidate and parent contexts remain in the private snapshot.']}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('at_utc','snapshot_cursor','current_status','decision_count','instance_count','private_snapshot_path')}))
    print(json.dumps({'records':len(current),'events':len(events),'dispositions':result['all_occurrence_history']['dispositions'],
                      'gates':result['all_occurrence_history']['gates'],'top_reasons':reason_counts.most_common(8),
                      'examples':len(selected),'repeated_families':len(repeated)}))


if __name__ == '__main__':
    main()
