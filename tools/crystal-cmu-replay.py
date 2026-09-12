"""Read-only paired grade replay; no models, controls, votes, or real data writes."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from unittest import mock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='/app/data/rejection_followup_audit/1788838388/line_review.sqlite3')
    parser.add_argument('--output', default='/app/docs/crystal-cmu-integrated-replay.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ['SPARK_AGENT_DATA_DIR'] = tempfile.mkdtemp(prefix='pine-cmu-replay-')
    import app
    import crystal_rhyme as cmu

    database = Path(args.snapshot)
    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        rows = [(seq, review_id, json.loads(body)) for seq, review_id, body in connection.execute(
            'SELECT seq, review_id, body FROM review_events WHERE seq BETWEEN 3538 AND 5433 ORDER BY seq')]
    rows = [(seq, review_id, body) for seq, review_id, body in rows
            if body.get('gate') == 'tint' and body.get('source') and body.get('candidate')]
    chunks = [chunk for _, _, body in rows for chunk in (body.get('context') or {}).get('chunks', [])
              if isinstance(chunk, dict)]
    vocabulary = frozenset(word for chunk in chunks for word in app._tint_words(chunk.get('text', '')))
    prior = json.loads((root / 'docs/crystal-cmu-benefit-audit.json').read_text())
    raw = {row['seq']: row['raw_trace'] for row in prior['raw_boundary_positive_rows'] + prior['new_positive_rows']
           if row.get('raw_trace')}
    # First verified load and repeated checks, excluding interpreter imports.
    cmu._LINES = None
    cmu._ERROR = ''
    cmu._pronunciations.cache_clear()
    began = time.perf_counter()
    sample = app.rap_rhyme_evidence('Stay there / Take care')
    cold_ms = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    for _ in range(1000):
        app.rap_rhyme_evidence('Stay there / Take care')
    warm_ms = (time.perf_counter() - began) * 1000
    empty = {'pairs': [], 'dictionary': {'available': False, 'error': 'paired comparison omits new evidence'}}
    counts, results, cache = Counter(), [], {}
    token = app._REJECTION_LAB_PREVIEW.set(True)
    try:
        with mock.patch.object(app, '_crystal_vocab', return_value=vocabulary), \
                mock.patch.object(app, 'crystal_acceptance_mode', return_value='fluid'), \
                mock.patch.object(app, 'line_review_capture', side_effect=AssertionError('No review writes')):
            for seq, review_id, body in rows:
                context = body.get('context') or {}
                old = body.get('evaluation') or {}
                source, stored = body['source'], body['candidate']
                candidate = app._tint_out_clean(raw[seq]['raw']) if seq in raw else stored
                kind, answering = context.get('kind', ''), context.get('answering', '')
                force = old.get('strength', .88)
                passages = context.get('chunks') or []
                key = json.dumps([source, candidate, kind, answering, force, passages], sort_keys=True)
                if key not in cache:
                    with mock.patch.object(cmu, 'terminal_rhymes', return_value=empty):
                        without = app.tint_evaluate(source, candidate, passages, answering, force, kind, strict=False)
                    after = app.tint_evaluate(source, candidate, passages, answering, force, kind, strict=False)
                    cache[key] = without, after
                without, after = cache[key]
                old_rhyme, new_rhyme = without['rhyme']['rap']['ok'], after['rhyme']['rap']['ok']
                counts.update({'events': 1, 'without_rhyme': int(old_rhyme), 'with_rhyme': int(new_rhyme),
                    'new_rhyme': int(new_rhyme and not old_rhyme),
                    'without_machine': int(without['machine_ok']), 'with_machine': int(after['machine_ok']),
                    'without_accepted': int(without['ok']), 'with_accepted': int(after['ok']),
                    'new_machine': int(after['machine_ok'] and not without['machine_ok']),
                    'new_accepted': int(after['ok'] and not without['ok']),
                    'new_rhyme_semantic_refused': int(new_rhyme and not old_rhyme and not after['semantic']['ok'])})
                results.append({'seq': seq, 'review_id': review_id, 'source': source,
                    'stored_candidate': stored, 'candidate': candidate, 'kind': kind,
                    'raw_trace': raw.get(seq), 'before': without, 'after': after})
    finally:
        app._REJECTION_LAB_PREVIEW.reset(token)
    after_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    assert before_hash == after_hash
    new_rows = [r for r in results if r['after']['ok'] and not r['before']['ok']]
    distinct = lambda selected: len({(r['source'], r['candidate']) for r in selected})
    report = {'read_only': True, 'models': 0, 'votes': 0, 'settings_writes': 0, 'playback': 0,
        'snapshot': str(database), 'snapshot_sha256': before_hash, 'snapshot_unchanged': True,
        'method': 'Actual current tint_evaluate, same source/candidate/context, with CMU disabled versus enabled. '
                  'Preview context excludes review/learning writes. Exact matching raw traces restore slash bars '
                  'where available; otherwise stored speech is used. No semantic or other grading rule differs.',
        'limits': ['This is a rejected-event cohort, not independent attempts or a station pass rate.',
                   'Vocabulary is a frozen union of retained chunk words, not a claim of exact live vocabulary.',
                   'Current semantic heuristics do not prove proposition fidelity; newly passing rows require manual review.'],
        'vocabulary_words': len(vocabulary), 'version': app.CRYSTAL_GRADER_VERSION,
        'dictionary': sample['pronunciation']['dictionary'],
        'performance': {'cold_ms': cold_ms, '1000_warm_full_rap_ms': warm_ms,
                        'lookup_cache_limit': cmu._pronunciations.cache_info().maxsize},
        'summary': {**dict(counts), 'pairs': distinct(results), 'new_accepted_pairs': distinct(new_rows),
                    'distinct_grade_inputs': len(cache)}, 'rows': results}
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'output': args.output, 'summary': report['summary'], 'performance': report['performance']}), flush=True)


if __name__ == '__main__':
    main()
