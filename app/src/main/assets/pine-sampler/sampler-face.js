/* THE SAMPLER'S FACE: a wallpaper, waveforms on the pads, three knobs and an
 * edit sheet.
 *
 * "Make sure the sampler page also has these controls and functionality. I
 *  need to be able to set a wallpaper for the background of the sampler
 *  screen based on images from the Pine Box Gallery. When editing a clip,
 *  allow me to specify the details of the clip similar to the image with the
 *  same style of pop up. I want the sampler to have the aesthetic I am
 *  showing in these images."
 *
 * The reference is a hardware-style phone sampler: a photograph behind
 * everything, pads drawn as translucent tiles with their own waveform, a row
 * of rotary knobs above the grid, and an edit panel that drops down over the
 * pads with the clip's waveform and its play mode.
 *
 * WHY THIS IS A SEPARATE FILE. sampler.js is already the largest view in the
 * app and it owns the INSTRUMENT - the engine, the banks, the gestures, the
 * bytes. This owns only the FACE, and it reaches the instrument through the
 * seams sampler.js publishes rather than through its internals. The one new
 * seam is `onPad`, which exists because a face that polled for the selection
 * would be a timer running all day to catch something that happens when a
 * finger moves.
 *
 * EVERY KNOB MOVES SOUND. Pan did not exist in either engine when this was
 * asked for; it was added to the C++ core, the JNI, Kotlin and the Web Audio
 * engine FIRST, and verified round-tripping on the tablet, precisely so that
 * none of these three is a control that does nothing. This project has
 * shipped two of those already and they are worse than an empty space.
 */
