'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..', 'desktop', 'renderer');
const html = fs.readFileSync(path.join(root, 'video-editor.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'video-editor.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'video-editor.css'), 'utf8');
const parody = js.slice(js.indexOf('function startParodyEditor()'), js.indexOf('\n  loadSource();'));
const htmlIds = [...html.matchAll(/\bid=["']([^"']+)["']/g)].map(match => match[1]);

test('parody editor DOM IDs are unique and every queried control exists', () => {
  assert.equal(new Set(htmlIds).size, htmlIds.length, 'duplicate HTML id');
  const queried = [...parody.matchAll(/\bel\(['"]([^'"]+)['"]\)/g)].map(match => match[1]);
  const missing = [...new Set(queried)].filter(id => !htmlIds.includes(id));
  assert.deepEqual(missing, []);
});
test('every literal getElementById event target exists in the markup', () => {
  const listenerIds = [...parody.matchAll(/\bel\(['"]([^'"]+)['"]\)\.addEventListener/g)].map(match => match[1]);
  const missing = [...new Set(listenerIds)].filter(id => !htmlIds.includes(id));
  assert.deepEqual(missing, []);
  for (const dynamic of ['parodySetIn', 'parodySetOut']) assert.ok(htmlIds.includes(dynamic));
  assert.match(parody, /Editor markup mismatch; missing:/);
  assert.match(js, /__pineVideoEditorBootError/);
  assert.match(js, /console\.error\('\[video-editor\] startup failed'/);
});

test('Camtasia-style controls, native players and both timeline lanes are present', () => {
  for (const id of ['parodyUndo', 'parodyRedo', 'parodyMediaBin', 'parodySearch',
    'parodyVideo', 'parodySourcePreview', 'parodyPreloadVideo', 'parodyOverlayVideo',
    'parodyTimeline', 'parodyOverlayTimeline', 'parodyTrack', 'parodyTransition',
    'parodyVolume', 'parodyAudioFadeIn', 'parodyAudioFadeOut', 'parodyOpacity',
    'parodyMaskCanvas', 'parodyMaskPen', 'parodyMaskKeyframeAdd']) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.match(html, /id="parodyVideo" controls/);
  assert.match(html, /id="parodySourcePreview" controls/);
  assert.match(parody, /setupDropLane\(timeline, 'base'\)/);
  assert.match(parody, /setupDropLane\(overlayTimeline, 'overlay'\)/);
  assert.match(parody, /application\/x-pine-timeline-index/);
  assert.match(parody, /application\/x-pine-media/);
  assert.match(css, /@media\(max-width:900px\)/);
});

test('media search/import and nonblocking source buffering use their contracts', () => {
  assert.match(parody, /\/api\/video-editor\/library\?q=/);
  assert.match(parody, /\/api\/video-editor\/library\/import/);
  assert.match(parody, /\{clip_id: clipId\}/);
  assert.match(parody, /preloadAdjacent\(activeIndex\)/);
  assert.match(parody, /preloadPreview\.src = record\.url/);
  assert.match(parody, /model\.editorRequest/);
});
