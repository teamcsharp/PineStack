/* THE SCRIPT VIEW, BUILT TO THE SKETCH.
 *
 * The operator numbered seven regions and said what each one is. They are
 * marked 1..7 through this file so the code and the drawing can be read
 * against each other:
 *
 *   1  back to the ordinary view          top-left, three small buttons
 *   2  a menu of every view
 *   3  reload / re-fit this view
 *   4  the pine tree - taps open a Pine Box panel
 *   5  the media player: art, spectrum, meter, a playhead you can scrub,
 *      and back/forward across tracks
 *   6  the live feed, "like an instant message correspondence", endless and
 *      auto-scrolling
 *   7  the right HALF of the screen: a Hollywood script of the broadcast,
 *      generated live, scrollable, tappable, editable, sendable back to the
 *      recording room
 *
 * WHERE THE SCRIPT COMES FROM, and why this is not a rendering of the feed.
 * #1050 already writes a real screenplay: GET /api/screenplay/{hour} returns
 * typed elements - scene, subheader, character, dialogue, parenthetical,
 * action, transition - with each dialogue carrying the aired line id, its
 * engine, whether it was tinted and its clip. Measured on the live station:
 * 127 elements for one hour, 63 of them dialogue. So this view FORMATS a
 * script the station already generates, rather than inventing one out of
 * chat rows, and the tap targets are real line ids that the rest of the
 * machinery already understands.
 *
 * THE TRAFFIC RULE. One shared feed subscription for the live half (the
 * ticker, the player, the console line) and ONE fetch of the screenplay,
 * refreshed on a slow clock and on demand. Nothing here polls at speed.
 * That rule is not decorative: 38 concurrent requests were measured
 * starving this tablet's audio for 46 seconds.
 */
