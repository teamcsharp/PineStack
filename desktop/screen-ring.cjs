'use strict';
/* THE ROLLING RECORD OF THIS WINDOW (2026-09-15, #1182).
 *
 * The operator: "Make sure that the Pine Box app also supports the ability
 * to record and export screen recordings of the application that are being
 * cached in real time as the application is running." And then, about the
 * app as a whole: "Basically the Pine Box app needs the same feature set as
 * what we have going on with the Pine Box tab. So it needs feature parity,
 * so there's nothing left out."
 *
 * He had the export sheet open when he said it, and the sheet was telling
 * him the truth: "the ring cannot be read on this surface (no replayState)"
 * and "no screen recording road on this surface". The renderer has had the
 * whole hot-corner export flow for a week; only the tablet had anything
 * behind it. The note this file closes was already written, at glass:clip
 * in main.js:
 *
 *     "Only the tablet has a rolling recorder; this window does not, so a
 *      local capture still films forwards."
 *
 * Which is why "save the last minute" on the desk could only ever mean
 * "wait a minute". It reaches backwards now.
 *
 * WHAT IS CACHED, AND WHY IT IS SHAPED LIKE THIS.
 *
 * The renderer records the window with MediaRecorder and hands finished
 * pieces down here; this module keeps them on DISK, oldest thrown away, and
 * cuts what is asked for out of the pieces that survive.
 *
 * The pieces are SELF-CONTAINED files - the recorder is stopped and started
 * again every SEGMENT_MS - rather than one long recording chopped into
 * timeslices. That costs a few milliseconds at each seam and buys the only
 * property that matters here: every file on disk is a file. A WebM
 * timeslice that is not the first carries no EBML header, so a ring made of
 * them is a ring of bytes that no decoder will open, and the failure only
 * shows up when somebody finally asks for a cut - which is the worst moment
 * to discover it.
 *
 * Disk rather than memory because the ask goes to twenty minutes. At the
 * bitrate the renderer asks for, twenty minutes is on the order of two
 * hundred megabytes; that is nothing on a disk and is not a thing to hold
 * in an Electron main process. HOLD_MAX_BYTES bounds it a second way, so a
 * screen that suddenly encodes badly cannot fill the drive while the
 * seconds count still looks reasonable.
 *
 * THE ERA. The concat demuxer refuses pieces whose codec parameters
 * disagree, and the window is resizable, so a ring that spans a resize
 * cannot be concatenated. Each piece records the size it was made at, and
 * pieces of the current size are an "era": a cut uses the newest era and
 * says so when it had to stop early. The renderer asks for a fixed capture
 * size to make this rare, not impossible.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const clipMux = require('./clip-mux.cjs');

/* THE OPERATOR'S OWN NUMBERS (#1182): "I want the rolling replay to be at
 * default 30 seconds with a max able to be set to up to five or ten minutes
 * and a minimum set to five seconds." Ten minutes is taken as the ceiling,
 * being the generous end of what he said.
 *
 * A piece must be shorter than the SHORTEST hold or the ring cannot hold a
 * whole one: at a five-second hold, two-second pieces leave three in hand
 * and a cut that can actually land inside the window. Ten minutes of them
 * is three hundred files, which is nothing for a directory and is the price
 * of every piece being a file a decoder will open. */
const SEGMENT_MS = 2000;
const HOLD_DEFAULT_S = 30;
const HOLD_MIN_S = 5;
const HOLD_MAX_S = 600;           /* ten minutes */
const HOLD_MAX_BYTES = 900 * 1024 * 1024;

function nowMs() { return Date.now(); }

class ScreenRing {
  constructor() {
    this.dir = null;
    this.pieces = [];             /* {file, at, ms, bytes, w, h} oldest first */
    this.holdSeconds = HOLD_DEFAULT_S;
    this.running = false;
    this.detail = 'not started';
    this.startedAt = 0;
    this.dropped = 0;             /* pieces aged out, for the record */
    /* #1182d: bumped on every piece that lands, so a cut can wait for the
     * one it just asked for rather than sleeping a guessed interval. */
    this.taken = 0;
    this.lastError = '';
  }

