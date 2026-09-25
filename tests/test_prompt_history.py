import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from prompt_history import History, apply_config, configuration, install


def test_durable_text_capture_pagination_and_models(tmp_path):
    history = History(tmp_path / 'history.sqlite3')
    body = {'model': 'writer', 'messages': [{'role': 'system', 'content': 'Exact system prompt'},
            {'role': 'user', 'content': 'Question', 'images': ['binary']}], 'options': {'seed': 123}}
    first = history.start(body, 'banter', {'dj': {'chattiness': 0.5}})
    history.finish(first, {'message': {'role': 'assistant', 'content': 'Full answer'}})
    second = history.start({**body, 'model': 'vision'}, 'vision', {})
    reopened = History(history.path)
    page = reopened.page(limit=1)
    assert page['rows'][0]['id'] == second
    assert reopened.page(before=page['next'])['rows'][0]['id'] == first
    assert len(reopened.page(model='writer')['rows']) == 1
    detail = reopened.detail(first)
    assert detail['request']['messages'][0]['content'] == 'Exact system prompt'
    assert detail['request']['messages'][1]['images'] == [{'omitted_binary_image': True}]
    assert body['messages'][1]['images'] == ['binary']
    assert detail['response']['message']['content'] == 'Full answer'
    assert detail['properties']['dj']['chattiness'] == 0.5


def test_failures_preserve_original_inference_behavior(tmp_path):
    history = History(tmp_path / 'history.sqlite3')
    client = Mock(post=AsyncMock(side_effect=TimeoutError('model timeout')))
    with pytest.raises(TimeoutError):
        asyncio.run(history.post(client, 'ollama', json={'model':'writer','prompt':'hello'}, context=lambda:{}))
    assert history.page()['rows'][0]['state'] == 'failed'
    history.start = Mock(side_effect=OSError('disk full'))
    client.post = AsyncMock(return_value=Mock(status_code=200, json=lambda:{'response':'works'}))
    result = asyncio.run(history.post(client, 'ollama', json={'prompt':'hello'}, context=lambda:{}))
    assert result.json()['response'] == 'works'
    assert 'capture failed' in history.last_error


def test_routes_require_auth_and_report_missing_records(tmp_path):
    app = FastAPI()
    def auth(header):
        if header != 'Bearer test':
            raise HTTPException(401, 'Unauthorized')
    install(app, {'require_read_auth':auth,'require_auth':auth}, History(tmp_path / 'history.db'))
    client = TestClient(app)
    assert client.get('/api/prompt-history').status_code == 401
    assert client.get('/api/prompt-history/missing',headers={'Authorization':'Bearer test'}).status_code == 404


def test_live_registry_and_conflict_checked_edit(tmp_path, monkeypatch):
    import app
    settings = app.validate_settings({'prompts':[{'name':'Test','prompt':'Test system prompt'}]})
    monkeypatch.setattr(app, 'load_settings', lambda: settings)
    save = Mock()
    monkeypatch.setattr(app, 'save_settings', save)
    nodes = configuration(vars(app))['nodes']
    node = next(n for n in nodes if n['path'] == ['dj','chattiness'])
    assert node['min'] == 0 and node['max'] == 1
    history = History(tmp_path / 'history.db')
    with pytest.raises(RuntimeError):
        apply_config(vars(app), history, {'path':node['path'],'was':'stale','value':0.4})
    with pytest.raises(ValueError):
        apply_config(vars(app), history, {'path':node['path'],'was':node['value'],'value':float('nan')})
    assert not save.called
    result = apply_config(vars(app), history, {'path':node['path'],'was':node['value'],'value':0.4})
    assert result['ok'] and save.call_args.args[0]['dj']['chattiness'] == 0.4
