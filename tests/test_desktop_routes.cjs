const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/renderer.js'), 'utf8');
const functions = source.slice(source.indexOf('function routeKeyFromState('), source.indexOf('function setDesiredBroadcast('));
function desktop() {
  const select = {value: 'app'};
  const context = {ROUTES: {app: {}, nabu: {}, box: {}, web: {}}, desiredBroadcast: 'app', broadcastChanging: false,
    document: {activeElement: null}, labels: {}, postCalls: 0,
    $: (id) => id === 'broadcastTarget' ? select : null};
  context.setText = (id, value) => { context.labels[id] = value; };
  context.setDesiredBroadcast = (value) => { context.desiredBroadcast = value; };
  context.api = {post() { context.postCalls++; throw new Error('A display refresh must never write routes.'); }};
  vm.createContext(context); vm.runInContext(functions, context);
  return {context, select};
}
const nabu = {music_to: 'box', voice_to: 'box', reply_to: 'box', voice_device: 'nabu', box_talk: true, on: true};
test('desktop displayed preset follows a backend route change without writing routes', () => {
  const {context, select} = desktop();
  context.syncBroadcastFromServer({routing: nabu});
  assert.equal(context.desiredBroadcast, 'nabu'); assert.equal(select.value, 'nabu');
  assert.match(context.labels.routeSummary, /Music: Nabu\nDJs: Nabu\nReplies: Nabu/);
  context.syncBroadcastFromServer({routing: {...nabu, music_to: 'here', voice_to: 'here', reply_to: 'here'}});
  assert.equal(select.value, 'app'); assert.match(context.labels.routeSummary, /Nabu: not routed/);
  assert.equal(context.postCalls, 0);
});
test('mixed routes do not claim the whole station uses the named device', () => {
  const {context, select} = desktop();
  context.syncBroadcastFromServer({routing: {...nabu, music_to: 'here'}});
  assert.equal(select.value, 'custom'); assert.match(context.labels.routeSummary, /Music: App\nDJs: Nabu/);
  assert.equal(context.postCalls, 0);
});
test('physical output pause and station off remain visible with Nabu selected', () => {
  const {context} = desktop();
  context.syncBroadcastFromServer({routing: {...nabu, box_talk: false, on: false}});
  assert.match(context.labels.routeSummary, /Nabu: output paused/);
  assert.match(context.labels.routeSummary, /Station off/);
});
test('a pending operator preset choice is not replaced by an old poll', () => {
  const {context, select} = desktop(); context.broadcastChanging = true;
  context.syncBroadcastFromServer({routing: nabu});
  assert.equal(select.value, 'app'); assert.equal(context.desiredBroadcast, 'app'); assert.equal(context.postCalls, 0);
});

test('legacy recovery preserves a custom route instead of selecting Nabu', async () => {
  const calls = [];
  const button = {textContent: 'Recover'};
  const context = {ROUTES: {nabu: {voice: 'box', reply: 'box', voice_device: 'nabu'}},
    config: {mode: 'attach', baseUrl: 'http://station'}, rebuildRelaunching: false,
    $: (id) => id === 'panicBtn' ? button : {value: 'custom'},
    api: {post: async (route, body) => {calls.push({route, body}); return {ok: true};}},
    document: {querySelectorAll: () => []},
    waitForAgent: async () => true, refresh: async () => {}, activeFrame: () => null};
  for (const name of ['setText', 'showRebuildOverlay', 'selectView', 'updateRebuildProgress', 'appendLog', 'hideRebuildOverlay']) context[name] = () => {};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function panicRecover('), source.indexOf('async function setBroadcastTarget(')), context);
  await context.panicRecover();
  assert.ok(calls.some((call) => call.route === '/api/pinebox/initialize'));
  assert.ok(calls.every((call) => call.route !== '/api/dj/output'));
  assert.equal(button.disabled, false);
});