  /* --------------------------------------------------------------- disk */

  ensureDir() {
    if (this.dir && fs.existsSync(this.dir)) return this.dir;
    this.dir = path.join(os.tmpdir(), 'pinebox-screen-ring-' + process.pid);
    fs.mkdirSync(this.dir, { recursive: true });
    return this.dir;
  }

  /* A ring left behind by a process that died. Nothing else cleans these
   * up, and a crashed session must not cost the disk a quarter gigabyte
   * until the machine is rebooted. */
  sweepOld() {
    let swept = 0;
    try {
      const tmp = os.tmpdir();
      for (const name of fs.readdirSync(tmp)) {
        if (!/^pinebox-screen-ring-(\d+)$/.test(name)) continue;
        const pid = Number(RegExp.$1);
        if (pid === process.pid) continue;
        let alive = false;
        try { process.kill(pid, 0); alive = true; } catch (e) { alive = false; }
        if (alive) continue;
        try { fs.rmSync(path.join(tmp, name), { recursive: true, force: true }); swept += 1; }
        catch (e) { /* someone else's, or in use */ }
      }
    } catch (e) { /* a tmpdir that cannot be listed is not fatal */ }
    return swept;
  }

  /* --------------------------------------------------------------- feed */

  begin(opts) {
    const want = Number((opts || {}).holdSeconds || 0);
    if (want > 0) this.setHold(want);
    this.ensureDir();
    this.sweepOld();
    this.running = true;
    this.startedAt = this.startedAt || nowMs();
    this.detail = 'recording';
    return this.state();
  }

  stop(why) {
    this.running = false;
    this.detail = String(why || 'stopped');
    return this.state();
  }

  setHold(seconds) {
    const n = Math.round(Number(seconds) || 0);
    this.holdSeconds = Math.max(HOLD_MIN_S, Math.min(HOLD_MAX_S, n || HOLD_DEFAULT_S));
    this.prune();
    return this.holdSeconds;
  }

  /* One finished piece from the renderer. `at` is when the piece STARTED,
   * in epoch ms, taken in the renderer rather than here: the trip through
   * IPC is short but it is not zero, and every cut is arithmetic on these
   * timestamps. */
  take(buffer, meta) {
    if (!buffer || !buffer.length) return { ok: false, why: 'empty piece' };
    const m = meta || {};
    const ms = Math.max(1, Math.round(Number(m.ms) || SEGMENT_MS));
    const at = Math.round(Number(m.at) || (nowMs() - ms));
    this.ensureDir();
    const file = path.join(this.dir, 'p' + String(at) + '.webm');
    try {
      fs.writeFileSync(file, Buffer.from(buffer));
    } catch (error) {
      this.lastError = error.message;
      return { ok: false, why: error.message };
    }
    this.taken += 1;
    this.pieces.push({ file, at, ms, bytes: buffer.length,
      w: Math.round(Number(m.w) || 0), h: Math.round(Number(m.h) || 0) });
    this.pieces.sort((a, b) => a.at - b.at);
    this.running = true;
    this.detail = 'recording';
    this.startedAt = this.startedAt || at;
    this.prune();
    return { ok: true, held: this.heldSeconds(), pieces: this.pieces.length };
  }

  /* Old pieces go, by time first and by weight second. */
  prune() {
    const keepFrom = nowMs() - (this.holdSeconds * 1000);
    while (this.pieces.length > 1) {
      const first = this.pieces[0];
      if (first.at + first.ms >= keepFrom) break;
      this.drop(first);
    }
    while (this.pieces.length > 1 && this.bytes() > HOLD_MAX_BYTES) {
      this.drop(this.pieces[0]);
    }
  }

  drop(piece) {
    this.pieces.shift();
    this.dropped += 1;
    try { fs.unlinkSync(piece.file); } catch (e) { /* already gone */ }
  }

  forget() {
    this.running = false;
    for (const p of this.pieces) { try { fs.unlinkSync(p.file); } catch (e) {} }
    this.pieces = [];
    if (this.dir) { try { fs.rmSync(this.dir, { recursive: true, force: true }); } catch (e) {} }
    this.dir = null;
  }

