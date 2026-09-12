/* The sampler's audio engine, exercised without an audio device.
 *
 * window.pineSampler is a SEAM: Web Audio here, native Oboe on the tablet.
 * These tests pin the behaviour both sides have to agree on - what window
 * of the sample is played, what a gate does that a one-shot does not, and
 * which voices a new hit is allowed to cut. The Android engine is expected
 * to satisfy the same table.
 *
 * What these cannot tell you: whether it sounds right, and how long a press
 * takes to become sound. That number is measured on the physical device
 * with a recorder, never inferred from here.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');

const RATE = 48000;
const SECONDS = 1;

/* A 10 Hz sine: known, evenly spaced zero crossings every 0.05s. */
function fixtureBuffer(channels = 1) {
  const data = [];
  for (let c = 0; c < channels; c += 1) {
    const channel = new Float32Array(RATE * SECONDS);
    for (let i = 0; i < channel.length; i += 1) {
      channel[i] = Math.sin((2 * Math.PI * 10 * i) / RATE);
    }
    data.push(channel);
  }
  return {
    sampleRate: RATE,
    length: RATE * SECONDS,
    duration: SECONDS,
    numberOfChannels: channels,
    getChannelData: (c) => data[c]
  };
}

let started = [];      /* every source.start(...) call, in order */
let stopped = [];      /* every source.stop(...) call            */

function param() {
  return {
    value: 0,
    setValueAtTime() { return this; },
    linearRampToValueAtTime(v) { this.value = v; return this; },
    cancelScheduledValues() { return this; }
  };
}

class FakeContext {
  constructor() {
    this.currentTime = 0;
    this.state = 'running';
    this.destination = {};
    this.baseLatency = 0.004;
  }
  resume() { this.state = 'running'; return Promise.resolve(); }
  createGain() {
    return {gain: param(), connect() {}, disconnect() {}};
  }
  createBufferSource() {
    const source = {
      buffer: null, loop: false, loopStart: 0, loopEnd: 0,
      playbackRate: {value: 1},
      onended: null,
      connect() {}, disconnect() {},
      start(...args) { started.push({source, args}); },
      stop(...args) {
        stopped.push({source, args});
        /* A real AudioBufferSourceNode fires onended once it has stopped,
         * and that is what frees the engine's voice slot. Without it here
         * the voice map would only ever grow, and the tests would be
         * measuring the harness rather than the engine. */
        if (source.onended) source.onended();
      }
    };
    return source;
  }
  createBuffer(channels, length, rate) {
    const data = Array.from({length: channels}, () => new Float32Array(length));
    return {
      sampleRate: rate, length, duration: length / rate,
      numberOfChannels: channels, getChannelData: (c) => data[c]
    };
  }
  decodeAudioData() { return Promise.resolve(fixtureBuffer()); }
}

globalThis.AudioContext = FakeContext;
const engine = require('../desktop/renderer/sampler-engine.js');

function reset() {
  /* Every pad goes too, not just the ringing voices: footprint() counts
   * what is resident across the whole engine, so a test that inherited
   * another test's pads would measure the file rather than the feature. */
  engine.clear();
  /* A one-shot ends because its window runs out, and nothing in this fake
   * advances time. Ending every source by hand is how a test says "and
   * then the audio finished", so each test starts with no voices ringing. */
  for (const entry of started) {
    if (entry.source.onended) entry.source.onended();
  }
  started = [];
  stopped = [];
  engine.setPolyphonic(true);
}

async function loadPad(id, patch) {
  await engine.load(id, new ArrayBuffer(8));
  engine.set(id, Object.assign({gain: 1, pitch: 1, loop: false, reverse: false,
    trim: null, choke: ''}, patch || {}));
}

test('a sample is decoded once on load and reports itself', async () => {
  reset();
  const got = await engine.load('a', new ArrayBuffer(8));
  assert.equal(got.seconds, SECONDS);
  assert.equal(got.rate, RATE);
  assert.equal(got.channels, 1);
  assert.equal(engine.loaded('a'), true);
  assert.equal(engine.seconds('a'), SECONDS);
});

test('an empty pad is silent rather than an error', () => {
  reset();
  assert.equal(engine.fire('never-loaded'), '');
});

test('a one-shot is given its exact window; a gate and a loop are not', async () => {
  reset();
  await loadPad('shot');

  engine.fire('shot');
  assert.equal(started.length, 1);
  /* (when, offset, duration) - the source stops itself at the window's end */
  assert.equal(started[0].args.length, 3);
  assert.equal(started[0].args[1], 0);
  assert.equal(started[0].args[2], SECONDS);

  started = [];
  engine.fire('shot', {gate: true});
  assert.equal(started[0].args.length, 2, 'a held note must not schedule its own end');

  started = [];
  const voice = engine.fire('shot', {loop: true});
  assert.equal(started[0].args.length, 2);
  assert.equal(started[0].source.loop, true);
  assert.equal(started[0].source.loopStart, 0);
  assert.equal(started[0].source.loopEnd, SECONDS);
  assert.ok(voice);
});

test('a trim narrows the window that is played', async () => {
  reset();
  await loadPad('trimmed', {trim: {start: 0.25, end: 0.75}});
  engine.fire('trimmed');
  assert.equal(started[0].args[1], 0.25);
  assert.equal(started[0].args[2], 0.5);
});

