/* THE STATION, ON THE LOCKED TABLET.
 *
 * "I want the Pine Box radio to have a splash screen on the lock screen
 * where it's showing me the status of the radio station, the script window,
 * and the media player allowing me to send in requests, interact with the
 * DJs, and review the scripts just from the lock screen of the tablet
 * itself whenever it's closed. Also... the data and information of
 * media_slideshow."
 *
 * WHAT THIS IS, AND WHAT IT IS NOT. It is not a keyguard replacement -
 * replacing the lock screen needs device-owner privilege and this app does
 * not hold it (`dumpsys device_policy` reports Device Owner Type: -1). It
 * is the kiosk's own screen drawn OVER the keyguard, which the manifest
 * already permits: `android:showWhenLocked` and `android:turnScreenOn`.
 * The practical difference is that Android's lock is still underneath; the
 * operator can still swipe it away to reach the rest of the device.
 *
 * WHY IT IS A WEB VIEW AND NOT A NATIVE LAYOUT. Everything on it already
 * exists as a view in this bundle - the station clock and now-playing, the
 * screenplay, the player, the request box, the talk dot. Building a second
 * native version of all of that would mean two accounts of the same
 * things, and the one nobody is looking at drifts. This composes what is
 * already here.
 *
 * THE COST IS ZERO POLLS. It rides PineStationFeed, the same 4 s snapshot
 * every other view reads, and asks for the screenplay and the slideshow on
 * a rest of their own. A lock screen that doubled the terminal's traffic
 * while nobody was even holding it would be a poor trade - this station has
 * a documented history of being starved by chatty clients.
 */
