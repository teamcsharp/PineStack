/* The provisioner, wired into the desktop.
 *
 * This is the layer between the Pine Box app and the three modules that
 * actually know things: terminal.cjs (the tablet), firmware.cjs (the way
 * back) and gsi.cjs (what we are about to put on it).
 *
 * It owns exactly two things those modules deliberately do not: WHERE adb
 * and fastboot live on this machine, and how to run them. Everything else
 * it delegates, so the decisions stay in the tested modules rather than in
 * IPC handlers nobody can exercise without a tablet.
 *
 * The survey() call is the one the UI leans on: one round trip that answers
 * "what is plugged in, is it fit to touch, do we have a way back, and is
 * the image we mean to flash the right one".
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFile } = require('node:child_process');

const { Terminal, readiness, parseProps } = require('./terminal.cjs');
const firmware = require('./firmware.cjs');
const gsi = require('./gsi.cjs');
const { AndroidBuild } = require('./android-build.cjs');
const pinetab = require('./pinetab-route.cjs');
const audio = require('./terminal-audio.cjs');

/* Where platform-tools tend to be. The configured path wins; after that we
 * look where we put them, then fall back to whatever is on PATH. */
const LIKELY = [
  'C:\\_tools\\platform-tools',
  'C:\\platform-tools',
  path.join(process.env.LOCALAPPDATA || '', 'Android', 'Sdk', 'platform-tools')
];

function exeName(tool) {
  return process.platform === 'win32' ? tool + '.exe' : tool;
}

function findTools(configured) {
  const roots = [configured, ...LIKELY].filter(Boolean);
  for (const root of roots) {
    const adb = path.join(root, exeName('adb'));
    if (fs.existsSync(adb)) {
      return {
        root,
        adb,
        fastboot: path.join(root, exeName('fastboot')),
        onPath: false,
        found: true
      };
    }
  }
  /* Nothing on disk where we expect it: hand back bare names and let the
   * OS resolve them. If that fails too, `found` being false is what the UI
   * reports - it does not pretend a missing tool is a missing tablet. */
  return {root: '', adb: exeName('adb'), fastboot: exeName('fastboot'),
    onPath: true, found: false};
}

function runner(exe, timeout) {
  return (args) => new Promise((resolve, reject) => {
    execFile(exe, args, {maxBuffer: 64 * 1024 * 1024, timeout: timeout || 180000},
      (error, stdout, stderr) => {
        const text = String(stdout || '') + String(stderr || '');
        /* fastboot writes almost everything to stderr and a non-zero exit
         * still carries the reason, so output beats the error object. */
        if (error && !text) return reject(error);
        resolve(text);
      });
  });
}

class TerminalHost {
  constructor({readConfig, writeConfig} = {}) {
    this.readConfig = readConfig || (() => ({}));
    this.writeConfig = writeConfig || (() => {});
  }

  tools() {
    const cfg = this.readConfig() || {};
    return findTools(cfg.platformTools);
  }

  terminal() {
    const tools = this.tools();
    /* Unlock can sit for a minute waiting for a finger on the tablet. */
    return new Terminal({
      run: runner(tools.adb, 120000),
      runFastboot: runner(tools.fastboot, 300000)
    });
  }

  /* Everything the provisioning screen needs, in one call. Nothing here
   * throws for an absent tablet or a missing tool - those are states to
   * paint, not errors to catch. */
  async survey() {
    const cfg = this.readConfig() || {};
    const tools = this.tools();
    const out = {at: Date.now(), tools, device: null, verdict: null,
      props: null, requirement: null, firmware: null, gsi: null, notes: []};

    if (!tools.found && !tools.onPath) {
      out.notes.push('adb was not found. Install Google platform-tools.');
    }

    const terminal = this.terminal();
    try {
      out.device = await terminal.identify();
    } catch (error) {
      out.device = {found: false, authorized: false, at: Date.now()};
      out.notes.push('adb could not be run: ' + error.message);
    }
    out.verdict = readiness(out.device);

    /* Treble facts only exist once the tablet has said yes. */
    if (out.device && out.device.authorized) {
      try {
        const raw = await runner(tools.adb, 60000)(['-s', out.device.serial, 'shell', 'getprop']);
        out.props = parseProps(raw);
        out.requirement = gsi.requirement(out.props);
      } catch (error) { /* the survey still stands without it */ }
    }

    if (cfg.firmwareDir) {
      const report = firmware.inspect(cfg.firmwareDir, {hashFiles: false});
      out.firmware = {
        report: {
          dir: report.dir, found: report.found, bytes: report.bytes,
          scatter: report.scatter, images: report.images, notes: report.notes
        },
        verdict: firmware.restorability(report,
          out.device && out.device.identity ? out.device.identity : null)
      };
    }

    if (cfg.gsiImage) {
      const image = gsi.inspect(cfg.gsiImage, {hash: false});
      out.gsi = {
        image,
        verdict: out.requirement ? gsi.match(out.requirement, image) : null
      };
    }
    return out;
  }

