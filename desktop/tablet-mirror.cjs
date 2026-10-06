/* THE TABLET'S SCREEN, LIVE, IN A WINDOW ON THIS DESK.
 *
 * "Add an icon of a tablet that whenever I click it, it allows me to show a
 *  picture in picture window in the Pine Box app that allows me to see the
 *  screen of the tablet itself in real time and be able to dynamically
 *  adjust the scale of the window."
 *
 * WHY MJPEG OVER A LOCAL SOCKET, and not the obvious roads:
 *
 *   not repeated screenshots - `exec-out screencap -p` is most of a second
 *     per frame over Wi-Fi adb. That is a slideshow, and this has to show a
 *     finger landing on a pad.
 *   not the rolling ring - ScreenReplay's packets would have to come out
 *     through the WebView bridge, base64, one round trip per chunk. It is
 *     built for reaching BACKWARDS, and pays for that with latency.
 *   not raw H.264 into WebCodecs - it would work, and it is a decoder,
 *     a packetiser and an SPS/PPS dance to maintain for a preview window.
 *
 *   multipart/x-mixed-replace is consumed by a bare <img> with no
 *     JavaScript at all. The picture then scales with CSS, which is the
 *     "adjust the scale to the size I need" half of the ask, for free.
 *
 * THE STREAM IS RESTARTED, NOT ASSUMED TO BE ETERNAL. `screenrecord` has
 * historically capped itself at three minutes, and the cap has moved between
 * Android versions - so rather than depend on which build this is, the pipe
 * is simply rebuilt whenever it ends. The viewer sees a hitch; it does not
 * see the picture stop.
 *
 * ONE SERVER, BOUND TO LOOPBACK, ON A PORT THE OS PICKS. Nothing here should
 * be reachable from the network: it is a mirror of a screen that may have a
 * bearer key on it.
 */
'use strict';

const http = require('node:http');
const { spawn, execFile } = require('node:child_process');

/* JPEG frame boundaries. The MJPEG that comes out of ffmpeg is just these
 * concatenated, so the split is a scan for the markers rather than anything
 * cleverer. */
const SOI = Buffer.from([0xff, 0xd8]);
const EOI = Buffer.from([0xff, 0xd9]);

const BOUNDARY = 'pineframe';

/* CAPTURE DETAIL, as fractions of the tablet's real screen rather than as
 * pixel counts - the tablet is asked how big it is, so these stay true if
 * the display or the GSI ever reports something different.
 *
 * A quarter is what a small window on the corner of a desk actually needs.
 * A third is the cheap read. A half is the everyday one. Full is every pixel
 * the panel has. Full uses native JPEG images to avoid the vendor AVC
 * encoder's large graphics footprint while the station is running. Balanced caps the
 * longer capture edge at 960 pixels while retaining the complete screen.
 *
 * FULL IS THE CEILING, and it is the tablet's rather than ours: asking
 * capture for more than the panel has makes the TABLET upscale and send
 * larger frames carrying no more detail. */
const SIZES = { quarter: 1 / 4, third: 1 / 3, half: 1 / 2, balanced: 1, full: 1 };
const BALANCED_LONG_EDGE = 960;

/* The bitrate follows the pixels: the same quality per pixel at every size,
 * rather than a fixed budget that looks fine small and smears at full. */
const BITS_PER_PIXEL = 11;

/* [mirror-quality] "Halve the quality and have a slider where I can adjust
 * that." QUALITY is a fraction of BITS_PER_PIXEL, separate from detail:
 * detail is how many pixels, quality is how many bits each one gets.
 *
 * Halved by default because on 2026-10-01 the full-detail mirror at 11.8
 * Mbit, stalled in n_tty_write, held 623 MB in screenrecord plus 947 MB in
 * the tablet's codec HAL - and screenrecord is oom_score_adj -1000, so the
 * low-memory killer took the kiosk four times in seven minutes instead. */
const QUALITY_MIN = 0.1;
const QUALITY_MAX = 1;

function clampQuality(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.round(Math.min(QUALITY_MAX, Math.max(QUALITY_MIN, n)) * 100) / 100;
}

/* The tablet's own, until it has been asked. Only a starting guess - see
 * measure(). */
const ASSUMED = { width: 1340, height: 800 };

const DEFAULTS = { size: 'balanced', fps: 15, quality: 0.5 };
const FIRST_FRAME_TIMEOUT_MS = 12000;
const STALLED_FRAME_TIMEOUT_MS = 5000;
const WATCH_EVERY_MS = 1000;
const ADB_CONNECT_TIMEOUT_MS = 6000;
/* [mirror-drop-still] A quiet pipe is asked about before it is killed. */
const STILL_PROBE_TIMEOUT_MS = 4000;
const STILL_RECHECK_MS = 5000;

/* THE CAMERA'S KNOWN DOOR.
 *
 * Fixed so that anything else on this machine - ComfyUI, OBS, ffmpeg, a
 * browser - can be told where the tablet's camera is and still find it
 * tomorrow. Loopback only: this is a camera in a studio, and a listening
 * socket nobody remembered opening is how that stops being true. */
const KNOWN_CAMERA_PORT = 8791;

