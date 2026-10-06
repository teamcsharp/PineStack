const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const shell = { url: 'file:///pine/index.html' }, panel = { url: 'http://station/' }, guest = { url: 'http://station/radio' };
const contents = { mainFrame: shell };
const context = { win: { isDestroyed: () => false, webContents: contents },
  ringAudioTarget: 'panel', panelFrameNow: () => panel, ringSound() {},
  ringAudioFrames: { revision: 12, targets: () => ['shell', 'panel', 'guest:42'], frame: target => target === 'guest:42' ? guest : null },
  ipcMain: { handle(_name, fn) { context.select = fn; } } };
vm.createContext(context);
const ipcStart = source.indexOf('ipcMain.handle("replay:audio-target"');
const ipcEnd = source.indexOf('\n});', ipcStart) + 4;
vm.runInContext(source.slice(ipcStart, ipcEnd), context);
const marker = 'setDisplayMediaRequestHandler((request, callback) => {';
const handlerStart = source.indexOf(marker) + marker.length;
const handlerEnd = source.indexOf('    }, { useSystemPicker: false });', handlerStart);
assert.ok(handlerStart > marker.length && handlerEnd > handlerStart);
vm.runInContext('function capture(request, callback) {' + source.slice(handlerStart, handlerEnd) + '}', context);
const owner = { sender: contents, senderFrame: shell };
const capture = request => { let response; context.capture(request, value => { response = value; }); return response; };
assert.throws(() => context.select({ sender: {}, senderFrame: shell }, 'shell'), /belongs/);
assert.throws(() => context.select({ sender: contents, senderFrame: {} }, 'shell'), /belongs/);
assert.throws(() => context.select(owner, 'system'), /Unknown/);
context.select(owner, 'shell');
assert.equal(capture({ frame: {}, audioRequested: true, videoRequested: false }), null,
  'guest requests cannot consume the recorder audio selection');
assert.equal(context.ringAudioTarget, 'shell');
const own = capture({ frame: shell, audioRequested: true, videoRequested: false });
assert.equal(own.audio, shell); assert.equal(own.enableLocalEcho, true);
assert.equal(context.ringAudioTarget, 'panel', 'a frame selection is consumed once');
const broadcast = capture({ frame: shell, audioRequested: true, videoRequested: false });
assert.equal(broadcast.audio, panel); assert.equal(broadcast.enableLocalEcho, true);
context.select(owner, 'shell');
assert.equal(capture({ frame: shell, audioRequested: false, videoRequested: true }), null);
assert.equal(context.ringAudioTarget, 'shell', 'picture negotiation cannot steal the sound selector');
context.select(owner, 'guest:42');
const radio = capture({ frame: shell, audioRequested: true, videoRequested: false });
assert.equal(radio.audio, guest); assert.equal(radio.enableLocalEcho, true);
assert.throws(() => context.select(owner, 'guest:666'), /Unknown/);
const discoveryStart = source.indexOf('ipcMain.handle("replay:audio-sources"');
const discoveryEnd = source.indexOf('\n});', discoveryStart) + 4;
vm.runInContext(source.slice(discoveryStart, discoveryEnd), context);
assert.throws(() => context.select({ sender: {}, senderFrame: shell }), /belongs/);
assert.throws(() => context.select({ sender: contents, senderFrame: {} }), /belongs/);
const discovered = context.select(owner);
assert.equal(discovered.ok, true); assert.equal(discovered.revision, 12);
assert.deepEqual(Array.from(discovered.targets), ['shell', 'panel', 'guest:42']);
contents.mainFrame = null;
assert.equal(capture({ frame: shell, audioRequested: true, videoRequested: false }), null,
  'a vanished owner frame refuses guest audio capture');
console.log('PiP audio targets: own loaded app frames, trusted discovery, serialized selection and local playback preserved');
