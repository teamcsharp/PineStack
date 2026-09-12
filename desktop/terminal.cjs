/* The terminal provisioner - discovery and identity, over USB.
 *
 * This is the read-only half. It finds a tablet, says exactly what it is,
 * and decides whether it is in a fit state to be touched. It writes
 * nothing, flashes nothing and unlocks nothing.
 *
 * It is modelled on the LCD firmware manager, which has been through this
 * once already on real hardware: identify the device by something it cannot
 * change, record what you found with a hash and a timestamp, and refuse to
 * act on anything that does not match. The tools differ - adb and fastboot
 * rather than esptool and espota - the discipline does not.
 *
 * `run` is injected so every one of these paths is testable without a
 * tablet on the end of a cable.
 */
'use strict';

const READINESS_BATTERY_FLOOR = 50;

/* One shell round trip for the lot: a getprop per fact would be a dozen
 * process launches for a screen that repaints. */
const PROPS = [
  'ro.product.model',
  'ro.product.device',
  'ro.product.manufacturer',
  'ro.product.name',
  'ro.build.fingerprint',
  'ro.build.version.release',
  'ro.build.version.sdk',
  'ro.build.id',
  'ro.serialno',
  'ro.boot.verifiedbootstate',
  'ro.boot.flash.locked',
  'ro.oem_unlock_supported',
  'sys.oem_unlock_allowed'
];

function parseDevices(text) {
  const out = [];
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^List of devices/i.test(line) || /^\*/.test(line)) continue;
    const parts = line.split(/\s+/);
    const serial = parts.shift();
    const state = parts.shift() || 'unknown';
    if (!serial) continue;
    const extra = {};
    for (const token of parts) {
      const at = token.indexOf(':');
      if (at > 0) extra[token.slice(0, at)] = token.slice(at + 1);
    }
    out.push({
      serial,
      /* device = talking. unauthorized = the RSA prompt has not been
       * accepted on the tablet, which is a person-shaped problem, not a
       * cable-shaped one, and must be reported as such. */
      state,
      authorized: state === 'device',
      model: extra.model || '',
      product: extra.product || '',
      transport: extra.transport_id || ''
    });
  }
  return out;
}

/* `getprop` output is [key]: [value], one per line. */
function parseProps(text) {
  const props = {};
  const shape = /^\[([^\]]+)\]:\s*\[(.*)\]$/;
  for (const raw of String(text || '').split(/\r?\n/)) {
    const match = shape.exec(raw.trim());
    if (match) props[match[1]] = match[2];
  }
  return props;
}

function parseBattery(text) {
  const level = /^\s*level:\s*(\d+)/m.exec(String(text || ''));
  const scale = /^\s*scale:\s*(\d+)/m.exec(String(text || ''));
  if (!level) return null;
  const value = Number(level[1]);
  const top = scale ? Number(scale[1]) : 100;
  if (!Number.isFinite(value) || !top) return null;
  return Math.round((value / top) * 100);
}

/* The bootloader's own account of itself. Two independent signals, because
 * a vendor that lies in one sometimes tells the truth in the other. */
function lockState(props) {
  const locked = props['ro.boot.flash.locked'];
  const verified = (props['ro.boot.verifiedbootstate'] || '').toLowerCase();
  if (locked === '0' || verified === 'orange') return 'unlocked';
  if (locked === '1' || verified === 'green') return 'locked';
  return 'unknown';
}

/* THE PHASE A QUESTION, and the reason this stage exists at all.
 *
 * `sys.oem_unlock_allowed` is the Developer-options toggle. On Lenovo and
 * MediaTek tablets it is frequently greyed out until the device has been
 * online for a while, which is in direct tension with wanting no account on
 * it. Finding that out now is cheap; finding it out on flashing day is not. */
function unlockAllowance(props) {
  const allowed = props['sys.oem_unlock_allowed'];
  const supported = props['ro.oem_unlock_supported'];
  if (allowed === '1') return 'allowed';
  if (supported === '0') return 'unsupported';
  if (allowed === '0') return 'blocked';
  return 'unknown';
}