class Mirror {
  constructor({ adb, serial, ffmpeg, execFile: runFile, spawn: spawnProcess, encoderLease, encoderOwner, jpegSourceFactory } = {}) {
    this.adb = adb || 'adb';
    this.serial = serial || '';
    this.ffmpeg = ffmpeg || 'ffmpeg';
    this.execFile = runFile || execFile;
    this.spawn = spawnProcess || spawn;
    this.encoderLease = encoderLease || null;
    this.encoderOwner = encoderOwner;
    this.jpegSource = null;
    this.jpegSourceFactory = jpegSourceFactory || (options => new (require('./tablet-jpeg-source.cjs').TabletJpegSource)(options));
    this.orphanChecked = false;
    this.leaseHeld = false;
    this.leaseRequested = false;
    this.acquiringLease = null;
    this.leaseTimer = null;
    this.leaseGeneration = 0;
    this.renewingLease = false;
    this.shape = Object.assign({}, DEFAULTS);
    /* The tablet's real screen, filled in by measure() on the first open. */
    this.real = Object.assign({}, ASSUMED);
    this.measured = false;

    this.server = null;
    this.port = 0;
    this.watchers = new Set();
    this.latest = null;
    this.frames = 0;
    this.startedAt = 0;
    this.lastFrameAt = 0;
    this.lastError = '';
    this.running = false;

    this.record = null;
    this.convert = null;
    this.spare = Buffer.alloc(0);
    this.restarts = 0;
    this.pipeAt = 0;
    this.pipeFrames = 0;
    this.rebuilding = false;
    this.retryTimer = null;
    this.watchdog = null;
    this.failedStarts = 0;
    this.lastRestartReason = '';
    this.connecting = false;
    this.epoch = 0;
    /* [mirror-drop-nolimit] null = not asked yet; see measure(). */
    this.unlimited = null;
    this.still = false;
    this.stillAt = 0;
    this.probing = false;
    this.paused = false;
    this.closing = false;
    this.opening = null;
    this.pausing = null;
    this.stopping = null;
    this.resumeRequested = false;
    this.rebuildGeneration = 0;
  }

  target(args) {
    return this.serial ? ['-s', this.serial, ...args] : args;
  }

  /* ------------------------------------------------------------ the door */

  /**
   * HOW BIG THE TABLET IS RIGHT NOW, asked once.
   *
   * NOT `wm size`. That answers with the NATURAL size - on this tablet
   * 800x1340, which is portrait - and the terminal runs landscape. Asking
   * screenrecord for those numbers gets a portrait crop of a landscape
   * screen, which is how the first version of this produced a picture
   * nobody could read.
   *
   * `dumpsys display` carries the live answer in its viewport line:
   *
   *   DisplayViewport{... orientation=1, logicalFrame=Rect(0, 0 - 1340, 800),
   *                   deviceWidth=1340, deviceHeight=800}
   *
   * which is what is on the glass at this moment, rotation included - and
   * that is what a mirror is for. `wm size` is kept only as a fallback, and
   * a tablet that answers neither keeps the assumed shape rather than
   * failing: a mirror at a slightly wrong aspect beats no mirror.
   */
  async measure(run) {
    /* [mirror-drop-nolimit] screenrecord stops itself after 180 s unless
     * told otherwise, and every stop is a rebuild the viewer sees as a
     * two-and-a-half second drop - measured, every 180 s on the dot. A
     * build that documents --time-limit 0 is asked for exactly that; one
     * that does not keeps the rebuild-on-end below. */
    if (typeof run === 'function' && this.unlimited === null) {
      try {
        const help = String(await run(this.target(['shell', 'screenrecord --help 2>&1'])) || '');
        this.unlimited = /set to 0\s+to remove the time limit/i.test(help);
      } catch (error) { this.unlimited = false; }
    }
    if (this.measured || typeof run !== 'function') return this.real;

    /* The live viewport first. */
    try {
      const said = String(await run(this.target(['shell', 'dumpsys display'])) || '');
      const found = /deviceWidth=(\d{3,5})\s*,\s*deviceHeight=(\d{3,5})/.exec(said);
      if (found) {
        this.real = { width: Number(found[1]), height: Number(found[2]) };
        this.measured = true;
        return this.real;
      }
    } catch (error) {
      this.lastError = 'could not read the tablet display: ' + error.message;
    }

    /* Then the natural size, rotated by hand if the tablet says it is. */
    try {
      const said = String(await run(this.target(['shell', 'wm size'])) || '');
      let got = null;
      for (const line of said.split(/\r?\n/)) {
        const found = /(\d{3,5})\s*x\s*(\d{3,5})/.exec(line);
        if (!found) continue;
        const shape = { width: Number(found[1]), height: Number(found[2]) };
        /* Override beats physical, and is printed second. */
        if (/override/i.test(line) || !got) got = shape;
      }
      if (got && got.width > 0 && got.height > 0) {
        let turned = 0;
        try {
          turned = Number(String(await run(
            this.target(['shell', 'settings get system user_rotation'])) || '0').trim()) || 0;
        } catch (error) { turned = 0; }
        /* Rotations 1 and 3 are the quarter turns, which swap the sides. */
        this.real = (turned === 1 || turned === 3)
          ? { width: got.height, height: got.width } : got;
        this.measured = true;
      }
    } catch (error) {
      this.lastError = 'could not read the tablet screen size: ' + error.message;
    }
    return this.real;
  }

  /* The capture shape for a named size. Even in both directions - the
   * tablet's encoder refuses an odd width and blames nothing in particular
   * when it does. */
  shapeFor(name) {
    // Balanced limits encoder surfaces and wireless traffic on the tablet.
    // It never enlarges a smaller display; touch coordinates still use real.
    const part = name === 'balanced'
      ? Math.min(1, BALANCED_LONG_EDGE / Math.max(this.real.width, this.real.height))
      : SIZES[name] || SIZES.half;
    const width = Math.max(2, (Math.round(this.real.width * part) >> 1) << 1);
    const height = Math.max(2, (Math.round(this.real.height * part) >> 1) << 1);
    const quality = clampQuality(this.shape.quality) || DEFAULTS.quality;
    return { width, height,
      bitrate: Math.max(400000, Math.round(width * height * BITS_PER_PIXEL * quality)) };
  }

