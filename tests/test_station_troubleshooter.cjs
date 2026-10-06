const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const handlers = new Map(), listeners = new Map(), windows = [], posts = [];
let audioFailure = false, live = false, offlineCamera = false, checkFailure = false, audioRuns = 0, desktopClosed = false, restored = 0, selectedCamera = 'pine';
let recoveryFailure = false, speechQuiet = 240, cleanupRuns = 0, wakeRuns = 0;
let speechVerified = false, panelMuted = false, repairVerified = false;
const desktopEvents = {};
class FakeWindow {
  constructor(options) { this.options = options; this.events = {}; this.webContents = { send() {}, setWindowOpenHandler() {}, on() {} }; windows.push(this); }
  isDestroyed() { return false; } isMinimized() { return false; } show() {} focus() {} setAlwaysOnTop() {}
  once(name, fn) { this.events[name] = fn; } on(name, fn) { this.events[name] = fn; } loadFile() { return Promise.resolve(); }
}
const desktop = { getBounds: () => ({ x: 0, y: 0, width: 800, height: 450 }), isDestroyed: () => false,
  webContents: { isAudioMuted: () => false,
    once: (name, fn) => (desktopEvents[name] = fn), on: (name, fn) => (desktopEvents[name] = fn),
    removeListener: (name, fn) => { if (desktopEvents[name] === fn) delete desktopEvents[name]; },
    reload: () => desktopEvents['did-finish-load'](), async executeJavaScript(code) {
    if (code.includes("const rooms=[")) { cleanupRuns++; return [{name:'Pine',result:{ok:true,stoppedPreviews:2,restartedVideos:1,walls:1,errors:[]}}]; }
    if (code.includes('pineRecoverPlayback')) { wakeRuns++; return ['Reconnected DJ players']; }
    if (code.includes('probeDjSpeech')) return {panelMuted, speech: {verified:speechVerified,
      say:speechVerified ? 'A live DJ voice player advanced with the audio graph running.' : 'Waiting for the next line; music does not verify DJ speech.',
      ...(speechVerified ? {proof:{id:'djVoiceAudio0',kind:'voice',advanced:.25,graphAdvanced:.25,graph:'running'}} : {})}};
    if (code.includes('state()?.cameraSource')) return selectedCamera;
    if (code.includes('PineRevive.run')) {
      audioRuns++;
      if (audioFailure) throw new Error('Fixture audio recovery failed');
      listeners.get('station-troubleshooter:progress')({ sender: desktop.webContents }, { lines: [{ label: 'Audio graph', state: 'proved', did: ['Graph running'] }] });
      return { verdict: { good: true, say: 'Audio output measured' }, lines: [{ label: 'Audio graph', state: 'proved', did: ['Graph running'] }] };
    }
    if (code.includes('PinePip.repairCamera')) return { ok: true, say: 'Camera display reopened' };
    if (code.includes("querySelector('.pip-camera')")) return { visible: true, image: true };
    if (code.includes('PineTabletDoctor.heal')) return { transcript: 'Wi-Fi checked, tablet not attached' };
    return { appVolume: 35, panel: { graph: 'running', media: [] } };
  } } };
const sandbox = { module: { exports: {} }, __dirname: path.resolve(__dirname, '../desktop'),
  require(name) { return name === 'electron' ? { BrowserWindow: FakeWindow, screen: { getDisplayMatching: () => ({ workArea: { width: 1000, height: 800 } }) } } : require(name); },
  setTimeout: (fn, ms) => ms <= 3000 ? setTimeout(fn, 0) : setTimeout(fn, ms), clearTimeout, console };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../desktop/station-troubleshooter.cjs'), 'utf8'), sandbox);