function identityOf(props, serial) {
  return {
    serial: props['ro.serialno'] || serial || '',
    model: props['ro.product.model'] || '',
    device: props['ro.product.device'] || '',
    manufacturer: props['ro.product.manufacturer'] || '',
    productName: props['ro.product.name'] || '',
    fingerprint: props['ro.build.fingerprint'] || '',
    android: props['ro.build.version.release'] || '',
    sdk: props['ro.build.version.sdk'] || '',
    buildId: props['ro.build.id'] || '',
    bootloader: lockState(props),
    oemUnlock: unlockAllowance(props)
  };
}

/* Whether this tablet may be taken to the next stage, and if not, exactly
 * what is in the way - in words the operator can act on. Nothing here is
 * advisory: a blocker stops the flow. */
function readiness(report) {
  const blockers = [];
  const warnings = [];
  const identity = report && report.identity;

  if (!report || !report.found) {
    blockers.push('No tablet is connected. Check the cable is a data cable, '
      + 'and that the USB mode is File transfer rather than charging.');
    return { ok: false, blockers, warnings };
  }
  if (!report.authorized) {
    blockers.push('USB debugging is not authorized yet. Unlock the tablet '
      + 'screen and accept "Allow USB debugging?", ticking "Always allow '
      + 'from this computer". The prompt does not render while the screen '
      + 'is locked or mid-update.');
    return { ok: false, blockers, warnings };
  }
  if (!identity || !identity.serial) {
    blockers.push('The tablet answered, but would not say what it is.');
    return { ok: false, blockers, warnings };
  }

  if (identity.oemUnlock === 'blocked') {
    blockers.push('OEM unlocking is off or greyed out, so the bootloader '
      + 'cannot be unlocked. Turn it on in Developer options. If it will '
      + 'not move, leave the tablet on Wi-Fi for a few hours and try again.');
  } else if (identity.oemUnlock === 'unsupported') {
    blockers.push('This device reports that OEM unlocking is not supported '
      + 'at all. The custom-ROM route is not available on it.');
  } else if (identity.oemUnlock !== 'allowed') {
    warnings.push('Could not read whether OEM unlocking is allowed. Confirm '
      + 'the toggle in Developer options before going further.');
  }

  if (typeof report.battery === 'number') {
    if (report.battery < READINESS_BATTERY_FLOOR) {
      blockers.push('Battery is at ' + report.battery + '%. Charge past '
        + READINESS_BATTERY_FLOOR + '% before flashing - a tablet that dies '
        + 'mid-write is the one way to genuinely brick it.');
    }
  } else {
    warnings.push('Could not read the battery level.');
  }

  if (identity.bootloader === 'unlocked') {
    warnings.push('The bootloader is already unlocked.');
  }

  return { ok: !blockers.length, blockers, warnings };
}

/* ------------------------------------------------------------------ fastboot
 *
 * Everything past this point can erase the tablet, so every one of these
 * reads like a refusal first and an action second.
 */

/* `fastboot getvar all` answers on stderr, one "(bootloader) key: value"
 * per line. Some keys repeat per slot; last one wins, which matches what
 * fastboot itself reports. */
function parseGetvar(text) {
  const vars = {};
  for (const raw of String(text || '').split(/\r?\n/)) {
    const match = /^\(bootloader\)\s*([^:]+):\s*(.*)$/.exec(raw.trim());
    if (match) vars[match[1].trim()] = match[2].trim();
  }
  return vars;
}

function bootloaderState(vars) {
  const unlocked = String(vars.unlocked || '').toLowerCase();
  return {
    serial: vars.serialno || '',
    product: vars.product || '',
    unlocked: unlocked === 'yes' ? true : unlocked === 'no' ? false : null,
    secure: String(vars.secure || '').toLowerCase() === 'yes',
    slotCount: Number(vars['slot-count'] || 0) || 0,
    currentSlot: vars['current-slot'] || '',
    userspace: String(vars['is-userspace'] || '').toLowerCase() === 'yes',
    batteryOk: String(vars['battery-soc-ok'] || '').toLowerCase() === 'yes',
    batteryMv: Number(String(vars['battery-voltage'] || '').replace(/[^0-9]/g, '')) || 0,
    maxDownload: Number(vars['max-download-size'] || 0) || 0,
    bootloaderVersion: vars['version-bootloader'] || ''
  };
}

/* THE LAST GATE BEFORE THE TABLET IS ERASED.
 *
 * `fastboot flashing unlock` wipes userdata and cannot be undone. This
 * refuses unless the identity matches the tablet we surveyed, the
 * bootloader itself says the battery is fine, and a VERIFIED restore image
 * exists on disk. The restore image is not optional here: without one an
 * unlock is a one-way door, and the operator asked specifically for a way
 * back. */
