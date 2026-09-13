/* window.PineSfxTv - the SFX guy's television, floating over every view.
 *
 * "If the SFX guy plays an MP4 clip, I wanna see a pop up of that in a
 *  little pop up window ... And then I want it to close out like a CRT
 *  television where it just closes into a line and disappears."
 *
 * "When popping up the picture in picture display on different views, I
 *  want it to pop up similar to this where it's basically just a little
 *  window that I'm able to click and drag around in position that's able
 *  to be saved to the preferences and be retained the next time that the
 *  picture in picture pops up in the view or in any view."
 *
 * WHY IT LIVES IN THE SHELL AND NOT IN A VIEW. Every view in this window
 * is a <section class="view"> that is display:none the moment another
 * tab is chosen, and three of them are <webview>s with their own
 * documents entirely. A set built inside any one of those exists in one
 * view only - which is precisely the arrangement the operator asked
 * against. This mounts at BODY level, a sibling of <main>, so it is over
 * the Script view, the Sampler, the Agent frame, and anything added
 * later, without those views knowing it exists.
 *
 * WHY IT POLLS ITS OWN ROUTE. A video sting never goes to the satellite -
 * the Nabu has no screen - and in the ordinary arrangement here the DJs
 * talk out of the box, which is exactly when the station panel stops
 * polling the voice feed at all. /api/dj/video (#1263) is the station's
 * own small door for the clips that have a picture: same ring, same feed
 * epoch, same staleness rule, filtered to video.
 *
 * THE GEOMETRY IS THE PREFERENCE. Where the operator drags it and what
 * size they leave it at are written to localStorage on pointerup - the
 * same store the rail width and the app volume use - and read back the
 * next time the set comes on, in whatever view happens to be showing.
 * It is clamped to the window on the way in, so a box left at the edge
 * of a big monitor is still on screen on a small one.
 */
