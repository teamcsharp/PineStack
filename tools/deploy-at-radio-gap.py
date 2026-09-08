"""Explicit backend restart at an observed quiet radio handoff; run on Docker host."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--restart', action='store_true', required=True)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--output', default='docs/prompt-learning-restart.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output
    report = {'started_at': time.time(), 'method': 'Observe existing audio state; restart once after a quiet handoff.',
              'playback_controls': 0, 'samples': [], 'restart_requested': False}
    check = ['docker', 'exec', 'spark-agent', 'python',
             'tools/rejection-review-live-check.py', '--before', '--require-quiet']
    deadline = time.monotonic() + max(1, args.seconds)
    next_log = 0
    while time.monotonic() < deadline:
        read = subprocess.run(check, capture_output=True, text=True, timeout=35)
        try:
            state = json.loads(read.stdout)
        except (ValueError, TypeError):
            state = {'at': time.time(), 'unavailable': True}
        if time.monotonic() >= next_log or read.returncode == 0:
            report['samples'].append(state)
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(state), flush=True)
            next_log = time.monotonic() + 15
        if read.returncode == 0 and not state.get('unavailable'):
            report['quiet_before_restart'] = state
            report['restart_requested'] = True
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            result = subprocess.run(['docker', 'restart', '--timeout', '30', 'spark-agent'],
                                    capture_output=True, text=True, timeout=100)
            report['restart_exit_code'] = result.returncode
            report['restart_finished_at'] = time.time()
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({'restart_exit_code': result.returncode, 'finished_at': report['restart_finished_at']}), flush=True)
            if result.returncode:
                raise SystemExit('Backend restart failed; inspect container state.')
            return
        time.sleep(.15)
    report['timed_out'] = True
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise SystemExit('No quiet handoff observed; no restart performed.')


if __name__ == '__main__':
    main()
