/* PINELIVE - THE FALLING AUDIOGRAPH AND THE METER.
 *
 * "I want to be able to go in and see a falling audiograph of the current
 *  audio."
 *
 * The station's host supervisor computes one frame ~20 times a second while
 * MX Live is armed or a test is running (CONTRACT.md section 6):
 *
 *   {t, rms, peak, clip, l, r, duck, bands}
 *
 * `bands` is 48 log-spaced bands from 30 Hz to 16 kHz, one byte each,
 * dBFS + 100 clamped to 0..100, base64. This file draws them and nothing
 * else - it makes no request and owns no timer of its own. pinelive.js
 * hands it frames and tells it when it may draw at all.
 *
 * WHY IT IS CHEAP ENOUGH FOR THE TABLET. The tablet was measured at 148 MB
 * free under a load average of 25, so:
 *   - the waterfall is a SMALL canvas (BANDS x 8 columns, ROWS rows) that
 *     CSS stretches to the width of the popup. 48 bands of data do not
 *     need 1400 device pixels; the compositor scales it for nothing.
 *   - a new frame shifts the picture down one row with a single
 *     drawImage of the canvas onto itself and writes ONE row of pixels.
 *   - nothing is drawn unless a frame arrived: frames are coalesced into
 *     one requestAnimationFrame, and with no frames the file costs zero.
 *   - no DOM is touched per frame. The number readout under the meter is
 *     written at most four times a second, into fixed-width cells.
 *   - pause() stops everything; pinelive.js calls it the moment the popup
 *     closes, the panel folds or the canvas scrolls out of sight.
 */