  async open(shape) {
    if (this.closing) return { ...this.where(), ok: false, say: 'mirror is closing' };
    if (this.pausing) await this.pausing;
    if (this.closing) return { ...this.where(), ok: false, say: 'mirror is closing' };
    if (this.running) return this.where();
    if (this.paused && this.server) {
      this.resume();
      return this.where();
    }
    if (this.opening) return this.opening;
    const opening = (async () => {
      Object.assign(this.shape, shape || {});
      this.shape.quality = clampQuality(this.shape.quality) || DEFAULTS.quality;
      await this.listen();
      if (this.closing) return { ...this.where(), ok: false, say: 'mirror is closing' };
      this.paused = false;
      this.running = true;
      this.startedAt = Date.now();
      this.pipe();
      this.watchdog = setInterval(() => this.health(), WATCH_EVERY_MS);
      if (this.watchdog.unref) this.watchdog.unref();
      return this.where();
    })();
    this.opening = opening;
    try { return await opening; }
    finally { if (this.opening === opening) this.opening = null; }
  }

  /**
   * Change size without closing the window.
   *
   * The URL does not change, so the <img> keeps its connection and simply
   * starts receiving bigger or smaller pictures - which is what makes
   * switching to full resolution and back feel like a setting rather than
   * like reopening the window.
   */
  retune(size) {
    if (!SIZES[size] || size === this.shape.size) return this.where();
    this.shape.size = size;
    if (this.running) this.rebuild('capture size changed');
    return this.where();
  }

  /* [mirror-quality] The slider. Same road as retune(): the URL stays, the
   * capture is rebuilt at the new bitrate or JPEG quality. */
  requality(value) {
    const quality = clampQuality(value);
    if (quality === null || quality === this.shape.quality) return this.where();
    this.shape.quality = quality;
    if (this.running) this.rebuild('capture quality changed');
    return this.where();
  }

  where() {
    const shape = this.shapeFor(this.shape.size);
    return {
      quality: this.shape.quality,
      bitrate: this.shape.size === 'full' ? 0 : shape.bitrate,
      capture: this.shape.size === 'full' ? 'jpeg' : 'h264',
      captureFps: this.shape.size === 'full' ? 12 : this.shape.fps,
      ok: true,
      url: 'http://127.0.0.1:' + this.port + '/live.mjpg',
      stillUrl: 'http://127.0.0.1:' + this.port + '/frame.jpg',
      size: this.shape.size,
      sizes: Object.keys(SIZES),
      width: shape.width,
      height: shape.height,
      /* The real screen, so the window can hold the tablet's aspect ratio
       * whatever fraction is being captured. */
      real: Object.assign({}, this.real),
      port: this.port
    };
  }

  listen() {
    return new Promise((resolve, reject) => {
      const server = http.createServer((request, response) => this.serve(request, response));
      this.server = server;
      server.on('error', reject);
      server.once('close', () => reject(new Error('mirror closed while opening')));
      /* Keep an opening socket from outliving a window closed while listen()
       * was pending. Each server owns its own callback. */
      server.listen(0, '127.0.0.1', () => {
        if (this.closing || this.server !== server) {
          try { server.close(); } catch (error) { /* already gone */ }
          reject(new Error('mirror closed while opening'));
          return;
        }
        this.port = server.address().port;
        resolve();
      });
    });
  }

  serve(request, response) {
    const path_ = String(request.url || '').split('?')[0];

    if (path_ === '/frame.jpg') {
      if (!this.latest) {
        response.writeHead(503, { 'Content-Type': 'text/plain' });
        return response.end('no frame yet');
      }
      response.writeHead(200, {
        'Content-Type': 'image/jpeg',
        'Content-Length': this.latest.length,
        'Cache-Control': 'no-store'
      });
      return response.end(this.latest);
    }

    if (path_ !== '/live.mjpg') {
      response.writeHead(404, { 'Content-Type': 'text/plain' });
      return response.end('not here');
    }

    response.writeHead(200, {
      'Content-Type': 'multipart/x-mixed-replace; boundary=' + BOUNDARY,
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      'Pragma': 'no-cache',
      'Connection': 'keep-alive'
    });
    try {
      request.socket.setNoDelay(true);
      request.socket.setKeepAlive(true, 1000);
      request.socket.setTimeout(0);
    } catch (error) { /* a local socket may already have closed */ }
    this.watchers.add(response);
    /* The frame already in hand, so a window that opens between frames shows
     * a picture immediately rather than a blank rectangle. */
    if (this.latest) this.push(response, this.latest);
    const drop = () => this.watchers.delete(response);
    request.on('close', drop);
    response.on('close', drop);
    response.on('error', drop);
  }

  push(response, jpeg) {
    try {
      if (response.destroyed || response.writableEnded) {
        this.watchers.delete(response);
        return false;
      }
      /* A local viewer can still decode more slowly than full-resolution
       * JPEGs arrive. Keep at most the response's own bounded socket buffer;
       * the next current frame is better than an ever-growing queue of stale
       * ones and keeps the Electron main process responsive. */
      if (response.writableNeedDrain) return false;
      const head = Buffer.from('--' + BOUNDARY + '\r\nContent-Type: image/jpeg\r\n'
        + 'Content-Length: ' + jpeg.length + '\r\n\r\n');
      return response.write(Buffer.concat([head, jpeg, Buffer.from('\r\n')]));
    } catch (error) {
      this.watchers.delete(response);
      return false;
    }
  }

  /* ----------------------------------------------------------- the pipe */

