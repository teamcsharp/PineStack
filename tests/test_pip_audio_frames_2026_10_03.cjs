'use strict';
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');
const { ReplayAudioFrames } = require('../desktop/replay-audio-frames.cjs');
function contents(id, url) {
  const guest = new EventEmitter();
  Object.assign(guest, { id, url, mainFrame: { id }, dead: false,
    getURL() { return this.url; }, isDestroyed() { return this.dead; } });
  return guest;
}
function fixture() {
  const host = { webContents: contents(1, 'file:///pine/index.html'), dead: false,
    isDestroyed() { return this.dead; } };
  let panel = null;
  const changes = [];
  const catalog = new ReplayAudioFrames({ getWindow: () => host, getPanel: () => panel,
    onChanged: value => changes.push(value) });
  return { host, catalog, changes, setPanel: value => { panel = value; } };
}
test('catalog includes all loaded own audio frames and counts the panel once', () => {
  const f = fixture(), panel = contents(2, 'http://station/panel'), radio = contents(3, 'http://station/radio');
  const blank = contents(4, 'about:blank');
  f.setPanel(panel.mainFrame);
  [panel, radio, blank].forEach(item => f.catalog.track(item));
  assert.deepEqual(f.catalog.targets(), ['shell', 'panel', 'guest:3']);
  assert.equal(f.catalog.frame('shell'), f.host.webContents.mainFrame);
  assert.equal(f.catalog.frame('panel'), panel.mainFrame);
  assert.equal(f.catalog.frame('guest:3'), radio.mainFrame);
  assert.equal(f.catalog.frame('guest:999'), null, 'unattached content is never selected');
  assert.equal(f.catalog.frame('guest:4'), null, 'an empty webview is not an audio source');
  assert.equal(f.catalog.frame('system'), null);
});
test('guest load, navigation and destruction revise discovery, even for unchanged IDs', () => {
  const f = fixture(), guest = contents(9, 'about:blank#initial');
  f.catalog.track(guest);
  assert.deepEqual(f.catalog.targets(), ['shell']);
  const attachedRevision = f.catalog.revision;
  f.catalog.track(guest);
  assert.equal(f.catalog.revision, attachedRevision, 'duplicate tracking has no duplicate listeners');
  guest.url = 'http://station/guide'; guest.emit('did-finish-load');
  assert.deepEqual(f.changes.at(-1).targets, ['shell', 'guest:9']);
  const previous = f.catalog.revision;
  guest.mainFrame = { id: 9, navigation: 2 }; guest.emit('did-navigate');
  assert.equal(f.catalog.revision, previous + 1, 'reloading the same source invalidates an old tap');
  assert.equal(f.catalog.frame('guest:9'), guest.mainFrame);
  guest.dead = true; guest.emit('destroyed');
  assert.deepEqual(f.changes.at(-1).targets, ['shell']);
  assert.equal(f.catalog.frame('guest:9'), null);
  assert.equal(f.catalog.guests.size, 0);
  f.host.dead = true;
  assert.deepEqual(f.catalog.targets(), []);
});
test('a disappearing guest cannot break discovery of the remaining sources', () => {
  const f = fixture(), bad = contents(7, 'http://station/tape'), good = contents(8, 'http://station/radio');
  f.catalog.track(bad); f.catalog.track(good);
  bad.getURL = () => { throw new Error('frame already disposed'); };
  assert.deepEqual(f.catalog.targets(), ['shell', 'guest:8']);
  assert.equal(f.catalog.frame('guest:7'), null);
});
