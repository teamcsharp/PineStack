/* THE GRAB WINDOW: WHAT JUST PLAYED, AND WHAT PLAYED BEFORE THAT.
 *
 * "If I tap on a pad and there is nothing there, then allow me to basically
 *  open a pop up that allows me to grab from previous seconds that the
 *  broadcast was playing and capture that and put that on the pad."
 *
 * "Also in the pop-up for recursive assignment show all the clips that had
 *  recently played in a sidebar and allow me to even tap on those to bring up
 *  its audio where I can then trim the boundaries and assign it to the pad."
 *
 * TWO SOURCES, ONE PAIR OF HANDLES. There are two different things the
 * operator might want and they are not interchangeable:
 *
 *   THE AIR    the last two minutes as they actually SOUNDED - the mix, the
 *              levels, the music under the voice. Held in memory by
 *              sampler-air.js. This is the only way to get a moment that was
 *              never a file: a laugh over a record, an overlap, a stumble.
 *   A CLIP     one line as the station RENDERED it, fetched from
 *              /api/booth/clip. Clean, isolated, and exactly one speaker.
 *
 * Both land on the same waveform with the same two handles and the same
 * ASSIGN button, because the choice between them is about what you want, not
 * about how the window works.
 *
 * THE SCRUBBER IS DRAWN FROM THE RING, NOT FROM A FILE. That means the window
 * can show the operator two minutes of broadcast without downloading
 * anything, and the selection is a memcpy. It also means the picture is only
 * as long as the tap has been listening - which is said, rather than drawn as
 * a misleading empty stretch.
 */
