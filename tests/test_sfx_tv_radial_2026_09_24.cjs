const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'sfx-tv.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'sfx-tv.css'), 'utf8');

test('one bounded radial menu carries every requested video action', () => {
  for (const label of [
    'Send video to sampler', 'Make parody with H3', 'Examine in depth',
    'Make favorite', 'Replay clip', 'Delete permanently',
  ]) assert.match(source, new RegExp("item\\('" + label));
  assert.match(source, /'c:microphone'/);
  assert.match(source, /'c:microscope'/);
  assert.match(source, /'c:renew'/);
  assert.match(source, /sfx-tv-radial-shade/);
  assert.match(css, /\.sfx-tv-radial\s*\{/);
  assert.match(css, /\.sfx-tv-radial-item\.delete/);
});

test('the shared hold menu is wired to popup video and native fullscreen video', () => {
  assert.match(source, /function wireVideoRadial\(media, getClip\)/);
  assert.match(source, /setTimeout\(function \(\) \{[\s\S]{0,240}radialOpen\(clip, at\)/);
  assert.match(source, /holdPicture: function \(x, y\)/);
  assert.match(source, /radialOpen\(playing, \{x: px, y: py\}\)/);
  assert.match(source, /openRadial: radialOpen/);
  assert.match(source, /wireRadial: wireVideoRadial/);
});

test('permanent deletion previews real playable media with a scrub gesture', () => {
  assert.match(source, /media\.controls = true; media\.loop = true/);
  assert.match(source, /media\.addEventListener\('pointermove'/);
  assert.match(source, /media\.currentTime = Math\.max\(0, Math\.min\(media\.duration, at\)\)/);
  assert.match(source, /label: 'VIDEO ASSEMBLING'/,
    'the browser placeholder can flash before the delete preview');
  assert.match(css, /\.sfx-tv-delete-stage/);
});

test('popup history starts at three and each reach reveals two older airings', () => {
  assert.match(source, /var STRIP_PAST = 3/);
  assert.match(source, /var HIST_PAGE = 2/);
  assert.match(source, /histFetch\(STRIP_PAST\)/);
  assert.match(source, /wanted \+ \(histAt > 0 \? 1 : 0\)/,
    'inclusive paging does not compensate for its repeated boundary row');
  assert.match(source, /box\.addEventListener\('click'[\s\S]{0,120}histFetch\(HIST_PAGE\)/);
});

test('parody submission keeps the selected popup media lineage', () => {
  assert.match(source, /source_type: chosen\.source_type \|\| 'recent'/);
  assert.match(source, /source_generation: chosen\.source_generation \|\| ''/);
});

test('parody preview never exposes an empty native video and fits its controls', () => {
  assert.match(source, /stage\.className = 'sfx-tv-parody-stage is-loading'/);
  assert.match(source, /source\.readyState >= 2 && source\.videoWidth > 0/);
  assert.match(source, /source\.removeAttribute\('poster'\)/);
  assert.match(css, /\.sfx-tv-parody-stage\.is-loading > video\s*\{\s*visibility: hidden !important/);
  assert.match(css, /height: clamp\(170px, 30dvh, 310px\)/);
  assert.match(css, /height: clamp\(150px, 25dvh, 240px\)/);
  assert.match(css, /max-height: calc\(100dvh - 88px\)/);
});

test('parody dictation visibly owns and silences every audio surface', () => {
  assert.match(source, /Listening to your dictation\. Device audio is muted\./);
  assert.match(source, /PineDuck\.hold\('sfx-parody-dictation', 0, box\)/);
  assert.match(source, /wallAsk\('level', \{level: 0\}\)/);
  assert.match(source, /root\.pineLevels\.refresh\('video'\)/);
  assert.match(source, /sourceWasMuted = !!source\.muted;[\s\S]{0,80}source\.muted = true/);
  assert.match(css, /\.sfx-tv-parody-listening/);
});

test('tapping a queue or history tile plays that item immediately', () => {
  assert.match(source, /A queue tile is a transport control/);
  assert.match(source, /jump\(\{id: row\.id, url: row\.url, sting: row\.sting,/);
  assert.doesNotMatch(source, /tap to open its menu/);
});
