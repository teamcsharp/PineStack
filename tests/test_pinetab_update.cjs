/* [pinetab-update] the tablet button's pipeline, end to end, with a fake adb and a
 * fake deploy.sh: locate -> connect -> decide -> release -> deploy -> verify. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { PinetabUpdate } = require('../desktop/pinetab-update.cjs');
const { stamp } = require('../desktop/pinetab-stamp.cjs');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pinetab-'));
function write(p, text, mode) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); if (mode) fs.chmodSync(p, mode); }
try {
  const root = path.join(tmp, 'repo');
  write(path.join(root, 'app/src/main/AndroidManifest.xml'), '<manifest/>');
  write(path.join(root, 'app/build.gradle.kts'), 'android {}');
  write(path.join(root, 'desktop/renderer/x.js'), '');
  const wanted = stamp(root).stamp;
  const state = path.join(tmp, 'installed.txt');
  fs.writeFileSync(state, '1.0.0');
  // a fake adb: connect, get-state, dumpsys package -> versionName from the state file
  const adb = path.join(tmp, 'adb');
  write(adb, `#!/bin/bash
case "$*" in
  connect*) echo "connected to $2";;
  *get-state*) echo device;;
  *dumpsys*) echo "    versionName=$(cat ${state})";;
  *) echo ok;;
esac`, 0o755);
  // a fake deploy.sh: step headers, then 'installs' the wanted build
  write(path.join(root, 'deploy.sh'), `#!/bin/bash
printf '\\n== syncing canonical shared views\\n'
printf '\\n== stamp ${wanted}\\n'
echo "building for $PINE_TAB"
printf '\\n== installing\\n'
echo Success
echo "1.0.0+${wanted}" > ${state}
`, 0o755);
  const events = [];
  const calls = { stop: 0, wake: 0 };
  const look = { host: '10.0.0.9', port: 5555, on_network: true, adb_port_open: true,
    seen: { agent: 'Mozilla/5.0 PineBoxKiosk/1.0.0' } };
  const pu = new PinetabUpdate({
    agentRoot: () => root,
    readConfig: () => ({ pinetabAdb: adb }),
    getJson: async () => look,
    postJson: async () => ({}),
    send: (ch, ev) => { if (ch === 'pinetab-progress') events.push(ev); },
    glassStop: async () => { calls.stop += 1; },
    wake: async () => { calls.wake += 1; return { ok: true }; }
  });
  (async () => {
    let c = await pu.check({});
    assert.strictEqual(c.wanted, wanted);
    assert.strictEqual(c.installed, '');
    assert.strictEqual(c.stale, true, 'an unstamped build needs one update');
    look.seen.agent = 'PineBoxKiosk/1.0.0+' + wanted;
    c = await pu.check({});
    assert.strictEqual(c.stale, false);
    look.seen.agent = 'PineBoxKiosk/1.0.0+aaaaaaaaaaaa';
    assert.strictEqual((await pu.check({})).stale, true);

    const r = await pu.update('update');
    assert.ok(r.ok, JSON.stringify(r));
    assert.strictEqual(r.before, '1.0.0');
    assert.strictEqual(r.after, wanted);
    assert.strictEqual(calls.stop, 1, 'the desk mirror is stopped before the install');
    assert.strictEqual(calls.wake, 1);
    const steps = events.filter((e) => e.state === 'step').map((e) => e.step);
    assert.deepStrictEqual(steps.slice(0, 3), ['syncing canonical shared views', 'stamp ' + wanted, 'installing']);
    assert.ok(events.some((e) => /building for 10\.0\.0\.9:5555/.test(e.line)), 'PINE_TAB is the located tablet');

    const again = await pu.update('update');
    assert.ok(again.ok && again.skipped, 'already current: nothing is built');
    console.log('pinetab update: ok (' + events.length + ' progress events)');
  })().catch((e) => { console.error(e); process.exitCode = 1; }).finally(() => fs.rmSync(tmp, { recursive: true, force: true }));
} catch (e) {
  fs.rmSync(tmp, { recursive: true, force: true });
  throw e;
}
