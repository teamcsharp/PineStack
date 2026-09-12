/* The terminal provisioner's read-only stage, without a tablet.
 *
 * The fixtures are real output shapes from the M9 on the bench:
 * VID_0E8D (MediaTek), serial HA1Y7RCV, which first appeared to adb as
 * `unauthorized` because nothing had ever asked it for permission.
 *
 * What these pin down is the GATE - what the provisioner refuses to do and
 * why - because every one of those refusals stands between the operator
 * and an erased tablet.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {
  Terminal, parseDevices, parseProps, parseBattery,
  lockState, unlockAllowance, readiness
} = require('../desktop/terminal.cjs');

const DEVICES_UNAUTHORIZED =
  'List of devices attached\nHA1Y7RCV               unauthorized transport_id:2\n';
const DEVICES_OK =
  'List of devices attached\n'
  + 'HA1Y7RCV               device product:TB310FU model:Lenovo_TB310FU '
  + 'device:TB310FU transport_id:3\n';

function props(overrides) {
  const base = {
    'ro.product.model': 'Lenovo TB310FU',
    'ro.product.device': 'TB310FU',
    'ro.product.manufacturer': 'LENOVO',
    'ro.build.fingerprint': 'Lenovo/TB310FU/TB310FU:13/TP1A.220624.014/S000123:user/release-keys',
    'ro.build.version.release': '13',
    'ro.build.version.sdk': '33',
    'ro.serialno': 'HA1Y7RCV',
    'ro.boot.verifiedbootstate': 'green',
    'ro.boot.flash.locked': '1',
    'ro.oem_unlock_supported': '1',
    'sys.oem_unlock_allowed': '1'
  };
  return Object.entries(Object.assign(base, overrides || {}))
    .map(([k, v]) => '[' + k + ']: [' + v + ']').join('\n');
}

const BATTERY = 'Current Battery Service state:\n  AC powered: true\n'
  + '  status: 2\n  health: 2\n  present: true\n  level: 87\n  scale: 100\n';

function fixture(overrides, battery) {
  const calls = [];
  const run = async (args) => {
    calls.push(args.join(' '));
    const line = args.join(' ');
    if (line.includes('devices')) return overrides.devices || DEVICES_OK;
    if (line.includes('dumpsys battery')) return battery === undefined ? BATTERY : battery;
    if (line.includes('getprop')) return props(overrides.props);
    if (line.includes('pm list packages')) return 'package:/system/app/A.apk=com.a\n';
    if (line.includes('pm list features')) return 'feature:android.hardware.audio.output\n';
    if (line.includes('settings list global')) return 'adb_enabled=1\n';
    return '';
  };
  return {terminal: new Terminal({run, now: () => 1789000000000}), calls};
}

test('adb device lines are read, including the unauthorized case', () => {
  const waiting = parseDevices(DEVICES_UNAUTHORIZED);
  assert.equal(waiting.length, 1);
  assert.equal(waiting[0].serial, 'HA1Y7RCV');
  assert.equal(waiting[0].state, 'unauthorized');
  assert.equal(waiting[0].authorized, false);

  const ready = parseDevices(DEVICES_OK);
  assert.equal(ready[0].authorized, true);
  assert.equal(ready[0].model, 'Lenovo_TB310FU');
  assert.equal(ready[0].product, 'TB310FU');

  /* The daemon's own chatter is not a device. */
  assert.equal(parseDevices('* daemon started successfully\n').length, 0);
  assert.equal(parseDevices('').length, 0);
});

test('getprop and battery output are parsed, and nonsense is not invented', () => {
  const parsed = parseProps(props());
  assert.equal(parsed['ro.product.device'], 'TB310FU');
  assert.equal(parsed['ro.serialno'], 'HA1Y7RCV');
  assert.equal(parseBattery(BATTERY), 87);
  assert.equal(parseBattery('level: 30\nscale: 60\n'), 50, 'scale is honoured');
  assert.equal(parseBattery('nothing useful'), null);
});

test('the bootloader is read from two independent signals', () => {
  assert.equal(lockState({'ro.boot.flash.locked': '1'}), 'locked');
  assert.equal(lockState({'ro.boot.verifiedbootstate': 'green'}), 'locked');
  assert.equal(lockState({'ro.boot.flash.locked': '0'}), 'unlocked');
  assert.equal(lockState({'ro.boot.verifiedbootstate': 'orange'}), 'unlocked');
  assert.equal(lockState({}), 'unknown', 'silence is not a lock state');
});

