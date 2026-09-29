/* PINESTREAM, THE DESK'S HALF: this window, a few pictures a second, to the
 * station.  [pinestream]
 *
 * The renderer (renderer/pinestream.js) decides WHETHER - it asks the station
 * which screen PineStream shows and says `run` every few seconds while it is
 * this one. This decides nothing: it captures while it is told to, and stops
 *
 *   - when the station answers a frame with keep:false (the operator's switch
 *     went off, or another screen was chosen) - the station is the master;
 *   - when `run` has not come for DEADMAN_MS (the page died or hung: a pusher
 *     nobody is steering must not keep filming);
 *   - after five failed posts in a row (the station is not there).
 *
 * THE PICTURE IS webContents.capturePage(): the window's own composited
 * output, webviews included, no permission and no picker, resized to the
 * width the station asked for and encoded to JPEG here - so the DGX never
 * encodes anything. An unchanged screen sends an empty keep-alive instead of
 * the same bytes again. A minimised or hidden window sends private=1 (there
 * is nothing true to show), and so does a renderer that says the screen is
 * private.
 */
'use strict';

const DEADMAN_MS = 12000;
const FAIL_LIMIT = 5;
const POST_TIMEOUT_MS = 6000;
const LIMITS = { fps: [1, 5, 2], width: [320, 960, 640], quality: [30, 90, 60] };

function clampOpt(v, key) {
  const [lo, hi, dflt] = LIMITS[key];
  const n = Math.round(Number(v));
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : dflt;
}

class PineStreamPush {
  constructor({ getWin, baseUrl, headers, fetchImpl, now } = {}) {
    this.getWin = getWin || (() => null);
    this.baseUrl = baseUrl || (() => 'http://127.0.0.1:8096');
    this.headers = headers || (() => ({}));
    this.fetch = fetchImpl || ((...a) => fetch(...a));
    this.now = now || (() => Date.now());
    this.opts = { fps: 2, width: 640, quality: 60, private: false, why: '' };
    this.running = false;
    this.timer = null;
    this.lastRun = 0;
    this.last = null;          /* the last JPEG sent, to skip an unchanged screen */
    this.sent = 0;
    this.kept = 0;
    this.fails = 0;
    this.why = 'not started';
    this.lastAnswer = null;
    this.lastError = '';
  }

  verb(verb, opts) {
    if (verb === 'run') return this.run(opts);
    if (verb === 'stop') { this.stop((opts && opts.why) || 'the page said stop'); return this.state(); }
    return this.state();
  }

  run(opts) {
    const o = opts || {};
    this.opts = {
      fps: clampOpt(o.fps, 'fps'), width: clampOpt(o.width, 'width'), quality: clampOpt(o.quality, 'quality'),
      private: !!o.private, why: String(o.why || '').slice(0, 120),
    };
    this.lastRun = this.now();
    if (!this.running) {
      this.running = true;
      this.fails = 0;
      this.last = null;
      this.why = 'running';
      this.schedule(0);
    }
    return this.state();
  }

  stop(why) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.running) this.why = String(why || 'stopped');
    this.running = false;
    this.last = null;
  }

  schedule(ms) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.tick().catch(() => {}); }, Math.max(0, ms));
  }

  async picture() {
    const win = this.getWin();
    if (!win || (win.isDestroyed && win.isDestroyed())) return { private: 'the Pine app has no window' };
    if ((win.isMinimized && win.isMinimized()) || (win.isVisible && !win.isVisible())) {
      return { private: 'the Pine app is minimised' };
    }
    const image = await win.webContents.capturePage();
    if (!image || image.isEmpty()) return { private: 'the Pine app would not capture' };
    const size = image.getSize();
    const sized = size.width > this.opts.width
      ? image.resize({ width: this.opts.width, quality: 'good' }) : image;
    return { jpeg: sized.toJPEG(this.opts.quality) };
  }

  async tick() {
    this.timer = null;
    if (!this.running) return;
    if (this.now() - this.lastRun > DEADMAN_MS) { this.stop('the page stopped asking'); return; }
    const t0 = this.now();
    let body = Buffer.alloc(0);
    let query = '?source=pineapp';
    try {
      let why = this.opts.private ? (this.opts.why || 'a private screen') : '';
      if (!why) {
        const got = await this.picture();
        if (got.private) why = got.private;
        else if (this.last && got.jpeg.equals(this.last)) this.kept += 1;   /* unchanged: keep-alive */
        else body = got.jpeg;
      }
      if (why) {
        query += '&private=1&why=' + encodeURIComponent(why);
        this.last = null;
      }
    } catch (err) {
      this.lastError = String((err && err.message) || err);
      query += '&private=1&why=' + encodeURIComponent('the Pine app would not capture');
    }
    let answer = null;
    try {
      const ctl = new AbortController();
      const kill = setTimeout(() => ctl.abort(), POST_TIMEOUT_MS);
      const res = await this.fetch(this.baseUrl().replace(/\/$/, '') + '/api/pinestream/frame' + query, {
        method: 'POST', body, signal: ctl.signal,
        headers: Object.assign({ 'Content-Type': 'image/jpeg', 'X-PineStream-Agent': 'desk' }, this.headers()),
      }).finally(() => clearTimeout(kill));
      answer = await res.json().catch(() => ({}));
      if (!res.ok && res.status !== 400 && res.status !== 413) throw new Error(res.status + ' ' + (answer.detail || answer.say || ''));
      this.fails = 0;
    } catch (err) {
      this.fails += 1;
      this.lastError = String((err && err.message) || err);
      if (this.fails >= FAIL_LIMIT) { this.stop('the station did not answer ' + FAIL_LIMIT + ' times'); return; }
      this.schedule(2000);
      return;
    }
    this.lastAnswer = answer;
    if (!answer || answer.keep === false) { this.stop((answer && answer.say) || 'the station said stop'); return; }
    if (body.length) { this.last = body; this.sent += 1; }
    /* the station is the master of the rate too */
    this.opts.fps = clampOpt(answer.fps || this.opts.fps, 'fps');
    this.opts.width = clampOpt(answer.width || this.opts.width, 'width');
    this.opts.quality = clampOpt(answer.quality || this.opts.quality, 'quality');
    const every = Math.round(1000 / this.opts.fps);
    this.schedule(every - (this.now() - t0));
  }

  state() {
    return {
      ok: true, running: this.running, why: this.why, fps: this.opts.fps, width: this.opts.width,
      quality: this.opts.quality, private: this.opts.private, sent: this.sent, kept: this.kept,
      fails: this.fails, lastError: this.lastError,
    };
  }
}

module.exports = { PineStreamPush, DEADMAN_MS };