  /* A wireless ADB transport can disappear while the tablet and its TCP
   * port remain healthy. Spawning `adb -s ... exec-out` does not reconnect
   * it; it exits immediately with "device not found" forever. */
  connect() {
    if (!/^[^\s:]+:\d+$/.test(this.serial)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      this.execFile(this.adb, ['connect', this.serial],
        { timeout: ADB_CONNECT_TIMEOUT_MS, windowsHide: true },
        (error, stdout, stderr) => {
          const answer = (String(stdout || '') + String(stderr || '')).trim();
          if (error || !/\b(?:already )?connected to\b/i.test(answer)
              || /failed|refused|unable|offline|unauthorized/i.test(answer)) {
            reject(new Error(answer || (error && error.message) || 'adb connect failed'));
          } else resolve();
        });
    });
  }

  async pipe() {
    if (!this.running) return;
    const epoch = ++this.epoch;
    this.connecting = true;
    this.pipeAt = 0;
    this.pipeFrames = this.frames;
    try {
      await this.connect();
    } catch (error) {
      if (this.running && epoch === this.epoch) {
        this.connecting = false;
        this.lastError = 'tablet ADB reconnect: ' + error.message;
        this.rebuild(this.lastError);
      }
      return;
    }
    if (!this.running || epoch !== this.epoch) return;
    try {
      if (!this.encoderLease) {
        const { EncoderLease } = require('./tablet-encoder-lease.cjs');
        this.encoderLease = new EncoderLease({ adb: this.adb, serial: this.serial,
          execFile: this.execFile, owner: this.encoderOwner });
      }
      this.leaseRequested = true;
      const acquiring = (async () => {
        let answer = await this.encoderLease.acquire();
        if (!this.orphanChecked) {
          // After a desktop crash, recover only this desktop's persisted owner.
          // A different owner's recorder is never signalled.
          if (answer && answer.ok !== true && answer.held === true
              && answer.owner === this.encoderLease.owner) {
            this.leaseHeld = true;
            await this.stopRemote();
            this.leaseHeld = false;
            answer = await this.encoderLease.acquire();
          }
        }
        if (answer && answer.ok === true) this.orphanChecked = true;
        return answer;
      })();
      this.acquiringLease = acquiring;
      try {
        const confirmed = await acquiring;
        if (!confirmed || confirmed.ok !== true || confirmed.held !== true
            || confirmed.video_running !== false || confirmed.video_released !== true
            || confirmed.owner !== this.encoderLease.owner) {
          throw new Error(confirmed && confirmed.detail || 'the tablet did not confirm exclusive encoder ownership');
        }
        this.leaseHeld = true;
      }
      finally { if (this.acquiringLease === acquiring) this.acquiringLease = null; }
    } catch (error) {
      if (this.running && epoch === this.epoch) {
        this.connecting = false;
        this.lastError = 'tablet encoder protection: ' + error.message;
        this.rebuild(this.lastError);
      }
      return;
    }
    if (!this.running || epoch !== this.epoch || this.closing) return;
    this.watchEncoderLease();
    this.connecting = false;
    this.pipeAt = Date.now();
    this.lastError = '';
    const { width, height, bitrate } = this.shapeFor(this.shape.size);
    const fps = this.shape.fps;

    if (this.shape.size === 'full') {
      // Keep true panel resolution without the vendor AVC encoder's large
      // graphics allocation. Each producer owns a fresh native stream token.
      const source = this.jpegSourceFactory({adb: this.adb, serial: this.serial,
        lease: this.encoderLease, runFile: this.execFile,
        onFrame: jpeg => { if (this.running && epoch === this.epoch) this.acceptFrame(jpeg); },
        onFailure: error => { if (this.running && epoch === this.epoch) this.rebuild('full-detail capture: ' + error.message); }});
      this.jpegSource = source;
      try { await source.start({width, height, quality: this.shape.quality}); }
      catch (error) {
        if (this.running && epoch === this.epoch) this.rebuild('full-detail capture: ' + error.message);
      }
      return;
    }

    /* --time-limit is not passed at all: some builds cap it at 180 and
     * refuse a larger number, and the restart below covers the cap either
     * way. Asking for something a build might reject buys nothing. */
    this.record = this.spawn(this.adb, this.target([
      'exec-out',
      'screenrecord --output-format=h264'
        + ' --size ' + width + 'x' + height
        + ' --bit-rate ' + bitrate
        + (this.unlimited ? ' --time-limit 0' : '')  /* [mirror-drop-limit0] */
        + ' -'
    ]), { windowsHide: true });

    /* screenrecord sends changes, so a quiet screen can provide only a few
     * H.264 pictures. Default analysis and codec frame queues wait for more
     * input and made a healthy still screen hit the first-frame timeout.
     * Bound input analysis bytes/time and both codec thread queues. Four static frames
     * now produce the first JPEG within 200 ms without waiting for motion; sparse
     * and moving fixtures preserve all 47 ordered, byte-identical pictures.
     * Keep ordinary buffering: nobuffer/low_delay previously produced no
     * pictures. The input rate remains explicit because raw H.264 has no
     * usable capture clock. */
    this.convert = this.spawn(this.ffmpeg, [
      '-hide_banner', '-loglevel', 'error',
      '-f', 'h264', '-r', '30', '-probesize', '32768',
      '-analyzeduration', '1', '-threads', '1', '-i', 'pipe:0',
      '-threads', '1', '-r', String(fps),
      '-q:v', '6',
      '-f', 'mjpeg', 'pipe:1'
    ], { windowsHide: true });

    this.record.stdout.pipe(this.convert.stdin);
    this.record.stdout.on('error', () => { /* the pipe closing is normal */ });
    this.convert.stdin.on('error', () => { /* likewise */ });

    this.record.stderr.on('data', (bytes) => { if (epoch === this.epoch) this.grumble(bytes); });
    this.convert.stderr.on('data', (bytes) => { if (epoch === this.epoch) this.grumble(bytes); });

    this.convert.stdout.on('data', (bytes) => { if (epoch === this.epoch) this.chew(bytes); });

    /* Whichever end dies, both are replaced - a half-built pipe produces no
     * pictures and holds a process open. */
    this.record.on('exit', (code, signal) => {
      if (epoch === this.epoch) this.rebuild('tablet encoder ended'
        + (code !== null ? ' (exit ' + code + ')' : signal ? ' (' + signal + ')' : '')
        + (this.lastError ? ': ' + this.lastError : ''));
    });
    this.convert.on('exit', (code, signal) => {
      if (epoch === this.epoch) this.rebuild('desktop decoder ended'
        + (code !== null ? ' (exit ' + code + ')' : signal ? ' (' + signal + ')' : '')
        + (this.lastError ? ': ' + this.lastError : ''));
    });
    this.record.on('error', (error) => {
      if (epoch !== this.epoch) return;
      this.lastError = error.message;
      this.rebuild('tablet encoder error');
    });
    this.convert.on('error', (error) => {
      if (epoch !== this.epoch) return;
      this.lastError = error.message;
      this.rebuild('desktop decoder error');
    });
  }

  watchEncoderLease() {
    if (this.leaseTimer || !this.leaseHeld || this.closing) return;
    this.leaseTimer = setInterval(() => this.renewEncoderLease(), 10000);
    if (this.leaseTimer.unref) this.leaseTimer.unref();
  }

  stopLeaseWatch() {
    this.leaseGeneration += 1;
    clearInterval(this.leaseTimer);
    this.leaseTimer = null;
  }

  async renewEncoderLease() {
    if (!this.leaseHeld || this.renewingLease || !this.running || this.closing) return;
    this.renewingLease = true;
    const generation = this.leaseGeneration;
    try {
      const confirmed = await this.encoderLease.renew();
      if (!confirmed || confirmed.ok !== true) {
        throw new Error(confirmed && confirmed.detail || 'the tablet did not renew exclusive encoder ownership');
      }
    }
    catch (error) {
      if (generation === this.leaseGeneration && this.running && !this.closing) {
        this.rebuild('tablet encoder protection was lost: ' + error.message);
      }
    } finally { this.renewingLease = false; }
  }

  async releaseEncoderLease() {
    this.stopLeaseWatch();
    if (this.acquiringLease) {
      try { await this.acquiringLease; } catch (error) { /* no confirmed hold */ }
    }
    if (!this.encoderLease || !this.leaseRequested) return;
    try {
      const released = await this.encoderLease.release();
      if (!released || released.ok !== true) {
        throw new Error(released && released.detail || 'the tablet is still waiting for encoder shutdown');
      }
    }
    catch (error) { this.lastError = 'tablet encoder release: ' + error.message; }
    finally { this.leaseHeld = false; this.leaseRequested = false; }
  }

  grumble(bytes) {
    const words = String(bytes || '').trim();
    if (!words) return;
    /* screenrecord narrates normal life on stderr; only keep what reads
     * like a real complaint, and only the newest. */
    if (/error|failed|denied|unable|not found|no devices|cannot/i.test(words)) {
      this.lastError = words.split('\n')[0].slice(0, 200);
    }
  }

  /* One MJPEG stream in, whole JPEGs out. */
  chew(bytes) {
    this.spare = this.spare.length ? Buffer.concat([this.spare, bytes]) : bytes;
    for (;;) {
      const from = this.spare.indexOf(SOI);
      if (from < 0) {
        /* Nothing recognisable yet. Do not let the leftovers grow without
         * bound if the stream is not what we think it is. */
        if (this.spare.length > 4 * 1024 * 1024) this.spare = Buffer.alloc(0);
        return;
      }
      const to = this.spare.indexOf(EOI, from + 2);
      if (to < 0) {
        if (from > 0) this.spare = this.spare.subarray(from);
        return;
      }
      const jpeg = this.spare.subarray(from, to + 2);
      this.spare = this.spare.subarray(to + 2);
      this.acceptFrame(jpeg);
    }
  }

  acceptFrame(jpeg) {
    this.latest = Buffer.from(jpeg);
    this.frames += 1;
    this.lastFrameAt = Date.now();
    this.failedStarts = 0;
    this.lastError = '';
    this.still = false;  /* [mirror-drop-moved] */
    this.stillAt = 0;
    for (const watcher of this.watchers) this.push(watcher, this.latest);
  }

  /** A live child process is not proof of a live picture. */
  health(now = Date.now()) {
    if (!this.running || this.rebuilding || !this.pipeAt) return false;
    const madeFrame = this.frames > this.pipeFrames;
    const from = madeFrame ? this.lastFrameAt : this.pipeAt;
    const limit = madeFrame ? STALLED_FRAME_TIMEOUT_MS : FIRST_FRAME_TIMEOUT_MS;
    if (now - from <= limit) return false;
    if (!madeFrame) {
      this.rebuild('no first frame arrived');
      return true;
    }
    /* [mirror-drop-probe] NO NEW FRAME IS NOT A DEAD PIPE. screenrecord
     * encodes changes; a still screen gives it nothing to send, and killing
     * the pipe for that turned a quiet picture into a real drop - and a
     * still screen into a rebuild every seven seconds. Ask the tablet
     * whether the recorder is still running before touching anything. */
    if (this.probing || (this.still && now - this.stillAt < STILL_RECHECK_MS)) return false;
    this.probing = true;
    const epoch = this.epoch;
    this.recorderAlive().then((alive) => {
      if (epoch !== this.epoch) return;
      this.probing = false;
      /* A frame that arrived meanwhile, or a rebuild, settles it. */
      if (!this.running || epoch !== this.epoch || this.lastFrameAt > from) return;
      if (alive) {
        this.still = true;
        this.stillAt = Date.now();
      } else {
        this.rebuild('frame pipe stalled: the tablet recorder is not answering');
      }
    });
    return false;
  }

  /* [mirror-drop-probe] Alive = our local adb child is still running AND the
   * tablet answers, within a few seconds, that screenrecord is running. A
   * transport that cannot answer that is as good as dead. */
  recorderAlive() {
    if (this.jpegSource) return this.jpegSource.alive().catch(() => false);
    return new Promise((resolve) => {
      if (!this.record || this.record.exitCode !== null) return resolve(false);
      try {
        this.execFile(this.adb, this.target(['shell', 'pidof screenrecord']),
          { timeout: STILL_PROBE_TIMEOUT_MS, windowsHide: true },
          (error, stdout) => resolve(!error && /\d/.test(String(stdout || ''))));
      } catch (error) { resolve(false); }
    });
  }

  rebuild(why) {
    if (!this.running || this.rebuilding) return;
    this.rebuilding = true;
    const generation = ++this.rebuildGeneration;
    this.lastRestartReason = String(why || 'stream ended');
    this.lastError = this.lastRestartReason;
    const hadFrames = this.frames > this.pipeFrames;
    this.failedStarts = hadFrames ? 0 : Math.min(4, this.failedStarts + 1);
    this.restarts += 1;
    const delay = hadFrames ? 350 : Math.min(5000, 500 * (2 ** this.failedStarts));
    clearTimeout(this.retryTimer);
    /* Give the tablet's encoder a clean SIGINT shutdown before its replacement
     * starts. The local server and viewers survive this producer restart. */
    this.stopPipe().then(() => {
      if (!this.running || this.closing || !this.rebuilding || generation !== this.rebuildGeneration) return;
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        if (!this.running || this.closing || !this.rebuilding || generation !== this.rebuildGeneration) return;
        this.rebuilding = false;
        this.spare = Buffer.alloc(0);
        this.pipe();
      }, delay);
    });
  }

  async stopPipe() {
    if (this.stopping) return this.stopping;
    this.epoch += 1;
    this.connecting = false;
    this.pipeAt = 0;
    const stopping = (async () => {
      // A late native acquire must finish before cleanup releases its hold.
      if (this.acquiringLease) {
        try { await this.acquiringLease; } catch (error) { /* acquire failed */ }
      }
      try { await this.stopRemote(); }
      catch (error) { this.lastError = 'tablet encoder stop: ' + error.message; }
      finally {
        await new Promise((r) => setTimeout(r, 400));
        this.kill();
      }
    })();
    this.stopping = stopping;
    try { await stopping; }
    finally { if (this.stopping === stopping) this.stopping = null; }
  }

  kill() {
    this.epoch += 1;
    this.probing = false;
    this.still = false;
    this.stillAt = 0;
    this.connecting = false;
    this.pipeAt = 0;
    for (const child of [this.record, this.convert]) {
      if (!child) continue;
      try { child.stdout && child.stdout.removeAllListeners(); } catch (error) { /* gone */ }
      try { child.removeAllListeners('exit'); } catch (error) { /* gone */ }
      try { child.kill(); } catch (error) { /* gone */ }
    }
    this.record = null;
    this.convert = null;
    this.jpegSource?.dispose();
    this.jpegSource = null;
  }

  /* [mirror-pause] THE TABLET'S ENCODER IS NOT SPENT ON A PICTURE NOBODY SEES.
   *
   * 2026-09-30: four tablet reboots, every one a kernel panic in its video
   * encoder (MVA exhausted, devapc BUG) with two H.264 encoders live - the
   * kiosk's replay ring and this mirror's screenrecord, which ran whenever
   * the window existed, minimised or buried behind the panel included. The
   * operator: "have the desk only record the tablet's screen while its
   * mirror window is actually open". pause() ends the tablet's screenrecord
   * with SIGINT - its own clean shutdown, the encoder given back rather
   * than torn down by a broken pipe - and keeps the local server, so the
   * window's <img> picks the picture up again on resume(). */
  async stopRemote() {
    // Always remove this producer's forward, even after a lost lease ACK.
    if (this.jpegSource) { await this.jpegSource.stop(); return; }
    // An acquire that was refused must never stop another owner's recorder.
    if (!this.encoderLease || !this.leaseHeld) return;
    const status = await this.encoderLease.status();
    if (!status || status.ok !== true || status.held !== true
        || status.owner !== this.encoderLease.owner) {
      this.lastError = 'the tablet encoder owner could not be verified before stopping';
      return;
    }
    const stop = 'pkill -INT -f "screenrecord --output-format=h264"; '
      + 'n=0; while pidof screenrecord >/dev/null; do '
      + 'n=$((n+1)); [ "$n" -ge 40 ] && exit 1; sleep 0.1; done; exit 0';
    await new Promise((resolve) => {
      try {
        this.execFile(this.adb, this.target(['shell', stop]),
          { timeout: 6000, windowsHide: true }, (error) => {
            if (error) this.lastError = 'the tablet recorder is still stopping';
            resolve();
          });
      } catch (error) { this.lastError = error.message; resolve(); }
    });
  }

  async pause() {
    this.resumeRequested = false;        // the latest hide wins over a queued restore
    this.rebuildGeneration += 1;
    if (this.pausing) return this.pausing;
    if (!this.running) return this.how();
    this.paused = true;
    this.running = false;
    this.epoch += 1;                      // late connect/data/exit callbacks stand down
    this.connecting = false;
    clearInterval(this.watchdog);
    clearTimeout(this.retryTimer);
    this.watchdog = null;
    this.retryTimer = null;
    this.rebuilding = false;
    this.stopLeaseWatch();
    const pausing = (async () => {
      try {
        await this.stopPipe();
        await this.releaseEncoderLease();
      } finally {
        this.pausing = null;
        if (this.resumeRequested && !this.closing && this.server) {
          this.resumeRequested = false;
          this.resume();
        }
      }
      return this.how();
    })();
    this.pausing = pausing;
    return pausing;
  }

  resume() {
    if (this.closing || !this.paused || this.running) return this.how();
    if (this.pausing) {
      this.resumeRequested = true;        // don't let an old stop kill a new encoder
      return this.how();
    }
    this.resumeRequested = false;
    this.paused = false;
    this.running = true;
    this.startedAt = Date.now();
    this.pipe();
    this.watchdog = setInterval(() => this.health(), WATCH_EVERY_MS);
    if (this.watchdog.unref) this.watchdog.unref();
    return this.how();
  }

  async closeGently() {
    this.closing = true;
    this.resumeRequested = false;
    if (this.pausing) await this.pausing;
    else if (this.running) await this.pause();
    this.close();
  }

  close() {
    this.closing = true;
    this.rebuildGeneration += 1;
    this.resumeRequested = false;
    this.paused = false;
    this.running = false;
    this.stopLeaseWatch();
    clearInterval(this.watchdog);
    clearTimeout(this.retryTimer);
    this.watchdog = null;
    this.retryTimer = null;
    this.rebuilding = false;
    this.kill();
    for (const watcher of this.watchers) {
      try { watcher.end(); } catch (error) { /* gone */ }
    }
    this.watchers.clear();
    if (this.server) {
      try { this.server.close(); } catch (error) { /* gone */ }
      this.server = null;
    }
    this.latest = null;
  }

  /* What it is doing, for the window's own status line. Live numbers, not
   * a claim: "running" is not the same as "there are pictures". */
  how() {
    const still = this.lastFrameAt ? Date.now() - this.lastFrameAt : 0;
    return {
      ...this.where(),
      running: this.running,
      paused: this.paused,
      closing: this.closing,
      encoderProtected: this.leaseHeld,
      frames: this.frames,
      watchers: this.watchers.size,
      restarts: this.restarts,
      rebuilding: this.rebuilding,
      connecting: this.connecting,
      /* [mirror-drop-state] what the window may honestly call a reconnect,
       * and a quiet stream that has been checked and is fine. */
      reconnecting: !!(this.rebuilding || this.connecting),
      still: !!this.still,
      stallMs: STALLED_FRAME_TIMEOUT_MS,
      noTimeLimit: !!this.unlimited,
      restartReason: this.lastRestartReason,
      sinceFrameMs: still,
      size: this.shape.size,
      quality: this.shape.quality,
      bitrate: this.shape.size === 'full' ? 0 : this.shapeFor(this.shape.size).bitrate,
      measured: this.measured,
      real: Object.assign({}, this.real),
      /* The honest reading: a stream that has not produced a frame in two
       * seconds is stalled, whatever the processes say. */
      live: this.frames > 0 && still < 2000,
      why: this.lastError,
      width: this.shapeFor(this.shape.size).width,
      height: this.shapeFor(this.shape.size).height
    };
  }
}

