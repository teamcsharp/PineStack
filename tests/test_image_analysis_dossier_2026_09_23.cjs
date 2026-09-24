const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const script = fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'script-page.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'script-page.css'), 'utf8');
const backend = fs.readFileSync(path.join(ROOT, 'app.py'), 'utf8');

test('image-analysis feed entries open the complete dossier endpoint', () => {
  assert.match(script, /stage === 'image_analysis'/);
  assert.match(script, /\/api\/dj\/image-analysis\//);
  assert.match(script, /What the vision model interpreted/);
  assert.match(script, /Dialogue generated from this analysis/);
  assert.match(script, /Generation trail/);
  assert.match(script, /Prompts, source image, and model details/);
});

test('the server follows paused gallery work into the cupboard', () => {
  assert.match(backend, /@app\.get\("\/api\/dj\/image-analysis\/\{line_id\}"\)/);
  assert.match(backend, /for candidate in list\(shelf_rows\("gallery"\)\)/);
  assert.match(backend, /transcript = await shelf_transcript\("gallery", sid\)/);
  assert.match(backend, /"image_analysis_ids"/);
  assert.match(backend, /media_sign\("gen:" \+ image\)/);
});

test('the dossier is bounded and responsive without horizontal scrolling', () => {
  assert.match(css, /\.sp-feed-detail-box\s*\{[^}]*overflow-x:\s*hidden/s);
  assert.match(css, /\.sp-analysis-top\s*\{[^}]*grid-template-columns/s);
  assert.match(css, /@media \(max-width: 650px\)[\s\S]*\.sp-analysis-top\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(css, /\.sp-analysis-turn-body span\s*\{[^}]*overflow-wrap:\s*anywhere/s);
});

test('the current strip keeps the exact timed row words and tap target', () => {
  assert.match(backend, /"text": str\(r\.get\("text"\) or ""\)\[:1600\]/);
  assert.match(backend, /"name": str\(r\.get\("name"\) or ""\)/);
  assert.match(script, /resumeAirFollow\('live strip', sayingLineId\)/);
  assert.match(script, /sayingLineId = String\(\(shown && shown\.id\) \|\| ''\)/);
  assert.match(script, /feedNow && feedNow\.id[\s\S]*String\(feedNow\.id\) !== String\(shown\.id\)[\s\S]*!headIsRead\(\)/);
});

test('the shared feed favors the timed current row over a stale snapshot', async () => {
  const source = fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'sampler-feed.js'), 'utf8');
  const now = Date.now() / 1000;
  let payload = null;
  const root = {
    document: {hidden: false, addEventListener() {}, removeEventListener() {}},
    PineLcdDialogue: {stationRows: (station) => station.chat || []},
    pineDesktop: {get: async () => ({
      server_ms: Date.now(), chat: [],
      stream_now: {at: now - 2, length: 10, rows: [{
        id: 'current-line', from: 0, until: 8,
        text: 'These are the words sounding now.', who: 'dj', name: 'Host'
      }]},
      speaking_now: {id: 'previous-line', text: 'Stale words.'}
    })},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {}
  };
  vm.runInNewContext(source, {
    window: root, globalThis: root, console, Date, Promise, Set,
    setInterval: () => 1, clearInterval() {}
  }, {filename: 'sampler-feed.js'});
  root.PineStationFeed.subscribe((next) => { payload = next; });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(payload.now.id, 'current-line');
  assert.equal(payload.now.text, 'These are the words sounding now.');
});
