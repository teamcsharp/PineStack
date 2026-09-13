/* REACHING THROUGH THE MIRROR AND TOUCHING THE TABLET.
 *
 * "Allow me to enable touch input and click on the tablet to interact with it
 *  through the remote display."
 * "I wanna be able to have gesture support by being able to click and swipe."
 *
 * ONE SHELL, HELD OPEN. Measured on this tablet over Wi-Fi adb, six taps
 * each, first discarded:
 *
 *   a fresh `adb shell input tap` per tap    127 ms mean (105-170)
 *   one held `adb shell`, tap lines written   42 ms mean (40-46)
 *   one held shell, raw sendevent            161 ms mean (158-166)
 *
 * So the shell is kept open. Forty milliseconds is the difference between a
 * remote screen that feels connected and one that feels like a form you are
 * submitting.
 *
 * AND IT IS `input`, NOT `sendevent`, WHICH IS THE SURPRISE. Raw events are
 * supposed to be the fast road, and here they are the slowest: a protocol-B
 * touch is nine sendevent invocations and each one is a process. They would
 * also need the rotation undoing by hand - this panel reports its axes in
 * PORTRAIT (0-799 by 0-1339) while the terminal runs landscape - and getting
 * that mapping subtly wrong is a bug that looks like a calibration problem
 * forever. `input` takes display coordinates and does that itself.
 *
 * COORDINATES ARE THE DISPLAY'S, in the orientation the operator is looking
 * at: 1340 by 800 here. The caller maps from the picture; this maps nothing.
 */
'use strict';

const { spawn } = require('node:child_process');

class TabletInput {
  constructor({ adb, serial } = {}) {
    this.adb = adb || 'adb';
    this.serial = serial || '';
    this.shell = null;
    this.sent = 0;
    this.lastError = '';
    this.opening = false;
  }

  target(args) {
    return this.serial ? ['-s', this.serial, ...args] : args;
  }

  open() {
    if (this.shell || this.opening) return;
    this.opening = true;
    try {
      this.shell = spawn(this.adb, this.target(['shell']), { windowsHide: true });
      this.shell.stdin.on('error', () => { /* a closing pipe is not news */ });
      this.shell.stderr.on('data', (bytes) => {
        const words = String(bytes || '').trim();
        if (words) this.lastError = words.split('\n')[0].slice(0, 200);
      });
      /* The shell dying is normal on an unplugged tablet; the next command
       * opens a new one rather than failing forever. */
      const gone = () => { this.shell = null; };
      this.shell.on('exit', gone);
      this.shell.on('error', (error) => {
        this.lastError = error.message;
        this.shell = null;
      });
      /* stdout is drained and discarded: `input` says nothing useful, and an
       * unread pipe eventually blocks the child. */
      this.shell.stdout.on('data', () => {});
    } catch (error) {
      this.lastError = error.message;
      this.shell = null;
    }
    this.opening = false;
  }

  say(line) {
    this.open();
    if (!this.shell || !this.shell.stdin.writable) {
      return { ok: false, why: this.lastError || 'the tablet shell is not open' };
    }
    try {
      this.shell.stdin.write(line + '\n');
      this.sent += 1;
      return { ok: true };
    } catch (error) {
      this.lastError = error.message;
      this.shell = null;
      return { ok: false, why: error.message };
    }
  }

  /* Whole numbers only: `input` rejects a decimal with a usage message that
   * goes to a stdout nobody is reading, so a fractional coordinate would
   * fail silently and look like a dead spot on the screen. */
  static round(value) {
    return Math.max(0, Math.round(Number(value) || 0));
  }

  tap(x, y) {
    return this.say('input tap ' + TabletInput.round(x) + ' ' + TabletInput.round(y));
  }

  /**
   * A drag, and with it every gesture the operator asked for.
   *
   * `input swipe` with a duration is the whole vocabulary: a short one is a
   * flick, a long one a drag, and the same point twice held for 600 ms is a
   * long press - which is how the sampler's pads are edited, so it matters.
   */
  swipe(x1, y1, x2, y2, ms) {
    const held = Math.max(20, Math.min(4000, Math.round(Number(ms) || 200)));
    return this.say('input swipe '
      + TabletInput.round(x1) + ' ' + TabletInput.round(y1) + ' '
      + TabletInput.round(x2) + ' ' + TabletInput.round(y2) + ' ' + held);
  }

  key(name) {
    /* Named keys only, and from a list - this string reaches a shell. */
    const safe = String(name || '').toUpperCase().replace(/[^A-Z0-9_]/g, '');
    if (!safe) return { ok: false, why: 'no key was named' };
    return this.say('input keyevent ' + safe);
  }

  /**
   * Typed text.
   *
   * `input text` takes %s for a space and chokes on shell metacharacters, so
   * the whole thing is single-quoted and any quote in it is escaped. This
   * string reaches a shell on a machine that runs the station: it is quoted
   * because it must be, not because it is tidy.
   */
  text(words) {
    const said = String(words == null ? '' : words);
    if (!said) return { ok: true };
    const quoted = said.replace(/'/g, "'\\''").replace(/ /g, '%s');
    return this.say("input text '" + quoted + "'");
  }

  how() {
    return { open: !!this.shell, sent: this.sent, why: this.lastError };
  }

  close() {
    if (!this.shell) return;
    try { this.shell.stdin.end(); } catch (error) { /* going anyway */ }
    try { this.shell.kill(); } catch (error) { /* going anyway */ }
    this.shell = null;
  }
}

module.exports = { TabletInput };
