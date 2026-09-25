/* THE SLIDESHOW, ON THE TABLET - a port of ~/bin/media-slideshow.
 *
 * "I want to have the media_slideshow ported as an app to pinetab that can
 *  be opened and used to manage and connect to and experience the SC stack
 *  just like the media_slideshow... and be able to view it on tablet
 *  exactly as it was set up on the linux system."
 *
 * The original is 25,000 lines of PySide6 that has been the box's own glass
 * since May. It is not really a slideshow - it is the SC stack's console
 * with the renders playing behind it: eleven service tailers, a GPU
 * sampler, py-spy, the ComfyUI workflow reader and the OpenWebUI
 * conversation feed, all in one fullscreen window.
 *
 * WHAT COULD BE PORTED AND WHAT COULD NOT, stated up front because the
 * difference is the whole design:
 *
 *   THE MATERIAL IS THE SAME MATERIAL. Not a copy, not a mirror. compose
 *   binds ../ComfyUI/output into the station at /comfy-output, and the
 *   desktop app's own diagnostic names `root dir
 *   /home/ehm_eckx/ComfyUI/output` - the host side of that same mount. So
 *   this view plays the same 1,358 pictures from the same folder, and a
 *   like here is a line in the same favorites.md the desktop app reads.
 *
 *   THE SETTINGS ARE THE SAME SETTINGS, when one compose line is present.
 *   The transition, the speed, the filter and the favourites-only flag live
 *   in screensaver_state.json next to the desktop app's output.md. The
 *   station says whether it is reading that file or a copy, and this view
 *   says so too rather than implying a link it does not have - see the
 *   settings row in the panel.
 *
 *   THE TAILERS COULD NOT COME. Every one of them is a subprocess -
 *   nvidia-smi, py-spy, docker, ssh to lilspark - and this is a WebView on
 *   a GApps-less GSI that can reach exactly one HTTP origin. So the reading
 *   stays on the station, where those things are already running on their
 *   own clocks, and arrives here as ONE poll: /api/slideshow/stack. That is
 *   not a reduced version of the eleven panes, it is the same numbers
 *   without eleven subprocesses per tablet.
 *
 * THE KEYBOARD IS GONE, AND THAT CHANGES THE CONTROLS. The desktop app is
 * driven by twenty single keys. A nine-inch tablet has none of them, so
 * every key becomes a surface: swipe for prev/next, double-tap to like,
 * press and hold for the destructive menu, and one bar that auto-hides the
 * way the desktop's overlays do. The key letters are printed beside each
 * control anyway, so an operator who knows the box knows this.
 *
 * WHAT IS HELD IN MEMORY: two pictures. The one on screen and the one
 * after it, which is the desktop's own single-media-in-flight rule and
 * matters more here - that process has a 750 MB budget on a 124 GB box,
 * this tablet was measured at 148 MB free under a load average of 25.
 *
 * IT DOES NOTHING WHILE IT IS NOT LOOKED AT. rail.js keeps a mounted view
 * in the document with display:none, so a timer left running would spend
 * the tablet's battery and the station's socket pool on a screen nobody is
 * on. Every tick checks first.
 */