(function (root) {
  'use strict';

  var BANDS = 48;
  var F_LO = 30;
  var F_HI = 16000;
  var COLS_PER_BAND = 8;
  var ROWS = 150;                 /* ~7.5 s at 20 frames a second */
  var FLOOR = 10;                 /* byte 10 = -90 dBFS: black */
  var CEIL = 96;                  /* byte 96 = -4 dBFS: white-hot */
  var METER_MIN_DB = -60;
  var PEAK_HOLD_MS = 1500;
  var PEAK_FALL_DB_PER_S = 24;
  var CLIP_HOLD_MS = 2500;
  var READOUT_MS = 250;
  var STALE_MS = 1200;

  /* ------------------------------------------------------------ pure parts */

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  /** base64 -> byte array (0..100). Tolerates an array already decoded. */
  function decodeBands(b64) {
    if (!b64) return null;
    if (Array.isArray(b64)) return b64.map(function (v) { return clamp(Number(v) || 0, 0, 100); });
    var bin = '';
    try {
      if (typeof root.atob === 'function') bin = root.atob(String(b64));
      else if (typeof Buffer !== 'undefined') bin = Buffer.from(String(b64), 'base64').toString('binary');
    } catch (err) { return null; }
    if (!bin) return null;
    var out = new Array(bin.length);
    for (var i = 0; i < bin.length; i += 1) out[i] = clamp(bin.charCodeAt(i), 0, 100);
    return out;
  }

  /** The centre frequency of band `b` (0..BANDS-1), log-spaced. */
  function bandHz(b, n) {
    n = n || BANDS;
    return F_LO * Math.pow(F_HI / F_LO, b / (n - 1));
  }

  /** Where a frequency sits across the waterfall, 0..1 (log). */
  function hzToX(hz) {
    return clamp(Math.log(hz / F_LO) / Math.log(F_HI / F_LO), 0, 1);
  }

  /** dBFS -> 0..1 of the meter's height (METER_MIN_DB at the bottom). */
  function dbToFrac(db) {
    db = Number(db);
    if (!isFinite(db)) return 0;
    return clamp((db - METER_MIN_DB) / -METER_MIN_DB, 0, 1);
  }

  /* The colour ramp: the panel's own night blue up through its teal and
   * cyan, into the gold it uses for a warning and on to a hot white. 256
   * RGBA entries, built once. */
  var STOPS = [
    [0.00, [8, 13, 17]],
    [0.18, [14, 46, 58]],
    [0.40, [31, 111, 122]],
    [0.58, [101, 199, 218]],
    [0.74, [227, 190, 99]],
    [0.88, [255, 138, 61]],
    [1.00, [255, 244, 228]]
  ];
  function buildRamp() {
    var lut = new Uint8ClampedArray(256 * 4);
    for (var i = 0; i < 256; i += 1) {
      var t = i / 255;
      var k = 1;
      while (k < STOPS.length - 1 && STOPS[k][0] < t) k += 1;
      var a = STOPS[k - 1], b = STOPS[k];
      var f = (t - a[0]) / Math.max(1e-6, b[0] - a[0]);
      f = clamp(f, 0, 1);
      lut[i * 4] = Math.round(a[1][0] + (b[1][0] - a[1][0]) * f);
      lut[i * 4 + 1] = Math.round(a[1][1] + (b[1][1] - a[1][1]) * f);
      lut[i * 4 + 2] = Math.round(a[1][2] + (b[1][2] - a[1][2]) * f);
      lut[i * 4 + 3] = 255;
    }
    return lut;
  }
  var RAMP = buildRamp();

  /** A band byte (0..100, dBFS+100) -> a ramp index 0..255. */
  function byteToIndex(v) {
    return Math.round(clamp((v - FLOOR) / (CEIL - FLOOR), 0, 1) * 255);
  }

  /** One waterfall row: `width` RGBA pixels interpolated across the bands,
   *  written into `out` (a Uint8ClampedArray of width*4). A grid tint is
   *  mixed in for the one-second marks. */
  function paintRow(bands, width, out, grid) {
    var n = bands.length;
    for (var x = 0; x < width; x += 1) {
      var pos = n > 1 ? x / (width - 1) * (n - 1) : 0;
      var i0 = Math.floor(pos);
      var i1 = Math.min(n - 1, i0 + 1);
      var f = pos - i0;
      var v = bands[i0] * (1 - f) + bands[i1] * f;
      var k = byteToIndex(v) * 4;
      var o = x * 4;
      var r = RAMP[k], g = RAMP[k + 1], b = RAMP[k + 2];
      if (grid) {                    /* a faint line every second */
        r = r + (60 - r) * grid;
        g = g + (84 - g) * grid;
        b = b + (96 - b) * grid;
      }
      out[o] = r; out[o + 1] = g; out[o + 2] = b; out[o + 3] = 255;
    }
    return out;
  }

  /** The axis marks, as fractions across the waterfall. */
  function axisMarks() {
    return [[50, '50'], [100, '100'], [250, '250'], [500, '500'], [1000, '1k'],
      [2000, '2k'], [4000, '4k'], [8000, '8k'], [16000, '16k']].map(function (m) {
      return {hz: m[0], label: m[1], x: hzToX(m[0])};
    });
  }

  function fmtDb(db) {
    db = Number(db);
    if (!isFinite(db) || db <= -99) return '-inf';
    return (db >= 0 ? '+' : '') + db.toFixed(1);
  }

  /* ------------------------------------------------------------- the view */

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /**
   * Build the audiograph into `host`. Answers a controller:
   *   push(frame)       - a frame from the levels stream (or the 1 s state)
   *   resume() / pause()
   *   note(text, kind)  - the one line over the picture ('' clears it)
   *   clear()
   *   stats()           - {frames, drawn, dropped, lastAt}
   */
  function mount(host, opts) {
    opts = opts || {};
    var dpr = Math.min(1.25, Number(root.devicePixelRatio) || 1);
    var W = BANDS * COLS_PER_BAND;
    var H = ROWS;

    host.classList.add('pl-scope');
    var wrap = make('div', 'pl-scope-wrap');
    var fall = make('div', 'pl-fall');
    var canvas = make('canvas', 'pl-fall-canvas');
    canvas.width = W;
    canvas.height = H;
    canvas.setAttribute('aria-label', 'Falling audiograph of the live input: low notes left, high notes right, newest at the top');
    canvas.setAttribute('role', 'img');
    fall.appendChild(canvas);

    var axis = make('div', 'pl-fall-axis');
    axisMarks().forEach(function (m) {
      var tick = make('span', '', m.label);
      tick.style.left = (m.x * 100).toFixed(2) + '%';
      axis.appendChild(tick);
    });
    fall.appendChild(axis);
    var overlay = make('div', 'pl-fall-note');
    overlay.hidden = true;
    fall.appendChild(overlay);

    var meterBox = make('div', 'pl-meter');
    var meter = make('canvas', 'pl-meter-canvas');
    meterBox.appendChild(meter);
    var scale = make('div', 'pl-meter-scale');
    [0, -6, -12, -18, -24, -36, -48].forEach(function (db) {
      var mark = make('span', '', String(db));
      mark.style.bottom = (dbToFrac(db) * 100).toFixed(2) + '%';
      scale.appendChild(mark);
    });
    meterBox.appendChild(scale);

    wrap.appendChild(fall);
    wrap.appendChild(meterBox);
    host.appendChild(wrap);

    /* The readout: fixed cells, written at most READOUT_MS apart. */
    var readout = make('div', 'pl-readout');
    var cells = {};
    [['rms', 'RMS'], ['peak', 'PEAK'], ['l', 'L'], ['r', 'R'], ['duck', 'DUCK'], ['clip', '']].forEach(function (c) {
      var cell = make('span', 'pl-readout-' + c[0]);
      if (c[1]) cell.appendChild(make('small', '', c[1]));
      var val = make('b', '', c[0] === 'clip' ? 'CLIP' : '--');
      cell.appendChild(val);
      readout.appendChild(cell);
      cells[c[0]] = val;
    });
    host.appendChild(readout);

    var ctx = canvas.getContext('2d', {alpha: false});
    var mctx = meter.getContext('2d');
    var row = ctx ? ctx.createImageData(W, 1) : null;
    if (ctx) { ctx.fillStyle = '#080d11'; ctx.fillRect(0, 0, W, H); }

    var state = {
      running: false, pending: [], raf: 0, frames: 0, drawn: 0, dropped: 0,
      lastAt: 0, lastSecond: -1,
      peak: [METER_MIN_DB, METER_MIN_DB], peakAt: [0, 0], peakShown: [METER_MIN_DB, METER_MIN_DB],
      clipAt: 0, lastFrame: null, readAt: 0, meterW: 0, meterH: 0, staleTimer: 0
    };

    function sizeMeter() {
      var box = meter.getBoundingClientRect();
      var w = Math.max(24, Math.round(box.width * dpr));
      var h = Math.max(40, Math.round(box.height * dpr));
      if (w !== state.meterW || h !== state.meterH) {
        state.meterW = meter.width = w;
        state.meterH = meter.height = h;
        drawMeter(Date.now());
      }
    }
    var ro = null;
    if (typeof root.ResizeObserver === 'function') {
      ro = new root.ResizeObserver(function () { if (state.running) sizeMeter(); });
      ro.observe(meterBox);
    }

    function drawRows() {
      state.raf = 0;
      if (!state.running || !ctx) { state.pending.length = 0; return; }
      var list = state.pending;
      state.pending = [];
      /* A stall (a hidden tab, a busy WebView) can deliver a burst. Draw
       * at most a second's worth; older rows would scroll straight off. */
      if (list.length > 24) { state.dropped += list.length - 24; list = list.slice(-24); }
      var n = list.length;
      if (n) {
        /* the one-second marks, decided oldest to newest */
        var marks = new Array(n);
        for (var j = 0; j < n; j += 1) {
          var sec = Math.floor(Number(list[j].t) || 0);
          marks[j] = state.lastSecond >= 0 && sec !== state.lastSecond ? (sec % 5 === 0 ? 0.4 : 0.18) : 0;
          state.lastSecond = sec;
        }
        ctx.drawImage(canvas, 0, 0, W, H - n, 0, n, W, H - n);
        for (var i = 0; i < n; i += 1) {
          var k = n - 1 - i;                   /* newest on the top row */
          paintRow(list[k].__bands, W, row.data, marks[k]);
          ctx.putImageData(row, 0, i);
          state.drawn += 1;
        }
      }
      drawMeter(Date.now());
      readoutMaybe(Date.now());
    }

    function drawMeter(now) {
      if (!mctx || !state.meterW) return;
      var w = state.meterW, h = state.meterH;
      mctx.clearRect(0, 0, w, h);
      var f = state.lastFrame || {};
      var fresh = now - state.lastAt < STALE_MS;
      var gap = Math.max(1, Math.round(2 * dpr));
      var duckW = Math.max(3, Math.round(w * 0.14));
      var barW = Math.floor((w - duckW - gap * 3) / 2);
      var sides = [f.l, f.r];
      if (!isFinite(Number(sides[0]))) sides[0] = f.rms;
      if (!isFinite(Number(sides[1]))) sides[1] = f.rms;
      for (var s = 0; s < 2; s += 1) {
        var x = s * (barW + gap);
        mctx.fillStyle = '#0d151b';
        mctx.fillRect(x, 0, barW, h);
        var lvl = fresh ? dbToFrac(sides[s]) : 0;
        var top = Math.round(h * (1 - lvl));
        /* the fill: green, gold past -12, red past -3 */
        var yGold = Math.round(h * (1 - dbToFrac(-12)));
        var yRed = Math.round(h * (1 - dbToFrac(-3)));
        if (top < h) {
          mctx.fillStyle = '#3fb97a';
          mctx.fillRect(x, Math.max(top, yGold), barW, h - Math.max(top, yGold));
          if (top < yGold) {
            mctx.fillStyle = '#e3be63';
            mctx.fillRect(x, Math.max(top, yRed), barW, yGold - Math.max(top, yRed));
          }
          if (top < yRed) {
            mctx.fillStyle = '#ef6f5e';
            mctx.fillRect(x, top, barW, yRed - top);
          }
        }
        /* the peak hold: held PEAK_HOLD_MS, then it falls */
        var held = state.peakShown[s];
        var age = now - state.peakAt[s];
        if (age > PEAK_HOLD_MS) held = Math.max(METER_MIN_DB, state.peak[s] - (age - PEAK_HOLD_MS) / 1000 * PEAK_FALL_DB_PER_S);
        state.peakShown[s] = held;
        if (held > METER_MIN_DB) {
          var py = Math.round(h * (1 - dbToFrac(held)));
          mctx.fillStyle = held > -3 ? '#ffb3a8' : '#edf3f5';
          mctx.fillRect(x, Math.max(0, py - 1), barW, Math.max(1, Math.round(2 * dpr)));
        }
      }
      /* the duck: how far the set is being dipped under a DJ line, drawn
       * down from the top of its own thin column */
      var dx = 2 * (barW + gap) + gap;
      mctx.fillStyle = '#0d151b';
      mctx.fillRect(dx, 0, duckW, h);
      var duck = fresh ? Number(f.duck) : 0;
      if (isFinite(duck) && duck < -0.2) {
        var dh = Math.round(h * clamp(-duck / 30, 0, 1));
        mctx.fillStyle = '#65c7da';
        mctx.fillRect(dx, 0, duckW, dh);
      }
      /* the clip lamp across the top */
      if (now - state.clipAt < CLIP_HOLD_MS) {
        mctx.fillStyle = '#ff5a4f';
        mctx.fillRect(0, 0, 2 * barW + gap, Math.max(3, Math.round(4 * dpr)));
      }
    }

    function readoutMaybe(now) {
      if (now - state.readAt < READOUT_MS) return;
      state.readAt = now;
      var f = state.lastFrame;
      var fresh = f && now - state.lastAt < STALE_MS;
      setCell('rms', fresh ? fmtDb(f.rms) : '--');
      setCell('peak', fresh ? fmtDb(f.peak) : '--');
      setCell('l', fresh && isFinite(Number(f.l)) ? fmtDb(f.l) : '--');
      setCell('r', fresh && isFinite(Number(f.r)) ? fmtDb(f.r) : '--');
      var duck = fresh ? Number(f.duck) : NaN;
      setCell('duck', isFinite(duck) && duck < -0.2 ? duck.toFixed(1) : '0');
      var clipping = now - state.clipAt < CLIP_HOLD_MS;
      if (cells.clip.parentNode.classList.contains('on') !== clipping) {
        cells.clip.parentNode.classList.toggle('on', clipping);
      }
    }

    function setCell(name, text) {
      if (cells[name].textContent !== text) cells[name].textContent = text;
    }

    function schedule() {
      if (state.raf || !state.running) return;
      state.raf = (root.requestAnimationFrame || function (fn) { return root.setTimeout(fn, 50); })(drawRows);
    }

    function push(frame) {
      if (!frame) return;
      state.frames += 1;
      var now = Date.now();
      var bands = decodeBands(frame.bands);
      var f = {t: Number(frame.t) || now / 1000, rms: Number(frame.rms), peak: Number(frame.peak),
        l: frame.l === undefined || frame.l === null ? NaN : Number(frame.l),
        r: frame.r === undefined || frame.r === null ? NaN : Number(frame.r),
        duck: Number(frame.duck) || 0, clip: !!frame.clip, __bands: bands};
      state.lastFrame = f;
      state.lastAt = now;
      /* each side's peak: the frame's crest (peak over rms) on that side's
       * rms; the frame's own peak when the sides are not given */
      var crest = isFinite(f.peak) && isFinite(f.rms) ? f.peak - f.rms : 0;
      for (var s = 0; s < 2; s += 1) {
        var side = s === 0 ? f.l : f.r;
        var v = isFinite(side) ? side + crest : f.peak;
        if (!isFinite(v)) continue;
        if (v >= state.peakShown[s]) { state.peak[s] = v; state.peakAt[s] = now; state.peakShown[s] = v; }
      }
      if (f.clip) state.clipAt = now;
      if (!state.running) return;
      if (bands && bands.length) state.pending.push(f);
      schedule();
    }

    /* With no frames coming the meter must fall back to silence and the
     * readout must stop claiming a level - a half-second check, and only
     * while the view is running. */
    function staleTick() {
      if (!state.running) return;
      var now = Date.now();
      if (state.lastFrame && now - state.lastAt >= STALE_MS) {
        drawMeter(now);
        readoutMaybe(now + READOUT_MS);
      }
    }

    function resume() {
      if (state.running) return;
      state.running = true;
      sizeMeter();
      if (!state.staleTimer) state.staleTimer = root.setInterval(staleTick, 500);
      schedule();
    }

    function pause() {
      state.running = false;
      state.pending.length = 0;
      if (state.raf && root.cancelAnimationFrame) { try { root.cancelAnimationFrame(state.raf); } catch (err) { /* gone */ } }
      state.raf = 0;
      if (state.staleTimer) { root.clearInterval(state.staleTimer); state.staleTimer = 0; }
    }

    function note(text, kind) {
      text = String(text || '');
      if (!text) { overlay.hidden = true; return; }
      if (overlay.textContent !== text) overlay.textContent = text;
      overlay.className = 'pl-fall-note' + (kind ? ' ' + kind : '');
      overlay.hidden = false;
    }

    function clear() {
      if (ctx) { ctx.fillStyle = '#080d11'; ctx.fillRect(0, 0, W, H); }
      state.lastFrame = null;
      state.peak = [METER_MIN_DB, METER_MIN_DB];
      state.peakShown = [METER_MIN_DB, METER_MIN_DB];
      drawMeter(Date.now());
    }

    function destroy() {
      pause();
      if (ro) { try { ro.disconnect(); } catch (err) { /* gone */ } }
    }

    return {push: push, resume: resume, pause: pause, note: note, clear: clear, destroy: destroy,
      running: function () { return state.running; },
      lastAt: function () { return state.lastAt; },
      stats: function () { return {frames: state.frames, drawn: state.drawn, dropped: state.dropped, lastAt: state.lastAt}; },
      canvas: canvas};
  }

  var api = {mount: mount, decodeBands: decodeBands, bandHz: bandHz, hzToX: hzToX,
    dbToFrac: dbToFrac, byteToIndex: byteToIndex, paintRow: paintRow, axisMarks: axisMarks,
    fmtDb: fmtDb, ramp: RAMP, BANDS: BANDS, ROWS: ROWS};
  root.PineLiveScope = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