function unlockReadiness(state, {identity, firmware, confirm} = {}) {
  const blockers = [];
  const warnings = [];

  if (!state || state.unlocked === null) {
    blockers.push('The bootloader did not say whether it is unlocked. '
      + 'Is the tablet actually in fastboot?');
    return {ok: false, blockers, warnings};
  }
  if (state.unlocked) {
    return {ok: false, already: true,
      blockers: ['This bootloader is already unlocked - nothing to do.'],
      warnings};
  }
  if (state.userspace) {
    blockers.push('This is fastbootd (userspace fastboot). Unlocking must be '
      + 'done from the real bootloader.');
  }
  if (!state.batteryOk) {
    blockers.push('The bootloader reports the battery is too low to flash '
      + 'safely. Charge it and try again.');
  }
  if (identity && identity.serial && state.serial
      && identity.serial !== state.serial) {
    blockers.push('This is not the tablet that was surveyed: expected '
      + identity.serial + ', found ' + state.serial + '.');
  }
  if (!firmware || !firmware.ok) {
    blockers.push('No verified restore image. Unlocking erases the tablet, '
      + 'and without a checked stock package there is no way back. Download '
      + 'it with LMSA and verify it first.');
  }
  if (confirm !== 'ERASE THIS TABLET') {
    blockers.push('Unlocking is not confirmed. This wipes every byte of user '
      + 'data on the tablet and cannot be undone.');
  }
  if (state.slotCount > 1) {
    warnings.push('An A/B device on slot ' + (state.currentSlot || '?')
      + '. Images must go to the active slot.');
  }
  warnings.push('The tablet will ask you to confirm on its own screen with '
    + 'the volume and power keys. Nothing happens until you do.');
  return {ok: !blockers.length, blockers, warnings};
}

class Terminal {
  /* run(args, options) -> Promise<string>. Everything shells out through
   * this one function, so a test supplies canned output and a real install
   * supplies adb. */
  /* `run` shells out to adb, `runFastboot` to fastboot. Both injected, so
   * every path below is testable without a tablet - including the ones
   * that would erase one. */
  constructor({ run, runFastboot, now = () => Date.now() } = {}) {
    if (typeof run !== 'function') throw new Error('Terminal needs a runner.');
    this.run = run;
    this.runFastboot = runFastboot || null;
    this.now = now;
  }

  fastbootAvailable() { return typeof this.runFastboot === 'function'; }

  async fastbootDevices() {
    if (!this.fastbootAvailable()) return [];
    return parseDevices(await this.runFastboot(['devices']));
  }

  /* The bootloader's own account of itself. */
  async bootloader() {
    if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
    const vars = parseGetvar(await this.runFastboot(['getvar', 'all']));
    return { vars, state: bootloaderState(vars), at: this.now() };
  }

  async rebootTo(mode) {
    if (mode === 'bootloader') return this.run(['reboot', 'bootloader']);
    if (mode === 'fastbootd') {
      if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
      return this.runFastboot(['reboot', 'fastboot']);
    }
    if (mode === 'system') {
      if (this.fastbootAvailable()) return this.runFastboot(['reboot']);
      return this.run(['reboot']);
    }
    throw new Error('Unknown reboot target: ' + mode);
  }

  /* Erases the tablet. Refuses unless unlockReadiness passes, which
   * includes an explicit confirmation string and a verified restore image. */
  async unlock(options = {}) {
    if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
    const { state } = await this.bootloader();
    const verdict = unlockReadiness(state, options);
    if (!verdict.ok) return { ok: false, ran: false, verdict, state };
    const output = await this.runFastboot(['flashing', 'unlock']);
    const after = await this.bootloader();
    return {
      ok: after.state.unlocked === true,
      ran: true, output, verdict,
      state: after.state, at: this.now()
    };
  }

  /* ---- wireless --------------------------------------------------------
   *
   * After provisioning, the cable should be optional. `adb tcpip` restarts
   * the daemon listening on a port; the tablet then answers over Wi-Fi and
   * can be updated, inspected and reconfigured from the app.
   *
   * This survives a reboot only if the build sets persist.adb.tcp.port -
   * which a userdebug GSI does not by default - so reconnecting after a
   * restart may need the cable once, and the caller is told so rather than
   * left wondering.
   */

