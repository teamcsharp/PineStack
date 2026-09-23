/* #1194: THE MIXING DRAWER ON THE DESK, WHERE THE GAIN IS IN ANOTHER WORLD.
 *
 * "Honor the sliders that I'm setting in the Pine box application, these are
 *  intended to be mixing the signal that I'm listening to."
 *
 * He moved MUSIC, DJS and DUCK in the desk app and nothing changed; the
 * drawer printed "20% (no desk here)" on a screen that was audibly playing
 * music. MEASURED, before any of this was written:
 *
 *   desktop/renderer/index.html   djGainMusic / djGainVoice / djDuck: zero
 *                                 occurrences. No #musicPlayer either.
 *   app.py (the station panel)    all three, plus the one #musicPlayer.
 *   index.html:542                <webview id="controlFrame"> - the panel is
 *                                 a SEPARATE DOCUMENT in its own process.
 *
 * PineAudioLaw.setLocalMix begins with document.getElementById, so on the
 * desk it could only ever return false. On the tablet the same file works
 * because the kiosk injects these modules INTO the panel, where the slider
 * and the gain node share one window.
 *
 * Four things are pinned here, because all four fail silently:
 *
 *   1. THE SHELL REACHES THE PANEL. A stubbed webview records what was
 *      evaluated inside it; the test asserts the panel's own slider ids are
 *      in that source and that the write is followed by djApplyGain.
 *   2. THE TABLET IS UNCHANGED. Where the gain slider is in this document
 *      the value is written straight onto it with the `input` event the
 *      panel listens for - no crossing, no coalescing, no Promise.
 *   3. A FAST DRAG IS NOT ONE CROSSING PER PIXEL. executeJavaScript is an
 *      IPC round trip; `input` fires per pixel. 200 moves must produce one
 *      crossing per frame carrying the value that was under the thumb, and
 *      the LAST value must always land.
 *   4. AN UNREACHABLE PANEL STILL TELLS THE TRUTH. A panel that reloaded
 *      under the drawer answers "I do not have that control", and the law
 *      must remember that as a proven false so the label can say "(no desk
 *      here)" - the one thing that must survive from the old behaviour.
 *
 * There is no jsdom in this repo, so the DOM is stubbed just far enough to
 * run the module for real.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const LAW = path.join(__dirname, '..', 'desktop', 'renderer', 'audio-law.js');
const LISTEN = path.join(__dirname, '..', 'desktop', 'renderer', 'listen.js');

function wait(ms) { return new Promise((go) => setTimeout(go, ms)); }

/* ---------------------------------------------------------- the stubs */

function makeSlider(id, value, min, max) {
  return {
    id, value: String(value), min: String(min), max: String(max),
    events: [],
    dispatchEvent(event) { this.events.push(event && event.type); return true; }
  };
}

/* A webview, as far as this module is concerned: a src and a function
 * called executeJavaScript that returns a Promise. Nothing else in a
 * browser has that shape, which is why it is the test for "am I the
 * shell". */
function makeFrame(id, answer) {
  const frame = {
    id, src: 'http://box.local/panel',
    calls: [],
    executeJavaScript(source) {
      frame.calls.push(source);
      if (typeof answer === 'function') return answer(source, frame.calls.length);
      return Promise.resolve(answer);
    }
  };
  return frame;
}

function stubWorld({sliders = {}, frames = [], mixer = null, store = null} = {}) {
  globalThis.document = {
    getElementById: (id) => sliders[id] || null,
    querySelectorAll: (what) => (what === 'webview' ? frames.slice() : [])
  };
  globalThis.Event = function Event(type) { this.type = type; };
  globalThis.pineMixer = mixer || undefined;
  if (store) {
    globalThis.localStorage = {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); }
    };
  } else {
    delete globalThis.localStorage;
  }
  delete require.cache[require.resolve(LAW)];
  return require(LAW);
}

/* ------------------------------------------- 1. the shell reaches in */

test('the desk crosses into the panel: the mix writes the station panel\'s own gains', async () => {
  const frame = makeFrame('controlFrame',
    Promise.resolve({hit: {music: true, duck: true}, shell: true}));
  const law = stubWorld({frames: [frame]});

  /* No djGainMusic in THIS document - exactly the desk - so the direct
   * write is impossible and the old code stopped here. */
  assert.equal(law.setLocalMix('music', 120), false,
    'the shell has no gain slider of its own; that is the whole bug');

  assert.equal(law.mixRoad('music'), 'panel');
  assert.equal(law.setMix('music', 120), 'panel',
    'setMix answers synchronously with the road, so the label never waits');
  assert.equal(law.setMix('duck', 40), 'panel');

  await wait(40);
  assert.equal(frame.calls.length, 1,
    'music and duck moved together ride ONE crossing, not two');
  const source = frame.calls[0];
  assert.match(source, /djGainMusic/);
  assert.match(source, /djDuck/);
  assert.match(source, /"music":120/);
  assert.match(source, /"duck":40/);
  assert.match(source, /dispatchEvent/,
    'the panel wires oninput="djApplyGain()" - a value without the event is a slider that moved and a sound that did not');
  assert.match(source, /djApplyGain/);
  assert.ok(!/djGainVoice/.test(source),
    'DJS is NOT the panel slider on the desk: app.py:180297 skips that write inside the shell (#1147)');

  await wait(20);
  assert.equal(law.mixReached('music'), true, 'the panel confirmed it moved');
  assert.equal(law.mixReached('duck'), true);
});

