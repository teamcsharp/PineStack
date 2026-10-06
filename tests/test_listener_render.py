"""Run the real listener render/auth functions without booting the station."""
import ast
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any
import unittest
from unittest import mock
from urllib.parse import quote
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse, Response
from starlette.requests import Request


def function_source(source, name):
    match = re.search(r'^(?:async )?def ' + re.escape(name) + r'\(', source, re.M)
    if not match:
        raise AssertionError('Missing real function: ' + name)
    following = re.search(r'^(?:@app\.|(?:async )?def |[A-Z_][A-Z_0-9]*\s*=)',
                          source[match.end():], re.M)
    return source[match.start():match.end() + following.start()] if following else source[match.start():]


class ListenerRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        # Parse only the actual template/functions. The full 13 MB station
        # AST made these small checks take two minutes before any test ran.
        opening = re.search(r'^RADIO_PAGE_HTML\s*=\s*(r?"""|r?\'\'\')', source, re.M)
        delimiter = opening.group(1)[-3:]
        end = source.index(delimiter, opening.end()) + len(delimiter)
        cls.template = ast.literal_eval(source[opening.start(1):end])
        names = ('require_auth', 'listen_token', 'token_scope', 'full_ok',
                 '_listener_media_token', 'listener_media_token_api', 'radio_page', 'tune_page')
        cls.code = compile('\n\n'.join(function_source(source, name) for name in names),
                           'listener-routes', 'exec')

    def routes(self, road):
        env = dict(Request=Request, Response=Response, HTMLResponse=HTMLResponse,
                   Header=Header, HTTPException=HTTPException, Any=Any,
                   json=json, quote=quote, time=time, uuid=uuid, hmac=hmac, hashlib=hashlib,
                   SPARK_AGENT_API_KEY='test-key', AUTOFILL_KEY=False,
                   RADIO_PAGE_HTML=self.template, CONTROL_PANEL_HTML='<html>panel</html>',
                   LINK_GONE_HTML='<html>expired</html>', _BUILD_MS=12345,
                   SHARE_SCOPES=('listen', 'full'), share_epoch=lambda: 1,
                   share_revoked=lambda: frozenset(), _request_road=lambda request: road)
        exec(self.code, env)
        return env

    def request(self, public=False):
        return Request({'type': 'http', 'headers': [(b'x-pinebox-public', b'1')] if public else []})

    def check_render(self, response, away, road):
        text = response.body.decode()
        self.assertNotRegex(text, r'__[A-Z][A-Z_]+__', 'a bare placeholder can abort all playback')
        self.assertIn('const AWAY = ' + ('true' if away else 'false') + ';', text)
        self.assertIn('const ROAD = "' + road + '";', text)
        self.assertIn('no-store', response.headers['cache-control'])

    def test_unsigned_radio_renders_all_values_without_minting_read_access(self):
        for road in ('house', 'lan', 'tailnet', 'funnel'):
            env = self.routes(road)
            mint = mock.Mock(side_effect=AssertionError('AUTOFILL=false cannot mint media access'))
            env['_listener_media_token'] = mint
            result = asyncio.run(env['radio_page'](self.request()))
            self.check_render(result, road in ('tailnet', 'funnel'), road)
            self.assertIn('MEDIA_TOKEN = ""', result.body.decode())
            mint.assert_not_called()

    def test_operator_radio_mints_a_listen_only_capability_for_native_media(self):
        env = self.routes('lan')
        env['AUTOFILL_KEY'] = True
        result = asyncio.run(env['radio_page'](self.request()))
        self.check_render(result, False, 'lan')
        token = re.search(r'MEDIA_TOKEN = "([^"\n]+)"', result.body.decode()).group(1)
        self.assertEqual(env['token_scope'](token), 'listen')
        self.assertFalse(env['full_ok'](token))
        self.assertNotIn('test-key', token)
        self.assertRegex(token.split('.')[1], r'^[a-f0-9]{12}$')
        expires = int(token.split('.')[0])
        self.assertAlmostEqual(expires - time.time(), 30 * 86400, delta=2)

    def test_signed_tailnet_and_public_links_keep_the_existing_expiry(self):
        for road, public in [('house', False), ('tailnet', False), ('funnel', True)]:
            env = self.routes(road)
            token = env['listen_token'](int(time.time()) + 60, 'abcd1234', scope='listen')
            env['_listener_media_token'] = mock.Mock(side_effect=AssertionError('Guests cannot extend expiry'))
            result = asyncio.run(env['tune_page'](token, self.request(public)))
            self.check_render(result, public or road == 'tailnet', road)
            text = result.body.decode()
            self.assertIn('/manifest.webmanifest?t=' + token, text)
            self.assertIn('MEDIA_TOKEN = "' + token + '"', text)
            env['_listener_media_token'].assert_not_called()

    def test_media_token_api_rejects_unauthenticated_and_listen_only_callers(self):
        env = self.routes('lan')
        guest = env['listen_token'](int(time.time()) + 60, 'abcd1234', scope='listen')
        for authorization in (None, 'Bearer wrong', 'Bearer ' + guest):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(env['listener_media_token_api'](Response(), authorization=authorization))
            self.assertEqual(raised.exception.status_code, 401)

    def test_media_token_api_uses_operator_auth_and_prevents_caching(self):
        env = self.routes('lan')
        response = Response()
        result = asyncio.run(env['listener_media_token_api'](response, authorization='Bearer test-key'))
        self.assertEqual(env['token_scope'](result['token']), 'listen')
        self.assertEqual(result['expires'], int(result['token'].split('.')[0]))
        self.assertEqual(response.headers['cache-control'], 'no-store')
        env['share_revoked'] = lambda: frozenset({result['token'].split('.')[1]})
        self.assertEqual(env['token_scope'](result['token']), '')
        env['share_revoked'] = lambda: frozenset()
        env['share_epoch'] = lambda: 2
        self.assertEqual(env['token_scope'](result['token']), '')

    def test_media_token_helper_returns_empty_when_no_server_key_is_configured(self):
        env = self.routes('lan')
        env['SPARK_AGENT_API_KEY'] = ''
        self.assertEqual(env['_listener_media_token'](), '')

    def test_native_media_token_endpoint_is_registered_as_a_protected_noncacheable_get(self):
        env = self.routes('lan')
        app = FastAPI()
        app.add_api_route('/api/listener/media-token', env['listener_media_token_api'], methods=['GET'])
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/listener/media-token').status_code, 401)
            response = client.get('/api/listener/media-token', headers={'Authorization': 'Bearer test-key'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(env['token_scope'](response.json()['token']), 'listen')


if __name__ == '__main__':
    unittest.main()
