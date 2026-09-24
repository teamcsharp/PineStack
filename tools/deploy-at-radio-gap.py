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
    # #1080: a compose environment change (OLLAMA_LANES) only reaches the
    # container when it is recreated; `docker restart` keeps the old env.
    parser.add_argument('--recreate', action='store_true',
                        help='docker compose up -d --force-recreate spark-agent instead of docker restart')
    parser.add_argument('--preserve-page', action='store_true',
                        help='retain pending page audio for replay after restart')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output
    if args.recreate:
        restart_command = ['docker', 'compose', '-f', str(root.parent / 'compose.yaml'),
                           'up', '-d', '--force-recreate', 'spark-agent']
    else:
        restart_command = ['docker', 'restart', '--timeout', '30', 'spark-agent']
    report = {'started_at': time.time(), 'method': 'Observe existing audio state; restart once after a quiet handoff.',
              'command': ' '.join(restart_command),
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
            if args.preserve_page:
                backup_code = '''
import json, os, urllib.request
from pathlib import Path

with urllib.request.urlopen("http://127.0.0.1:8096/api/dj/voice?since=0", timeout=20) as response:
    feed = json.load(response)
now = int(feed["server_ms"])
clips = [row for row in feed.get("clips", [])
         if isinstance(row, dict) and row.get("delivery_id") and row.get("url")
         and int(row.get("broadcast_ms") or 0) >= now - 45000][-120:]
path = Path(os.getenv("SPARK_AGENT_DATA_DIR", "/app/data")) / "page_delivery_recovery.json"
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps({"reason": "Pending page audio retained at quiet deploy",
                                 "clips": clips}, ensure_ascii=False), encoding="utf-8")
os.replace(temporary, path)
print(json.dumps({"clips": len(clips), "path": str(path)}))
'''
                backup = subprocess.run(
                    ['docker', 'exec', '-i', 'spark-agent', 'python', '-'],
                    input=backup_code, capture_output=True, text=True, timeout=35)
                if backup.returncode:
                    raise SystemExit('Page audio preservation failed; no restart performed: '
                                     + backup.stderr[-500:])
                report['page_preservation'] = json.loads(backup.stdout)
            report['restart_requested'] = True
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            result = subprocess.run(restart_command,
                                    capture_output=True, text=True, timeout=240)
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