/* ======================================================= the camera =====
 *
 * THE TABLET'S CAMERA, WITHOUT ITS SCREEN.
 *
 * The tablet streams JPEGs on a local socket - see camera/PineCameraService -
 * and this forwards that socket to a port here and re-serves it as the same
 * multipart an <img> understands. Deliberately the same wire format and the
 * same splitter as the screen mirror above: one of those is enough.
 *
 * NOTHING IS ENCODED, SCALED OR CONVERTED ON THIS SIDE. The frames arrive
 * already compressed because an ImageReader can be asked for JPEG directly,
 * so there is no ffmpeg in this path at all - which is why it starts in a
 * fraction of the time the screen mirror does.
 */
class CameraGlass {
  constructor({ adb, serial } = {}) {
    this.adb = adb || 'adb';
    this.serial = serial || '';
    this.server = null;
    this.port = 0;
    this.tap = null;              /* the tcp port adb is forwarding */
    this.pipe = null;             /* the socket to the tablet */
    this.watchers = new Set();
    this.latest = null;
    this.frames = 0;
    this.lastError = '';
    this.running = false;
    this.spare = Buffer.alloc(0);
    this.facing = 'rear';
  }

  target(args) {
    return this.serial ? ['-s', this.serial, ...args] : args;
  }

  run(args, timeoutMs) {
    return new Promise((resolve, reject) => {
      require('node:child_process').execFile(this.adb, args,
        { timeout: timeoutMs || 15000, windowsHide: true },
        (error, stdout, stderr) => {
          const said = String(stdout || '') + String(stderr || '');
          if (error && !said) return reject(error);
          resolve(said);
        });
    });
  }

