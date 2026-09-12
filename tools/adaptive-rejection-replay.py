"""Replay the fixed 47-event audit through the real grader without live work."""
from collections import Counter
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def main():
    isolated = Path(os.environ.get('SPARK_AGENT_DATA_DIR', '')).resolve()
    if not str(isolated).startswith('/tmp/') or isolated.is_relative_to(ROOT / 'data'):
        raise SystemExit('An isolated /tmp SPARK_AGENT_DATA_DIR is required.')
    audit = json.loads((ROOT / 'docs/adaptive-rejection-audit.json').read_text())
    snapshot = Path(audit['manifest']['snapshot'])
    before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    rows = []
    with closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as db:
        for seq, review_id, stamp, body in db.execute('SELECT seq,review_id,at,body FROM review_events ORDER BY seq'):
            row = json.loads(body)
            if stamp >= audit['manifest']['since_epoch'] and row.get('gate') == 'tint':
                rows.append({**row, 'seq': seq, 'id': review_id, 'at': stamp})
    assert len(rows) == 47
    import app
    names = ('app.py', 'crystal_contract.py', 'crystal_acceptance.py', 'prompt_learning.py')
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    vocabulary = frozenset(word for row in rows
        for chunk in (row.get('context') or {}).get('chunks') or []
        for word in app._tint_content(chunk.get('text', '') if isinstance(chunk, dict) else ''))
    results = []
    judge_before = copy.deepcopy(app._TINT_JUDGE_RING)
    token = app._REJECTION_LAB_PREVIEW.set(True)
    forbidden = AssertionError('Offline replay attempted a model, journal write or override')
    try:
        with (mock.patch.object(app, '_crystal_vocab', return_value=vocabulary),
              mock.patch.object(app, 'line_review_capture', side_effect=forbidden),
              mock.patch.object(app._LINE_REVIEW, 'evaluate', side_effect=forbidden),
              mock.patch.object(app._LINE_REVIEW, 'record', side_effect=forbidden),
              mock.patch.object(app, 'prompt_learning_observe', side_effect=forbidden),
              mock.patch.object(app, 'ask_model', new=mock.AsyncMock(side_effect=forbidden)),
              mock.patch.object(app, 'call_ollama', new=mock.AsyncMock(side_effect=forbidden))):
            for mode in ('strict', 'fluid'):
                app._PROMPT_LEARNING.update(app._PROMPT_LEARNING.settings()['revision'], mode=mode)
                assert app.crystal_acceptance_mode() == mode
                for index, row in enumerate(rows):
                    ctx, old = row.get('context') or {}, row.get('evaluation') or {}
                    assert isinstance(old.get('strength'), (int, float)) and old.get('grade') in ('meaning', 'strict')
                    args = dict(chunks=copy.deepcopy(ctx.get('chunks') or []),
                                answering=str(ctx.get('answering') or ''),
                                force=old['strength'], kind=str(ctx.get('kind') or ''),
                                strict=old['grade'] == 'strict')
                    current = app.tint_evaluate(row['source'], row['candidate'], **args)
                    assert current['version'] == 6 and not current.get('operator_accepted')
                    if mode == 'strict':
                        results.append({
                            'seq': row['seq'], 'id': row['id'], 'at': row['at'],
                            'source': row['source'], 'candidate': row['candidate'],
                            'pair_sha256': digest(json.dumps([row['source'], row['candidate']], ensure_ascii=False)),
                            'kind': args['kind'], 'stage': ctx.get('stage'),
                            'disposition': row.get('disposition'), 'technical': bool(row.get('technical')),
                            'inputs': args, 'old_evaluation': old, 'strict_evaluation': current,
                            'old_rap_ok': (old.get('rhyme') or {}).get('rap', {}).get('ok') is True,
                            'current_rap_ok': current['rhyme']['rap']['ok'],
                            'raw_ok': current['machine_ok']})
                    else:
                        assert current['machine_ok'] == results[index]['raw_ok']
                        assert current['machine_faults'] == results[index]['strict_evaluation']['machine_faults']
                        results[index].update(fluid_evaluation=current, fluid_ok=current['ok'])
    finally:
        app._REJECTION_LAB_PREVIEW.reset(token)
    assert app._TINT_JUDGE_RING == judge_before
    groups = {}
    for row in results:
        if row['fluid_ok'] and not row['old_evaluation'].get('ok'):
            group = groups.setdefault(row['pair_sha256'], {'pair_sha256': row['pair_sha256'],
                'source': row['source'], 'candidate': row['candidate'], 'sequences': [],
                'manual_status': 'pending', 'manual_note': ''})
            group['sequences'].append(row['seq'])
    report = {'status': 'awaiting_manual_pair_review', 'at_utc': datetime.now(timezone.utc).isoformat(),
        'snapshot_sha256': before, 'snapshot_path': str(snapshot), 'source_sha256': hashes,
        'method': 'Actual app.tint_evaluate version6 twice per occurrence, preserving recorded source/candidate/chunks/answering/kind/force/meaning-or-strict grade. Only temporary learner mode changes: strict then fluid. Preview enabled; model calls, review storage and learning observations forbidden.',
        'vocabulary': {'method': 'Frozen union of retained context.chunks content words from these47 occurrences; approximation to the original full live crystal vocabulary.',
                       'count': len(vocabulary), 'sha256': digest('\n'.join(sorted(vocabulary)))},
        'counts': {'occurrences': len(results), 'exact_pairs': len({r['pair_sha256'] for r in results}),
            'old_machine_pass': sum(r['old_evaluation'].get('machine_ok') is True for r in results),
            'current_raw_pass': sum(r['raw_ok'] for r in results),
            'fluid_pass': sum(r['fluid_ok'] for r in results),
            'fluid_style_advisory_pass': sum(r['fluid_ok'] and not r['raw_ok'] for r in results),
            'rhyme_false_to_true': sum(not r['old_rap_ok'] and r['current_rap_ok'] for r in results),
            'rhyme_true_to_false': sum(r['old_rap_ok'] and not r['current_rap_ok'] for r in results),
            'newly_passing_exact_pairs': len(groups),
            'fluid_blocking_faults': dict(Counter(f for r in results if not r['fluid_ok'] for f in r['fluid_evaluation']['faults']))},
        'rhyme_changed_sequences': [r['seq'] for r in results if r['old_rap_ok'] != r['current_rap_ok']],
        'newly_passing_pairs': list(groups.values()), 'results': results,
        'integrity': {'snapshot_unchanged': before == hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                      'sources_unchanged': hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names},
                      'judge_ring_unchanged': app._TINT_JUDGE_RING == judge_before,
                      'production_writes_or_models': False},
        'limits': ['Rejection-only sample: eligibility changes do not measure production acceptance rate or writing quality.',
                   'The original full live vocabulary was not saved. Frozen retained-chunk vocabulary can alter inferred names and style evidence; full chunk copying checks remain exact.',
                   'Repeated occurrences can differ in answering/style context. Distinct-pair summaries do not replace per-occurrence full reports.',
                   'No candidate was rewritten, voted on, queued, recorded or played.']}
    (ROOT / 'docs/adaptive-rejection-replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'counts': report['counts'], 'integrity': report['integrity'],
                      'pairs': report['newly_passing_pairs']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
