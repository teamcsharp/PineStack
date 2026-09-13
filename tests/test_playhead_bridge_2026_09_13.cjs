/* #1330: THE DJ PLAYHEAD, ACROSS THE WEBVIEW BOUNDARY.
 *
 * The SCRIPT view places its highlight by matching a position against each
 * row's from/until window, and #1278 established that the position must be
 * READ off the audio rather than estimated: the clock estimate was behind
 * the sound in 81.3% of samples, median -2.99s, with 29.8% of moves skips
 * and 20.5% backward.
 *
 * It read that position with `document.querySelectorAll('audio')` - in the
 * desktop CHROME. The chrome's document holds exactly one <audio>
 * (desktopRadioPlayer, index.html:203). djVoiceAudio0/1 are created by the
 * panel, which runs inside <webview id="radioFrame"> and is a separate DOM
 * the chrome cannot reach. So on the desktop that scan returned null every
 * time - not sometimes - and the view silently ran on the very estimator
 * #1278 was written to replace, with #1287's file guard and #1294's
 * named-row preference dead for the same reason.
 *
 * This bridges it. The tests worth having are the ones whose failure is
 * SILENT, and for a bridge there is exactly one shape of that:
 *
 *   A STALE READING THAT STILL LOOKS LIVE. If the webview navigates, the
 *   panel crashes, or the interval simply stops, the last value sits there
 *   looking like a position. The mark then FREEZES on a line - which reads
 *   as a working highlight on a quiet show, not as a broken one. That is
 *   strictly worse than no bridge at all, because falling back to the
 *   clock at least keeps moving. Hence: stale must mean ABSENT.
 *
 *   SILENCE NEVER REPORTED. When a round ends nothing is sounding, and if
 *   the reporter only ever posts positions, the host keeps the last one
 *   and the mark stays lit on a line that stopped playing.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const RENDERER = path.join(__dirname, '..', 'desktop', 'renderer');

/* The host half, lifted out of renderer.js by its own markers, so the test
 * runs the shipped source and not a copy of it. */
function hostBridge() {
  const src = fs.readFileSync(path.join(RENDERER, 'renderer.js'), 'utf8');
  const from = src.indexOf("/* #1330: the panel's DJ playhead");
  assert.ok(from > 0, 'the #1330 host bridge is still in renderer.js');
  const tail = src.indexOf('window.pinePlayhead =', from);
  const to = src.indexOf('};', tail) + 2;
  const ctx = {window: {}, Date, String, Number};
  ctx.window.window = ctx.window;
  vm.createContext(ctx);
  vm.runInContext(src.slice(from, to), ctx);
  return ctx;
}

test('a fresh reading is handed straight back', () => {
  const ctx = hostBridge();
  ctx.window.__pinePlayhead = {id: 'djVoiceAudio0', t: 3.42,
    file: 'a277eb58.wav', duration: 9, at: Date.now()};
  const got = ctx.window.pinePlayhead();
  assert.equal(got.t, 3.42);
  assert.equal(got.file, 'a277eb58.wav');
});

test('a STALE reading is absent, not frozen', () => {
  /* The whole safety story. A bridge that keeps returning its last value
   * pins the highlight to one line and looks like it is working. */
  const ctx = hostBridge();
  ctx.window.__pinePlayhead = {id: 'djVoiceAudio0', t: 3.42,
    file: 'a277eb58.wav', duration: 9, at: Date.now() - 5000};
  assert.equal(ctx.window.pinePlayhead(), null,
    'five seconds old must read as no reading at all');
});

test('nothing sounding reads as nothing', () => {
  const ctx = hostBridge();
  ctx.window.__pinePlayhead = null;
  assert.equal(ctx.window.pinePlayhead(), null);
});

/* The webview half. It is small enough to run whole, with electron and the
 * DOM stubbed, which is better than extracting part of it. */
function preload(audios) {
  const src = fs.readFileSync(path.join(RENDERER, 'webview-preload.js'), 'utf8');
  const sent = [];
  const timers = [];
  const ctx = {
    require: (name) => {
      assert.equal(name, 'electron');
      return {
        contextBridge: {exposeInMainWorld: () => {}},
        clipboard: {}, nativeImage: {},
        ipcRenderer: {sendToHost: (ch, msg) => sent.push([ch, msg])}
      };
    },
    document: {querySelectorAll: () => audios},
    setInterval: (fn) => { timers.push(fn); return 1; },
    Number, String, Date
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  assert.equal(timers.length, 1, 'the reporter is on a timer');
  return {sent, tick: timers[0]};
}

function voice(extra) {
  return Object.assign({
    id: 'djVoiceAudio0', paused: false, ended: false,
    currentTime: 2.5, duration: 8, currentSrc: 'http://x/media/abc123.wav?t=9'
  }, extra || {});
}

test('the sounding voice is reported with its file', () => {
  const {sent, tick} = preload([voice()]);
  tick();
  assert.equal(sent.length, 1);
  const [channel, msg] = sent[0];
  assert.equal(channel, 'pine-playhead');
  assert.equal(msg.t, 2.5);
  assert.equal(msg.file, 'abc123.wav', 'the query string is not part of it');
});

test('the chrome audio element is never mistaken for the voice', () => {
  /* The one <audio> the chrome does own. If this were reported, the view
   * would place the highlight from the MUSIC position - two different
   * timebases, and the bug would look like drift rather than a mix-up. */
  const {sent, tick} = preload([voice({id: 'desktopRadioPlayer'})]);
  tick();
  /* Nothing at all, rather than a null: the host has never been told
   * there was sound, so there is nothing to correct. */
  assert.equal(sent.length, 0, 'not a djVoice element, so not a reading');
});

test('a paused or unstarted element is not a reading', () => {
  for (const bad of [{paused: true}, {ended: true}, {currentTime: 0}]) {
    const {sent, tick} = preload([voice(bad)]);
    tick();
    assert.equal(sent.length, 0, JSON.stringify(bad));
  }
});

test('silence is reported once, then not repeated', () => {
  /* Reported: or the mark stays lit on a line that has stopped. Once: or
   * a quiet show posts four messages a second saying nothing forever. */
  const {sent, tick} = preload([]);
  tick();
  tick();
  assert.equal(sent.length, 0, 'silence from the start says nothing');

  const live = [voice()];
  const run = preload(live);
  run.tick();
  assert.equal(run.sent.length, 1);
  live.length = 0;                       /* the round ends */
  run.tick();
  assert.equal(run.sent.length, 2);
  assert.equal(run.sent[1][1], null, 'the host is told the sound stopped');
  run.tick();
  assert.equal(run.sent.length, 2, 'and not told again, every 250ms');
});