(function (root) {
  'use strict';

  var HOST_CLASS = 'sp-page';
  var SCREENPLAY_REST_MS = 20000;   /* the script is minutes-scale news */
  var FEED_MAX = 240;               /* the booth ring's own size */

  var mounted = false;
  var host = null;
  var stop = null;
  var elements = [];
  var hourKey = '';
  var scriptNodes = new Map();      /* #1273: element id -> its live node */
  var paintedIn = null;             /* #1273: the box those nodes hang in */
  var chasedAt = 0;                 /* #1271: last re-read chased by a mark */
  var beforeKey = '';               /* #1276: the closed hour we hold */
  var beforePage = null;            /*         and its page, fetched once */
  /* #1269: the join between an element's id and its text. A character no
     id or text can contain, written as an ESCAPE - an earlier patch put a
     real NUL byte in this file, which every text tool then read as binary. */
  var SEP = '\u0000';
  var fetchedAt = 0;
  var fetching = false;
  var pinned = null;                /* the element the operator tapped */
  var stick = true;                 /* keep the script scrolled to the end */
  var feedStick = true;
  var seen = Object.create(null);   /* feed rows already drawn */
  var feedNodes = Object.create(null);  /* #1279: id -> its live row */
  var feedLive = '';                    /* #1279: the row marked airing */

  /* FOLLOWING THE LINE THAT IS ACTUALLY BEING SAID.
   *
   * "I need the currently spoken line that is being said to be the line
   * being highlighted... It is highlighting 20 lines."
   *
   * It was highlighting 71, and for a reason that had nothing to do with
   * speech: the amber marker went on any element whose `aired` was not the
   * string 'stream', and the screenplay's three values are 'published'
   * (59), 'stream' (43) and 'prepared' (12). 'published' means it ALREADY
   * AIRED. So the mark was on most of the hour.
   *
   * The live position is not in the screenplay at all - it is in the
   * station's `stream_now`: the epoch second the burst began, its length,
   * and every row's from/until offset inside it. That is enough to know
   * which line is in the room RIGHT NOW without asking, so the highlight
   * moves on a local 250 ms tick against a 4 s poll - the cadence the
   * codebase already prescribes ("the round clock every 250 ms,
   * speaking_now every 4 s"), and no extra traffic for a station with a
   * documented history of being starved by chatty clients. */
  var liveStream = null;            /* stream_now, as last polled */
  var speakingNow = null;           /* the 4 s fallback */
  var flow = null;                  /* dialogue_flow: why it is waiting */
  var stationPaused = false;
  var skewMs = 0;                   /* server clock minus ours */
  var lastOffMs = 0;                /* #1267: watched, no longer applied */
  var nowLineId = '';               /* the one line being said */
  var follow = true;                /* keep it on screen */
  var selfScrollUntil = 0;          /* a scroll WE started, not the operator */
  var beat = 0;

  function api() { return root.pineDesktop || {get: function () { return Promise.reject(new Error('no bridge')); }}; }
  function el(id) { return document.getElementById(id); }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* ------------------------------------------------------------ 1, 2, 3 */

  function buildBar() {
    var bar = make('div', 'sp-bar');

    /* 1 - back to the ordinary view. */
    var back = make('button', 'sp-btn', '←');
    back.title = 'Back to the full Pine Box application';
    back.addEventListener('click', function () {
      if (root.PineViewChrome) root.PineViewChrome.show('control');
      var tech = el('pineViewTab-tech');
      if (tech) tech.click();
    });

    /* 2 - every view, as a menu. A <select> on purpose: the platform's own
     * picker is reachable with a thumb and needs no popup of my own. */
    var pick = make('select', 'sp-pick');
    var views = (root.PineViewChrome && root.PineViewChrome.VIEWS) || [];
    var head = make('option', '', 'views');
    head.value = '';
    pick.appendChild(head);
    for (var i = 0; i < views.length; i += 1) {
      var opt = make('option', '', views[i].label);
      opt.value = views[i].id;
      pick.appendChild(opt);
    }
    pick.addEventListener('change', function () {
      if (!pick.value) return;
      var tab = el('pineViewTab-' + pick.value);
      if (tab) tab.click();
      else if (root.PineViewChrome) root.PineViewChrome.show(pick.value);
      pick.value = '';
    });

    /* 3 - reload / re-fit. Re-reads the script and re-measures the layout,
     * which is the honest meaning of "adjust the view": anything sized by a
     * grid has no geometry until it is visible. */
    var again = make('button', 'sp-btn', '↻');
    again.title = 'Re-read the script and re-fit the view';
    again.addEventListener('click', function () {
      fetchedAt = 0;
      loadScreenplay(true);
      try { root.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
    });

    bar.appendChild(back);
    bar.appendChild(pick);
    bar.appendChild(again);
    return bar;
  }

  /* ---------------------------------------------------------------- 4 */

  /* The tree opens the Pine Box panel. On the tablet that panel already
   * exists as the native drawer - broadcast, routing, the device list - so
   * the tree hands it over rather than building a second one that would
   * drift from it. Where there is no drawer, a small sheet stands in. */
  function buildTree() {
    var tree = make('button', 'sp-tree');
    tree.title = 'Pine Box - broadcast, levels and settings';
    tree.setAttribute('aria-label', 'Pine Box');
    tree.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<path d="M12 2 L17 9 H14 L18.5 15 H14.5 L20 21 H4 L9.5 15 H5.5 L10 9 H7 Z"/>'
      + '<rect x="11" y="21" width="2" height="2"/></svg>';
    tree.addEventListener('click', function () {
      if (root.PineViewChrome && root.PineViewChrome.openMenu() !== 'sheet') return;
      togglePanel();
    });
    return tree;
  }

  function togglePanel() {
    var box = el('spPanel');
    if (!box) return;
    box.hidden = !box.hidden;
  }

  function buildPanel() {
    var box = make('div', 'sp-panel');
    box.id = 'spPanel';
    box.hidden = true;
    box.appendChild(make('h4', '', 'Pine Box'));
    var rows = [
      ['Give this terminal the air', 'solo'],
      ['Let every page sound', 'clear'],
      ['Re-read the script', 'reload']
    ];
    for (var i = 0; i < rows.length; i += 1) {
      (function (label, action) {
        var b = make('button', 'sp-panel-row', label);
        b.addEventListener('click', function () { panelAction(action, b); });
        box.appendChild(b);
      })(rows[i][0], rows[i][1]);
    }
    box.appendChild(make('p', 'sp-panel-why',
      'The full desk - broadcast routing, levels and settings - is in the '
      + 'drawer: swipe in from the left edge.'));
    return box;
  }

  function panelAction(action, button) {
    var was = button.textContent;
    if (action === 'reload') { fetchedAt = 0; loadScreenplay(true); return; }
    button.textContent = 'working...';
    var body = action === 'solo'
      ? {listener: (typeof root.pineListenerId === 'function') ? root.pineListenerId() : ''}
      : {clear: true};
    api().post('/api/radio/solo', body).then(function () {
      button.textContent = was;
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 40);
    });
  }

  /* ---------------------------------------------------------------- 5 */

  function buildPlayer() {
    var box = make('div', 'sp-player');
    box.innerHTML =
      '<img id="spArt" class="sp-art" alt="">'
      + '<div class="sp-playmid">'
      + '<div id="spTitle" class="sp-title"></div>'
      + '<div id="spWho" class="sp-who"></div>'
      + '<canvas id="spSpectrum" class="sp-spectrum"></canvas>'
      + '<canvas id="spVoice" class="sp-voicemeter"></canvas>'
      + '<div class="sp-seekrow">'
      + '<i id="spAt" class="sp-time"></i>'
      + '<input id="spSeek" class="sp-seek" type="range" min="0" max="1000" value="0">'
      + '<i id="spLen" class="sp-time"></i>'
      + '</div></div>'
      + '<div class="sp-transport">'
      + '<button id="spPrev" class="sp-tbtn" title="The station’s previous track">⏮</button>'
      + '<button id="spNext" class="sp-tbtn" title="Skip to the next track">⏭</button>'
      + '</div>';
    return box;
  }

  /* THE PLAYHEAD IS A REAL SCRUB, and it moves THIS terminal's player.
   *
   * The station owns the broadcast clock; there is no route to move it, and
   * inventing one would desync every other listener. What this scrubs is the
   * element playing here - which is what a hand on a playhead means on the
   * device in front of you - and the labels say the position honestly. Back
   * and forward DO move the station's queue, because those routes exist
   * (/api/dj/prev, /api/dj/next) and skipping is a thing the whole house
   * hears by design. */
  function wirePlayer() {
    var seek = el('spSeek');
    var player = function () { return el('musicPlayer'); };
    var dragging = false;
    if (seek) {
      seek.addEventListener('pointerdown', function () { dragging = true; });
      var release = function () { dragging = false; };
      ['pointerup', 'pointercancel'].forEach(function (n) {
        seek.addEventListener(n, release);
      });
      seek.addEventListener('input', function () {
        var p = player();
        if (!p || !isFinite(p.duration) || !p.duration) return;
        p.currentTime = (Number(seek.value) / 1000) * p.duration;
      });
    }
    seek && (seek.dataset.dragging = '');
    var prev = el('spPrev');
    var next = el('spNext');
    if (prev) prev.addEventListener('click', function () { api().post('/api/dj/prev', {}); });
    if (next) next.addEventListener('click', function () { api().post('/api/dj/next', {}); });

    /* The meters and the playhead ride requestAnimationFrame - numbers the
     * browser already has, no request of any kind. */
    var frame = 0;
    var tick = function () {
      frame = requestAnimationFrame(tick);
      var spectrum = el('spSpectrum');
      if (!spectrum || !spectrum.isConnected || !spectrum.clientWidth) return;
      var meters = root.PineMeters;
      if (meters) {
        meters.attach(['musicPlayer', 'djVoiceAudio0', 'djVoiceAudio1']);
        meters.draw(spectrum, meters.read('musicPlayer', 'music'), '#54d18b');
        meters.draw(el('spVoice'),
          meters.readLoudest(['djVoiceAudio0', 'djVoiceAudio1'], 'voice'), '#e3be63');
      }
      var p = player();
      if (p && isFinite(p.duration) && p.duration) {
        if (seek && !dragging) seek.value = String(Math.round((p.currentTime / p.duration) * 1000));
        var at = el('spAt'); var len = el('spLen');
        if (at) at.textContent = clock(p.currentTime);
        if (len) len.textContent = clock(p.duration);
      }
    };
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
    document.addEventListener('pointerdown', function () {
      if (root.PineMeters) root.PineMeters.wake();
    });
  }

  function clock(v) {
    var t = Math.max(0, Math.round(Number(v) || 0));
    var m = Math.floor(t / 60);
    var s = t % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function paintPlayer(state) {
    var now = (state && state.now) || {};
    var art = el('spArt');
    if (art) {
      var want = now.art || '';
      if (art.dataset.want !== want) {
        art.dataset.want = want;
        if (want) { art.src = want; art.hidden = false; }
        else { art.removeAttribute('src'); art.hidden = true; }
      }
      art.onerror = function () { art.hidden = true; };
    }
    var title = el('spTitle');
    if (title) title.textContent = now.title || 'the station';
    var who = el('spWho');
    if (who) {
      who.textContent = [now.artist, now.album].filter(Boolean).join(' · ');
    }
  }

  /* ---------------------------------------------------------------- 6 */

  /* "Like an instant message correspondence" - newest at the bottom,
   * endless, auto-scrolling. APPEND ONLY: the whole reason this reads as a
   * conversation rather than a table is that rows never move once written.
   * Rebuilding the list each tick would also throw away the operator's
   * scroll position, which is the one thing an endless feed must not do. */
  function paintFeed(state) {
    var box = el('spFeed');
    if (!box) return;
    /* #1279: KEPT AND RE-SEATED, NOT APPENDED AND FROZEN.
     *
     * This drew each id once, in first-appearance order, and never
     * moved or refreshed it. That would be fine if rows arrived in the
     * order they sound - but a burst is published up to 58.8 SECONDS
     * before any of it is audible (measured; mean 5.7 future-stamped
     * rows per poll). Replayed against a real 16-poll sequence this
     * function's order came out 104 of 253 pairs discordant - 41.1% -
     * with interjections that sound 13-40s EARLIER parked underneath
     * lines nobody had said yet, for the life of the pane.
     *
     * Rows are held by id now and put back in `air_at` order on every
     * paint. That key is itself a moving target, but re-seating lets
     * the feed CORRECT ITSELF when a stamp moves instead of being
     * frozen wrong. Their words and state are refreshed too: a row
     * drawn while `prepared` used to still read `prepared` long after
     * it had aired. */
    var rows = (state && state.chat) || [];
    var added = 0;
    var want = [];
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var id = String((row && row.id) || '');
      if (!id) continue;
      var node = feedNodes[id];
      if (!node) {
        node = feedRow(row);
        feedNodes[id] = node;
        seen[id] = true;
        added += 1;
      } else {
        feedDress(node, row);
      }
      node.pineAt = Number(row.air_at || row.ts || 0);
      want.push(node);
    }
    if (want.length) {
      want.sort(function (a, b) { return a.pineAt - b.pineAt; });
      var cursor = box.firstChild;
      for (var w = 0; w < want.length; w += 1) {
        if (want[w] === cursor) { cursor = cursor.nextSibling; continue; }
        box.insertBefore(want[w], cursor);
      }
    }
    /* The station also does things that are not speech. */
    var log = (state && state.activity_log) || [];
    for (var k = 0; k < log.length; k += 1) {
      var ev = log[k];
      var key = 'ev' + (ev && ev.at) + String((ev && ev.stage) || '');
      if (!ev || seen[key]) continue;
      seen[key] = true;
      box.appendChild(eventRow(ev));
      added += 1;
    }
    if (!added) return;
    /* Endless, but not unbounded: this screen runs for hours. */
    /* #1279: a trimmed row must be FORGOTTEN as well as removed. The
       node map would otherwise still hold it, and the next paint would
       put it straight back - an unbounded pane that resurrects its own
       history. `seen` is left alone: it is what stops a trimmed row
       being counted as newly arrived. */
    while (box.children.length > FEED_MAX) {
      var old = box.firstChild;
      var oldId = old && old.getAttribute && old.getAttribute('data-line');
      box.removeChild(old);
      if (oldId) {
        delete feedNodes[oldId];
        if (feedLive === oldId) feedLive = '';
      }
    }
    if (feedStick) box.scrollTop = box.scrollHeight;
  }

  function feedRow(row) {
    var who = String(row.who || 'dj');
    /* #1279: NOT from `row.aired === "airing"`. That is spelled right
       and is unreachable - `airing` is attached only to speaking_now /
       stream_now, never to a chat row (measured: 0 of 317 across 16
       polls), so this pane has never once marked the line being said.
       markFeedLive() does it from the live pointer, every tick. */
    var line = make('div', 'sp-msg');
    line.dataset.line = String(row.id || '');
    line.appendChild(make('b', 'sp-msg-who', row.name || who));
    line.appendChild(make('span', 'sp-msg-text', ''));
    feedDress(line, row);
    line.addEventListener('click', function () { jumpToLine(String(row.id || '')); });
    return line;
  }

  /* #1279: a row's words and state as they are NOW. A row used to be
     drawn once and never touched again, so one drawn while it was
     `prepared` still read `prepared` long after it had aired. */
  function feedDress(line, row) {
    var head = line.firstChild;
    var body = line.lastChild;
    var name = String(row.name || row.who || 'dj');
    var text = String(row.text || '').trim();
    if (head && head.textContent !== name) head.textContent = name;
    if (body && body.textContent !== text) body.textContent = text;
    var state = String(row.aired || '');
    if (line.pineState !== state) {
      line.pineState = state;
      line.classList.toggle('pending', state === 'prepared');
    }
  }

  /* #1279: THE LINE THAT IS SOUNDING, marked from the live pointer and
     re-asserted on every tick, so it cannot be stranded by a row that
     was drawn before it started. */
  function markFeedLive(id) {
    var want = String(id || '');
    if (want === feedLive) return;
    var was = feedLive && feedNodes[feedLive];
    if (was) was.classList.remove('airing');
    feedLive = want;
    var node = want && feedNodes[want];
    if (node) node.classList.add('airing');
  }

  function eventRow(ev) {
    var line = make('div', 'sp-msg sp-msg-ev');
    line.appendChild(make('b', 'sp-msg-who', String(ev.stage || 'station')));
    line.appendChild(make('span', 'sp-msg-text', String(ev.detail || '')));
    return line;
  }

  /* ---------------------------------------------------------------- 7 */

  function loadScreenplay(force) {
    var now = Date.now();
    if (fetching) return;
    if (!force && now - fetchedAt < SCREENPLAY_REST_MS) return;
    /* #1273b: a FORCED read is one the page asked for because the line
       it needs is missing (#1271). Asking for the cached copy would
       hand back the very page that just failed to contain it - measured
       16.1s old, against 2.1s with `fresh`. The rest poll stays cached,
       and so does the hour before: it is closed, 238 kB, and the server
       holds it for fifteen minutes. */
    var live = force ? '?fresh=1' : '';
    fetching = true;
    api().get('/api/screenplay').then(function (index) {
      var hours = (index && index.hours) || [];
      if (!hours.length) throw new Error('no hours written yet');
      hourKey = String(hours[0].key || '');
      /* #1268: THE READING DOES NOT END BECAUSE THE HOUR DID.
       *
       * "I want to put on my reading glasses and watch the pine box go
       *  through an endless reading that is endlessly streamed."
       *
       * This asked for hours[0] and nothing else, so at the top of
       * every hour the whole script was replaced by a nearly empty
       * page - measured at the 3 PM turn, 350 entries down to 0 - and
       * the reader's place went with it. Worse, a burst that straddles
       * the turn is still SOUNDING while the lines it is saying have
       * just left the page, so the highlight has nothing to land on.
       *
       * The hour before is carried too, above it and in order. The
       * window stays bounded: as the clock rolls, hours[1] becomes the
       * hour that just ended and the one before it drops off the top,
       * so this is always one to two hours of script and never grows.
       */
      var before = hours[1] && Number(hours[1].lines || 0) > 0
        ? String(hours[1].key || '') : '';
      /* #1276: THE HOUR THAT IS OVER IS FETCHED ONCE.
       *
       * This asked for both hours on every poll AND every chase. The
       * earlier hour is 238 kB, it is closed, and the server holds it
       * for fifteen minutes - the answer cannot change. Worse,
       * `fetching` is one latch across the whole Promise.all, so while
       * that 238 kB was in flight the #1271 chase returned at
       * `if (fetching) return;` and the live line could not be
       * collected. Measured on the tablet: thirty seconds after opening
       * the view, script rendered, nothing lit, because the sounding
       * line was not on the page yet.
       *
       * It is kept until the clock rolls and a different hour becomes
       * the one before. */
      var want = [api().get('/api/screenplay/'
        + encodeURIComponent(hourKey) + live)];
      if (before && before === beforeKey && beforePage) {
        want.push(Promise.resolve(beforePage));        /* already held */
      } else if (before) {
        want.push(api().get('/api/screenplay/' + encodeURIComponent(before))
          .then(function (page) {
            beforeKey = before; beforePage = page; return page;
          }, function () { return null; }));   /* its loss is survivable */
      } else {
        beforeKey = ''; beforePage = null;
      }
      return Promise.all(want).then(function (got) {
        return {now: got[0] || {}, was: got[1] || null,
          nowKey: hourKey, wasKey: before};
      });
    }).then(function (both) {
      var page = both.now;
      /* Each element remembers WHICH HOUR it belongs to, so a note put
         on a line from the earlier hour is filed against that hour and
         not against the one on screen. */
      function stamp(list, key) {
        var out = [];
        for (var i = 0; i < (list || []).length; i += 1) {
          var it = list[i];
          if (it && typeof it === 'object') { it.hour = key; out.push(it); }
        }
        return out;
      }
      elements = stamp(both.was && both.was.elements, both.wasKey)
        .concat(stamp(page.elements, both.nowKey));
      fetchedAt = Date.now();
      fetching = false;
      paintScript(page, both.was);
    }, function (err) {
      fetching = false;
      var box = el('spScript');
      if (box && !box.children.length) {
        box.appendChild(make('p', 'sp-empty',
          'The script could not be read: ' + ((err && err.message) || err)));
      }
    });
  }

  /* Hollywood layout: each element type is its own block, and the CSS does
   * the indenting the way a script does - character centred over dialogue,
   * parentheticals tucked inside it, action full width. */
  function paintScript(page, before) {
    var box = el('spScript');
    if (!box) return;
    var head = el('spScriptHead');
    if (head && page) {
      /* #1268: the count is of what is ON THE PAGE, both hours of it,
         because that is what the reader can scroll through. */
      var lines = (page.counts && page.counts.lines) || 0;
      var back = (before && before.counts && before.counts.lines) || 0;
      head.textContent = (page.title || 'the broadcast')
        + '  ·  ' + (lines + back) + ' lines'
        + (back ? '  (with the hour before)' : '')
        + (page.live ? '  ·  live' : '');
    }
    var atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    /* #1269: REBUILD ONLY WHAT CHANGED.
     *
     * "keep an eye on how it is jumping around"
     *
     * This used to replaceChildren() and re-append EVERY element on
     * every poll - twenty seconds, a few hundred nodes, and with the
     * hour before it now carried too (#1268) a few hundred more. Every
     * node the reader was looking at was destroyed and rebuilt, which
     * throws the scroll offset and drops the highlight (nowLineId was
     * cleared just below, unconditionally), so the page re-seated
     * itself three times a minute whether anything had changed or not.
     *
     * #1269 answered that with a longest-common-PREFIX compare, on the
     * reasoning that a script only ever grows at the end. It does not,
     * and #1273 below replaces it - see there for what moves the page
     * and what it measured. This note is kept only because the fault it
     * describes is still the right one to have been chasing.
     */
    /* #1273: KEPT, NOT REBUILT. The prefix match this replaces assumed
     * the script only grows at the end; measured on air it destroyed 240
     * nodes over eight polls, 238 of them identical content that had
     * merely moved. See the patch note for the three things that move
     * it. Nodes are keyed by the server's element id and kept. */
    if (paintedIn !== box) { scriptNodes.clear(); paintedIn = box; }
    var anchor = scriptAnchor(box);
    var order = [];
    var wanted = Object.create(null);
    for (var i = 0; i < elements.length; i += 1) {
      var item = elements[i];
      var key = String(item.id || '') || ('ix:' + i);
      wanted[key] = 1;
      /* Everything the node's APPEARANCE depends on, so a line revised
         in place is re-dressed rather than rebuilt. */
      var print = String(item.text || '') + SEP + String(item.type || '')
        + SEP + String(item.aired || '') + SEP + (item.tinted ? '1' : '0');
      var node = scriptNodes.get(key);
      if (node && node.pinePrint !== print) {
        var lit = node.classList.contains('sp-now');
        var picked = node.classList.contains('picked');
        node.textContent = String(item.text || '');
        node.className = 'sp-el sp-' + String(item.type || 'action')
          + (item.aired === 'prepared' ? ' pending' : '')
          + (item.tinted ? ' tinted' : '')
          + (lit ? ' sp-now' : '') + (picked ? ' picked' : '');
        node.pinePrint = print;
      }
      if (!node) {
        node = scriptBlock(item);
        node.pinePrint = print;
        scriptNodes.set(key, node);
      }
      order.push(node);
    }
    scriptNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode === box) held.remove();
      scriptNodes.delete(key);
    });
    stitchScript(box, order);
    scriptRestore(box, anchor);
    /* FOLLOWING BEATS STICKING TO THE END.
     * The live line sits wherever the conversation has got to, and the end
     * of the hour is usually well past it; scrolling to the bottom after
     * every repaint would drag the operator away from the line being said
     * twenty seconds after it arrived. */
    if (stick && atEnd && !(follow && nowLineId)) box.scrollTop = box.scrollHeight;
    /* #1273: THE MARK IS RE-ASSERTED, NOT MERELY REMEMBERED.
       #1269 asked whether a node with this id existed - not whether it
       still CARRIED the mark. A rebuilt node exists without .sp-now, so
       nowLineId stayed set, markNow returned at `id === nowLineId`, and
       the page showed no highlight at all until the station moved on.
       That is the operator's "highlighting incorrect segments". Keyed
       nodes make it rare; asking the right question makes it
       impossible. */
    if (nowLineId) {
      var held = box.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (!held) nowLineId = '';
      else if (!held.classList.contains('sp-now')) held.classList.add('sp-now');
    }
    tick();
  }

  /* #1273: HOLD THE READER'S PLACE ACROSS A REPAINT. Measure one row
     that is actually on screen before, find the SAME element after, and
     move the scroll by the difference - so an element inserted above the
     reader does not drag the page out from under them. Deliberately not
     derived from offsetTop; the sampler's commit records why that
     failed. */
  function scriptAnchor(box) {
    if (!box || box.scrollTop <= 4) return {pinned: true};
    var lip = box.getBoundingClientRect();
    for (var i = 0; i < box.children.length; i += 1) {
      var seat = box.children[i].getBoundingClientRect();
      if (seat.bottom <= lip.top + 1) continue;      /* scrolled off the top */
      return {node: box.children[i], was: seat.top};
    }
    return {pinned: true};
  }

  function scriptRestore(box, anchor) {
    if (!box || !anchor || anchor.pinned) return;
    var node = anchor.node;
    /* It left the page while it was being read. Leave the scroll alone:
       the browser's own anchoring has already chosen a neighbour. */
    if (!node || node.parentNode !== box) return;
    var drift = node.getBoundingClientRect().top - anchor.was;
    if (Math.abs(drift) > 0.5) {
      box.scrollTop = Math.max(0, box.scrollTop + drift);
    }
  }

  /* Put `order` into `box`, in that order, moving as little as possible.
     A node already in the right place costs one comparison; anything
     else is one insertBefore. */
  function stitchScript(box, order) {
    var cursor = box.firstChild;
    for (var i = 0; i < order.length; i += 1) {
      if (order[i] === cursor) { cursor = cursor.nextSibling; continue; }
      box.insertBefore(order[i], cursor);
    }
    while (cursor) {                    /* not asked for any more */
      var next = cursor.nextSibling;
      cursor.remove();
      cursor = next;
    }
  }

  function scriptBlock(item) {
    var type = String(item.type || 'action');
    var node = make('div', 'sp-el sp-' + type);
    node.textContent = String(item.text || '');
    if (item.id) node.dataset.el = String(item.id);
    if (item.line) node.dataset.line = String(item.line);
    /* A line that has not aired yet is the interesting one - it can still
     * be changed before the room hears it. ONLY 'prepared' is that line;
     * 'published' and 'stream' have both already been heard. */
    if (item.aired === 'prepared') node.classList.add('pending');
    if (item.tinted) node.classList.add('tinted');
    if (type === 'dialogue' || type === 'action') {
      node.addEventListener('click', function () { openLine(item, node); });
    }
    return node;
  }

  /* ---------------------------------------------------- the live line */

  /* Where the burst has got to, in its own seconds. Uses the server's clock
   * rather than ours: `server_ms` is stamped in every poll, so the offset
   * between the two machines cancels instead of accumulating. */
  /* #1278: THE PLAYER THAT IS SOUNDING, or null when none is.
   *
   * The DJ voice rides one of a small set of <audio> elements. The one
   * that matters is the one that is actually playing - unpaused, not
   * ended, and past its first frame. */
  function soundingPlayer() {
    var all = document.querySelectorAll('audio');
    for (var i = 0; i < all.length; i += 1) {
      var a = all[i];
      if (!a || a.paused || a.ended) continue;
      if (!/djVoice/i.test(String(a.id || ''))) continue;
      if (!(Number(a.currentTime) > 0)) continue;
      return a;
    }
    return null;
  }

  /* Where the burst has got to, in its own seconds.
   *
   * #1278: READ, NOT ESTIMATED. This used to be
   * `(Date.now() + skewMs)/1000 - liveStream.at`, and `skewMs` is
   * re-read from `server_ms` on every poll, so it carried the whole
   * delivery latency and all its jitter. Measured against the audio
   * over 308 samples: behind the sound in 81.3% of them, off by more
   * than three seconds in 58.5%, median -2.99s; skewMs spread 16.7s and
   * moved a median of 1.79s between polls; the clock stalled in 61.3%
   * of intervals and then lurched. Against six-second lines that is
   * precisely a mark that skips forward and snaps back - 29.8% of moves
   * were skips and 20.5% were backward, 26 of those 31 with the
   * document completely unchanged.
   *
   * The audio element's currentTime is the SAME coordinate as the rows'
   * from/until - both are offsets into the same welded file - so the
   * position does not have to be estimated. Verified: a burst's maximum
   * `until` 86.86s against the player's own duration 87.76s.
   *
   * The clock remains for the one case with nothing to read: no player
   * sounding. */
  function streamAt() {
    var player = soundingPlayer();
    if (player) return Number(player.currentTime) || 0;
    if (!liveStream || !liveStream.at) return -1;
    return ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
  }

  /* The row the room is hearing. stream_now first - it is exact to the
   * quarter second - and speaking_now only as a fallback, since it is
   * refreshed every four seconds and a four second lag on a four second
   * line points at the wrong one. */
  function activeRow() {
    var t = streamAt();
    var rows = (liveStream && liveStream.rows) || [];
    function within(list, of) {
      for (var i = 0; i < list.length; i += 1) {
        var row = list[i];
        var from = Number(row.from), until = Number(row.until);
        if (!isFinite(from) || !isFinite(until)) continue;
        if (t >= from && t < until) {
          return {id: String(row.id || ''), from: from, until: until,
            at: t, index: i, of: of};
        }
      }
      return null;
    }
    if (t >= 0) {
      var seat = within(rows, rows.length);
      if (seat) return seat;
      /* #1278: A CLIP OF ITS OWN IS STILL A LINE OF THE SCRIPT.
       *
       * This searched `liveStream.rows` and nothing else - one burst.
       * Anything that airs as its own single-row clip is not in that
       * list, so no window contained the position and the mark was
       * cleared. Measured over 827 sounding samples, the split was
       * perfect: `interject` lit correctly 0 times of 151, and
       * `station_id` 0 of 17, while every kind riding the welded burst
       * was lit sometimes. That is 20% of sounding samples guaranteed
       * wrong - and in 77% of the dark samples the line was already on
       * the page, so it was never the screenplay being stale.
       *
       * The feed's full row list is where those clips live. */
      var all = [];
      try { all = (root.PineStationFeed.rows() || []); } catch (err) { all = []; }
      if (all.length && all !== rows) {
        var loose = within(all, all.length);
        if (loose) return loose;
      }
    }
    if (speakingNow && speakingNow.id) {
      return {id: String(speakingNow.id), from: 0, until: 0, at: t,
        index: -1, of: rows.length};
    }
    return null;
  }

  /* PULL THE ARITHMETIC BACK ONTO THE STATION'S TRUTH.
   *
   * Measured over 30 samples: the interpolation agreed with the station on
   * 28 and disagreed on 2, both at a burst boundary, by a second or so.
   * That is drift - our clock and the station's playout are not the same
   * clock, and `at` is the moment the burst was HANDED to the player, not
   * the moment sound left it.
   *
   * So `speaking_now` is used as a reference mark rather than a fallback.
   * When the poll says a different row is in the room, the offset is
   * nudged - not snapped - until the two agree. Nudging matters: a snap on
   * a four-second-old reading would jerk the highlight backwards every
   * poll, which looks worse than the drift it fixes. */
  function correct() {
    if (!speakingNow || !speakingNow.id || !liveStream) return;
    var rows = liveStream.rows || [];
    var want = String(speakingNow.id);
    var seat = -1;
    for (var i = 0; i < rows.length; i += 1) {
      if (String(rows[i].id || '') === want) { seat = i; break; }
    }
    if (seat < 0) return;
    var row = rows[seat];
    var t = streamAt();
    if (t < 0) return;
    if (t >= Number(row.from || 0) && t < Number(row.until || 0)) return;  /* agreed */
    /* How far off we are from the middle of the row the station names. */
    var aim = (Number(row.from || 0) + Number(row.until || 0)) / 2;
    var off = (aim - t) * 1000;
    if (Math.abs(off) > 30000) return;   /* a different burst entirely */
    /* Held SEPARATELY from the clock skew, which is re-read from
     * `server_ms` on every poll and would otherwise wipe this out four
     * seconds after it was learned. */
    /* #1267: AND IT IS NO LONGER CARRIED. Measured on the tablet
     * against the station, 21 samples where the room was saying a
     * named line: the highlight was the right line in 16, and in the
     * other 5 it was BEHIND - one entry twice, two once, three twice -
     * and never once ahead. A one-directional error is a bias, not
     * drift.
     *
     * This is why. `driftMs` starts at 0 on every new burst (the
     * subscriber resets it whenever `liveStream.at` moves), is only
     * touched when the interpolated position falls OUTSIDE the row the
     * station names, and then closes just HALF the gap. So each burst
     * began with the error back at zero and converged in halves, which
     * on lines of five to seven seconds means it is still catching up
     * when the burst ends.
     *
     * The comment above justified it by 2 disagreements in 30 samples
     * at burst boundaries. It is now costing 5 in 21 across the whole
     * line - the cure was worse than the fault.
     *
     * The station's own feed has no such term: sampler-feed.js reads
     * `Date.now() + skew` and picks the row whose window contains it,
     * full stop. With this gone the two arithmetics are identical, and
     * the page agrees with the feed by construction rather than by
     * chasing it. `off` is still measured and reported below, because a
     * number worth fixing is worth watching.
     */
    lastOffMs = off;
  }

  /* ONE line carries the mark. The class is removed from whatever had it
   * before rather than from everything, so a 283-element script does not
   * get walked four times a second. */
  function markNow(id) {
    if (id === nowLineId) return;
    /* #1263: CLEAR EVERY MARK, not the one we remember.
     *
     * "it's highlighting multiple lines at the same time when it's
     *  broadcasting. When really I need it to highlight a single line."
     *
     * This used to un-mark only the node matching `nowLineId`, so any
     * path that cleared that variable WITHOUT repainting left its line
     * lit for ever and the next tick lit another beside it. There are
     * three such paths - the live chip, and the two view gestures added
     * in #1260 - and each tap stranded one more highlight.
     *
     * Only one line is ever being said, so only one may ever be marked.
     * Asking the document rather than trusting a remembered id makes
     * that true by construction, whatever else clears what. */
    var lit = document.querySelectorAll('.sp-el.sp-now');
    for (var i = 0; i < lit.length; i += 1) lit[i].classList.remove('sp-now');
    /* #1270: A MARK THAT DID NOT HAPPEN IS NOT REMEMBERED.
     *
     * This used to write `nowLineId = id` and only THEN look for the
     * node, returning quietly when the line was not on the page yet -
     * which happens constantly, because the station moves to a line
     * the moment it airs and the screenplay is only re-read every
     * twenty seconds. The id was now recorded as marked when nothing
     * had been marked, so every later tick hit `id === nowLineId` at
     * the top and returned. The highlight then sat on the PREVIOUS
     * line until the station moved again - which is the one-to-three
     * entry lag measured on the tablet, always behind and never ahead.
     *
     * It was masked until now: paintScript cleared nowLineId on every
     * repaint, so the mark was forced to re-seat three times a minute.
     * #1269 stopped rebuilding the page and the mask went with it.
     *
     * So the node is found FIRST. If the line has not arrived yet the
     * id is left unset and the next tick - a quarter of a second - has
     * another go, which is also what makes the view seat itself on
     * mount instead of sitting at the top of a 72,000px script.
     */
    var node = id
      ? document.querySelector('.sp-el[data-line="' + id + '"]')
      : null;
    if (id && !node) {
      /* #1271: AND THE PAGE GOES AND GETS IT.
       *
       * The line the room is saying can only be marked if it is ON the
       * page, and the script is re-read every twenty seconds - so a
       * line that aired since the last read waits, and the highlight
       * sits on the one before it. Measured on the tablet: correct
       * within 3 seconds at some changes and 7 at others, always one
       * line behind, always catching up in the end. The wait was the
       * whole of it.
       *
       * Being unable to find the line IS the signal that the script is
       * stale, so it asks for a fresh one there and then, at most once
       * every three seconds. Nothing else in the view has to know. */
      nowLineId = '';
      var t = Date.now();
      if (t - chasedAt > 3000) { chasedAt = t; loadScreenplay(true); }
      return;
    }
    nowLineId = id || '';
    if (!node) return;
    node.classList.add('sp-now');
    if (follow) {
      /* Centred, not merely visible: the operator is reading the
       * conversation, and the next line wants to be under it.
       *
       * THE GUARD IS THE WHOLE FIX. Measured: the highlight was on screen
       * in 0 of 7 talking samples, because a smooth scroll fires scroll
       * events all the way down, the handler below read "the line is not
       * visible yet" from one of them and switched following OFF - the
       * auto-scroll cancelled itself on its first frame, every time. */
      selfScrollUntil = Date.now() + 900;
      try { node.scrollIntoView({block: 'center', behavior: 'smooth'}); }
      catch (err) { node.scrollIntoView(false); }
    }
  }

  function seconds(v) {
    if (!isFinite(v)) return '—';
    return (v < 10 ? v.toFixed(1) : String(Math.round(v))) + 's';
  }

  /* WHY IT IS NOT SPEAKING YET, in one line.
   *
   * "I want to be able to see what is causing it to delay or what is
   * happening with its processing."
   *
   * Everything below already rides in the feed poll this view subscribes
   * to, so the readout costs no request. The order is deliberate: what the
   * room can hear beats what the desk is doing, and a named blocker beats
   * a count. */
  function status() {
    var row = activeRow();
    if (stationPaused) return {state: 'paused', text: 'air paused — nothing is going out'};

    if (row && row.until > row.from) {
      var left = row.until - row.at;
      var node = document.querySelector('.sp-el[data-line="' + row.id + '"]');
      var who = '';
      if (node) {
        var prev = node.previousElementSibling;
        if (prev && prev.classList.contains('sp-character')) who = prev.textContent + ' · ';
      }
      var tail = '';
      if (row.index >= 0 && row.of) {
        var rest = row.of - row.index - 1;
        tail = rest > 0 ? ' · ' + rest + ' more in this burst' : ' · last of the burst';
      }
      return {state: 'air', text: who + 'on air · ' + seconds(Math.max(0, left))
        + ' left of ' + seconds(row.until - row.from) + tail};
    }

    if (row && row.id) return {state: 'air', text: 'on air'};

    /* Nothing in the room. Say what the booth is doing about it. */
    var f = flow || {};
    if (f.render_waiting) {
      return {state: 'work', text: 'written, waiting on the voice — '
        + f.render_waiting + ' line' + (f.render_waiting === 1 ? '' : 's')
        + ' in the render queue'};
    }
    if (f.delivery_waiting) {
      return {state: 'work', text: 'voiced, waiting to be handed to air — '
        + f.delivery_waiting + ' waiting'};
    }
    if (f.writing) return {state: 'work', text: 'the room is writing the next round'};
    if (f.ad_cover) return {state: 'work', text: 'an ad is covering the gap'};

    /* A BLOCKER IS ONLY A BLOCKER IF IT BLOCKS.
     *
     * `blockers` carries all-clears too - measured live, the only entry was
     * "continuity reserve is healthy" - and `tint_hold` is TRUE at rest, so
     * an earlier draft of this line read "holding for the tint lane to
     * finish a pass" permanently, over ordinary music. A readout that says
     * the same worried thing all day teaches the operator to ignore it. */
    var blockers = (f.blockers || []).filter(function (b) {
      var t = String(b || '').toLowerCase();
      return t && t.indexOf('healthy') < 0 && t.indexOf('is fine') < 0
        && t.indexOf('no shortage') < 0 && t.indexOf(' ok') < 0;
    });
    if (blockers.length) return {state: 'wait', text: 'held: ' + blockers[0]};

    /* Nothing is wrong: it is a music bed, and the only question worth
     * answering is when the pair are back. */
    var rest = 'music';
    if (typeof f.talk_next_in === 'number' && f.talk_next_in > 0) {
      rest += ' — the pair are back in ' + seconds(f.talk_next_in);
    } else if (typeof f.ready === 'number' && typeof f.target === 'number') {
      rest += ' — ' + f.ready + ' rounds banked against a target of ' + f.target;
    }
    return {state: 'idle', text: rest};
  }

  function paintStatus() {
    var line = el('spNow');
    if (!line) return;
    var got = status();
    if (line.dataset.state !== got.state) line.dataset.state = got.state;
    if (line.__text !== got.text) { line.__text = got.text; line.textContent = got.text; }
  }

  /* The 250 ms heartbeat: move the mark, move the readout. Nothing here
   * touches the network. */
  function tick() {
    var row = activeRow();
    markNow(row ? row.id : '');
    markFeedLive(row ? row.id : '');            /* #1279 */
    paintStatus();
  }

  function jumpToLine(id) {
    if (!id) return;
    var node = document.querySelector('.sp-el[data-line="' + id + '"]');
    if (!node) return;
    node.scrollIntoView({block: 'center'});
    node.classList.add('flash');
    setTimeout(function () { node.classList.remove('flash'); }, 1200);
  }

  /* Tap a line: what it is, and what can be done with it. */
  function openLine(item, node) {
    pinned = item;
    document.querySelectorAll('.sp-el.picked').forEach(function (n) {
      n.classList.remove('picked');
    });
    node.classList.add('picked');
    var box = el('spDetail');
    if (!box) return;
    box.hidden = false;
    box.replaceChildren();

    box.appendChild(make('b', 'sp-detail-who', item.name || item.who || item.tag || 'the station'));
    box.appendChild(make('p', 'sp-detail-text', item.text || ''));

    var facts = [];
    if (item.round) facts.push(item.round);
    if (item.kind) facts.push(item.kind);
    if (item.engine) facts.push(item.engine);
    if (item.seconds) facts.push(Number(item.seconds).toFixed(1) + 's');
    if (item.tinted) facts.push('tinted');
    if (item.aired) facts.push(item.aired === 'stream' ? 'aired' : item.aired);
    box.appendChild(make('i', 'sp-detail-facts', facts.join('  ·  ')));

    var note = make('textarea', 'sp-note');
    note.placeholder = 'A note, or how this should have been said...';
    box.appendChild(note);

    var row = make('div', 'sp-detail-row');

    var keep = make('button', 'sp-btn wide', 'Keep the note');
    keep.addEventListener('click', function () {
      sendNote(item, note.value, keep);
    });
    row.appendChild(keep);

    var back = make('button', 'sp-btn wide', 'Send to the recording room');
    /* Honest about the limit rather than failing in the operator's hand:
     * the return path needs a round that is still on the shelf. */
    back.title = 'Asks the writers to do this line again, with your note '
      + 'above it. Only possible while the round it belongs to is still on '
      + 'the shelf.';
    back.addEventListener('click', function () { sendBack(item, note.value, back); });
    row.appendChild(back);

    var clip = make('button', 'sp-btn wide', 'Hear it');
    clip.disabled = !item.clip;
    clip.addEventListener('click', function () { hear(item, clip); });
    row.appendChild(clip);

    box.appendChild(row);
    var close = make('button', 'sp-detail-close', '✕');
    close.addEventListener('click', function () { box.hidden = true; });
    box.appendChild(close);
  }

  function sendNote(item, text, button) {
    if (!text.trim()) { button.textContent = 'write something first'; return; }
    var was = button.textContent;
    button.textContent = 'keeping...';
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'line', target_id: item.line || item.id, text: text,
      who: 'operator'
    }).then(function () {
      button.textContent = 'kept';
      setTimeout(function () { button.textContent = was; }, 1600);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function sendBack(item, text, button) {
    var was = button.textContent;
    button.textContent = 'sending...';
    /* The note first, so the request and the reason are stored together
     * even if the rewrite is refused. */
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'rework', target_id: item.line || item.id,
      text: text || 'Do this one again.', who: 'operator'
    }).then(function () {
      button.textContent = 'asked';
      setTimeout(function () { button.textContent = was; }, 1800);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function hear(item, button) {
    if (!item.clip) return;
    var was = button.textContent;
    button.textContent = 'fetching...';
    var audio = new Audio(item.clip);
    audio.play().then(function () { button.textContent = was; },
      function () { button.textContent = 'would not play'; });
  }

  /* ------------------------------------------------------------- build */

  function build(node) {
    host = node;
    host.classList.add(HOST_CLASS);
    host.replaceChildren();

    var left = make('div', 'sp-left');
    left.appendChild(buildBar());            /* 1 2 3 */
    var treeRow = make('div', 'sp-treerow');
    treeRow.appendChild(buildTree());        /* 4 */
    left.appendChild(treeRow);
    left.appendChild(buildPanel());
    left.appendChild(buildPlayer());         /* 5 */
    var feedHead = make('div', 'sp-feedhead');
    feedHead.appendChild(make('b', '', 'Feed'));
    feedHead.appendChild(make('i', 'sp-feedwhy', 'everything the station is doing'));
    left.appendChild(feedHead);
    var feed = make('div', 'sp-feed');       /* 6 */
    feed.id = 'spFeed';
    feed.addEventListener('scroll', function () {
      feedStick = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
    });
    left.appendChild(feed);

    var right = make('div', 'sp-right');     /* 7 */
    var head = make('div', 'sp-scripthead');
    head.appendChild(make('b', '', 'The script'));
    head.appendChild(make('i', 'sp-scriptwhy', ''));
    head.lastChild.id = 'spScriptHead';
    right.appendChild(head);
    /* One line, console-shaped, directly under the heading: what is
       happening with the line that is being said. */
    var now = make('div', 'sp-now-line');
    now.id = 'spNow';
    now.dataset.state = 'idle';
    right.appendChild(now);

    var script = make('div', 'sp-script');
    script.id = 'spScript';
    script.addEventListener('scroll', function () {
      if (Date.now() < selfScrollUntil) return;   /* our own scroll, in flight */
      stick = script.scrollTop + script.clientHeight >= script.scrollHeight - 40;
      /* Scrolling by hand means "let me read"; following would yank the
         page back every quarter second. Tapping the readout resumes it. */
      var node = nowLineId
        && document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (node) {
        var box = script.getBoundingClientRect();
        var seat = node.getBoundingClientRect();
        follow = seat.bottom > box.top && seat.top < box.bottom;
      }
      var chip = el('spNow');
      if (chip) chip.classList.toggle('adrift', !follow);
    });
    right.appendChild(script);

    /* #1260: DOUBLE-TAP THE SCRIPT TO READ IT PROPERLY.
     *
     * "If I double tap the script page, I want to also have the script
     *  show up in this view." - the full-page screenplay the desktop
     *  shows, on the glass, instead of a column beside the player.
     *
     * A class on the host, so the layout is CSS's business and nothing
     * here has to know about the other six regions. dblclick fires on
     * this WebView; the manual two-tap timer underneath it is for the
     * cases where a fast double touch is delivered as two taps and the
     * synthetic dblclick never arrives. */
    /* #1272: A SINGLE TAP DOES NOTHING, AND THAT IS THE POINT.
     *
     * "script view should only go fullscreen if i double tap the blank
     *  area of the script view. If i tripple tap it, show it with the
     *  colorings and display style of a script document so it can be
     *  easier on the eyes."
     *
     * The operator works this view with a thumb while the station is
     * playing - listening, reading, and grabbing clips onto sampler
     * pads - so a single stray tap on the margin must not throw the
     * pane into full screen underneath them. Nothing happens until a
     * second tap says it was meant.
     *
     *     two taps    full screen, on and off
     *     three taps  the script-document setting, on and off
     *
     * The count is held for one window after the LAST tap rather than
     * the first, so a deliberate triple is never cut short by the
     * double firing on its way past. */
    var tapTimer = null;
    var taps = 0;
    var TAP_WINDOW = 300;
    var PAPER = 'sp-look-paper';

    function reseat() {
      /* The pane changed shape, so the line that was centred no longer
         is. Re-seat rather than leave the reader stranded. */
      follow = true;
      nowLineId = '';
      try { tick(); } catch (e) { /* the change matters more */ }
    }
    function bigToggle() { host.classList.toggle('sp-big'); reseat(); }
    /* #1272: the script-document setting - paper, Courier, the standard
       measures, and each element coloured for what it IS. One setting
       that goes on and off, not a cycle: the operator asked for a look,
       not a carousel. */
    function paperToggle() { host.classList.toggle(PAPER); reseat(); }

    /* A tap on a LINE still opens that line - that is what the detail
     * panel is for and it predates this. These gestures belong to the
     * PANE: the margins, the gutters, the space between the speeches. */
    function onTap(ev) {
      var t = ev && ev.target;
      if (t && t.closest && t.closest('button, input, a, .sp-detail')) return;
      /* THE BLANK AREA ONLY. A tap on a line belongs to that line - it
         opens the detail panel, which is how a clip is inspected and
         sent to a pad - and must never be read as part of a gesture. */
      if (t && t !== script && t.closest && t.closest('.sp-el')) return;
      taps += 1;
      if (tapTimer) clearTimeout(tapTimer);
      tapTimer = setTimeout(function () {
        var count = taps;
        tapTimer = null;
        taps = 0;
        if (count === 2) bigToggle();
        else if (count >= 3) paperToggle();
        /* one tap: nothing at all */
      }, TAP_WINDOW);
    }
    script.addEventListener('click', onTap);

    /* --- THE CRAWL -------------------------------------------------
     *
     * "I want an icon that allows me to start it auto scrolling, but by
     *  default I want it to automatically be on the area that's actively
     *  airing. However, I do want a slider that allows me to choose the
     *  speed."
     *
     * Two different ways to move, and they must not fight: FOLLOW keeps
     * the live line in view and is the default; CRAWL walks the page at
     * a chosen rate for reading ahead. Starting the crawl stands follow
     * down, and tapping the live chip (which already exists) stands the
     * crawl down and goes back to the air. */
    var crawl = false;
    var crawlPx = 18;            /* pixels per second at the middle */
    var crawlLast = 0;
    var crawlOwed = 0;

    var tools = make('div', 'sp-crawl');
    var run = make('button', 'sp-crawl-go');
    run.type = 'button';
    run.textContent = '▶';           /* play; becomes pause when on */
    run.title = 'Auto-scroll the script';
    var rate = document.createElement('input');
    rate.type = 'range';
    rate.min = '1'; rate.max = '100'; rate.value = '30';
    rate.className = 'sp-crawl-rate';
    rate.title = 'How fast it scrolls';
    tools.appendChild(run);
    tools.appendChild(rate);
    right.appendChild(tools);

    function crawlRate() {
      /* 1..100 on the slider, about 2 to 220 px a second, curved so the
         slow half of the travel has real resolution - that is the half
         anybody reading along actually uses. */
      var v = Math.max(1, Math.min(100, Number(rate.value) || 30)) / 100;
      return 2 + 218 * v * v;
    }
    function crawlSet(on) {
      crawl = !!on;
      run.textContent = crawl ? '⏸' : '▶';
      run.classList.toggle('on', crawl);
      tools.classList.toggle('on', crawl);
      if (crawl) {
        follow = false;             /* the two cannot both drive */
        var chip = el('spNow');
        if (chip) chip.classList.add('adrift');
        crawlLast = 0;
        crawlOwed = 0;
        requestAnimationFrame(crawlStep);
      }
    }
    function crawlStep(ts) {
      if (!crawl) return;
      var box = el('spScript');
      if (!box) { crawl = false; return; }
      if (crawlLast) {
        crawlOwed += crawlRate() * ((ts - crawlLast) / 1000);
        var whole = Math.floor(crawlOwed);
        if (whole >= 1) {
          crawlOwed -= whole;
          selfScrollUntil = Date.now() + 400;   /* our own scroll (#the guard) */
          box.scrollTop += whole;
          if (box.scrollTop + box.clientHeight >= box.scrollHeight - 2) {
            crawlSet(false);                    /* the end of the script */
          }
        }
      }
      crawlLast = ts;
      if (crawl) requestAnimationFrame(crawlStep);
    }
    run.addEventListener('click', function (ev) {
      ev.stopPropagation();                     /* not a pane tap */
      crawlSet(!crawl);
    });
    rate.addEventListener('click', function (ev) { ev.stopPropagation(); });
    rate.addEventListener('input', function () {
      if (crawl) { crawlLast = 0; }             /* take the new rate now */
    });

    now.addEventListener('click', function () {
      crawlSet(false);       /* back to the air stands the crawl down */
      follow = true;
      now.classList.remove('adrift');
      nowLineId = '';        /* force markNow to re-seat and scroll */
      tick();
    });

    var detail = make('div', 'sp-detail');
    detail.id = 'spDetail';
    detail.hidden = true;
    right.appendChild(detail);

    host.appendChild(left);
    host.appendChild(right);
  }

  function mount(node) {
    if (mounted) return Promise.resolve(true);
    build(node);
    wirePlayer();
    mounted = true;

    var feed = root.PineStationFeed;
    if (feed && typeof feed.subscribe === 'function') {
      stop = feed.subscribe(function (payload) {
        var state = (payload && payload.station) || payload || {};
        var wasAt = liveStream && liveStream.at;
        liveStream = state.stream_now || null;
        if (!liveStream || liveStream.at !== wasAt) lastOffMs = 0;
        speakingNow = state.speaking_now || null;
        flow = state.dialogue_flow || null;
        /* talk_next_in rides at the top of the payload, not inside
           dialogue_flow; fold it in so status() has one place to read. */
        if (flow && typeof state.talk_next_in === 'number') {
          flow.talk_next_in = state.talk_next_in;
        }
        stationPaused = !!state.paused;
        /* Cancel the clock difference between this tablet and the station
           rather than assuming they agree; four seconds of drift would
           point the highlight at the wrong line. */
        if (state.server_ms) skewMs = Number(state.server_ms) - Date.now();
        correct();
        paintPlayer(state);
        paintFeed(state);
        loadScreenplay(false);
        tick();
      });
    } else {
      loadScreenplay(true);
    }
    if (root.PineConsoleLine) root.PineConsoleLine.start();
    /* #1276: the read the operator is actually waiting on when they
       switch to this view. Forced, so it cannot be answered out of a
       twenty-second cache that predates the line now sounding. */
    loadScreenplay(true);
    if (!beat) beat = setInterval(tick, 250);
    return Promise.resolve(true);
  }

  root.PineScriptPage = {
    mount: mount,
    isMounted: function () { return mounted; },
    close: function () {
      if (stop) stop();
      stop = null;
      if (beat) clearInterval(beat);
      beat = 0;
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineScriptPage;
})(typeof window !== 'undefined' ? window : globalThis);
