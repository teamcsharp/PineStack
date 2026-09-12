/* window.PineSlideshowSource - the slideshow's whole traffic budget.
 *
 * THE VIEW THIS FEEDS is a port of ~/bin/media-slideshow, the 25,000-line
 * PySide6 application that has run on the box's own glass since May. That
 * program reads a local directory, decodes from a local disk, and shells
 * out to nvidia-smi and py-spy whenever it likes. None of that is available
 * here: this is a WebView on a nine-inch MediaTek tablet reaching one
 * origin over HTTP/1.1, and the origin is a single-process FastAPI app that
 * is also writing and recording a live radio show.
 *
 * So the discipline is presentation-source.js's, for the same measured
 * reason: on 2026-09-11, 38 concurrent requests to this station produced a
 * 46-SECOND MEDIA STALL on this glass. A slideshow is the worst possible
 * shape for that hazard - it wants a new picture every ten seconds, a
 * filmstrip of thumbnails, a hot-load poll and a telemetry panel - so
 * everything except the pictures themselves goes through ONE gate:
 *
 *   - a value younger than its maxAge is handed back with NO request;
 *   - two callers asking for the same route share ONE promise;
 *   - anything else queues, and the queue drains one at a time.
 *
 * THE PICTURES DO NOT GO THROUGH THE GATE, and that is deliberate rather
 * than an oversight. An <img> is fetched by the engine, not by this file,
 * and the view holds exactly two of them - the one on screen and the one
 * after it. That is the desktop app's own "single-media-in-flight" rule
 * (its docstring, line 41) and it matters more here than it does there:
 * that process has a 750 MB budget on a 124 GB box, this one was measured
 * at 148 MB free under a load average of 25.
 *
 * WHY THE ROUTES ARE NEW. /api/generations/image reads the whole file into
 * memory and answers with it - no Accept-Ranges, no small size. video-wall.js
 * already had to work around the first half of that by downloading clips
 * whole; the filmstrip would have hit the second, pulling 1.3 MB per 64
 * pixels. /api/slideshow/media has Range and `?w=`, so a thumbnail is about
 * two kilobytes and a video seeks.
 */
