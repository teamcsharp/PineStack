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

  var playing = null;              // #1306b: the clip in the tube now
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

    /* #1306b: THE PAD ICON, top right of the PICTURE.
     * "an icon to the top right of the video of a small box that if I
     *  tap it, it basically assigns that video that's playing to the
     *  sampler on a available pad." */
    var pad = document.createElement('button');
    pad.type = 'button';
    pad.className = 'sfx-tv-pad';
    pad.title = 'Send this clip to a sampler pad';
    pad.setAttribute('aria-label', 'Send to a sampler pad');
    pad.innerHTML = (typeof root.pineIcon === 'function'
      ? root.pineIcon('c:box', 'Send to a sampler pad') : '') || '\u25a3';
    pad.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var was = pad.getAttribute('data-say') || '';
      toPad(playing, function (text) {
        pad.setAttribute('data-say', String(text || was));
        pad.classList.add('said');
        setTimeout(function () {
          if (pad.isConnected) { pad.classList.remove('said'); }
        }, 2400);
      });
    });
    screen.appendChild(pad);

    /* #1306b: A HOLD ON THE PICTURE opens the sheet. Told apart from a
     * drag the same way the script strip does it - time AND movement -
     * because this window is draggable by its head and the screen is
     * the one part of it that is not. */
    var held = null, heldTimer = 0;
    screen.addEventListener('pointerdown', function (ev) {
      if (ev.target.closest('button')) return;
      held = {x: ev.clientX, y: ev.clientY};
      if (heldTimer) clearTimeout(heldTimer);
      heldTimer = setTimeout(function () {
        heldTimer = 0;
        if (playing) sheet(playing);
      }, 500);
    });
    screen.addEventListener('pointermove', function (ev) {
      if (!held) return;
      if (Math.abs(ev.clientX - held.x) > 8
          || Math.abs(ev.clientY - held.y) > 8) {
        if (heldTimer) { clearTimeout(heldTimer); heldTimer = 0; }
        held = null;
      }
    });
    ['pointerup', 'pointercancel'].forEach(function (name) {
      screen.addEventListener(name, function () {
        if (heldTimer) { clearTimeout(heldTimer); heldTimer = 0; }
        held = null;
      });
    });

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

  /* #1306b: down NOW, for a cut. teardown() is the polite version and
   * schedules next(); this one leaves the queue alone because its
   * caller is about to put something in the tube itself. */
  function teardownNow() {
    var going = video;
    try { if (going) { going.pause(); going.removeAttribute('src'); going.load(); } }
    catch (err) {}
    try { if (host && host.parentNode) host.parentNode.removeChild(host); }
    catch (err) {}
    host = video = tube = null;
    showing = false;
  }

  /* ---- one clip ------------------------------------------------------ */

  function play(clip) {
    playing = clip;                                        /* #1306b */
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

  /* #1306b: THE FOUR THINGS THE OPERATOR WANTS TO DO TO A CLIP.
   *
   * Every one of these already has a door and the clip already
   * carries the handle they want - its sfx id. Nothing here invents
   * an endpoint.
   */
  function clipId(clip) {
    if (!clip) return '';
    if (clip.id) return String(clip.id);
    /* Older rings carry only the url: /sfx/<id>?t=<sig> */
    var m = /\/sfx\/([^?#/]+)/.exec(String(clip.url || ''));
    return m ? m[1] : '';
  }

  function post(path, body) {
    var bridge = api();
    if (!bridge || !bridge.post) return Promise.reject(new Error('no bridge'));
    return bridge.post(path, body || {});
  }

  function weigh(clip, up, say) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    /* The station's own draw weight - the same dial the SFX desk
       writes - so a thumb here really does change how often it comes
       round. 0.05 is the floor the draw already reads as "marked all
       the way down". */
    post('/api/sfx/weight', {id: id, weight: up ? 2 : 0.05}).then(
      function () { say(up ? 'more often' : 'less often'); },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  function scrap(clip, say, done) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    post('/api/sfx/delete', {id: id}).then(
      function () { say('deleted'); if (done) done(); },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  function toPad(clip, say) {
    var id = clipId(clip);
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') {
      say('the sampler is not on this page'); return;
    }
    var row = {id: id, url: String(clip.url || ''), sfx: true,
               text: String(clip.sting || ''), who: 'the board'};
    say('taking it...');
    Promise.resolve(sampler.grab(row)).then(function (got) {
      say(got && got.ok ? 'on a pad' : ((got && got.why) || 'it refused'));
    }, function (err) {
      say(String((err && err.message) || err).slice(0, 40));
    });
  }

  function inspect(clip, say) {
    var id = clipId(clip);
    var bridge = api();
    if (!id || !bridge || !bridge.get) { say('no id on this clip'); return; }
    bridge.get('/api/sfx/info?id=' + encodeURIComponent(id)).then(
      function (got) {
        var bits = [];
        if (got && got.name) bits.push(got.name);
        if (got && got.seconds) bits.push(Number(got.seconds).toFixed(1) + 's');
        if (got && got.folder) bits.push(got.folder);
        if (got && got.plays !== undefined) bits.push(got.plays + ' plays');
        if (got && got.weight !== undefined) bits.push('weight ' + got.weight);
        say(bits.join('  -  ') || 'nothing known about it');
      },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  /* The sheet itself: a hold on the picture opens it. */
  function sheet(clip) {
    if (!host) return;
    var old = host.querySelector('.sfx-tv-sheet');
    if (old) { old.remove(); return; }        /* a second hold shuts it */
    var wrap = document.createElement('div');
    wrap.className = 'sfx-tv-sheet';
    var name = document.createElement('b');
    name.textContent = String(clip.sting || clip.text || 'this clip');
    var note = document.createElement('i');
    note.className = 'sfx-tv-note';
    note.textContent = '';
    var say = function (text) { note.textContent = String(text || ''); };
    var rowA = document.createElement('div');
    rowA.className = 'sfx-tv-sheetrow';
    var rowB = document.createElement('div');
    rowB.className = 'sfx-tv-sheetrow';

    function button(into, label, title, go) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.title = title;
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        go();
      });
      into.appendChild(b);
      return b;
    }

    button(rowA, 'Inspect', 'What the station knows about this clip',
           function () { inspect(clip, say); });
    button(rowA, '\u25b2 More', 'Play it more often',
           function () { weigh(clip, true, say); });
    button(rowA, '\u25bc Less', 'Play it less often',
           function () { weigh(clip, false, say); });
    button(rowB, 'Send to a pad', 'Put it on the first free sampler pad',
           function () { toPad(clip, say); });
    var kill = button(rowB, 'Delete', 'Remove the file permanently',
      function () {
        /* The one action here that cannot be taken back, so it asks. */
        if (kill.dataset.sure !== '1') {
          kill.dataset.sure = '1';
          kill.textContent = 'Delete for good?';
          setTimeout(function () {
            if (!kill.isConnected) return;
            kill.dataset.sure = '';
            kill.textContent = 'Delete';
          }, 3000);
          return;
        }
        scrap(clip, say, function () { wrap.remove(); });
      });
    kill.className = 'bad';
    var shut = button(rowB, 'Close', 'Put this away',
                      function () { wrap.remove(); });
    shut.className = 'quiet';

    wrap.appendChild(name);
    wrap.appendChild(rowA);
    wrap.appendChild(rowB);
    wrap.appendChild(note);
    wrap.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    host.appendChild(wrap);
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
    offer: offer,
    /* #1306b: CUT TO THIS ONE, NOW.
     *
     * offer() queues and next() refuses while `showing`, which is
     * right for the station's own stings - two pictures at once is
     * the fault there. It is exactly wrong for the operator's thumb:
     * a second tap means "not that one, this one". So rapid fire
     * reads as cycling instead of as a queue draining, and the
     * station's own road is untouched.
     *
     * The mark is set the way offer() sets it, so the poll that later
     * sees this same clip in the ring does not play it a second
     * time. */
    cut: function (clip) {
      if (!clip || !clip.url || !mounted) return false;
      try {
        marks[String(clip.ts || '') + '|' + String(clip.url)] = 1;
      } catch (err) { /* the play below still stands */ }
      queue.length = 0;
      if (hold) { clearTimeout(hold); hold = null; }
      /* Down without waiting out the CRT collapse - the next picture
         is the answer to the tap, not the animation. */
      try { teardownNow(); } catch (err) { /* nothing was up */ }
      showing = true;
      try { play(clip); return true; }
      catch (err) { showing = false; return false; }
    },
    playing: function () { return playing; }
  };

  /* #1306b: AND IT COMES ON BY ITSELF WHERE NOBODY MOUNTS IT.
   *
   * The desktop shell mounts this explicitly, with a baseUrl, because
   * its renderer is not served from the station. The tablet's view
   * bundle has no such step - every view there is injected and left to
   * find its own feet - so the set existed on one surface only, while
   * the operator taps the video button on the other.
   *
   * Deferred rather than immediate: the shell's own mount runs during
   * its startup and `if (mounted) return` makes this a no-op there.
   * Where nothing has claimed it after a few seconds, this is the
   * tablet, the page is served from the station, and a relative base
   * is the right one.
   */
  try {
    if (root.document && root.setTimeout) {
      root.setTimeout(function () {
        try {
          if (!mounted && /^https?:$/.test(String(root.location.protocol))) {
            root.PineSfxTv.mount({baseUrl: ''});
          }
        } catch (err) { /* no set is better than a broken view */ }
      }, 3000);
    }
  } catch (err) { /* not a browser */ }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSfxTv;
  }
})(typeof window !== 'undefined' ? window : globalThis);
