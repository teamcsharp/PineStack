import pytest
from fastapi.testclient import TestClient
import app


def test_media_signed_ranges_missing_and_invalid(tmp_path, monkeypatch):
    video = tmp_path / 'sample.mp4'
    video.write_bytes(b'0123456789')
    monkeypatch.setattr(app, 'comfy_output_find', lambda name: video if name == video.name else None)
    monkeypatch.setattr(app, 'SPARK_AGENT_API_KEY', 'test-secret')
    def unauthorized(*_):
        raise app.HTTPException(401, 'Unauthorized')
    monkeypatch.setattr(app, 'require_listen_auth', unauthorized)
    client = TestClient(app.app)
    url = '/api/generations/media/sample.mp4?t=' + app.media_sign('gen:sample.mp4')
    got = client.get(url, headers={'Range':'bytes=2-5'})
    assert got.status_code == 206 and got.content == b'2345'
    assert got.headers['content-range'] == 'bytes 2-5/10'
    assert got.headers['content-type'] == 'video/mp4'
    assert client.get(url, headers={'Range':'bytes=20-30'}).status_code == 416
    assert client.get(url, headers={'Range':'bytes=-3'}).content == b'789'
    assert client.get(url.replace('sample.mp4?', 'missing.mp4?')).status_code == 401
    assert client.get('/api/generations/media/missing.mp4?t=' + app.media_sign('gen:missing.mp4')).status_code == 404


def test_gallery_cursor_survives_new_renders_and_filters_before_paging(monkeypatch):
    records = [{'prompt_id':str(i),'status':'done','purpose':'voice_ad' if i % 2 else 'gallery','files':[str(i)+'.png']} for i in range(1100)]
    monkeypatch.setattr(app, '_read_all_generations', lambda:records)
    first = app.generation_history_page(purpose='voice_ad', limit=30)
    records.append({'prompt_id':'new','status':'done','purpose':'voice_ad','files':['new.mp4']})
    second = app.generation_history_page(first['next'],'voice_ad',30)
    assert first['generations'][-1]['prompt_id'] == '1041'
    assert second['generations'][0]['prompt_id'] == '1039'
    seen = set()
    page = first
    while page['generations']:
        seen.update(r['prompt_id'] for r in page['generations'])
        if not page['next']:
            break
        page = app.generation_history_page(page['next'],'voice_ad',30)
    assert len(seen) == 550 and '1' in seen
    with pytest.raises(app.HTTPException):
        app.generation_history_page('deleted')