(function (root) {
  'use strict';

  var KEY = 'pineSfxTvBox';       // the preference: left, top, width, height
  var POLL_MS = 2500;
  var MIN = {w: 180, h: 120};
  var DEFAULT = {width: 420, height: 268};
  /* Longer than the .off animation in sfx-tv.css, so the last frame of the
   * collapse is seen rather than cut off by the removal. */
  var OFF_MS = 520;
  /* Past this many seconds late, the set would be coming on over whatever
   * is airing NOW - which is worse than the clip being missed. */
  var LATE = 8;

  var host = null;                 // the window, while a clip is in it
  var video = null;
  var tube = null;
  var timer = null;                // the poll
  var hold = null;                 // the "not due yet" timer
  var queue = [];
  var seen = 0;
  var busy = false;                // a poll in flight
  var showing = false;
  var base = '';
  var level = 1;
  var marks = Object.create(null);
  var mounted = false;

  function api() { return root.pineDesktop; }

  function now() { return Date.now(); }

  /* ---- the preference ------------------------------------------------ */

  function readBox() {
    var saved = null;
    try { saved = JSON.parse(root.localStorage.getItem(KEY) || 'null'); }
    catch (err) { saved = null; }
    var w = Number(saved && saved.width) || DEFAULT.width;
    var h = Number(saved && saved.height) || DEFAULT.height;
    w = Math.max(MIN.w, Math.min(w, (root.innerWidth || 1280) - 16));
    h = Math.max(MIN.h, Math.min(h, (root.innerHeight || 800) - 16));
    /* No saved position yet: the lower right, out of the way of a rail on
     * the left and a reading column in the middle. */
    var left = saved && Number.isFinite(Number(saved.left))
      ? Number(saved.left) : (root.innerWidth || 1280) - w - 32;
    var top = saved && Number.isFinite(Number(saved.top))
      ? Number(saved.top) : (root.innerHeight || 800) - h - 72;
    /* Clamped, always: a box left at the edge of a big monitor has to
     * still be reachable on a small one, and a title bar off the top of
     * the screen is a window that can never be dragged back. */
    left = Math.max(0, Math.min(left, (root.innerWidth || 1280) - 80));
    top = Math.max(0, Math.min(top, (root.innerHeight || 800) - 40));
    return {left: left, top: top, width: w, height: h};
  }

  function writeBox() {
    if (!host) return;
    var box = {left: host.offsetLeft, top: host.offsetTop,
               width: host.offsetWidth, height: host.offsetHeight};
    if (box.width < MIN.w || box.height < MIN.h) return;
    try { root.localStorage.setItem(KEY, JSON.stringify(box)); }
    catch (err) { /* a locked store is not a reason to stop the show */ }
  }

  /* ---- the frame ----------------------------------------------------- */

  function drag(node, handle) {
    handle.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      if (event.target.closest('button')) return;
      var from = {x: event.clientX, y: event.clientY,
                  left: node.offsetLeft, top: node.offsetTop};
      try { handle.setPointerCapture(event.pointerId); } catch (err) {}
      var move = function (e) {
        /* Clamped so the title bar can never leave the window: a set
         * dragged off the top edge is one nothing can bring back. */
        node.style.left = Math.max(0, Math.min((root.innerWidth || 0) - 60,
          from.left + e.clientX - from.x)) + 'px';
        node.style.top = Math.max(0, Math.min((root.innerHeight || 0) - 30,
          from.top + e.clientY - from.y)) + 'px';
      };
      var drop = function () {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', drop);
        handle.removeEventListener('pointercancel', drop);
        writeBox();                  // the preference is written on release
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', drop);
      handle.addEventListener('pointercancel', drop);
      event.preventDefault();
    });
  }

  function grip(node) {
    var handle = document.createElement('div');
    handle.className = 'sfx-tv-grip';
    handle.title = 'Drag to resize';
    handle.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      var from = {x: event.clientX, y: event.clientY,
                  w: node.offsetWidth, h: node.offsetHeight};
      try { handle.setPointerCapture(event.pointerId); } catch (err) {}
      var move = function (e) {
        node.style.width = Math.max(MIN.w, Math.min(
          (root.innerWidth || 0) - node.offsetLeft - 4,
          from.w + e.clientX - from.x)) + 'px';
        node.style.height = Math.max(MIN.h, Math.min(
          (root.innerHeight || 0) - node.offsetTop - 4,
          from.h + e.clientY - from.y)) + 'px';
      };
      var drop = function () {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', drop);
        handle.removeEventListener('pointercancel', drop);
        writeBox();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', drop);
      handle.addEventListener('pointercancel', drop);
      event.preventDefault();
      event.stopPropagation();
    });
    node.appendChild(handle);
  }

  function build(name) {
    var box = readBox();
    host = document.createElement('div');
    host.className = 'sfx-tv';
    host.id = 'sfxTv';
    host.style.left = Math.round(box.left) + 'px';
    host.style.top = Math.round(box.top) + 'px';
    host.style.width = Math.round(box.width) + 'px';
    host.style.height = Math.round(box.height) + 'px';

    var head = document.createElement('div');
    head.className = 'sfx-tv-head';
    var title = document.createElement('b');
    title.textContent = String(name || 'SFX');
    var shut = document.createElement('button');
    shut.type = 'button';
    shut.textContent = '✕';
    shut.title = 'Close';
    shut.setAttribute('aria-label', 'Close');
    head.appendChild(title);
    head.appendChild(shut);

    var screen = document.createElement('div');
    screen.className = 'sfx-tv-screen';
    tube = document.createElement('div');
    tube.className = 'sfx-tv-tube';
    video = document.createElement('video');
    video.playsInline = true;
    video.preload = 'auto';
    video.controls = false;
    /* #789/#981: the shell owns live element volume, and the booth monitor
     * switch governs anything tagged pine-live. A sting that skipped the
     * tag would be the one sound in this window nobody could turn down. */
    video.dataset.pineLive = 'voice';
    video.volume = level;
    tube.appendChild(video);
    var glass = document.createElement('div');
    glass.className = 'sfx-tv-glass';
    var vignette = document.createElement('div');
    vignette.className = 'sfx-tv-vignette';
    var flash = document.createElement('div');
    flash.className = 'sfx-tv-flash';
    screen.appendChild(tube);
    screen.appendChild(glass);
    screen.appendChild(vignette);
    screen.appendChild(flash);

    host.appendChild(head);
    host.appendChild(screen);
    grip(host);
    /* A sibling of <main>, never inside a view: that is the whole reason
     * it survives a tab change. */
    document.body.appendChild(host);
    drag(host, head);
    return {shut: shut, flash: flash};
  }

  /* `mine` is the <video> the caller believes is on screen. Every timer
   * below outlives the clip that armed it - the watchdog by twelve
   * seconds - so a teardown that trusted the module's own reference
   * would either throw on a set already gone or tear down the NEXT
   * clip's set on behalf of a dead one. Measured as a TypeError every
   * twelve seconds after the first clip, in a renderer with no console
   * anybody was reading. */
  function teardown(mine) {
    if (mine && video && video !== mine) return;   // a newer set owns the screen
    var going = mine || video;
    /* Removing a <video> from the document does NOT stop it, so the src
     * goes first and the node second. */
    try { if (going) { going.pause(); going.removeAttribute('src'); going.load(); } }
    catch (err) {}
    try { if (host && host.parentNode) host.parentNode.removeChild(host); }
    catch (err) {}
    host = video = tube = null;
    showing = false;
    setTimeout(next, 120);
  }

  /* ---- one clip ------------------------------------------------------ */

  function play(clip) {
    var parts = build(clip.sting || clip.text || 'SFX');
    /* Held locally, because every handler and timer below can fire after
     * the module's own references have moved on. */
    var screen = video;
    var glass = tube;
    var done = false;
    var finish = function () {
      if (done) return;
      done = true;
      writeBox();                    // wherever it ended up is the preference
      try {
        glass.classList.remove('on');
        void glass.offsetWidth;      // restart the animation, never resume it
        glass.classList.add('off');
      } catch (err) {}
      setTimeout(function () { teardown(screen); }, OFF_MS);
    };
    var close = function () {
      /* The operator's own ✕ wants the picture gone now, not in half a
       * second - but the geometry is still worth keeping. */
      if (done) return;
      done = true;
      writeBox();
      teardown(screen);
    };

    parts.shut.addEventListener('click', close);
    glass.classList.add('on');       // dot -> line -> picture
    parts.flash.classList.add('pop');

    screen.addEventListener('ended', finish);
    screen.addEventListener('error', finish);
    screen.src = base.replace(/\/+$/, '') + String(clip.url || '');
    screen.volume = level;
    /* THE WATCHDOG. `error` does not fire for every way a clip can fail
     * to begin - a stalled range request, a container this build cannot
     * decode, a zero-byte download off the drop share - and a set left on
     * with a black tube holds every clip behind it. */
    setTimeout(function () {
      if (done || video !== screen) return;
      if (screen.paused || !Number(screen.currentTime)) finish();
    }, 12000);
    var started = screen.play();
    if (started && started.catch) {
      started.catch(function () {
        /* The picture is still worth having without the sound. */
        try { screen.muted = true; screen.play().catch(function () {}); }
        catch (err) { finish(); }
      });
    }
  }

  function next() {
    if (showing || !mounted) return;
    var clip = queue.shift();
    while (clip && (now() - Number(clip.at || now())) / 1000 > LATE) {
      clip = queue.shift();
    }
    if (!clip) return;
    var wait = Number(clip.at || 0) - now();
    if (wait > 250) {
      /* Early is not late: the station stamps an air moment a lead ahead
       * of delivery, and a picture that jumps the gun lands over the line
       * it was meant to punctuate. */
      queue.unshift(clip);
      if (hold) clearTimeout(hold);
      hold = setTimeout(function () { hold = null; next(); }, wait);
      return;
    }
    showing = true;
    try { play(clip); }
    catch (err) { showing = false; }
  }

  function offer(clip) {
    if (!clip || !clip.url) return;
    var mark = String(clip.ts || '') + '|' + String(clip.url);
    if (marks[mark]) return;
    marks[mark] = 1;
    queue.push(clip);
    if (queue.length > 4) queue.splice(0, queue.length - 4);
    next();
  }

  async function poll() {
    if (busy || !api() || !api().get) return;
    busy = true;
    try {
      var got = await api().get('/api/dj/video?since=' + seen);
      var serverMs = Number((got && got.server_ms) || now());
      ((got && got.clips) || []).forEach(function (clip) {
        seen = Math.max(seen, Number(clip.ts || 0));
        /* The station's clock, carried onto this one - the box and this
         * machine have no reason to agree. */
        clip.at = now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
        offer(clip);
      });
    } catch (err) { /* the show goes on */
    } finally { busy = false; }
  }

  root.PineSfxTv = {
    mount: function (opts) {
      if (mounted) return;
      mounted = true;
      base = String((opts && opts.baseUrl) || '');
      poll();
      timer = setInterval(poll, POLL_MS);
      /* A window that shrank under a set left near the edge would strand
       * it off screen; the clamp is the same one the opener uses. */
      root.addEventListener('resize', function () {
        if (!host) return;
        host.style.left = Math.max(0, Math.min((root.innerWidth || 0) - 60,
          host.offsetLeft)) + 'px';
        host.style.top = Math.max(0, Math.min((root.innerHeight || 0) - 30,
          host.offsetTop)) + 'px';
      });
    },
    rebase: function (url) { base = String(url || ''); },
    /* The shell's master volume times the booth's share, handed over by
     * applyAppVolume - this window has no mixer of its own. */
    level: function (value) {
      level = Math.max(0, Math.min(1, Number(value)));
      if (video) {
        video.volume = level;
        if (level > 0 && video.muted) video.muted = false;
      }
    },
    stop: function () {
      if (timer) clearInterval(timer);
      if (hold) clearTimeout(hold);
      timer = hold = null;
      mounted = false;
      teardown();
    },
    /* Numbers the operator can look at rather than a claim in a comment. */
    box: readBox,
    waiting: function () { return queue.length; },
    on: function () { return showing; },
    offer: offer
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSfxTv;
  }
})(typeof window !== 'undefined' ? window : globalThis);