  /* -------------------------------------------------------------- reads */

  bytes() {
    let n = 0;
    for (const p of this.pieces) n += p.bytes;
    return n;
  }

  heldSeconds() {
    if (!this.pieces.length) return 0;
    const first = this.pieces[0];
    const last = this.pieces[this.pieces.length - 1];
    return Math.max(0, ((last.at + last.ms) - first.at) / 1000);
  }

  /* The size the newest pieces are being made at. */
  era() {
    if (!this.pieces.length) return { w: 0, h: 0 };
    const last = this.pieces[this.pieces.length - 1];
    return { w: last.w, h: last.h };
  }

  /* The shape hot-corners.js reads: {ok, running, seconds, holds, bytes,
   * detail}. `seconds` is what is HELD - less than `holds` for the first
   * minutes and after the recorder has been interrupted - which is exactly
   * what the tablet's own replayState means by it. */
  state() {
    const held = this.heldSeconds();
    let detail = this.detail;
    if (this.running && held < this.holdSeconds) {
      detail = 'recording - holding ' + held.toFixed(0) + 's of '
        + this.holdSeconds + 's';
    } else if (this.running) {
      detail = 'recording - the ring is full';
    }
    if (this.lastError) detail += ' (last trouble: ' + this.lastError + ')';
    return { ok: true, running: !!this.running, seconds: Math.round(held * 10) / 10,
      holds: this.holdSeconds, bytes: this.bytes(), pieces: this.pieces.length,
      dropped: this.dropped, era: this.era(), where: this.dir || '',
      detail };
  }

  /* The pieces covering `seconds` of video ending `back` seconds ago, newest
   * era only. Returns what it could actually reach, never a promise it
   * cannot keep. */
  window(seconds, back) {
    const want = Math.max(0.2, Number(seconds) || 0);
    const behind = Math.max(0, Number(back) || 0);
    const held = this.heldSeconds();
    if (!this.pieces.length) {
      return { ok: false, held: 0, detail: 'the ring is empty' };
    }
    const end = nowMs() - (behind * 1000);
    const start = end - (want * 1000);
    const era = this.era();
    const used = [];
    let clamped = false;
    for (const p of this.pieces) {
      if (p.at + p.ms <= start) continue;
      if (p.at >= end) continue;
      if (era.w && p.w && (p.w !== era.w || p.h !== era.h)) { clamped = true; continue; }
      used.push(p);
    }
    if (!used.length) {
      return { ok: false, held, clamped,
        detail: 'nothing in the ring covers that window' };
    }
    const first = used[0];
    const last = used[used.length - 1];
    if (first.at > start + 250) clamped = true;
    /* Where the cut really lands, said the way the tablet says it: seconds
     * before now, oldest edge and newest edge. */
    const from = (nowMs() - first.at) / 1000;
    const to = Math.max(0, (nowMs() - (last.at + last.ms)) / 1000);
    /* How far into the first piece the wanted window begins. */
    const offset = Math.max(0, (start - first.at) / 1000);
    return { ok: true, pieces: used, held, clamped,
      from: Math.round(from * 10) / 10, to: Math.round(to * 10) / 10,
      offset, seconds: Math.min(want, ((last.at + last.ms) - Math.max(start, first.at)) / 1000),
      w: era.w, h: era.h };
  }

  /* --------------------------------------------------------------- cuts */