test('OEM unlock allowance distinguishes off, unsupported and unknown', () => {
  assert.equal(unlockAllowance({'sys.oem_unlock_allowed': '1'}), 'allowed');
  assert.equal(unlockAllowance({'sys.oem_unlock_allowed': '0'}), 'blocked');
  assert.equal(unlockAllowance({'ro.oem_unlock_supported': '0'}), 'unsupported');
  assert.equal(unlockAllowance({}), 'unknown');
});

test('an identified tablet in good order is cleared to proceed', async () => {
  const {terminal} = fixture({});
  const report = await terminal.identify();
  assert.equal(report.found, true);
  assert.equal(report.authorized, true);
  assert.equal(report.identity.serial, 'HA1Y7RCV');
  assert.equal(report.identity.device, 'TB310FU');
  assert.equal(report.identity.android, '13');
  assert.equal(report.identity.bootloader, 'locked');
  assert.equal(report.identity.oemUnlock, 'allowed');
  assert.equal(report.battery, 87);

  const verdict = readiness(report);
  assert.equal(verdict.ok, true);
  assert.deepEqual(verdict.blockers, []);
});

test('an unauthorized tablet is a person-shaped problem, and says so', async () => {
  const {terminal, calls} = fixture({devices: DEVICES_UNAUTHORIZED});
  const report = await terminal.identify();
  assert.equal(report.found, true);
  assert.equal(report.authorized, false);
  assert.equal(report.state, 'unauthorized');
  assert.equal(report.identity, undefined);
  /* It must not go poking the device that has not said yes yet. */
  assert.equal(calls.filter((c) => c.includes('shell')).length, 0);

  const verdict = readiness(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /Allow USB debugging/);
  assert.match(verdict.blockers[0], /locked or mid-update/,
    'the reason the prompt is invisible is the useful half');
});

test('no tablet at all is reported as a cable, not a fault', async () => {
  const {terminal} = fixture({devices: 'List of devices attached\n'});
  const report = await terminal.identify();
  assert.equal(report.found, false);
  const verdict = readiness(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /data cable|File transfer/);
});

test('OEM unlocking greyed out blocks the flow with the Lenovo remedy', async () => {
  const {terminal} = fixture({props: {'sys.oem_unlock_allowed': '0'}});
  const verdict = readiness(await terminal.identify());
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /OEM unlocking is off or greyed out/);
  assert.match(verdict.blockers[0], /Wi-Fi for a few hours/);
});

test('a device that cannot be unlocked at all is refused outright', async () => {
  const {terminal} = fixture({props: {'ro.oem_unlock_supported': '0', 'sys.oem_unlock_allowed': '0'}});
  const verdict = readiness(await terminal.identify());
  assert.equal(verdict.ok, false);
  assert.equal(verdict.blockers.length, 1);
  assert.match(verdict.blockers[0], /not supported/);
});

test('a flat battery blocks flashing, because that is how a tablet is bricked', async () => {
  const {terminal} = fixture({}, 'level: 31\nscale: 100\n');
  const report = await terminal.identify();
  assert.equal(report.battery, 31);
  const verdict = readiness(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /Charge past 50%/);

  /* Unreadable is a warning, not a block - refusing to work because a
   * number was missing would be its own kind of wrong. */
  const soft = fixture({}, 'nothing');
  const softVerdict = readiness(await soft.terminal.identify());
  assert.equal(softVerdict.ok, true);
  assert.match(softVerdict.warnings.join(' '), /battery level/);
});

test('an already-unlocked bootloader is noted but does not block', async () => {
  const {terminal} = fixture({props: {'ro.boot.flash.locked': '0', 'ro.boot.verifiedbootstate': 'orange'}});
  const verdict = readiness(await terminal.identify());
  assert.equal(verdict.ok, true);
  assert.match(verdict.warnings.join(' '), /already unlocked/);
});

test('the snapshot records what it is, and admits what it is not', async () => {
  const {terminal} = fixture({});
  const shot = await terminal.snapshot();
  assert.equal(shot.ok, true);
  assert.equal(shot.serial, 'HA1Y7RCV');
  assert.equal(shot.completeness, 'partial');
  assert.match(shot.caveat, /not a restorable image/);
  assert.match(shot.caveat, /erases the device/);
  assert.ok(shot.parts.packages.includes('com.a'));
  assert.ok(shot.parts.props.includes('ro.serialno'));
});

test('a snapshot is never taken of a tablet that has not said yes', async () => {
  const {terminal, calls} = fixture({devices: DEVICES_UNAUTHORIZED});
  const shot = await terminal.snapshot();
  assert.equal(shot.ok, false);
  assert.equal(calls.filter((c) => c.includes('pm list')).length, 0);
});

test('the runner is required, so nothing here can silently shell out', () => {
  assert.throws(() => new Terminal({}), /needs a runner/);
});
