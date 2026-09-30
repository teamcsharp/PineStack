/* [cam-open] the Pine Cam goes out as a picture and comes back as one: the
 * stream is never cut by removing the src (that blanked the box before its VCR
 * out), and an open puts a fresh still up before the stream takes over.
 * Runs the shipped functions out of desktop/renderer/pine-cam.js. */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'pine-cam.js'), 'utf8');
const a = src.indexOf('  function stillUrl()');
const b = src.indexOf('  function paintFrame()');
assert(a > 0 && b > a, 'the [cam-open] block is in pine-cam.js');
const block = src.slice(a, b);

function fakeImg() {
  const ls = {};
  return {
    src: '', removed: 0, onerror: null,
    removeAttribute() { this.removed += 1; this.src = ''; },
    addEventListener(t, f) { (ls[t] = ls[t] || []).push(f); },
    removeEventListener(t, f) { ls[t] = (ls[t] || []).filter(x => x !== f); },
    fire(t) { (ls[t] || []).slice().forEach(f => f()); },
    count(t) { return (ls[t] || []).length; },
  };
}

const env = {shown: true, mjpegFailedAt: 0, timers: []};
const make = new Function('env', `
  var base = function () { return 'http://st'; };
  var setTimeout = function (f) { env.timers.push(f); };
  var mjpegFailedAt = 0;
  Object.defineProperty(env, 'failedAt', {get: function () { return mjpegFailedAt; }});
  var shown; Object.defineProperty(env, 'setShown', {value: function (v) { shown = v; }});
  shown = true;
  ${block}
  return {mjpegStop: mjpegStop, mjpegStart: mjpegStart};
`);
const f = make(env);
const M = 'http://st:8098/live.mjpg';

// open: a still first, the stream only once the still has landed
let img = fakeImg();
f.mjpegStart(img, M);
assert(/frame\.jpg/.test(img.src), 'an open shows a fresh still first');
assert.strictEqual(img.onerror, null, 'a failing still is not a failing stream');
img.fire('load');
assert(img.src.indexOf(M) === 0, 'the stream takes over behind the still');
assert.strictEqual(img.__mjpeg, M);
assert.strictEqual(img.count('load'), 0, 'the hand-over listener is gone');
env.timers.forEach(t => t());                       // the late timer does nothing more
assert(img.src.indexOf(M) === 0);

// close: never a removed src - a still replaces the stream
f.mjpegStop(img);
assert.strictEqual(img.removed, 0, 'the picture is never blanked');
assert(/frame\.jpg/.test(img.src), 'the stream is cut by a still');
assert.strictEqual(img.__mjpeg, '');

// closed while the still was landing: the stream does not start after all
img = fakeImg();
f.mjpegStart(img, M);
env.setShown(false);
f.mjpegStop(img);
img.fire('load');
assert(/frame\.jpg/.test(img.src), 'a closed box does not open the stream');
env.setShown(true);

// a still that never lands does not hold the stream back
img = fakeImg(); env.timers = [];
f.mjpegStart(img, M);
env.timers.forEach(t => t());
assert(img.src.indexOf(M) === 0, 'the 1.5 s timer hands over anyway');

console.log('cam-open ok');
