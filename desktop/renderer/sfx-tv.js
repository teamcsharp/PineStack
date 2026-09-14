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
    /* #1312: one set at a time, always. A stray from an earlier cut
       would otherwise sit here holding a connection for ever. */
    try {
      var old = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < old.length; i += 1) {
        var v = old[i].querySelector('video');
        try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
        catch (e2) { /* already gone */ }
        if (old[i].parentNode) old[i].parentNode.removeChild(old[i]);
      }
    } catch (err) { /* nothing to sweep */ }
    var box = readBox();
    host = document.createElement('div');
    /* #1308b: `waiting` until the first frame - see play(). */
    host.className = 'sfx-tv waiting';
    host.id = 'sfxTv';
    host.style.left = Math.round(box.left) + 'px';
    host.style.top = Math.round(box.top) + 'px';
    host.style.width = Math.round(box.width) + 'px';
    host.style.height = Math.round(box.height) + 'px';
    /* #1306e/#1322: HIGH ENOUGH TO BE SEEN, ON EVERY SURFACE.
     *
     * The stylesheet puts the set at 900. On the kiosk that buried it
     * outright - every injected view floats at z-index 2147483000 - so
     * the set was built, playing and completely invisible. Measured on
     * the tablet: the set on screen at 702,350 with elementFromPoint at
     * its own centre returning `sp-el sp-character`.
     *
     * #1306e lifted the KIOSK only, reasoning that 900 was right in the
     * desktop shell because that shell's top chrome sits at 1000. That
     * reasoning has not held. The shell now carries the same high bands
     * the kiosk does - view-chrome at 2147483200, the hold sheets at
     * 2147483046, the trace console at 2147483004, the SC pop-up at
     * 2147483010, the panel's own 3JS windows at 2147483020 - and the
     * Agent tab is a <webview> with a compositing layer of its own. A
     * set at 900 behind any of those is #1306e's fault again, on the
     * other surface, with nothing on screen to say so.
     *
     * So it climbs on BOTH, and stays UNDER the things that are meant
     * to cover it: the sampler's overlays (2147483030+), the hold
     * sheets (2147483046), the lock screen (2147483050) and the boot
     * splash (2147483100). A locked tablet must never be showing a
     * video through the lock.
     *
     * The stylesheet's 900 is now only the fallback for a surface where
     * an inline style is refused. */
    try {
      host.style.zIndex = '2147483020';
    } catch (err) { /* the stylesheet's own 900 stands */ }

    /* #1309b: NO CHROME. "The video pop-up needs to be just a video.
     * No wasted space, no elements around it... I just want it to pop
     * up as just a video box. Just a video itself."
     *
     * So there is no title bar and no close button. The set closes
     * itself when the clip ends, and the hold sheet carries a Close
     * for a clip somebody wants gone early. `shut` is still handed
     * back so play()'s own wiring is unchanged - it is simply a
     * button nothing ever shows. */
    var shut = document.createElement('button');
    shut.type = 'button';
    shut.hidden = true;

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

    host.appendChild(screen);
    grip(host);
    /* A sibling of <main>, never inside a view: that is the whole reason
     * it survives a tab change. */
    document.body.appendChild(host);
    /* #1309b: the head WAS the drag handle, so the window itself is
       now the handle. drag() already ignores a pointerdown on a
       button, and the hold that opens the sheet cancels itself the
       moment the pointer wanders - so a small press opens the sheet
       and a real drag moves the set. */
    drag(host, host);
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
    /* #1312: and anything an earlier tangle left attached. */
    try {
      var stray = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < stray.length; i += 1) {
        var v = stray[i].querySelector('video');
        try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
        catch (e2) { /* already gone */ }
        if (stray[i].parentNode) stray[i].parentNode.removeChild(stray[i]);
      }
    } catch (err) { /* nothing stray */ }
    host = video = tube = null;
    showing = false;
    setTimeout(next, 120);
  }

  /* #1306b: down NOW, for a cut. teardown() is the polite version and
   * schedules next(); this one leaves the queue alone because its
   * caller is about to put something in the tube itself. */
  /* #1312: EVERY SET IN THE DOCUMENT, NOT THE ONE WE THINK IS OURS.
   *
   * This released `video` and `host` - the module's own references -
   * which is precisely the mistake teardown(mine) was written to
   * avoid, and under rapid cutting it orphans sets: cut() tears down,
   * play() installs new references, and a host from a moment ago is
   * left ATTACHED with a <video> still in NETWORK_LOADING.
   *
   * Each orphan holds an HTTP connection open. A WebView allows about
   * six per host, and this page already spends several on the music
   * player and the voice elements - so after a few taps there were
   * none left and EVERY request hung. Measured on the tablet: two
   * orphaned videos at net=2 ready=0, and from inside the page a
   * fetch of /api/pulse never returning, while the same URL answered
   * the desk in 0.02s. That is the whole of "I tap the icon and no
   * video pops up": the picture could not be fetched because the
   * pictures before it had never let go.
   *
   * Sweeping the document by class cannot orphan anything, however
   * the references got tangled. Removing a <video> does not stop it,
   * so the src goes first and the node second - #1147's rule. */
  function teardownNow() {
    var all = document.querySelectorAll('.sfx-tv');
    for (var i = 0; i < all.length; i += 1) {
      var v = all[i].querySelector('video');
      try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
      catch (err) { /* already gone */ }
      try { if (all[i].parentNode) all[i].parentNode.removeChild(all[i]); }
      catch (err) { /* already gone */ }
    }
    host = video = tube = null;
    showing = false;
  }

  /* ---- one clip ------------------------------------------------------ */

  function play(clip) {
    playing = clip;                                        /* #1306b */
    var tries = Number(clip.__tries) || 0;                 /* #1311d */
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

    /* #1308b: NOTHING IS SHOWN UNTIL THERE IS A PICTURE.
     *
     * "I don't want to see the video icon. I just want to see the crt
     *  effect then expand out becoming the video window. Do not show
     *  the preview video box first. That image isn't even scaled
     *  properly to be a box, so it's like skewed."
     *
     * That icon is not ours and it is not the clip: it is the Android
     * WebView's own placeholder for a <video> with no frames yet, and
     * being a fixed bitmap it ignores the object-fit: contain this
     * stylesheet sets, which is why it came out stretched. The set
     * used to open the moment play() was called, and the clip takes a
     * couple of seconds to arrive over the LAN - so the CRT expanded
     * onto the placeholder and the picture appeared inside it later.
     *
     * So the whole window waits. It is built and positioned, but
     * hidden, until the first real frame exists; then the CRT runs and
     * expands into the picture itself. A clip that never arrives is
     * torn down by the watchdog below and was never seen at all,
     * which is better than an empty box that sat there. */
    var shown = false;
    var reveal = function () {
      if (shown || done) return;
      shown = true;
      try {
        host.classList.remove('waiting');
        glass.classList.add('on');   // dot -> line -> picture
        parts.flash.classList.add('pop');
      } catch (err) { /* the picture is there either way */ }
    };
    /* loadeddata is the first frame; playing covers a clip that was
       already buffered. Both are harmless twice - reveal guards. */
    screen.addEventListener('loadeddata', reveal);
    screen.addEventListener('playing', reveal);

    /* #1311d: A CLIP THIS BUILD CANNOT DECODE IS NOT THE END OF THE TAP.
     *
     * The library is 400 grabbed mp4s and they are not all the same
     * inside - measured on the tablet, a clip that the station served
     * perfectly (200 OK, video/mp4, 415 kB in 0.11s) came back
     * MEDIA_ERR_SRC_NOT_SUPPORTED, because this WebView has no
     * decoder for what is in that particular container.
     *
     * The operator tapped a button and is owed a picture, so a clip
     * that will not open is SKIPPED rather than mourned: the set asks
     * the cue road for another and tries that instead. Only a cut the
     * operator asked for retries - the station's own stings keep the
     * old behaviour, because there the clip is punctuating a line and
     * a substitute would land after the moment it was for. */
    var failed = function () {
      if (done) return;
      if (!shown && clip.__cut && tries < 3 && api() && api().post) {
        done = true;                 /* this attempt is over */
        try { teardownNow(); } catch (err) { /* nothing up */ }
        api().post('/api/sfx/video/cue', {who: 'retry'}).then(
          function (got) {
            var next = got && got.clip;
            if (!next) { showing = false; return; }
            next.__cut = true;
            next.__tries = tries + 1;
            showing = true;
            try { play(next); } catch (err) { showing = false; }
          },
          function () { showing = false; });
        return;
      }
      finish();
    };
    screen.addEventListener('ended', finish);
    screen.addEventListener('error', failed);
    screen.src = base.replace(/\/+$/, '') + String(clip.url || '');
    screen.volume = level;
    /* #1310: THE PAD'S IN AND OUT, ON THE PICTURE TOO.
     *
     * The same {start, end} the engine clips the audio to, so a video
     * pad's trim edits both halves of it from the one editor. Seeking
     * waits for metadata - currentTime cannot be set before the
     * duration is known - and the out is watched on timeupdate rather
     * than with a timer, because a clip that stalls should stop where
     * the operator said, not where a clock guessed. */
    var from = Number(clip.from);
    var to = Number(clip.to);
    if (isFinite(from) && from > 0) {
      screen.addEventListener('loadedmetadata', function () {
        try { screen.currentTime = from; } catch (err) { /* whole clip */ }
      });
    }
    if (isFinite(to) && to > 0) {
      screen.addEventListener('timeupdate', function () {
        if (Number(screen.currentTime) >= to) finish();
      });
    }
    /* THE WATCHDOG. `error` does not fire for every way a clip can fail
     * to begin - a stalled range request, a container this build cannot
     * decode, a zero-byte download off the drop share - and a set left on
     * with a black tube holds every clip behind it. */
    setTimeout(function () {
      if (done || video !== screen) return;
      /* #1311d: a clip that never started is skipped the same way one
         that errored is - a stalled range request and a missing
         decoder look identical from here and deserve the same answer. */
      if (screen.paused || !Number(screen.currentTime)) failed();
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
    /* #1309b: and the only way left to dismiss the picture itself,
       now that the title bar with its ✕ is gone. */
    var away = button(rowB, 'Stop', 'Take the picture off the screen',
      function () {
        wrap.remove();
        try { teardownNow(); } catch (err) { /* already gone */ }
      });
    away.className = 'quiet';

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

  /* The one shape of "this clip has been dealt with here". Written in
   * one place because two spellings of it is a picture that plays
   * twice. */
  function markOf(clip) {
    if (!clip || !clip.url) return '';
    var mark = String(clip.ts || '') + '|' + String(clip.url);
    marks[mark] = 1;
    return mark;
  }

  /* #1322: TELL THE OTHER SETS.
   *
   * A clip fired locally - a sampler pad holding an mp4 (#1310) - never
   * touches the station, so the app's set and the tablet's set each
   * only ever show the clips that happen to have been fired on them.
   * "When a video clip is played, show a PiP overlay on the application
   * as well."
   *
   * So a local cut also RINGS the clip: /api/sfx/video/cut puts it in
   * the same ring /api/dj/video serves, with no claim on the air (see
   * page_picture_append). The stamped clip comes back and is marked
   * here, which is what stops this surface playing its own picture a
   * second time when the poll comes round to it.
   *
   * Silent about failure throughout: the picture is already on THIS
   * screen, and a station that refused the ring is not a reason to take
   * it down. */
  function ring(clip) {
    if (!clip || !clip.url) return;
    if (!api() || !api().post) return;
    var body = {
      url: String(clip.url), sting: String(clip.sting || ''),
      id: String(clip.id || ''), seconds: Number(clip.seconds) || 0
    };
    if (Number(clip.from) > 0) body.from = Number(clip.from);
    if (Number(clip.to) > 0) body.to = Number(clip.to);
    try {
      api().post('/api/sfx/video/cut', body).then(function (got) {
        if (got && got.clip) markOf(got.clip);
      }, function () { /* the picture is up here either way */ });
    } catch (err) { /* likewise */ }
  }

  function offer(clip) {
    if (!clip || !clip.url) return;
    if (marks[String(clip.ts || '') + '|' + String(clip.url)]) return;
    markOf(clip);
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
    /* #1322: "this clip has been dealt with here", for a caller that
       rang the station by some other road and does not want its own
       picture back. */
    mark: markOf,
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
     * time.
     *
     * #1322: `{ring: true}` says the caller fired this clip LOCALLY and
     * the station has never heard of it - a sampler pad, not the cue
     * road - so it is also published for the other surfaces' sets. A
     * clip that came back FROM the station is already in the ring and
     * must not be rung again. */
    cut: function (clip, opts) {
      if (!clip || !clip.url) return false;
      /* Before the mount check, deliberately: a surface with no set of
         its own still owes the other surfaces the picture. */
      if (opts && opts.ring) ring(clip);
      if (!mounted) return false;
      try { markOf(clip); }
      catch (err) { /* the play below still stands */ }
      queue.length = 0;
      if (hold) { clearTimeout(hold); hold = null; }
      try { clip.__cut = true; } catch (err) { /* frozen: no retry */ }
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
          if (mounted) return;
          if (/^https?:$/.test(String(root.location.protocol))) {
            root.PineSfxTv.mount({baseUrl: ''});
          } else if (root.pineDesktop) {
            /* #1399: AND ON THE DESKTOP, WHERE THE SHELL'S OWN MOUNT CAN
             * RUN TOO EARLY. renderer.js mounts this inside loadConfig,
             * and loadConfig runs before this file has been evaluated -
             * so window.PineSfxTv was undefined at that instant and the
             * mount was skipped. Measured: with the endless set ringing
             * three clips ahead and the tablet playing them, the desktop's
             * tube stayed dark until mount() was called by hand, after
             * which it lit within twelve seconds. The base is the one the
             * chrome already knows (#1348). */
            var b = '';
            try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; }
            catch (err) { b = ''; }
            root.PineSfxTv.mount({baseUrl: b || 'http://127.0.0.1:8096'});
          }
        } catch (err) { /* no set is better than a broken view */ }
      }, 3000);
    }
  } catch (err) { /* not a browser */ }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSfxTv;
  }
})(typeof window !== 'undefined' ? window : globalThis);