  /* Hashing 6.5 GB is not something to do on every repaint, so it is its
   * own call and the UI asks for it deliberately. */
  async verifyFirmware(dir) {
    const target = dir || (this.readConfig() || {}).firmwareDir;
    if (!target) return {ok: false, blockers: ['No firmware folder is set.']};
    const report = firmware.inspect(target, {hashFiles: true});
    const device = await this.terminal().identify().catch(() => null);
    return {
      report,
      verdict: firmware.restorability(report,
        device && device.identity ? device.identity : null)
    };
  }

  async verifyGsi(file) {
    const target = file || (this.readConfig() || {}).gsiImage;
    if (!target) return {ok: false, blockers: ['No GSI image is set.']};
    const image = gsi.inspect(target, {hash: true});
    const survey = await this.survey();
    return {
      image,
      verdict: survey.requirement ? gsi.match(survey.requirement, image) : null
    };
  }

  /* THE DESTRUCTIVE ONE.
   *
   * The renderer cannot unlock by accident: it has to pass the same exact
   * confirmation string the tested gate demands, and this refuses before
   * going near fastboot unless a verified restore image exists. */
  async unlock(confirm) {
    const cfg = this.readConfig() || {};
    if (!cfg.firmwareDir) {
      return {ok: false, ran: false, verdict: {ok: false, warnings: [],
        blockers: ['No restore image is configured. Unlocking erases the '
          + 'tablet, so a verified stock package must be on disk first.']}};
    }
    const checked = await this.verifyFirmware(cfg.firmwareDir);
    const device = await this.terminal().identify().catch(() => null);
    return this.terminal().unlock({
      firmware: checked.verdict,
      identity: device && device.identity ? device.identity : null,
      confirm
    });
  }

  /* ---- wireless -------------------------------------------------------
   * Once a terminal is provisioned the cable is optional: it is found on
   * the network, connected to, and updated from here. */

  async wirelessEnable(port) {
    /* Target the CABLED device explicitly. Once the tablet is on both USB
     * and Wi-Fi, adb has two transports for it and refuses an untargeted
     * command with "more than one device/emulator". */
    let serial = '';
    try {
      const usb = await this.terminal().devices();
      const cabled = usb.find((d) => d.authorized && !d.serial.includes(':'));
      if (cabled) serial = cabled.serial;
    } catch (error) { /* fall through untargeted */ }
    return this.terminal().wirelessEnable(port || 5555, serial);
  }

  async wirelessConnect(host, port) {
    return this.terminal().wirelessConnect(host, port || 5555);
  }

  async wirelessDisconnect(host) {
    return this.terminal().wirelessDisconnect(host);
  }

  /* Every terminal this machine can see. mDNS first; the subnet sweep is
   * the fallback and can be refused by the caller. */
  async discover(options) {
    const found = await this.terminal().findTerminals(options || {});
    /* A device already on the USB cable is not a discovery, but it IS a
     * terminal, and leaving it off the list would be confusing. */
    try {
      const usb = await this.terminal().devices();
      for (const device of usb) {
        if (device.serial && !device.serial.includes(':')) {
          found.found.push({host: '', port: 0, serial: device.serial,
            how: 'usb', state: device.state});
        }
      }
    } catch (error) { /* the network list still stands */ }
    return found;
  }

  /* ---- the PineTab app ------------------------------------------------
   * Building the kiosk APK and putting it on the tablet, from here. */

  androidBuilder() {
    const { execFile } = require('node:child_process');
    return new AndroidBuild({
      run: (cmd, args, options) => new Promise((resolve, reject) => {
        execFile(cmd, args, Object.assign({maxBuffer: 64 * 1024 * 1024,
          timeout: 1800000, windowsHide: true}, options || {}),
          (error, stdout, stderr) => {
            const text = String(stdout || '') + String(stderr || '');
            if (error) return reject(Object.assign(error, {output: text}));
            resolve(text);
          });
      })
    });
  }

  async buildApk(options) {
    const cfg = this.readConfig() || {};
    return this.androidBuilder().build(Object.assign(
      {projectDir: cfg.androidProject || 'C:\_tools\pinebox-android\PineBoxKiosk'},
      options || {}));
  }

  async installApk(options) {
    const tools = this.tools();
    let serial = '';
    try {
      const devices = await this.terminal().devices();
      const first = devices.find((d) => d.authorized);
      if (first) serial = first.serial;
    } catch (error) { /* untargeted install */ }
    return this.androidBuilder().installApk(Object.assign(
      {serial, adb: tools.adb}, options || {}));
  }

  /* ---- where the broadcast goes -------------------------------------
   * The station's own routes never learn about the tablet; the desktop and
   * the tablet simply agree which of them is the page-side sink, through
   * the settings every install already shares. */

