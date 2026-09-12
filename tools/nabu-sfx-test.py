"""Run the Python suite with isolated state and save its result, inside Docker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    started = time.time()
    with tempfile.TemporaryDirectory(prefix='pinebox-nabu-tests-') as state:
        env = dict(os.environ, SPARK_AGENT_DATA_DIR=state)
        result = subprocess.run(
            ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'],
            env=env, capture_output=True, text=True, timeout=240)
    report = {'started_at': started, 'finished_at': time.time(),
              'isolated_state': True, 'exit_code': result.returncode,
              'stdout': result.stdout, 'stderr': result.stderr,
              'source_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                  for name in ('app.py', 'nabu_audio.py', 'sfx_cadence.py', 'sfx_speech_bank.py')}}
    Path('docs/nabu-sfx-python-tests.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(result.stdout[-2000:])
    print(result.stderr[-14000:])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
