const assert = require('node:assert/strict');
const {test} = require('node:test');
const actions = require('../desktop/renderer/line-actions.js');

const line = {id: 'spoken-line', said: 'A spoken sentence.'};
const stage = {say() {}};

test('make ad requests random SFX with music off and needs explicit confirmation', async () => {
  let request;
  globalThis.pineDesktop = {post: async (route, body) => {
    request = {route, body};
    return {ok: true, music: false, auto_air: true, scheduled: true, ad_id: 'spot-1',
      sfx_id: 'clip-1', say: 'spot ready'};
  }};
  assert.deepEqual(await actions.makeAdFromLine(line, stage),
    {ok: true, then: 'spot ready'});
  assert.deepEqual(request, {route: '/api/line-actions/make-ad',
    body: {line_id: 'spoken-line', sfx: 'random', music: false}});
  globalThis.pineDesktop.post = async () => ({ok: true});
  assert.equal((await actions.makeAdFromLine(line, stage)).ok, false);
  globalThis.pineDesktop.post = async () => ({ok: true, music: false, ad_id: 'spot-2'});
  assert.equal((await actions.makeAdFromLine(line, stage)).ok, false);
  globalThis.pineDesktop.post = async () => ({ok: true, music: false,
    auto_air: true, scheduled: false, ad_id: 'spot-3', sfx_id: 'clip-3'});
  assert.equal((await actions.makeAdFromLine(line, stage)).ok, false);
  delete globalThis.pineDesktop;
});

test('spoken-line actions follow dialogue identity, never a clip or record', () => {
  const node = (classes, dataset = {}) => ({dataset, classList: {
    contains(name) { return classes.includes(name); }
  }});
  assert.equal(actions.spokenLine({id: 'live', node: node(['sp-saying'],
    {spoken: 'true'})}, null), true);
  assert.equal(actions.spokenLine({id: 'script', node: node(['sp-el', 'sp-dialogue'])}, null), true);
  assert.equal(actions.spokenLine({id: 'prepared', node: node([], {dialogueId: 'turn-1'})}, null), true);
  assert.equal(actions.spokenLine({id: 'clip', node: node(['sp-saying'],
    {spoken: 'false'})}, null), false);
  assert.equal(actions.spokenLine({id: 'record', node: node(['sp-el', 'sp-action'])}, null), false);
  assert.equal(actions.spokenLine({id: 'effect', node: node(['sp-el', 'sp-dialogue'])},
    {sfx: 'effect.mp4'}), false);
});

test('the live strip exposes the spoken line and its words to the hold sheet', () => {
  const strip = {dataset: {line: 'spoken-line', spoken: 'true'},
    textContent: 'Host A spoken sentence.',
    querySelector() { return {textContent: 'A spoken sentence.'}; }};
  const found = actions.lineAt({closest() { return strip; }});
  assert.equal(found.id, 'spoken-line');
  assert.equal(found.said, 'A spoken sentence.');
  assert.equal(actions.spokenLine(found, null), true);
  strip.dataset.spoken = 'false';
  assert.equal(actions.spokenLine(found, null), false);
});

test('dry voice save refuses inexact source and saves only confirmed route', async () => {
  let saved = 0;
  globalThis.pineDesktop = {
    post: async () => ({ok: true, exact: false, voice_only: true,
      route: '/api/booth/clip?line=spoken-line'}),
    keepClip: async () => { saved += 1; return {ok: true, where: 'recordings'}; }
  };
  assert.equal((await actions.saveDryVoice(line, stage)).ok, false);
  assert.equal(saved, 0);
  globalThis.pineDesktop.post = async () => ({ok: true, exact: true,
    voice_only: true, route: '/api/line-actions/dry-voice/file/spoken-line'});
  assert.deepEqual(await actions.saveDryVoice(line, stage),
    {ok: true, then: 'dry voice saved to recordings'});
  assert.equal(saved, 1);
  delete globalThis.pineDesktop;
});