(function (root) {
  'use strict';

  var SKIN_KEY = 'pineSamplerSkin';

  function sampler() { return root.PineSampler || null; }
  /* THE ENGINE THE SAMPLER IS ACTUALLY USING, which on the tablet is the
   * NATIVE one. `pineSampler` first, exactly as sampler.js does it:
   * PineSamplerEngine is the Web Audio implementation and it is published
   * under its own name even when the native engine owns the pads, so
   * preferring it here meant asking an engine with no pads in it how long
   * pad 1 was. It answered zero, the waveform drew nothing and every knob
   * read its default - a face wired to the wrong instrument. */
  function engine() { return root.pineSampler || root.PineSamplerEngine || null; }

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function host() {
    return document.getElementById('sampler') || document.querySelector('.pb-sampler');
  }

  /* ===================================================== the wallpaper === */

  /* THE SAME PICTURE THE STATION IS SELLING, unless the operator picked one.
   *
   * WallpaperWatch already answers "what art is on the block" for the tablet's
   * home screen, and the answer is the same here: `selling_now` first, then
   * the newest render. The difference is that this one is a CHOICE - the
   * operator can pin a picture they like and it stays until they change it,
   * because a background that moves under your hands while you are playing is
   * a distraction, not a feature.
   */
  var skin = {url: '', name: '', pinned: false};

  function loadSkin() {
    try {
      var saved = JSON.parse(root.localStorage.getItem(SKIN_KEY) || 'null');
      if (saved && saved.url) skin = saved;
    } catch (err) { /* no preference is the normal case */ }
  }

  function saveSkin() {
    try { root.localStorage.setItem(SKIN_KEY, JSON.stringify(skin)); }
    catch (err) { /* a preference is not worth an exception */ }
  }

  function paintSkin() {
    var where = host();
    if (!where) return;
    if (skin.url) {
      where.style.backgroundImage = 'url("' + skin.url + '")';
      where.classList.add('pb-skinned');
    } else {
      where.style.removeProperty('background-image');
      where.classList.remove('pb-skinned');
    }
  }

  function api() { return root.pineDesktop || null; }

  function get(route) {
    var bridge = api();
    if (bridge && typeof bridge.get === 'function') {
      return Promise.resolve(bridge.get(route)).then(function (text) {
        return typeof text === 'string' ? JSON.parse(text) : text;
      });
    }
    return fetch(route, {credentials: 'same-origin'}).then(function (res) {
      if (!res.ok) throw new Error('the station said ' + res.status);
      return res.json();
    });
  }

  /* A page of gallery pictures, newest first. Videos are dropped: a wallpaper
   * cannot be one, and this route serves .mp4 alongside the stills. */
  function pictures(limit) {
    return get('/api/generations?limit=' + (limit || 60)).then(function (log) {
      var rows = (log && log.generations) || [];
      var out = [];
      for (var i = 0; i < rows.length; i += 1) {
        var files = (rows[i] && rows[i].files) || [];
        for (var f = 0; f < files.length; f += 1) {
          var name = String(files[f] || '');
          if (/\.(png|jpe?g|webp)$/i.test(name)) out.push(name);
        }
      }
      return out;
    });
  }

  function urlFor(name) {
    return '/api/generations/image/' + encodeURIComponent(name);
  }

  var picker = null;
  function closePicker() {
    if (picker) { picker.remove(); picker = null; }
  }

  function openPicker() {
    closePicker();
    picker = make('div', 'pb-skins');
    var head = make('div', 'pb-skins-head');
    head.appendChild(make('b', '', 'Background'));
    var shut = make('button', 'pb-skins-x', '×');
    shut.addEventListener('click', closePicker);
    head.appendChild(shut);
    picker.appendChild(head);

    var row = make('div', 'pb-skins-acts');
    var follow = make('button', 'pb-skins-act',
      'Follow the station · whatever is being sold');
    follow.addEventListener('click', function () {
      skin = {url: '', name: '', pinned: false};
      saveSkin();
      paintSkin();
      followStation();
      closePicker();
    });
    var none = make('button', 'pb-skins-act', 'No picture');
    none.addEventListener('click', function () {
      skin = {url: '', name: '', pinned: true};
      saveSkin();
      paintSkin();
      closePicker();
    });
    row.appendChild(follow);
    row.appendChild(none);
    picker.appendChild(row);

    var grid = make('div', 'pb-skins-grid');
    picker.appendChild(grid);
    document.body.appendChild(picker);
    if (root.PineDismiss) root.PineDismiss.watch(picker, closePicker, []);

    pictures(60).then(function (names) {
      if (!picker) return;
      if (!names.length) {
        grid.appendChild(make('p', 'pb-skins-none', 'The gallery has no pictures yet.'));
        return;
      }
      names.slice(0, 48).forEach(function (name) {
        var tile = make('button', 'pb-skins-tile');
        /* The THUMBNAIL, not the full render. The slideshow route resizes and
         * caches per width; the gallery route does not, and forty-eight
         * full-size PNGs is the 3.7 MB mistake all over again. */
        tile.style.backgroundImage =
          'url("/api/slideshow/media/' + encodeURIComponent(name) + '?w=320")';
        tile.title = name;
        tile.addEventListener('click', function () {
          skin = {url: urlFor(name), name: name, pinned: true};
          saveSkin();
          paintSkin();
          closePicker();
        });
        grid.appendChild(tile);
      });
    }, function (err) {
      if (picker) grid.appendChild(make('p', 'pb-skins-none',
        'The gallery would not answer: ' + ((err && err.message) || err)));
    });
  }

  /* When nothing is pinned, wear whatever the station is selling. */
  function followStation() {
    if (skin.pinned) return;
    var feed = root.PineStationFeed;
    var state = feed && feed.state ? (feed.state() || {}) : {};
    var sold = state.selling_now;
    var name = sold && sold.image ? String(sold.image) : '';
    if (name) {
      if (skin.name === name) return;
      skin = {url: urlFor(name), name: name, pinned: false};
      paintSkin();
      return;
    }
    if (skin.url) return;                 /* keep the last one rather than blank */
    pictures(12).then(function (names) {
      if (skin.pinned || !names.length) return;
      skin = {url: urlFor(names[0]), name: names[0], pinned: false};
      paintSkin();
    }, function () { /* no gallery, no background */ });
  }

  /* ================================================ waveforms on the pads == */

  /* WHY THE PADS CARRY A PICTURE OF THEIR SOUND. Sixteen tiles of text all
   * look the same at arm's length; sixteen waveforms do not. The engine
   * already computes peaks for the trim editor, so this is a read, not a
   * decode - and it is cached per pad because a bank repaint should not be
   * sixteen analyses. */
  var peakCache = Object.create(null);

  function peaksFor(key) {
    if (peakCache[key]) return peakCache[key];
    var audio = engine();
    if (!audio || typeof audio.peaks !== 'function') return null;
    var got = null;
    try { got = audio.peaks(key, 64); } catch (err) { got = null; }
    if (got && got.length) peakCache[key] = got;
    return got;
  }

  function forgetPeaks(key) { delete peakCache[key]; }

  function drawPadWave(cell, key) {
    var canvas = cell.querySelector('.pb-pad-wave');
    var bars = peaksFor(key);
    if (!bars) {
      if (canvas) canvas.remove();
      return;
    }
    if (!canvas) {
      canvas = make('canvas', 'pb-pad-wave');
      canvas.width = 128;
      canvas.height = 44;
      cell.insertBefore(canvas, cell.firstChild);
    }
    var pen = canvas.getContext('2d');
    pen.clearRect(0, 0, canvas.width, canvas.height);
    var mid = canvas.height / 2;
    var step = canvas.width / bars.length;
    pen.fillStyle = 'rgba(18, 26, 32, .78)';
    for (var i = 0; i < bars.length; i += 1) {
      var v = Math.max(0, Math.min(1, Number(bars[i]) || 0));
      var h = Math.max(1, v * mid);
      pen.fillRect(i * step, mid - h, Math.max(1, step - 0.6), h * 2);
    }
  }

  function paintPadFaces() {
    var api_ = sampler();
    if (!api_) return;
    var bank = api_.bankIndex();
    var layout = api_.layout();
    for (var p = 0; p < api_.padCount; p += 1) {
      var cell = document.getElementById('pad-' + p);
      if (!cell) continue;
      var meta = layout[bank][p];
      if (!meta) {
        var old = cell.querySelector('.pb-pad-wave');
        if (old) old.remove();
        continue;
      }
      drawPadWave(cell, api_.padKey(bank, p));
    }
  }

  /* ====================================================== the knob row ==== */

  /* A ROTARY, DRIVEN VERTICALLY.
   *
   * Turning a knob by following the angle of the finger is how hardware
   * works and is miserable on glass: the pointer crosses the centre and the
   * value jumps half a turn. Every software sampler worth using drags
   * UP and DOWN instead, and that is what this does - a full travel is about
   * two hundred pixels, and holding shift is not available on a tablet so
   * fine adjustment comes from a slow drag rather than a modifier.
   */
  function knob(name, spec) {
    var wrap = make('div', 'pb-knob');
    wrap.dataset.knob = spec.key;
    var dial = make('div', 'pb-knob-dial');
    var mark = make('i', 'pb-knob-mark');
    dial.appendChild(mark);
    var label = make('span', 'pb-knob-name', name);
    var said = make('b', 'pb-knob-said', '');
    wrap.appendChild(dial);
    wrap.appendChild(label);
    wrap.appendChild(said);

    var dragging = false;
    var startY = 0;
    var startValue = 0;

    var show = function (value) {
      var unit = (value - spec.min) / (spec.max - spec.min);
      /* 270 degrees of travel, the hardware convention: seven o'clock round
       * to five o'clock, with the dead zone at the bottom. */
      mark.style.transform = 'rotate(' + (-135 + unit * 270).toFixed(1) + 'deg)';
      said.textContent = spec.say(value);
    };

    wrap.addEventListener('pointerdown', function (event) {
      var value = spec.read();
      if (value === null) return;
      dragging = true;
      startY = event.clientY;
      startValue = value;
      try { wrap.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
      wrap.classList.add('turning');
      event.preventDefault();
    });
    wrap.addEventListener('pointermove', function (event) {
      if (!dragging) return;
      var travel = (startY - event.clientY) / 200;
      var want = startValue + travel * (spec.max - spec.min);
      want = Math.max(spec.min, Math.min(spec.max, want));
      spec.write(want);
      show(want);
    });
    var stop = function () {
      if (!dragging) return;
      dragging = false;
      wrap.classList.remove('turning');
      spec.done();
    };
    wrap.addEventListener('pointerup', stop);
    wrap.addEventListener('pointercancel', stop);
    /* A double tap puts it back where it started - the only way to find
     * centre again on a control with no numbers under the thumb. */
    wrap.addEventListener('dblclick', function () {
      spec.write(spec.home);
      show(spec.home);
      spec.done();
    });

    wrap.show = show;
    wrap.spec = spec;
    return wrap;
  }

  var knobs = [];
  var faceRow = null;

  function selectedKey() {
    var api_ = sampler();
    if (!api_) return null;
    var bank = api_.bankIndex();
    var pad = api_.selectedPad();
    if (!api_.layout()[bank][pad]) return null;
    return {key: api_.padKey(bank, pad), bank: bank, pad: pad};
  }

  function padSetting(field, fallback) {
    var at = selectedKey();
    if (!at) return null;
    var audio = engine();
    var state = null;
    try { state = audio.get(at.key); } catch (err) { state = null; }
    if (state && field in state) return Number(state[field]);
    var meta = sampler().layout()[at.bank][at.pad];
    var got = meta ? Number(meta[field]) : NaN;
    return isFinite(got) ? got : fallback;
  }

  function setPadSetting(field, value) {
    var at = selectedKey();
    if (!at) return;
    var patch = {};
    patch[field] = value;
    try { engine().set(at.key, patch); } catch (err) { /* engine said no */ }
    var meta = sampler().layout()[at.bank][at.pad];
    if (meta) meta[field] = value;
  }

  function settled() {
    var api_ = sampler();
    if (api_) api_.save();
  }

  function buildFace() {
    var where = host();
    if (!where || faceRow) return;
    /* The grid lives inside .pb-right, not directly under the host, so the
     * row is inserted into the GRID'S OWN parent. `where.insertBefore(row,
     * grid)` throws NotFoundError when grid is a grandchild - which is
     * exactly what it did, silently taking the whole face with it. */
    var grid = where.querySelector('.pb-padwrap');
    if (!grid || !grid.parentNode) return;

    faceRow = make('div', 'pb-face');

    knobs = [
      knob('VOL', {
        key: 'gain', min: 0, max: 2, home: 1,
        say: function (v) { return Math.round(v * 100) + '%'; },
        read: function () { return padSetting('gain', 1); },
        write: function (v) { setPadSetting('gain', v); },
        done: settled
      }),
      knob('PITCH', {
        /* In SEMITONES on the face and a ratio underneath, because "+3" is a
         * thing a person can aim at and 1.1892 is not. */
        key: 'pitch', min: -24, max: 24, home: 0,
        say: function (v) {
          var n = Math.round(v);
          return n === 0 ? '0' : (n > 0 ? '+' : '') + n;
        },
        read: function () {
          var ratio = padSetting('pitch', 1);
          return ratio === null ? null : 12 * Math.log2(Math.max(0.03125, ratio));
        },
        write: function (v) { setPadSetting('pitch', Math.pow(2, Math.round(v) / 12)); },
        done: settled
      }),
      knob('PAN', {
        key: 'pan', min: -1, max: 1, home: 0,
        say: function (v) {
          var n = Math.round(v * 50);
          if (!n) return 'C';
          return (n < 0 ? 'L' : 'R') + Math.abs(n);
        },
        read: function () { return padSetting('pan', 0); },
        write: function (v) { setPadSetting('pan', v); },
        done: settled
      })
    ];
    knobs.forEach(function (k) { faceRow.appendChild(k); });

    var side = make('div', 'pb-face-acts');
    var edit = make('button', 'pb-face-act', 'EDIT');
    edit.addEventListener('click', function () { openEdit(); });
    var kill = make('button', 'pb-face-act', 'DELETE');
    kill.addEventListener('click', function () { deleteSelected(); });
    var skinBtn = make('button', 'pb-face-act pb-face-skin', 'BACKDROP');
    skinBtn.title = 'A picture from the Pine Box gallery behind the pads';
    skinBtn.addEventListener('click', openPicker);
    side.appendChild(edit);
    side.appendChild(kill);
    side.appendChild(skinBtn);
    faceRow.appendChild(side);

    grid.parentNode.insertBefore(faceRow, grid);
    paintFace();
  }

  function paintFace() {
    var at = selectedKey();
    if (faceRow) faceRow.classList.toggle('empty', !at);
    for (var i = 0; i < knobs.length; i += 1) {
      var value = knobs[i].spec.read();
      knobs[i].show(value === null ? knobs[i].spec.home : value);
    }
  }

  async function deleteSelected() {
    var api_ = sampler();
    var at = selectedKey();
    if (!api_ || !at) return;
    var meta = api_.layout()[at.bank][at.pad];
    var said = (meta && meta.label ? meta.label : 'this pad').slice(0, 48);
    if (!root.confirm('Delete pad ' + (at.pad + 1) + '?\n\n' + said)) return;
    /* Silence first, then remove - clearing under a sounding voice leaves a
     * sound with nothing left to stop it. */
    try { engine().stopAll(); } catch (err) { /* nothing playing */ }
    if (root.PineAir) root.PineAir.release('pad');
    forgetPeaks(at.key);
    await api_.forget(at.bank, at.pad);
    closeEdit();
    paintFace();
  }

  /* ======================================================== the edit sheet = */

  var sheet = null;
  var unwatchSheet = null;

  function closeEdit() {
    if (unwatchSheet) { unwatchSheet(); unwatchSheet = null; }
    if (sheet) { sheet.remove(); sheet = null; }
  }

  function openEdit(which) {
    var api_ = sampler();
    if (!api_) return;
    if (which !== undefined) api_.select(which);
    var at = selectedKey();
    closeEdit();
    if (!at) return;

    sheet = make('div', 'pb-edit');

    var stage = make('div', 'pb-edit-stage');
    var canvas = make('canvas', 'pb-edit-wave');
    canvas.id = 'pbEditWave';
    stage.appendChild(canvas);
    var lane = make('div', 'pb-edit-lane');
    lane.appendChild(make('i', 'pb-edit-band'));
    lane.appendChild(make('i', 'pb-edit-handle a'));
    lane.appendChild(make('i', 'pb-edit-handle b'));
    stage.appendChild(lane);
    sheet.appendChild(stage);

    var tabs = make('div', 'pb-edit-tabs');
    tabs.appendChild(make('span', 'pb-edit-tab on', 'SAMPLE'));
    sheet.appendChild(tabs);

    var row = make('div', 'pb-edit-row');
    var prev = make('button', 'pb-edit-arrow', '◀');
    prev.title = 'The pad before this one';
    prev.addEventListener('click', function () {
      openEdit((at.pad + api_.padCount - 1) % api_.padCount);
    });
    var next = make('button', 'pb-edit-arrow', '▶');
    next.title = 'The pad after this one';
    next.addEventListener('click', function () {
      openEdit((at.pad + 1) % api_.padCount);
    });

    var modes = make('div', 'pb-edit-modes');
    var mode = function (name, field, on) {
      var button = make('button', 'pb-edit-mode' + (on ? ' on' : ''), name);
      button.addEventListener('click', function () {
        if (field === 'oneshot') {
          /* ONE SHOT is the ABSENCE of loop, not a flag of its own - the
           * engine has one truth and the face must not invent a second. */
          setPadSetting('loop', false);
        } else {
          setPadSetting(field, !readMode(field));
        }
        settled();
        openEdit(at.pad);
      });
      return button;
    };
    modes.appendChild(mode('ONE SHOT', 'oneshot', !readMode('loop')));
    modes.appendChild(mode('REVERSE', 'reverse', readMode('reverse')));
    modes.appendChild(mode('LOOP', 'loop', readMode('loop')));

    row.appendChild(prev);
    row.appendChild(modes);
    row.appendChild(next);
    sheet.appendChild(row);

    var says = make('p', 'pb-edit-said', '');
    says.id = 'pbEditSaid';
    sheet.appendChild(says);

    var where = host();
    where.appendChild(sheet);
    if (root.PineDismiss) unwatchSheet = root.PineDismiss.watch(sheet, closeEdit, []);

    drawEdit(at);
    wireTrim(lane, at);
  }

  function readMode(field) {
    var at = selectedKey();
    if (!at) return false;
    var state = null;
    try { state = engine().get(at.key); } catch (err) { state = null; }
    if (state && field in state) return !!state[field];
    var meta = sampler().layout()[at.bank][at.pad];
    return !!(meta && meta[field]);
  }

  function padWindow(at) {
    var audio = engine();
    var total = 0;
    try { total = Number(audio.seconds(at.key)) || 0; } catch (err) { total = 0; }
    var state = null;
    try { state = audio.get(at.key); } catch (err) { state = null; }
    var trim = state && state.trim ? state.trim : null;
    var from = trim ? Math.max(0, Number(trim.start) || 0) : 0;
    var to = trim && Number(trim.end) > from
      ? Math.min(total, Number(trim.end)) : total;
    return {total: total, from: from, to: to};
  }

  function drawEdit(at) {
    var canvas = document.getElementById('pbEditWave');
    if (!canvas) return;
    var width = canvas.clientWidth || 560;
    var height = canvas.clientHeight || 150;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    var pen = canvas.getContext('2d');
    pen.clearRect(0, 0, width, height);

    var bars = null;
    try { bars = engine().peaks(at.key, Math.min(512, Math.max(64, width))); }
    catch (err) { bars = null; }
    if (bars && bars.length) {
      var mid = height / 2;
      var step = width / bars.length;
      pen.fillStyle = '#7fd4ea';
      for (var i = 0; i < bars.length; i += 1) {
        var v = Math.max(0, Math.min(1, Number(bars[i]) || 0));
        var h = Math.max(1, v * (mid - 6));
        pen.fillRect(i * step, mid - h, Math.max(1, step - 0.5), h * 2);
      }
    }
    var win = padWindow(at);
    var said = document.getElementById('pbEditSaid');
    var meta = sampler().layout()[at.bank][at.pad];
    if (said) {
      said.textContent = 'pad ' + (at.pad + 1) + ' · '
        + (win.to - win.from).toFixed(2) + 's of ' + win.total.toFixed(2) + 's'
        + (meta && meta.label ? ' · ' + meta.label.slice(0, 60) : '');
    }
    placeTrim(win);
  }

  function placeTrim(win) {
    if (!sheet) return;
    var lane = sheet.querySelector('.pb-edit-lane');
    if (!lane || !win.total) return;
    var a = win.from / win.total;
    var b = win.to / win.total;
    lane.querySelector('.pb-edit-handle.a').style.left = (a * 100).toFixed(2) + '%';
    lane.querySelector('.pb-edit-handle.b').style.left = (b * 100).toFixed(2) + '%';
    var band = lane.querySelector('.pb-edit-band');
    band.style.left = (a * 100).toFixed(2) + '%';
    band.style.width = ((b - a) * 100).toFixed(2) + '%';
  }

  function wireTrim(lane, at) {
    var holding = null;
    var at01 = function (event) {
      var box = lane.getBoundingClientRect();
      return Math.max(0, Math.min(1,
        (event.clientX - box.left) / Math.max(1, box.width)));
    };
    lane.addEventListener('pointerdown', function (event) {
      var win = padWindow(at);
      if (!win.total) return;
      var where = at01(event);
      holding = Math.abs(where - win.from / win.total)
        <= Math.abs(where - win.to / win.total) ? 'a' : 'b';
      try { lane.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
      move(event);
    });
    var move = function (event) {
      if (!holding) return;
      var win = padWindow(at);
      if (!win.total) return;
      var where = at01(event) * win.total;
      var from = win.from;
      var to = win.to;
      if (holding === 'a') from = Math.min(where, to - 0.02);
      else to = Math.max(where, from + 0.02);
      setPadSetting('trim', {start: Math.max(0, from), end: Math.min(win.total, to)});
      drawEdit(at);
    };
    lane.addEventListener('pointermove', move);
    var stop = function () {
      if (!holding) return;
      holding = null;
      settled();
    };
    lane.addEventListener('pointerup', stop);
    lane.addEventListener('pointercancel', stop);
  }

  /* ============================================================= startup == */

  var started = false;
  function start() {
    if (started) return;
    started = true;
    /* Never let the face take the instrument down with it: the sampler has
     * to play whether or not it is wearing a photograph. */
    try { build(); } catch (err) {
      if (root.console) root.console.warn('sampler face: ' + (err && err.message));
    }
  }

  function build() {
    loadSkin();
    paintSkin();
    buildFace();
    followStation();
    var api_ = sampler();
    if (api_ && api_.onPad) {
      api_.onPad(function () {
        paintFace();
        paintPadFaces();
      });
    }
    /* The station's idea of what it is selling changes on its own clock, and
     * only matters when nothing is pinned. Once a minute is plenty; the
     * gallery is not a slideshow here. */
    setInterval(followStation, 60000);
  }

  var out = {
    start: start, openEdit: openEdit, closeEdit: closeEdit,
    openPicker: openPicker, paintFace: paintFace, paintPadFaces: paintPadFaces,
    forgetPeaks: forgetPeaks,
    skin: function () { return skin; }
  };
  root.PineSamplerFace = out;
  if (typeof module !== 'undefined' && module.exports) module.exports = out;
})(typeof window !== 'undefined' ? window : globalThis);