(function (root) {
  'use strict';

  /* The desktop app's transition list, in its order, so "cycle" means the
   * same thing on both screens and a state file written by either names
   * something the other can show. Several are approximations of a
   * QGraphicsView effect and are marked as such below; none is a different
   * transition wearing the same name. */
  var TRANSITIONS = [
    'all', 'slide', 'swirl', 'rotate', 'flip', 'mosaic', 'fold',
    'bump', 'bash', 'unroll', 'origami', 'sand', 'shatter', 'cube',
    'delete', 'tv', 'crt', 'vaporwave', 'unfold', 'liquid'
  ];
  /* Every concrete one, for when the transition is "all" - the desktop
   * picks a random concrete transition per advance, so this does too. */
  var CONCRETE = TRANSITIONS.slice(1);

  var TRANSITION_MS = 600;   /* the desktop's TRANSITION_MS */
  var DELETE_MS = 900;       /* its DELETE_MS */
  var THUMB_PX = 64;         /* QUEUE_THUMB_SIZE */
  var STRIP_ITEMS = 7;       /* QUEUE_VISIBLE_ITEMS */
  var HOT_LOAD_MS = 20000;   /* how often to ask what is new */
  var BAR_HIDE_MS = 4000;
  var PAGE = 300;

  /* #1357: how often to ask whether the camera is on the air, and how
   * often to pull a frame while it is. Four a second is what the link
   * writes, so asking faster buys nothing but requests. */
  var CAM_ASK_MS = 5000;
  var CAM_FRAME_MS = 250;
  var CAM_OFF_KEY = 'pineSlideshowCamOff';

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function source() {
    return root.PineSlideshowSource || null;
  }

  function mount(host) {
    if (!host) return null;
    var src = source();
    if (!src) {
      host.appendChild(el('div', 'pine-view-note',
        'The slideshow needs PineSlideshowSource, which is not on this '
        + 'terminal. Its file is bundled beside this one; if it is missing '
        + 'the bundle is older than this view.'));
      return null;
    }

    /* ---- state ------------------------------------------------------ */

    var S = {
      items: [],           /* [{file, at, bytes, kind, fav}] */
      index: -1,
      paused: false,
      transition: 'all',
      seconds: 10,         /* IMAGE_SECONDS */
      filter: 'all',       /* media_filter: all | image | video */
      favoritesOnly: false,
      /* One seed for the life of this mount, like the desktop's single
       * random.Random - so page two of the playlist continues the same
       * deal rather than re-shuffling the deck. */
      seed: Math.floor(Math.random() * 1000000) + 1,
      /* #1357: is there a camera on the air, and has the operator sent
       * it away? Two separate answers - the station decides the first
       * and only the person looking at this screen decides the second. */
      camLive: false,
      camOff: false,
      newest: 0,
      shown: 0,            /* "items shown total" in the box's diagnostic */
      fresh: 0,            /* what the hot-load queue has brought in */
      settingsShared: null,
      busy: false,
      layer: 0
    };

    var timer = null;
    var camTimer = null;
    var camFrameTimer = null;
    var hotTimer = null;
    var barTimer = null;
    var destroyed = false;

    /* ---- the furniture ---------------------------------------------- */

    var wrap = el('div', 'sl');
    var stage = el('div', 'sl-stage');
    var layers = [el('div', 'sl-layer'), el('div', 'sl-layer')];
    stage.appendChild(layers[0]);
    stage.appendChild(layers[1]);
    wrap.appendChild(stage);

    /* #1357: THE CAMERA TAKES THE GALLERY'S PLACE.
     *
     * "If the station is present, then on the station broadcast I want
     *  to replace the slideshow with the broadcast of what's being
     *  broadcasted from the camera. And I also want the ability to
     *  toggle it off and toggle it back to being the gallery."
     *
     * A layer over the stage rather than an item in the playlist. The
     * playlist is a list of files on disk with favourites, likes and a
     * shuffle seed; a live camera is none of those things, and pushing
     * it in there would mean every road that steps, likes or deletes an
     * item has to learn about a row that has no file behind it.
     *
     * The gallery STOPS while the camera covers it. Cross-fading
     * pictures nobody can see costs the tablet real bandwidth - the
     * measured figure that made ?w= necessary was 6.7 MB of PNG in
     * thirty seconds - and it would be spent on a hidden layer.
     */
    var cam = el('div', 'sl-cam');
    var camShot = el('img', 'sl-cam-shot');
    camShot.alt = 'the Pine Cam';
    cam.appendChild(camShot);
    cam.appendChild(el('div', 'sl-cam-tag', 'PINE CAM \u00b7 LIVE'));
    stage.appendChild(cam);

    var flash = el('div', 'sl-flash');           /* the like / action flash */
    wrap.appendChild(flash);

    var caption = el('div', 'sl-caption');
    wrap.appendChild(caption);

    var bar = el('div', 'sl-bar');
    wrap.appendChild(bar);

    var strip = el('div', 'sl-strip');
    wrap.appendChild(strip);

    var sheet = el('div', 'sl-sheet');
    sheet.hidden = true;
    wrap.appendChild(sheet);

    host.appendChild(wrap);

    /* ---- the control bar -------------------------------------------- */

    var buttons = {};

    function button(key, label, hint, onPress) {
      var node = el('button', 'sl-btn');
      node.appendChild(el('span', 'sl-btn-face', label));
      /* The desktop's key letter, printed. An operator who knows the box
       * should not have to learn a second vocabulary for the same act. */
      if (key) node.appendChild(el('span', 'sl-btn-key', key));
      node.title = hint;
      node.addEventListener('click', function (event) {
        event.stopPropagation();
        wake();
        onPress();
      });
      buttons[label] = node;
      bar.appendChild(node);
      return node;
    }

    var pauseBtn = button('SPACE', '❚❚', 'Pause or resume', function () {
      S.paused = !S.paused;
      paintBar();
      if (!S.paused) schedule();
      say(S.paused ? 'paused' : 'playing');
    });
    button('←', '◀', 'Previous', function () { step(-1); });
    button('→', '▶', 'Next', function () { step(1); });
    var likeBtn = button('L', '♡', 'Like or unlike this one', like);
    var favBtn = button('F', '★', 'Show only favourites', function () {
      S.favoritesOnly = !S.favoritesOnly;
      remember({favorites_only: S.favoritesOnly});
      reload();
    });
    var transBtn = button('T', 'all', 'Cycle the transition', function () {
      var at = TRANSITIONS.indexOf(S.transition);
      S.transition = TRANSITIONS[(at + 1) % TRANSITIONS.length];
      remember({transition: S.transition});
      paintBar();
      say(S.transition);
    });
    var filterBtn = button('↑↓', 'ALL', 'Pictures, video, or both', function () {
      S.filter = S.filter === 'all' ? 'image'
        : (S.filter === 'image' ? 'video' : 'all');
      remember({media_filter: S.filter});
      reload();
    });
    /* #1357: the toggle. Hidden until there is a camera to toggle - a
     * button that can only ever say 'no camera' is furniture. */
    var camBtn = button('C', '\u25c9',
      'Show the camera instead of the gallery', function () {
        S.camOff = !S.camOff;
        try { localStorage.setItem(CAM_OFF_KEY, S.camOff ? '1' : '0'); }
        catch (err) { /* a forgotten choice still works this session */ }
        paintCam();
        say(S.camOff ? 'the gallery' : 'the camera');
      });
    camBtn.hidden = true;

    var speedBtn = button('', '10s', 'How long each picture stays', function () {
      var ladder = [3, 5, 10, 20, 30, 60];
      var at = ladder.indexOf(S.seconds);
      S.seconds = ladder[(at + 1) % ladder.length];
      remember({image_seconds: S.seconds});
      paintBar();
      schedule();
      say(S.seconds + ' seconds');
    });
    button('DEL', '⌫', 'Set aside, or delete', actionSheet);
    /* THE OVERLAYS ARE THE POINT, so S turns the whole layer on and off
     * rather than opening a summary sheet. The desktop application has no
     * such sheet — it has the readouts, permanently, over the picture. */
    var overlayBtn = button('S', '◲', 'The backend overlays', function () {
      overlaysOn = !overlaysOn;
      applyOverlays();
      say(overlaysOn ? 'overlays on' : 'overlays off');
    });
    button('H', '?', 'What the controls do', function () { openSheet('help'); });

    /* ---- the camera (#1357) ----------------------------------------- */

    function camUrl() {
      var b = '';
      try { b = src.base ? src.base() : ''; } catch (err) { b = ''; }
      return b + '/api/pinelink/frame.jpg?_=' + Date.now();
    }

    function camShowing() { return !!(S.camLive && !S.camOff); }

    function paintCam() {
      var on = camShowing();
      camBtn.hidden = !S.camLive;
      camBtn.classList.toggle('on', on);
      cam.classList.toggle('show', on);
      if (on) {
        if (timer) { clearTimeout(timer); timer = null; }
        camDraw();
      } else {
        camShot.removeAttribute('src');
        schedule();
      }
    }

    function camDraw() {
      if (!camShowing() || destroyed) return;
      /* A hidden view is a view nobody is watching. visible() is the
       * same check the step timer uses. */
      if (!visible()) return;
      camShot.src = camUrl();
    }

    function camAsk() {
      if (destroyed) return;
      var b = '';
      try { b = src.base ? src.base() : ''; } catch (err) { b = ''; }
      var road = b + '/api/pinelink/look';
      var got;
      try {
        got = (root.pineDesktop && root.pineDesktop.get)
          ? root.pineDesktop.get('/api/pinelink/look')
          : fetch(road, {credentials: 'same-origin'}).then(function (r) {
            return r.ok ? r.json() : null;
          });
      } catch (err) { return; }
      Promise.resolve(got).then(function (d) {
        /* on_air_now is the station's own answer and already folds in
         * both halves of the question - the link being live AND the
         * operator's on-air preference. Reading the two separately here
         * would be a second copy of a rule that has one home. */
        var was = S.camLive;
        S.camLive = !!(d && d.on_air_now);
        if (was !== S.camLive) paintCam();
      }).catch(function () { /* asked again on the next sweep */ });
    }

    function paintBar() {
      pauseBtn.firstChild.textContent = S.paused ? '▶' : '❚❚';
      pauseBtn.classList.toggle('on', S.paused);
      transBtn.firstChild.textContent = S.transition;
      filterBtn.firstChild.textContent = S.filter === 'all' ? 'ALL'
        : (S.filter === 'image' ? 'IMG' : 'VID');
      filterBtn.classList.toggle('on', S.filter !== 'all');
      speedBtn.firstChild.textContent = S.seconds + 's';
      favBtn.classList.toggle('on', S.favoritesOnly);
      var row = current();
      likeBtn.firstChild.textContent = (row && row.fav) ? '♥' : '♡';
      likeBtn.classList.toggle('on', !!(row && row.fav));
    }

    /* The bar hides itself the way the desktop's overlays do, and any touch
     * brings it back. A slideshow with permanent furniture is a file
     * browser. */
    function wake() {
      wrap.classList.add('awake');
      if (barTimer) clearTimeout(barTimer);
      barTimer = setTimeout(function () {
        wrap.classList.remove('awake');
      }, BAR_HIDE_MS);
    }

    function say(text) {
      flash.textContent = text;
      flash.classList.remove('on');
      /* Reflow, or a second flash in the same beat never restarts. */
      void flash.offsetWidth;
      flash.classList.add('on');
    }

    /* ---- the playlist ----------------------------------------------- */

    function current() {
      return S.index >= 0 ? S.items[S.index] : null;
    }

    function visible() {
      /* IS THIS VIEW ON SCREEN?
       *
       * rail.js keeps a mounted view in the document at display:none, and
       * its `open` class is the plainest signal there is — so that is asked
       * first.
       *
       * offsetParent IS NOT A SUBSTITUTE, and the fit probe caught it:
       * offsetParent is ALWAYS null for a position:fixed element, which the
       * rail's host and the standalone page's picture stage both are. So
       * `offsetParent || open` answered "not visible" for every host that
       * did not happen to use the rail's class, and the whole monitor sat
       * asleep on a page that was plainly being looked at. A box with real
       * dimensions that is not display:none is the honest test. */
      if (host.classList.contains('open')) return true;
      try {
        var box = host.getBoundingClientRect();
        if (!box.width || !box.height) return false;
        return getComputedStyle(host).display !== 'none';
      } catch (err) {
        return true;      /* never make a measurement failure into silence */
      }
    }

    /* IT MUST NOT GIVE UP ON ONE MISS, and the first version did.
     *
     * MEASURED ON THE TABLET: the very first playlist request answered
     * `timeout`, and the view showed a note and stopped for good — a black
     * screen for the rest of the session. The same request from the same
     * WebView a minute later took 242 ms. Nothing was wrong with the route.
     *
     * The cause is the one this codebase keeps rediscovering: rail.js
     * reopens the remembered view 1.2s after boot, which is exactly when the
     * panel is pulling a two-megabyte document and the native feed is
     * starting. OkHttp allows five requests per host; a question asked into
     * that lands last. The station is not down at that moment, it is busy,
     * and those need different behaviour.
     *
     * So a failure backs off and asks again — 2s, 4s, 8s, capped at 30 —
     * and the note says so rather than reading as a fault. A success clears
     * the note and the backoff. */
    var backoff = 0;
    var retryTimer = null;

    function reload() {
      paintBar();
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
      return src.page({
        limit: PAGE, kind: S.filter, favorites: S.favoritesOnly ? 1 : 0,
        order: 'shuffle', seed: S.seed
      }).then(function (body) {
        backoff = 0;
        S.items = (body && body.rows) || [];
        S.newest = (body && body.newest_at) || 0;
        S.index = S.items.length ? 0 : -1;
        paintStrip();
        if (S.index >= 0) { note(''); show(0, 'slide'); }
        else note(S.favoritesOnly
          ? 'No favourites yet. Like one with the heart and it lands in '
            + 'favorites.md, which is the same file the box reads.'
          : 'Nothing playable in the folder.');
        schedule();
        return body;
      }, function (err) {
        backoff = backoff ? Math.min(backoff * 2, 30000) : 2000;
        note('The station did not answer ('
          + (err && err.message ? err.message : err) + '). Asking again in '
          + Math.round(backoff / 1000) + 's — this is usually the panel’s '
          + 'own boot traffic, not a station that is down.');
        if (destroyed) return;
        retryTimer = setTimeout(function () {
          retryTimer = null;
          reload();
        }, backoff);
      });
    }

    /* ONE note element, replaced. It lives beside the layers rather than
     * inside the stage's children, because clearing the stage would take
     * the two layers with it — and a view whose layers are gone never
     * shows another picture. */
    var noteBox = el('div', 'sl-note');
    noteBox.hidden = true;
    wrap.insertBefore(noteBox, flash);

    function note(text) {
      noteBox.textContent = text || '';
      noteBox.hidden = !text;
    }

    /* THE HOT LOAD. The desktop app's Playlist.append() "inserts ahead of
     * the cursor", so a render that has just finished is the next thing on
     * screen rather than something you reach in twenty minutes. Same
     * behaviour, asked for rather than watched. */
    function hotLoad() {
      if (destroyed || !visible() || !S.newest) return;
      src.since(S.newest).then(function (body) {
        var rows = (body && body.fresh) || [];
        if (body && body.newest_at) S.newest = body.newest_at;
        if (!rows.length) return;
        var have = {};
        S.items.forEach(function (row) { have[row.file] = true; });
        var added = rows.filter(function (row) {
          if (have[row.file]) return false;
          if (S.filter !== 'all' && row.kind !== S.filter) return false;
          if (S.favoritesOnly && !row.fav) return false;
          return true;
        });
        if (!added.length) return;
        /* Ahead of the cursor, newest first. */
        var at = Math.max(0, S.index + 1);
        Array.prototype.splice.apply(S.items, [at, 0].concat(added));
        S.fresh += added.length;
        paintStrip();
        say(added.length === 1 ? 'one new render'
          : added.length + ' new renders');
      }, function () { /* a quiet miss is not worth a banner */ });
    }

    /* ---- showing one ------------------------------------------------ */

    function schedule() {
      if (timer) clearTimeout(timer);
      timer = null;
      if (S.paused || destroyed) return;
      var row = current();
      if (!row) return;
      /* A video runs to its own end; the desktop does the same rather than
       * cutting a clip off at IMAGE_SECONDS. */
      if (row.kind === 'video') return;
      timer = setTimeout(function () {
        if (!visible()) { schedule(); return; }
        step(1);
      }, Math.max(1, S.seconds) * 1000);
    }

    function step(direction) {
      if (!S.items.length) return;
      var next = S.index + direction;
      if (next < 0) next = S.items.length - 1;
      if (next >= S.items.length) next = 0;
      show(next, pick());
    }

    function pick() {
      if (S.transition !== 'all') return S.transition;
      return CONCRETE[Math.floor(Math.random() * CONCRETE.length)];
    }

    function show(index, transition) {
      var row = S.items[index];
      if (!row || S.busy) return;
      S.index = index;
      S.busy = true;

      var from = layers[S.layer];
      var to = layers[1 - S.layer];
      to.innerHTML = '';

      var media;
      if (row.kind === 'video') {
        media = document.createElement('video');
        media.style.visibility = 'hidden';
        media.autoplay = true;
        media.playsInline = true;
        /* MUTED, ALWAYS. #1008: what comes out of this tablet's speaker is
         * the station's business, not a view's - an unmuted clip would talk
         * over the air the operator is listening to. */
        media.muted = true;
        media.loop = false;
        var cover = new Image();
        cover.className = 'sl-media';
        cover.alt = '';
        cover.style.background = '#05080b';
        cover.style.objectFit = 'contain';
        var icon = new Image();
        icon.className = 'sl-media';
        icon.alt = '';
        icon.style.cssText = 'object-fit:contain;width:min(96px,24%);height:min(96px,24%);'
          + 'inset:50% auto auto 50%;transform:translate(-50%,-50%);background:transparent';
        icon.src = src.base() + '/spark/asset/pinebox.png';
        to.appendChild(cover);
        to.appendChild(icon);
        var posterUrl = row.poster_url || row.poster;
        if (posterUrl) {
          cover.src = /^(https?:)?\/\//.test(posterUrl) ? posterUrl
            : src.base() + (posterUrl.charAt(0) === '/' ? '' : '/')
              + posterUrl;
          cover.addEventListener('load', function () { icon.hidden = true; });
          cover.addEventListener('error', function () { cover.removeAttribute('src'); });
        }
        var frameGeneration = 0, firstTime = NaN;
        var framePending = false, frameShown = false;
        function frameReady() {
          return media.readyState >= 2 && media.videoWidth > 0 && media.videoHeight > 0;
        }
        function revealFrame() {
          if (frameShown || !frameReady()) return;
          frameShown = true;
          media.style.visibility = 'visible';
          cover.hidden = true;
          icon.hidden = true;
        }
        function hideFrame() {
          frameGeneration += 1;
          firstTime = NaN;
          framePending = false;
          frameShown = false;
          media.style.visibility = 'hidden';
          cover.hidden = false;
          icon.hidden = !!(posterUrl && cover.complete && cover.naturalWidth);
        }
        media.addEventListener('loadstart', hideFrame);
        media.addEventListener('emptied', hideFrame);
        function armFrame() {
          if (!frameReady()) return;
          if (!Number.isFinite(firstTime)) firstTime = Number(media.currentTime) || 0;
          if (typeof media.requestVideoFrameCallback !== 'function' || framePending) return;
          framePending = true;
          var token = frameGeneration;
          try {
            media.requestVideoFrameCallback(function () {
              if (token !== frameGeneration) return;
              framePending = false;
              revealFrame();
            });
          } catch (err) { framePending = false; /* timeupdate remains the fallback */ }
        }
        media.addEventListener('loadeddata', armFrame);
        media.addEventListener('playing', armFrame);
        media.addEventListener('seeked', function () {
          if (!media.seeking) revealFrame();
        });
        media.addEventListener('timeupdate', function () {
          if (!Number.isFinite(firstTime)) { armFrame(); return; }
          if (Number.isFinite(firstTime)
            && Number(media.currentTime) > firstTime + 0.04) revealFrame();
        });
        media.addEventListener('ended', function () {
          if (!S.paused) step(1);
        });
        media.src = src.url(row.file);
      } else {
        media = new Image();
        media.decoding = 'async';
        media.src = src.url(row.file);
      }
      media.className = 'sl-media';
      to.appendChild(media);

      run(from, to, transition, function () {
        from.innerHTML = '';       /* the other picture is released here */
        S.layer = 1 - S.layer;
        S.busy = false;
        S.shown += 1;
        paintCaption();
        paintStrip();
        paintBar();
        schedule();
      });

      /* ONE AHEAD, AND ONLY ONE. The browser caches it; nothing holds a
       * reference, so it costs the picture and not a second copy. */
      var ahead = S.items[index + 1];
      if (ahead && ahead.kind !== 'video') {
        var pre = new Image();
        pre.decoding = 'async';
        pre.src = src.url(ahead.file);
      }
    }

    function paintCaption() {
      var row = current();
      if (!row) { caption.textContent = ''; return; }
      caption.innerHTML = '';
      caption.appendChild(el('span', 'sl-cap-name', row.file));
      var age = Math.max(0, (Date.now() / 1000) - row.at);
      caption.appendChild(el('span', 'sl-cap-meta',
        (S.index + 1) + ' / ' + S.items.length + '  ·  ' + ago(age)
        + (row.fav ? '  ·  ♥' : '')));
    }

    function ago(seconds) {
      if (seconds < 90) return Math.round(seconds) + 's ago';
      if (seconds < 5400) return Math.round(seconds / 60) + ' min ago';
      if (seconds < 172800) return Math.round(seconds / 3600) + ' h ago';
      return Math.round(seconds / 86400) + ' days ago';
    }

    /* ---- the transitions -------------------------------------------- */

    /* Each name below is the desktop app's. Where a QGraphicsView effect
     * has no CSS equivalent the comment says what this one actually does,
     * because a transition that is merely NAMED after the original is the
     * kind of thing that quietly makes two screens different. */
    function run(from, to, name, done) {
      var kind = name || 'slide';
      if (kind === 'mosaic') return mosaic(from, to, done);
      if (kind === 'shatter') return shatter(from, to, done);

      to.classList.add('sl-in', 'sl-t-' + kind);
      from.classList.add('sl-out', 'sl-t-' + kind);
      to.style.display = 'block';

      var settled = false;
      function finish() {
        if (settled) return;
        settled = true;
        /* done() EMPTIES the outgoing layer, and it must do so BEFORE the
         * classes come off. `animation-fill-mode: both` is holding that
         * layer at its final frame — faded out, rotated away — and removing
         * the class first snaps a fully opaque old picture back over the
         * new one for a frame. It reads as a flicker on every advance. */
        done();
        to.classList.remove('sl-in', 'sl-t-' + kind);
        from.classList.remove('sl-out', 'sl-t-' + kind);
      }
      /* A timeout as well as the event: animationend does not fire if the
       * view is hidden mid-transition, and a slideshow stuck with busy=true
       * is a dead screen that looks like a network fault. */
      to.addEventListener('animationend', finish, {once: true});
      setTimeout(finish, (kind === 'delete' ? DELETE_MS : TRANSITION_MS) + 250);
    }

    /* MOSAIC is the one that cannot be faked. The desktop pixelizes the
     * outgoing frame; CSS has no pixelate, and a blur is a different
     * effect that would read as "the tablet is out of focus". So the
     * outgoing picture is genuinely resampled through a canvas, four steps
     * down, which is what pixelizing is. */
    function mosaic(from, to, done) {
      var img = from.querySelector('img');
      if (!img || !img.naturalWidth) {
        to.style.display = 'block';
        from.style.opacity = '0';
        setTimeout(function () { from.style.opacity = ''; done(); }, 200);
        return;
      }
      var canvas = document.createElement('canvas');
      canvas.className = 'sl-media sl-canvas';
      var box = from.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(box.width));
      canvas.height = Math.max(1, Math.round(box.height));
      var ctx = canvas.getContext('2d');
      ctx.imageSmoothingEnabled = false;
      from.innerHTML = '';
      from.appendChild(canvas);

      var steps = [0.25, 0.08, 0.03, 0.012];
      var at = 0;
      (function tick() {
        if (at >= steps.length) {
          to.style.display = 'block';
          to.classList.add('sl-in', 'sl-t-sand');
          setTimeout(function () {
            to.classList.remove('sl-in', 'sl-t-sand');
            done();
          }, TRANSITION_MS);
          return;
        }
        var scale = steps[at];
        at += 1;
        var w = Math.max(1, Math.round(canvas.width * scale));
        var h = Math.max(1, Math.round(canvas.height * scale));
        var small = document.createElement('canvas');
        small.width = w;
        small.height = h;
        var sctx = small.getContext('2d');
        sctx.imageSmoothingEnabled = false;
        try {
          sctx.drawImage(img, 0, 0, w, h);
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.imageSmoothingEnabled = false;
          ctx.drawImage(small, 0, 0, canvas.width, canvas.height);
        } catch (err) {
          at = steps.length;      /* a tainted or half-decoded frame */
        }
        setTimeout(tick, TRANSITION_MS / (steps.length + 1));
      })();
    }

    /* SHATTER: eight real shards of the outgoing frame, each clipped and
     * thrown. Eight rather than the desktop's many, because every shard is
     * a composited layer and this is a MediaTek GPU. */
    function shatter(from, to, done) {
      var img = from.querySelector('img');
      if (!img) { to.style.display = 'block'; done(); return; }
      var shards = document.createDocumentFragment();
      for (var i = 0; i < 8; i += 1) {
        var piece = img.cloneNode(false);
        piece.className = 'sl-media sl-shard';
        var x = (i % 4) * 25;
        var y = Math.floor(i / 4) * 50;
        piece.style.clipPath = 'polygon(' + x + '% ' + y + '%, '
          + (x + 25) + '% ' + y + '%, ' + (x + 25) + '% ' + (y + 50) + '%, '
          + x + '% ' + (y + 50) + '%)';
        piece.style.setProperty('--sl-fly-x',
          ((x - 37) * (2 + Math.random() * 3)) + '%');
        piece.style.setProperty('--sl-fly-y',
          ((y - 25) * (2 + Math.random() * 3)) + '%');
        piece.style.setProperty('--sl-spin',
          (Math.random() * 120 - 60) + 'deg');
        shards.appendChild(piece);
      }
      from.innerHTML = '';
      from.appendChild(shards);
      from.classList.add('sl-shattering');
      to.style.display = 'block';
      setTimeout(function () {
        from.classList.remove('sl-shattering');
        done();
      }, TRANSITION_MS + 150);
    }

    /* ---- the filmstrip (the desktop's hot-load queue) ---------------- */

    function paintStrip() {
      strip.innerHTML = '';
      if (!S.items.length) return;
      for (var i = 0; i < STRIP_ITEMS; i += 1) {
        var at = S.index + i;
        if (at >= S.items.length) at -= S.items.length;
        var row = S.items[at];
        if (!row) continue;
        var cell = el('button', 'sl-cell' + (i === 0 ? ' now' : ''));
        if (row.kind === 'video') {
          /* No frame can be pulled without a decoder the station does not
           * have, so a clip says it is one rather than showing a hole. */
          cell.appendChild(el('span', 'sl-cell-video', '▶'));
        } else {
          var thumb = new Image();
          thumb.decoding = 'async';
          thumb.loading = 'lazy';
          thumb.src = src.thumb(row.file, THUMB_PX * 2);
          cell.appendChild(thumb);
        }
        if (row.fav) cell.appendChild(el('span', 'sl-cell-fav', '♥'));
        (function (index) {
          cell.addEventListener('click', function (event) {
            event.stopPropagation();
            wake();
            show(index, pick());
          });
        })(at);
        strip.appendChild(cell);
      }
    }

    /* ---- likes, and the two ways to remove something ----------------- */

    function like() {
      var row = current();
      if (!row) return;
      src.like(row.file, !row.fav).then(function (body) {
        row.fav = !!(body && body.on);
        paintBar();
        paintCaption();
        paintStrip();
        say(row.fav ? '♥ liked' : 'unliked');
      }, function (err) {
        say('could not write favorites.md: '
          + (err && err.message ? err.message : err));
      });
    }

    /* THE DESTRUCTIVE ONE IS BEHIND A SHEET, and the two options are not
     * the same option. The desktop's trash disc has an outer ring that
     * MOVES a picture into smut/ - out of the show, still on disk - and the
     * unlink is a separate act. On a keyboard that distinction is two
     * gestures; under a thumb on a nine-inch screen an undoable and an
     * unundoable act must not be one tap apart. */
    function actionSheet() {
      var row = current();
      if (!row) return;
      openSheet('action', row);
    }

    function removeCurrent(row) {
      var at = S.items.indexOf(row);
      if (at >= 0) S.items.splice(at, 1);
      if (!S.items.length) {
        S.index = -1;
        /* The LAYERS are emptied, never the stage: the stage's children ARE
         * the two layers, and a view that has thrown them away cannot show
         * another picture for the rest of the session. */
        layers[0].innerHTML = '';
        layers[1].innerHTML = '';
        paintStrip();
        note('Nothing left in this filter.');
        return;
      }
      if (S.index >= S.items.length) S.index = 0;
      show(S.index, 'delete');
      paintStrip();
    }

    /* ---- settings, shared with the box ------------------------------ */

    function remember(patch) {
      src.setState(patch).then(function (body) {
        S.settingsShared = !!(body && body.shared);
      }, function () {
        S.settingsShared = false;
      });
    }

    function restore() {
      return src.state().then(function (body) {
        var state = (body && body.state) || {};
        S.settingsShared = !!(body && body.shared);
        if (TRANSITIONS.indexOf(state.transition) >= 0) {
          S.transition = state.transition;
        }
        if (state.image_seconds > 0) S.seconds = Number(state.image_seconds);
        if (state.media_filter === 'image' || state.media_filter === 'video'
            || state.media_filter === 'all') {
          S.filter = state.media_filter;
        }
        S.favoritesOnly = !!state.favorites_only;
        paintBar();
      }, function () { /* the defaults above are already the box's */ });
    }

    /* ---- the sheets: the stack, the help, the destructive menu ------- */

    function openSheet(which, row) {
      sheet.innerHTML = '';
      sheet.hidden = false;
      sheet.dataset.kind = which;

      var close = el('button', 'sl-sheet-close', '✕');
      close.addEventListener('click', function (event) {
        event.stopPropagation();
        closeSheet();
      });
      sheet.appendChild(close);

      if (which === 'help') return paintHelp();
      if (which === 'action') return paintAction(row);
    }

    function closeSheet() {
      sheet.hidden = true;
      sheet.innerHTML = '';
    }

    function paintAction(row) {
      sheet.appendChild(el('h3', 'sl-sheet-title', row.file));
      sheet.appendChild(el('p', 'sl-sheet-note',
        'Two different acts. Only one of them can be undone.'));

      var aside = el('button', 'sl-sheet-row', 'Set aside  —  moves it to '
        + 'smut/, out of the rotation, still on disk');
      aside.addEventListener('click', function () {
        closeSheet();
        src.aside(row.file).then(function (body) {
          say((body && body.say) || 'set aside');
          removeCurrent(row);
        }, function (err) {
          say('could not set aside: ' + (err && err.message ? err.message : err));
        });
      });
      sheet.appendChild(aside);

      var kill = el('button', 'sl-sheet-row danger',
        'Delete  —  unlinks the file. There is no undo.');
      kill.addEventListener('click', function () {
        kill.textContent = 'Press again to delete ' + row.file;
        kill.classList.add('armed');
        kill.onclick = function () {
          closeSheet();
          src.destroy(row.file).then(function () {
            say('deleted ' + row.file);
            removeCurrent(row);
          }, function (err) {
            say('could not delete: ' + (err && err.message ? err.message : err));
          });
        };
      });
      sheet.appendChild(kill);
    }

    function paintHelp() {
      sheet.appendChild(el('h3', 'sl-sheet-title', 'The slideshow'));
      sheet.appendChild(el('p', 'sl-sheet-note',
        'The same folder the box plays from — /home/ehm_eckx/ComfyUI/output, '
        + 'which reaches the station as the /comfy-output mount. A like here '
        + 'is a line in the same favorites.md.'));
      var rows = [
        ['Swipe left or right', 'previous / next  (← →)'],
        ['Tap the picture', 'show or hide the controls'],
        ['Double tap', 'like  (L)'],
        ['Press and hold', 'set aside, or delete  (DEL)'],
        ['T', 'cycle the transition — all twenty of the box’s'],
        ['F', 'favourites only'],
        ['↑↓', 'pictures, video, or both'],
        ['S', 'the backend overlays — the graph, the stats, the services, '
          + 'the GPU, the thermals, the station'],
        ['H', 'this']
      ];
      var table = el('div', 'sl-help');
      rows.forEach(function (pair) {
        var line = el('div', 'sl-help-row');
        line.appendChild(el('span', 'sl-help-key', pair[0]));
        line.appendChild(el('span', 'sl-help-what', pair[1]));
        table.appendChild(line);
      });
      sheet.appendChild(table);
    }


    /* ---- touch: every key that is gone ------------------------------ */

    var touch = {x: 0, y: 0, at: 0, held: null, moved: false};
    var lastTap = 0;

    stage.addEventListener('touchstart', function (event) {
      var point = event.touches[0];
      touch.x = point.clientX;
      touch.y = point.clientY;
      touch.at = Date.now();
      touch.moved = false;
      /* Press and hold is the destructive menu. 600ms, long enough that a
       * slow swipe does not open it. */
      touch.held = setTimeout(function () {
        touch.held = null;
        if (!touch.moved) actionSheet();
      }, 600);
    }, {passive: true});

    stage.addEventListener('touchmove', function (event) {
      var point = event.touches[0];
      if (Math.abs(point.clientX - touch.x) > 12
          || Math.abs(point.clientY - touch.y) > 12) {
        touch.moved = true;
        if (touch.held) { clearTimeout(touch.held); touch.held = null; }
      }
    }, {passive: true});

    stage.addEventListener('touchend', function (event) {
      if (touch.held) { clearTimeout(touch.held); touch.held = null; }
      var point = event.changedTouches[0];
      var dx = point.clientX - touch.x;
      var dy = point.clientY - touch.y;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) {
        wake();
        step(dx < 0 ? 1 : -1);
        return;
      }
      /* A vertical swipe is the desktop's up/down: the media filter. */
      if (Math.abs(dy) > 80 && Math.abs(dy) > Math.abs(dx)) {
        wake();
        S.filter = dy < 0 ? 'image' : (S.filter === 'video' ? 'all' : 'video');
        remember({media_filter: S.filter});
        reload();
        return;
      }
      if (touch.moved) return;
      var now = Date.now();
      if (now - lastTap < 320) { lastTap = 0; like(); return; }
      lastTap = now;
      /* One tap wakes the bar; it is only a toggle once the bar is up, so
       * the first touch on a bare screen never hides something. */
      setTimeout(function () {
        if (lastTap !== now) return;
        if (wrap.classList.contains('awake')) {
          wrap.classList.remove('awake');
          if (barTimer) clearTimeout(barTimer);
        } else {
          wake();
        }
      }, 320);
    }, {passive: true});

    /* A keyboard may still be attached - the desk's, over USB - and the
     * desktop app's letters cost nothing to honour. */
    function onKey(event) {
      if (!visible()) return;
      var key = String(event.key || '').toLowerCase();
      var map = {
        ' ': function () { pauseBtn.click(); },
        'arrowright': function () { step(1); },
        'arrowleft': function () { step(-1); },
        'arrowup': function () { S.filter = 'image'; remember({media_filter: 'image'}); reload(); },
        'arrowdown': function () { S.filter = 'video'; remember({media_filter: 'video'}); reload(); },
        'l': like,
        't': function () { transBtn.click(); },
        'f': function () { favBtn.click(); },
        's': function () { openSheet('stack'); },
        'h': function () { openSheet('help'); },
        'delete': actionSheet,
        'backspace': actionSheet,
        'escape': closeSheet
      };
      if (map[key]) { event.preventDefault(); wake(); map[key](); }
    }
    document.addEventListener('keydown', onKey);

    /* ---- the backend overlays --------------------------------------- */

    /* ON BY DEFAULT. "Whenever I would be looking at that slideshow, I would
     * be getting overlays that would be telling me everything that was
     * happening with backend components." The pictures are the background;
     * these are the instrument panel. */
    var overlays = null;
    var overlaysOn = true;
    try {
      overlaysOn = localStorage.getItem('slideshowOverlays') !== '0';
    } catch (err) { overlaysOn = true; }

    function applyOverlays() {
      try { localStorage.setItem('slideshowOverlays', overlaysOn ? '1' : '0'); }
      catch (err) { /* a remembered toggle is not worth a broken view */ }
      if (overlayBtn) overlayBtn.classList.toggle('on', overlaysOn);
      if (overlaysOn && !overlays && root.SparkOverlays) {
        overlays = root.SparkOverlays.mount(wrap, {
          mode: 'overlay',
          /* Nothing is asked of the station unless this view is the one on
           * screen AND the overlay layer is switched on. Pressing S does
           * not just hide the readouts, it stops them being fetched. */
          active: function () { return overlaysOn && visible(); }
        });
      }
      if (overlays) overlays.node.style.display = overlaysOn ? '' : 'none';
      if (!root.SparkOverlays && overlaysOn) {
        say('spark-overlays.js is not on this terminal');
      }
    }

    /* ---- go --------------------------------------------------------- */

    /* HOW MUCH OF THE FOOT BELONGS TO SOMEONE ELSE. console-line.js welds a
     * fixed readout across the bottom of every screen on this terminal, and
     * the control bar was drawn underneath it — the key letters were clipped
     * off every button. Measured rather than assumed, and re-measured on a
     * turn, because the tablet rotates and that line wraps. */
    /* HOW MUCH OF THE RIGHT EDGE BELONGS TO THE RAIL.
     *
     * THE TRAP, and it is a CSS one worth writing down: `.pine-view-host`
     * reserves the rail's strip with `padding-right:34px`, and this view is
     * `position:absolute; inset:0` inside it — so it was assumed to be
     * inset by that padding. IT IS NOT. The containing block for an
     * absolutely positioned child is the padding BOX, which INCLUDES the
     * padding; only in-flow content is pushed in by it. So the panels ran
     * underneath the rail's tabs, which paint over them at z-index
     * 2147483001, and the right-hand figures were simply covered.
     *
     * Measured rather than hardcoded at 34, and re-measured on a turn: the
     * rail's tabs are vertical text and its width follows the font. */
    function measureRail() {
      var rail = document.getElementById('pineViewRail');
      var width = 0;
      if (rail) {
        try {
          var box = rail.getBoundingClientRect();
          if (box.width && box.right >= root.innerWidth - 4) {
            width = Math.round(box.width);
          }
        } catch (err) { width = 0; }
      }
      wrap.style.setProperty('--sl-rail', width + 'px');
    }

    function measureFoot() {
      var line = document.getElementById('pineConsoleLine');
      var height = 0;
      if (line) {
        try {
          var box = line.getBoundingClientRect();
          /* Only if it really is at the foot; a hidden or floated one must
           * not reserve space the bar then leaves empty. */
          if (box.height && box.bottom >= root.innerHeight - 4) {
            height = Math.round(box.height);
          }
        } catch (err) { height = 0; }
      }
      wrap.style.setProperty('--sl-console', height + 'px');
    }
    function measureChrome() { measureFoot(); measureRail(); }
    measureChrome();
    /* AND AGAIN ONCE THE PAGE HAS SETTLED. MEASURED on the tablet: at mount
     * time the rail's own box was 0px wide — it is built at boot but had not
     * been laid out at the instant this view was created — so the readouts
     * were drawn under it and their right-hand figures were covered. rail.js
     * defers its own reopen by 1200ms for the same reason: a view that
     * measures a still-settling document measures the wrong thing. */
    setTimeout(measureChrome, 1400);
    /* A ResizeObserver catches the rest: a tab added, the font changing, the
     * tablet turned. Not every engine has one, and a missing observer must
     * not cost the measurement that already happened. */
    var watcher = null;
    try {
      if (root.ResizeObserver) {
        watcher = new root.ResizeObserver(measureChrome);
        var rail = document.getElementById('pineViewRail');
        if (rail) watcher.observe(rail);
        watcher.observe(document.documentElement);
      }
    } catch (err) { watcher = null; }
    function onResize() { measureChrome(); }
    root.addEventListener('resize', onResize);

    wake();
    applyOverlays();
    restore().then(reload);
    hotTimer = setInterval(hotLoad, HOT_LOAD_MS);
    try { S.camOff = localStorage.getItem(CAM_OFF_KEY) === '1'; }
    catch (err) { S.camOff = false; }
    camAsk();
    camTimer = setInterval(camAsk, CAM_ASK_MS);
    camFrameTimer = setInterval(camDraw, CAM_FRAME_MS);

    return {
      node: wrap,
      state: S,
      reload: reload,
      /* The overlay layer this view owns. A host that embeds the slideshow
       * reads this rather than mounting a SECOND layer on top — which is
       * exactly what /spark?pictures=1 did until the fit probe counted
       * fourteen widgets where there should have been seven. */
      overlays: function () { return overlays; },
      destroy: function () {
        destroyed = true;
        if (timer) clearTimeout(timer);
        if (retryTimer) clearTimeout(retryTimer);
        if (camTimer) clearInterval(camTimer);
        if (camFrameTimer) clearInterval(camFrameTimer);
        if (hotTimer) clearInterval(hotTimer);
        if (barTimer) clearTimeout(barTimer);
        document.removeEventListener('keydown', onKey);
        root.removeEventListener('resize', onResize);
        if (watcher) { try { watcher.disconnect(); } catch (err) { /* gone */ } }
        if (overlays) overlays.destroy();
        layers[0].innerHTML = '';
        layers[1].innerHTML = '';
      }
    };
  }

  root.PineSlideshow = {mount: mount, TRANSITIONS: TRANSITIONS};
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSlideshow;
  }
})(typeof window !== 'undefined' ? window : globalThis);