  async open(facing) {
    this.facing = facing === 'front' ? 'front' : 'rear';
    if (this.running) return this.where();
    await this.listen();
    /* A port of the OS's choosing on this side, so two terminals cannot
     * collide, forwarded to the abstract socket the service opened. */
    const picked = 9230 + Math.floor(Math.random() * 400);
    await this.run(this.target(['forward', 'tcp:' + picked,
      'localabstract:pine_camera']), 20000);
    this.tap = picked;
    this.running = true;
    this.draw();
    return this.where();
  }

  where() {
    const at = 'http://127.0.0.1:' + this.port;
    return { ok: true, facing: this.facing, port: this.port,
      url: at + '/camera.mjpg',
      /* Both said plainly, because the whole point of a fixed port is that
       * these can be copied into something else. */
      stream: at + '/camera.mjpg',
      still: at + '/camera.jpg',
      known: this.port === KNOWN_CAMERA_PORT };
  }

  /**
   * A PORT THAT CAN BE WRITTEN DOWN.
   *
   * The OS picking one is fine for a window that is handed the number; it is
   * no use at all to a ComfyUI workflow that has to name the source. So the
   * known port is tried first and a random one is only the fallback - which
   * means a graph built yesterday still finds the camera today.
   */
  listen() {
    return new Promise((resolve) => {
      this.server = http.createServer((request, response) => this.serve(request, response));
      const anywhere = () => {
        this.server.listen(0, '127.0.0.1', () => {
          this.port = this.server.address().port;
          resolve();
        });
      };
      this.server.once('error', () => {
        /* Something already holds it - another Pine Box, or a leftover.
         * Taking any port beats refusing to show the camera. */
        this.server.removeAllListeners('error');
        this.server.on('error', () => {});
        anywhere();
      });
      this.server.listen(KNOWN_CAMERA_PORT, '127.0.0.1', () => {
        this.port = this.server.address().port;
        resolve();
      });
    });
  }

