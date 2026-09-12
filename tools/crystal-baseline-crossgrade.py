"""Regrade already generated trials; never generate, apply, vote or play."""
import argparse
import codecs
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


def vector_texts(path):
    """Stream JSON string values named text, retaining no numeric embeddings."""
    before = path.stat()
    sha = hashlib.sha256()
    decode = codecs.getincrementaldecoder('utf-8')()
    parser = json.JSONDecoder()
    key = re.compile(r'(?<!\\)"text"\s*:\s*(?=")')
    buffer = ''
    with path.open('rb') as handle:
        while True:
            data = handle.read(1024 * 1024)
            sha.update(data)
            buffer += decode.decode(data, final=not data)
            index = 0
            while True:
                match = key.search(buffer, index)
                if match is None:
                    buffer = buffer[max(index, len(buffer) - 64):]
                    break
                try:
                    text, used = parser.raw_decode(buffer[match.end():])
                except json.JSONDecodeError:
                    buffer = buffer[match.start():]
                    if not data or len(buffer) > 8 * 1024 * 1024:
                        raise ValueError('Incomplete or oversized vector text value')
                    break
                if not isinstance(text, str):
                    raise ValueError('Vector text is not a string')
                yield text
                index = match.end() + used
            if not data:
                break
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Vector source changed while read')
    yield {'path': str(path), 'bytes': after.st_size, 'mtime': after.st_mtime,
           'sha256': sha.hexdigest()}


def prompt_value(prompt, label):
    start = prompt.index(label)
    start = prompt.index('\n', start) + 1
    return json.JSONDecoder().raw_decode(prompt[start:].lstrip())[0]


def wire_evidence(case, clean):
    """Require the same trace/call, exact request inputs and delivered result."""
    trace = case.get('trace') or {}
    items = trace.get('items') or []
    before, trial = case['before'], case['trial']
    baseline, context = trial['baseline'], before.get('context') or {}
    trace_id = trial['provenance']['trace_id']
    if trace.get('trace_id') != trace_id:
        raise ValueError('The trial and downloaded trace identities differ')
    requests = {r['record']['details']['call_id']: r for r in items
                if r['record']['kind'] == 'model_wire_request' and r['trace_id'] == trace_id}
    evaluated = [r for r in items if r['trace_id'] == trace_id
                 and r['record']['kind'] == 'trial_evaluation'
                 and r['record']['details'].get('source') == baseline['source']
                 and r['record']['details'].get('candidate') == trial['candidate']]
    matches = []
    for response in items:
        if response['trace_id'] != trace_id or response['record']['kind'] != 'model_response':
            continue
        details = response['record']['details']
        request = requests.get(details.get('call_id'))
        if not request or request['seq'] >= response['seq']:
            continue
        prompts = [message.get('content', '') for message in request['record']['details']['body']['messages']]
        prompt = next((text for text in prompts if 'ORIGINAL SOURCE' in text), '')
        if not prompt:
            continue
        source = prompt_value(prompt, 'ORIGINAL SOURCE')
        chunks = prompt_value(prompt, 'HOW THAT WRITER WRITES')
        world = prompt_value(prompt, 'THE STYLE WORLD')
        if source != baseline['source'] or chunks != context.get('chunks') or world != context.get('crystal'):
            raise ValueError('Wire prompt inputs differ from the retained source/style context')
        raw = details.get('response', {}).get('message', {}).get('content', '')
        legacy = clean(re.sub(r'\s*/\s*', ', ', raw))
        current = clean(raw)
        if (legacy != trial['candidate'] and current != trial['candidate']) or not any(row['seq'] > response['seq'] for row in evaluated):
            continue
        matches.append({'trace_id': trace_id, 'call_id': details['call_id'],
            'wire_step': request['seq'], 'response_step': response['seq'],
            'model': details['response'].get('model'), 'raw': raw, 'restored': current,
            'exact_legacy_clean_match': legacy == trial['candidate'],
            'exact_current_clean_match': current == trial['candidate'],
            'source_style_chunks_verified': True,
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'raw_sha256': hashlib.sha256(raw.encode()).hexdigest()})
    if len(matches) != 1:
        return {'proven': False, 'why': f'Expected one exact wire match; found {len(matches)}'}
    return {'proven': True, **matches[0]}


