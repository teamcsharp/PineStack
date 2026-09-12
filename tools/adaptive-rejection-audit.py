"""Analyze a retained consistent SQLite snapshot; never imports the station."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def overview(rows):
    return {'events': len(rows), 'distinct_review_ids': len({r['id'] for r in rows}),
            'gates': dict(Counter(r['gate'] for r in rows)),
            'dispositions': dict(Counter(r.get('disposition') for r in rows)),
            'stages': dict(Counter(str((r.get('context') or {}).get('stage')) for r in rows)),
            'reasons': dict(Counter(reason for row in rows for reason in set(row.get('reasons') or []))),
            'technical': sum(bool(r.get('technical')) for r in rows)}


def retained(row):
    context = row.get('context') or {}
    entry = context.get('entry') or {}
    return {**{k: row.get(k) for k in ('seq', 'id', 'at', 'gate', 'disposition', 'technical',
                                       'source', 'candidate', 'reasons', 'evaluation')},
            'context': {k: context[k] for k in ('kind', 'stage', 'turn', 'marker', 'answering',
                        'caller_name', 'script', 'script_plain', 'turns', 'verbatim', 'source_original',
                        'lab_trace_id') if k in context},
            'entry_metadata': {k: entry[k] for k in ('kind', 'prep_kind', 'product', 'seed', 'who', 'voice', 'sid', 'at') if k in entry},
            'source_chars': len(row.get('source') or ''), 'candidate_chars': len(row.get('candidate') or '')}


def main():
    output = Path('docs/adaptive-rejection-audit.json')
    previous = json.loads(output.read_text())
    manifest = previous['manifest']
    db = sqlite3.connect(Path(manifest['snapshot']).as_uri() + '?mode=ro', uri=True)
    history = []
    for seq, identity, stamp, body in db.execute('SELECT seq,review_id,at,body FROM review_events ORDER BY seq'):
        row = json.loads(body); row.update(seq=seq, id=identity, at=stamp); history.append(row)
    current = [{'id': identity, 'gate': gate, 'status': status} for identity, gate, status in
               db.execute('SELECT id,gate,review_status FROM line_reviews')]
    db.close()
    rows = [r for r in history if r['at'] >= manifest['since_epoch']]
    exact, families = defaultdict(list), defaultdict(list)
    for row in rows:
        ctx = row.get('context') or {}
        key = (row['gate'], ctx.get('kind'), ' '.join(row.get('source', '').split()))
        families[key].append(row)
        exact[(*key, ' '.join(row.get('candidate', '').split()))].append(row)
    repeated = [{'review_id': group[0]['id'], 'sequences': [r['seq'] for r in group],
                 'stages': [(r.get('context') or {}).get('stage') for r in group],
                 'dispositions': [r.get('disposition') for r in group],
                 'same_stage_repeats': len(group) - len({(r.get('context') or {}).get('stage') for r in group})}
                for group in exact.values() if len(group) > 1]
    source_families = [{'gate': key[0], 'kind': key[1], 'source': key[2],
                       'events': len(group), 'candidate_variants': len({r.get('candidate') for r in group}),
                       'sequences': [r['seq'] for r in group]}
                      for key, group in families.items() if len(group) > 2]
    tint = [r for r in rows if r['gate'] == 'tint']
    latest_blends = [r for r in history if r['gate'] == 'blend'][-5:]
    assessments = [
        {'sequences': [3494, 3499, 3526], 'finding': 'touch/clutch is a real rhyme missed by the orthographic vowel classes. Meaning/transformation checks pass, but the extra clutch metaphor remains awkward; this is not blanket approval of the prose.'},
        {'sequences': [3497], 'finding': 'kid/bid is a real landing pair. The three-word comma clause A disaster bid is merged into the next clause by the four-word minimum and loses its endpoint.'},
        {'sequences': [3505, 3506, 3522], 'finding': 'Phone greeting retains the exact digits and passes meaning/transformation. Existing rhyme evidence fails on eight/fate/mistake; pronunciation and bar segmentation need a bounded regression, not a broad semantic waiver.'},
        {'sequences': [3491, 3508, 3519, 3520, 3521, 3527, 3528, 3535], 'finding': 'Global negation-presence mismatches appear after added no-denying/no-complying/no-failing phrases. Some rhetorical phrases may preserve polarity, but others add certainty or refusal. Do not waive these globally without predicate-specific evidence.'},
        {'sequences': [3515, 3518, 3537], 'finding': 'Candidates with actual rap evidence can be blocked only on transformation. They still include awkward filler, near-copying or an incomplete source. A fluid editorial mode can label this as a style warning while retaining meaning/rhyme/copied-source protections; it must not claim improved quality.'},
        {'sequences': [3524, 3535], 'finding': 'Ad entry source text is already mostly radio chatter rather than its product. Entry seed vil1.md contains embedded A/C caller dialogue. Tint is preserving a damaged upstream composition; gate softening cannot supply the missing product sale.'},
        {'sequences': [3489], 'finding': 'Most recent blend predates this process by about16 seconds. It discards most assembled host dialogue and moves/reseats the tail. The refusal is protective; blend_script returns the original, so a rejected blend is not itself a cut of the retained original script.'},
    ]
    result = {'status': 'complete', 'manifest': manifest,
              'at_utc': datetime.fromtimestamp(manifest['captured_at'], timezone.utc).isoformat(),
              'snapshot_sha256': hashlib.sha256(Path(manifest['snapshot']).read_bytes()).hexdigest(),
              'latest_cursor': max(r['seq'] for r in history),
              'all_current_record_count': len(current), 'all_history_event_count': len(history),
              'all_current_status': dict(Counter(r['status'] for r in current)),
              'all_current_gates': dict(Counter(r['gate'] for r in current)),
              'pending_current_gates': dict(Counter(r['gate'] for r in current if r['status'] == 'pending')),
              'window': overview(rows),
              'tint_evaluation': {'events': len(tint),
                  'semantic_ok': sum((r.get('evaluation') or {}).get('semantic', {}).get('ok') is True for r in tint),
                  'rap_ok': sum((r.get('evaluation') or {}).get('rhyme', {}).get('rap', {}).get('ok') is True for r in tint),
                  'transformation_only': [r['seq'] for r in tint if r.get('reasons') == ['rhetoric was not materially transformed']],
                  'rhyme_only': [r['seq'] for r in tint if r.get('reasons') == ['no rhyme evidence - the bar does not land a rhyme']]},
              'literal_bield_matches': [r['seq'] for r in rows if 'bield' in (r.get('source', '') + r.get('candidate', '')).lower()],
              'repeated_exact_candidate_occurrences': repeated,
              'repeated_source_families': sorted(source_families, key=lambda r: -r['events']),
              'assessments': assessments,
              'all_new_exact_examples': [retained(r) for r in rows],
              'recent_historical_blends': [retained(r) for r in latest_blends],
              'limits': ['Every retained event in the window is represented. Refusals are not a denominator of all generated candidates.',
                         'Distinct rejection, retry and terminal-cut stages for the same candidate are not automatically duplicate model work.',
                         'Pronunciation misses are distinct from overall writing quality. Passing a rhyme check is not evidence that added metaphors are faithful.',
                         'Current-state GET and the SQLite backup were taken a few moments apart; later arrivals are intentionally outside this consistent snapshot.',
                         'Full source/candidate strings and evaluations are retained in this local report; the private snapshot retains omitted parent evidence.']}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: result[k] for k in ('latest_cursor', 'all_current_status', 'window', 'tint_evaluation', 'repeated_exact_candidate_occurrences')}))


if __name__ == '__main__':
    main()