(function (root) {
  'use strict';

  /* The widest the picture can usefully be on THIS screen, in real device
   * pixels, rounded to a 320-pixel step so terminals of a similar size share
   * one cached copy. Capped at 1920: past that the wire cost grows and
   * nothing in this house has a bigger panel. */
  function screenWidth() {
    var css = Math.max(320, (root.screen && root.screen.width) || 1280);
    var real = css * Math.min(2, root.devicePixelRatio || 1);
    var step = Math.ceil(Math.min(1920, real) / 320) * 320;
    return Math.max(640, step);
  }


  /* How stale an answer may be before a caller's ask actually costs a
   * request. Chosen against how fast each thing can really change: the
   * folder gains a picture when a render finishes and a render on this box
   * measured 84-102s; the settings file is edited by a hand; the stack
   * readout is already cached ten seconds on the station side, so asking
   * faster than that buys nothing but a queue entry. */
  var AGES = {
    '/api/slideshow/playlist': 60000,
    '/api/slideshow/favorites': 30000,
    '/api/slideshow/state': 60000,
    '/api/slideshow/stack': 10000
  };
  var DEFAULT_AGE = 30000;

  /* This view asks about four routes. A ceiling well above that means a
   * runaway caller is refused with a sentence rather than quietly filling
   * memory. */
  var QUEUE_MOST = 10;

  var cache = {};        /* route -> {at, value} */
  var inflight = {};     /* route -> promise */
  var queue = [];
  var draining = false;
  var peak = 0;

  function ageFor(route) {
    var path = String(route || '').split('?')[0];
    return Object.prototype.hasOwnProperty.call(AGES, path)
      ? AGES[path] : DEFAULT_AGE;
  }

  /* The bridge when there is one, a bare fetch when there is not - the same
   * fallback every other view here carries, so this file also works in a
   * desktop renderer and in a plain browser during development. */
  function bridge() {
    return root.pineDesktop || null;
  }

  function rawGet(route) {
    var api = bridge();
    if (api && typeof api.get === 'function') return api.get(route);
    return fetch(route, {credentials: 'same-origin'}).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  function rawPost(route, body) {
    var api = bridge();
    if (api && typeof api.post === 'function') return api.post(route, body || {});
    return fetch(route, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  /* THE SLOT IS CLEARED BEFORE THE CALLER IS ANSWERED, and the order is the
   * whole point.
   *
   * FOUND BY A TEST, not by reading. The first version settled the caller's
   * promise and cleared `inflight` in a later `.then`, so for exactly one
   * microtask turn a FINISHED request was still recorded as in flight -
   * and anything that asked in that window was handed the finished
   * promise, bypassing its own maxAge. It made `since()` wrong: two
   * hot-load polls in the same turn produced one request and one answer,
   * so "has anything new arrived" could be answered with a stale yes.
   *
   * Settling last also means a caller that immediately asks again from its
   * own `.then` starts a real request rather than re-reading the answer it
   * was just given. */
  function drain() {
    if (draining) return;
    var job = queue.shift();
    if (!job) return;
    draining = true;
    rawGet(job.route).then(function (value) {
      cache[job.route] = {at: Date.now(), value: value};
      return {ok: true, value: value};
    }, function (err) {
      return {ok: false, err: err};
    }).then(function (outcome) {
      draining = false;
      delete inflight[job.route];
      if (outcome.ok) job.settle(outcome.value);
      else job.fail(outcome.err);
      drain();
    });
  }

  /* ONE SLOW REQUEST AT A TIME, for everything that is not a picture. */
  function ask(route, maxAge) {
    var limit = typeof maxAge === 'number' ? maxAge : ageFor(route);
    var held = cache[route];
    if (held && (Date.now() - held.at) < limit) {
      return Promise.resolve(held.value);
    }
    if (inflight[route]) return inflight[route];
    if (queue.length >= QUEUE_MOST) {
      return Promise.reject(new Error(
        'the slideshow already has ' + queue.length + ' questions waiting '
        + 'for the station; this one was not added'));
    }
    var promise = new Promise(function (settle, fail) {
      queue.push({route: route, settle: settle, fail: fail});
      if (queue.length > peak) peak = queue.length;
    });
    inflight[route] = promise;
    drain();
    return promise;
  }

  /* A write is never queued behind reads: a like or a pause is the
   * operator's hand on the glass and must not wait out a filmstrip. It does
   * invalidate what it changed, so the next read is fresh. */
  function tell(route, body, forget) {
    (forget || []).forEach(function (path) {
      Object.keys(cache).forEach(function (key) {
        if (key.indexOf(path) === 0) delete cache[key];
      });
    });
    return rawPost(route, body);
  }

  function page(options) {
    var opts = options || {};
    var parts = [];
    if (opts.limit) parts.push('limit=' + opts.limit);
    if (opts.offset) parts.push('offset=' + opts.offset);
    if (opts.kind && opts.kind !== 'all') parts.push('kind=' + opts.kind);
    if (opts.favorites) parts.push('favorites=1');
    if (opts.order) parts.push('order=' + opts.order);
    if (opts.seed) parts.push('seed=' + opts.seed);
    return ask('/api/slideshow/playlist' + (parts.length ? '?' + parts.join('&') : ''));
  }

  /* THE HOT LOAD. The desktop app watches the directory with a
   * QFileSystemWatcher and inserts a finished render AHEAD OF THE CURSOR,
   * so a picture that has just appeared is the next thing on screen. A
   * WebView cannot watch a directory, so it asks the station what is newer
   * than the newest thing it holds - one small answer, usually empty, and
   * never the whole list again. */
  function since(stamp) {
    var route = '/api/slideshow/playlist?since=' + encodeURIComponent(stamp);
    /* Deliberately un-cached: the whole question is "has anything changed
     * in the last twenty seconds", and a cached answer to that is a
     * contradiction. It still rides the one-at-a-time queue. */
    delete cache[route];
    return ask(route, 0);
  }

  root.PineSlideshowSource = {
    ask: ask,
    tell: tell,
    page: page,
    since: since,
    state: function () { return ask('/api/slideshow/state'); },
    favorites: function () { return ask('/api/slideshow/favorites'); },
    stack: function () { return ask('/api/slideshow/stack'); },

    /* Settings go to the file the desktop app itself reads - see
     * app.py's #1240 header for which file that is and when it is
     * genuinely shared. Invalidates the state read so the panel shows
     * what was actually stored, not what was sent. */
    setState: function (patch) {
      return tell('/api/slideshow/state', patch, ['/api/slideshow/state',
        '/api/slideshow/stack']);
    },

    like: function (file, on) {
      return tell('/api/slideshow/favorites', {file: file, on: on},
        ['/api/slideshow/favorites', '/api/slideshow/playlist']);
    },

    /* Out of the rotation, still on disk - the desktop trash disc's outer
     * ring. The permanent one is below it and says so. */
    aside: function (file) {
      return tell('/api/slideshow/aside/' + encodeURIComponent(file), {},
        ['/api/slideshow/playlist']);
    },

    destroy: function (file) {
      var api = bridge();
      var route = '/api/generations/image/' + encodeURIComponent(file);
      Object.keys(cache).forEach(function (key) {
        if (key.indexOf('/api/slideshow/playlist') === 0) delete cache[key];
      });
      if (api && typeof api.del === 'function') return api.del(route, {});
      return fetch(route, {method: 'DELETE', credentials: 'same-origin'})
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        });
    },

    /* The bytes doors. Built here so no caller assembles a URL by hand and
     * so the thumbnail width is the one the station actually caches. */
    url: function (file, width) {
      /* ASK FOR THE SIZE THE SCREEN CAN ACTUALLY SHOW.
       *
       * This used to hand back the bare route, which serves the original
       * render - and ComfyUI renders are big. Measured on the tablet over
       * thirty seconds of ordinary slideshow: 6.7 MB of PNG out of 10 MB of
       * total panel traffic, on a link that delivers about 400 kB/s. Single
       * files of 3.7 MB and 1.7 MB for a picture being displayed at 1340
       * CSS pixels wide.
       *
       * The station already had the answer - `?w=` on this very route, added
       * for the filmstrip - so the full-size door simply was not using it.
       *
       * ONE WIDTH PER SCREEN, ROUNDED. The route caches per width, so asking
       * for 1341 on one device and 1343 on another would fill the cache with
       * near-identical copies and hit it on neither. Rounding to a step
       * keeps every terminal of a given size sharing one cached image. */
      return '/api/slideshow/media/' + encodeURIComponent(file)
        + '?w=' + (width || screenWidth());
    },
    thumb: function (file, width) {
      return '/api/slideshow/media/' + encodeURIComponent(file)
        + '?w=' + (width || 128);
    },

    /* A number the operator can look at, rather than a claim in a comment -
     * the same reason presentation-source.js publishes its own. */
    peak: function () { return peak; },
    waiting: function () { return queue.length; },
    forget: function () { cache = {}; }
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSlideshowSource;
  }
})(typeof window !== 'undefined' ? window : globalThis);
