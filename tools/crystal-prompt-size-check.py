"""Replay a captured production prompt through the current pure builder only.

Reads the trace database without writes; does not import app or request models.
The public report contains sizes and identity checks, never dialogue text.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import crystal_prompts


def values(prompt):
    result = []
    for line in prompt.splitlines():
        if not line.startswith(('[', '"', '{')):
            continue
        try:
            result.append(json.loads(line))
        except ValueError:
            pass
    return result


def facts(value):
    if isinstance(value, str):
        return json.loads(value[value.index('{'):])
    return value


def contains_mapping(tree, required):
    if isinstance(tree, dict):
        if all(tree.get(k) == v for k, v in required.items()):
            return True
        return any(contains_mapping(value, required) for value in tree.values())
    if isinstance(tree, list):
        return any(contains_mapping(value, required) for value in tree)
    if isinstance(tree, str) and '{' in tree:
        try:
            return contains_mapping(facts(tree), required)
        except (ValueError, TypeError):
            return False
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='/app/data/rejection_lab.sqlite3')
    parser.add_argument('--trace-id', default='9524779c20de4d4b8b19d9b9b9760368')
    parser.add_argument('--call-id', default='0e872199290141d08bb2b4c60c5b6212')
    parser.add_argument('--output', default='docs/crystal-prompt-size-check.json')
    args = parser.parse_args()
    db = sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
    body = None
    for raw in db.execute('SELECT record FROM lab_traces WHERE trace_id=? ORDER BY seq', (args.trace_id,)):
        record = json.loads(raw[0]); detail = record.get('details') or {}
        if record.get('kind') == 'model_wire_request' and detail.get('call_id') == args.call_id:
            body = detail['body']
            break
    db.close()
    if not body:
        raise ValueError('The exact retained wire request was not found')
    original = body['messages'][-1]['content']
    parsed = values(original)
    old_rows = next(v for v in parsed if isinstance(v, list) and v and isinstance(v[0], dict) and 'requested' in v[0])
    chunks = next(v for v in parsed if isinstance(v, list) and v and isinstance(v[0], dict) and 'text' in v[0])
    strings = [v for v in parsed if isinstance(v, str)]
    world, lesson = strings[0], strings[1] if len(strings) > 1 else ''
    kind = json.loads(re.search(r'^Road: (.+)\.$', original, re.M).group(1))
    force = float(re.search(r'Style strength: ([\d.]+)', original).group(1))
    refinement = ''
    marker = 'OPERATOR CRYSTAL REFINEMENT'
    if marker in original:
        refinement = original[original.index('\n', original.index(marker)) + 1:].split('\n\n', 1)[0]
    turns = [(r['speaker'], r['source']) for r in old_rows]
    indices = [i for i, r in enumerate(old_rows) if r['requested']]
    requested = set(indices)
    kwargs = {'selected_indices': indices,
              'candidates': {i: (r.get('rejected_attempt') or {}).get('candidate') for i, r in enumerate(old_rows) if i in requested},
              'evaluations': {i: (r.get('rejected_attempt') or {}).get('evaluation') for i, r in enumerate(old_rows) if i in requested},
              'contracts': {i: r['source_contract'] for i, r in enumerate(old_rows) if i in requested},
              'operator_instruction': refinement, 'lesson': lesson}
    start = original.index('Rewrite retained radio dialogue.')
    ending = 'Return only the requested rewritten lines in the specified output format.'
    end = original.index(ending, start) + len(ending)
    old_builder = original[start:end]
    new_builder = crystal_prompts.round_prompt(turns, world, chunks, force, kind, **kwargs)
    reconstructed = original[:start] + new_builder + original[end:]
    new_values = values(new_builder)
    new_rows = next(v for v in new_values if isinstance(v, list) and v and isinstance(v[0], dict) and 'requested' in v[0])
    new_chunks = next(v for v in new_values if isinstance(v, list) and v and isinstance(v[0], dict) and 'text' in v[0])
    checks = {
        'all_originals_speakers_order_and_requested_flags_exact':
            [{k:r[k] for k in ('id', 'speaker', 'source', 'requested')} for r in new_rows] ==
            [{k:r[k] for k in ('id', 'speaker', 'source', 'requested')} for r in old_rows],
        'full_style_passages_and_metadata_exact': new_chunks == chunks,
        'full_world_exact': world in new_values,
        'full_feedback_exact': not lesson or lesson in new_values,
        'all_requested_source_contract_facts_retained': all(
            contains_mapping(new_rows[i], facts(old_rows[i]['source_contract'])) for i in indices),
        'all_nonempty_candidates_exact': all(
            (r.get('rejected_attempt') or {}).get('candidate') ==
            (new_rows[i].get('rejected_attempt') or {}).get('candidate')
            for i, r in enumerate(old_rows) if (r.get('rejected_attempt') or {}).get('candidate')),
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    report = {'method': 'Pure current builder replay of one exact retained production wire request; no models or production writes.',
        'call_id': args.call_id, 'trace_id': args.trace_id,
        'builder_sha256': hashlib.sha256(Path(crystal_prompts.__file__).read_bytes()).hexdigest(),
        'old_user_chars': len(original), 'new_user_chars': len(reconstructed),
        'old_builder_chars': len(old_builder), 'new_builder_chars': len(new_builder),
        'reduction_chars': len(original) - len(reconstructed),
        'reduction_percent': round(100 * (len(original) - len(reconstructed)) / len(original), 2),
        'turns': len(old_rows), 'requested_turns': len(indices),
        'nonempty_candidates_in_capture': sum(bool((r.get('rejected_attempt') or {}).get('candidate')) for r in old_rows),
        'checks': checks,
        'limits': ['Character reduction is measured; token or latency improvement requires new service measurements.',
                   'This captured call had no nonempty candidates; separate unit tests must verify full candidate preservation on repair calls.']}
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
