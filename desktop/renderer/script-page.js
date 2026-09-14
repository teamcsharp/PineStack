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
  var adrift = 0;                   /* #1282: consecutive off-screen reads */
  var folded = Object.create(null);   /* #1285: seg id -> folded? */
  var byHand = Object.create(null);   /* #1285: the operator said so */
  var liveSeg = '';                   /* #1285: the segment on air */
  var planHours = [];                 /* #1289: the director's entries */
  var planAt = 0;                     /* when we last read them */
  var planning = false;
  var planWay = 'below';              /* #1289: 'below' | 'beside' */
  var PLAN_REST_MS = 30000;           /* a running order is not news */
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

    /* #1303: THE SFX GUY, ON A PICTURE, ON THE OPERATOR'S THUMB.
     *
     * Carbon out of the vendored set through pineIcon() - the house
     * rule is monochromatic Carbon and never an emoji, and the set is
     * checked before choosing. It posts the `video` road #1303 built
     * and reports what the air actually did with it: a button that
     * cues the broadcast must not be silent about whether it took. */
    var reel = make('button', 'sp-btn sp-reel', '');
    reel.title = 'Cue the SFX guy to play a random video on the broadcast';
    reel.setAttribute('aria-label', 'Play a random video clip');
    try {
      if (typeof root.pineIcon === 'function') {
        reel.innerHTML = root.pineIcon('m:video_library',
                                       'Play a random video clip');
      }
    } catch (err) { /* the title still names it */ }
    if (!reel.innerHTML) reel.textContent = 'video';
    /* #1311b: RAPID FIRE MEANS EVERY TAP COUNTS.
     *
     * This disabled the button for the length of the request, so at
     * anything faster than one tap a second the second, third and
     * fourth taps were simply swallowed - measured, five taps and the
     * picture never changed after the first. The operator asked to
     * "tap on the button, rapid fire, and have it cycle between
     * videos", so nothing is refused; a sequence number keeps a slow
     * answer from landing on top of a faster one that came after it. */
    reel.addEventListener('click', function () {
      reel.classList.add('sp-firing');
      fireVideo(reel);
    });

    /* #1385 (#1108): THE PLAY BUTTON NEXT TO THE VIDEO BUTTON.
     *
     * "Put a play button next to the video button that ... puts the SFX
     *  guy into video play mode where the videos are being played one
     *  after another chosen from random from the collection."
     *
     * The mode is the station's (#1366, /api/sfx/video/mode) and it is
     * a held setting, so this button only reports and flips it; the set
     * keeps running through a restart and this view coming and going. */
    var loop = make('button', 'sp-btn sp-loop', '');
    loop.title = 'Endless video: the SFX guy plays clips one after another, at random';
    loop.setAttribute('aria-label', 'Endless video on or off');
    try {
      if (typeof root.pineIcon === 'function') {
        loop.innerHTML = root.pineIcon('c:renew', 'Endless video');
      }
    } catch (err) { /* the title still names it */ }
    if (!loop.innerHTML) loop.textContent = 'loop';
    loop.addEventListener('click', function () { loopToggle(loop); });
    setTimeout(function () { loopRead(loop); }, 900);

    /* #1385 (#1110): find a word that was said on the air. */
    var find = make('input', 'sp-find', '');
    find.type = 'search';
    find.placeholder = 'find a word said on air';
    find.title = 'Every time this word was said on the air in the last two days, and why it keeps being said';
    find.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); findOpen(find.value); }
    });

    bar.appendChild(back);
    bar.appendChild(pick);
    bar.appendChild(reel);                                   /* #1303 */
    bar.appendChild(loop);                                   /* #1385 */
    bar.appendChild(find);                                   /* #1385 */
    bar.appendChild(again);
    return bar;
  }

  /* #1298: WHAT IS BEING SAID, BESIDE THE TREE.
   *
   * The words come from activeRow() - the same answer the highlight
   * uses, so the strip and the script can never disagree. The speaker
   * is the nearest preceding character heading, which is how the
   * screenplay says it; a clip has no heading, because it is an action
   * line, so it is named as a clip instead of being given a voice it
   * does not have. */
  function buildSaying() {
    var box = make('div', 'sp-saying');
    box.id = 'spSaying';
    var body = make('div', 'sp-saying-body');
    var who = make('div', 'sp-saying-who', '');
    who.id = 'spSayingWho';
    var text = make('div', 'sp-saying-text', '');
    text.id = 'spSayingText';
    body.appendChild(who);
    body.appendChild(text);
    var scope = document.createElement('canvas');
    scope.className = 'sp-saying-scope';
    scope.id = 'spSayingScope';
    box.appendChild(body);
    box.appendChild(scope);
    /* #1303b: TAP JUMPS, HOLD OPENS.
     *
     * A tap takes the reader to the line the strip is quoting; a hold
     * opens that line's own detail panel - the same one the script's
     * elements open, so "manage this clip, inspect it" is the surface
     * that already exists rather than a second one that would drift
     * from it.
     *
     * Told apart by time AND by movement, because on a tablet every
     * tap begins as a touch that might become a scroll: 500ms without
     * wandering more than a few pixels is a hold, a drag cancels
     * both, and the click that follows a fired hold is swallowed. */
    var holdTimer = 0;
    var heldAt = null;
    var holdFired = false;

    function holdOff() {
      if (holdTimer) { clearTimeout(holdTimer); holdTimer = 0; }
      heldAt = null;
    }

    box.addEventListener('pointerdown', function (ev) {
      holdFired = false;
      heldAt = {x: ev.clientX, y: ev.clientY};
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(function () {
        holdTimer = 0;
        holdFired = true;
        openSaying();
      }, 500);
    });
    box.addEventListener('pointermove', function (ev) {
      if (!heldAt) return;
      if (Math.abs(ev.clientX - heldAt.x) > 8
          || Math.abs(ev.clientY - heldAt.y) > 8) holdOff();
    });
    box.addEventListener('pointerup', holdOff);
    box.addEventListener('pointercancel', function () {
      holdOff(); holdFired = false;
    });
    box.addEventListener('click', function (ev) {
      if (holdFired) {                 /* the hold already answered */
        holdFired = false;
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
      if (nowLineId) jumpToLine(nowLineId);
    });
    return box;
  }

  /* #1303b: the live line's own detail panel, off the strip.
   *
   * The node carries the current item (see paintScript), so this opens
   * what the line says NOW rather than what it said when its node was
   * first built. */
  function openSaying() {
    if (!nowLineId) return;
    var node = document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
    if (!node || !node.pineItem) return;
    jumpToLine(nowLineId);
    openLine(node.pineItem, node);
  }

  /* Who says this line, the way the screenplay says it: the nearest
     character heading above it. */
  function sayingWho(node) {
    var walk = node;
    while (walk) {
      if (/sp-character/.test(walk.className || '')) {
        return String(walk.textContent || '').trim();
      }
      walk = walk.previousElementSibling;
    }
    return '';
  }

  var sayingSaid = '';

  function paintSaying(row) {
    var who = el('spSayingWho');
    var text = el('spSayingText');
    if (!who || !text) return;
    /* #1311: an answer the operator asked for outranks the line for a
       few seconds - see say(). */
    if (sayUntil && Date.now() < sayUntil) return;
    var node = (row && row.id)
      ? document.querySelector('.sp-el[data-line="' + row.id + '"]')
      : null;
    var body = node ? String(node.textContent || '').trim() : '';
    var name = '';
    if (node && /sp-dialogue/.test(node.className)) {
      name = sayingWho(node);
    } else if (node) {
      /* An action line IS the clip - "A sting off the board: 344 clip
         (0:35)" - so it is labelled as one rather than attributed. */
      name = 'CLIP';
    }
    if (!body) {
      name = '';
      body = soundingPlayer() ? 'sounding' : 'the room is quiet';
    }
    var print = name + '\u0001' + body;
    if (print === sayingSaid) return;         /* no needless repaint */
    sayingSaid = print;
    who.textContent = name;
    text.textContent = body;
    host.classList.toggle('sp-saying-idle', !node);
  }

  /* THE SPECTRUM, OFF THE PANEL'S OWN ANALYSER.
   *
   * window.audioScope memoises one analyser per element and adopts
   * window.pineAudioCtx; sampler-air.js wraps that same function
   * because a second createMediaElementSource on one element throws.
   * So this never builds a context or a source - it asks for the one
   * that exists.
   *
   * On rAF rather than a timer: this tablet's WebView suspends JS
   * timers and keeps firing rAF (#1241), so rAF is the only clock here
   * that does not freeze. */
  var scopeFrame = 0;
  var scopeWide = 0;
  var scopeHigh = 0;

  function paintScope() {
    scopeFrame = root.requestAnimationFrame(paintScope);
    var canvas = el('spSayingScope');
    /* #745's lesson, on our own canvas: it costs nothing while it
       cannot be seen. */
    if (!canvas || !canvas.offsetParent) return;
    var player = soundingPlayer();
    var ctx2d = null;
    try { ctx2d = canvas.getContext('2d'); } catch (err) { return; }
    if (!ctx2d) return;
    var dpr = root.devicePixelRatio || 1;
    var wide = Math.round(canvas.clientWidth * dpr);
    var high = Math.round(canvas.clientHeight * dpr);
    /* #745 again: writing canvas.width resets the whole 2D context, so
       it is measured and compared, never assigned every frame. */
    if (wide && high && (wide !== scopeWide || high !== scopeHigh)) {
      canvas.width = wide; canvas.height = high;
      scopeWide = wide; scopeHigh = high;
    }
    if (!scopeWide || !scopeHigh) return;
    ctx2d.clearRect(0, 0, scopeWide, scopeHigh);
    var scope = null;
    if (player && typeof root.audioScope === 'function') {
      try { scope = root.audioScope(player); } catch (err) { scope = null; }
    }
    var bins = scope && scope.bins;
    if (!scope || !bins) {
      /* A flat line is the honest picture of silence. */
      ctx2d.fillStyle = 'rgba(101, 199, 218, .22)';
      ctx2d.fillRect(0, Math.floor(scopeHigh / 2), scopeWide, Math.max(1, dpr));
      return;
    }
    try { scope.analyser.getByteFrequencyData(bins); } catch (err) { return; }
    var bars = 22;
    var step = Math.max(1, Math.floor(bins.length / bars));
    var gap = Math.max(1, Math.round(dpr));
    var span = scopeWide / bars;
    ctx2d.fillStyle = 'rgba(101, 199, 218, .85)';
    for (var b = 0; b < bars; b += 1) {
      var sum = 0;
      for (var k = 0; k < step; k += 1) sum += bins[(b * step) + k] || 0;
      var level = (sum / step) / 255;
      var tall = Math.max(dpr, level * scopeHigh);
      ctx2d.fillRect(Math.round(b * span), Math.round(scopeHigh - tall),
        Math.max(1, Math.round(span) - gap), Math.round(tall));
    }
  }

  /* #1303: cue a video, and say what came back.
   *
   * Through the bridge's own post(), the way sendNote and sendBack
   * already talk to the station - not a hand-rolled fetch that would
   * have to re-derive the base URL and the key for itself. The answer
   * lands on the strip, because a button that cues the air should
   * never be silent about whether the air took it. */
  var reelTurn = 0;

  /* ---- #1385: the endless set ----------------------------------- */
  var loopOn = false;

  function loopPaint(btn) {
    if (!btn) return;
    btn.classList.toggle('on', !!loopOn);
    btn.title = loopOn
      ? 'Endless video is ON - tap to stop after the clip on the tube'
      : 'Endless video: the SFX guy plays clips one after another, at random';
  }

  function loopRead(btn) {
    if (!api() || !api().get) return;
    Promise.resolve(api().get('/api/sfx/video/mode')).then(function (got) {
      loopOn = !!(got && got.on);
      loopPaint(btn);
    }, function () { /* asked again next time */ });
  }

  function loopToggle(btn) {
    if (!api() || !api().post) return;
    var want = !loopOn;
    loopOn = want;
    loopPaint(btn);
    Promise.resolve(api().post('/api/sfx/video/mode', {on: want})).then(function (got) {
      loopOn = !!(got && got.on !== undefined ? got.on : want);
      loopPaint(btn);
      say(loopOn ? 'endless video is on - one clip after another'
                 : 'endless video is off - back to the dial');
    }, function (err) {
      loopOn = !want;
      loopPaint(btn);
      say('the station did not answer: ' + String((err && err.message) || err).slice(0, 60));
    });
  }

  /* ---- #1385: the word search ------------------------------------ */

  /* The station does the counting (/api/said/search, #1380); this only
   * draws what it said. A sheet over the view, tap away to close, the
   * same shape as the clip doctor's - the operator asked for it on the
   * tablet, so every control is a thumb's size. */
  function findClose() {
    var old = el('spFindSheet');
    if (old) old.remove();
  }

  function findOpen(q) {
    q = String(q || '').trim();
    if (q.length < 2 || !api() || !api().get) return;
    findClose();
    var back = make('div', 'sp-find-back');
    back.id = 'spFindSheet';
    var box = make('div', 'sp-find-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, '\u201c' + q + '\u201d on the air'));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.addEventListener('click', findClose);
    head.appendChild(x);
    box.appendChild(head);
    var why = make('div', 'sp-find-why', 'asking the station\u2026');
    box.appendChild(why);
    var facts = make('div', 'sp-find-facts');
    box.appendChild(facts);
    var list = make('div', 'sp-find-list');
    box.appendChild(list);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) findClose(); });
    document.body.appendChild(back);
    Promise.resolve(api().get('/api/said/search?q=' + encodeURIComponent(q) + '&hours=48&limit=120')).then(function (d) {
      if (!d) { why.textContent = 'the station did not answer'; return; }
      why.textContent = d.why || d.say || '';
      var bits = [String(d.total || 0) + ' airing(s) in ' + (d.hours || 48) + 'h, ' + String(d.distinct || 0) + ' distinct line(s)'];
      (d.by_round || []).slice(0, 4).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      (d.by_who || []).slice(0, 3).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      facts.textContent = bits.join('  \u00b7  ');
      (d.repeated || []).slice(0, 5).forEach(function (t) {
        if (t.n < 2) return;
        var row = make('div', 'sp-find-rep');
        row.appendChild(make('b', null, '\u00d7' + t.n + ' '));
        row.appendChild(make('span', null, (t.who ? t.who + ': ' : '') + t.text));
        list.appendChild(row);
      });
      (d.rows || []).forEach(function (r) {
        var row = make('div', 'sp-find-row');
        var ago = r.ago >= 3600 ? Math.round(r.ago / 3600) + 'h ago' : Math.round(r.ago / 60) + 'm ago';
        row.appendChild(make('span', 'sp-find-when', ago + ' \u00b7 ' + (r.who || '?') + ' \u00b7 ' + (r.round || r.kind || '')));
        row.appendChild(make('span', 'sp-find-text', r.text || ''));
        list.appendChild(row);
      });
      if (!(d.rows || []).length) list.appendChild(make('div', 'sp-find-row', 'not said on the air in the last two days'));
    }, function (err) {
      why.textContent = 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80);
    });
  }

  function fireVideo(btn) {
    var mine = (reelTurn += 1);
    function done(text, bad) {
      if (mine !== reelTurn) return;  /* a newer tap owns the screen */
      btn.classList.remove('sp-firing');
      btn.classList.toggle('sp-fired-bad', !!bad);
      say(text);
      setTimeout(function () { btn.classList.remove('sp-fired-bad'); }, 2600);
    }
    /* #1306: the CUE road, not the fill road. dj_sting's path cost
       4.6-5.7s warm, none of it the pick - the chat row, the history
       write, the length probe and the whole satellite/announce
       decision a video never uses. This rings the clip and hands it
       straight back, and the set cuts to it here rather than waiting
       out its own 2.5s poll. Rapid taps therefore cycle. */
    api().post('/api/sfx/video/cue', {who: 'operator'}).then(function (got) {
      var clip = got && got.clip;
      if (!clip) {
        done(String((got && got.say) || 'no clip'), true);
        /* #1361b: A MISS IS A QUESTION, NOT A VERDICT. Four different
           faults have printed the same four words on this strip, and
           only one of them is cured by tapping again. The doctor
           names which one this is and puts the cure under a thumb. */
        try {
          if (root.PineClipDoctor) root.PineClipDoctor.open(String((got && got.say) || ''));
        } catch (err) { /* the strip already said it */ }
        return;
      }
      /* #1311b: an answer that has been overtaken is dropped rather
         than cutting the picture backwards. */
      if (mine !== reelTurn) return;
      try {
        if (root.PineSfxTv && root.PineSfxTv.cut) root.PineSfxTv.cut(clip);
      } catch (err) { /* the clip is in the ring either way */ }
      /* Not an error if the set is not on this surface - the clip is in
         the ring either way and whatever is watching will show it. */
      done(String(clip.sting || 'on the set'));
    }, function (err) {
      done(String((err && err.message) || err).slice(0, 60), true);
    });
  }

  /* #1311: A SHORT WORD ON THE STRIP, AND IT STAYS LONG ENOUGH TO READ.
   *
   * This set the text and then cleared sayingSaid so the next tick
   * would repaint - which it did, 250ms later, over the top of the
   * message. So a tap that answered "the clip library is still
   * warming" showed nothing at all, and a button that was working
   * and refusing looked like a button that was dead. That is how the
   * operator came to report the video icon as unresponsive.
   *
   * The message now holds the strip for a few seconds; paintSaying
   * stands off until it expires. */
  var sayUntil = 0;

  function say(text) {
    var line = el('spSayingText');
    if (!line) return;
    sayUntil = Date.now() + 4000;
    sayingSaid = ' said';        /* never equal to a real print */
    line.textContent = String(text || '');
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
      /* #1287: an insertBefore on an attached node is a detach and an
         attach, so stitching an already-correct list still takes every
         row out of the document for an instant. Check first: with the
         treadmill above gone, the order matches on nearly every paint
         and this loop does nothing at all. */
      var settled = true;
      var walk = box.firstChild;
      for (var c2 = 0; c2 < want.length; c2 += 1) {
        while (walk && /sp-msg-ev/.test(walk.className)) walk = walk.nextSibling;
        if (walk !== want[c2]) { settled = false; break; }
        walk = walk.nextSibling;
      }
      if (!settled) {
        var cursor = box.firstChild;
        for (var w = 0; w < want.length; w += 1) {
          if (want[w] === cursor) { cursor = cursor.nextSibling; continue; }
          box.insertBefore(want[w], cursor);
        }
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
    /* #1287: THE TRIM STOPS EVICTING ROWS IT STILL WANTS.
     *
     * #1279 trimmed on `box.children.length > FEED_MAX`, and the pane
     * holds activity rows and orphans as well as chat rows - so
     * several WANTED rows never fit inside the 240. The trim evicted
     * them from the front, forgot them, and the next paint recreated
     * them, re-inserted them at the front, and the trim evicted six
     * again. Measured: 65,023 detach/re-attach events in 9.2 minutes,
     * 7,055 a minute, at 3.67 paints a second - the largest single
     * reason a row moves under the operator's finger, and my own.
     *
     * Orphans go first, the cap counts only what is wanted, and a row
     * still in `want` is never evicted. */
    var keep = Object.create(null);
    for (var w2 = 0; w2 < want.length; w2 += 1) {
      var wid = want[w2].getAttribute('data-line');
      if (wid) keep[wid] = 1;
    }
    var kids = [].slice.call(box.children);
    for (var k2 = 0; k2 < kids.length; k2 += 1) {
      var kid = kids[k2];
      var kidId = kid.getAttribute && kid.getAttribute('data-line');
      if (!kidId || keep[kidId]) continue;
      if (/sp-msg-ev/.test(kid.className)) continue;   /* an event row */
      box.removeChild(kid);                            /* an orphan */
      delete feedNodes[kidId];
      if (feedLive === kidId) feedLive = '';
    }
    var over = want.length - FEED_MAX;
    for (var t2 = 0; t2 < over; t2 += 1) {
      var old = want[t2];
      var oldId = old && old.getAttribute && old.getAttribute('data-line');
      if (old && old.parentNode === box) box.removeChild(old);
      if (oldId) {
        delete feedNodes[oldId];
        if (feedLive === oldId) feedLive = '';
      }
    }
    if (!added && over <= 0) return;
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
      /* #1303b: THE NODE CARRIES THE CURRENT ITEM.
         The click handler scriptBlock attaches closes over the item the
         node was BUILT with, and a re-dress does not refresh it. Anything
         reading the node later - the strip's hold, for one - should get
         what this line says now. */
      node.pineItem = item;
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
    /* #1285: re-assert the folds, so a line arriving into a folded
       segment arrives folded rather than springing it open. */
    segApply();
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
    /* #1289: the plan is not an element of the screenplay and must
       survive the stitch. It is kept, and kept last. */
    var plan = null;
    while (cursor) {
      var next = cursor.nextSibling;
      if (cursor.id === 'spPlan') { plan = cursor; }
      else { cursor.remove(); }
      cursor = next;
    }
    if (plan) box.appendChild(plan);
  }

  /* #1285: fold a finished segment, leave the one on air open.
   *
   * Done by hiding members rather than nesting them: the reconciler
   * (#1273) stitches a FLAT list, and that is the fix that stopped this
   * page destroying a few hundred nodes a poll and losing the highlight
   * with them. A tree would undo it. */
  /* #1300: what each segment was last left as, so a repaint that
     re-asserts the same folds does not replay their motion. */
  var segWas = Object.create(null);
  var segFxTimer = 0;
  var FOLD_FX_MOST = 140;        /* beyond this a segment snaps */
  var FOLD_FX_MS = 260;

  function segApply(motion) {
    var box = el('spScript');
    if (!box) return;
    var all = box.querySelectorAll('.sp-el');
    var moving = [], shutting = [], opening = [];      /* #1300 */
    /* #1294: EVERYTHING BEHIND THE AIR IS SHUT, NOT ONLY THE SEGMENT
     * IT JUST LEFT.
     *
     * segFollow folds the one the air walks out of, and `folded`
     * starts empty - so every segment that had already finished when
     * the page painted stayed open for ever. Measured: 0 to 3 shut of
     * 51-57 scenes, ~2,100 elements and ~62,000 px of scroll. The fold
     * worked; it was just never reached.
     *
     * DOM order is script order (the reconciler stitches the canonical
     * list), so "behind" is "before the first element of the live
     * segment". A hand still outranks this, and with nothing on air
     * nothing is folded. */
    if (liveSeg) {
      var seen = Object.create(null);
      var reached = false;
      for (var p = 0; p < all.length; p += 1) {
        var mark = all[p].getAttribute('data-seg') || '';
        if (!mark) continue;                     /* plan rows, spacers */
        if (mark === liveSeg) { reached = true; break; }
        seen[mark] = 1;
      }
      if (reached) {
        for (var key in seen) {
          if (!byHand[key]) folded[key] = true;
        }
      }
    }
    /* #1300b: WHICH SEGMENTS CHANGED, SETTLED BEFORE ANYTHING IS
     * WRITTEN.
     *
     * This used to be decided inside the loop below, against segWas,
     * which the same loop also updated - and a segment's SCENE HEADING
     * is its first element in DOM order. The heading is excluded from
     * the motion by `!head`, so it fell through and wrote segWas for
     * the whole segment; by the time the members were reached the
     * value they needed to compare against was already the new one,
     * and not one of them ever animated. Measured on the tablet: a
     * fold opening 51 members, `sp-fx` on zero of them.
     *
     * A loop must not both read and write the memo it is deciding by. */
    var segsNow = Object.create(null);
    var changed = Object.create(null);
    for (var q = 0; q < all.length; q += 1) {
      var qseg = all[q].getAttribute('data-seg') || '';
      if (!qseg || segsNow[qseg] !== undefined) continue;
      var qshut = !!(folded[qseg] && qseg !== liveSeg);
      segsNow[qseg] = qshut;
      if (segWas[qseg] !== undefined && segWas[qseg] !== qshut) {
        changed[qseg] = 1;
      }
    }

    for (var i = 0; i < all.length; i += 1) {
      var node = all[i];
      var seg = node.getAttribute('data-seg') || '';
      var head = /sp-scene/.test(node.className);
      var shut = !!(seg && folded[seg] && seg !== liveSeg);
      /* The heading is how a folded segment is reopened, so it is the
         one thing that must never be hidden by its own fold. */
      /* #1300: and when this segment has just CHANGED state, it is
         shown changing rather than simply being different. */
      if (seg && motion && changed[seg] && !head
          && (moving.length < FOLD_FX_MOST)) {
        moving.push(node);
        if (shut) {
          /* Stays in layout while it collapses; hidden at the end. */
          node.hidden = false;
          node.classList.add('sp-fx');
          shutting.push(node);
        } else {
          node.hidden = false;
          node.classList.add('sp-fx', 'sp-gone');
          opening.push(node);
        }
        continue;                 /* segWas is settled after the loop */
      }
      node.hidden = shut && !head;
      if (head) {
        node.classList.toggle('sp-shut', shut);
        /* #1285b: what is inside, so a closed segment can be chosen
           without opening it. On an attribute and shown through
           ::after - the reconciler re-dresses a changed element with
           textContent and would wipe a child span every repaint. */
        if (shut) {
          var got = segCount(seg);
          node.setAttribute('data-inside', got
            ? ('  ▸ ' + got.lines + (got.lines === 1 ? ' line' : ' lines')
               + (got.seconds >= 1
                  ? '  ·  ' + Math.round(got.seconds) + 's' : ''))
            : '  ▸');
        } else {
          node.setAttribute('data-inside', '');
        }
      }
    }
    /* #1300b: and only now, once every element has been able to read
       the old value. */
    for (var done in segsNow) segWas[done] = segsNow[done];
    segSettle(shutting, opening);                            /* #1300 */
  }

  /* #1300: THE BATCH, FINISHED TOGETHER.
   *
   * One timer for the whole pass rather than one per node - a few
   * hundred timers is the kind of thing that makes a tablet stutter,
   * and they would all land in the same frame anyway.
   *
   * The close is only committed to `hidden` at the end, so a folded
   * segment still costs nothing in layout once it has gone; the open
   * only has to drop the class it started from. */
  function segSettle(shutting, opening) {
    if (!shutting.length && !opening.length) return;
    if (opening.length) {
      /* A frame with the start value on the node, or there is nothing
         for the transition to run FROM and it arrives instantly. */
      root.requestAnimationFrame(function () {
        for (var i = 0; i < opening.length; i += 1) {
          opening[i].classList.remove('sp-gone');
        }
      });
    }
    if (shutting.length) {
      root.requestAnimationFrame(function () {
        for (var i = 0; i < shutting.length; i += 1) {
          shutting[i].classList.add('sp-gone');
        }
      });
    }
    if (segFxTimer) root.clearTimeout(segFxTimer);
    segFxTimer = root.setTimeout(function () {
      segFxTimer = 0;
      for (var i = 0; i < shutting.length; i += 1) {
        shutting[i].hidden = true;
        shutting[i].classList.remove('sp-fx', 'sp-gone');
      }
      for (var k = 0; k < opening.length; k += 1) {
        opening[k].classList.remove('sp-fx', 'sp-gone');
      }
    }, FOLD_FX_MS + 40);
  }

  /* What is inside a fold, so it can be chosen without opening it. */
  function segCount(seg) {
    var box = el('spScript');
    if (!box || !seg) return null;
    var all = box.querySelectorAll('.sp-el[data-seg="' + seg + '"]');
    var lines = 0, secs = 0;
    for (var i = 0; i < all.length; i += 1) {
      if (!/sp-dialogue/.test(all[i].className)) continue;
      lines += 1;
      secs += Number(all[i].getAttribute('data-secs') || 0) || 0;
    }
    return {lines: lines, seconds: secs};
  }

  function segToggle(seg) {
    if (!seg) return;
    folded[seg] = !folded[seg];
    byHand[seg] = true;              /* the operator's choice outranks */
    segApply(true);                                          /* #1300 */
    foldSave();                                              /* #1294 */
  }

  /* #1294: THE READER'S PLACE OUTLIVES THE VIEW.
   *
   * The kiosk Activity is recreated roughly every five minutes - the
   * gallery writes the device wallpaper, systemui regenerates the
   * Material You overlays, and the resulting CONFIG_ASSETS_PATHS
   * (0x80000000) is not in MainActivity's configChanges mask, so the
   * WebView reloads. Seven relaunches in 33 minutes, each taking every
   * fold and the scroll position with it.
   *
   * localStorage, NOT sessionStorage: a relaunch is a new session and
   * would take session storage with it. Every read and write is
   * guarded - the accessor itself throws in some contexts - and a page
   * with nothing stored must render correctly, which here means the
   * folds simply start closed-behind-the-air as they now do anyway. */
  var FOLD_KEY = 'pine.script.folds.v1';

  function foldSave() {
    try {
      var box = el('spScript');
      root.localStorage.setItem(FOLD_KEY, JSON.stringify({
        folded: folded, byHand: byHand, liveSeg: liveSeg,
        top: box ? Math.round(box.scrollTop) : 0, at: Date.now()}));
    } catch (err) { /* storage blocked: the view still works */ }
  }

  var foldTop = -1;                  /* the scroll to restore, once */

  function foldLoad() {
    var held = null;
    try {
      held = JSON.parse(root.localStorage.getItem(FOLD_KEY) || 'null');
    } catch (err) { held = null; }
    if (!held || typeof held !== 'object') return;
    /* Stale beyond an hour is not this show any more. */
    if (Date.now() - Number(held.at || 0) > 3600000) return;
    if (held.folded && typeof held.folded === 'object') {
      for (var a in held.folded) folded[a] = !!held.folded[a];
    }
    if (held.byHand && typeof held.byHand === 'object') {
      for (var b in held.byHand) byHand[b] = !!held.byHand[b];
    }
    if (Number(held.top) > 0) foldTop = Number(held.top);
  }

  /* The air moved on: fold what it left, unless a hand opened it. */
  function segFollow(seg) {
    if (!seg || seg === liveSeg) return;
    var was = liveSeg;
    liveSeg = seg;
    if (was && !byHand[was]) folded[was] = true;
    folded[seg] = false;
    /* #1300: the hand-off the operator asked to SEE - the finished
       script shutting and the next one opening out. */
    segApply(true);
    foldSave();                                              /* #1294 */
  }

  /* #1289: THE HOUR AHEAD. /api/director?hour=N is already the hour
     as ordered entries, and a planned one carries its written turns. */
  function loadPlan(force) {
    if (planning) return;
    if (!force && Date.now() - planAt < PLAN_REST_MS) return;
    planning = true;
    var want = [api().get('/api/director?hour=0')
      .then(null, function () { return null; })];
    want.push(api().get('/api/director?hour=1')
      .then(null, function () { return null; }));
    Promise.all(want).then(function (got) {
      var fresh = got.filter(Boolean);
      planning = false;
      /* #1289b: a failed read must not WIPE the running order. Both
         fetches swallow their own errors and return null, so a blip
         used to hand back an empty list, paintPlan cleared the node,
         and the hour ahead vanished until the next poll. Keep what we
         have unless something better arrived. */
      if (!fresh.length) return;
      planHours = fresh;
      planAt = Date.now();
      paintPlan();
    }, function () { planning = false; });
  }

  function planRow(cls, text) {
    return make('div', 'sp-el ' + cls, String(text || ''));
  }

  /* #1294: the plan's own keyed nodes. paintPlan called
     box.replaceChildren() on a thirty-second timer - 509 nodes
     destroyed in one batch, ~1,012 a minute, and in one round of
     sixteen it wiped every visible plan row. This is the stitch
     paintScript has had since #1273, on the one pane that never got
     it. */
  var planNodes = new Map();
  var planIn = null;

  function planKeep(key, cls, text) {
    var print = cls + '\u0001' + text;
    var node = planNodes.get(key);
    if (node && node.pinePrint !== print) {
      node.className = cls;
      node.textContent = text;
      node.pinePrint = print;
    }
    if (!node) {
      node = make('div', cls, text);
      node.pinePrint = print;
      planNodes.set(key, node);
    }
    return node;
  }

  function paintPlan() {
    var box = el('spPlan');
    if (!box) return;
    if (planIn !== box) { planNodes.clear(); planIn = box; }
    if (!planHours.length) {
      if (planNodes.size) { box.replaceChildren(); planNodes.clear(); }
      return;
    }
    var order = [];
    var wanted = Object.create(null);
    for (var h = 0; h < planHours.length; h += 1) {
      var page = planHours[h] || {};
      var rows = page.entries || [];
      var ahead = [];
      for (var i = 0; i < rows.length; i += 1) {
        /* What has already been said is the screenplay's job; this pane
           is only what is still to come. */
        var st = String(rows[i].state || '');
        if (st === 'aired' || st.indexOf('went by') === 0) continue;
        ahead.push(rows[i]);
      }
      if (!ahead.length) continue;
      var hourKey = 'h:' + h;
      var when = planKeep(hourKey, 'sp-el sp-planhour sp-planjump',
        (h === 0 ? 'STILL TO COME THIS HOUR' : 'THE HOUR AFTER')
        + '  ·  ' + ahead.length
        + (ahead.length === 1 ? ' segment' : ' segments'));
      wanted[hourKey] = 1;
      /* #1294: in `below` the plan sits 60,242 px down a 62,386 px
         scroll - the whole night away from the line being said. The
         heading is the handle back. Attached once, because planKeep
         hands back the SAME node every repaint. */
      if (!when.__jump) {
        when.__jump = 1;
        when.addEventListener('click', function () {
          if (nowLineId) jumpToLine(nowLineId);
        });
      }
      order.push(when);
      for (var k = 0; k < ahead.length; k += 1) {
        var e = ahead[k];
        var sc = e.script || {};
        var turns = sc.turns || [];
        var mark = String(e.state || '');
        var clock = e.start
          ? new Date(Number(e.start) * 1000).toTimeString().slice(0, 5) : '';
        var segKey = 'p:' + h + ':' + String(e.slot_id || e.ordinal || k);
        var head = planKeep(segKey, 'sp-el sp-planseg'
          + (mark === 'on air' ? ' sp-planlive' : '')
          + (turns.length ? '' : ' sp-planbare'),
          (clock ? clock + '  ' : '')
          + String(e.label || e.kind || 'segment').toUpperCase()
          + '   ' + (e.minutes ? e.minutes + ' MIN' : ''));
        head.setAttribute('data-plan', String(e.slot_id || e.ordinal || k));
        head.setAttribute('data-state', mark);
        wanted[segKey] = 1;
        order.push(head);
        if (!turns.length) {
          /* A hole is shown, not hidden: an operator who sees it before
             the slot arrives can still do something about it. */
          var bare = planKeep(segKey + ':why', 'sp-el sp-planwhy',
            mark || 'nothing behind it');
          wanted[segKey + ':why'] = 1;
          order.push(bare);
          continue;
        }
        for (var t2 = 0; t2 < turns.length; t2 += 1) {
          var turn = turns[t2];
          var cueKey = segKey + ':c' + t2;
          var lineKey = segKey + ':l' + t2;
          order.push(planKeep(cueKey, 'sp-el sp-character sp-plancue',
            String(turn.who || turn.seat || '').toUpperCase()));
          order.push(planKeep(lineKey, 'sp-el sp-dialogue sp-planline',
            String(turn.text || '')));
          wanted[cueKey] = 1;
          wanted[lineKey] = 1;
        }
      }
    }
    planNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode === box) held.remove();
      planNodes.delete(key);
    });
    stitchScript(box, order);
  }

  /* #1289: the two layouts differ only in where the plan hangs. */
  function planLayout(way) {
    planWay = (way === 'beside') ? 'beside' : 'below';
    var box = el('spPlan');
    var script = el('spScript');
    if (!box || !script || !script.parentNode) return;
    host.classList.toggle('sp-beside', planWay === 'beside');
    if (planWay === 'below') {
      script.appendChild(box);                 /* one continuous scroll */
    } else {
      script.parentNode.insertBefore(box, script.nextSibling);
    }
  }

  function scriptBlock(item) {
    var type = String(item.type || 'action');
    var node = make('div', 'sp-el sp-' + type);
    node.textContent = String(item.text || '');
    if (item.id) node.dataset.el = String(item.id);
    if (item.line) node.dataset.line = String(item.line);
    if (item.seg) node.dataset.seg = String(item.seg);        /* #1285 */
    if (item.seconds) node.dataset.secs = String(item.seconds);
    if (type === 'scene') {
      /* #1285: the heading is the fold's handle. */
      node.classList.add('sp-fold');
      node.addEventListener('click', function (ev) {
        ev.stopPropagation();        /* not a pane gesture (#1272) */
        segToggle(String(item.seg || item.id || ''));
      });
    }
    /* A line that has not aired yet is the interesting one - it can still
     * be changed before the room hears it. ONLY 'prepared' is that line;
     * 'published' and 'stream' have both already been heard. */
    if (item.aired === 'prepared') node.classList.add('pending');
    if (item.tinted) node.classList.add('tinted');
    /* #1330: the record that is on the deck RIGHT NOW, not one that
     * finished an hour ago. The two read identically before this, so a
     * script that had just caught up with a track change looked exactly
     * like one that had skipped it - which is how "the script jumped
     * over changing the track" is what a forty second lag looks like
     * from the outside. The server says which; this shows it. */
    if (item.playing) node.classList.add('sp-spinning');
    /* #1330: where the SCRIPT put this line. Carried so a reader can
     * follow the running order without re-deriving it, and so the mark
     * can tell a scripted line from one nothing wrote. */
    if (item.block) node.dataset.block = String(item.block);
    if (item.ord !== undefined && item.ord !== null) {
      node.dataset.ord = String(item.ord);
    }
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
  /* #1330: THE PANEL'S PLAYHEAD, ACROSS THE WEBVIEW BOUNDARY.
   *
   * soundingPlayer() below scans THIS document. On the desktop chrome
   * that document holds one <audio> (desktopRadioPlayer); djVoiceAudio0/1
   * are created by the panel, which runs inside <webview id="radioFrame">
   * and is a DOM this one cannot reach. So on the chrome the scan
   * returned null every single time - not intermittently - and #1278's
   * read position, #1287's file guard and #1294's named-row preference
   * were all silently dead there, leaving the view on the clock estimate
   * the whole lot was written to replace.
   *
   * webview-preload.js posts the position out; renderer.js stamps it on
   * arrival and hands back null once it is stale. Stale has to mean
   * absent: a frozen mark reads as a working one, which is worse than
   * falling back to the clock and is how this fault survived so long. */
  function bridgeHead() {
    try { return (root.pinePlayhead && root.pinePlayhead()) || null; }
    catch (e) { return null; }
  }

  /* True when the position is READ off the sound, false when it is
   * estimated. The searches below are only trustworthy in the first
   * case, and they had no way to ask. */
  function headIsRead() {
    return !!(bridgeHead() || soundingPlayer());
  }

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
    var head = bridgeHead();                              /* #1330 */
    if (head) return Number(head.t) || 0;
    var player = soundingPlayer();
    if (player) return Number(player.currentTime) || 0;
    if (!liveStream || !liveStream.at) return -1;
    return ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
  }

  /* The row the room is hearing. stream_now first - it is exact to the
   * quarter second - and speaking_now only as a fallback, since it is
   * refreshed every four seconds and a four second lag on a four second
   * line points at the wrong one. */
  /* #1287: the basename of the file the player is actually sounding,
     so a row can be asked whether it belongs to it. `from`/`until` are
     offsets into a row's OWN file, and matching them without checking
     the file is how a row 99 seconds away wins - 23 of the 24
     wrong-line samples were exactly that. */
  function soundingFile() {
    var head = bridgeHead();                              /* #1330 */
    if (head) return String(head.file || '');
    var a = soundingPlayer();
    if (!a) return '';
    var src = String(a.currentSrc || a.src || '').split('?')[0];
    return src.split('/').pop() || '';
  }

  function rowFile(row) {
    return String(row.clip_media || row.media || '');
  }

  /* #1294: a row's window under EITHER name.
   *
   * The burst table calls them from/until; the feed calls them
   * clip_from/clip_until, and 168 of 171 feed rows carry only the
   * second pair. within() read only the first, so on the feed every
   * multi-row file collapsed into the lone-row branch and the last row
   * of the file won the whole file. */
  function rowFrom(row) {
    var v = Number(row.from);
    return isFinite(v) ? v : Number(row.clip_from);
  }

  function rowUntil(row) {
    var v = Number(row.until);
    return isFinite(v) ? v : Number(row.clip_until);
  }

  function activeRow() {
    var t = streamAt();
    var rows = (liveStream && liveStream.rows) || [];
    var file = soundingFile();
    /* #1330: A BURST THAT HAS RUN OUT IS NOT A TABLE TO SEARCH.
     *
     * With an estimated position there is no filename to hold a row to,
     * so #1287's guard cannot fire and a finished burst's windows still
     * bracket the estimate - lighting a row that stopped sounding some
     * time ago and holding it lit. #1294 measured that shape: 12 of 19
     * wrong samples were more than two seconds in.
     *
     * The station's own reader already refuses this - it accepts an
     * offset only inside [0, length + 4] before falling back to
     * speaking_now - and the view should refuse it on the same terms.
     * Where the position is READ this cannot arise, because the file
     * guard settles it; this is only for where we are guessing. */
    if (!headIsRead() && liveStream && liveStream.at) {
      var span = Number(liveStream.length || 0) + 4;
      if (!(t >= 0 && t <= span)) {
        return (speakingNow && speakingNow.id)
          ? {id: String(speakingNow.id), from: 0, until: 0, at: t,
             index: -1, of: rows.length}
          : null;
      }
    }
    function within(list, of) {
      var lone = null, loneAt = -1;
      for (var i = 0; i < list.length; i += 1) {
        var row = list[i];
        var mine = rowFile(row);
        /* #1287: only rows of the file that is sounding. */
        if (file && mine && mine !== file) continue;
        var from = rowFrom(row), until = rowUntil(row);
        if (!isFinite(from) || !isFinite(until)) {
          /* #1287: A ROW THAT IS THE WHOLE FILE HAS NO WINDOW.
           * Measured: 0 of 25 `interject` rows carry from/until - they
           * are a clip of one line, so there is nothing to offset
           * into - and interject was lit correctly 0 of 37 times. My
           * #1278 note claimed the wider search would catch them; it
           * could not, because the field its loop needs does not
           * exist on them. If the sounding file IS this row's file,
           * this row is the line. */
          if (file && mine === file) { lone = row; loneAt = i; }
          continue;
        }
        if (t >= from && t < until) {
          return {id: String(row.id || ''), from: from, until: until,
            at: t, index: i, of: of};
        }
      }
      if (lone) {
        return {id: String(lone.id || ''), from: 0,
          until: Number(lone.seconds) || 0, at: t, index: loneAt, of: of};
      }
      return null;
    }
    if (t >= 0) {
      /* #1294: WHICHEVER TABLE CAN BE CHECKED AGAINST THE SOUND.
       *
       * liveStream.rows carry {id, from, until} and no media - probed
       * on the tablet, that is the whole of streamKeys - so #1287's
       * file guard above can never fire for them. When the sounding
       * file moves on and stream_now has not, the old burst's window
       * brackets the new file's currentTime and lights a row that is
       * not being said, for the length of the clip: 12 of the 19 wrong
       * samples measured were more than two seconds in, which is what
       * separates this from the mark merely lagging.
       *
       * The feed's rows carry clip_media, so when we know the name of
       * what is sounding they are the table that can be held to it.
       * Where the two describe the same file they agree to three
       * decimals, so this is a change of ORDER, not of arithmetic. */
      var fed = [];
      try { fed = (root.PineStationFeed.rows() || []); } catch (e1) { fed = []; }
      if (file && fed.length) {
        var named = within(fed, fed.length);
        if (named) return named;
      }
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
      var all = fed;
      if (!file && all.length && all !== rows) {
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
    segFollow(node.getAttribute('data-seg') || '');          /* #1285 */
    if (follow) {
      /* Centred, not merely visible: the operator is reading the
       * conversation, and the next line wants to be under it.
       *
       * THE GUARD IS THE WHOLE FIX. Measured: the highlight was on screen
       * in 0 of 7 talking samples, because a smooth scroll fires scroll
       * events all the way down, the handler below read "the line is not
       * visible yet" from one of them and switched following OFF - the
       * auto-scroll cancelled itself on its first frame, every time. */
      /* #1282: MOVE ONLY IF IT HAS TO, AND DO NOT CANCEL YOURSELF.
       *
       * `block:'center'` re-centred on every line change - about ten
       * full animations a minute at a 6.4s median dwell, each one a
       * chance for the page to move under a finger. `nearest` moves
       * only when the line is actually outside the pane, and
       * `.sp-now`'s scroll-margin keeps it off the edge when it does.
       *
       * And the 900ms guard was a fixed window against a scroll whose
       * duration grows with distance - 21.9% of movements were still
       * running two samples later. When it expired mid-flight the
       * animation's own scroll events reached the handler, which read
       * geometry that had not settled and switched following off. The
       * scroll cancelled itself, which is the very fault the guard
       * exists to prevent. `scrollend` says when it is really over. */
      selfScrollUntil = Date.now() + 2400;        /* backstop only */
      /* #1330: ON THE BOX THAT ACTUALLY SCROLLS.
       *
       * This said `script`, which is declared in build() and in
       * planLayout() and in neither case is in scope here. Under 'use
       * strict' it resolved through named access on the global object to
       * <section id="script"> - the view HOST, which is overflow:hidden
       * and never scrolls. So 'scrollend' never fired, selfScrollUntil
       * never cleared early, and the 2400ms backstop governed every
       * move: for 2.4s after each highlight the handler below returned
       * at its first line and the operator's own scroll was discarded,
       * which is the precise opposite of what the guard is for. */
      var box = el('spScript');
      try {
        if (box && 'onscrollend' in box) {
          box.addEventListener('scrollend', function done() {
            box.removeEventListener('scrollend', done);
            selfScrollUntil = 0;
          }, {once: true});
        }
      } catch (err) { /* the backstop still covers it */ }
      try { node.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
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
  /* #1295: HOW MUCH OF THIS CLIP IS LEFT, drawn on the line itself.
   *
   * Set as a custom property and an attribute, never as a child node:
   * the reconciler re-dresses a changed line with textContent, so a
   * child span would be wiped every repaint. The CSS paints the bar
   * off --sp-run and the countdown off data-left.
   *
   * A row with no usable window (an interject is a clip of one line
   * and carries neither end) gets no bar rather than a wrong one. */
  var runNode = null;

  function markRun(row) {
    var node = (row && row.id)
      ? document.querySelector('.sp-el[data-line="' + row.id + '"]')
      : null;
    if (runNode && runNode !== node) {
      runNode.style.removeProperty('--sp-run');
      runNode.removeAttribute('data-left');
    }
    runNode = node;
    if (!node || !row) return;
    var span = Number(row.until) - Number(row.from);
    var gone = Number(row.at) - Number(row.from);
    if (!isFinite(span) || span <= 0 || !isFinite(gone)) {
      node.style.removeProperty('--sp-run');
      node.removeAttribute('data-left');
      return;
    }
    var run = Math.max(0, Math.min(1, gone / span));
    node.style.setProperty('--sp-run', (run * 100).toFixed(1) + '%');
    var left = Math.max(0, Math.round(span - gone));
    node.setAttribute('data-left', left >= 60
      ? (Math.floor(left / 60) + ':' + ('0' + (left % 60)).slice(-2))
      : (left + 's'));
  }

  function tick() {
    var row = activeRow();
    markNow(row ? row.id : '');
    markRun(row);                                            /* #1295 */
    paintSaying(row);                                        /* #1298 */
    markFeedLive(row ? row.id : '');            /* #1279 */
    /* #1286: say when the room is quiet, instead of leaving a page full
       of `pending` and `tinted` marks to be read as though one of them
       were live. */
    try {
      /* #1294: the PLAYER, not the row. This read activeRow(), which
         falls back to speaking_now, so quiet stayed off for a second
         or two after a clip ended - 22 of 348 silent samples. What
         "quiet" means is that nothing is sounding, and there is an
         element that knows. */
      host.classList.toggle('sp-quiet', !soundingPlayer() && !(row && row.id));
    } catch (err) { /* the mark still stands on its own */ }
    paintStatus();
  }

  /* #1303b: the row the sampler's own sourceFor() expects. A clip line
     carries its url and is taken exactly; a spoken line carries its id
     and the clip route cuts it out of the welded round. */
  function samplerRow(item) {
    if (!item) return null;
    var id = String(item.line || item.id || '');
    var url = String(item.clip || '');
    if (!id && !url) return null;
    var row = {id: id, text: String(item.text || ''),
               who: String(item.name || item.who || '')};
    if (url) { row.url = url; row.sfx = true; }
    return row;
  }

  function padRow(item) {
    var row = samplerRow(item);
    if (!row) return null;
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') return null;
    try {
      if (typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        return null;                 /* nothing behind it: no button */
      }
    } catch (err) { return null; }
    var btn = make('button', 'sp-btn wide', 'Send to a sampler pad');
    btn.title = 'Put this on the first free pad of the sampler';
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = 'taking it...';
      Promise.resolve(sampler.grab(row)).then(function (got) {
        var ok = got && got.ok;
        btn.textContent = ok ? 'on a pad' : ((got && got.why) || 'it refused');
        btn.disabled = !!ok;
        if (!ok) setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      }).catch(function (err) {
        btn.textContent = 'it refused: ' + (err && err.message);
        setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      });
    });
    return btn;
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

    /* #1303b: ASSIGN IT TO A PAD.
     *
     * Through PineSampler.grab, the published seam - whose own comment
     * says it exists so "another view can GREY ITS OWN BUTTON with the
     * same answer this one uses, rather than guessing from `aired` -
     * which is the exact mistake that once offered 7 of ~220 takeable
     * moments". So this asks takeable() and simply is not there when
     * there is nothing behind the line. */
    var take = padRow(item);
    if (take) row.appendChild(take);

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
    treeRow.appendChild(buildSaying());      /* #1298 */
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
      /* #1282: TWICE, NOT ONCE. Following used to end the first time
         the lit node looked off-screen, which a long smooth scroll
         guarantees mid-flight. Two consecutive readings means a single
         unsettled frame cannot end it - but a real hand-scroll, which
         produces many, still does. */
      var node = nowLineId
        && document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (node) {
        var box = script.getBoundingClientRect();
        var seat = node.getBoundingClientRect();
        var here = seat.bottom > box.top && seat.top < box.bottom;
        if (here) { adrift = 0; follow = true; }
        else if ((adrift += 1) >= 2) { follow = false; }
      } else if (nowLineId === '') {
        /* #1270 leaves this empty while the line has not arrived. The
           old code reconsidered nothing here, so scrolling away during
           that window did not count as "let me read" and the page
           yanked back the moment the line landed. */
        if ((adrift += 1) >= 2) { follow = false; }
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
    /* #1289: the hour ahead, and which way to show it. */
    var ahead = make('button', 'sp-crawl-go sp-planway');
    ahead.type = 'button';
    ahead.textContent = '⎘';
    ahead.title = 'The hour ahead: below the script, or beside it';
    ahead.addEventListener('click', function (ev) {
      ev.stopPropagation();
      planLayout(planWay === 'below' ? 'beside' : 'below');
      ahead.classList.toggle('on', planWay === 'beside');
      loadPlan(true);
    });
    tools.appendChild(ahead);
    right.appendChild(tools);

    var plan = make('div', 'sp-plan');
    plan.id = 'spPlan';
    script.appendChild(plan);          /* 'below' is the default */

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
    foldLoad();                                              /* #1294 */
    if (!scopeFrame) paintScope();                           /* #1298 */

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
        loadPlan(false);                              /* #1289 */
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
    loadPlan(true);                                   /* #1289 */
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
