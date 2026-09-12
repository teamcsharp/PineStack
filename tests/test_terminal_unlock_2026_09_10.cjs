/* The fastboot half of the provisioner - the part that can erase a tablet.
 *
 * GETVAR below is the real output read off HA1Y7RCV on 2026-09-10: an A/B
 * MediaTek device on slot a, locked and secure, product t6100a_wifi.
 *
 * Almost every test here asserts a REFUSAL, because that is what this code
 * mostly is. `fastboot flashing unlock` wipes the tablet and cannot be
 * undone, so the interesting behaviour is all in what it declines to do.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {
  Terminal, parseGetvar, bootloaderState, unlockReadiness
} = require('../desktop/terminal.cjs');

const GETVAR = [
  '(bootloader) max-download-size: 0x8000000',
  '(bootloader) hw-revision: ca00',
  '(bootloader) battery-soc-ok: yes',
  '(bootloader) battery-voltage: 4014mV',
  '(bootloader) serialno: HA1Y7RCV',
  '(bootloader) unlocked: no',
  '(bootloader) secure: yes',
  '(bootloader) product: t6100a_wifi',
  '(bootloader) is-userspace: no',
  '(bootloader) slot-count: 2',
  '(bootloader) current-slot: a',
  '(bootloader) version-bootloader: t6100a_wifi-4babc561b-20250515134948-20',
  'finished. total time: 0.031s'
].join('\n');

const OK_FIRMWARE = {ok: true};
const CONFIRM = 'ERASE THIS TABLET';
const state = () => bootloaderState(parseGetvar(GETVAR));

function fixture({getvar = GETVAR, obeys = true} = {}) {
  const calls = [];
  let unlocked = false;
  const runFastboot = async (args) => {
    calls.push(args.join(' '));
    if (args[0] === 'getvar') {
      return unlocked && obeys ? getvar.replace('unlocked: no', 'unlocked: yes') : getvar;
    }
    if (args[0] === 'flashing' && args[1] === 'unlock') { unlocked = true; return 'OKAY'; }
    if (args[0] === 'devices') return 'HA1Y7RCV\tfastboot\n';
    return '';
  };
  return {
    terminal: new Terminal({run: async () => '', runFastboot, now: () => 1789000000000}),
    calls
  };
}

test('the bootloader is read exactly as fastboot reports it', () => {
  const read = state();
  assert.equal(read.serial, 'HA1Y7RCV');
  assert.equal(read.product, 't6100a_wifi');
  assert.equal(read.unlocked, false);
  assert.equal(read.secure, true);
  assert.equal(read.slotCount, 2);
  assert.equal(read.currentSlot, 'a');
  assert.equal(read.userspace, false);
  assert.equal(read.batteryOk, true);
  assert.equal(read.batteryMv, 4014);
  assert.equal(read.maxDownload, 0x8000000);
  /* fastboot's own trailing chatter is not a variable. */
  assert.equal(parseGetvar(GETVAR)['finished. total time'], undefined);
});

test('an unreadable bootloader is unknown, never assumed unlocked', () => {
  const blank = bootloaderState(parseGetvar('nothing useful here'));
  assert.equal(blank.unlocked, null);
  const verdict = unlockReadiness(blank, {firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /did not say whether it is unlocked/);
});

test('unlocking refuses without a verified restore image', () => {
  const verdict = unlockReadiness(state(), {confirm: CONFIRM});
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /No verified restore image/);
  assert.match(verdict.blockers.join(' '), /no way back/);

  const failed = unlockReadiness(state(), {confirm: CONFIRM, firmware: {ok: false}});
  assert.equal(failed.ok, false, 'a package that failed verification is not a restore image');
});

test('unlocking refuses without an explicit, exact confirmation', () => {
  for (const confirm of [undefined, '', 'yes', 'erase this tablet', 'ERASE THIS TABLET ']) {
    const verdict = unlockReadiness(state(), {firmware: OK_FIRMWARE, confirm});
    assert.equal(verdict.ok, false, 'accepted ' + JSON.stringify(confirm));
    assert.match(verdict.blockers.join(' '), /not confirmed/);
  }
  assert.equal(unlockReadiness(state(), {firmware: OK_FIRMWARE, confirm: CONFIRM}).ok, true);
});

