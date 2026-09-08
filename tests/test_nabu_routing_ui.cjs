const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/renderer.js'), 'utf8');
function harness() {
  const calls = [], paints = [], notes = [];
  let finishRefresh;
  const context = {lastRouting: {voice_to: 'here', music_to: 'here', reply_to: 'here',
      voice_device: 'nabu', box_talk: false},
    api: {async post(url, body) { calls.push({url, body}); return {voice_to: 'box',
      music_to: 'here', reply_to: 'here', voice_device: 'nabu', box_talk: true}; }},
    paintStreamRoutes(r) { paints.push({...r}); }, paintNabuMix() {}, syncBroadcastFromServer() {},
    rerouteAudioNow() { calls.push('reroute'); }, noteRouteOk(s) { notes.push(s); },
    noteRouteError(s) { throw new Error(s); },
    refresh() { return new Promise(resolve => { finishRefresh = resolve; }); }};
  vm.createContext(context);
  const start = source.indexOf('async function setStreamRoute(');
  const end = source.indexOf('function initStreamRoutes(', start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  return {context, calls, paints, notes, finish: () => finishRefresh()};
}
test('confirmed DJ route changes local audio before the slow diagnosis completes', async () => {
  const h = harness();
  const pending = h.context.setStreamRoute('voice', 'box');
  await new Promise(setImmediate);
  assert.equal(h.context.lastRouting.voice_to, 'box');
  assert.equal(h.context.lastRouting.box_talk, true);
  assert.ok(h.calls.includes('reroute'));
  assert.match(h.notes[0], /Nabu/);
  assert.equal(h.calls[0].body.voice, 'box');
  assert.equal(Object.keys(h.calls[0].body).length, 1);
  h.finish();
  await pending;
});
test('server route response preserves unrelated dial ownership and accepts nested state', () => {
  const h = harness();
  h.context.lastRouting.music_control = false;
  h.context.acceptRoutingResponse({routing: {voice_to: 'here', box_talk: false}});
  assert.equal(h.context.lastRouting.music_control, false);
  assert.equal(h.context.lastRouting.voice_device, 'nabu');
  assert.equal(h.context.lastRouting.box_talk, false);
  assert.equal(h.calls.filter(c => c.url).length, 0);
});
test('a malformed route response cannot replace confirmed routing', () => {
  const h = harness();
  h.context.acceptRoutingResponse({ok: false});
  assert.equal(h.context.lastRouting.voice_to, 'here');
  assert.equal(h.calls.length, 0);
});
test('broadcast selector relies on bounded route wake and does not initialize or speak', async () => {
  const h = harness();
  Object.assign(h.context, {ROUTES: {nabu: {label: 'Nabu', voice: 'box', music: 'box',
    reply: 'box', voice_device: 'nabu', box_talk: true}}, broadcastChanging: false,
    setDesiredBroadcast() {}, setText() {}, syncEmbeddedBroadcast() {}, applyAppVolume() {},
    pollDesktopRadio: async () => {}, refresh: async () => {}});
  const start = source.indexOf('async function setBroadcastTarget(');
  const end = source.indexOf('async function applyDefaultBroadcast(', start);
  vm.runInContext(source.slice(start, end), h.context);
  await h.context.setBroadcastTarget('nabu');
  assert.deepEqual(h.calls.filter(c => c.url).map(c => c.url), ['/api/dj/output']);
  assert.equal(h.context.broadcastChanging, false);
});