(function (root) {
  'use strict';

  var ID = 'pineLock';
  var SCREENPLAY_REST_MS = 45000;   /* the script is minutes-scale */
  var SLIDESHOW_REST_MS = 30000;
  var PICTURE_MS = 9000;            /* how long one picture holds */

  var host = null;
  var stop = null;
  var beat = 0;
  var shown = false;
  var elements = [];
  var scriptAt = 0;
  var slides = [];
  var slideAt = 0;
  var slideNow = 0;
  var pictureTurn = 0;

  function api() {
    return root.pineDesktop || {get: function () {
      return Promise.reject(new Error('no bridge'));
    }};
  }

  function el(id) { return document.getElementById(id); }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function clock(value) {
    var d = new Date(Number(value) || Date.now());
    return String(d.getHours()).padStart(2, '0') + ':'
      + String(d.getMinutes()).padStart(2, '0');
  }

  /* ------------------------------------------------------------- build */

  function build() {
    if (el(ID)) return el(ID);
    host = make('div', 'lk-screen');
    host.id = ID;
    host.hidden = true;
    host.innerHTML =
      /* The picture behind everything - the slideshow's own material. */
      '<img id="lkArt" class="lk-art" alt="">'
      + '<div class="lk-shade"></div>'

      + '<div class="lk-grid">'

      /* 1 - the station, and the time. */
      + '<header class="lk-head">'
      + '<div class="lk-when"><b id="lkClock">--:--</b>'
      + '<i id="lkDate"></i></div>'
      + '<div class="lk-who"><b id="lkStation">Pine Box</b>'
      + '<i id="lkAir" class="lk-air">checking…</i></div>'
      /* THE WAY OUT, and it is not optional.
       *
       * This screen is drawn OVER Android's keyguard, which means it also
       * covers the keyguard's own unlock gesture - the operator found the
       * tablet "stuck on a lock screen" and he was right: there was
       * nothing on it that let go. Any view that covers the lock must
       * carry its own exit, in plain sight, sized for a thumb. */
      + '<button id="lkOut" class="lk-out" type="button" '
      + 'aria-label="put this away and unlock">✕</button>'
      + '</header>'

      /* 2 - what is on, and the transport. */
      + '<section class="lk-now">'
      + '<img id="lkCover" class="lk-cover" alt="" hidden>'
      + '<div class="lk-nowtext">'
      + '<b id="lkTitle">—</b><i id="lkBy"></i>'
      + '<div class="lk-barwrap"><span id="lkBar" class="lk-bar"></span></div>'
      + '<i id="lkClockRow" class="lk-dim"></i>'
      + '</div>'
      + '<div class="lk-transport">'
      + '<span id="lkVote"></span>'
      + '<button id="lkPrev" class="lk-btn" type="button">‹‹</button>'
      + '<button id="lkSkip" class="lk-btn" type="button">››</button>'
      + '</div>'
      + '</section>'

      /* 3 - the script, live. */
      + '<section class="lk-script">'
      + '<h4>The script <i id="lkScriptWhy" class="lk-dim"></i></h4>'
      + '<div id="lkScriptBody" class="lk-scriptbody"></div>'
      + '</section>'

      /* 4 - ask for something, without unlocking. */
      + '<section class="lk-ask">'
      + '<input id="lkAsk" class="lk-input" type="search" '
      + 'placeholder="ask for a record, or say something to the DJs" '
      + 'autocomplete="off" spellcheck="false">'
      + '<div id="lkHits" class="lk-hits" hidden></div>'
      + '<i id="lkSaid" class="lk-dim"></i>'
      + '</section>'

      /* 5 - the slideshow, named. */
      + '<footer class="lk-foot">'
      + '<i id="lkSlides" class="lk-dim"></i>'
      + '</footer>'

      + '</div>';
    document.body.appendChild(host);
    wire();
    return host;
  }

  function wire() {
    var out = el('lkOut');
    if (out) out.addEventListener('click', function (event) {
      event.stopPropagation();
      hide();
    });

    /* A second way out, because one button can be missed: a long press
     * anywhere on the screen also puts it away. Deliberately long, so it
     * cannot fire while somebody is reading the script. */
    var held = 0;
    host.addEventListener('pointerdown', function () {
      clearTimeout(held);
      held = setTimeout(hide, 1100);
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (name) {
      host.addEventListener(name, function () { clearTimeout(held); });
    });

    var prev = el('lkPrev');
    var skip = el('lkSkip');
    if (prev) prev.addEventListener('click', function (e) {
      e.stopPropagation();
      api().post('/api/dj/prev', {});
    });
    if (skip) skip.addEventListener('click', function (e) {
      e.stopPropagation();
      api().post('/api/dj/next', {});
    });

    /* Tapping the picture moves the slideshow on, the way tapping the wall
     * does - the same gesture meaning the same thing in two places. */
    var art = el('lkArt');
    if (art) art.addEventListener('click', function () { nextPicture(true); });

    /* The arrows, on the same record the player is showing. A function,
     * not a value: the record changes under the control. */
    var seat = el('lkVote');
    if (seat && root.PineVote) {
      root.PineVote.mount(seat, function () { return nowTrack; }, say);
    }

    wireAsk();
  }

  /* What the player is currently showing, for the vote arrows. */
  var nowTrack = {};

  /* ---------------------------------------------------------- the ask */

  /* ONE BOX, TWO KINDS OF SENTENCE.
   *
   * A record is searched and requested; anything else goes to the station
   * the same way a spoken command does - /v1/chat/completions, the door
   * the Nabu speaks through - so "tell Skip he was right" works from the
   * lock screen without unlocking anything. */
  function wireAsk() {
    var box = el('lkAsk');
    var hits = el('lkHits');
    if (!box) return;
    var timer = 0;

    box.addEventListener('input', function () {
      clearTimeout(timer);
      var q = box.value.trim();
      if (q.length < 2) { if (hits) hits.hidden = true; return; }
      timer = setTimeout(function () { look(q); }, 240);
    });

    box.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      var text = box.value.trim();
      if (!text) return;
      box.value = '';
      if (hits) hits.hidden = true;
      talk(text);
    });

    if (root.PineDismiss && hits) {
      root.PineDismiss.watch(hits, function () { hits.hidden = true; }, [box]);
    }
  }

  function look(q) {
    var hits = el('lkHits');
    if (!hits) return;
    api().get('/api/music/search?q=' + encodeURIComponent(q) + '&limit=6')
      .then(function (got) {
        var rows = (got && (got.rows || got.tracks || got.results)) || [];
        hits.replaceChildren();
        if (!rows.length) { hits.hidden = true; return; }
        rows.slice(0, 6).forEach(function (row) {
          var line = make('button', 'lk-hit');
          line.type = 'button';
          line.appendChild(make('b', '', String(row.title || row.track || row.name || '')));
          line.appendChild(make('i', '', String(row.artist || '')));
          line.addEventListener('click', function (event) {
            event.stopPropagation();
            hits.hidden = true;
            var box = el('lkAsk');
            if (box) box.value = '';
            ask(String(row.title || row.track || row.name || ''), row.id);
          });
          hits.appendChild(line);
        });
        hits.hidden = false;
      }, function () { hits.hidden = true; });
  }

  function say(text, bad) {
    var line = el('lkSaid');
    if (!line) return;
    line.textContent = String(text || '');
    line.classList.toggle('bad', !!bad);
    clearTimeout(line.__timer);
    line.__timer = setTimeout(function () { line.textContent = ''; }, 9000);
  }

  function ask(title, id) {
    say('asking for ' + title + '…');
    api().post('/api/dj/request', {q: title, id: id || '', now: true})
      .then(function (got) {
        say(String((got && (got.reply || got.detail)) || ('asked for ' + title)));
      }, function (err) {
        say('the station refused that: ' + ((err && err.message) || err), true);
      });
  }

  /* Anything that is not a record goes where a spoken command goes. */
  function talk(text) {
    say('"' + text + '" — sending…');
    api().post('/v1/chat/completions', {
      messages: [{role: 'user', content: text}]
    }).then(function (done) {
      var said = '';
      try {
        var choice = (done && done.choices && done.choices[0]) || {};
        said = String((choice.message && choice.message.content) || '').trim();
      } catch (err) { /* an odd shape is not a failure to act */ }
      say(said || 'sent.');
    }, function (err) {
      say('the station refused that: ' + ((err && err.message) || err), true);
    });
  }

  /* ------------------------------------------------------------ paint */

  function paint(state) {
    if (!shown || !state) return;

    var at = Date.now();
    var c = el('lkClock');
    if (c) c.textContent = clock(at);
    var d = el('lkDate');
    if (d) {
      d.textContent = new Date(at).toLocaleDateString(undefined,
        {weekday: 'long', day: 'numeric', month: 'long'});
    }

    var station = el('lkStation');
    if (station) station.textContent = state.station_name || state.station || 'Pine Box';

    /* THE AIR, said the way the rail says it - the same words in both
     * places, so the operator is never comparing two vocabularies. */
    var air = el('lkAir');
    if (air) {
      var word = state.paused ? 'air paused'
        : state.on ? (state.speaking ? 'on air · talking' : 'on air')
          : 'off air';
      air.textContent = word;
      air.dataset.state = state.paused ? 'paused' : state.on ? 'on' : 'off';
    }

    var now = state.now || {};
    nowTrack = {id: now.id || '', title: now.track || now.title || ''};
    var title = el('lkTitle');
    var by = el('lkBy');
    if (title) title.textContent = String(now.track || now.title || '—');
    if (by) by.textContent = String(now.artist || '');

    var cover = el('lkCover');
    if (cover) {
      var art = now.art || now.cover || '';
      if (art) { cover.src = String(art); cover.hidden = false; }
      else { cover.removeAttribute('src'); cover.hidden = true; }
    }

    var length = Number(state.length || now.length || 0);
    var gone = Number(state.elapsed || 0);
    var bar = el('lkBar');
    if (bar) {
      var pct = length > 0 ? Math.max(0, Math.min(100, (gone / length) * 100)) : 0;
      bar.style.width = pct.toFixed(1) + '%';
    }
    var row = el('lkClockRow');
    if (row) {
      row.textContent = length > 0
        ? spell(gone) + ' / ' + spell(length)
        : (state.playing ? 'playing' : '');
    }
  }

  function spell(seconds) {
    var s = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  /* ---------------------------------------------------------- the script */

  function readScript(force) {
    if (!shown) return;
    var now = Date.now();
    if (!force && now - scriptAt < SCREENPLAY_REST_MS) return;
    scriptAt = now;
    api().get('/api/screenplay').then(function (index) {
      var hours = (index && index.hours) || [];
      if (!hours.length) throw new Error('nothing written yet');
      return api().get('/api/screenplay/'
        + encodeURIComponent(String(hours[0].key || '')));
    }).then(function (page) {
      elements = (page && page.elements) || [];
      paintScript(page);
    }, function (err) {
      var body = el('lkScriptBody');
      if (body && !body.children.length) {
        body.appendChild(make('p', 'lk-dim',
          'the script could not be read: ' + ((err && err.message) || err)));
      }
    });
  }

  /* THE TAIL OF THE HOUR, not the whole of it. A lock screen is read at
   * arm's length for a few seconds; the last dozen elements are what
   * "review the scripts" means here, and the Script view is a tab away for
   * the rest. */
  function paintScript(page) {
    var body = el('lkScriptBody');
    if (!body) return;
    var why = el('lkScriptWhy');
    if (why && page) {
      why.textContent = (page.title || '') +
        (page.live ? '  ·  live' : '');
    }
    body.replaceChildren();
    var tail = elements.slice(-14);
    tail.forEach(function (item) {
      var type = String(item.type || 'action');
      var node = make('div', 'lk-el lk-' + type);
      node.textContent = String(item.text || '');
      if (item.line) node.dataset.line = String(item.line);
      body.appendChild(node);
    });
    body.scrollTop = body.scrollHeight;
  }

  /* ------------------------------------------------------- the pictures */

  /* THE SLIDESHOW'S OWN MATERIAL.
   *
   * /api/slideshow reports what is in the ComfyUI output folder - the very
   * directory `~/bin/media-slideshow` plays from. It cannot report whether
   * that app is RUNNING (the station is in a container with no shared PID
   * namespace) and it cannot read its diagnostic (/home/ehm_eckx/bin is
   * not mounted), so this shows the pictures and says how many there are,
   * which is the part that is true. */
  function readSlides(force) {
    if (!shown) return;
    var now = Date.now();
    if (!force && now - slideAt < SLIDESHOW_REST_MS) return;
    slideAt = now;
    api().get('/api/slideshow?limit=40').then(function (got) {
      if (!got || !got.ok) {
        var note = el('lkSlides');
        if (note) note.textContent = String((got && got.say) || '');
        return;
      }
      slides = (got.rows || []).map(function (r) {
        return String(got.url || '/api/generations/image/')
          + encodeURIComponent(String(r.file || ''));
      }).filter(Boolean);
      var note = el('lkSlides');
      if (note) {
        note.textContent = got.playlist + ' pictures in the slideshow'
          + (got.newest_age != null
            ? '  ·  newest ' + spellAge(got.newest_age) : '');
      }
      if (slides.length && !(el('lkArt') || {}).getAttribute) return;
      if (slides.length && !el('lkArt').getAttribute('src')) nextPicture(false);
    }, function () { /* the pictures are decoration; never shout */ });
  }

  function spellAge(seconds) {
    var s = Number(seconds) || 0;
    if (s < 90) return Math.round(s) + 's ago';
    if (s < 5400) return Math.round(s / 60) + 'm ago';
    return Math.round(s / 3600) + 'h ago';
  }

  /* A GRACEFUL CHANGE, NOT A FLASH.
   *
   * "Check into what causes the transitions to have a flash whenever
   * they're changing out between the images... I want that image to be
   * slowly panning and moving on the screen, scaling in or zooming out."
   *
   * THE FLASH HAD A CAUSE. One <img> was faded to zero, its `src` was
   * swapped, and it was faded back - so for as long as the new picture
   * took to arrive over the network there was nothing in the element at
   * all, and the lock screen's dark ground showed through. A gallery
   * picture here is over a megabyte; that gap is easily long enough to
   * read as a blink. Fading a not-yet-loaded image is fading to nothing.
   *
   * So there are TWO layers and the next picture is fully decoded before
   * anything moves: load underneath, cross-fade over, swap the roles. The
   * screen is never without a picture, so there is nothing to flash.
   *
   * AND IT MOVES WHILE IT SITS. Each picture is given a slow drift - a
   * push in some direction and a scale that goes the opposite way from the
   * last one, so a zoom-in is followed by a zoom-out rather than a series
   * of identical creeps. Done in CSS, on the compositor, where it costs
   * this tablet nothing.
   */
  var layers = [];
  var front = 0;
  var drift = 0;

  function layerFor(n) {
    if (layers.length) return layers[n];
    var a = el('lkArt');
    if (!a) return null;
    /* The second layer is made from the first, so it inherits every rule
     * rather than needing its own. */
    /* IDEMPOTENT, for the same reason the Listen backdrop is: a remount
     * clears this module's `layers` while the element it made last time is
     * still in the document, and the layers accumulate. */
    var b = document.getElementById('lkArt2');
    if (!b) {
      b = a.cloneNode(false);
      b.id = 'lkArt2';
      b.style.opacity = '0';
      a.parentNode.insertBefore(b, a.nextSibling);
    }
    layers = [a, b];
    return layers[n];
  }

  function nextPicture(byHand) {
    if (!slides.length) return;
    if (!layerFor(0)) return;
    slideNow = (slideNow + 1) % slides.length;
    pictureTurn = Date.now();

    var back = layers[1 - front];
    var show = layers[front];
    var src = slides[slideNow];

    /* DECODE FIRST. Nothing on screen changes until the picture is
     * actually there - that is the whole cure for the flash. */
    var pre = new Image();
    pre.onload = function () {
      back.src = src;
      /* Start the new one from its own corner, so the drift has somewhere
       * to go, and alternate the direction each time. */
      drift = (drift + 1) % 4;
      back.className = 'lk-art lk-drift-' + drift;
      back.style.opacity = '1';
      show.style.opacity = '0';
      front = 1 - front;
    };
    pre.onerror = function () {
      /* A picture that will not load is skipped rather than shown as a
       * hole - and the turn is not wasted. */
      if (slides.length > 1) setTimeout(function () { nextPicture(false); }, 60);
    };
    pre.src = src;
    if (byHand && pre.complete) pre.onload();
  }

  /* ------------------------------------------------------- show / hide */

  function show() {
    build();
    if (shown) return true;
    shown = true;
    host.hidden = false;
    document.body.classList.add('pine-locked');

    var feed = root.PineStationFeed;
    if (feed && typeof feed.subscribe === 'function' && !stop) {
      stop = feed.subscribe(function (payload) {
        paint((payload && payload.station) || payload || {});
      });
    }
    readScript(true);
    readSlides(true);

    /* One clock for the whole screen: the time, the picture turn, and the
     * two rests. Nothing here has a timer of its own. */
    if (!beat) {
      beat = setInterval(function () {
        if (!shown) return;
        var c = el('lkClock');
        if (c) c.textContent = clock(Date.now());
        if (Date.now() - pictureTurn > PICTURE_MS) nextPicture(false);
        readScript(false);
        readSlides(false);
      }, 1000);
    }
    return true;
  }

  function hide() {
    if (!shown) return false;
    shown = false;
    if (host) host.hidden = true;
    document.body.classList.remove('pine-locked');
    if (stop) { stop(); stop = null; }
    if (beat) { clearInterval(beat); beat = 0; }
    return true;
  }

  root.PineLock = {
    show: show, hide: hide, build: build,
    isShowing: function () { return shown; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineLock;
})(typeof window !== 'undefined' ? window : globalThis);
