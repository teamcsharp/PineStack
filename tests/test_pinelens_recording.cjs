const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {LensRecording} = require('../desktop/pinelens-recording.cjs');
const mux = require('../desktop/clip-mux.cjs');

test('recording evicts old footage, snapshots past timestamps and reports short history', async () => {
  const ring = new LensRecording({seconds: 3});
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-lens-test-out-'));
  const now = Date.now();
  const run = mux.run, find = mux.findFfmpeg;
  try {
    for (let i = 0; i < 6; i++) ring.add({id: String(i), jpeg: Buffer.from('jpeg').toString('base64')}, now - 5000 + i * 1000);
    assert.equal(ring.rows.length, 4); assert.equal(ring.state().seconds, 3);
    mux.findFfmpeg = () => ({path: 'ffmpeg'});
    mux.run = async (_tool, args) => {
      const manifest = fs.readFileSync(args[args.indexOf('-i') + 1], 'utf8');
      assert.ok(manifest.includes('duration 1'));
      assert.equal(args[args.indexOf('-t') + 1], '3');
      // A fresh frame evicts original history while the export snapshot stays intact.
      ring.add({id: 'new', jpeg: Buffer.from('jpeg').toString('base64')}, now + 2000);
      fs.writeFileSync(args.at(-1), 'video');
    };
    const made = await ring.export(120, folder);
    assert.equal(made.seconds, 3); assert.equal(made.partial, true);
    assert.equal(fs.readFileSync(made.path, 'utf8'), 'video');
  } finally {mux.run = run; mux.findFfmpeg = find; ring.close();fs.rmSync(folder, {recursive: true, force: true});}
});

test('a stale recorder cannot export a fresh-looking frozen video', async () => {
  const ring = new LensRecording();
  try {
    ring.add({id: 'old', jpeg: Buffer.from('jpeg').toString('base64')}, Date.now() - 10000);
    await assert.rejects(ring.export(60, os.tmpdir()), /not currently active/);
  } finally {ring.close();}
});
