/* THE LEVEL METERS - what the music and the DJs are actually doing.
 *
 * "I want an audio meter of the audio that's playing for the music... and an
 * audio meter showing of the DJs talking. Like an audio meter that goes up
 * and down showing the notes that's happening."
 *
 * So: real levels off the real audio, not an animation. Which means tapping
 * the media elements with an AnalyserNode - and that is the dangerous part,
 * which is why this file is careful in ways that look excessive.
 *
 * THE HAZARD, IN THE CODEBASE'S OWN WORDS (app.py, the spectrogram note):
 *
 *   "Creating a MediaElementSource re-routes the element through the graph,
 *    so it must be reconnected to the destination or the audio goes silent -
 *    and it can only be created once per element."
 *
 * Once `createMediaElementSource(el)` is called, the element no longer feeds
 * the speakers directly. If the graph is not wired through to the
 * destination, or the context never starts, or the source node is garbage
 * collected, the audio is gone - and it cannot be undone, because a second
 * call on the same element throws. On this terminal that would mean
 * silencing a station that took a long time to get sounding.
 *
 * Hence:
 *
 *   - every tap connects source -> analyser -> destination IN THAT ORDER,
 *     and the destination hop is not optional or deferred;
 *   - every node is kept on a module-level map, because a garbage-collected
 *     MediaElementSource takes the audio with it;
 *   - a failed tap leaves the element ALONE and the meter simply reports
 *     nothing, rather than half-wiring a graph;
 *   - an element that something else has already tapped is detected by the
 *     marker below and skipped, since a second tap throws.
 *
 * A meter is worth having. It is not worth a silent radio.
 */
(function (root) {
  'use strict';

  var TAPPED = '__pineMeterTapped';
  var ctx = null;
  var taps = {};          /* keeps source/analyser alive - see above */
  var bins = 64;          /* bars across; 64 reads as "notes" at a glance */

  function context() {
    if (ctx) return ctx;
    var Ctor = root.AudioContext || root.webkitAudioContext;
    if (!Ctor) return null;
    try { ctx = new Ctor(); } catch (err) { return null; }
    return ctx;
  }

  /* Chromium starts a context suspended until a gesture. A suspended
   * context means a silent graph, so this is retried rather than assumed. */
  function wake() {
    var c = context();
    if (c && c.state === 'suspended') { try { c.resume(); } catch (err) { /* later */ } }
    return c && c.state === 'running';
  }

  /* Tap one element. Returns an analyser, or null - and null is a promise
   * that the element was not touched at all. */
  function tap(el) {
    if (!el) return null;
    if (taps[el.id]) return taps[el.id].analyser;
    /* Somebody else got here first; a second source on one element throws
     * and would take the audio with it. */
    if (el[TAPPED]) return null;
    var c = context();
    if (!c) return null;
    /* NEVER TAP INTO A GRAPH THAT IS NOT RUNNING.
     *
     * Chromium starts an AudioContext suspended until a user gesture. A
     * suspended graph produces nothing - so tapping the element here would
     * route the station's audio into silence, permanently, because
     * createMediaElementSource cannot be undone and cannot be called twice.
     *
     * A meter is worth having; it is not worth a silent radio. If the
     * context is not running yet, the element is left completely alone and
     * the meter reports that it has nothing to read. wake() is called on
     * every pointerdown, so the first touch makes the meters live. */
    if (c.state !== 'running') { wake(); return null; }
    var source = null;
    var analyser = null;
    try {
      source = c.createMediaElementSource(el);
      analyser = c.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;
      /* THE DESTINATION HOP. Without this the element is silent forever. */
      source.connect(analyser);
      analyser.connect(c.destination);
    } catch (err) {
      /* If the source was made but the wiring failed, put the audio back
       * the only way still available: straight to the speakers. */
      if (source) { try { source.connect(c.destination); } catch (e2) { /* gone */ } }
      return null;
    }
    el[TAPPED] = true;
    taps[el.id || ('el' + Object.keys(taps).length)] =
      {el: el, source: source, analyser: analyser,
       data: new Uint8Array(analyser.frequencyBinCount)};
    return analyser;
  }

  /* The loudest the DJs get. Voices are quieter than records, so the two
   * meters would otherwise look like the DJs never speak. */
  var GAIN = {music: 1, voice: 1.6};

  /* One reading: the bars, and a single peak for a simple meter. */
  function read(id, kind) {
    var held = taps[id];
    if (!held) return null;
    var analyser = held.analyser;
    var data = held.data;
    analyser.getByteFrequencyData(data);
    var lift = GAIN[kind] || 1;
    var out = new Array(bins);
    var step = Math.max(1, Math.floor(data.length / bins));
    var peak = 0;
    for (var b = 0; b < bins; b += 1) {
      var sum = 0;
      for (var k = 0; k < step; k += 1) sum += data[b * step + k] || 0;
      var v = Math.min(1, (sum / step / 255) * lift);
      out[b] = v;
      if (v > peak) peak = v;
    }
    /* An element that is paused or silent must read zero, not the last
     * frame the analyser happened to hold. */
    if (held.el.paused || held.el.muted) {
      for (var z = 0; z < bins; z += 1) out[z] = 0;
      peak = 0;
    }
    return {bars: out, peak: peak};
  }

  /* Draw one reading into a canvas. Bars from the middle out, so quiet
   * reads as a line rather than as an empty box. */
  function draw(canvas, reading, colour) {
    if (!canvas) return;
    var w = canvas.clientWidth || canvas.width;
    var h = canvas.clientHeight || canvas.height;
    if (!w || !h) return;
    var dpr = Math.min(2, root.devicePixelRatio || 1);
    if (canvas.width !== Math.round(w * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    var g = canvas.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (!reading) return;
    var bars = reading.bars;
    var gap = 1;
    var bw = Math.max(1, (w - gap * (bars.length - 1)) / bars.length);
    g.fillStyle = colour || '#65c7da';
    for (var i = 0; i < bars.length; i += 1) {
      var v = bars[i];
      var bh = Math.max(v > 0 ? 1.5 : 0.5, v * h);
      g.globalAlpha = v > 0 ? 0.35 + v * 0.65 : 0.18;
      g.fillRect(i * (bw + gap), (h - bh) / 2, bw, bh);
    }
    g.globalAlpha = 1;
  }

  /* Attach to whatever is on the page. Called on every paint: elements the
   * panel creates later (a DJ voice player per line) are picked up then. */
  function attach(ids) {
    wake();
    var got = {};
    for (var i = 0; i < ids.length; i += 1) {
      var el = document.getElementById(ids[i]);
      if (!el) continue;
      got[ids[i]] = !!tap(el);
    }
    return got;
  }

  /* The loudest of a set - the DJ meter watches several voice players and
   * only one of them speaks at a time. */
  function readLoudest(ids, kind) {
    var best = null;
    for (var i = 0; i < ids.length; i += 1) {
      var r = read(ids[i], kind);
      if (!r) continue;
      if (!best || r.peak > best.peak) best = r;
    }
    return best;
  }

  root.PineMeters = {
    attach: attach, read: read, readLoudest: readLoudest, draw: draw,
    wake: wake, bins: bins,
    /* For the honest empty state: are we actually reading anything? */
    tapped: function () { return Object.keys(taps); }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineMeters;
})(typeof window !== 'undefined' ? window : globalThis);