test('unlocking refuses a tablet that is not the one we surveyed', () => {
  const verdict = unlockReadiness(state(), {
    firmware: OK_FIRMWARE, confirm: CONFIRM, identity: {serial: 'SOMEONEELSE'}
  });
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /not the tablet that was surveyed/);
});

test('unlocking refuses a low battery, on the bootloader own word', () => {
  const flat = bootloaderState(parseGetvar(GETVAR.replace('battery-soc-ok: yes', 'battery-soc-ok: no')));
  const verdict = unlockReadiness(flat, {firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /battery is too low/);
});

test('unlocking refuses from fastbootd, which cannot do it', () => {
  const userspace = bootloaderState(parseGetvar(GETVAR.replace('is-userspace: no', 'is-userspace: yes')));
  const verdict = unlockReadiness(userspace, {firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /fastbootd/);
});

test('an already-unlocked bootloader is a no-op, not an error', () => {
  const open = bootloaderState(parseGetvar(GETVAR.replace('unlocked: no', 'unlocked: yes')));
  const verdict = unlockReadiness(open, {firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(verdict.ok, false);
  assert.equal(verdict.already, true);
  assert.match(verdict.blockers[0], /already unlocked/);
});

test('the A/B slot and the on-screen confirmation are always said out loud', () => {
  const verdict = unlockReadiness(state(), {firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(verdict.ok, true);
  assert.match(verdict.warnings.join(' '), /A.B device on slot a/);
  assert.match(verdict.warnings.join(' '), /confirm on its own screen/);
});

test('unlock() does not touch the tablet when the gate refuses', async () => {
  const {terminal, calls} = fixture();
  const result = await terminal.unlock({firmware: OK_FIRMWARE});   /* no confirm */
  assert.equal(result.ok, false);
  assert.equal(result.ran, false);
  assert.equal(calls.filter((c) => c.includes('flashing unlock')).length, 0,
    'the unlock command must never be issued past a refusal');
});

test('unlock() runs, then re-reads the bootloader to prove it worked', async () => {
  const {terminal, calls} = fixture();
  const result = await terminal.unlock({
    firmware: OK_FIRMWARE, confirm: CONFIRM, identity: {serial: 'HA1Y7RCV'}
  });
  assert.equal(result.ran, true);
  assert.equal(result.ok, true);
  assert.equal(result.state.unlocked, true);
  assert.equal(calls.filter((c) => c === 'flashing unlock').length, 1);
  /* getvar before AND after: the claim is verified, not assumed. */
  assert.ok(calls.filter((c) => c.startsWith('getvar')).length >= 2);
});

test('an unlock the device silently ignored is reported as failed', async () => {
  const {terminal} = fixture({obeys: false});
  const result = await terminal.unlock({firmware: OK_FIRMWARE, confirm: CONFIRM});
  assert.equal(result.ran, true);
  assert.equal(result.ok, false,
    'still locked means it did not work, whatever fastboot printed');
});

test('a terminal with no fastboot runner cannot pretend to unlock', async () => {
  const bare = new Terminal({run: async () => ''});
  assert.equal(bare.fastbootAvailable(), false);
  await assert.rejects(() => bare.unlock({firmware: OK_FIRMWARE, confirm: CONFIRM}),
    /No fastboot runner/);
  assert.deepEqual(await bare.fastbootDevices(), []);
});

test('reboot targets are explicit, and an unknown one is refused', async () => {
  const {terminal, calls} = fixture();
  await terminal.rebootTo('bootloader');
  await terminal.rebootTo('fastbootd');
  await terminal.rebootTo('system');
  assert.ok(calls.includes('reboot fastboot'), 'fastbootd is a fastboot reboot');
  assert.ok(calls.includes('reboot'));
  await assert.rejects(() => terminal.rebootTo('somewhere'), /Unknown reboot target/);
});
