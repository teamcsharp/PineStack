/* WHAT IS HAPPENING, ON THE THING IT IS HAPPENING TO.
 *
 * "When downloading anything, when grabbing anything, when downloading it
 * to the sampler pad or caching anything, I want to see a loading bar on
 * that element illustrating what's happening. I always want to see
 * animations for transitional actions that are happening."
 *
 * ON THE ELEMENT, NOT IN A CORNER. A spinner in the corner of the screen
 * tells the operator that SOMETHING is busy; a bar across the row he just
 * pressed tells him THAT is busy. On a tablet where a cut can take ninety
 * seconds - the sampler's own ceiling, because the station is writing and
 * recording audio and a cut queues behind that work - the difference is
 * whether he presses it again.
 *
 * TWO KINDS OF BAR, AND THE CHOICE IS NOT COSMETIC:
 *
 *   MEASURED     a real fraction, when the work reports one - bytes of a
 *                clip against its Content-Length. It fills as the thing
 *                actually arrives.
 *   UNMEASURED   a travelling sweep, when nothing can be counted. It says
 *                "working" and refuses to imply progress it does not have.
 *
 * A bar that crawls to 90% and sits there is a lie told slowly, and this
 * station has enough of those. So `busy.run()` shows the sweep unless it
 * is given something real to count.
 *
 * IT ALWAYS ENDS. Every bar carries its own ceiling: if the work never
 * settles the bar says so and goes, rather than leaving a row that looks
 * permanently mid-flight. A progress indicator that can outlive its work
 * is worse than none.
 */
(function (root) {
  'use strict';

  var CEILING_MS = 120000;   /* above the sampler's own 90 s fetch ceiling */

  function make(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  /**
   * Put a bar on an element for as long as a piece of work runs.
   *
   * @param host  the element the operator pressed
   * @param work  a promise, or a function given a `tick` it may call with
   *              a 0..1 fraction to turn the sweep into a real measure
   * @param label optional words under the bar
   * @return the work's own promise, so callers chain as they already did
   */
  function run(host, work, label) {
    if (!host) {
      return typeof work === 'function' ? work(function () {}) : work;
    }
    var bar = attach(host, label);
    var done = function (ok) {
      bar.finish(ok);
    };

    var promise;
    try {
      promise = (typeof work === 'function') ? work(bar.tick) : work;
    } catch (err) {
      done(false);
      return Promise.reject(err);
    }
    if (!promise || typeof promise.then !== 'function') {
      done(true);
      return Promise.resolve(promise);
    }
    return promise.then(function (value) {
      done(true);
      return value;
    }, function (err) {
      done(false);
      throw err;
    });
  }

  /** The bar itself, for callers that drive it by hand. */
  function attach(host, label) {
    /* One bar per element: pressing twice must not stack two. */
    var old = host.querySelector(':scope > .pb-busy');
    if (old) old.remove();

    var wrap = make('div', 'pb-busy');
    var lane = make('div', 'pb-busy-lane');
    var fill = make('i', 'pb-busy-fill');
    lane.appendChild(fill);
    wrap.appendChild(lane);
    if (label) {
      var says = make('span', 'pb-busy-say');
      says.textContent = String(label);
      wrap.appendChild(says);
    }

    /* The host has to be a positioning context or the bar lands on the
     * page. Only set when it is not already one, so nothing that manages
     * its own layout is disturbed. */
    var was = getComputedStyle(host).position;
    if (was === 'static') {
      host.style.position = 'relative';
      wrap.dataset.moved = '1';
    }
    host.appendChild(wrap);
    host.classList.add('pb-busy-on');

    var ceiling = setTimeout(function () {
      say('this is taking longer than it should');
      finish(false);
    }, CEILING_MS);

    function say(text) {
      var node = wrap.querySelector('.pb-busy-say');
      if (!node) {
        node = make('span', 'pb-busy-say');
        wrap.appendChild(node);
      }
      node.textContent = String(text);
    }

    /* 0..1 turns the sweep into a real measure. Anything outside that -
     * or nothing at all - leaves it sweeping, which is the honest state
     * when the work cannot be counted. */
    function tick(fraction, words) {
      var f = Number(fraction);
      if (isFinite(f) && f >= 0 && f <= 1) {
        wrap.classList.add('measured');
        fill.style.width = (f * 100).toFixed(1) + '%';
      }
      if (words) say(words);
    }

    function finish(ok) {
      clearTimeout(ceiling);
      wrap.classList.add(ok === false ? 'failed' : 'done');
      if (ok !== false) {
        wrap.classList.add('measured');
        fill.style.width = '100%';
      }
      setTimeout(function () {
        wrap.remove();
        host.classList.remove('pb-busy-on');
        if (wrap.dataset.moved) host.style.position = '';
      }, ok === false ? 2600 : 420);
    }

    return {element: wrap, tick: tick, say: say, finish: finish};
  }

  /**
   * Fetch bytes with a real measure where the server declares a length.
   *
   * This is what makes a download's bar honest rather than decorative: the
   * response is read in chunks against Content-Length. Where the station
   * does not declare one - and several of its media routes do not - it
   * falls back to the sweep rather than inventing a denominator.
   */
  function fetchWithBar(host, url, options, label) {
    return run(host, function (tick) {
      return fetch(url, options || {}).then(function (res) {
        if (!res.ok) throw new Error('the station said ' + res.status);
        var total = Number(res.headers.get('Content-Length') || 0);
        if (!total || !res.body || !res.body.getReader) {
          return res.blob();
        }
        var reader = res.body.getReader();
        var chunks = [];
        var got = 0;
        return (function pull() {
          return reader.read().then(function (step) {
            if (step.done) return new Blob(chunks);
            chunks.push(step.value);
            got += step.value.length;
            tick(got / total,
              Math.round(got / 1024) + ' of ' + Math.round(total / 1024) + ' kB');
            return pull();
          });
        })();
      });
    }, label);
  }

  var api = {run: run, attach: attach, fetchWithBar: fetchWithBar};
  root.PineBusy = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
