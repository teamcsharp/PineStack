"""Apply the operator's SFX cadence and Nabu DJ route; preserve other settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request


CHANGES = {
    'sfx': True, 'sfx_every_units': 2, 'sfx_rate': 1.0, 'sfx_gap': 3,
    'sfx_make': False, 'sfx_max_seconds': 4.0,
    'sfx_folders': ['samples_grabbed'], 'sfx_drop_folders': ['samples_grabbed'],
    'sfx_rescan_seconds': 60, 'sfxguy_rate': 100, 'sfxguy_every_units': 4,
    'nabu_music_level': 0.0, 'music_box_level': 0.0, 'nabu_voice_level': 1.0,
}


def request(path, body=None, method=None):
    if body is not None and path not in ('/api/settings', '/api/dj/output'):
        raise ValueError('Only requested settings and output may be changed.')
    req = urllib.request.Request('http://127.0.0.1:8096' + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + os.environ['SPARK_AGENT_API_KEY'],
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def route(state):
    return {k: state.get(k) for k in ('on', 'paused', 'music_to', 'voice_to',
                                    'reply_to', 'voice_device', 'box_talk')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', required=True)
    parser.add_argument('--output', default='docs/nabu-sfx-deployment.json')
    args = parser.parse_args()
    out = Path(args.output)
    report = {'started_at': time.time(), 'requested_settings': CHANGES,
              'requested_route': {'voice': 'nabu', 'music': 'nabu', 'box_talk': True,
                                  'music_level': 0.0, 'voice_level': 1.0},
              'test_playback_requests': 0, 'review_votes': 0, 'direct_model_requests': 0}
    def save():
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        before = request('/api/settings')
        report['route_before'] = route(request('/api/dj'))
        report['settings_before'] = {k: before['dj'].get(k) for k in CHANGES}
        report['source_sha256'] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in ('app.py', 'sfx_cadence.py', 'sfx_speech_bank.py', 'nabu_audio.py',
                         'desktop/renderer/renderer.js', 'package.json')}
        save()
        wanted = json.loads(json.dumps(before))
        wanted['dj'].update(CHANGES)
        result = request('/api/settings', wanted, 'PUT')
        report['settings_after'] = {k: result['dj'].get(k) for k in CHANGES}
        assert report['settings_after'] == CHANGES, 'Requested SFX settings were not retained.'
        other_changes = [k for k in set(before['dj']) | set(result['dj'])
                         if k not in CHANGES and before['dj'].get(k) != result['dj'].get(k)]
        report['unrequested_dj_setting_keys_changed'] = other_changes
        assert not other_changes, 'An unrelated DJ setting changed.'
        output_result = request('/api/dj/output', report['requested_route'], 'POST')
        report['route_after'] = route(output_result)
        report['mix_applied'] = output_result.get('mix_applied', {})
        assert report['mix_applied'].get('music', {}).get('ok') is True, 'Nabu music adjustment failed.'
        assert report['mix_applied'].get('voice', {}).get('ok') is True, 'Nabu DJ adjustment failed.'
        assert report['route_after']['voice_to'] == 'box'
        assert report['route_after']['voice_device'] == 'nabu'
        assert report['route_after']['box_talk'] is True
        assert all(report['route_after'][k] == report['route_before'][k]
                   for k in ('on', 'paused', 'reply_to'))
        assert report['route_after']['music_to'] == 'box'
        report['learning_after'] = {k: v for k, v in
            request('/api/orchestrator/prompt-learning')['status'].items()
            if k in ('enabled', 'mode', 'revision', 'automation_paused')}
        report['ok'] = True
        report['finished_at'] = time.time()
        save()
        print(json.dumps(report, ensure_ascii=False))
    except Exception as exc:
        report['ok'] = False
        report['error'] = type(exc).__name__ + ': ' + str(exc)[:200]
        save()
        raise


if __name__ == '__main__':
    main()
