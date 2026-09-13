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
const { spawn } = require('node:child_process');

/* JPEG frame boundaries. The MJPEG that comes out of ffmpeg is just these
 * concatenated, so the split is a scan for the markers rather than anything
 * cleverer. */
const SOI = Buffer.from([0xff, 0xd8]);
const EOI = Buffer.from([0xff, 0xd9]);

const BOUNDARY = 'pineframe';

/* THE THREE SIZES, as fractions of the tablet's real screen rather than as
 * pixel counts - the tablet is asked how big it is, so these stay true if
 * the display or the GSI ever reports something different.
 *
 * A quarter is what a small window on the corner of a desk actually needs.
 * A third is the cheap read. A half is the everyday one. Full is every pixel
 * the panel has and four times the encoder work of a half, on a tablet that
 * is also running the station and the rolling recorder - so it is reached by
 * asking for it, or by zooming in far enough to need it.
 *
 * FULL IS THE CEILING, and it is the tablet's rather than ours: asking
 * screenrecord for more than the panel has makes the TABLET upscale and send
 * larger frames carrying no more detail. */
const SIZES = { quarter: 1 / 4, third: 1 / 3, half: 1 / 2, full: 1 };

/* The bitrate follows the pixels: the same quality per pixel at every size,
 * rather than a fixed budget that looks fine small and smears at full. */
const BITS_PER_PIXEL = 11;

/* The tablet's own, until it has been asked. Only a starting guess - see
 * measure(). */
const ASSUMED = { width: 1340, height: 800 };

const DEFAULTS = { size: 'half', fps: 15 };

class Mirror {
  constructor({ adb, serial, ffmpeg } = {}) {
    this.adb = adb || 'adb';
    this.serial = serial || '';
    this.ffmpeg = ffmpeg || 'ffmpeg';
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
    const part = SIZES[name] || SIZES.half;
    const width = Math.max(2, (Math.round(this.real.width * part) >> 1) << 1);
    const height = Math.max(2, (Math.round(this.real.height * part) >> 1) << 1);
    return { width, height,
      bitrate: Math.max(800000, Math.round(width * height * BITS_PER_PIXEL)) };
  }

  async open(shape) {
    if (this.running) return this.where();
    Object.assign(this.shape, shape || {});
    await this.listen();
    this.running = true;
    this.startedAt = Date.now();
    this.pipe();
    return this.where();
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
    if (this.running) this.rebuild();
    return this.where();
  }

  where() {
    const shape = this.shapeFor(this.shape.size);
    return {
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
      this.server = http.createServer((request, response) => this.serve(request, response));
      this.server.on('error', reject);
      /* Port 0: the OS picks a free one, and 127.0.0.1 so nothing off this
       * machine can watch the tablet's screen. */
      this.server.listen(0, '127.0.0.1', () => {
        this.port = this.server.address().port;
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
      'Connection': 'close'
    });
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
      response.write('--' + BOUNDARY + '\r\n');
      response.write('Content-Type: image/jpeg\r\n');
      response.write('Content-Length: ' + jpeg.length + '\r\n\r\n');
      response.write(jpeg);
      response.write('\r\n');
    } catch (error) {
      this.watchers.delete(response);
    }
  }

  /* ----------------------------------------------------------- the pipe */

  pipe() {
    if (!this.running) return;
    const { width, height, bitrate } = this.shapeFor(this.shape.size);
    const fps = this.shape.fps;

    /* --time-limit is not passed at all: some builds cap it at 180 and
     * refuse a larger number, and the restart below covers the cap either
     * way. Asking for something a build might reject buys nothing. */
    this.record = spawn(this.adb, this.target([
      'exec-out',
      'screenrecord --output-format=h264'
        + ' --size ' + width + 'x' + height
        + ' --bit-rate ' + bitrate
        + ' -'
    ]), { windowsHide: true });

    /* THESE ARGUMENTS ARE THE MEASURED ONES. DO NOT TIDY THEM.
     *
     * The usual live-stream incantation - `-probesize 32 -analyzeduration 0
     * -fflags nobuffer -flags low_delay` - produces ZERO frames against raw
     * H.264 from screenrecord, and fails silently: bytes pour in, one
     * warning is printed, and no picture ever comes out. Each half is fatal
     * on its own; removing only the probesize still gave nothing.
     *
     * Measured, nine seconds each:
     *   plain      183 frames, first at 2.86 s
     *   -r 30/-r15  86 frames, first at 2.40 s   <- this
     *   "low delay"  0 frames, never
     *   -vf fps=15 111 frames, first at 2.39 s
     *
     * Telling it the input rate is what fixes it: ffmpeg stops trying to
     * estimate a rate the raw stream does not carry. Anything added here
     * needs measuring again, because the failure is invisible. */
    this.convert = spawn(this.ffmpeg, [
      '-hide_banner', '-loglevel', 'error',
      '-f', 'h264', '-r', '30', '-i', 'pipe:0',
      '-r', String(fps),
      '-q:v', '6',
      '-f', 'mjpeg', 'pipe:1'
    ], { windowsHide: true });

    this.record.stdout.pipe(this.convert.stdin);
    this.record.stdout.on('error', () => { /* the pipe closing is normal */ });
    this.convert.stdin.on('error', () => { /* likewise */ });

    this.record.stderr.on('data', (bytes) => this.grumble(bytes));
    this.convert.stderr.on('data', (bytes) => this.grumble(bytes));

    this.convert.stdout.on('data', (bytes) => this.chew(bytes));

    /* Whichever end dies, both are replaced - a half-built pipe produces no
     * pictures and holds a process open. */
    const again = () => this.rebuild();
    this.record.on('exit', again);
    this.convert.on('exit', again);
    this.record.on('error', (error) => { this.lastError = error.message; again(); });
    this.convert.on('error', (error) => { this.lastError = error.message; again(); });
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
      this.latest = Buffer.from(jpeg);
      this.frames += 1;
      this.lastFrameAt = Date.now();
      for (const watcher of this.watchers) this.push(watcher, this.latest);
    }
  }

  rebuild() {
    if (!this.running || this.rebuilding) return;
    this.rebuilding = true;
    this.kill();
    this.restarts += 1;
    /* A breath before trying again: an unplugged tablet would otherwise
     * spawn adb in a tight loop for as long as the window stays open. */
    setTimeout(() => {
      this.rebuilding = false;
      this.spare = Buffer.alloc(0);
      this.pipe();
    }, 700);
  }

  kill() {
    for (const child of [this.record, this.convert]) {
      if (!child) continue;
      try { child.stdout && child.stdout.removeAllListeners(); } catch (error) { /* gone */ }
      try { child.removeAllListeners('exit'); } catch (error) { /* gone */ }
      try { child.kill(); } catch (error) { /* gone */ }
    }
    this.record = null;
    this.convert = null;
  }

  close() {
    this.running = false;
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
      running: this.running,
      frames: this.frames,
      watchers: this.watchers.size,
      restarts: this.restarts,
      sinceFrameMs: still,
      size: this.shape.size,
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
    return { ok: true, facing: this.facing,
      url: 'http://127.0.0.1:' + this.port + '/camera.mjpg', port: this.port };
  }

  listen() {
    return new Promise((resolve, reject) => {
      this.server = http.createServer((request, response) => this.serve(request, response));
      this.server.on('error', reject);
      this.server.listen(0, '127.0.0.1', () => {
        this.port = this.server.address().port;
        resolve();
      });
    });
  }

  serve(request, response) {
    if (!String(request.url || '').startsWith('/camera.mjpg')) {
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
