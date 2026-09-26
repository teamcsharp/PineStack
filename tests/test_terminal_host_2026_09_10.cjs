/* The provisioner's wiring into the desktop.
 *
 * There is very little logic here on purpose - the decisions live in
 * terminal.cjs, firmware.cjs and gsi.cjs, which are tested without
 * hardware. What this layer owns is where adb lives, and one refusal that
 * must hold even if every other check were somehow skipped: the desktop
 * cannot unlock a tablet when no restore image is configured.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {TerminalHost, findTools} = require('../desktop/terminal-host.cjs');

const isWindows = process.platform === 'win32';
const adbName = isWindows ? 'adb.exe' : 'adb';

function toolsDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-tools-'));
  fs.writeFileSync(path.join(dir, adbName), 'not really adb');
  fs.writeFileSync(path.join(dir, isWindows ? 'fastboot.exe' : 'fastboot'), 'nor this');
  return dir;
}

test('a configured platform-tools folder wins over everything else', () => {
  const dir = toolsDir();
  const tools = findTools(dir);
  assert.equal(tools.found, true);
  assert.equal(tools.root, dir);
  assert.equal(tools.adb, path.join(dir, adbName));
  assert.ok(tools.fastboot.endsWith(isWindows ? 'fastboot.exe' : 'fastboot'));
  fs.rmSync(dir, {recursive: true, force: true});
});

test('with nothing on disk it falls back to PATH and says so', () => {
  const tools = findTools(path.join(os.tmpdir(), 'pine-tools-definitely-not-here'));
  if (tools.found) return;   /* a machine with real platform-tools installed */
  assert.equal(tools.onPath, true);
  assert.equal(tools.adb, adbName);
  assert.equal(tools.root, '');
});

test('the survey reports a missing adb as a missing TOOL, not a missing tablet', async () => {
  const host = new TerminalHost({
    readConfig: () => ({platformTools: path.join(os.tmpdir(), 'pine-nope-xyz')})
  });
  const tools = host.tools();
  if (tools.found) return;   /* real tools present; nothing to prove here */
  const survey = await host.survey();
  assert.equal(survey.device.found, false);
  assert.equal(survey.verdict.ok, false);
  /* The distinction matters: "no tablet" sends the operator to the cable,
   * "no adb" sends them to a download. */
  assert.match(survey.notes.join(' '), /adb was not found|adb could not be run/);
});

test('the desktop cannot unlock without a restore image configured', async () => {
  let ranAnything = false;
  const host = new TerminalHost({readConfig: () => ({})});
  host.terminal = () => {
    ranAnything = true;
    throw new Error('the tablet must not be touched');
  };
  const result = await host.unlock('ERASE THIS TABLET');
  assert.equal(result.ok, false);
  assert.equal(result.ran, false);
  assert.match(result.verdict.blockers.join(' '), /No restore image is configured/);
  assert.match(result.verdict.blockers.join(' '), /erases the tablet/);
  assert.equal(ranAnything, false,
    'it must refuse before going anywhere near fastboot');
});

test('verify calls refuse plainly when nothing is configured', async () => {
  const host = new TerminalHost({readConfig: () => ({})});
  const fw = await host.verifyFirmware();
  assert.equal(fw.ok, false);
  assert.match(fw.blockers.join(' '), /No firmware folder/);
  const image = await host.verifyGsi();
  assert.equal(image.ok, false);
  assert.match(image.blockers.join(' '), /No GSI image/);
});

test('install() registers the whole provisioning surface', () => {
  const registered = [];
  const fakeIpc = {handle: (name) => registered.push(name)};
  new TerminalHost({readConfig: () => ({})}).install(fakeIpc);
  for (const name of ['terminal:tools', 'terminal:survey', 'terminal:snapshot',
    'terminal:bootloader', 'terminal:reboot', 'terminal:verify-firmware',
    'terminal:verify-gsi', 'terminal:unlock', 'terminal:discover',
    'terminal:wireless-enable', 'terminal:wireless-connect',
    'terminal:wireless-disconnect']) {
    assert.ok(registered.includes(name), 'missing handler ' + name);
  }
});

test('discovery lists a cabled tablet alongside anything on the network', async () => {
  const host = new TerminalHost({readConfig: () => ({})});
  host.terminal = () => ({
    findTerminals: async () => ({found: [{host: '10.89.1.77', port: 5555,
      serial: 'HA1Y7RCV', how: 'mdns'}], notes: []}),
    devices: async () => [{serial: 'HA1Y7RCV', state: 'device'}]
  });
  const result = await host.discover();
  assert.equal(result.found.length, 2);
  assert.ok(result.found.some((d) => d.how === 'mdns'));
  assert.ok(result.found.some((d) => d.how === 'usb'),
    'a tablet on the cable is still a terminal, even if it was not discovered');
});

test('a network listing survives adb being unable to list USB devices', async () => {
  const host = new TerminalHost({readConfig: () => ({})});
  host.terminal = () => ({
    findTerminals: async () => ({found: [{host: '10.89.1.77', how: 'sweep'}], notes: []}),
    devices: async () => { throw new Error('adb is gone'); }
  });
  const result = await host.discover();
  assert.equal(result.found.length, 1, 'the network result must not be lost');
});

test('glass features reattach to an online tablet before calling it absent', async () => {
  const host = new TerminalHost({readConfig: () => ({})});
  let reads = 0;
  let connected = '';
  host.terminal = () => ({
    devices: async () => (++reads < 2 ? [] : [
      {serial: '10.89.1.154:5555', authorized: true}
    ])
  });
  host.station = async (route) => {
    assert.equal(route, '/api/tablet/look');
    return {host: '10.89.1.154', port: 5555, fetching: true,
      adb_port_open: true};
  };
  host.wirelessConnect = async (address, port) => {
    connected = address + ':' + port;
    return {ok: true};
  };

  assert.equal(await host.glassSerial(), '10.89.1.154:5555');
  assert.equal(connected, '10.89.1.154:5555');
});

test('glass auto-attach refuses a remembered tablet without a live heartbeat', async () => {
  const host = new TerminalHost({readConfig: () => ({})});
  let connects = 0;
  host.terminal = () => ({devices: async () => []});
  host.station = async () => ({host: '10.89.1.154', port: 5555,
    fetching: false, adb_port_open: true});
  host.wirelessConnect = async () => { connects += 1; return {ok: true}; };

  assert.equal(await host.glassSerial(), '');
  assert.equal(connects, 0);
});
