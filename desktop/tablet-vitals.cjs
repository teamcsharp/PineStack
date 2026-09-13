/* WHAT THE TABLET IS COSTING, AND HOW LONG IT HAS LEFT.
 *
 * "Whenever I'm connected with the tablet show connection information here
 *  and detailed information about the heartbeat and the graphics information
 *  on how it's taxing the system and the tablet and how it's impacting the
 *  battery life, along with showing a numerical overlay of how much battery
 *  life is on the tablet and how much battery life is left."
 *
 * ONE ROUND TRIP, NOT SEVEN. Every adb call over Wi-Fi costs 140-200 ms on
 * this link, measured. Asking seven questions separately would make the
 * panel a second and a half behind and put seven times the load on a tablet
 * whose load average is already 27. So one shell runs the lot and the answer
 * is split on a marker.
 *
 * EVERY FIELD HERE WAS READ OFF THE REAL TABLET BEFORE IT WAS PARSED. That
 * is not a courtesy - guessing the shape of a dumpsys is how the diagnostics
 * button once reported `[object Object]`, a bare uuid and `bank ?`.
 *
 *   dumpsys battery      level 14 / scale 100, status 3, voltage 3604 (mV),
 *                        temperature 351 (tenths of a degree), Charge
 *                        counter 714000 (uAh)
 *   current_now          -1343900, MICROAMPS, negative while discharging
 *   /proc/loadavg        27.60 26.44 25.06 14/2093 3073
 *   /proc/meminfo        MemTotal / MemAvailable, in kB
 *   dumpsys gfxinfo      Total frames rendered, Janky frames: n (p%),
 *                        50th/90th/95th/99th percentile: NNms
 *
 * TIME LEFT IS COMPUTED FROM CHARGE AND DRAW, not from the percentage. The
 * charge counter is in uAh and the current in uA, so their ratio is hours -
 * a real measurement rather than a guess scaled off a battery's nameplate.
 * It is also honest about charging: a tablet on the cable has no "time left"
 * and says so instead of printing a negative number.
 */
'use strict';

const MARK = '---pine---';

/* The one shell. Ordered so the cheap things come first: if the tablet dies
 * partway through the answer, the battery reading is already in hand. */
const ASK = [
  'dumpsys battery',
  'echo ' + MARK,
  'cat /sys/class/power_supply/battery/current_now 2>/dev/null',
  'echo ' + MARK,
  'cat /proc/loadavg',
  'echo ' + MARK,
  'grep -E "MemTotal|MemAvailable" /proc/meminfo',
  'echo ' + MARK,
  'dumpsys gfxinfo com.pinebox.kiosk 2>/dev/null | grep -E '
    + '"Total frames rendered|Janky frames:|percentile|Missed Vsync"'
].join('; ');

/* status, from BatteryManager. 2 is charging, 5 is full; the rest are not. */
const STATUS = { 1: 'unknown', 2: 'charging', 3: 'discharging',
  4: 'not charging', 5: 'full' };

function number(text, fallback) {
  const got = Number(String(text == null ? '' : text).trim());
  return isFinite(got) ? got : (fallback === undefined ? null : fallback);
}

function field(block, name) {
  const found = new RegExp('^\\s*' + name + ':\\s*(.+)$', 'im').exec(block || '');
  return found ? found[1].trim() : '';
}

class Vitals {
  constructor({ adb, serial, run } = {}) {
    this.adb = adb || 'adb';
    this.serial = serial || '';
    this.run = run;
    /* What the tablet was drawing before the mirror opened, so the panel can
     * say what the mirror itself costs rather than only what the tablet
     * costs. Set by `mark()`. */
    this.baseline = null;
    this.last = null;
  }

  target(args) {
    return this.serial ? ['-s', this.serial, ...args] : args;
  }

  /** Remember the present draw as the "before" for the mirror's cost. */
  mark(reading) {
    const at = reading || this.last;
    if (at && at.battery && isFinite(at.battery.drawMa)) {
      /* The charging state rides along, because a draw taken on the cable
       * and one taken off it are not the same measurement - see read(). */
      this.baseline = { drawMa: at.battery.drawMa,
        charging: !!at.battery.charging, at: Date.now() };
    }
  }