test('DJS on the desk rides the shell\'s own voice mix, because the panel slider is inert there', async () => {
  /* app.py:180297 guards the djGainVoice write with
   *     window.__pineDesktopVolume === undefined
   * so inside the desktop shell that slider moves a number and no sound
   * (#1147: the shell's injected script owns every live element's volume).
   * The road that the ear obeys is renderer.js's window.pineMixer. */
  const set = [];
  const frame = makeFrame('controlFrame', Promise.resolve({hit: {}, shell: true}));
  const law = stubWorld({
    frames: [frame],
    mixer: {get: () => ({voice: 1, music: 1}), set: (v) => { set.push(v); return v; }}
  });

  await wait(20);                /* the canonical bus applies its boot state */
  set.length = 0;

  assert.equal(law.mixRoad('voice'), 'shell');
  assert.equal(law.setMix('voice', 60), 'shell');
  await wait(40);
  assert.deepEqual(set, [{voice: 0.6}],
    'the drawer speaks percent where 100 is unity; the shell speaks multipliers');
  assert.equal(law.mixReached('voice'), true);
  assert.equal(frame.calls.length, 0, 'no crossing is spent on a slider that cannot be heard');

  /* ...and with no mixer in the room there is no voice road at all, which
   * the label has to be allowed to say. */
  const law2 = stubWorld({frames: [makeFrame('controlFrame', Promise.resolve({hit: {}}))]});
  assert.equal(law2.mixRoad('voice'), '');
  assert.equal(law2.setMix('voice', 60), '');
});

/* -------------------------------------------- 2. the tablet, untouched */

test('on the tablet the gain node is local and the write is direct', async () => {
  const music = makeSlider('djGainMusic', 100, 0, 600);
  const duck = makeSlider('djDuck', 70, 0, 90);
  const voice = makeSlider('djGainVoice', 160, 0, 600);
  let applied = 0;
  globalThis.djApplyGain = () => { applied += 1; };
  const law = stubWorld({sliders: {djGainMusic: music, djGainVoice: voice, djDuck: duck}});

  assert.equal(law.mixRoad('music'), 'local');
  assert.equal(law.mixRoad('voice'), 'local',
    'where the slider is in this window it IS the road, shell or no shell');
  assert.equal(law.setMix('music', 130), 'local');
  /* Synchronously, with no frame to wait for: this is the surface that
   * works today and it must not start going through a queue. */
  assert.equal(music.value, '130');
  assert.deepEqual(music.events, ['input', 'change']);
  assert.ok(applied > 0, 'djApplyGain is called belt-and-braces; it is idempotent');
  assert.equal(law.setMix('duck', 45), 'local');
  assert.equal(duck.value, '45');
  delete globalThis.djApplyGain;

  const seen = await law.readMix();
  assert.equal(seen.road, 'local');
  assert.equal(seen.music, 130);
  assert.equal(seen.duck, 45);
});

/* ------------------------------------------------ 3. the cost of a drag */

test('a fast drag is one crossing per frame, and the last value always lands', async () => {
  /* The crossing is held open on purpose, which is what a slow IPC round
   * trip looks like from here. Everything the thumb does while it is open
   * must collapse into ONE further crossing carrying the final value. */
  let release = null;
  const held = new Promise((go) => { release = go; });
  const frame = makeFrame('controlFrame', (source, n) =>
    (n === 1 ? held : Promise.resolve({hit: {music: true}})));
  const law = stubWorld({frames: [frame]});

  for (let i = 1; i <= 200; i += 1) law.setMix('music', i);
  assert.equal(frame.calls.length, 0, 'nothing crosses during the drag itself');
  await wait(40);
  assert.equal(frame.calls.length, 1, '200 moves, ONE crossing - not one per pixel');
  assert.match(frame.calls[0], /"music":200/, 'and it carries the value under the thumb');

  for (let i = 201; i <= 400; i += 1) law.setMix('music', Math.min(200, i));
  await wait(40);
  assert.equal(frame.calls.length, 1,
    'while a crossing is in the air the thumb only overwrites the pending value');

  release({hit: {music: true}, shell: true});
  await wait(60);
  assert.equal(frame.calls.length, 2, 'exactly one catch-up crossing on the way out');
  assert.match(frame.calls[1], /"music":200/);
  await wait(40);
  assert.equal(frame.calls.length, 2, 'and then it stops - no tail of stale writes');
});

