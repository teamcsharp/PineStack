'use strict';
/* [tablet-attach] The desk says why the tablet is not attached, and clears a dead link (#1589, 2026-10-05).
 *
 * The attach check is run against a stand-in adb: a small script that keeps one tablet's state in a
 * file and answers `devices`, `connect` and `disconnect` the way adb does - including the trap, where
 * `connect` to a tablet still listed as offline answers "already connected" and changes nothing.
 * (The stand-in is a shell script, so those cases run where a shell can be an executable: not on Windows.)
 *
 * Run on local disk, never from the share:  node --test tests/test_tablet_attach_2026_10_05.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { TerminalHost } = require('../desktop/terminal-host.cjs');

const ROOT = path.join(__dirname, '..');
const windows = process.platform === 'win32';
const SERIAL = '10.0.0.9:5555';

function bench(state, { up = true, allowed = true, saved = SERIAL } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-adb-'));
  const file = name => path.join(dir, name);
  fs.writeFileSync(file('state'), state); fs.writeFileSync(file('log'), '');
  if (up) fs.writeFileSync(file('up'), '1');
  if (allowed) fs.writeFileSync(file('allowed'), '1');
  fs.writeFileSync(file('adb'), [
    '#!/bin/bash',
    'here="$(dirname "$0")"; echo "$*" >> "$here/log"; state="$(cat "$here/state")"',
    'case "$1" in',
    '  devices) echo "List of devices attached"; [ "$state" != gone ] && echo "' + SERIAL + '   $state product:p model:m transport_id:3";;',
    '  disconnect) echo gone > "$here/state"; echo "disconnected $2";;',
    '  connect)',
    '    if [ "$state" != gone ]; then echo "already connected to $2";',
    '    elif [ ! -f "$here/up" ]; then echo "failed to connect to \'$2\': Connection refused";',
    '    elif [ ! -f "$here/allowed" ]; then echo unauthorized > "$here/state"; echo "failed to authenticate to $2";',
    '    else echo device > "$here/state"; echo "connected to $2"; fi;;',
    'esac', 'exit 0', ''].join('\n'), { mode: 0o755 });
  fs.writeFileSync(file('fastboot'), '');
  const host = new TerminalHost({ readConfig: () => ({ platformTools: dir, tabletSerial: saved }) });
  return { host, calls: () => fs.readFileSync(file('log'), 'utf8').trim().split('\n').filter(Boolean), state: () => fs.readFileSync(file('state'), 'utf8').trim(),
    done: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test('a tablet that is ready is simply used', { skip: windows }, async () => {
  const b = bench('device');
  assert.equal(await b.host.glassSerial(), SERIAL); assert.equal(b.host.glassWhy, '');
  assert.deepEqual(b.calls(), ['devices -l'], 'nothing is reconnected that works');
  b.done();
});

test('the trap: a dead link adb still lists is dropped, and the tablet comes back', { skip: windows }, async () => {
  const b = bench('offline');
  assert.equal(await b.host.glassSerial(), SERIAL, 'an online tablet is attached again');
  assert.deepEqual(b.calls(), ['devices -l', 'disconnect ' + SERIAL, 'connect ' + SERIAL, 'devices -l']);
  assert.equal(b.host.glassWhy, ''); assert.equal(b.state(), 'device');
  b.done();
});

test('a tablet that is gone from the list is connected without a needless drop', { skip: windows }, async () => {
  const b = bench('gone');
  assert.equal(await b.host.glassSerial(), SERIAL);
  assert.deepEqual(b.calls(), ['devices -l', 'connect ' + SERIAL, 'devices -l']);
  b.done();
});

test('a tablet that refuses says so, in adb\'s own words', { skip: windows }, async () => {
  const b = bench('gone', { up: false });
  assert.equal(await b.host.glassSerial(), '');
  assert.equal(b.host.glassWhy, "the tablet at " + SERIAL + " did not take the connection (failed to connect to '" + SERIAL + "': Connection refused)");
  b.done();
});

test('a tablet waiting for its prompt is a person-shaped problem, and is not dropped', { skip: windows }, async () => {
  const waiting = bench('gone', { allowed: false });
  assert.equal(await waiting.host.glassSerial(), '');
  assert.match(waiting.host.glassWhy, /has not allowed this computer yet - accept the debugging prompt on its screen$/);
  const again = bench('unauthorized', { allowed: false });
  assert.equal(await again.host.glassSerial(), '');
  assert.ok(!again.calls().some(call => call.startsWith('disconnect')), 'the pending prompt is left on the screen');
  assert.match(again.host.glassWhy, /has not allowed this computer yet/);
  waiting.done(); again.done();
});

test('no tablet was ever chosen: the reason names what adb does see, or nothing at all', { skip: windows }, async () => {
  const none = bench('gone', { saved: '' });
  assert.equal(await none.host.glassSerial(), ''); assert.equal(none.host.glassWhy, '', 'nothing to say: the caller says no tablet is attached');
  const other = bench('offline', { saved: '' });
  assert.equal(await other.host.glassSerial(), ''); assert.equal(other.host.glassWhy, 'adb lists ' + SERIAL + ' as offline, which is not ready');
  const ready = bench('device', { saved: '' });
  assert.equal(await ready.host.glassSerial(), SERIAL, 'the first ready tablet is used, as before');
  none.done(); other.done(); ready.done();
});

test('a reason from the last look does not outlive it', { skip: windows }, async () => {
  const b = bench('gone', { up: false });
  await b.host.glassSerial(); assert.notEqual(b.host.glassWhy, '');
  fs.writeFileSync(path.join(path.dirname(b.host.tools().adb), 'up'), '1');
  assert.equal(await b.host.glassSerial(), SERIAL); assert.equal(b.host.glassWhy, '');
  b.done();
});

test('an adb that is not there is named as that, not as a missing tablet', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-noadb-'));
  const host = new TerminalHost({ readConfig: () => ({ platformTools: dir, tabletSerial: SERIAL }) });
  const tools = host.tools();
  if (tools.found) return;                       /* a machine with real platform-tools in a usual place */
  const saved = process.env.PATH; process.env.PATH = dir;
  try { assert.equal(await host.glassSerial(), ''); } finally { process.env.PATH = saved; }
  assert.equal(host.glassWhy, 'adb was not found on this computer - set the platform-tools folder');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('both places that print the verdict print the reason when there is one', () => {
  const main = fs.readFileSync(path.join(ROOT, 'desktop', 'main.js'), 'utf8');
  assert.equal((main.match(/why: terminalHost\.glassWhy \|\| "no tablet is attached"/g) || []).length, 2);
  assert.equal((main.match(/why: "no tablet is attached"/g) || []).length, 0, 'no bare verdict is left');
  const host = fs.readFileSync(path.join(ROOT, 'desktop', 'terminal-host.cjs'), 'utf8');
  assert.ok(host.indexOf("(['disconnect', saved])") < host.indexOf("(['connect', saved])"), 'the dead entry is dropped before the reconnect');
  assert.match(host, /runner\(tools\.adb, 12000\)\(\['connect', saved\]\)/);
});
