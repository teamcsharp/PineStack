const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const elements = new Map();
const document = {
  getElementById: id => elements.get(id),
  createElement: () => ({ style: {}, hidden: false, setAttribute(key, value) { this[key] = value; },
    appendChild(child) { elements.set(child.id, child); } }),
  body: { appendChild(child) { elements.set(child.id, child); } }
};
let receive, claimCalls = 0, cuts = [], reports = [], retry = false;
const window = { document, PineStationFeed: { subscribe(fn) { receive = fn; } }, pineDesktop: {
  async post(route, body) {
    if (route.endsWith('/claim')) {
      claimCalls++;
      if (retry) { retry = false; throw new Error('temporary network failure'); }
      return { go: true, seconds: 600, name: 'pinepip.mp4' };
    }
    reports.push(body); return { ok: true };
  },
  async replayExport(options) { cuts.push(options); return { ok: true, uploaded: { ok: true } }; }
}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'desktop/renderer/screen-export.js'), 'utf8'), { window, console: { error() {} } });
const flush = () => new Promise(resolve => setImmediate(resolve));
const send = (target, id, kind = 'poll') => receive({ kind, station: {
  screen_export: { target, id }, export_progress: { target, pct: 45, say: 'Cutting video' }
} });
(async () => {
  send('tab', 'tablet'); await flush(); assert.equal(claimCalls, 0);
  send('pip', 'pip', 'join'); send('pip', 'pip'); await flush();
  assert.equal(claimCalls, 1); assert.equal(cuts.length, 1);
  assert.equal(cuts[0].view, 'pip'); assert.equal(cuts[0].require_audio, true);
  assert.equal(cuts[0].upload, true); assert.equal(reports[0].device, 'pip'); assert.equal(reports[0].ok, true);
  const bar = elements.get('pineExportBar'); assert.equal(bar.hidden, false); assert.equal(bar['aria-valuenow'], '45');
  send('pip', 'pip'); await flush(); assert.equal(cuts.length, 1);
  send('tab', 'tablet'); assert.equal(bar.hidden, true);
  retry = true; send('app', 'app'); await flush(); send('app', 'app'); await flush();
  assert.equal(cuts[1].view, 'app'); assert.equal(cuts[1].require_audio, true); assert.equal(reports[1].device, 'app');
  receive({ kind: 'poll', station: {} }); assert.equal(bar.hidden, true);
  // Run the actual remote-panel painter: a tablet sees only tablet cuts.
  const app = fs.readFileSync(path.join(root, 'app.py'), 'utf8');
  const start = app.indexOf('function exportProgressPaint(p) {');
  const end = app.indexOf('\nlet screenExportSeen', start);
  const tablet = { document, window: { pineDesktop: { __pineKiosk: true, replayExport() {} } } };
  vm.createContext(tablet); vm.runInContext(app.slice(start, end), tablet);
  tablet.exportProgressPaint({ target: 'pip', pct: 5 }); assert.equal(bar.hidden, true);
  tablet.exportProgressPaint({ target: 'app', pct: 15 }); assert.equal(bar.hidden, true);
  tablet.exportProgressPaint({ target: 'tab', pct: 25 }); assert.equal(bar.hidden, false);
  tablet.exportProgressPaint(null); assert.equal(bar.hidden, true);
  assert.match(fs.readFileSync(path.join(root, 'desktop/renderer/pine-pip.css'), 'utf8'), /:not\(#pineExportBar\)/);
  console.log('Screen export routing: desktop claim/upload/completion, retries, duplicate polls, PiP bar, tablet filtering passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
