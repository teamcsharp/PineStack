'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {PinetabUpdate} = require('../desktop/pinetab-update.cjs');
(async () => {
  const events = [], calls = [];
  let source = 'aaaaaaaaaaaa', installed = 'bbbbbbbbbbbb';
  const pu = new PinetabUpdate({send: (_, e) => events.push(e), glassStop: async () => calls.push('stop'), wake: async () => calls.push('wake')});
  pu.wanted = () => ({stamp: source});
  pu.snapshotSource = async () => ({root:'isolated test project', stamp:source});
  pu.locate = async () => {calls.push('locate'); return 'tablet:5555';};
  pu.installedByAdb = async () => ({stamp: installed, name: '1.0.0+' + installed});
  pu.volume = async () => -1;
  pu.relaunch = async () => calls.push('relaunch');
  pu.deploy = async (_, mode) => {
    calls.push(mode);
    if (mode === 'prepare') fs.writeFileSync(pu.ready.apk, 'compiled APK');
    if (mode === 'install') installed = pu.ready.wanted;
    return true;
  };
  const dirs = [];
  try {
    let result = await pu.update('prepare');
    assert.ok(result.ok && result.ready);
    dirs.push(path.dirname(pu.ready.apk));
    assert.equal(installed, 'bbbbbbbbbbbb');
    assert.deepEqual(calls, ['prepare'], 'preparing must not locate, stop, install or wake the tablet');
    assert.ok(events.some(e => e.step === 'ready'));
    source = 'cccccccccccc';
    result = await pu.update('install');
    assert.equal(result.ok, false);
    assert.match(result.why, /source changed/);
    assert.deepEqual(calls, ['prepare'], 'stale APK cannot install');
    source = 'aaaaaaaaaaaa';
    fs.appendFileSync(pu.ready.apk, 'changed');
    result = await pu.update('install');
    assert.equal(result.ok, false);
    assert.match(result.why, /APK changed/);
    result = await pu.update('prepare');
    dirs.push(path.dirname(pu.ready.apk));
    assert.ok(result.ready);
    result = await pu.update('install');
    assert.ok(result.ok && result.relaunched);
    assert.equal(installed, source);
    assert.equal(pu.ready, null);
    assert.deepEqual(calls, ['prepare', 'prepare', 'locate', 'stop', 'install', 'wake', 'relaunch']);
    assert.equal((await pu.update('install')).ok, false, 'second install needs a prepared artifact');
    pu.job.running = true;
    assert.equal((await pu.update('prepare')).ok, false, 'concurrent build cannot replace the job');
    console.log('PineTab prepare/install transitions: passed');
  } finally {
    for (const dir of dirs) {
      assert.ok(dir.startsWith(path.join(os.tmpdir(), 'pinetab-ready-')));
      fs.rmSync(dir, {recursive:true, force:true});
    }
  }
})().catch(e => {console.error(e); process.exitCode = 1;});