  /* `serial` matters more than it looks. Once the tablet is BOTH on the
   * cable and on the network, adb has two transports for one device and
   * answers "more than one device/emulator" to any untargeted command -
   * including this one. Measured on HA1Y7RCV. */
  async wirelessEnable(port = 5555, serial = '') {
    const target = serial ? ['-s', serial] : [];
    const out = await this.run([...target, 'tcpip', String(port)]);
    /* MEASURED: `adb tcpip` RESTARTS the daemon on the device, so the very
     * next shell command lands while it is gone and fails. Reading the
     * address immediately reported "no Wi-Fi address" for a tablet that
     * plainly had one. Wait for it to come back, and retry. */
    const net = require('./terminal-net.cjs');
    let address = null;
    for (let attempt = 0; attempt < 4 && !address; attempt += 1) {
      if (attempt) await new Promise((r) => setTimeout(r, 1500));
      try {
        address = net.parseAddress(
          await this.run([...target, 'shell', 'ip', '-f', 'inet', 'addr', 'show', 'wlan0']));
      } catch (error) { /* the daemon is still restarting; try again */ }
    }
    return {ok: (/restarting in TCP mode|already/i.test(out) || !!address)
        && !/more than one device/i.test(out),
      port, address, output: out, at: this.now(),
      persists: false,
      note: address
        ? 'Connect with adb connect ' + address.address + ':' + port
        : 'The tablet has no Wi-Fi address yet - join a network first.'};
  }

  async wirelessConnect(host, port = 5555) {
    const target = String(host).includes(':') ? String(host) : host + ':' + port;
    const out = await this.run(['connect', target]);
    return {ok: /connected to/i.test(out) && !/failed|refused/i.test(out),
      target, output: String(out).trim(), at: this.now()};
  }

  async wirelessDisconnect(host) {
    return this.run(host ? ['disconnect', String(host)] : ['disconnect']);
  }

  /* Every terminal this machine can see, by mDNS and then, if nothing
   * answered, a bounded sweep of the private subnets it is attached to. */
  async findTerminals(options = {}) {
    const net = require('./terminal-net.cjs');
    return net.discover(Object.assign({runAdb: this.run}, options));
  }

  /* ---- flashing --------------------------------------------------------
   *
   * Primitives only. WHAT to flash and in WHAT ORDER is a plan, and plans
   * live in gsi.cjs where they can be read and tested as data rather than
   * buried in a sequence of awaits.
   */

  async flash(partition, file, extra = []) {
    if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
    return this.runFastboot([...extra, 'flash', partition, file]);
  }

  /* Super is often full of the vendor's own logical partitions. Deleting
   * one makes room for a GSI larger than the system it replaces. */
  async deleteLogicalPartition(name) {
    if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
    return this.runFastboot(['delete-logical-partition', name]);
  }

  async wipeData() {
    if (!this.fastbootAvailable()) throw new Error('No fastboot runner.');
    return this.runFastboot(['-w']);
  }