test('five webviews, one desk: the frame that answered is the only one written to again', async () => {
  /* This window has control, radio, system2, guide and slides. Writing all
   * five would spend four IPC round trips on documents that have never
   * heard of djGainMusic, and reading the wrong one first would report "no
   * desk here" with the desk two elements away. */
  const radio = makeFrame('radioFrame', Promise.resolve({hit: {music: false}}));
  const control = makeFrame('controlFrame', Promise.resolve({hit: {music: true}, shell: true}));
  const guide = makeFrame('guideFrame', Promise.resolve({hit: {music: false}}));
  const law = stubWorld({frames: [radio, control, guide]});

  law.setMix('music', 110);
  await wait(60);
  assert.equal(control.calls.length, 1, 'the first flush asks every frame');
  assert.equal(law.mixReached('music'), true, 'and one of them had the desk');

  law.setMix('music', 111);
  await wait(60);
  assert.equal(control.calls.length, 2);
  assert.equal(radio.calls.length, 1, 'the radio frame is not asked a second time');
  assert.equal(guide.calls.length, 1);
});

/* ------------------------------------------- 4. the honest failure lives */

test('a panel that reloaded under the drawer is a proven false, not a guess', async () => {
  /* Two ways this goes wrong in the room: the panel navigated (the Promise
   * rejects) or it came back without the control (hit is false). Both must
   * end as "no desk here" rather than a number nobody set. */
  const gone = makeFrame('controlFrame', () => Promise.reject(new Error('detached')));
  const law = stubWorld({frames: [gone]});
  law.setMix('music', 90);
  await wait(60);
  assert.equal(law.mixReached('music'), false);
  const read = await law.readMix();
  assert.equal(read.road, '', 'and the read-back refuses to invent a value');
  assert.equal(read.music, null);

  const empty = makeFrame('controlFrame', Promise.resolve({hit: {music: false}, shell: true}));
  const law2 = stubWorld({frames: [empty]});
  law2.setMix('music', 90);
  await wait(60);
  assert.equal(law2.mixReached('music'), false);

  /* And with neither a slider nor a frame - a plain page - there is no
   * road at all, which is the case the phrase was written for. */
  const law3 = stubWorld({});
  assert.equal(law3.mixRoad('music'), '');
  assert.equal(law3.setMix('music', 90), '');
});

test('the drawer still says "(no desk here)" - and only when it is true', () => {
  /* The label is listen.js's, and listen.js is a view that cannot be run
   * without a browser; what is pinned here is that the phrase survived and
   * that it is driven by the PROVEN answer rather than by "setLocalMix
   * returned false", which on the desk it always did. */
  const src = fs.readFileSync(LISTEN, 'utf8');
  assert.match(src, /\(no desk here\)/, 'the honest failure is kept');
  assert.match(src, /law\.mixReached/, 'the label asks what was proven');
  assert.match(src, /law\.setMix\(stream, Number\(input\.value\)\)/,
    'the rows go through the road-finding door');
  assert.match(src, /if \(law\.mixRoad && law\.mixRoad\(stream\)\) return;/,
    'a row with a local road must never post a STATION level for every listener');
});

/* ------------------------------------------------------------- HERE */

test('HERE reading 0% was an unwritten store, not a level of zero', () => {
  /* The operator's screenshot: HERE 0% while the station was audible.
   * localStorage.getItem returns null when the key was never written,
   * Number(null) is 0, and Number.isFinite(0) is true - so the old "or 1"
   * fallback was unreachable. Nothing writes pineMusicVolume into the
   * SHELL's store: the injected appVolumeScript writes it inside the panel,
   * which is a different origin and a different store. */
  const empty = stubWorld({store: {}});
  assert.equal(empty.localVolume(), null,
    'an unwritten store has no opinion, and null is how it says so');

  const set = stubWorld({store: {pineMusicVolume: '0.4'}});
  assert.equal(set.localVolume(), 0.4);

  const quiet = stubWorld({store: {pineMusicVolume: '0'}});
  assert.equal(quiet.localVolume(), 0, 'a real zero is still a real zero');

  /* ...and the view falls back through #appVolume, the desk's master. */
  const src = fs.readFileSync(LISTEN, 'utf8');
  assert.match(src, /function hereLevel\(\)/);
  assert.match(src, /const slider = el\("appVolume"\);/);
});

/* ------------------------------------------------------------- DUCK */

test('DUCK is the panel\'s own duck depth, and the label says which duck it is', () => {
  /* Two ducks in this house and they are not the same duck:
   *   djDuck        how far the music dips while a DJ is talking. A depth
   *                 the operator dials, 0-90, read by djLevels.
   *   PineDuck      the automatic 10%-for-reports / 2%-for-dictation hold.
   *                 Reference counted, transient, nothing to dial.
   * The drawer's row is the first one; "not set" came from asking the
   * STATION for a level called duck, which it has never published. */
  const law = stubWorld({frames: [makeFrame('controlFrame', Promise.resolve({hit: {duck: true}}))]});
  assert.equal(law.mixRoad('duck'), 'panel');
  assert.equal(law.mixMax('duck'), 90);
  assert.deepEqual(law.STREAMS, ['music', 'voice', 'reply'],
    'duck is not a station stream, which is why levelOf could only say "not set"');

  const src = fs.readFileSync(LISTEN, 'utf8');
  assert.match(src, /not the automatic duck that steps the broadcast back/,
    'the row title tells the operator which duck this is');
});
