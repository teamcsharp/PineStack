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
  var fetchedAt = 0;
  var fetching = false;
  var pinned = null;                /* the element the operator tapped */
  var stick = true;                 /* keep the script scrolled to the end */
  var feedStick = true;
  var seen = Object.create(null);   /* feed rows already drawn */

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
  var driftMs = 0;                  /* playout minus the handover stamp */
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
    var rows = (state && state.chat) || [];
    var added = 0;
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var id = String((row && row.id) || '');
      if (!id || seen[id]) continue;
      seen[id] = true;
      box.appendChild(feedRow(row));
      added += 1;
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
    while (box.children.length > FEED_MAX) box.removeChild(box.firstChild);
    if (feedStick) box.scrollTop = box.scrollHeight;
  }

  function feedRow(row) {
    var who = String(row.who || 'dj');
    var line = make('div', 'sp-msg' + (row.aired === 'airing' ? ' airing' : ''));
    line.dataset.line = String(row.id || '');
    var head = make('b', 'sp-msg-who', row.name || who);
    var body = make('span', 'sp-msg-text', String(row.text || '').trim());
    line.appendChild(head);
    line.appendChild(body);
    line.addEventListener('click', function () { jumpToLine(String(row.id || '')); });
    return line;
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
    fetching = true;
    api().get('/api/screenplay').then(function (index) {
      var hours = (index && index.hours) || [];
      if (!hours.length) throw new Error('no hours written yet');
      hourKey = String(hours[0].key || '');
      return api().get('/api/screenplay/' + encodeURIComponent(hourKey));
    }).then(function (page) {
      elements = (page && page.elements) || [];
      fetchedAt = Date.now();
      fetching = false;
      paintScript(page);
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
  function paintScript(page) {
    var box = el('spScript');
    if (!box) return;
    var head = el('spScriptHead');
    if (head && page) {
      head.textContent = (page.title || 'the broadcast')
        + '  ·  ' + ((page.counts && page.counts.lines) || 0) + ' lines'
        + (page.live ? '  ·  live' : '');
    }
    var atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    box.replaceChildren();
    for (var i = 0; i < elements.length; i += 1) {
      box.appendChild(scriptBlock(elements[i]));
    }
    /* FOLLOWING BEATS STICKING TO THE END.
     * The live line sits wherever the conversation has got to, and the end
     * of the hour is usually well past it; scrolling to the bottom after
     * every repaint would drag the operator away from the line being said
     * twenty seconds after it arrived. */
    if (stick && atEnd && !(follow && nowLineId)) box.scrollTop = box.scrollHeight;
    /* The script was just rebuilt, so the marked node is gone. Forget it
       and let the next tick put the class back where it belongs. */
    nowLineId = '';
    tick();
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
  function streamAt() {
    if (!liveStream || !liveStream.at) return -1;
    return ((Date.now() + skewMs + driftMs) / 1000) - Number(liveStream.at || 0);
  }

  /* The row the room is hearing. stream_now first - it is exact to the
   * quarter second - and speaking_now only as a fallback, since it is
   * refreshed every four seconds and a four second lag on a four second
   * line points at the wrong one. */
  function activeRow() {
    var t = streamAt();
    var rows = (liveStream && liveStream.rows) || [];
    if (t >= 0) {
      for (var i = 0; i < rows.length; i += 1) {
        var row = rows[i];
        if (t >= Number(row.from || 0) && t < Number(row.until || 0)) {
          return {id: String(row.id || ''), from: Number(row.from || 0),
            until: Number(row.until || 0), at: t, index: i, of: rows.length};
        }
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
    driftMs += off * 0.5;   /* off is already milliseconds; take half the gap */
  }

  /* ONE line carries the mark. The class is removed from whatever had it
   * before rather than from everything, so a 283-element script does not
   * get walked four times a second. */
  function markNow(id) {
    if (id === nowLineId) return;
    if (nowLineId) {
      var was = document.querySelector('.sp-el.sp-now[data-line="' + nowLineId + '"]');
      if (was) was.classList.remove('sp-now');
    }
    nowLineId = id || '';
    if (!nowLineId) return;
    var node = document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
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
    api().post('/api/screenplay/' + encodeURIComponent(hourKey) + '/note', {
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
    api().post('/api/screenplay/' + encodeURIComponent(hourKey) + '/note', {
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
    now.addEventListener('click', function () {
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
        if (!liveStream || liveStream.at !== wasAt) driftMs = 0;
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
