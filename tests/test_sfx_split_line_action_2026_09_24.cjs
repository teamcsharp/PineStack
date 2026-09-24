const assert = require('node:assert/strict');
const {test} = require('node:test');
const actions = require('../desktop/renderer/line-actions.js');

test('script SFX edit opens the exact clip in the editor', async () => {
  const sent = [];
  const opened = [];
  globalThis.pineDesktop = {post: async (route, body) => {
    sent.push({route, body});
    return {ok: true, editor_url: '/video-editor/?source=' + 'a'.repeat(32) + '&sfx=1'};
  }};
  globalThis.PineSfxTv = {openEditor: (path, name) => opened.push({path, name})};
  const result = await actions.editSfx({id: 'line-5'},
    {sfx: 'clip-2', line: 'line-5', name: 'Long sting'}, {say() {}});
  assert.equal(result.ok, true);
  assert.deepEqual(sent, [{route: '/api/sfx/edit/open', body: {
    clip: 'clip-2', line: 'line-5', name: 'Long sting'}}]);
  assert.deepEqual(opened, [{path: '/video-editor/?source=' + 'a'.repeat(32) + '&sfx=1',
    name: 'Long sting'}]);
  delete globalThis.pineDesktop;
  delete globalThis.PineSfxTv;
});

test('script SFX edit falls back to line identity and reports missing editor', async () => {
  globalThis.pineDesktop = {post: async (route, body) => {
    assert.equal(body.line, 'line-6');
    assert.equal(body.clip, '');
    return {editor_url: '/video-editor/?source=' + 'b'.repeat(32) + '&sfx=1'};
  }};
  assert.equal((await actions.editSfx({id: 'line-6'},
    {sfx: '', name: 'Cue'}, {say() {}})).ok, false);
  delete globalThis.pineDesktop;
});