test('reverse mirrors the trim rather than reusing it', async () => {
  reset();
  await loadPad('back', {trim: {start: 0.1, end: 0.4}, reverse: true});
  engine.fire('back');
  /* Played backwards, the last 0.4s becomes an offset of 1 - 0.4 = 0.6. */
  assert.ok(Math.abs(started[0].args[1] - 0.6) < 1e-9, 'offset mirrors');
  assert.ok(Math.abs(started[0].args[2] - 0.3) < 1e-9, 'duration is unchanged');
});

test('a nonsense trim falls back to the whole sample instead of silence', async () => {
  reset();
  await loadPad('bad', {trim: {start: 0.9, end: 0.2}});
  engine.fire('bad');
  assert.equal(started[0].args[1], 0);
  assert.equal(started[0].args[2], SECONDS);
});

test('velocity and tune reach the voice, and are clamped', async () => {
  reset();
  await loadPad('tune', {pitch: 2});
  engine.fire('tune');
  assert.equal(started[0].source.playbackRate.value, 2);

  started = [];
  engine.fire('tune', {pitch: 1000});
  assert.equal(started[0].source.playbackRate.value, 32, 'an absurd tune is clamped, not obeyed');
});

test('polyphony lets pads ring together; switching it off cuts the last hit', async () => {
  reset();
  await loadPad('poly');
  engine.fire('poly');
  engine.fire('poly');
  assert.equal(engine.levels().voices, 2);
  assert.equal(stopped.length, 0);

  reset();
  await loadPad('poly');
  engine.setPolyphonic(false);
  engine.fire('poly');
  engine.fire('poly');
  assert.equal(stopped.length, 1, 'the earlier voice is released, not left ringing');
});

test('a choke group cuts its siblings but leaves other pads alone', async () => {
  reset();
  await loadPad('hat-open', {choke: 'hats'});
  await loadPad('hat-shut', {choke: 'hats'});
  await loadPad('kick', {choke: ''});

  engine.fire('kick');
  engine.fire('hat-open');
  assert.equal(stopped.length, 0);
  engine.fire('hat-shut');
  assert.equal(stopped.length, 1, 'the open hat is cut');
  assert.equal(engine.levels().pads.kick, 1, 'the kick keeps ringing');
});

test('release and stopAll ramp a voice down rather than cutting it dead', async () => {
  reset();
  await loadPad('ring');
  const voice = engine.fire('ring', {gate: true});
  engine.release(voice);
  assert.equal(stopped.length, 1);
  /* stop() is scheduled in the future, not at once - that gap is the fade. */
  assert.ok(stopped[0].args[0] > 0, 'the stop is scheduled after a release ramp');

  stopped = [];
  engine.fire('ring');
  engine.fire('ring');
  engine.stopAll();
  assert.equal(stopped.length, 2);
});

test('a trim handle snaps to the nearest zero crossing', async () => {
  reset();
  await loadPad('cross');
  /* 10 Hz: crossings every 0.05s. */
  const snapped = engine.zeroCross('cross', 0.052);
  assert.ok(Math.abs(snapped - 0.05) < 0.002, 'snapped to ' + snapped);

  /* Nothing within reach leaves the handle where it was put, rather than
   * dragging it somewhere the operator did not ask for. 0.025s is the peak
   * of the lobe - the furthest this waveform ever gets from a crossing. */
  const far = engine.zeroCross('cross', 0.025, 0.5);
  assert.equal(far, 0.025);
});

test('chop shares one decoded buffer across pads instead of decoding again', async () => {
  reset();
  await loadPad('source');
  assert.equal(engine.copy('source', 'slice-3'), true);
  assert.equal(engine.loaded('slice-3'), true);
  engine.set('slice-3', {trim: {start: 0.5, end: 0.75}});
  engine.fire('slice-3');
  assert.equal(started[0].args[1], 0.5);
  assert.equal(started[0].args[2], 0.25);
  assert.equal(engine.copy('nothing-here', 'slice-4'), false);
});

test('peaks answer at the asked-for resolution for the waveform view', async () => {
  reset();
  await loadPad('wave');
  assert.equal(engine.peaks('wave', 256).length, 256);
  assert.equal(engine.peaks('missing', 256).length, 0);
  const peaks = engine.peaks('wave', 64);
  assert.ok(Math.max(...peaks) > 0.9, 'a full-scale sine should peak near one');
});

test('the memory footprint is real, and a chopped bank is counted once', async () => {
  reset();
  await loadPad('f1');
  const one = engine.footprint();
  assert.equal(one.pads, 1);
  assert.equal(one.buffers, 1);
  /* float32 per sample per channel */
  assert.equal(one.bytes, RATE * SECONDS * 1 * 4);

  await loadPad('f2');
  assert.equal(engine.footprint().bytes, one.bytes * 2, 'two decodes cost twice');

  /* Chop shares one buffer across sixteen pads. If that were counted per
   * pad the reading would be sixteen times the truth, and the warning it
   * drives would be nonsense. */
  engine.copy('f1', 'f3');
  engine.copy('f1', 'f4');
  const shared = engine.footprint();
  assert.equal(shared.pads, 4);
  assert.equal(shared.buffers, 2);
  assert.equal(shared.bytes, one.bytes * 2, 'shared buffers are counted once');
});

test('unloading a pad silences it and forgets it', async () => {
  reset();
  await loadPad('gone');
  engine.fire('gone');
  engine.unload('gone');
  assert.equal(engine.loaded('gone'), false);
  assert.equal(engine.fire('gone'), '');
});
