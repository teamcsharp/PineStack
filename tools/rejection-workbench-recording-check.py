"""GET-only recording observations; contains no trigger, vote or playback APIs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request


def snapshot(base, phase):
    headers = {'Authorization': 'Bearer ' + os.environ.get('SPARK_AGENT_API_KEY', '')}
    def get(path):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=30) as response:
            return json.load(response)
    room = get('/api/recording-room')
    logic = get('/api/orchestrator/logic')
    pantry = get('/api/pantry/table?most=1000')
    flow = get('/api/dj/flow')
    pantry_rows = []
    data_dir = Path(os.environ.get('SPARK_AGENT_DATA_DIR', '/app/data'))
    media_dir = data_dir / 'voice_media'
    try:
        saved_pantry = json.loads((data_dir / 'pantry.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        saved_pantry = {}
    for row in pantry.get('rows', []):
        name = str(row.get('media') or '').rsplit('/', 1)[-1].split('?', 1)[0]
        item = {k: row.get(k) for k in ('key', 'kind', 'who', 'seconds', 'bytes', 'at', 'used')}
        item['media_id'] = hashlib.sha256(name.encode()).hexdigest()[:24] if name else ''
        saved_clip = (saved_pantry.get(row.get('key')) or {}).get('clip') or {}
        if name and str(saved_clip.get('path') or '').rsplit('/', 1)[-1] == name:
            item.update(render_ms=saved_clip.get('ms'), engine=saved_clip.get('engine'),
                        cached=bool(saved_clip.get('cached')), receipt_matches_media=True)
        try:
            stat = (media_dir / name).stat() if name else None
            item.update(media_mtime=stat.st_mtime if stat else None, media_bytes=stat.st_size if stat else 0)
        except OSError:
            item.update(media_mtime=None, media_bytes=0)
        pantry_rows.append(item)
    recent = [{k: row.get(k) for k in ('at', 'who', 'engine', 'chars', 'seconds', 'ms', 'cost', 'how')}
              for row in room.get('recent', [])]
    health = flow.get('health') or {}
    result = {'phase': phase, 'at': time.time(), 'utc': datetime.now(timezone.utc).isoformat(),
        'on': logic.get('on'), 'paused': logic.get('paused'),
        'hours_ready': logic.get('hours_ready'), 'target_hours': logic.get('target_hours'),
        'pipeline': logic.get('pipeline'), 'booths': room.get('booths'),
        'preparing': {k: (room.get('preparing') or {}).get(k) for k in ('kind', 'stage', 'at', 'made', 'lines', 'ago')},
        'writers': room.get('writers'), 'shelf': room.get('shelf'),
        'playback_takes': room.get('takes'), 'playback_shelf_served': room.get('shelf_served'),
        'playback_recent_how': dict(Counter(row.get('how') or 'unknown' for row in recent)),
        'playback_recent': recent,
        'pantry': {'total': pantry.get('takes'), 'shown': len(pantry_rows), 'rows': pantry_rows},
        'air': {k: health.get(k) for k in ('on', 'talk_gap_seconds', 'talk_gap_target', 'floor_busy', 'last_speech')},
        'file_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                        for name in ('app.py', 'line_review.py', 'rejection_workbench.py')}}
    # Diagnostics currently contain only stage/count data; explicitly keep those
    # fields so future detailed additions cannot leak scripts into this report.
    result['pipeline'] = {k: (logic.get('pipeline') or {}).get(k) for k in
                         ('at', 'total', 'stages', 'roads', 'bottleneck', 'next_step', 'recording_waiting', 'tint_waiting')}
    try:
        proc = Path('/proc/1/stat').read_text().rsplit(')', 1)[1].split()
        boot = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines()
                    if line.startswith('btime '))
        result['container_start_epoch'] = boot + int(proc[19]) / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, IndexError, StopIteration):
        result['container_start_epoch'] = None
    return result


def summarize(data):
    rows = data.get('snapshots') or []
    before = next((r for r in reversed(rows) if r.get('phase') == 'before'), None)
    after = [r for r in rows if r.get('phase') == 'after']
    if not before or not after:
        return {'state': 'awaiting_after' if before else 'awaiting_baseline'}
    baseline_media = {r.get('media_id') for r in before['pantry']['rows']}
    window_start = max(before['at'], after[0].get('container_start_epoch') or 0)
    new_media = {}
    for snap in after:
        for row in snap['pantry']['rows']:
            if row.get('media_id') not in baseline_media and (row.get('media_mtime') or 0) > window_start and row.get('media_bytes', 0) > 0:
                new_media[row['media_id']] = row
    fresh = [r for r in new_media.values() if r.get('receipt_matches_media') and
             (r.get('render_ms') or 0) > 0 and not r.get('cached')]
    return {'state': 'observed', 'before_utc': before['utc'], 'last_utc': after[-1]['utc'],
        'after_samples': len(after), 'fresh_window_start_epoch': window_start,
        'new_pantry_media_since_deployment_or_baseline': len(new_media),
        'new_media_by_kind': dict(Counter(row.get('kind') or 'unknown' for row in new_media.values())),
        'new_media_seconds': round(sum(row.get('seconds') or 0 for row in new_media.values()), 2),
        'new_media_with_positive_synthesis_receipt': len(fresh),
        'fresh_receipts_by_kind': dict(Counter(row.get('kind') or 'unknown' for row in fresh)),
        'fresh_receipts_by_engine': dict(Counter(row.get('engine') or 'unknown' for row in fresh)),
        'preparation_active_samples': sum((row.get('booths') or {}).get('preparing', 0) > 0 for row in after),
        'before_stages': before['pipeline'].get('stages'), 'latest_stages': after[-1]['pipeline'].get('stages'),
        'limits': ['The playback take ledger excludes off-air preparation; shelf serves are not new synthesis.',
                   'Fresh synthesis receipts require a new media file plus matching persisted clip, positive render milliseconds and no cached flag; other new files are reported separately.',
                   'The API returns the newest 400 pantry entries; older rows and short renders between samples may be missed.',
                   'Concurrent playback, writing and operator pause changes can change inventory independently of this deployment.']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8096')
    parser.add_argument('--phase', required=True, choices=('before', 'after'))
    parser.add_argument('--output', default='docs/rejection-workbench-recording-check.json')
    args = parser.parse_args()
    path = Path(args.output)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'method': 'Authenticated GET-only API and local media stat observations; no production controls used.', 'snapshots': []}
    item = snapshot(args.base_url, args.phase)
    data['snapshots'].append(item)
    data['summary'] = summarize(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'phase': item['phase'], 'utc': item['utc'], 'paused': item['paused'],
        'booths': item['booths'], 'stages': item['pipeline'].get('stages'),
        'playback_takes': item['playback_takes'], 'playback_shelf_served': item['playback_shelf_served'],
        'pantry_shown': item['pantry']['shown'], 'summary': data['summary']}))


if __name__ == '__main__':
    main()