sandbox.module.exports.install({ ipcMain: { handle: (key, fn) => handlers.set(key, fn), on: (key, fn) => listeners.set(key, fn) }, getWindow: () => desktopClosed ? null : desktop,
  restoreDesktop: async () => { restored++; desktopClosed = false; },
  request: async (route, body) => {
    if (body) posts.push(route);
    if (route === '/api/broadcast/fix/repair') { if (recoveryFailure) throw Error('Station offline'); return {ok:true,...(repairVerified === undefined ? {} : {verified:repairVerified}),lines:['Music is playing; DJ production is pending.']}; }
    if (route === '/api/broadcast/health') return {stuck:speechQuiet>=60,dialogue_quiet:speechQuiet,say:'Fixture dialogue health'};
    if (checkFailure && route === '/api/broadcast/console') throw new Error('Delivery endpoint unavailable');
    if (route === '/api/pinelink/doctor') return offlineCamera ? { verdict: 'Camera off' } : { camera: 'camera', cure: 'reset', verdict: 'Radio needs reset' };
    if (route === '/api/pinelink/reset-radio') { live = true; return { ok: true, say: 'Radio reset' }; }
    if (route === '/api/pinelink/state') return { state: live ? 'live' : 'no-link', fresh: live };
    if (route === '/api/tablet/look') return { fetching: false, adb_port_open: false, verdict: 'Tablet offline' };
    return { say: 'Fixture answered' };
  } });