  listFile(dir, pieces) {
    const lines = pieces.map(
      (p) => "file '" + p.file.replace(/\\/g, '/').replace(/'/g, "'\\''") + "'");
    const list = path.join(dir, 'pieces.txt');
    fs.writeFileSync(list, lines.join('\n') + '\n', 'utf8');
    return list;
  }

  /* An mp4 of the window, written to `out`. Output-side -ss and -t, which
   * is the accurate seek - input-side seeking on a concat of WebM lands on
   * the nearest keyframe and a "last ten seconds" that is really the last
   * fourteen is not a cut, it is a guess. */
  async cut(want, options) {
    const opts = options || {};
    const got = this.window(want.seconds, want.back);
    if (!got.ok) return { ok: false, detail: got.detail, held: got.held };
    const dir = clipMux.stash();
    try {
      const list = this.listFile(dir, got.pieces);
      const out = want.out || path.join(dir, 'screen.mp4');
      const args = ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', list,
        '-ss', got.offset.toFixed(3), '-t', got.seconds.toFixed(3),
        '-an',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-pix_fmt', 'yuv420p', '-r', '25',
        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
        '-movflags', '+faststart', out];
      await clipMux.run(clipMux.findFfmpeg(opts.ffmpeg).path, args, 300000);
      const bytes = fs.statSync(out).size;
      return { ok: true, out, bytes, seconds: Math.round(got.seconds * 10) / 10,
        asked: Number(want.seconds) || 0, held: got.held, clamped: got.clamped,
        from: got.from, to: got.to, dir,
        w: got.w, h: got.h };
    } catch (error) {
      clipMux.forget(dir);
      return { ok: false, detail: error.message, held: got.held };
    }
  }

  /* Evenly spaced JPEGs out of the window, oldest first, for the scrub
   * strip. The mp4 behind them is temporary and is deleted before this
   * returns; nothing reaches the recordings folder. */
  async frames(want, options) {
    const opts = options || {};
    const seconds = Math.max(1, Math.min(30, Number(want.seconds) || 5));
    const count = Math.max(2, Math.min(24, Math.round(Number(want.count) || 10)));
    const edge = Math.max(120, Math.min(1280, Math.round(Number(want.edge) || 320)));
    const back = Math.max(0, Number(want.back) || 0);
    const got = this.window(seconds, back);
    if (!got.ok) return { ok: false, held: got.held, detail: got.detail };
    const dir = clipMux.stash();
    try {
      const list = this.listFile(dir, got.pieces);
      const span = Math.max(0.2, got.seconds);
      /* fps chosen so `count` frames land across the window. The half-frame
       * offset puts the first sample inside the window rather than exactly
       * on its opening edge, where a concat seam can leave a black field. */
      const fps = count / span;
      const args = ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', list,
        '-ss', (got.offset + (0.5 / Math.max(fps, 0.01))).toFixed(3),
        '-t', span.toFixed(3),
        '-vf', 'fps=' + fps.toFixed(5) + ',scale=' + edge + ':-2:flags=bicubic',
        '-frames:v', String(count), '-q:v', '4',
        path.join(dir, 'f%03d.jpg')];
      await clipMux.run(clipMux.findFfmpeg(opts.ffmpeg).path, args, 120000);
      const names = fs.readdirSync(dir).filter((n) => /^f\d+\.jpg$/.test(n)).sort();
      const frames = [];
      let bytes = 0;
      for (let i = 0; i < names.length; i += 1) {
        const b64 = fs.readFileSync(path.join(dir, names[i])).toString('base64');
        bytes += b64.length;
        /* `at` is how many seconds before NOW this frame sits, one decimal,
         * so the newest frame of a tail window is 0.0 and the strip can
         * label it "now" - the same meaning the tablet gives it. */
        const ago = got.to + ((names.length - 1 - i) * (span / Math.max(1, names.length - 1)));
        frames.push({ at: Math.round(ago * 10) / 10,
          image: 'data:image/jpeg;base64,' + b64 });
      }
      if (!frames.length) {
        return { ok: false, held: got.held, detail: 'the encoder produced no frames' };
      }
      return { ok: true, seconds: Math.round(span * 10) / 10, held: Math.round(got.held * 10) / 10,
        from: got.from, to: got.to, asked_back: back, clamped: got.clamped,
        frames, bytes, edge, detail: '' };
    } catch (error) {
      return { ok: false, held: got.held, detail: error.message };
    } finally {
      clipMux.forget(dir);
    }
  }
}

module.exports = { ScreenRing, SEGMENT_MS, HOLD_DEFAULT_S, HOLD_MIN_S, HOLD_MAX_S,
  HOLD_MAX_BYTES };