  /* Walk an ordered plan, stopping at the first step that fails.
   *
   * Each step says WHERE it must run - the bootloader or fastbootd - and
   * this refuses to run it anywhere else rather than letting fastboot fail
   * in a way that looks like a bad image. `onStep` reports progress so a UI
   * can show the plan advancing instead of a frozen button. */
  async runPlan(steps, {onStep, dryRun} = {}) {
    const done = [];
    for (const step of steps || []) {
      const entry = {stage: step.stage, where: step.where || '', ran: false,
        ok: false, output: ''};
      if (onStep) {
        try { onStep(Object.assign({}, entry, {starting: true})); }
        catch (err) { /* a bad listener never stops a flash */ }
      }

      if (step.where && !dryRun) {
        const {state} = await this.bootloader();
        const inFastbootd = state.userspace === true;
        if (step.where === 'fastbootd' && !inFastbootd) {
          entry.output = 'This step needs fastbootd, and the device is in the bootloader.';
          done.push(entry);
          return {ok: false, steps: done, at: this.now()};
        }
        if (step.where === 'bootloader' && inFastbootd) {
          entry.output = 'This step needs the bootloader, and the device is in fastbootd.';
          done.push(entry);
          return {ok: false, steps: done, at: this.now()};
        }
      }

      if (dryRun) {
        entry.ok = true;
        entry.output = 'fastboot ' + (step.args || []).join(' ');
      } else {
        try {
          entry.output = String(await this.runFastboot(step.args || []));
          entry.ran = true;
          /* fastboot prints FAILED while still exiting zero on some builds,
           * so the text is read rather than the exit code trusted. */
          entry.ok = !/FAILED|error:/i.test(entry.output);
          /* And a command can succeed while doing nothing at all. On this
           * MT6768 tablet `fastboot -w` answered "wipe task partition not
           * found: userdata" and finished in 4ms - reported as a clean
           * wipe, having wiped nothing. A step that quietly did not happen
           * is worse than one that failed loudly, so say so. */
          const hollow = entry.output.match(
            /partition not found:?\s*\S*|No such file or directory|Command not supported|did not find/gi);
          if (entry.ok && hollow) {
            entry.notes = ['This step reported success but appears not to have '
              + 'done anything: ' + [...new Set(hollow)].join('; ')];
          }
        } catch (error) {
          entry.ran = true;
          entry.ok = false;
          entry.output = error.message || String(error);
        }
      }

      done.push(entry);
      if (onStep) { try { onStep(entry); } catch (err) { /* ui */ } }
      if (!entry.ok && !step.optional) {
        return {ok: false, steps: done, at: this.now()};
      }
      /* A step that moves the device between modes has to be given time
       * to come back before the next one asks it anything, or the next
       * `where` check reads a device halfway through rebooting. */
      if (step.settle && !dryRun) {
        await new Promise((resolve) => setTimeout(resolve, step.settle));
      }
    }
    return {ok: true, steps: done, at: this.now()};
  }

  async devices() {
    return parseDevices(await this.run(['devices', '-l']));
  }

  /* The whole read-only picture of one tablet. Never throws for a tablet
   * that is simply absent or unauthorized - those are states to report,
   * not exceptions to handle. */
  async identify(serial) {
    const list = await this.devices();
    const picked = serial
      ? list.find((entry) => entry.serial === serial)
      : list[0];

    if (!picked) {
      return { found: false, authorized: false, at: this.now(), devices: list };
    }
    if (!picked.authorized) {
      return {
        found: true, authorized: false, state: picked.state,
        serial: picked.serial, at: this.now(), devices: list
      };
    }

    const target = ['-s', picked.serial];
    let props = {};
    let battery = null;
    try {
      props = parseProps(await this.run(target.concat(['shell', 'getprop'])));
    } catch (err) { /* reported through readiness, not thrown */ }
    try {
      battery = parseBattery(await this.run(target.concat(['shell', 'dumpsys', 'battery'])));
    } catch (err) { /* battery is a warning, never fatal */ }

    return {
      found: true,
      authorized: true,
      state: picked.state,
      serial: picked.serial,
      identity: identityOf(props, picked.serial),
      battery,
      at: this.now(),
      devices: list
    };
  }

  /* What we can honestly keep before a wipe.
   *
   * This is NOT the full-flash image the CYD gets, and the record says so
   * in its own words rather than letting a later reader assume otherwise.
   * Unlocking erases the tablet, and a real restore needs Lenovo's stock
   * firmware, which this cannot produce. */
  async snapshot(serial) {
    const report = await this.identify(serial);
    if (!report.authorized) return { ok: false, report };
    const target = ['-s', report.serial];
    const parts = {};
    for (const [name, args] of [
      ['props', ['shell', 'getprop']],
      ['packages', ['shell', 'pm', 'list', 'packages', '-f']],
      ['features', ['shell', 'pm', 'list', 'features']],
      ['settingsGlobal', ['shell', 'settings', 'list', 'global']]
    ]) {
      try { parts[name] = await this.run(target.concat(args)); }
      catch (err) { parts[name] = ''; }
    }
    return {
      ok: true,
      at: this.now(),
      serial: report.serial,
      identity: report.identity,
      parts,
      completeness: 'partial',
      caveat: 'A record of what this tablet was, not a restorable image. '
        + 'Unlocking the bootloader erases the device; putting it back to '
        + 'stock needs Lenovo firmware for this exact model, which this '
        + 'snapshot does not contain.'
    };
  }
}

module.exports = {
  Terminal, parseDevices, parseProps, parseBattery, parseGetvar,
  lockState, unlockAllowance, identityOf, readiness,
  bootloaderState, unlockReadiness,
  READINESS_BATTERY_FLOOR, PROPS
};