def verdict(evaluation):
    tint = evaluation['tint']
    return {'accepted': bool(evaluation['ok']), 'machine_ok': bool(tint['machine_ok']),
            'accepted_with_advisories': bool(evaluation['ok'] and tint.get('editorial', {}).get('accepted_with_advisories')),
            'semantic_ok': bool(tint['semantic']['ok']), 'rap_ok': bool(tint['rhyme']['rap']['ok'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='/app/docs/rejection-learning-baseline-trials.json')
    parser.add_argument('--output', default='/app/docs/rejection-learning-baseline-v8-crossgrade.json')
    parser.add_argument('--vocabulary', help='Reuse a previously frozen vocabulary JSON, without rereading live mind files')
    parser.add_argument('--grade-label', default='v8', help='Label for the current offline grader in new output files')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ['SPARK_AGENT_DATA_DIR'] = tempfile.mkdtemp(prefix='pine-baseline-crossgrade-')
    import app
    from rejection_workbench import RejectionWorkbench
    path = Path(args.input)
    original_bytes = path.read_bytes()
    data = json.loads(original_bytes)
    cases = data['cases']
    vocab, sources = set(), []
    minds = sorted({chunk['mind'] for case in cases for chunk in case['before']['context']['chunks']})
    frozen_path = Path(args.vocabulary) if args.vocabulary else Path(args.output).with_name(
        Path(args.output).stem + '-vocabulary.json')
    if args.vocabulary:
        frozen = json.loads(frozen_path.read_text())
        vocab.update(frozen['words'])
        if hashlib.sha256('\n'.join(sorted(vocab)).encode()).hexdigest() != frozen['sha256']:
            raise ValueError('Frozen vocabulary hash mismatch')
        sources = frozen['sources']
    for mind in ([] if args.vocabulary else minds):
        if re.fullmatch(r'[a-zA-Z0-9_-]+', mind) is None:
            raise ValueError('Unsafe retained mind identifier')
        vector_path = root / 'data/minds' / mind / 'vectors.json'
        count = 0
        for value in vector_texts(vector_path):
            if isinstance(value, dict):
                sources.append({**value, 'mind': mind, 'text_values': count})
            else:
                vocab.update(app._tint_content(value))
                count += 1
    if not args.vocabulary:
        for case in cases:
            for chunk in case['before']['context']['chunks']:
                vocab.update(app._tint_content(chunk['text']))
        frozen = {'words': sorted(vocab), 'sources': sources,
                  'sha256': hashlib.sha256('\n'.join(sorted(vocab)).encode()).hexdigest(),
                  'retained_prompt_chunks_also_included': True}
        if frozen_path.exists() and json.loads(frozen_path.read_text()) != frozen:
            raise ValueError('Refusing to replace a different frozen vocabulary')
        if not frozen_path.exists():
            frozen_path.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'vocabulary_ready': len(vocab), 'sources': sources}), flush=True)
    results = []
    service = RejectionWorkbench(vars(app))
    delivered_label=args.grade_label+'_delivered'
    wire_label=args.grade_label+'_wire_restored'
    counts = {name: Counter() for name in ('historical', delivered_label, wire_label)}
    for case in cases:
        baseline, before, trial = case['trial']['baseline'], case['before'], case['trial']
        if before['source'] != baseline['source']:
            raise ValueError('Trial source and saved occurrence differ')
        proof = wire_evidence(case, app._tint_out_clean)
        force, mode = baseline['strength'], baseline['acceptance_mode']
        strict = baseline['grade'] == 'strict'
        with ExitStack() as stack:
            for name, value in [('_crystal_vocab', mock.Mock(return_value=frozenset(vocab))),
                    ('crystal_force', mock.Mock(return_value=force)),
                    ('crystal_grade_strict', mock.Mock(return_value=strict)),
                    ('crystal_acceptance_mode', mock.Mock(return_value=mode)),
                    ('line_review_capture', mock.Mock(side_effect=AssertionError('No review writes')))]:
                stack.enter_context(mock.patch.object(app, name, value))
            delivered = service.grade(before, trial['candidate'])
            restored = service.grade(before, proof['restored']) if proof['proven'] else None
        historical = verdict(trial['evaluation'])
        current = verdict(delivered)
        repaired = verdict(restored) if restored else None
        for name, value in [('historical', historical), (delivered_label, current), (wire_label, repaired)]:
            if value is not None:
                counts[name].update({'graded': 1, **{key: int(flag) for key, flag in value.items()}})
        results.append({'case_id': case['frozen_case_id'], 'original_split': case['split'],
            'review_id': before['id'], 'event_seq': before['event_seq'], 'operation_id': case['operation_id'],
            'source': baseline['source'], 'delivered_candidate': trial['candidate'],
            'context': before['context'], 'baseline_profile': baseline,
            'historical_evaluation': trial['evaluation'],
            'historical_verdict': historical, delivered_label+'_verdict': current,
            wire_label+'_verdict': repaired, 'wire_proof': proof,
            delivered_label+'_evaluation': delivered, wire_label+'_evaluation': restored})
    assert path.read_bytes() == original_bytes
    report = {'read_only': True, 'model_requests': 0, 'tts': 0, 'votes': 0, 'applies': 0,
        'settings_writes': 0, 'playback_requests': 0, 'input': str(path),
        'input_sha256': hashlib.sha256(original_bytes).hexdigest(), 'input_unchanged': True,
        'grader_version': app.CRYSTAL_GRADER_VERSION,
        'method': 'Actual RejectionWorkbench.grade with each saved source/context/force/meaning-mode/fluid-mode. '
                  'Compare historical recorded verdict, exact delivered wording under current grader, and exact '
                  'wire-proven original bars through the current cleaner under the same current grader. No wording generation.',
        'vocabulary': {'words': len(vocab), 'sha256': hashlib.sha256('\n'.join(sorted(vocab)).encode()).hexdigest(),
                       'sources': sources, 'frozen_file': str(frozen_path),
                       'frozen_file_sha256': hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                       'retained_prompt_chunks_also_included': True},
        'limits': ['The original train/holdout labels are provenance only: all twelve cases have now informed debugging. There is no blind holdout.',
                   'The full current retained mind vocabulary is frozen from disk. The old process cache completeness at the baseline instant is not proven.',
                   'Regrading stored wording measures grader/cleanup effects; it does not demonstrate a new prompt generation benefit.',
                   'Machine acceptance and manual fidelity/fluency assessments are distinct.'],
        'summary': {key: dict(value) for key, value in counts.items()}, 'cases': results}
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'output': args.output, 'summary': report['summary']}), flush=True)


if __name__ == '__main__':
    main()
