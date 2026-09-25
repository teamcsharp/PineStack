'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const M = require('../desktop/renderer/video-edit-model.js');
const fs = require('node:fs');
const path = require('node:path');

test('V2 track has a real disclosure control and timeline trim edges are draggable', () => {
  const root = path.join(__dirname, '..');
  const html = fs.readFileSync(path.join(root, 'desktop/renderer/video-editor.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'desktop/renderer/video-editor.css'), 'utf8');
  const js = fs.readFileSync(path.join(root, 'desktop/renderer/video-editor.js'), 'utf8');
  assert.match(html, /id="parodyOverlayToggle"[^>]+aria-expanded="true"[^>]+aria-controls="parodyOverlayTimeline"/);
  assert.match(js, /function setOverlayCollapsed\(collapsed\)/);
  assert.match(js, /parodyOverlayTimeline'\)\.hidden = overlayCollapsed/);
  assert.match(js, /handle\.addEventListener\('pointerdown'.*startEdgeTrim/);
  assert.match(js, /window\.addEventListener\('pointermove', move, \{passive: false\}\)/);
  assert.match(js, /trimReadout\.textContent = 'In '.*'   Out '.*'   Length '/);
  assert.match(js, /node\.setPointerCapture\(event\.pointerId\)/);
  assert.match(html, /id="parodyTrimFrame"/);
  assert.match(js, /function setTrimMode\(on\)/);
  assert.match(js, /function queueTrimFrame\(current\)/);
  assert.match(js, /trimPreviewTarget = \{clip: current, local: local,/);
  assert.match(js, /Math\.abs\(preview\.currentTime - pending\) > \.035/);
  assert.match(js, /sourcePreview\.pause\(\); overlayPreview\.pause\(\)/);
  assert.match(css, /\.parody-segment \.clip-edge\{[^}]*touch-action:none[^}]*cursor:ew-resize/);
  assert.match(css, /\.clip-trim-readout\{[^}]*ui-monospace/);
  assert.match(css, /\.parody-trim-frame\{/);
});

test('Electron bridge is preferred for GET and POST', async () => {
  const calls = [];
  const env = {desktop: {
    get: async path => (calls.push(['get', path]), {status: 'ready'}),
    post: async (path, body) => (calls.push(['post', path, body]), {status: 'queued'}),
  }, parentApi: async () => { throw new Error('parent must not run'); }};
  assert.equal((await M.editorRequest(env, 'GET', '/source')).status, 'ready');
  assert.equal((await M.editorRequest(env, 'POST', '/import', {clip_id: 'a'})).status, 'queued');
  assert.deepEqual(calls, [['get', '/source'], ['post', '/import', {clip_id: 'a'}]]);
});

test('embedded same-origin parent API receives serialized request options', async () => {
  const calls = [];
  const result = await M.editorRequest({parentApi: async (path, options) => {
    calls.push([path, options]); return {status: 'ready'};
  }}, 'POST', '/api/video-editor/library/import', {clip_id: 'abc'});
  assert.equal(result.status, 'ready');
  assert.deepEqual(calls, [['/api/video-editor/library/import', {method: 'POST', body: '{"clip_id":"abc"}'}]]);
});

test('PineTab same-origin API is used when there is no bridge or parent API', async () => {
  let called = false;
  const result = await M.editorRequest({sameOriginApi: async (path, options) => {
    called = path === '/api/video-editor/library?q=voice&limit=40' && options.method === 'GET';
    return {clips: []};
  }}, 'GET', '/api/video-editor/library?q=voice&limit=40');
  assert.equal(called, true); assert.deepEqual(result, {clips: []});
});

test('raw fetch fallback carries auth, save permit and useful HTTP errors', async () => {
  const calls = [];
  const result = await M.editorRequest({key: 'station-key', fetch: async (path, options) => {
    calls.push([path, options]); return {ok: true, status: 200, json: async () => ({id: 'export'})};
  }}, 'POST', '/api/video-editor/splice-exports', {save_token: 'permit'});
  assert.equal(result.id, 'export');
  assert.equal(calls[0][1].headers.Authorization, 'Bearer station-key');
  assert.equal(calls[0][1].headers['X-Pine-Save-Token'], 'permit');
  await assert.rejects(M.editorRequest({fetch: async () => ({ok: false, status: 503,
    json: async () => ({detail: 'editor warming'})})}, 'GET', '/source'), error => error.status === 503 && /warming/.test(error.message));
});