const open = handlers.get('station-troubleshooter:open');
assert.throws(() => open({ sender: {} }), /Pine desktop/);
open({ sender: desktop.webContents }); open({ sender: desktop.webContents });
assert.equal(windows.length, 1); assert.equal(windows[0].options.alwaysOnTop, true);
const popup = { sender: windows[0].webContents }, run = handlers.get('station-troubleshooter:run');
assert.throws(() => run({ sender: desktop.webContents }, 'all'), /troubleshooting window/);
(async () => {
  await assert.rejects(run(popup, 'invalid'), /Unknown troubleshooting/);
  checkFailure = true;
  const checked = await run(popup, 'check');
  assert.equal(checked.busy, false);
  assert.ok(checked.entries.some(entry => entry.label === 'Broadcast delivery' && entry.status === 'failed'));
  assert.ok(checked.entries.some(entry => entry.label === 'Audio in this app'), 'one failed endpoint does not prevent other checks');
  const audio = await run(popup, 'audio');
  assert.equal(audioRuns, 1); assert.equal(audio.audioSteps[0].label, 'Audio graph');
  assert.ok(audio.entries.some(entry => entry.status === 'verified'));
  const oldSteps = JSON.stringify(audio.audioSteps);
  listeners.get('station-troubleshooter:progress')({ sender: {} }, { lines: [{ label: 'Fake' }] });
  assert.equal(JSON.stringify(audio.audioSteps), oldSteps, 'foreign progress is rejected');
  audioFailure = true;
  const failed = await run(popup, 'audio');
  assert.equal(failed.busy, false); assert.ok(failed.entries.some(entry => entry.status === 'failed'));
  offlineCamera = true;
  const offline = await run(popup, 'camera');
  assert.ok(offline.entries.some(entry => /Turn it on/.test(entry.detail))); assert.equal(posts.length, 0, 'offline hardware receives manual steps without a blind reset');
  offlineCamera = false;
  const camera = await run(popup, 'camera');
  assert.equal(posts[0], '/api/pinelink/reset-radio');
  assert.ok(camera.entries.some(entry => entry.label === 'Camera picture' && entry.status === 'verified'));
  selectedCamera = 'tab-front';
  const cameraPosts = posts.length;
  const tabletCamera = await run(popup, 'camera');
  assert.ok(tabletCamera.entries.some(entry => entry.label === 'PineTab camera PiP'));
  assert.ok(tabletCamera.entries.some(entry => entry.label === 'Camera picture' && entry.status === 'verified'));
  assert.equal(posts.length, cameraPosts, 'tablet camera repair does not reset the unrelated Pine Cam');
  selectedCamera = 'pine';
  const tablet = await run(popup, 'tablet');
  assert.ok(tablet.entries.some(entry => entry.label === 'Pine Tab result' && entry.status === 'attention'));
  const all = await run(popup, 'all');
  assert.ok(all.entries.some(entry => entry.label === 'DJ audio controls' && entry.status === 'failed'));
  assert.ok(all.entries.some(entry => entry.label === 'Pine Tab result'), 'repair-all continues past a failed component');
  assert.equal(all.busy, false);
  const reloaded = await run(popup, 'reload');
  assert.ok(reloaded.entries.some(entry => entry.label === 'App display' && entry.status === 'changed'));
  assert.equal(Object.keys(desktopEvents).length, 0, 'renderer reload cleans up its listeners');
  desktopClosed = true;
  const shown = await run(popup, 'show');
  assert.equal(restored, 1); assert.equal(desktopClosed, false);
  assert.ok(shown.entries.some(entry => entry.label === 'Pine window' && entry.status === 'changed'));
  desktopClosed = true;
  await run(popup, 'reload');
  assert.equal(restored, 2, 'repair can recreate a closed desktop while troubleshooting remains open');
  audioFailure = false;
  recoveryFailure = true;
  const offlinePlayback = await run(popup, 'playback');
  assert.equal(offlinePlayback.busy, false);
  assert.ok(cleanupRuns >= 2 && wakeRuns >= 2, 'H3 cleanup and local DJ recovery continue while the station is offline');
  assert.ok(offlinePlayback.entries.some(entry => entry.label === 'Station and orchestrator' && entry.status === 'failed'));
  assert.ok(offlinePlayback.entries.some(entry => entry.label === 'DJ delivery verification' && entry.status === 'attention'), 'music output does not verify DJ speech');
  recoveryFailure = false; speechQuiet = 2;
  const playing = await run(popup, 'playback');
  assert.ok(posts.includes('/api/broadcast/fix/repair'), 'direct playback action always asks the orchestrator even if local audio is sounding');
  assert.ok(playing.entries.some(entry => entry.label === 'DJ delivery verification' && entry.status === 'verified'));
  assert.ok(playing.entries.some(entry => entry.label === 'DJ speech in this app' && entry.status === 'attention'), 'another listener acknowledgement and music cannot verify this app speech');
  repairVerified = undefined; speechVerified = true;
  const localSpeech = await run(popup, 'playback');
  assert.ok(localSpeech.entries.some(entry => entry.label === 'Station and orchestrator' && entry.status === 'checked'), 'successful healthy diagnosis without an explicit verified field is checked');
  assert.ok(localSpeech.entries.some(entry => entry.label === 'DJ speech in this app' && entry.status === 'verified'));
  assert.ok(localSpeech.entries.some(entry => entry.label === 'App audio result' && entry.status === 'verified'), 'music evidence is labelled app audio');
  panelMuted = true;
  const mutedSpeech = await run(popup, 'playback');
  assert.ok(mutedSpeech.entries.some(entry => entry.label === 'DJ speech in this app' && entry.status === 'attention'), 'muted webview cannot verify local speech');
  panelMuted = false; speechVerified = false; repairVerified = false;
  speechQuiet = null;
  const unknown = await run(popup, 'playback');
  assert.ok(unknown.entries.some(entry => entry.label === 'DJ delivery verification' && entry.status === 'attention'), 'missing dialogue timing cannot imply speech was heard');
  const revive = require('../desktop/renderer/pine-revive.js'), progress = [];
  revive._deps({ api: { get: async () => ({}) }, doc: null, win: {}, now: () => 1000, wait: async () => {} });
  const recovered = await revive.run({ only: ['look'], gap: 1, tone: false, onProgress: value => progress.push(value.lines.map(line => line.state)) });
  assert.equal(recovered.done, true); assert.ok(progress.some(states => states.includes('running'))); assert.ok(progress.some(states => states.includes('looked')), 'real recovery driver reports each step');
  const reporterFailure = await revive.run({ only: ['look'], gap: 1, tone: false, onProgress: () => { throw new Error('Reporter failed'); } });
  assert.equal(reporterFailure.done, true, 'a reporting failure does not interrupt recovery'); revive._deps(null);
  console.log('Station troubleshooter: OS window reuse, sender/action checks, partial failures, audio progress, camera cure and picture proof, tablet verdicts and repair-all passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