  serve(request, response) {
    const path_ = String(request.url || '').split('?')[0];

    /* ONE FRAME, for the many things that want a picture rather than a
     * stream - ComfyUI's image loaders among them. Same bytes, no
     * multipart. */
    if (path_ === '/camera.jpg') {
      if (!this.latest) {
        response.writeHead(503, { 'Content-Type': 'text/plain' });
        return response.end('no frame yet');
      }
      response.writeHead(200, {
        'Content-Type': 'image/jpeg',
        'Content-Length': this.latest.length,
        'Cache-Control': 'no-store'
      });
      return response.end(this.latest);
    }

    if (path_ !== '/camera.mjpg') {
      response.writeHead(404, { 'Content-Type': 'text/plain' });
      return response.end('not here');
    }
    response.writeHead(200, {
      'Content-Type': 'multipart/x-mixed-replace; boundary=' + BOUNDARY,
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      'Connection': 'close'
    });
    this.watchers.add(response);
    if (this.latest) this.push(response, this.latest);
    const drop = () => this.watchers.delete(response);
    request.on('close', drop);
    response.on('close', drop);
    response.on('error', drop);
  }

  push(response, jpeg) {
    try {
      if (response.writableNeedDrain || response.writableLength > 128 * 1024) return;
      response.write('--' + BOUNDARY + '\r\n');
      response.write('Content-Type: image/jpeg\r\n');
      response.write('Content-Length: ' + jpeg.length + '\r\n\r\n');
      response.write(jpeg);
      response.write('\r\n');
    } catch (error) {
      this.watchers.delete(response);
    }
  }