(function (root) {
  'use strict';

  var sheet = null;
  var view = null;       /* {buffer, rate, fromAir, label, who, cut}  */
  var sel = {a: 0, b: 1};/* selection, as fractions of the view       */
  var audition = null;

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function api() {
    return root.pineDesktop || null;
  }

  /* ------------------------------------------------------------- opening */

  var host = null;

  function open(options) {
    close();
    host = options || {};
    sheet = make('div', 'sg-sheet');

    var head = make('div', 'sg-head');
    head.appendChild(make('b', '', 'Put something on pad ' + ((host.pad | 0) + 1)));
    var shut = make('button', 'sg-x', '×');
    shut.type = 'button';
    shut.addEventListener('click', close);
    head.appendChild(shut);
    sheet.appendChild(head);

    var body = make('div', 'sg-body');

    /* ---- the sidebar: what has recently played ------------------------ */
    var side = make('aside', 'sg-side');
    side.appendChild(make('h4', '', 'Recently played'));
    var list = make('div', 'sg-list');
    list.id = 'sgList';
    side.appendChild(list);
    body.appendChild(side);

    /* ---- the stage: the waveform and its handles ---------------------- */
    var stage = make('section', 'sg-stage');

    var pick = make('div', 'sg-pick');
    var airBtn = make('button', 'sg-src on', 'The air');
    airBtn.type = 'button';
    airBtn.title = 'The broadcast as it sounded, mix and all';
    var said = make('span', 'sg-said', '');
    said.id = 'sgSaid';
    pick.appendChild(airBtn);
    pick.appendChild(said);
    stage.appendChild(pick);

    var canvas = make('canvas', 'sg-wave');
    canvas.id = 'sgWave';
    stage.appendChild(canvas);

    var lane = make('div', 'sg-lane');
    lane.id = 'sgLane';
    lane.appendChild(make('i', 'sg-handle a'));
    lane.appendChild(make('i', 'sg-sel'));
    lane.appendChild(make('i', 'sg-handle b'));
    stage.appendChild(lane);

    var read = make('div', 'sg-read', '');
    read.id = 'sgRead';
    stage.appendChild(read);

    var row = make('div', 'sg-acts');
    var play = make('button', 'sg-act', 'Preview');
    play.type = 'button';
    play.addEventListener('click', preview);
    var whole = make('button', 'sg-act', 'Whole thing');
    whole.type = 'button';
    whole.addEventListener('click', function () {
      sel.a = 0; sel.b = 1; paint();
    });
    var assign = make('button', 'sg-act go', 'Put it on the pad');
    assign.type = 'button';
    assign.addEventListener('click', assignIt);
    row.appendChild(play);
    row.appendChild(whole);
    row.appendChild(assign);
    stage.appendChild(row);

    body.appendChild(stage);
    sheet.appendChild(body);
    document.body.appendChild(sheet);

    airBtn.addEventListener('click', function () {
      airBtn.classList.add('on');
      showAir();
      markList(null);
    });

    wireLane(lane);
    showAir();
    fillList(list);

    if (root.PineDismiss) root.PineDismiss.watch(sheet, close, []);
  }

  function close() {
    stopAudition();
    if (sheet) { sheet.remove(); sheet = null; }
    view = null;
    host = null;
  }

  /* ---------------------------------------------------------- the air view */

  function showAir() {
    var air = root.PineAir;
    var said = document.getElementById('sgSaid');
    if (!air || !air.ready()) {
      view = null;
      if (said) said.textContent = air ? air.why() : 'the air tap is not loaded';
      paint();
      return;
    }
    var have = air.seconds();
    var bytes = air.sliceWav(have, 0);
    if (!bytes) { view = null; paint(); return; }
    decode(bytes).then(function (buffer) {
      view = {
        buffer: buffer, bytes: bytes, fromAir: true,
        label: 'air', who: 'broadcast',
        cut: 'off the air, as it played'
      };
      /* THE NEWEST END IS THE INTERESTING END. Two minutes of history with
       * the selection defaulting to the whole of it would make the common
       * case - "that bit just now" - the one that needs the most dragging.
       * The last eight seconds is where a hand reaches. */
      var want = Math.min(8, buffer.duration);
      sel.a = 1 - (want / buffer.duration);
      sel.b = 1;
      if (said) {
        said.textContent = have.toFixed(0) + 's held · drag the handles';
      }
      paint();
    }, function (err) {
      view = null;
      if (said) said.textContent = 'that would not decode: ' + (err.message || err);
      paint();
    });
  }

  /* ------------------------------------------------------- the clip sidebar */

  /* WHAT THE FEED ALREADY KNOWS. sampler.js has sourceFor()/takeable() for
   * exactly this question - which rows have audio behind them - and they are
   * published so a second view does not have to guess from `aired`, the
   * mistake that once offered 7 takeable moments out of about 220. */
  function fillList(list) {
    var sampler = root.PineSampler;
    var rows = [];
    try {
      /* The ONE poller, not a second one: PineStationFeed is what the
       * sampler's own feed pane already reads, so this window shows exactly
       * the rows the operator can see behind it. */
      var feed = root.PineStationFeed;
      if (feed && typeof feed.rows === 'function') rows = (feed.rows() || []).slice().reverse();
    } catch (err) { rows = []; }
    if (!rows.length && root.djLastState && root.djLastState.chat) {
      rows = root.djLastState.chat.slice(-60).reverse();
    }
    var offered = 0;
    for (var i = 0; i < rows.length && offered < 40; i += 1) {
      var row = rows[i];
      if (!row) continue;
      if (sampler && typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        continue;
      }
      offered += 1;
      list.appendChild(clipRow(row));
    }
    if (!offered) {
      list.appendChild(make('p', 'sg-none',
        'Nothing with audio behind it yet. The air on the left is still there.'));
    }
  }

  function clipRow(row) {
    var item = make('button', 'sg-clip');
    item.type = 'button';
    item.appendChild(make('b', '', (row.who || row.name || 'line')));
    item.appendChild(make('span', '', String(row.text || '').slice(0, 90)));
    item.addEventListener('click', function () {
      markList(item);
      var pickAir = document.querySelector('.sg-src');
      if (pickAir) pickAir.classList.remove('on');
      loadClip(row, item);
    });
    return item;
  }

  function markList(which) {
    var all = document.querySelectorAll('.sg-clip');
    for (var i = 0; i < all.length; i += 1) all[i].classList.toggle('on', all[i] === which);
  }

  function loadClip(row, item) {
    var said = document.getElementById('sgSaid');
    var sampler = root.PineSampler;
    var source = sampler && typeof sampler.sourceFor === 'function'
      ? sampler.sourceFor(row) : null;
    if (!source) {
      if (said) said.textContent = 'there is no audio behind that line yet';
      return;
    }
    if (said) said.textContent = 'fetching…';
    var bar = root.PineBusy ? root.PineBusy.attach(item, 'fetching') : null;
    fetchBytes(source.url).then(function (bytes) {
      return decode(bytes).then(function (buffer) {
        view = {
          buffer: buffer, bytes: bytes, fromAir: false,
          label: String(row.text || row.name || 'take').slice(0, 90),
          who: row.who || row.name || '',
          srcId: row.id || '',
          cut: 'the station’s own cut of this line'
        };
        sel.a = 0; sel.b = 1;
        if (said) said.textContent = buffer.duration.toFixed(2) + 's · trim it and assign';
        if (bar) bar.finish(true);
        paint();
      });
    }, function (err) {
      if (bar) bar.finish(false);
      if (said) said.textContent = 'could not fetch it: ' + (err.message || err);
    });
  }

  /* The bridge fetches where there is one - it carries the bearer and is not
   * subject to the page's origin - and plain fetch is the fallback. */
  function fetchBytes(url) {
    var bridge = api();
    if (bridge && typeof bridge.getBytes === 'function') {
      return Promise.resolve(bridge.getBytes(url)).then(function (got) {
        return got && got.bytes ? got.bytes : got;
      });
    }
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error('the station said ' + res.status);
      return res.arrayBuffer();
    });
  }

  function decode(bytes) {
    var engine = root.PineSamplerEngine;
    var ctx = engine && engine.context ? engine.context() : null;
    if (!ctx) {
      var Ctor = root.AudioContext || root.webkitAudioContext;
      if (!Ctor) return Promise.reject(new Error('no audio engine here'));
      ctx = new Ctor();
    }
    return ctx.decodeAudioData(bytes.slice(0));
  }

  /* ------------------------------------------------------------ the picture */

  function paint() {
    var canvas = document.getElementById('sgWave');
    var read = document.getElementById('sgRead');
    if (!canvas) return;
    var width = canvas.clientWidth || 600;
    var height = canvas.clientHeight || 96;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    var pen = canvas.getContext('2d');
    pen.clearRect(0, 0, width, height);
    if (!view || !view.buffer) {
      pen.globalAlpha = 0.5;
      pen.fillStyle = '#7c8b7a';
      pen.fillRect(0, height / 2, width, 1);
      if (read) read.textContent = '';
      place();
      return;
    }
    /* MIN AND MAX PER COLUMN, not one sample per column: a plain stride
     * through 5.7 million samples draws aliasing, not a waveform, and the
     * operator is choosing edges by eye. */
    var data = view.buffer.getChannelData(0);
    var per = data.length / width;
    pen.fillStyle = '#9fe08f';
    for (var x = 0; x < width; x += 1) {
      var from = Math.floor(x * per);
      var to = Math.min(data.length, Math.floor((x + 1) * per));
      var lo = 1, hi = -1;
      for (var i = from; i < to; i += 1) {
        var v = data[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (lo > hi) { lo = 0; hi = 0; }
      var top = (1 - hi) * height / 2;
      var bottom = (1 - lo) * height / 2;
      pen.fillRect(x, top, 1, Math.max(1, bottom - top));
    }
    if (read) {
      var span = view.buffer.duration;
      read.textContent = (sel.a * span).toFixed(2) + 's to ' + (sel.b * span).toFixed(2)
        + 's · ' + ((sel.b - sel.a) * span).toFixed(2) + 's selected';
    }
    place();
  }

  function place() {
    var lane = document.getElementById('sgLane');
    if (!lane) return;
    var a = lane.querySelector('.sg-handle.a');
    var b = lane.querySelector('.sg-handle.b');
    var band = lane.querySelector('.sg-sel');
    if (a) a.style.left = (sel.a * 100).toFixed(2) + '%';
    if (b) b.style.left = (sel.b * 100).toFixed(2) + '%';
    if (band) {
      band.style.left = (sel.a * 100).toFixed(2) + '%';
      band.style.width = ((sel.b - sel.a) * 100).toFixed(2) + '%';
    }
  }

  function wireLane(lane) {
    var dragging = null;
    var at = function (event) {
      var box = lane.getBoundingClientRect();
      return Math.max(0, Math.min(1, (event.clientX - box.left) / Math.max(1, box.width)));
    };
    lane.addEventListener('pointerdown', function (event) {
      var where = at(event);
      /* Whichever handle is nearer - a lane this thin cannot be hit reliably
       * by aiming at the handle itself with a thumb. */
      dragging = Math.abs(where - sel.a) <= Math.abs(where - sel.b) ? 'a' : 'b';
      try { lane.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
      move(event);
    });
    var move = function (event) {
      if (!dragging) return;
      var where = at(event);
      if (dragging === 'a') sel.a = Math.min(where, sel.b - 0.002);
      else sel.b = Math.max(where, sel.a + 0.002);
      sel.a = Math.max(0, sel.a);
      sel.b = Math.min(1, sel.b);
      paint();
    };
    lane.addEventListener('pointermove', move);
    lane.addEventListener('pointerup', function () { dragging = null; });
    lane.addEventListener('pointercancel', function () { dragging = null; });
  }

  /* ------------------------------------------------------------- the sound */

  function stopAudition() {
    if (!audition) return;
    try { audition.stop(); } catch (err) { /* already done */ }
    audition = null;
    if (root.PineAir) root.PineAir.release('grab');
  }

  /* "Whenever I tap on audio, I want to mute the broadcast so I can hear that
   * audio that I am hearing from tapping on it." Same duck as the pads. */
  function preview() {
    stopAudition();
    if (!view || !view.buffer) return;
    var engine = root.PineSamplerEngine;
    var ctx = engine && engine.context ? engine.context() : null;
    if (!ctx) return;
    if (root.PineAir) root.PineAir.duck('grab');
    var span = view.buffer.duration;
    var from = sel.a * span;
    var length = Math.max(0.02, (sel.b - sel.a) * span);
    var node = ctx.createBufferSource();
    node.buffer = view.buffer;
    node.connect(ctx.destination);
    node.onended = function () {
      if (audition === node) stopAudition();
    };
    node.start(0, from, length);
    audition = node;
  }

  /* ------------------------------------------------------------ the assign */

  function assignIt() {
    if (!view || !view.buffer || !host || typeof host.put !== 'function') return;
    stopAudition();
    var span = view.buffer.duration;
    var from = sel.a * span;
    var to = sel.b * span;
    var bytes = cut(view.buffer, from, to);
    if (!bytes) return;
    var words = view.fromAir
      ? 'air · ' + (to - from).toFixed(1) + 's'
      : view.label;
    host.put(bytes, {
      label: words,
      who: view.who || '',
      kind: view.fromAir ? 'air' : 'clip',
      srcId: view.srcId || '',
      cut: view.cut + (sel.a > 0 || sel.b < 1
        ? ' (trimmed to ' + from.toFixed(2) + '–' + to.toFixed(2) + 's)'
        : '')
    }).then(function () {
      if (host && typeof host.note === 'function') {
        host.note('Pad ' + ((host.pad | 0) + 1) + ' - ' + words);
      }
      close();
    }, function (err) {
      var said = document.getElementById('sgSaid');
      if (said) said.textContent = 'it would not take: ' + (err.message || err);
    });
  }

  /* THE SELECTION AS WAV BYTES. The trim is baked in here rather than stored
   * as a trim range on the pad: a pad taken off the air has no file behind it
   * to re-trim from, and two different meanings of "trim" on one pad is how a
   * sampler starts lying about what it holds. The pad's own trim handles
   * still work afterwards, on this shorter recording. */
  function cut(buffer, from, to) {
    var rate = buffer.sampleRate;
    var start = Math.max(0, Math.floor(from * rate));
    var end = Math.min(buffer.length, Math.ceil(to * rate));
    var count = end - start;
    if (count < 1) return null;
    var channels = buffer.numberOfChannels;
    var out = new Float32Array(count);
    for (var c = 0; c < channels; c += 1) {
      var data = buffer.getChannelData(c);
      for (var i = 0; i < count; i += 1) out[i] += data[start + i] / channels;
    }
    return wav(out, rate);
  }

  function wav(samples, rate) {
    var bytes = new ArrayBuffer(44 + samples.length * 2);
    var view_ = new DataView(bytes);
    var text = function (at, s) {
      for (var i = 0; i < s.length; i += 1) view_.setUint8(at + i, s.charCodeAt(i));
    };
    text(0, 'RIFF');
    view_.setUint32(4, 36 + samples.length * 2, true);
    text(8, 'WAVE');
    text(12, 'fmt ');
    view_.setUint32(16, 16, true);
    view_.setUint16(20, 1, true);
    view_.setUint16(22, 1, true);
    view_.setUint32(24, rate, true);
    view_.setUint32(28, rate * 2, true);
    view_.setUint16(32, 2, true);
    view_.setUint16(34, 16, true);
    text(36, 'data');
    view_.setUint32(40, samples.length * 2, true);
    var at = 44;
    for (var i = 0; i < samples.length; i += 1) {
      var v = Math.max(-1, Math.min(1, samples[i]));
      view_.setInt16(at, v < 0 ? v * 0x8000 : v * 0x7fff, true);
      at += 2;
    }
    return bytes;
  }

  var apiOut = {open: open, close: close};
  root.PineSamplerGrab = apiOut;
  if (typeof module !== 'undefined' && module.exports) module.exports = apiOut;
})(typeof window !== 'undefined' ? window : globalThis);
