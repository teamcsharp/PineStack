"""Isolated full-suite result for the measured prompt-learning changes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

started = time.time()
with tempfile.TemporaryDirectory(prefix='pinebox-learning-tests-') as state:
    result = subprocess.run(['python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'],
        env=dict(os.environ, SPARK_AGENT_DATA_DIR=state), capture_output=True, text=True, timeout=240)
report = {'started_at': started, 'finished_at': time.time(), 'isolated_state': True,
    'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
    'source_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
        ('app.py', 'prompt_learning.py', 'crystal_prompts.py', 'crystal_contract.py', 'rejection_workbench.py',
         'crystal_rhyme.py', 'vendor/cmudict/cmudict.dict')}}
Path('docs/rejection-learning-python-tests.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(result.stdout[-2000:])
print(result.stderr[-14000:])
raise SystemExit(result.returncode)