  /* Connect to the forwarded port and read frames until it ends. The tablet
   * only opens its camera while somebody is connected, so this connection IS
   * the thing that turns the lens on. */
  draw() {
    if (!this.running) return;
    const net = require('node:net');
    const pipe = net.connect(this.tap, '127.0.0.1');
    this.pipe = pipe;
    pipe.on('data', (bytes) => this.chew(bytes));
    pipe.on('error', (error) => {
      this.lastError = error.message;
      this.again();
    });
    pipe.on('close', () => this.again());
  }

  again() {
    if (!this.running || this.mending) return;
    this.mending = true;
    this.spare = Buffer.alloc(0);
    setTimeout(() => {
      this.mending = false;
      if (this.running) this.draw();
    }, 800);
  }

  /* BY LENGTH, NOT BY MARKERS - and the mirror's splitter above is exactly
   * what cannot be used here.
   *
   * An ImageReader's JPEG carries EXIF, and Android's EXIF routinely embeds
   * a THUMBNAIL, which is itself a JPEG: there is a second ff d8 ... ff d9
   * pair inside the header of the first. Scanning for markers stops at the
   * thumbnail's end and yields a truncated frame that ends in a correct ff d9
   * and will not decode. Measured: 12,658 bytes, valid tail, refused by the
   * decoder, every single frame.
   *
   * So the tablet sends four bytes of big-endian length first and this never
   * has to guess. */
  chew(bytes) {
    this.spare = this.spare.length ? Buffer.concat([this.spare, bytes]) : bytes;
    for (;;) {
      if (this.spare.length < 4) return;
      const size = this.spare.readUInt32BE(0);
      /* A length that could not be a frame means the stream is out of step;
       * dropping what is held is the only way back that does not loop. */
      if (size <= 0 || size > 16 * 1024 * 1024) {
        this.lastError = 'the camera stream lost its place';
        this.spare = Buffer.alloc(0);
        return;
      }
      if (this.spare.length < 4 + size) return;
      this.latest = Buffer.from(this.spare.subarray(4, 4 + size));
      this.spare = this.spare.subarray(4 + size);
      this.frames += 1;
      this.lastFrameAt = Date.now();
      for (const watcher of this.watchers) this.push(watcher, this.latest);
    }
  }

  how() {
    const still = this.lastFrameAt ? Date.now() - this.lastFrameAt : 0;
    return { running: this.running, facing: this.facing, frames: this.frames,
      watchers: this.watchers.size, sinceFrameMs: still,
      live: this.frames > 0 && still < 2500, why: this.lastError };
  }

  async close() {
    this.running = false;
    try { this.pipe && this.pipe.destroy(); } catch (error) { /* gone */ }
    this.pipe = null;
    for (const watcher of this.watchers) {
      try { watcher.end(); } catch (error) { /* gone */ }
    }
    this.watchers.clear();
    if (this.server) {
      try { this.server.close(); } catch (error) { /* gone */ }
      this.server = null;
    }
    if (this.tap) {
      try { await this.run(this.target(['forward', '--remove', 'tcp:' + this.tap]), 10000); }
      catch (error) { /* the forward outlives us at worst */ }
      this.tap = 0;
    }
    this.latest = null;
  }
}

module.exports = { Mirror, DEFAULTS, SIZES, CameraGlass };
