/* [tune-background] The living background, on the public listener page.
 *
 * "make the background of the page the active background set in pineAgent
 *  via pinePip. I want it behind all the elements as the background."
 * "whenever it's cycling back and forth [the DJ photo], I want it to show
 *  the same effect that's used for the background of the pine pip, but
 *  chosen randomly." (operator, 2026-10-07)
 *
 * Two uses of the same bundle, both reusing PineViz exactly as Pine PiP
 * does (desktop/renderer/pine-pip.js) - the same /vendor/pineviz.bundle.js,
 * the same Three.js, the same hand-tuned "pinepip" palette:
 *
 *   #pbBg        a full-page, fixed, z-index:-1 host behind every element
 *                on this page, showing whichever of the eleven modes the
 *                operator has chosen in Pine PiP right now. The mode
 *                itself lives on the OTHER side of Electron's own
 *                localStorage, invisible to a browser on another device -
 *                so this polls the one field of Pine PiP's settings a
 *                listener is allowed to read, GET
 *                /api/system3/public/background (app.py, [pinepip-bg]).
 *
 *   gallery       the DJ photo box (#galleryStage/#galleryImage) already
 *   flourish      cycles its picture every five seconds (renderGallery(),
 *                 same file) with a plain src swap. This page cannot reach
 *                 that function's own closures, so it watches the <img>'s
 *                 src attribute instead: every time it changes AND no
 *                 video is on the stage (class "tv" - tvHide()/tvShow()
 *                 own that), a second PineViz instance plays one mode,
 *                 picked at random, over the box for under a second before
 *                 the new picture shows through.
 *
 * Deferred and last, and entirely best-effort: a listener with no WebGL,
 * or a vendor bundle not yet installed on this host, sees exactly what
 * the page looked like before this file existed - the flat colour already
 * in the stylesheet, and a plain cut between pictures. */
(function () {
  'use strict';
  if (window.PineTuneBackground) return;

  function pageVar(name) {
    try { return (0, eval)(name); } catch (e) { return undefined; }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.onload = function () { resolve(); };
      el.onerror = function () { reject(new Error('could not load ' + src)); };
      document.head.appendChild(el);
    });
  }
  function three() {
    if (window.THREE) return Promise.resolve(window.THREE);
    return loadScript('/vendor/three.min.js').then(function () { return window.THREE; });
  }
  function pineViz() {
    if (window.PineViz && window.PineViz.mount) return Promise.resolve(window.PineViz);
    /* [viz-eager] a ten-minute key, same as pine-pip.js: a fixed bundle
       reaches a listener at its next reload, never mid-visit. */
    return loadScript('/vendor/pineviz.bundle.js?v=' + Math.floor(Date.now() / 600000))
      .then(function () { return window.PineViz; });
  }
  function palette(P) {
    /* [viz-look] the exact reference palette pine-pip.js registers - the
       visuals are not coloured by this page's own theme. */
    P.PALETTES.pinepip = {name: 'Pine PiP', bg: '#03061a', bg2: '#0a1c4d', primary: '#2b7bff',
      secondary: '#8a4dff', accent: '#3de1ff', glow: '#6f8cff', ink: '#eaf2ff'};
    return 'pinepip';
  }

  function ask(path) {
    var api = window.api;
    if (typeof api === 'function') return api(path);
    var key = pageVar('KEY'), guest = pageVar('GUEST');
    var url = path + (path.indexOf('?') >= 0 ? '&' : '?') + 't=' + encodeURIComponent(typeof key === 'string' ? key : '');
    var opts = {};
    if (guest === false && typeof key === 'string' && key) { opts = {headers: {Authorization: 'Bearer ' + key}}; url = path; }
    return fetch(url, opts).then(function (r) { return r.json(); });
  }

  /* ---- the full-page background, mirroring Pine PiP's own ------------------ */
  var bgViz = null, bgMode = '';
  function mountBg() {
    var host = document.getElementById('pbBg');
    if (!host) return;
    Promise.all([three(), pineViz()]).then(function (got) {
      var P = got[1];
      bgViz = P.mount(host, {provider: new P.ExternalProvider(), palette: palette(P),
        quality: 'medium', keys: false, click: false, transition: 'crossfade'});
      pollBgMode();
      setInterval(pollBgMode, 20000);
    }).catch(function () { /* the flat colour already in the stylesheet stands in */ });
  }
  function pollBgMode() {
    ask('/api/system3/public/background').then(function (got) {
      var mode = String((got && got.mode) || '');
      if (!bgViz || !mode || mode === bgMode) return;
      bgMode = mode;
      try { bgViz.set(mode); } catch (e) { /* an id Pine PiP knows that this bundle does not (yet) */ }
    }, function () { /* the next poll tries again */ });
  }

  /* ---- the DJ photo cycle's own flourish, chosen fresh each time ------------ */
  var flourishViz = null, flourishHost = null, flourishLoading = null, flourishTimer = 0;
  function flourishReady() {
    if (flourishViz) return Promise.resolve(flourishViz);
    if (flourishLoading) return flourishLoading;
    var stage = document.getElementById('galleryStage');
    if (!stage) return Promise.resolve(null);
    flourishHost = document.createElement('div');
    flourishHost.className = 'tune-bg-flourish';
    stage.appendChild(flourishHost);
    flourishLoading = Promise.all([three(), pineViz()]).then(function (got) {
      var P = got[1];
      flourishViz = P.mount(flourishHost, {provider: new P.ExternalProvider(), palette: palette(P),
        quality: 'low', keys: false, click: false, transition: 'crossfade'});
      flourishLoading = null;
      return flourishViz;
    }, function () { flourishLoading = null; return null; });
    return flourishLoading;
  }
  function playFlourish() {
    var stage = document.getElementById('galleryStage');
    if (!stage || stage.classList.contains('tv')) return;   /* a video owns the box: leave it alone */
    flourishReady().then(function (viz) {
      if (!viz || !flourishHost) return;
      var modes = viz.modes || [];
      if (modes.length) { try { viz.set(modes[Math.floor(Math.random() * modes.length)].id); } catch (e) {} }
      clearTimeout(flourishTimer);
      flourishHost.classList.add('on');
      flourishTimer = setTimeout(function () { flourishHost.classList.remove('on'); }, 700);
    });
  }
  function watchGallery() {
    var image = document.getElementById('galleryImage');
    if (!image || typeof MutationObserver !== 'function') return;
    var seen = image.getAttribute('src') || '';
    new MutationObserver(function () {
      var next = image.getAttribute('src') || '';
      if (next === seen || !next) return;
      seen = next;
      playFlourish();
    }).observe(image, {attributes: true, attributeFilter: ['src']});
  }

  function style() {
    var s = document.createElement('style');
    s.textContent = [
      '#pbBg{position:fixed;inset:0;z-index:-1;pointer-events:none;background:#04060b}',
      '.tune-bg-flourish{position:absolute;inset:0;z-index:5;opacity:0;pointer-events:none;',
      'transition:opacity .35s ease;border-radius:inherit;overflow:hidden}',
      '.tune-bg-flourish.on{opacity:1}',
      'body.car .tune-bg-flourish{display:none}'
    ].join('\n');
    document.head.appendChild(s);
  }

  function start() {
    style();
    mountBg();
    watchGallery();
  }

  window.PineTuneBackground = {mode: function () { return bgMode; }};

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
