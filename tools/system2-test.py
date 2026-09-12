"""Run isolated Python or Node regressions, with source snapshots and a deadline.

Python runs inside spark-agent; Node may run from the shared Windows workspace.
Only tests/test_*.py or tests/test_*.cjs are selected. Electron/device smoke tools
are deliberately separate. No app startup or live API is invoked by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def hashes():
    paths = set(ROOT.glob('*.py')) | {ROOT / 'package.json', Path(__file__).resolve()}
    for directory in ('frontend', 'desktop'):
        paths.update((ROOT / directory).rglob('*.js'))
        paths.update((ROOT / directory).rglob('*.css'))
    paths.update((ROOT / 'tests').glob('test_*.py'))
    paths.update((ROOT / 'tests').glob('test_*.cjs'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('python', 'node'), default='python')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--output', default='')
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error('timeout must be between 1 and 600 seconds')
    destination = Path(args.output) if args.output else ROOT / 'docs' / ('system2-' + args.suite + '-tests.json')
    started = time.time()
    before = hashes()
    records = []
    exit_code = 0
    with tempfile.TemporaryDirectory(prefix='pinebox-system2-' + args.suite + '-tests-') as state:
        env = dict(os.environ, SPARK_AGENT_DATA_DIR=state, PYTHONIOENCODING='utf-8')
        env.pop('SPARK_AGENT_API_KEY', None)
        guard = Path(state) / 'sitecustomize.py'
        guard.write_text('''import socket
import faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(120, repeat=True)
def _blocked(*args, **kwargs):
    raise RuntimeError("Network blocked by isolated System2 test runner")
socket.create_connection = _blocked
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
''', encoding='utf-8')
        env['PYTHONPATH'] = state + os.pathsep + str(ROOT) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        selected = sorted((ROOT / 'tests').glob('test_*.' + ('py' if args.suite == 'python' else 'cjs')))
        commands = [(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v')] if args.suite == 'python' else [('node', p.relative_to(ROOT).as_posix()) for p in selected]
        deadline = time.monotonic() + args.timeout
        for command in commands:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                records.append({'command': command, 'timed_out': True, 'not_started': True})
                exit_code = 124
                break
            one_started = time.time()
            try:
                result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                    text=True, encoding='utf-8', errors='replace', timeout=remaining)
                row = {'command': command, 'exit_code': result.returncode,
                       'stdout': result.stdout, 'stderr': result.stderr, 'timed_out': False}
            except subprocess.TimeoutExpired as error:
                row = {'command': command, 'exit_code': 124, 'timed_out': True,
                       'stdout': text(error.stdout), 'stderr': text(error.stderr)}
            except OSError as error:
                row = {'command': command, 'exit_code': 127, 'timed_out': False,
                       'stdout': '', 'stderr': str(error)}
            row.update(started_at=one_started, finished_at=time.time())
            row['seconds'] = round(row['finished_at'] - one_started, 3)
            pattern = r'Ran (\d+) tests?' if args.suite == 'python' else r'(?:^|\n)(?:#|ℹ) tests (\d+)'
            matches = re.findall(pattern, row['stdout'] + '\n' + row['stderr'])
            row['reported_tests'] = int(matches[-1]) if matches else None
            legacy = re.findall(r'(\d+) [^\n]*checks passed', row['stdout']) if args.suite == 'node' and not matches else []
            row['legacy_reported_checks'] = int(legacy[-1]) if legacy else None
            records.append(row)
            if row['exit_code']:
                exit_code = row['exit_code']
                print(json.dumps({'command': command, 'exit_code': row['exit_code'],
                                  'stderr_tail': row['stderr'][-10000:], 'stdout_tail': row['stdout'][-4000:]}))
    after = hashes()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    report = {'suite': args.suite, 'started_at': started, 'finished_at': time.time(),
        'timeout_seconds': args.timeout, 'isolated_state': True, 'isolated_path': state,
        'python_network_guard': 'socket connection blocked; no live credentials in child',
        'python_diagnostics': 'Verbose per-test record plus faulthandler thread dumps after each 120-second wait',
        'node_scope': 'existing fixture unit tests only; no Electron/device smoke tools',
        'exit_code': exit_code, 'selected_files': [p.relative_to(ROOT).as_posix() for p in selected],
        'reported_tests': sum(r.get('reported_tests') or 0 for r in records),
        'legacy_reported_checks': sum(r.get('legacy_reported_checks') or 0 for r in records),
        'commands_without_reported_count': sum(r.get('reported_tests') is None for r in records),
        'commands': records, 'source_sha256_start': before, 'source_sha256_end': after,
        'changed_during_run': changed,
        'limitation': 'This validates the source actually loaded by tests. Any changed source requires focused revalidation or a final frozen-source rerun.'}
    report['seconds'] = round(report['finished_at'] - started, 3)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temporary, destination)
    print(json.dumps({'output': str(destination), 'exit_code': exit_code,
        'reported_tests': report['reported_tests'], 'selected_files': len(selected),
        'seconds': report['seconds'], 'changed_during_run': changed}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