  async read() {
    if (typeof this.run !== 'function') {
      return { ok: false, why: 'there is no way to run adb' };
    }
    const began = Date.now();
    let said = '';
    try {
      said = String(await this.run(this.target(['shell', ASK])) || '');
    } catch (error) {
      return { ok: false, why: error.message, rttMs: Date.now() - began };
    }
    /* THE HEARTBEAT IS THIS CALL. A separate ping would measure a different
     * moment and cost another round trip; the sweep itself is the most
     * honest thing to time. */
    const rttMs = Date.now() - began;

    const parts = said.split(MARK);
    const out = {
      ok: true,
      at: Date.now(),
      rttMs,
      connection: this.connection(),
      battery: this.battery(parts[0] || '', parts[1] || ''),
      load: this.load(parts[2] || ''),
      memory: this.memory(parts[3] || ''),
      graphics: this.graphics(parts[4] || '')
    };

    /* WHAT THE MIRROR IS ADDING - but only against a comparable before.
     *
     * current_now flips sign when the cable goes in, and drawMa is its
     * magnitude, so a tablet that started discharging at 850 mA and is now
     * charging at 322 reads as "-528 mA since the mirror opened". That is
     * arithmetic on two different quantities and it appeared on screen
     * looking authoritative. If the charging state has changed since the
     * baseline, there is no honest comparison to make, and the row is
     * dropped rather than filled with a number. */
    if (this.baseline && out.battery && isFinite(out.battery.drawMa)
        && this.baseline.charging === out.battery.charging) {
      out.battery.sinceMirrorMa =
        Math.round((out.battery.drawMa - this.baseline.drawMa) * 10) / 10;
    }
    this.last = out;
    return out;
  }

  connection() {
    /* A serial that looks like host:port came in over the network; anything
     * else is on the cable. That distinction is the difference between
     * "140 ms of Wi-Fi" and "something is wrong". */
    const overNet = /^[\d.]+:\d+$/.test(this.serial) || /_adb-tls-/.test(this.serial);
    return {
      serial: this.serial || '(the only device attached)',
      how: overNet ? 'wi-fi' : 'usb',
      address: overNet ? this.serial.split(':')[0] : ''
    };
  }

  battery(block, currentText) {
    const level = number(field(block, 'level'));
    const scale = number(field(block, 'scale'), 100) || 100;
    const status = number(field(block, 'status'));
    const chargeUah = number(field(block, 'Charge counter'));
    /* MICROAMPS, and negative while discharging on this tablet. Some builds
     * report it positive while discharging, so the sign is not trusted for
     * anything except its own display - the STATUS says which way it is
     * going. */
    const currentUa = number(currentText);
    const drawMa = currentUa == null ? null
      : Math.round(Math.abs(currentUa) / 1000 * 10) / 10;

    const charging = status === 2 || status === 5;
    let hoursLeft = null;
    if (!charging && chargeUah != null && drawMa != null && drawMa > 1) {
      /* uAh over uA is hours. A real measurement, not a percentage scaled
       * against a nameplate capacity. */
      hoursLeft = Math.round((chargeUah / 1000) / drawMa * 100) / 100;
    }

    return {
      percent: level == null ? null : Math.round(level / scale * 100),
      level, scale,
      status: STATUS[status] || 'unknown',
      charging,
      volts: number(field(block, 'voltage')) == null ? null
        : number(field(block, 'voltage')) / 1000,
      /* Tenths of a degree, as dumpsys reports it. */
      tempC: number(field(block, 'temperature')) == null ? null
        : number(field(block, 'temperature')) / 10,
      chargeMah: chargeUah == null ? null : Math.round(chargeUah / 1000),
      drawMa,
      /* Watts, because milliamps alone say nothing without the voltage and
       * this is the number that compares across devices. */
      watts: (drawMa != null && number(field(block, 'voltage')) != null)
        ? Math.round(drawMa * (number(field(block, 'voltage')) / 1000)) / 1000
        : null,
      hoursLeft
    };
  }

  load(text) {
    const bits = String(text || '').trim().split(/\s+/);
    const threads = /(\d+)\/(\d+)/.exec(bits[3] || '');
    return {
      one: number(bits[0]),
      five: number(bits[1]),
      fifteen: number(bits[2]),
      running: threads ? Number(threads[1]) : null,
      threads: threads ? Number(threads[2]) : null
    };
  }

  memory(text) {
    const total = /MemTotal:\s*(\d+)/.exec(text || '');
    const free = /MemAvailable:\s*(\d+)/.exec(text || '');
    return {
      totalMb: total ? Math.round(Number(total[1]) / 1024) : null,
      freeMb: free ? Math.round(Number(free[1]) / 1024) : null
    };
  }

  graphics(text) {
    const pick = (what) => {
      const found = new RegExp(what + ':\\s*(\\d+)\\s*ms', 'i').exec(text || '');
      return found ? Number(found[1]) : null;
    };
    const total = /Total frames rendered:\s*(\d+)/.exec(text || '');
    /* "Janky frames: 9525 (34.45%)" - the legacy line is deliberately NOT
     * matched, because it counts almost everything and reads as a disaster
     * on a perfectly healthy device. */
    const janky = /^\s*Janky frames:\s*(\d+)\s*\(([\d.]+)%\)/im.exec(text || '');
    const missed = /Number Missed Vsync:\s*(\d+)/.exec(text || '');
    return {
      frames: total ? Number(total[1]) : null,
      janky: janky ? Number(janky[1]) : null,
      jankyPercent: janky ? Number(janky[2]) : null,
      p50: pick('50th percentile'),
      p90: pick('90th percentile'),
      p95: pick('95th percentile'),
      p99: pick('99th percentile'),
      gpu90: pick('90th gpu percentile'),
      missedVsync: missed ? Number(missed[1]) : null
    };
  }
}

module.exports = { Vitals };
