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
  /* [plviz] the visualizer's styles, cycled by a tap (PLVIZ_QUEUE.md holds
   * the rest of the operator's sheet) */
  var VIZ_STYLES = [
    {name: 'Bars', kind: 'bars', color: '#ff9a1f'},
    {name: 'Neon mirror', kind: 'mirror', color: '#29b6ff'},
    {name: 'LED', kind: 'led', color: '#39e36b'},
    {name: 'LED mirror', kind: 'ledmirror', color: '#ff2e7a'},
    {name: 'Glow wave', kind: 'wave', color: '#2ee6e6'},
    /* [plviz2] the rest of the sheet, row by row; env shapes the height
     * across the bands (centre = taller middle, tri = a diamond) */
    {name: 'Neon sine', kind: 'sine', color: '#3dff7a'},
    {name: 'Violet line', kind: 'line', color: '#b35cff'},
    {name: 'Red matrix', kind: 'dotmatrix', color: '#ff3b3b', env: 'centre'},
    {name: 'Blue needles', kind: 'needles', color: '#3d8bff'},
    {name: 'Gold line', kind: 'osc', color: '#ffc53d'},
    {name: 'Violet cloud', kind: 'cloud', color: '#a45cff'},
    {name: 'Sky mirror', kind: 'taper', color: '#5ec8ff', env: 'centre'},
    {name: 'Lime slats', kind: 'gapbars', color: '#a6ff2e'},
    {name: 'Ember cloud', kind: 'cloud', color: '#ff8a1f'},
    {name: 'Blue diamond', kind: 'diamond', color: '#3b7bff', env: 'tri'},
    {name: 'Violet thin', kind: 'thin', color: '#c04dff', env: 'centre'}
  ];
  var VIZ_MORE = {sine: 1, line: 1, dotmatrix: 1, needles: 1, osc: 1, cloud: 1,
    taper: 1, gapbars: 1, diamond: 1, thin: 1};   /* [plviz2] drawn by drawVizMore */
  var VIZ_HOLD_MS = 700;           /* a peak cap holds this long ... */
  var VIZ_FALL_PER_S = 0.55;       /* ... then falls this much of the height a second */
  var VIZ_BAR_FALL_PER_S = 2.2;    /* the bars themselves ease down */

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

  /* [msgviz] THE VISUALIZER, SHARED: drawVizMore and drawViz's painting half,
     lifted verbatim out of mount() so any canvas can draw a style. */
  function vizPainter(vctx, vz, dpr) {
    /* [plviz2] the other eleven styles, all drawn about the middle line: a
     * wide low-alpha pass is the glow, then the core, then every band's
     * peak cap at its held height. Answers false for the first five kinds. */
    function vizHash(a) { a = Math.sin(a * 12.9898) * 43758.5453; return a - Math.floor(a); }
    function drawVizMore(st, cw, ch, n, slot, mid, cap, now) {
      var k = st.kind;
      if (!VIZ_MORE[k]) return false;
      var span = Math.max(1, mid - cap - 1), lw = Math.max(1, dpr);
      var i, j, c, x, y, h, w, t, pass, on, pts;
      var env = new Array(n);
      for (i = 0; i < n; i += 1) {
        t = (i + 0.5) / n;
        env[i] = st.env === 'centre' ? 0.3 + 0.7 * Math.sin(Math.PI * t)
          : (st.env === 'tri' ? 1 - 0.8 * Math.abs(2 * t - 1) : 1);
      }
      function lv(p) {   /* the eased level at a fractional band, shaped */
        var a = clamp(Math.floor(p), 0, n - 1), b = Math.min(n - 1, a + 1), f = clamp(p - a, 0, 1);
        return (vz.level[a] || 0) * env[a] * (1 - f) + (vz.level[b] || 0) * env[b] * f;
      }
      vctx.lineJoin = 'round';
      if (k === 'sine') {                 /* a mirrored lobe every two bands */
        for (pass = 0; pass < 2; pass += 1) {
          vctx.beginPath();
          vctx.moveTo(0, mid);
          for (i = 0; i < n; i += 2) {
            h = Math.max(lv(i), lv(i + 1)) * span;
            vctx.quadraticCurveTo((i + 1) * slot, mid - 2 * h, Math.min(cw, (i + 2) * slot), mid);
          }
          for (i = n - 2 + (n % 2); i >= 0; i -= 2) {
            h = Math.max(lv(i), lv(i + 1)) * span;
            vctx.quadraticCurveTo((i + 1) * slot, mid + 2 * h, i * slot, mid);
          }
          vctx.closePath();
          if (pass) { vctx.globalAlpha = 1; vctx.lineWidth = lw * 1.6; vctx.stroke(); }
          else { vctx.globalAlpha = 0.2; vctx.fill(); vctx.lineWidth = lw * 7; vctx.stroke(); }
        }
      } else if (k === 'line' || k === 'osc') {
        pts = [[0, mid]];
        if (k === 'line') {                 /* one smooth swing a band, alternate sides */
          for (i = 0; i < n; i += 1) pts.push([(i + 0.5) * slot, mid - (i % 2 ? -1 : 1) * lv(i) * span]);
          pts.push([cw, mid]);
        } else {                             /* a carrier whose swing is the spectrum */
          t = now / 1000 * 7;
          for (j = 1; j <= n * 4; j += 1) pts.push([j * slot / 4, mid - lv(j / 4 - 0.5) * span * Math.sin(j * 1.9 + t)]);
        }
        for (pass = 0; pass < 2; pass += 1) {
          vctx.globalAlpha = pass ? 1 : 0.22;
          vctx.lineWidth = pass ? lw * 1.8 : lw * 6;
          vctx.beginPath();
          vctx.moveTo(pts[0][0], pts[0][1]);
          for (j = 1; j < pts.length - 1; j += 1) {
            if (k === 'line') vctx.quadraticCurveTo(pts[j][0], pts[j][1], (pts[j][0] + pts[j + 1][0]) / 2, (pts[j][1] + pts[j + 1][1]) / 2);
            else vctx.lineTo(pts[j][0], pts[j][1]);
          }
          vctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
          vctx.stroke();
        }
      } else if (k === 'taper' || k === 'gapbars' || k === 'thin') {
        var frac = k === 'thin' ? 0.28 : (k === 'taper' ? 0.8 : 0.7);
        for (pass = 0; pass < 2; pass += 1) {
          vctx.globalAlpha = pass ? 1 : 0.22;
          w = Math.max(1, Math.min(slot, slot * frac * (pass ? 1 : 1.8)));
          for (i = 0; i < n; i += 1) {
            h = lv(i) * span;
            vctx.fillRect((i + 0.5) * slot - w / 2, mid - h, w, Math.max(1, 2 * h));
          }
        }
        if (k === 'gapbars') {                /* the fine slats: background lines across */
          var gap = Math.max(1, Math.round(dpr)), pitch = Math.max(3, Math.round(4 * dpr));
          vctx.globalAlpha = 1;
          vctx.fillStyle = '#05080b';
          for (y = mid - gap / 2 - pitch * Math.floor(mid / pitch); y < ch; y += pitch) vctx.fillRect(0, y, cw, gap);
        }
      } else if (k === 'needles' || k === 'cloud') {
        var sub = k === 'cloud' ? 6 : 3, seed = Math.floor(now / 60) % 997;
        for (pass = 0; pass < 2; pass += 1) {
          vctx.globalAlpha = pass ? 1 : 0.2;
          vctx.lineWidth = pass ? lw : lw * 2.5;
          vctx.beginPath();
          for (j = 0; j < n * sub; j += 1) {
            h = lv((j + 0.5) / sub - 0.5) * span;
            h *= k === 'cloud' ? 0.25 + 0.75 * vizHash(j * 1.37 + seed * 7.1) : 0.8 + 0.2 * vizHash(j);
            x = (j + 0.5) * slot / sub;
            vctx.moveTo(x, mid - h);
            vctx.lineTo(x, mid + h);
          }
          vctx.stroke();
        }
      } else {                                  /* dotmatrix, diamond: a mirrored dot grid */
        var dm = k === 'dotmatrix';
        var pch = Math.max(2 * dpr, Math.min(cw / (n * (dm ? 2 : 1)), mid / (dm ? 12 : 8)));
        var cols = Math.max(1, Math.floor(cw / pch)), x0 = (cw - cols * pch) / 2;
        var rows = Math.max(3, Math.floor(span / pch)), dot = pch * (dm ? 0.72 : 0.62);
        var lit = new Array(cols);
        for (j = 0; j < cols; j += 1) lit[j] = Math.round(lv((j + 0.5) / cols * n - 0.5) * rows);
        vctx.globalAlpha = 0.16;              /* the glow: one soft column per lit column */
        for (j = 0; j < cols; j += 1) if (lit[j]) vctx.fillRect(x0 + j * pch, mid - lit[j] * pch, pch, 2 * lit[j] * pch);
        vctx.globalAlpha = 1;
        vctx.beginPath();
        for (j = 0; j < cols; j += 1) {
          x = x0 + (j + 0.5) * pch;
          on = lit[j];
          for (c = 0; c < on; c += 1) {
            y = (c + 0.5) * pch;
            if (dm) { vctx.rect(x - dot / 2, mid - y - dot / 2, dot, dot); vctx.rect(x - dot / 2, mid + y - dot / 2, dot, dot); }
            else {
              vctx.moveTo(x + dot / 2, mid - y); vctx.arc(x, mid - y, dot / 2, 0, 2 * Math.PI);
              vctx.moveTo(x + dot / 2, mid + y); vctx.arc(x, mid + y, dot / 2, 0, 2 * Math.PI);
            }
          }
        }
        vctx.fill();
      }
      /* every band's peak cap, held then falling (drawViz moved vz.hold) */
      vctx.globalAlpha = 1;
      vctx.fillStyle = '#ffffff';
      w = Math.max(1, slot * (k === 'thin' ? 0.3 : 0.6));
      for (i = 0; i < n; i += 1) {
        h = (vz.hold[i] || 0) * env[i] * span;
        x = (i + 0.5) * slot - w / 2;
        if (k === 'line') { vctx.fillRect(x, i % 2 ? mid + h : mid - h - cap, w, cap); continue; }
        vctx.fillRect(x, mid - h - cap, w, cap);
        vctx.fillRect(x, mid + h, w, cap);
      }
      vctx.fillStyle = st.color;
      return true;
    }
    function vizBody(st, cw, ch, n, now) {
      var i, c, v, h, x;
      vctx.globalAlpha = 1;
      vctx.fillStyle = '#05080b';
      vctx.fillRect(0, 0, cw, ch);
      var slot = cw / n, bw = Math.max(1, slot * 0.62), mid = ch / 2, cap = Math.max(2, Math.round(2 * dpr));
      vctx.fillStyle = st.color;
      vctx.strokeStyle = st.color;
      if (drawVizMore(st, cw, ch, n, slot, mid, cap, now)) { /* [plviz2] drawn */ }
      else if (st.kind === 'wave') {
        for (var pass = 0; pass < 2; pass += 1) {
          vctx.globalAlpha = pass ? 0.9 : 0.28;
          vctx.beginPath();
          vctx.moveTo(0, mid);
          for (i = 0; i < n; i += 1) vctx.lineTo((i + 0.5) * slot, mid - vz.level[i] * (mid - 2));
          vctx.lineTo(cw, mid);
          for (i = n - 1; i >= 0; i -= 1) vctx.lineTo((i + 0.5) * slot, mid + vz.level[i] * (mid - 2));
          vctx.closePath();
          if (pass) { vctx.lineWidth = Math.max(1, dpr * 1.5); vctx.stroke(); } else vctx.fill();
        }
        vctx.globalAlpha = 1;
        for (i = 0; i < n; i += 1) {
          vctx.fillRect((i + 0.5) * slot - cap / 2, mid - vz.hold[i] * (mid - 2) - cap, cap, cap);
          vctx.fillRect((i + 0.5) * slot - cap / 2, mid + vz.hold[i] * (mid - 2), cap, cap);
        }
      } else {
        var cells = st.kind === 'led' ? 18 : 9;
        for (var glow = 0; glow < 2; glow += 1) {
          vctx.globalAlpha = glow ? 1 : 0.22;
          var gw = glow ? bw : Math.min(slot, bw * 1.7);
          for (i = 0; i < n; i += 1) {
            x = i * slot + (slot - gw) / 2;
            if (st.kind === 'bars') {
              h = vz.level[i] * (ch - cap - 2);
              vctx.fillRect(x, ch - h, gw, h);
            } else if (st.kind === 'mirror') {
              h = vz.level[i] * (mid - cap - 1);
              vctx.fillRect(x, mid - h, gw, Math.max(1, 2 * h));
            } else {
              var ledH = (st.kind === 'led' ? ch : mid) / cells;
              var on = Math.round(vz.level[i] * cells);
              for (c = 0; c < on; c += 1) {
                if (st.kind === 'led') vctx.fillRect(x, ch - (c + 1) * ledH + 1, gw, ledH - 2);
                else {
                  vctx.fillRect(x, mid - (c + 1) * ledH + 1, gw, ledH - 2);
                  vctx.fillRect(x, mid + c * ledH + 1, gw, ledH - 2);
                }
              }
            }
          }
        }
        vctx.globalAlpha = 1;
        vctx.fillStyle = '#ffffff';
        for (i = 0; i < n; i += 1) {
          x = i * slot + (slot - bw) / 2;
          if (st.kind === 'bars' || st.kind === 'led') vctx.fillRect(x, ch - vz.hold[i] * (ch - cap - 2) - cap, bw, cap);
          else {
            h = vz.hold[i] * (mid - cap - 1);
            vctx.fillRect(x, mid - h - cap, bw, cap);
            vctx.fillRect(x, mid + h, bw, cap);
          }
        }
      }
    }
    return {more: drawVizMore, body: vizBody};
  }

  /* [msgviz] One frame of a style onto any 2d context: levels 0..1 (any band
     count), the bars easing down, every band's cap held VIZ_HOLD_MS then
     falling - the state object carries both between frames. */
  function vizDraw(ctx, w, h, levels, state, styleIndex) {
    if (!ctx || !levels || !levels.length) return null;
    state = state || {};
    var vz = state.vz || (state.vz = {style: 0, level: [], hold: [], holdAt: [], at: 0, named: 0});
    if (!state.painter || state.ctx !== ctx) {
      state.painter = vizPainter(ctx, vz, Number(state.dpr) || 1);
      state.ctx = ctx;
    }
    var now = Date.now(), n = levels.length;
    var dt = vz.at ? Math.min(0.25, (now - vz.at) / 1000) : 0;
    vz.at = now;
    for (var i = 0; i < n; i += 1) {
      var v = clamp(Number(levels[i]) || 0, 0, 1);
      vz.level[i] = Math.max(v, (vz.level[i] || 0) - dt * VIZ_BAR_FALL_PER_S);
      if (v >= (vz.hold[i] || 0)) { vz.hold[i] = v; vz.holdAt[i] = now; }
      else if (now - (vz.holdAt[i] || 0) > VIZ_HOLD_MS) vz.hold[i] = Math.max(v, vz.hold[i] - dt * VIZ_FALL_PER_S);
    }
    var L = VIZ_STYLES.length;
    var st = VIZ_STYLES[((Math.floor(Number(styleIndex) || 0) % L) + L) % L];
    state.painter.body(st, Math.max(1, Math.round(w)), Math.max(1, Math.round(h)), n, now);
    return st;
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

    /* [plviz] the visualizer takes the big area; the waterfall steps into the
     * narrow box beside the meter. A tap cycles the style (kept per screen). */
    var vizBox = make('div', 'pl-viz');
    var viz = make('canvas', 'pl-viz-canvas');
    viz.setAttribute('role', 'img');
    viz.setAttribute('aria-label', 'Spectrum of the live input - tap to change the style');
    vizBox.appendChild(viz);
    var vizName = make('span', 'pl-viz-name', '');
    vizBox.appendChild(vizName);
    var vctx = viz.getContext('2d');
    var vz = {style: 0, level: [], hold: [], holdAt: [], at: 0, named: 0};
    var painter = vizPainter(vctx, vz, dpr);   /* [msgviz] */
    var drawVizMore = painter.more;
    try { vz.style = (parseInt(root.localStorage.getItem('pineLive.viz') || '0', 10) || 0) % VIZ_STYLES.length; } catch (err) { vz.style = 0; }
    vizBox.addEventListener('click', function (e) {
      e.stopPropagation();
      vz.style = (vz.style + 1) % VIZ_STYLES.length;
      vz.named = Date.now();
      try { root.localStorage.setItem('pineLive.viz', String(vz.style)); } catch (err) { /* per screen only */ }
      if (state.lastFrame) drawViz(state.lastFrame.__bands, Date.now());
    });
    wrap.appendChild(vizBox);
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


    /* [plviz] one frame of the visualizer: bars ease down, each band's peak
     * cap holds VIZ_HOLD_MS then falls at VIZ_FALL_PER_S. */
    function drawViz(bands, now) {
      if (!vctx || !bands || !bands.length) return;
      var cw = Math.max(1, Math.round(vizBox.clientWidth * dpr));
      var ch = Math.max(1, Math.round(vizBox.clientHeight * dpr));
      if (viz.width !== cw || viz.height !== ch) { viz.width = cw; viz.height = ch; }
      var st = VIZ_STYLES[vz.style] || VIZ_STYLES[0];
      var n = bands.length, i, c, v, h, x;
      var dt = vz.at ? Math.min(0.25, (now - vz.at) / 1000) : 0;
      vz.at = now;
      for (i = 0; i < n; i += 1) {
        v = clamp((bands[i] - FLOOR) / (CEIL - FLOOR), 0, 1);
        vz.level[i] = Math.max(v, (vz.level[i] || 0) - dt * VIZ_BAR_FALL_PER_S);
        if (v >= (vz.hold[i] || 0)) { vz.hold[i] = v; vz.holdAt[i] = now; }
        else if (now - (vz.holdAt[i] || 0) > VIZ_HOLD_MS) vz.hold[i] = Math.max(v, vz.hold[i] - dt * VIZ_FALL_PER_S);
      }
      painter.body(st, cw, ch, n, now);   /* [msgviz] the shared painter */
      if (vizName.textContent !== st.name) vizName.textContent = st.name;
      vizName.style.opacity = now - vz.named < 1500 ? '1' : '0';
    }

    function drawRows() {
      state.raf = 0;
      if (!state.running || !ctx) { state.pending.length = 0; return; }
      var list = state.pending;
      state.pending = [];
      if (list.length) drawViz(list[list.length - 1].__bands, Date.now());   /* [plviz] */
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
    fmtDb: fmtDb, ramp: RAMP, BANDS: BANDS, ROWS: ROWS,
    vizDraw: vizDraw,                                   /* [msgviz] */
    VIZ_STYLES: VIZ_STYLES.map(function (s) { return {name: s.name, kind: s.kind}; })};
  root.PineLiveScope = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