  async station(route, options) {
    const cfg = this.readConfig() || {};
    const base = String(cfg.baseUrl || 'http://10.89.1.246:8096').replace(/\/+$/, '');
    const headers = Object.assign({'Content-Type': 'application/json'},
      cfg.apiKey ? {Authorization: 'Bearer ' + cfg.apiKey} : {});
    const response = await fetch(base + route,
      Object.assign({headers}, options || {}));
    if (!response.ok) {
      throw new Error(route + ' answered ' + response.status + ' ' + response.statusText);
    }
    return response.json();
  }

  async pinetabWhere() {
    const [state, settings, roster] = await Promise.all([
      this.station('/api/dj'), this.station('/api/settings'),
      this.station('/api/radio/listeners')
    ]);
    return {
      current: pinetab.currentDestination(state, settings, roster),
      offered: pinetab.destinations(),
      tabShouldPlay: pinetab.tabShouldPlay(state, settings, roster),
      roster
    };
  }

  /* THREE writes, and the order is the whole correctness argument.
   *
   * 1. solo   - hand the air to the one page that should have it
   * 2. output - move the route
   * 3. settings - record the destination durably
   *
   * The air goes FIRST. The other way round there is a window where the
   * show is routed to a page and no page believes it is the sink - which,
   * depending on which way it lands, is either silence or every page
   * sounding at once. Both are worse than a moment of the old destination.
   *
   * planFor refuses outright when the chosen destination is not looking at
   * the station, rather than routing to `here` with nobody holding the air:
   * that is precisely the state where three pages play a half-second apart.
   */
  async pinetabSend(key) {
    const [settings, roster] = await Promise.all([
      this.station('/api/settings'), this.station('/api/radio/listeners')
    ]);
    const plan = pinetab.planFor(key, settings, roster);
    if (!plan.ok) return plan;
    if (plan.solo) {
      await this.station('/api/radio/solo',
        {method: 'POST', body: JSON.stringify(plan.solo)});
    }
    await this.station('/api/dj/output', {method: 'POST', body: JSON.stringify(plan.output)});
    await this.station('/api/settings', {method: 'PUT', body: JSON.stringify(plan.settings)});
    return Object.assign({}, plan, {sent: true, at: Date.now()});
  }

  /* ---- the routing table: which device makes the noise ---------------
   *
   * Separate from pinetabSend above, and deliberately so. That one answers
   * "where does the station send this stream"; this one answers "of the
   * devices looking at a page, which one is the room" - and carries each
   * device's own volumes, so the tablet's levels are settable from here.
   */

  async audioTable() {
    const [settings, roster] = await Promise.all([
      this.station('/api/settings'), this.station('/api/radio/listeners')
    ]);
    return Object.assign(audio.decide(settings, roster),
      {at: Date.now(), me: 'desktop'});
  }

  /* Set one device's switch or levels. The whole settings document goes
   * back because PUT /api/settings REPLACES it. */
  async audioSet(id, patch) {
    const settings = await this.station('/api/settings');
    const out = audio.update(settings, id, patch || {});
    if (!out.ok) return out;
    await this.station('/api/settings',
      {method: 'PUT', body: JSON.stringify(out.settings)});
    const roster = await this.station('/api/radio/listeners');
    return {ok: true, row: out.row,
      decision: audio.decide(out.settings, roster), at: Date.now()};
  }

  install(ipcMain) {
    const handle = (name, fn) => ipcMain.handle(name, (_event, ...args) => fn(...args));
    handle('terminal:tools', () => this.tools());
    handle('terminal:survey', () => this.survey());
    handle('terminal:snapshot', (serial) => this.terminal().snapshot(serial));
    handle('terminal:bootloader', () => this.terminal().bootloader());
    handle('terminal:reboot', (mode) => this.terminal().rebootTo(mode));
    handle('terminal:verify-firmware', (dir) => this.verifyFirmware(dir));
    handle('terminal:verify-gsi', (file) => this.verifyGsi(file));
    handle('terminal:unlock', (confirm) => this.unlock(confirm));
    handle('terminal:discover', (options) => this.discover(options));
    handle('terminal:wireless-enable', (port) => this.wirelessEnable(port));
    handle('terminal:wireless-connect', (host, port) => this.wirelessConnect(host, port));
    handle('terminal:wireless-disconnect', (host) => this.wirelessDisconnect(host));
    handle('terminal:toolchain', () => this.androidBuilder().toolchain());
    handle('terminal:build-apk', (options) => this.buildApk(options));
    handle('terminal:install-apk', (options) => this.installApk(options));
    handle('pinetab:where', () => this.pinetabWhere());
    handle('pinetab:send', (key) => this.pinetabSend(key));
    handle('terminal-audio:table', () => this.audioTable());
    handle('terminal-audio:set', (id, patch) => this.audioSet(id, patch));
    return this;
  }
}

module.exports = {TerminalHost, findTools, runner, LIKELY};
