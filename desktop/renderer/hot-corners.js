/* HOT CORNERS. Four swipes from the edges of the glass, each one a tool.
 *
 * "If I swipe into the tablet from the top left of the screen down to the
 * center, I want to take a screenshot of the screen and I want to be able
 * to draw on the screen and outline things with my finger in red and be
 * able to submit that image along with the report into the Pine box inbox.
 * If I swipe in from the right side, I want to save a recording and save
 * it out to the Pine Box recordings folder that I have specified. And I
 * want to save anywhere from the last five seconds to the last 20 minutes.
 * So the tablet should always be recording, and I want to basically be
 * able to swipe into the center from the top right and be able to export
 * a video of whatever has been happening on the tablet for the last X
 * amount of time and save that to the directory. If I swipe from the left
 * corner up to the center, I want to basically bring up a dialogue window
 * of what just happened. So basically it's an inspector window that shows
 * the last line of dialogue or the active playing dialogue, and it gives
 * me a flow by flow flow chart explaining everything that's happened as
 * far as how this piece of line came to be broadcasted and all the
 * parameters pertaining to it. ... If I go to the bottom right corner and
 * I swipe up to the center, I basically want to replay the last sound
 * effects clip that was played. I also want preferences ... for each of
 * the hot corners ... change these and set these and disable these."
 *
 * THE GESTURE. A primary pointer goes down inside a 110 px square at one
 * of the four corners and travels at least 150 px toward the centre -
 * both components pointing inward, within 35 degrees of the diagonal -
 * inside 1.5 s, with one finger. Anything else is abandoned and nothing
 * else on the page is touched: the press was not ours and it still goes
 * where it was going. Only a COMMITTED swipe is swallowed (the move, the
 * up, and the synthetic click the platform sends after it), and only
 * then does the corner's action run. Listening is in the capture phase on
 * the document, so the right-hand rail, PineDrag, the sampler and every
 * view keep exactly the events they had; this never stops an event it has
 * not claimed.
 *
 * THE GLOW. A quarter-circle at the corner that grows with the drag. One
 * fixed element per gesture, moved with transform and opacity only, so
 * the tablet's frame pipeline (which is sensitive: see the tablet frame
 * notes) does no layout for it.
 *
 * THE BRIDGE. On the tablet the kiosk's Kotlin side exposes these on
 * pineDesktop: screenShot(), replayState(), replayExport({seconds,
 * upload}), replayFrames({seconds, count}), hotCorners(),
 * hotCornersSet({...}); and it calls
 * window.PineHotCorners.configure(cfg) on page load and whenever the
 * drawer changes a preference. On the desk (Electron) the preload exposes
 * pineDesktop too, with shotView() for a picture of the window but no
 * replay ring. Every road is feature-tested with typeof, and where a
 * surface has no road the toast says so rather than failing quietly.
 *
 * ES5 throughout: this file is injected into an Android WebView as well
 * as loaded by the desk. No emoji anywhere; icons are Carbon, through
 * pineIcon('c:name') from pine-icons.js.
 */
(function (root) {
  'use strict';

  var doc = root.document || null;

  /* ------------------------------------------------------- the constants */

  var CORNER_PX = 110;      /* the square at each corner a swipe may start in */
  var COMMIT_PX = 150;      /* how far it must travel toward the centre */
  var COMMIT_MS = 1500;     /* and how quickly */
  var COMMIT_DEG = 35;      /* within this many degrees of the diagonal */
  var JUDGE_PX = 40;        /* past this the direction is judged; short of it a
                               wobble is still a wobble */

  /* #1166: "Make sure I can also activate hot corners by tapping on the
   * corners. or clicking."
   *
   * A TAP IS A SWIPE THAT NEVER WENT ANYWHERE. Both begin with exactly the
   * same pointerdown - same corner square, same gates, same glow - and the
   * two are told apart only at the up. These are the numbers that do it.
   *
   * TAP_PX is deliberately UNDER JUDGE_PX. Short of JUDGE_PX the judge
   * returns 'going' and never rules on direction, so a press that stayed
   * inside TAP_PX cannot have been thrown out as "not toward the centre"
   * along the way - a tap and a failed swipe can therefore never be
   * confused for one another. Past it the press was travelling somewhere
   * and belongs to the swipe, committed or abandoned; it is not a tap.
   *
   * TAP_MS leaves the long press alone. Half a second is far longer than a
   * tap on glass and far shorter than a deliberate hold, so anything that
   * wants press-and-hold in a corner later still has it to claim. */
  var TAP_PX = 24;
  var TAP_MS = 500;

  var STORE = 'pineHotCorners';
  var STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1200];

  /* #1155 THE SCRUB STRIP'S REACH. "I would like to go back the whole
   * recording range."
   *
   * SCRUB_WINDOW   how many seconds of ring one strip of thumbnails shows.
   * SCRUB_COUNT    how many thumbnails that is.
   * SCRUB_STEP     windows are snapped to this many seconds so that sliding
   *                back and forth lands on the SAME window twice and the
   *                cache can answer it. Without snapping every pixel of the
   *                coarse slider would be a fresh mux of the ring.
   * SCRUB_SETTLE   how long the coarse slider must be still before the ask
   *                goes out. A drag across 20 minutes crosses hundreds of
   *                windows and must not ask for any of them on the way.
   * SCRUB_CACHE    the cap on remembered thumbnails, in BASE64 CHARACTERS.
   *                5 MB of base64 is about 170 thumbnails at the ~30 kB
   *                each one measures - 17 windows - and JavaScript holds
   *                those characters as UTF-16, so the real cost is nearer
   *                10 MB. That is the ceiling worth paying on this tablet;
   *                past it the least recently used window is dropped. */
  var SCRUB_WINDOW = 5;
  var SCRUB_COUNT = 10;
  var SCRUB_STEP = 5;
  var SCRUB_SETTLE = 260;
  var SCRUB_CACHE = 5 * 1024 * 1024;
  var ACTIONS = ['off', 'shot', 'export', 'inspect', 'sfx', 'report'];
  var ACTION_WORDS = {
    off: 'Off',
    shot: 'Screenshot and draw',
    'export': 'Export the screen video',
    inspect: 'Inspect the last line',
    sfx: 'Replay the last SFX clip',
    report: 'File a Pine report'
  };
  var CORNER_WORDS = {tl: 'Top left', tr: 'Top right', bl: 'Bottom left', br: 'Bottom right'};
  var CORNERS = ['tl', 'tr', 'bl', 'br'];
  var DEFAULTS = {enabled: true, tl: 'shot', tr: 'export', bl: 'inspect', br: 'sfx'};
  /* "Heard" - the row reached an output. `airing` is what the station
   * stamps on the row that is sounding now (lcd-dialogue.js reads it the
   * same way); prepared / held / analysis were written and never heard. */
  var HEARD = ['stream', 'box', 'both', 'published', 'page', 'airing'];
  var NOT_DIALOGUE = ['sfx', 'marker', 'music'];

  /* ------------------------------------------------------------ helpers */

  function now() { return Date.now(); }

  function merge(into, from) {
    for (var k in from) {
      if (Object.prototype.hasOwnProperty.call(from, k)) into[k] = from[k];
    }
    return into;
  }

  function make(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* One Carbon glyph, or nothing - never a character standing in for one. */
  function icon(name) {
    var out = '';
    try { if (typeof root.pineIcon === 'function') out = root.pineIcon(name); } catch (e) { out = ''; }
    return out || '';
  }

  function button(cls, words, iconName) {
    var b = make('button', cls);
    b.type = 'button';
    var glyph = iconName ? icon(iconName) : '';
    if (glyph) b.innerHTML = glyph;
    b.appendChild(make('span', '', words));
    return b;
  }

  function bridge() { return root.pineDesktop || null; }

  function has(name) {
    var d = bridge();
    return !!(d && typeof d[name] === 'function');
  }

  /* The set's rule (script-page.js stationUrl, #1399): served by the
   * station - the kiosk's loopback door, any http page - a station path is
   * already right; on the desk, in a file: page, the chrome knows the
   * station's base and the loopback is the fallback. */
  function stationUrl(u) {
    u = String(u || '');
    if (!u || /^https?:\/\//.test(u)) return u;
    var proto = '';
    try { proto = String(root.location && root.location.protocol); } catch (e) { proto = ''; }
    if (/^https?:$/.test(proto)) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (e) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }

  function station() {
    if (!has('get')) return Promise.reject(new Error('no station bridge on this surface'));
    return Promise.resolve(bridge().get('/api/dj'));
  }

  /* The station key the way talk-dot's serverKey() finds it: the page's
   * SERVER_KEY (the kiosk's panel page), else the bridge's config (the
   * desk). '' where neither is reachable - said, not assumed. */
  function stationKey() {
    try { if (typeof root.SERVER_KEY === 'string' && root.SERVER_KEY) return Promise.resolve(root.SERVER_KEY); }
    catch (e) { /* no such global */ }
    if (!has('readConfig')) return Promise.resolve('');
    return Promise.resolve(bridge().readConfig()).then(function (cfg) {
      return String((cfg && (cfg.apiKey || cfg.api_key)) || '');
    }, function () { return ''; });
  }

  /* A picture the annotator can draw from and still export. A data: URL
   * is already fine. A station picture on an http page (the kiosk) is
   * same-origin, so the <img> may load it directly. On the desk the page
   * is file: and the picture is cross-origin: drawn straight into a
   * canvas it would TAINT it and toDataURL would refuse - so it is fetched
   * with the station key, the way talk-dot's serverKey() road does, and
   * drawn from a blob URL, which is ours. Answers {src, revoke}. */
  function loadPicture(src) {
    src = String(src || '');
    if (/^(data|blob):/.test(src)) return Promise.resolve({src: src, revoke: null});
    var url = stationUrl(src);
    var proto = '';
    try { proto = String(root.location && root.location.protocol); } catch (e) { proto = ''; }
    var sameOrigin = /^https?:$/.test(proto) && !/^https?:\/\//.test(src);
    if (sameOrigin || typeof root.fetch !== 'function' || !root.URL || !root.URL.createObjectURL) {
      return Promise.resolve({src: url, revoke: null});
    }
    return stationKey().then(function (key) {
      var opts = key ? {headers: {Authorization: 'Bearer ' + key}} : {};
      return root.fetch(url, opts).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.blob();
      }).then(function (blob) {
        var made = root.URL.createObjectURL(blob);
        return {src: made, revoke: function () { try { root.URL.revokeObjectURL(made); } catch (e) { /* gone */ } }};
      });
    }).then(null, function () {
      /* The fetch road failed: let the <img> try, and say so if the
       * export is then refused. */
      return {src: url, revoke: null};
    });
  }

  function fmtSeconds(s) {
    s = Number(s) || 0;
    if (s < 60) return s + ' s';
    var m = s / 60;
    return (m === Math.floor(m) ? m : m.toFixed(1)) + ' min';
  }

  /* #1155: HOW FAR BACK, IN REAL TIME. "I would like to go back the whole
   * recording range" means the labels run to twenty minutes, and "-732.4s"
   * is not a time anybody reads. Under a minute keeps the tenth of a
   * second the operator was already picking frames by; past it the tenth
   * is noise and the minute is the thing.
   *
   *   0      -> 'now'      12.4 -> '12.4s'
   *   72     -> '1m 12s'   732  -> '12m 12s'
   *
   * Pure, and the one place this wording is decided: the thumbnail labels,
   * the coarse slider's read-out and the line the report is filed with all
   * come through here, so they can never disagree with each other. */
  function fmtBack(sec) {
    sec = Number(sec);
    if (!isFinite(sec) || sec <= 0) return 'now';
    if (sec < 60) return sec.toFixed(1) + 's';
    var m = Math.floor(sec / 60);
    var s = Math.round(sec - m * 60);
    if (s === 60) { m += 1; s = 0; }
    return m + 'm ' + s + 's';
  }

  /* -------------------------------------------------------------- config */

  var cfg = merge({}, DEFAULTS);

  /* What a patch is allowed to say. A corner is one of the six actions or
   * it is 'off'; `enabled` is a boolean; `ring` is the native side's own
   * number (how long the replay ring keeps) and is carried, not judged. */
  function clean(patch) {
    var out = {};
    if (!patch || typeof patch !== 'object') return out;
    if (patch.enabled !== undefined) out.enabled = !!patch.enabled;
    for (var i = 0; i < CORNERS.length; i += 1) {
      var c = CORNERS[i];
      if (patch[c] === undefined || patch[c] === null) continue;
      var v = String(patch[c]).toLowerCase();
      out[c] = ACTIONS.indexOf(v) >= 0 ? v : 'off';
    }
    if (patch.ring !== undefined) out.ring = patch.ring;
    return out;
  }

  /* Merge and keep. localStorage is wrapped because the accessor itself
   * can throw (a WebView with site data blocked, a thumbnail capture). */
  function configure(patch) {
    merge(cfg, clean(patch));
    try { root.localStorage.setItem(STORE, JSON.stringify(cfg)); } catch (e) { /* kept in memory only */ }
    paintPrefs();
    return config();
  }

  function config() { return merge({}, cfg); }

  (function load() {
    try {
      var raw = root.localStorage.getItem(STORE);
      if (raw) merge(cfg, clean(JSON.parse(raw)));
    } catch (e) { /* the defaults stand */ }
  })();

  /* ---------------------------------------------------------- the judge */

  /* Which corner a point is in, or ''. Pure, so it can be tested. */
  function cornerAt(x, y, w, h) {
    var left = x <= CORNER_PX, right = x >= w - CORNER_PX;
    var top = y <= CORNER_PX, bottom = y >= h - CORNER_PX;
    if (top && left) return 'tl';
    if (top && right) return 'tr';
    if (bottom && left) return 'bl';
    if (bottom && right) return 'br';
    return '';
  }

  /* The centre's sign from each corner: +1 when the centre is to the
   * right of / below the corner. */
  function signs(corner) {
    return {
      x: (corner === 'tl' || corner === 'bl') ? 1 : -1,
      y: (corner === 'tl' || corner === 'tr') ? 1 : -1
    };
  }

  /* One drag, judged: {state: 'going'|'commit'|'drop', progress, why}.
   * dx/dy are the pointer's travel from where it went down; ms the time.
   *
   * The direction is judged once the finger has gone JUDGE_PX, not at the
   * commit distance: a press at the top-left corner dragged straight down
   * is a scroll, and it is handed back after 40 px rather than 150, so a
   * corner is never a dead zone for scrolling. */
  function judge(corner, dx, dy, ms) {
    if (ms > COMMIT_MS) return {state: 'drop', progress: 0, why: 'too slow'};
    var s = signs(corner);
    var ax = dx * s.x, ay = dy * s.y;          /* positive = toward the centre */
    var dist = Math.sqrt(dx * dx + dy * dy);
    var progress = Math.max(0, Math.min(1, dist / COMMIT_PX));
    if (dist < JUDGE_PX) return {state: 'going', progress: progress};
    if (ax <= 0 || ay <= 0) return {state: 'drop', progress: 0, why: 'not toward the centre'};
    var deg = Math.abs(Math.atan2(ay, ax) * 180 / Math.PI - 45);
    if (deg > COMMIT_DEG) return {state: 'drop', progress: 0, why: 'off the diagonal'};
    if (dist < COMMIT_PX) return {state: 'going', progress: progress};
    return {state: 'commit', progress: 1};
  }

  /* #1166: IS THIS PRESS SOMEBODY ELSE'S?
   *
   * "Make sure I can also activate hot corners by tapping on the corners.
   *  or clicking."
   *
   * A tap is a far more dangerous gesture than a swipe, because a tap is
   * what everything else on the screen is listening for too. The corner
   * squares are not empty: the TOP RIGHT sits under the view rail, whose
   * tabs are the only way between views on the tablet, and the TOP LEFT
   * sits under the panel's own controls on the desk. A corner that ate
   * those would be far worse than no corner at all.
   *
   * So the tap is taken ONLY off the page's own background. Two families
   * are refused, and a press that lands on either is left entirely alone -
   * it is not swallowed, not acted on, and reaches whatever it was going
   * to reach:
   *
   *   THINGS THAT ARE OPERATED. button, a, input, select, textarea,
   *   label, summary, and anything wearing role=button/link/tab/checkbox/
   *   slider/menuitem or contenteditable. That one list covers the rail's
   *   tabs (they are <button class="pine-view-tab">), every sheet button,
   *   the clock's GRAB button and the search box.
   *
   *   SURFACES THAT OWN THEIR OWN GESTURES. The SFX set (#sfxTv, which
   *   takes a tap to open its menu and a double tap to replay), the talk
   *   dot, the report pad, the camera, the rail's own body between its
   *   tabs, and this file's own furniture. These are floating things that
   *   can sit anywhere, including squarely in a corner.
   *
   * THE ANSWER IS DECIDED AT POINTERDOWN, not at the up, because that is
   * where the operator's finger actually landed - by the up the element
   * under it may have moved or gone. And it governs the TAP ONLY: the
   * swipe is untouched, so a swipe that begins on a rail tab still works
   * exactly as it did before this change.
   *
   * WHEN IN DOUBT, DO NOT TAKE IT. A throw anywhere in this walk answers
   * "yes, somebody else's" - the corner losing a tap is a small thing
   * beside the corner eating a press that was not its own. */
  function overControl(node) {
    var TAGS = {button: 1, a: 1, input: 1, select: 1, textarea: 1,
                label: 1, summary: 1, option: 1};
    var ROLES = {button: 1, link: 1, tab: 1, checkbox: 1, radio: 1,
                 slider: 1, menuitem: 1, switch: 1, textbox: 1};
    /* Floating surfaces with gestures of their own, by id or by class. */
    var OWNED = /(^|\s)(pine-view-tab|pineViewRail|sfx-tv|pine-cam|hc-btn|hc-pick|hc-x|hc-glow|hc-strip|hc-toast)(\s|$)/;
    var OWNED_ID = {sfxTv: 1, pineViewRail: 1, pineTalkDot: 1, pineTalkSay: 1,
                    pineReportPad: 1, pineTip: 1};
    try {
      var el = node;
      if (el && el.nodeType === 3) el = el.parentNode;   /* a text node */
      var hops = 0;
      while (el && el.nodeType === 1 && hops < 60) {
        if (el === doc.body || el === doc.documentElement) return false;
        var tag = String(el.tagName || '').toLowerCase();
        if (TAGS[tag] === 1) return true;
        if (el.getAttribute) {
          var role = el.getAttribute('role');
          if (role && ROLES[String(role).toLowerCase()] === 1) return true;
          if (el.getAttribute('contenteditable') === 'true') return true;
        }
        if (el.id && OWNED_ID[el.id] === 1) return true;
        /* className is an SVGAnimatedString on an SVG node, not a string. */
        var cls = el.className;
        if (typeof cls !== 'string') cls = (cls && cls.baseVal) || '';
        if (cls && OWNED.test(cls)) return true;
        el = el.parentNode;
        hops += 1;
      }
    } catch (err) {
      return true;                      /* unreadable: leave the press alone */
    }
    return false;
  }

  /* --------------------------------------------------------- the glow */

  var glow = null;

  var pulseTimer = 0;

  function glowShow(corner, progress) {
    if (!doc || !doc.body) return;
    /* #1166: a swipe starting during a tap's pulse owns the glow from
     * here; the pulse must not hide it out from under the drag. */
    if (pulseTimer) { clearTimeout(pulseTimer); pulseTimer = 0; }
    if (!glow) {
      glow = make('div', 'hc-glow');
      doc.body.appendChild(glow);
    }
    glow.className = 'hc-glow on ' + corner;
    var k = 0.25 + progress * 0.75;
    glow.style.transform = 'scale(' + k.toFixed(3) + ')';
    glow.style.opacity = String(0.35 + progress * 0.6);
  }

  function glowHide() {
    if (pulseTimer) { clearTimeout(pulseTimer); pulseTimer = 0; }
    if (!glow) return;
    glow.className = 'hc-glow';
    glow.style.opacity = '0';
  }

  /* #1166: THE TAP'S OWN FLASH. A swipe grows the glow under the finger,
   * so a tap - which has no travel to grow with - would otherwise fire
   * with a glow that barely appeared. This puts it up at full and lets it
   * go: dropping the `on` class hands it back to the stylesheet's
   * .18s opacity fade, so the corner that fired is unmistakably the one
   * that lights, and it is gone before the action's own sheet arrives. */
  function glowPulse(corner) {
    glowShow(corner, 1);
    pulseTimer = setTimeout(function () {
      pulseTimer = 0;
      if (!glow) return;
      glow.className = 'hc-glow';
      glow.style.opacity = '0';
    }, 150);
  }

  /* ---------------------------------------------------------- the gesture */

  var live = null;                       /* the drag being judged */
  var swallowId = null;                  /* the pointer whose up we still owe a swallow */
  var swallowClickUntil = 0;             /* the synthetic click after a commit */
  var sheets = [];                       /* what is open: while a sheet is up the
                                            corners belong to its controls */

  function eat(ev) {
    try { ev.preventDefault(); } catch (e) { /* passive */ }
    try { ev.stopPropagation(); } catch (e) { /* not an event */ }
    try { if (ev.stopImmediatePropagation) ev.stopImmediatePropagation(); } catch (e) { /* older engine */ }
  }

  function abandon() {
    live = null;
    glowHide();
  }

  function onDown(ev) {
    if (live) {
      /* A second finger is not a corner swipe - a pinch, a two-hand hold. */
      if (ev.pointerId !== live.id) abandon();
      return;
    }
    if (!cfg.enabled) return;
    if (ev.isPrimary === false) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    if (sheets.length) return;
    var w = root.innerWidth || 0, h = root.innerHeight || 0;
    var corner = cornerAt(ev.clientX, ev.clientY, w, h);
    if (!corner) return;
    if ((cfg[corner] || 'off') === 'off') return;
    /* #1166: `onControl` is decided HERE, where the finger actually
     * landed, and is read only by the tap at the up - see onUp and
     * overControl. The swipe does not consult it and is unchanged. */
    live = {id: ev.pointerId, corner: corner, x: ev.clientX, y: ev.clientY,
            t: now(), onControl: overControl(ev.target)};
    glowShow(corner, 0);
  }

  function onMove(ev) {
    if (!live || ev.pointerId !== live.id) return;
    var got = judge(live.corner, ev.clientX - live.x, ev.clientY - live.y, now() - live.t);
    if (got.state === 'going') { glowShow(live.corner, got.progress); return; }
    if (got.state === 'drop') { abandon(); return; }
    /* Committed. From here the press is ours: the rest of the move, the
     * up, and the click the platform will synthesise after it. */
    var corner = live.corner;
    live = null;
    swallowId = ev.pointerId;
    swallowClickUntil = now() + 700;
    glowHide();
    eat(ev);
    act(cfg[corner]);
  }

  /* #1166: THE TAP, TAKEN HERE OR NOT AT ALL.
   *
   * "Make sure I can also activate hot corners by tapping on the corners.
   *  or clicking."
   *
   * Everything that had to be true for a swipe to be possible was already
   * checked at the down - the corners are on, this corner is not `off`, no
   * sheet is up, it was the primary pointer, the left button, and the
   * press landed inside the corner's square. If `live` is still here at
   * the up, all of that held and the only questions left are whether the
   * press stayed still, whether it was brief, and whose it was.
   *
   * The gates are re-checked rather than assumed: a sheet can have opened
   * under the finger, and the preferences drawer can have turned the
   * corner off, between the down and the up.
   *
   * ON FIRING, THE PRESS BECOMES OURS, exactly as a committed swipe does:
   * the click the platform synthesises afterwards is swallowed by
   * onClick. Without that a corner tap on the LISTEN view's backdrop
   * would also be counted by that view's own double-tap-to-full-screen,
   * and the operator would get two things for one finger. */
  function onUp(ev) {
    if (live && ev.pointerId === live.id) {
      var was = live;
      live = null;
      var dx = ev.clientX - was.x, dy = ev.clientY - was.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var ms = now() - was.t;
      var what = cfg[was.corner] || 'off';
      if (was.onControl                      /* somebody else's press */
          || dist > TAP_PX                   /* it was going somewhere */
          || ms > TAP_MS                     /* a press, not a tap */
          || sheets.length                   /* a sheet owns the screen now */
          || !cfg.enabled
          || what === 'off') {
        glowHide();
        return;
      }
      swallowClickUntil = now() + 700;
      glowPulse(was.corner);
      eat(ev);
      act(what);
      return;
    }
    if (swallowId !== null && ev.pointerId === swallowId) {
      swallowId = null;
      eat(ev);
    }
  }

  function onCancel(ev) {
    if (live && ev.pointerId === live.id) abandon();
    if (swallowId !== null && ev.pointerId === swallowId) swallowId = null;
  }

  function onClick(ev) {
    if (now() < swallowClickUntil) {
      swallowClickUntil = 0;
      eat(ev);
    }
  }

  /* While a corner drag is being judged the page must not start scrolling
   * under it - a scroll cancels the pointer and the swipe is lost. Only
   * while one is live: every other touch is left passive. */
  function onTouchMove(ev) {
    if (live || swallowId !== null) {
      try { ev.preventDefault(); } catch (e) { /* passive after all */ }
    }
  }

  var wired = false;
  function wire() {
    if (wired || !doc) return;
    wired = true;
    doc.addEventListener('pointerdown', onDown, true);
    doc.addEventListener('pointermove', onMove, true);
    doc.addEventListener('pointerup', onUp, true);
    doc.addEventListener('pointercancel', onCancel, true);
    doc.addEventListener('click', onClick, true);
    try {
      doc.addEventListener('touchmove', onTouchMove, {capture: true, passive: false});
    } catch (e) {
      doc.addEventListener('touchmove', onTouchMove, true);
    }
  }

  function unwire() {
    if (!wired || !doc) return;
    wired = false;
    doc.removeEventListener('pointerdown', onDown, true);
    doc.removeEventListener('pointermove', onMove, true);
    doc.removeEventListener('pointerup', onUp, true);
    doc.removeEventListener('pointercancel', onCancel, true);
    doc.removeEventListener('click', onClick, true);
    doc.removeEventListener('touchmove', onTouchMove, true);
  }

  /* ------------------------------------------------------------- toast */

  var toastEl = null;
  var toastGone = 0;

  function toast(text, bad) {
    if (!doc || !doc.body) return;
    if (!toastEl) {
      toastEl = make('div', 'hc-toast');
      doc.body.appendChild(toastEl);
    }
    clearTimeout(toastGone);
    /* An empty text takes the toast down at once - the work it was
     * announcing has produced its own answer on screen. */
    if (!String(text || '')) {
      toastEl.classList.remove('up');
      toastGone = setTimeout(function () {
        if (toastEl && toastEl.parentNode) toastEl.parentNode.removeChild(toastEl);
        toastEl = null;
      }, 260);
      return;
    }
    toastEl.textContent = String(text || '');
    toastEl.classList.toggle('bad', !!bad);
    toastEl.classList.add('up');
    /* Still working (ends in an ellipsis, U+2026): leave it up. A refusal
     * stays longer than a success, because a success is usually visible
     * somewhere else and a refusal is only ever here. */
    if (/\u2026$/.test(String(text || ''))) return;
    toastGone = setTimeout(function () {
      if (!toastEl) return;
      toastEl.classList.remove('up');
      setTimeout(function () {
        if (toastEl && toastEl.parentNode) toastEl.parentNode.removeChild(toastEl);
        toastEl = null;
      }, 260);
    }, bad ? 6000 : 3200);
  }

  /* --------------------------------------------------------- the sheets */

  /* Every pop-up here is the same box: a header that PineDrag moves it by
   * (data-pine-drag / data-pine-drag-handle - pine-dismiss.js's delegated
   * drag), a close glyph, and tap-away / Escape through PineDismiss.watch
   * like every other panel on the page. */
  function sheet(title, cls, opts) {
    var box = make('div', 'hc-sheet' + (cls ? ' ' + cls : ''));
    box.setAttribute('data-pine-drag', '');
    var head = make('div', 'hc-head');
    head.setAttribute('data-pine-drag-handle', '');
    head.appendChild(make('b', '', title));
    var x = make('button', 'hc-x', '×');
    x.type = 'button';
    x.setAttribute('aria-label', 'close');
    head.appendChild(x);
    box.appendChild(head);
    var body = make('div', 'hc-body');
    box.appendChild(body);
    doc.body.appendChild(box);
    /* 2026-09-14: a diagnostic sheet ducks the broadcast to 10%; the
       preferences sheet is not one. The hold follows the element. */
    if (root.PineDuck && String(cls || '').indexOf('prefs') < 0 && !(opts && opts.duck === false)) {
      root.PineDuck.hold('hc-' + (cls || 'sheet'), root.PineDuck.REPORT, box);
    }

    var unwatch = null;
    var entry = {box: box, body: body, close: null, onClose: null};
    function close() {
      var at = sheets.indexOf(entry);
      if (at >= 0) sheets.splice(at, 1);
      if (unwatch) { try { unwatch(); } catch (e) { /* gone */ } unwatch = null; }
      if (box.parentNode) box.parentNode.removeChild(box);
      if (typeof entry.onClose === 'function') { try { entry.onClose(); } catch (e) { /* fine */ } }
    }
    entry.close = close;
    x.addEventListener('click', function (e) { e.stopPropagation(); close(); });
    sheets.push(entry);
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      unwatch = root.PineDismiss.watch(box, close, []);
    }
    return entry;
  }

  function closeSheets() {
    for (var i = sheets.length - 1; i >= 0; i -= 1) {
      try { sheets[i].close(); } catch (e) { /* stuck */ }
    }
    sheets.length = 0;
  }

  /* ------------------------------------------------- "shot": draw on it */

  /* The picture. Tablet first (the kiosk's PixelCopy of the whole screen),
   * then the desk's capture of its own window, else the honest answer. */
  function shoot() {
    if (has('screenShot')) {
      return Promise.resolve(bridge().screenShot()).then(function (got) {
        if (got && got.ok && got.image) return String(got.image);
        throw new Error(String((got && got.detail) || 'the tablet gave no picture'));
      });
    }
    if (has('shotView')) {
      return Promise.resolve(bridge().shotView()).then(function (got) {
        if (got && got.ok && got.dataUrl) return String(got.dataUrl);
        throw new Error(String((got && got.why) || 'the desk gave no picture'));
      });
    }
    return Promise.reject(new Error('no screenshot road on this surface'));
  }

  /* "draw on the screen and outline things with my finger in red". The
   * picture is the canvas's background at the viewport's size; the ink is
   * kept as strokes so Undo takes one back and Clear takes them all; the
   * canvas is redrawn from the picture up on each of those. The primary
   * button composes the two into one PNG and hands it to `opts.onDone`.
   *
   * TWO ROADS SHARE IT. The corner swipe: onDone is PineReport.fromKey -
   * the same road the tablet's volume-up chord takes: the flash, the
   * report pad, the dot listening, and the existing road files it into the
   * Pine inbox with the picture. And the inbox (#1140): "When following
   * reports allow me to tap the image to full screen it and basically use
   * my finger as a cursor to draw on it in red and then go back." There
   * the buttons read Undo / Clear / Back / Keep, and Keep's onDone PUTs
   * the drawn-on copy back to the station (script-page.js inboxKeep).
   *
   * annotate(src, opts):
   *   src               a data: URL, an http(s) URL, or a station path
   *                     such as /api/pine-uploads/<name> (loaded through
   *                     the station URL rule; fetched with the station key
   *                     and drawn from a blob URL where the page is file:,
   *                     so the export is never refused for taint)
   *   opts.onDone(png, note)
   *                     the composed PNG data URL, and (#1148) the line
   *                     saying which frame it is - '' when the picture is
   *                     the live one, so a caller that does not care may
   *                     ignore the second argument entirely. May answer a
   *                     promise: the sheet stays up, its button reads
   *                     opts.busyLabel, until it settles; a rejection is
   *                     toasted and the ink is kept for another go.
   *                     Default: PineReport.
   *   opts.scrub        (#1148) offer the scrub strip under the toolbar.
   *                     Only the corner's screenshot road sets it: an
   *                     inbox picture has no last five seconds behind it.
   *   opts.onCancel()   the back button; nothing changes.
   *   opts.fileLabel    the primary button's words (default 'File the report')
   *   opts.fileIcon     its Carbon icon (default 'c:email')
   *   opts.backLabel    the cancel button's words (default 'Cancel')
   *   opts.busyLabel    the primary button's words while onDone runs
   *   opts.note         the hint in the bar
   *   opts.cancelSay    the toast on cancel (default 'nothing filed')
   * Answers {close}. */
  function annotate(src, opts) {
    opts = opts || {};
    var wrap = make('div', 'hc-ink');
    var canvas = make('canvas', 'hc-ink-canvas');
    var bar = make('div', 'hc-ink-bar');
    var note = make('span', 'hc-ink-note', String(opts.note || 'draw on the picture, then file the report'));
    var undo = button('hc-btn', 'Undo', 'c:skip--back--filled');
    var clear = button('hc-btn', 'Clear', 'c:clean');
    var cancel = button('hc-btn', String(opts.backLabel || 'Cancel'), 'c:close--filled');
    var file = button('hc-btn hc-primary', String(opts.fileLabel || 'File the report'),
      String(opts.fileIcon || 'c:email'));
    bar.appendChild(note);
    bar.appendChild(undo);
    bar.appendChild(clear);
    bar.appendChild(cancel);
    bar.appendChild(file);
    wrap.appendChild(canvas);
    wrap.appendChild(bar);
    doc.body.appendChild(wrap);
    if (root.PineDuck) root.PineDuck.hold('hc-ink', root.PineDuck.REPORT, wrap);   /* 2026-09-14 */
    /* #1154: the sheet covers the screen, so nothing under it needs to be
     * rendered while it is up. See hush() below for what this buys and
     * what it deliberately leaves alone. */
    hush();

    var ctx = canvas.getContext('2d');
    var img = new Image();
    var strokes = [];
    var stroke = null;
    var W = 0, H = 0;
    var revoke = null;
    var busy = false;
    /* #1148, the scrub strip. `liveSrc` is the picture the annotator
     * opened with - the live screenshot - which the strip calls "now";
     * `bgSrc` is whatever the canvas is painted from at this moment;
     * `scrubAt` is how many seconds before the capture that frame sits,
     * and 0 means the live one. The INK IS NEVER BAKED IN: strokes stay a
     * list and redraw() paints them over whatever background is current,
     * which is the whole reason a frame can be swapped underneath them. */
    var liveSrc = '';
    var bgSrc = '';
    var scrubAt = 0;

    /* #1154 - WHY THE INK FELT LATE, AND WHAT ACTUALLY FIXED IT.
     *
     * "This is alright. It looks like it's better, but it is a little
     *  laggy when I'm drawing the strokes."
     *
     * The stroke handler was never the cost: 0.055 ms a move. What is
     * slow is the PAGE. Traced on the tablet with the sheet already up and
     * nobody drawing, ProxyMain::BeginMainFrame took 2035 ms of 2500 ms
     * wall across 34 frames - 60 ms of style, layout and paint for every
     * frame the panel produces - and the ink can never appear sooner than
     * the frame that carries it. Measured: 3.9 fps while the sheet was up.
     *
     * AND NONE OF THAT WORK WAS VISIBLE. This sheet is fixed, inset:0 and
     * opaque; the feed, the meters, the clocks and the wallpaper under it
     * are painting into a covered screen. So while it is up they are taken
     * out of the rendering lifecycle with content-visibility:hidden - not
     * display:none, which would throw away their layout and their scroll
     * positions - and put back exactly as they were on close. Measured
     * again straight afterwards: 11 fps, median frame gap 167 ms -> 86 ms.
     *
     * 11 fps is the pacer's own floor (PINE_PACE=4 in app.py is ~67 ms a
     * group plus a vsync), so this reaches it and cannot pass it. Going
     * further means changing the pace, and app.py is not ours.
     *
     * WHAT IS DELIBERATELY LEFT ALONE: the toast, because it speaks while
     * the sheet is up; the report pad, because filing opens it; and the
     * corner sheets. They are named in the rule in hot-corners.css.
     *
     * ONE CLASS ON <html>, NOT A LIST OF ELEMENTS, AND THAT IS THE WHOLE
     * SAFETY ARGUMENT. The first cut walked document.body.children, hid
     * each one and remembered what to put back. It shipped a terminal that
     * went dark: the sheet left the DOM by a road that does not run
     * close() - measured on the tablet, 36 children still hidden with no
     * sheet up and nothing on screen - and a per-element list can only be
     * undone by the code that made it. A class cannot leak that way: one
     * removal restores everything, whatever happened in between, including
     * elements that arrived while the sheet was up. And the WATCHDOG below
     * removes it the moment there is no sheet left to justify it, so the
     * worst case is one second of a covered screen instead of a dead one.
     *
     * Rendering only: timers, audio and the broadcast are untouched. */
    var hushGuard = null;
    function hush() {
      if (!doc.documentElement || !doc.documentElement.classList) return;
      doc.documentElement.classList.add('hc-hushed');
      if (hushGuard) return;
      /* THE DEAD MAN'S HANDLE. Nothing may keep the page hidden once the
       * sheet that asked for it is gone, however it went. */
      hushGuard = setInterval(function () {
        if (!doc.querySelector('.hc-ink')) unhush();
      }, 1000);
    }
    function unhush() {
      if (hushGuard) { clearInterval(hushGuard); hushGuard = null; }
      try {
        if (doc.documentElement && doc.documentElement.classList) {
          doc.documentElement.classList.remove('hc-hushed');
        }
      } catch (e) { /* nothing left to restore */ }
    }

    var entry = {box: wrap, body: wrap, close: null};
    var unwatch = null;
    function close() {
      var at = sheets.indexOf(entry);
      if (at >= 0) sheets.splice(at, 1);
      /* FIRST, and outside everything that can throw: a sheet that went
       * away leaving the page hidden would be a black terminal. */
      unhush();
      if (unwatch) { try { unwatch(); } catch (e) { /* gone */ } unwatch = null; }
      root.removeEventListener('resize', fit);
      if (revoke) { try { revoke(); } catch (e) { /* gone */ } revoke = null; }
      if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
    }
    entry.close = close;
    sheets.push(entry);
    /* Full screen, so tap-away means nothing here; the watch is for Escape
     * and for closeAll on a view switch, the same as every other panel. */
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      unwatch = root.PineDismiss.watch(wrap, close, []);
    }

    function inkStyle() {
      ctx.strokeStyle = 'rgba(255,40,40,.95)';
      ctx.lineWidth = 6;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
    }

    function fit() {
      W = root.innerWidth || 1280;
      H = root.innerHeight || 800;
      var dpr = Math.min(2, root.devicePixelRatio || 1);
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      redraw();
    }

    function path(points) {
      if (!points.length) return;
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      if (points.length === 1) ctx.lineTo(points[0].x + 0.01, points[0].y);
      for (var i = 1; i < points.length; i += 1) ctx.lineTo(points[i].x, points[i].y);
      ctx.stroke();
    }

    function redraw() {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, W, H);
      if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, W, H);
      inkStyle();
      for (var i = 0; i < strokes.length; i += 1) path(strokes[i]);
    }

    /* #1148: THE BACKGROUND IS SWAPPABLE, AND ONLY THE BACKGROUND.
     *
     * "Whenever I access the screen capture to follow report, I also want
     *  to be able to scrub between the last five seconds of the broadcast
     *  to find the right frame."
     *
     * The new picture is decoded into a SECOND Image and only becomes the
     * background once it has loaded, so dragging the slider never flashes
     * black between frames. A pick that lands while an earlier one is
     * still decoding wins: the late arrival sees bgSrc has moved on and
     * drops itself. redraw() then repaints the ink on top, untouched. */
    function setBackground(url, live) {
      url = String(url || '');
      if (!url || url === bgSrc) return;
      bgSrc = url;
      var next = new Image();
      next.onload = function () {
        if (bgSrc !== url) return;          /* a later pick already won */
        img = next;
        redraw();
      };
      next.onerror = function () {
        if (bgSrc !== url) return;
        toast(live
          ? 'the picture could not be decoded; the ink still files'
          : 'that frame could not be decoded; the picture is unchanged', true);
      };
      next.src = url;
    }

    fit();                                  /* black until the picture lands */
    loadPicture(src).then(function (got) {
      if (!wrap.parentNode) { if (got.revoke) got.revoke(); return; }
      revoke = got.revoke;
      liveSrc = got.src;
      /* Only if the operator has not already scrubbed away from it. */
      if (!bgSrc) setBackground(got.src, true);
    }, function (err) {
      toast('the picture could not be fetched: ' + String((err && err.message) || err), true);
    });

    /* Ink. The canvas owns its pointer (touch-action:none in the sheet, so
     * the WebView never turns a stroke into a scroll). */
    var inkId = null;
    canvas.addEventListener('pointerdown', function (ev) {
      if (inkId !== null) return;
      if (ev.pointerType === 'mouse' && ev.button !== 0) return;
      inkId = ev.pointerId;
      try { canvas.setPointerCapture(ev.pointerId); } catch (e) { /* older engine */ }
      stroke = [{x: ev.clientX, y: ev.clientY}];
      /* #1154: the ink style is set ONCE per stroke, not once per move.
       * Every redraw() ends by setting it too, and changing canvas.width
       * (fit) resets the context and then redraws - so the context is
       * always carrying the ink's stroke style when a move arrives. */
      inkStyle();
      path(stroke);
      ev.preventDefault();
    }, {passive: false});

    /* #1154: "This is alright. It looks like it's better, but it is a
     *  little laggy when I'm drawing the strokes."
     *
     * MEASURED FIRST, AND THE OBVIOUS SUSPECT WAS INNOCENT. This handler
     * already drew only the NEW segment rather than repainting the world,
     * and it costs 0.055 ms a move on the tablet (240 moves, p95 0.1 ms,
     * worst 3.1 ms). The page around it is the cost - see hush() below -
     * and on top of that the panel paces requestAnimationFrame to one
     * group every ~67 ms (app.py, PINE_PACE), so pointermove arrives in
     * clumps rather than one delivery per digitiser sample.
     *
     * COALESCED EVENTS are the cure for what that clumping LOOKS like.
     * The engine keeps every sample taken between two deliveries; without
     * asking for them a fast stroke is one straight chord across the whole
     * gap, which reads as angular AND late. With them the line follows the
     * finger's real path, and the whole batch goes down as ONE path with
     * one stroke() rather than a beginPath/stroke pair per point. */
    canvas.addEventListener('pointermove', function (ev) {
      if (inkId === null || ev.pointerId !== inkId || !stroke) return;
      ev.preventDefault();
      var pts = null;
      if (typeof ev.getCoalescedEvents === 'function') {
        try { pts = ev.getCoalescedEvents(); } catch (e) { pts = null; }
      }
      if (!pts || !pts.length) pts = [ev];
      var last = stroke[stroke.length - 1];
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      for (var i = 0; i < pts.length; i += 1) {
        var p = {x: pts[i].clientX, y: pts[i].clientY};
        stroke.push(p);
        ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
    }, {passive: false});
    function inkUp(ev) {
      if (inkId === null || ev.pointerId !== inkId) return;
      try { canvas.releasePointerCapture(ev.pointerId); } catch (e) { /* not held */ }
      inkId = null;
      if (stroke && stroke.length) strokes.push(stroke);
      stroke = null;
    }
    canvas.addEventListener('pointerup', inkUp);
    canvas.addEventListener('pointercancel', inkUp);

    undo.addEventListener('click', function () { if (busy) return; strokes.pop(); redraw(); });
    clear.addEventListener('click', function () { if (busy) return; strokes.length = 0; redraw(); });
    cancel.addEventListener('click', function () {
      if (busy) return;
      close();
      if (typeof opts.onCancel === 'function') { try { opts.onCancel(); } catch (e) { /* theirs */ } }
      toast(String(opts.cancelSay || 'nothing filed'));
    });

    /* ------------------------------------------- #1148: the scrub strip */

    /* "Whenever I access the screen capture to follow report, I also want
     *  to be able to scrub between the last five seconds of the broadcast
     *  to find the right frame."
     *
     * The screenshot is of the screen AS IT IS WHEN THE SWIPE FINISHES,
     * which is always a beat after the thing the operator meant to point
     * at. The tablet has already been holding a rolling video of the
     * screen (replay/ScreenReplay.kt); replayFrames pulls the last five
     * seconds of it out as ten small JPEGs, and this is the row of them.
     *
     * WHAT IT MUST NOT DO. It must not delay the annotator: the sheet is
     * already up and drawable with the live shot before this is asked for.
     * It must not appear at all where there is no ring - the desk has no
     * replayFrames, and an empty strip or an error there would be a worse
     * annotator than the one that shipped. So: no bridge road, or ok:false,
     * or no frames, and the whole thing is taken back off the sheet. */
    /* #1155 - AND IT REACHES THE WHOLE RING.
     *
     * "Okay, that is actually much smoother. That is better. Also, I would
     *  like to go back the whole recording range."
     *
     * TWO CONTROLS, because one cannot be both. The COARSE slider carries
     * the whole of what the ring holds - twenty minutes - and says where
     * the shown window sits; the FINE slider walks the ten thumbnails
     * inside that window. On a 1154x690 glass a single slider over 1200
     * seconds gives a thumb about half a second of ring per pixel, which
     * is no way to find a frame.
     *
     * WINDOWS, NEVER THE WHOLE THING. Twenty minutes of thumbnails would
     * be 2400 pictures and tens of megabytes; the strip only ever holds
     * SCRUB_WINDOW seconds of them, and asks for another window when the
     * coarse slider settles. Asks are snapped to SCRUB_STEP so that going
     * back to somewhere already visited is answered from the cache rather
     * than by re-muxing the ring.
     *
     * THE FIRST PAINT IS STILL INSTANT. The sheet opens on the live shot,
     * the nearest window (back = 0) is asked for straight away, and
     * nothing reaches further back until the operator asks it to. */
    var strip = null;
    var stripThumbs = null;
    var stripSlider = null;
    var stripCoarse = null;
    var stripWhen = null;
    var shots = [];
    var held = 0;                /* what the ring holds, in seconds */
    var backNow = 0;             /* where the shown window ends, before now */
    var settleTimer = null;
    var inFlight = 0;            /* the ask whose answer is still wanted */

    /* The window cache. Keyed by the snapped `back`; value is the frame
     * list exactly as the bridge gave it. `cacheChars` is the measured
     * base64 it holds, and the least recently used window goes when that
     * passes SCRUB_CACHE - see the constant for why 5 MB. */
    var cache = {};
    var cacheOrder = [];
    var cacheChars = 0;

    function cacheKey(back) { return String(Math.round(back / SCRUB_STEP) * SCRUB_STEP); }

    function cacheGet(back) {
      var k = cacheKey(back);
      var hit = cache[k];
      if (!hit) return null;
      var at = cacheOrder.indexOf(k);            /* freshen it */
      if (at >= 0) { cacheOrder.splice(at, 1); cacheOrder.push(k); }
      return hit;
    }

    function cachePut(back, list) {
      var k = cacheKey(back);
      if (cache[k]) return;
      var chars = 0, i;
      for (i = 0; i < list.length; i += 1) chars += String(list[i].image || '').length;
      cache[k] = {list: list, chars: chars};
      cacheOrder.push(k);
      cacheChars += chars;
      while (cacheChars > SCRUB_CACHE && cacheOrder.length > 1) {
        var old = cacheOrder.shift();
        if (cache[old]) { cacheChars -= cache[old].chars; delete cache[old]; }
      }
    }

    function dropStrip() {
      if (settleTimer) { clearTimeout(settleTimer); settleTimer = null; }
      if (strip && strip.parentNode) strip.parentNode.removeChild(strip);
      strip = null;
      stripThumbs = null;
      stripSlider = null;
      stripCoarse = null;
      stripWhen = null;
      shots = [];
      cache = {};
      cacheOrder = [];
      cacheChars = 0;
      wrap.className = 'hc-ink';
    }

    /* '-1m 12s' for the older frames, 'now' for the live shot. */
    function stripLabel(at) {
      return at > 0 ? '-' + fmtBack(at) : 'now';
    }

    function pick(i) {
      if (busy || !shots.length) return;
      if (!(i >= 0)) i = 0;
      if (i >= shots.length) i = shots.length - 1;
      var s = shots[i];
      if (!s) return;
      scrubAt = s.at;
      setBackground(s.live ? (liveSrc || src) : s.full, !!s.live);
      if (stripSlider && String(stripSlider.value) !== String(i)) stripSlider.value = String(i);
      if (stripThumbs) {
        var kids = stripThumbs.childNodes;
        for (var k = 0; k < kids.length; k += 1) {
          if (kids[k] && kids[k].className !== undefined) {
            kids[k].className = 'hc-strip-thumb' + (k === i ? ' on' : '');
          }
        }
      }
      note.textContent = s.at > 0
        ? 'the frame from ' + fmtBack(s.at) + ' before the capture - the ink stays'
        : String(opts.note || 'draw on the picture, then file the report');
    }

    /* Paint the thumbnails for the window now in hand. `list` is the
     * bridge's frames, oldest first; `atTail` says the window reaches now,
     * in which case the newest tile is the LIVE SHOT rather than the ring's
     * last frame - the operator is already drawing on the live shot, and
     * coming back to "now" has to give back exactly the picture that was
     * there, to the pixel, or the ink would no longer line up with what is
     * under it. The ring's own last frame is still that tile's thumbnail:
     * it is the cheap small one and it looks the same. */
    function paintWindow(list, atTail) {
      var i;
      shots = [];
      for (i = 0; i < list.length; i += 1) {
        var f = list[i];
        var at = Number(f && f.at);
        if (!isFinite(at) || at < 0) at = 0;
        var pic = String((f && f.image) || '');
        if (pic) shots.push({at: at, thumb: pic, full: pic, live: false});
      }
      if (!shots.length) return false;
      if (atTail) {
        shots[shots.length - 1].at = 0;
        shots[shots.length - 1].live = true;
      }
      if (!stripThumbs) return false;
      stripThumbs.innerHTML = '';
      for (i = 0; i < shots.length; i += 1) {
        (function (idx) {
          var b = make('button', 'hc-strip-thumb');
          b.type = 'button';
          var im = doc.createElement('img');
          im.src = shots[idx].thumb;
          im.alt = '';
          b.appendChild(im);
          b.appendChild(make('span', 'hc-strip-at', stripLabel(shots[idx].at)));
          b.addEventListener('click', function (ev) { ev.stopPropagation(); pick(idx); });
          stripThumbs.appendChild(b);
        }(i));
      }
      stripSlider.max = String(shots.length - 1);
      stripSlider.value = String(shots.length - 1);
      pick(shots.length - 1);
      return true;
    }

    function sayWhen(text) { if (stripWhen) stripWhen.textContent = text; }

    /* Ask the bridge for the window ending `back` seconds before now, or
     * answer it from the cache. Only the LAST ask counts: a drag across
     * the ring can leave earlier answers in flight and they must not paint
     * over the window the operator has since moved to. */
    function loadWindow(back, onFirst) {
      var snapped = Math.round(back / SCRUB_STEP) * SCRUB_STEP;
      var hit = cacheGet(snapped);
      if (hit) {
        backNow = snapped;
        paintWindow(hit.list, snapped <= 0);
        sayWhen(snapped <= 0 ? 'the last ' + SCRUB_WINDOW + ' seconds'
          : 'the ' + SCRUB_WINDOW + ' seconds ending ' + fmtBack(snapped) + ' ago');
        return;
      }
      var mine = ++inFlight;
      sayWhen(snapped <= 0 ? 'reading the last five seconds...'
        : 'reading ' + fmtBack(snapped) + ' back...');
      var asked;
      try {
        asked = bridge().replayFrames({seconds: SCRUB_WINDOW, count: SCRUB_COUNT, back: snapped});
      } catch (err) { asked = Promise.reject(err); }
      Promise.resolve(asked).then(function (got) {
        if (!wrap.parentNode || mine !== inFlight) return;      /* stale */
        var list = (got && got.ok && got.frames && got.frames.length) ? got.frames : null;
        if (!list) {
          if (onFirst) { dropStrip(); return; }
          sayWhen('nothing readable that far back');
          return;
        }
        /* What the ring holds can only be known once it has answered; the
         * coarse slider's reach is set from it and grows as the ring does. */
        var nowHeld = Number(got.held || got.seconds || 0);
        if (isFinite(nowHeld) && nowHeld > held) {
          held = nowHeld;
          if (stripCoarse) stripCoarse.max = String(Math.max(SCRUB_STEP, Math.floor(held)));
        }
        cachePut(snapped, list);
        backNow = snapped;
        if (onFirst && !buildStrip()) { dropStrip(); return; }
        if (!paintWindow(list, snapped <= 0)) { if (onFirst) dropStrip(); return; }
        if (stripCoarse) stripCoarse.value = String(Math.round(snapped));
        /* The bridge says where the window REALLY landed. Asking further
         * back than the ring reaches is not an error - it is the oldest
         * thing there is - but the operator is told rather than shown the
         * wrong minute without a word. */
        if (got.clamped) {
          sayWhen('that is as far back as the ring goes - ' + fmtBack(Number(got.to) || 0) + ' ago');
        } else {
          sayWhen(snapped <= 0 ? 'the last ' + SCRUB_WINDOW + ' seconds'
            : 'the ' + SCRUB_WINDOW + ' seconds ending ' + fmtBack(snapped) + ' ago');
        }
      }, function () {
        if (!wrap.parentNode || mine !== inFlight) return;
        /* Silence is the contract on the first ask: the annotator is
         * exactly what it was where there is no ring to read. */
        if (onFirst) dropStrip(); else sayWhen('that window could not be read');
      });
    }

    /* The strip's furniture, built once the first window has answered. */
    function buildStrip() {
      if (!strip) return false;
      strip.className = 'hc-strip';
      strip.innerHTML = '';

      stripThumbs = make('div', 'hc-strip-thumbs');

      stripSlider = doc.createElement('input');
      stripSlider.type = 'range';
      stripSlider.className = 'hc-strip-slider';
      stripSlider.min = '0';
      stripSlider.max = String(SCRUB_COUNT - 1);
      stripSlider.step = '1';
      stripSlider.value = String(SCRUB_COUNT - 1);
      stripSlider.addEventListener('input', function () { pick(Number(stripSlider.value)); });
      stripSlider.addEventListener('change', function () { pick(Number(stripSlider.value)); });

      /* THE COARSE SLIDER runs backwards on purpose: hard right is now,
       * and dragging left walks into the past, which is the direction a
       * timeline runs everywhere else on this station. It is `direction:
       * rtl` in the stylesheet, so the VALUE is still plain seconds-back
       * and no arithmetic has to be inverted here. */
      var row = make('div', 'hc-strip-far');
      stripCoarse = doc.createElement('input');
      stripCoarse.type = 'range';
      stripCoarse.className = 'hc-strip-coarse';
      stripCoarse.min = '0';
      stripCoarse.max = String(Math.max(SCRUB_STEP, Math.floor(held || SCRUB_STEP)));
      stripCoarse.step = String(SCRUB_STEP);
      stripCoarse.value = '0';
      stripWhen = make('div', 'hc-strip-line', 'the last ' + SCRUB_WINDOW + ' seconds');

      function coarseMoved() {
        var back = Number(stripCoarse.value) || 0;
        /* The read-out follows the thumb at once; the ASK waits until the
         * thumb stops. A drag over twenty minutes crosses hundreds of
         * windows and must not mux the ring for any of them on the way. */
        sayWhen(back <= 0 ? 'the last ' + SCRUB_WINDOW + ' seconds'
          : fmtBack(back) + ' ago');
        if (settleTimer) clearTimeout(settleTimer);
        settleTimer = setTimeout(function () {
          settleTimer = null;
          loadWindow(back, false);
        }, SCRUB_SETTLE);
      }
      stripCoarse.addEventListener('input', coarseMoved);
      stripCoarse.addEventListener('change', coarseMoved);

      row.appendChild(stripCoarse);
      strip.appendChild(stripThumbs);
      strip.appendChild(stripSlider);
      strip.appendChild(row);
      strip.appendChild(stripWhen);
      wrap.className = 'hc-ink hc-scrub';
      return true;
    }

    if (opts.scrub && has('replayFrames')) {
      strip = make('div', 'hc-strip hc-strip-wait');
      strip.appendChild(make('div', 'hc-strip-line', 'reading the last five seconds...'));
      wrap.appendChild(strip);
      wrap.className = 'hc-ink hc-scrub-wait';
      /* What the ring holds, asked for beside the frames rather than
       * before them - the first window must not wait on a second call.
       * replayState is only a nicety here; replayFrames reports `held`
       * itself and that is what actually sets the slider's reach. */
      if (has('replayState')) {
        Promise.resolve(bridge().replayState()).then(function (st) {
          var s = Number(st && st.seconds);
          if (isFinite(s) && s > held) {
            held = s;
            if (stripCoarse) stripCoarse.max = String(Math.max(SCRUB_STEP, Math.floor(held)));
          }
        }, function () { /* replayFrames will say */ });
      }
      loadWindow(0, true);
    }

    /* Which frame this picture is, in the operator's words, or '' for the
     * live one. It becomes the first line of the Pine report so the inbox
     * item says what the picture alone cannot. #1155: the same minutes-and
     * -seconds wording the strip uses, through the one formatter. */
    function frameNote() {
      if (!(scrubAt > 0)) return '';
      return '(the frame from ' + fmtBack(scrubAt) + ' before the capture)';
    }

    /* The default onDone: the report road. */
    function fileReport(png) {
      if (!root.PineReport || typeof root.PineReport.fromKey !== 'function') {
        throw new Error('the report pad is not loaded on this surface');
      }
      root.PineReport.fromKey(png, frameNote());
    }

    file.addEventListener('click', function () {
      if (busy) return;
      var png = '';
      try { png = canvas.toDataURL('image/png'); } catch (e) { png = ''; }
      if (!png) {
        toast('the marked-up picture could not be composed (the picture is not ours to export)', true);
        return;
      }
      var done = typeof opts.onDone === 'function' ? opts.onDone : fileReport;
      busy = true;
      var wordsWere = file.lastChild ? file.lastChild.textContent : '';
      if (opts.busyLabel && file.lastChild) file.lastChild.textContent = String(opts.busyLabel);
      file.disabled = true;
      var out;
      try { out = done(png, frameNote()); } catch (e) { out = Promise.reject(e); }
      Promise.resolve(out).then(function () {
        busy = false;
        close();
      }, function (err) {
        busy = false;
        file.disabled = false;
        if (file.lastChild) file.lastChild.textContent = wordsWere;
        toast(String((err && err.message) || err), true);
      });
    });
    root.addEventListener('resize', fit);
    return {close: close};
  }

  function shot() {
    toast('taking the picture…');
    shoot().then(function (dataUrl) {
      toast('');
      /* #1148: the report road, as before - with the last five seconds
       * offered underneath it where the tablet can serve them. */
      annotate(dataUrl, {scrub: true});
    }, function (err) {
      toast(String((err && err.message) || err), true);
    });
  }

  /* ------------------------------------------- "export": the last N s */

  /* The step table, against what the ring holds. Pure, so it can be
   * tested: a step is `ok` when the ring holds at least that much (half
   * a second of slack, because the ring reports what it has measured). */
  function stepTable(held) {
    held = Number(held);
    var known = isFinite(held) && held > 0;
    var out = [];
    for (var i = 0; i < STEPS.length; i += 1) {
      out.push({seconds: STEPS[i], label: fmtSeconds(STEPS[i]),
        ok: known ? STEPS[i] <= held + 0.5 : true});
    }
    return out;
  }

  var videoEditor = null;
  var captureBusy = false;

  function editorPath(sourceId) {
    sourceId = String(sourceId || '');
    if (!/^[0-9a-f]{32}$/.test(sourceId)) throw new Error('invalid video source identity');
    return '/video-editor/?source=' + sourceId;
  }

  function editorMessage(event, frameWindow, origin) {
    if (!event || event.source !== frameWindow || event.origin !== origin) return '';
    var kind = event.data && event.data.type;
    return kind === 'pine-video-editor-close' || kind === 'pine-video-editor-export' ? kind : '';
  }

  /* Keep the station document and its player alive underneath the editor.
   * The source is an opaque station identity; returned URLs cannot navigate
   * the native bridge to another host. Export notifications never save files. */
  function openVideoEditor(sourceId) {
    var url = stationUrl(editorPath(sourceId));
    var origin = new root.URL(url, root.location.href).origin;
    if (videoEditor) videoEditor.close();
    var box = make('section', 'hc-video-editor');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Screen recording editor');
    var bar = make('div', 'hc-video-editor-bar');
    bar.appendChild(make('span', '', 'Screen recording'));
    var back = button('hc-btn', 'Close editor');
    bar.appendChild(back);
    var frame = make('iframe', 'hc-video-editor-frame');
    frame.title = 'Edit screen recording';
    frame.setAttribute('allow', 'autoplay; fullscreen');
    frame.src = url;
    box.appendChild(bar);
    box.appendChild(frame);
    doc.body.appendChild(box);
    /* 2026-09-15 (#1172): "Whenever I'm in the process of editing a screen
     * recording or editing a screenshot or filing a report, stop playing
     * video and audio until I close the window. Also stop playing videos
     * and spawning videos whenever I have a pop-up up dealing with
     * diagnostic screen capture or video editing."
     *
     * The report pad, the ink overlay and every corner sheet already tell
     * PineDuck they are open, and the listen and SFX roads stand their
     * clips down on that signal (#1167). This editor was the one surface
     * that did not - so a clip could play, and start the next one, behind
     * the very window he is editing a clip in. The hold is tied to the
     * element, so a road that tears the editor out without calling close()
     * still ends the quiet. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('hc-video-editor', root.PineDuck.REPORT, box);
    }
    var entry = {box: box, close: close};
    function close() {
      root.removeEventListener('message', receive);
      var at = sheets.indexOf(entry);
      if (at >= 0) sheets.splice(at, 1);
      if (box.parentNode) box.parentNode.removeChild(box);
      if (videoEditor === entry) videoEditor = null;
    }
    function receive(event) {
      var kind = editorMessage(event, frame.contentWindow, origin);
      if (kind === 'pine-video-editor-close') close();
      else if (kind === 'pine-video-editor-export') toast('Edited video is ready');
    }
    back.addEventListener('click', close);
    root.addEventListener('message', receive);
    sheets.push(entry);
    videoEditor = entry;
    return entry;
  }

  function exportSheet() {
    if (captureBusy) { toast('Preparing the captured video\u2026'); return; }
    var canEdit = has('replayEdit');
    var s = sheet(canEdit ? 'Edit the last recorded moment' : 'Save the last …', 'hc-export', {duck: false});
    var body = s.body;
    var big = make('div', 'hc-big', '');
    var range = make('input', 'hc-range');
    range.type = 'range';
    range.min = '0';
    range.max = String(STEPS.length - 1);
    range.step = '1';
    range.value = '4';                      /* a minute, to start */
    range.setAttribute('aria-label', 'how much of the screen recording to save');
    var ticks = make('div', 'hc-ticks');
    var holds = make('p', 'hc-dim', 'reading the ring…');
    var save = button('hc-btn hc-primary hc-wide', canEdit ? 'Open video editor' : 'Save to recordings', 'c:save');
    var audioNote = make('p', 'hc-dim', canEdit ? 'Reading captured audio status\u2026' : '');
    var videoOnly = make('input', '');
    videoOnly.type = 'checkbox';
    var videoOnlyRow = make('label', 'hc-row hc-master');
    videoOnlyRow.appendChild(videoOnly);
    /* 2026-09-15 (#1205b): THE LABEL NOW HAS TO MEAN WHAT IT SENDS.
     *
     * It said "Allow video without complete audio if unavailable" and it
     * sends `video_only`, which the cut reads as "do not carry the
     * broadcast at all". Before tonight a desk recording was always silent,
     * so the flag changed nothing and the wording cost nothing. Now that a
     * cut carries the broadcast, ticking this is the difference between
     * sound and none - so it says that. */
    videoOnlyRow.appendChild(make('span', '', 'Record the picture only - no broadcast audio'));
    body.appendChild(big);
    body.appendChild(range);
    body.appendChild(ticks);
    body.appendChild(holds);
    if (canEdit) {
      body.appendChild(audioNote);
      body.appendChild(videoOnlyRow);
    }
    body.appendChild(save);

    var table = stepTable(0);
    function paintTicks() {
      if (ticks.replaceChildren) ticks.replaceChildren(); else ticks.innerHTML = '';
      for (var i = 0; i < table.length; i += 1) {
        var t = make('span', table[i].ok ? '' : 'off', table[i].label);
        if (i === Number(range.value)) t.className += ' at';
        ticks.appendChild(t);
      }
      big.textContent = 'the last ' + fmtSeconds(STEPS[Number(range.value)]);
    }
    range.addEventListener('input', paintTicks);
    range.addEventListener('change', paintTicks);
    paintTicks();

    if (has('replayState')) {
      Promise.resolve(bridge().replayState()).then(function (got) {
        var audio = got && got.audio;
        if (canEdit) audioNote.textContent = audio ?
          'Audio: ' + String(audio.state || 'unknown').replace(/_/g, ' ') +
          (audio.detail ? ' - ' + audio.detail : '') : 'Captured audio status is unavailable.';
        var held = Number(got && got.seconds) || 0;
        table = stepTable(held);
        var last = -1;
        for (var i = 0; i < table.length; i += 1) if (table[i].ok) last = i;
        if (got && got.running === false) {
          holds.textContent = 'the tablet is not recording' + (got.detail ? ': ' + got.detail : '');
        } else if (held > 0) {
          holds.textContent = 'the ring holds ' + Math.round(held) + ' s'
            + (got && got.atLeast ? ' (at least ' + Math.round(Number(got.atLeast)) + ' s)' : '');
        } else {
          holds.textContent = 'the ring holds nothing yet' + (got && got.detail ? ': ' + got.detail : '');
        }
        if (held > 0 && last >= 0) {
          range.max = String(last);
          if (Number(range.value) > last) range.value = String(last);
        }
        paintTicks();
      }, function (err) {
        holds.textContent = 'the ring could not be read: ' + String((err && err.message) || err);
        if (canEdit) audioNote.textContent = 'Captured audio status is unavailable.';
      });
    } else {
      holds.textContent = 'the ring cannot be read on this surface (no replayState)';
    }

    save.addEventListener('click', function () {
      var seconds = STEPS[Number(range.value)] || STEPS[0];
      if (!canEdit && !has('replayExport')) {
        toast('no screen recording road on this surface', true);
        return;
      }
      save.disabled = true;
      if (canEdit) {
        captureBusy = true;
        range.disabled = true;
        videoOnly.disabled = true;
        toast('Preparing the last ' + fmtSeconds(seconds) + ' for editing\u2026');
        Promise.resolve(bridge().replayEdit({seconds: seconds, video_only: videoOnly.checked})).then(function (got) {
          captureBusy = false;
          save.disabled = range.disabled = videoOnly.disabled = false;
          if (!got || !got.ok) {
            var detail = String((got && got.detail) || 'The captured video could not be opened');
            if (got && got.original_saved) detail += ' - original saved to ' + String(got.where || 'recordings');
            audioNote.textContent = detail;
            toast(detail, true);
            return;
          }
          try {
            openVideoEditor(got.source_id || got.id);
            s.close();
            toast('');
          } catch (err) {
            toast(String((err && err.message) || err), true);
          }
        }, function (err) {
          captureBusy = false;
          save.disabled = range.disabled = videoOnly.disabled = false;
          audioNote.textContent = String((err && err.message) || err);
          toast(audioNote.textContent, true);
        });
        return;
      }
      toast('saving the last ' + fmtSeconds(seconds) + '…');
      Promise.resolve(bridge().replayExport({seconds: seconds, upload: true})).then(function (got) {
        save.disabled = false;
        if (!got || !got.ok) {
          toast(String((got && got.detail) || 'it could not be saved'), true);
          return;
        }
        var said = 'saved ' + fmtSeconds(Number(got.seconds) || seconds) + ' to ' + String(got.where || 'the tablet');
        var up = got.uploaded;
        if (up && up.ok) said += ' · carried to ' + String(up.dest || 'the recordings folder');
        else if (up && up.detail) said += ' · not carried: ' + String(up.detail);
        else said += ' · not carried';
        toast(said);
        s.close();
      }, function (err) {
        save.disabled = false;
        toast(String((err && err.message) || err), true);
      });
    });
  }

  /* --------------------------------------- "inspect": the line inspector */

  /* The line being said, else the last one heard. Rows are /api/dj chat
   * rows. Pure, so it can be tested; `nowSec` is the station's clock. */
  function heardRow(chat, nowSec) {
    var rows = [];
    var i;
    for (i = 0; i < (chat || []).length; i += 1) {
      var r = chat[i];
      if (!r || !r.id) continue;
      if (HEARD.indexOf(String(r.aired || '')) < 0) continue;
      if (NOT_DIALOGUE.indexOf(String(r.kind || '')) >= 0) continue;
      if (!String(r.text || '').trim()) continue;
      rows.push(r);
    }
    if (!rows.length) return null;
    var when = function (r) { return Number(r.air_at) || Number(r.ts) || 0; };
    var best = null;
    /* Sounding now: it started, and its seconds have not run out. */
    for (i = 0; i < rows.length; i += 1) {
      var at = Number(rows[i].air_at) || 0;
      var len = Number(rows[i].seconds) || 0;
      if (at > 0 && at <= nowSec + 0.5 && at + len >= nowSec && (!best || at >= when(best))) best = rows[i];
    }
    if (best) return best;
    /* Else the newest that has already been heard. */
    for (i = 0; i < rows.length; i += 1) {
      if (when(rows[i]) > nowSec + 0.5) continue;
      if (!best || when(rows[i]) >= when(best)) best = rows[i];
    }
    if (best) return best;
    for (i = 0; i < rows.length; i += 1) {
      if (!best || when(rows[i]) >= when(best)) best = rows[i];
    }
    return best;
  }

  function inspect() {
    if (!root.PineLineDeep || typeof root.PineLineDeep.open !== 'function') {
      toast('the line inspector is not loaded on this surface', true);
      return;
    }
    toast('finding the line being said…');
    station().then(function (got) {
      var nowSec = (Number(got && got.server_ms) || now()) / 1000;
      var row = heardRow((got && got.chat) || [], nowSec);
      if (!row) { toast('nothing has been heard yet', true); return; }
      /* The shape line-actions.js builds when a line is held: id, said,
       * node - plus the row itself, which line-deep's stepper reads. */
      var line = {
        id: String(row.id),
        said: String(row.text || '').trim(),
        node: null,
        row: row
      };
      toast('');
      root.PineLineDeep.open(line);
    }, function (err) {
      toast(String((err && err.message) || err), true);
    });
  }

  /* ------------------------------------------ "sfx": the last clip again */

  /* The newest SFX row that has something to play. The desk's own cues
   * (a hang-up, a ring) carry sfx:'' and no url - they are the station's
   * bookkeeping, not a clip. */
  function lastSfx(chat) {
    for (var i = (chat || []).length - 1; i >= 0; i -= 1) {
      var r = chat[i];
      if (!r || String(r.kind || '') !== 'sfx') continue;
      if (r.url || r.sfx || r.sfx_sample_id) return r;
    }
    return null;
  }

  var playing = null;

  function stopAudio() {
    if (!playing) return;
    try { playing.pause(); } catch (e) { /* already gone */ }
    playing = null;
    if (root.PineAir && typeof root.PineAir.release === 'function') root.PineAir.release('audition');
  }

  /* The audio-only road, copied from line-actions.js playIt: the element
   * is marked as the sampler's own so the air tap does not record it
   * back into its ring, the broadcast is ducked while it plays, and every
   * road out releases the duck. */
  function playAudio(src, name) {
    stopAudio();
    var audio = new Audio(src);
    if (root.PineAir && typeof root.PineAir.mine === 'function') root.PineAir.mine(audio);
    ['ended', 'pause', 'emptied'].forEach(function (when) {
      audio.addEventListener(when, function () {
        if (playing !== audio) return;
        stopAudio();
      });
    });
    audio.addEventListener('error', function () {
      stopAudio();
      toast('the station would not hand over ' + name, true);
    });
    audio.addEventListener('loadedmetadata', function () {
      if (playing === audio && root.PineAir && typeof root.PineAir.duck === 'function') {
        root.PineAir.duck('audition', audio.duration);
      }
    });
    if (root.PineAir && typeof root.PineAir.duck === 'function') root.PineAir.duck('audition');
    playing = audio;
    var p = null;
    try { p = audio.play(); } catch (e) { p = Promise.reject(e); }
    Promise.resolve(p).then(function () {
      toast('replaying ' + name);
    }, function (err) {
      stopAudio();
      toast('could not replay ' + name + ': ' + String((err && err.message) || err), true);
    });
  }

  function replaySfx() {
    toast('finding the last clip…');
    station().then(function (got) {
      var row = lastSfx((got && got.chat) || []);
      if (!row) { toast('no SFX clip has played yet', true); return; }
      var key = String(row.sfx || row.sfx_sample_id || '');
      /* The station prefixes a cadence sample's text with the speaker
       * glyph (U+1F50A, written as its surrogate pair here); the name is
       * what follows it. */
      var name = String(row.text || key || 'the clip').replace(/^\uD83D\uDD0A\s*/, '');
      var url = String(row.url || ('/sfx/' + encodeURIComponent(key)));
      /* A clip with a picture goes back on the SFX set, through the same
       * cut() the sampler's pads use - on THIS glass only (no ring), which
       * is what a replay is. cut() answers false where no set is mounted
       * and the audio road below takes over. */
      if (row.video && root.PineSfxTv && typeof root.PineSfxTv.cut === 'function') {
        var shown = false;
        try {
          shown = !!root.PineSfxTv.cut({id: key, url: url, sting: name,
            seconds: Number(row.seconds) || 0, video: true, ts: row.ts}, {ring: false});
        } catch (e) { shown = false; }
        if (shown) { toast('replaying ' + name + ' on the set'); return; }
      }
      playAudio(stationUrl(url), name);
    }, function (err) {
      toast(String((err && err.message) || err), true);
    });
  }

  /* ----------------------------------------------------------- "report" */

  function report() {
    if (!root.PineReport || typeof root.PineReport.open !== 'function') {
      toast('the report pad is not loaded on this surface', true);
      return;
    }
    try { root.PineReport.open(''); }
    catch (e) { toast('the report pad refused: ' + ((e && e.message) || e), true); }
  }

  /* -------------------------------------------------------------- act */

  function act(name) {
    name = String(name || 'off');
    if (name === 'shot') return shot();
    if (name === 'export') return exportSheet();
    if (name === 'inspect') return inspect();
    if (name === 'sfx') return replaySfx();
    if (name === 'report') return report();
    return undefined;
  }

  /* -------------------------------------------------------- preferences */

  /* "I also want preferences ... for each of the hot corners ... change
   * these and set these and disable these." A master switch and one
   * select per corner. On the tablet a change goes to the native side
   * (hotCornersSet), which persists it and pushes configure() back; on
   * the desk configure() is the store. */
  var prefsEntry = null;
  var prefsControls = null;

  function paintPrefs() {
    if (!prefsControls) return;
    try {
      prefsControls.master.checked = !!cfg.enabled;
      for (var i = 0; i < CORNERS.length; i += 1) {
        prefsControls[CORNERS[i]].value = cfg[CORNERS[i]] || 'off';
        prefsControls[CORNERS[i]].disabled = !cfg.enabled;
      }
    } catch (e) { /* the sheet is going */ }
  }

  function set(patch) {
    if (has('hotCornersSet')) {
      Promise.resolve(bridge().hotCornersSet(patch)).then(function (got) {
        configure(got && typeof got === 'object' ? got : patch);
      }, function () {
        configure(patch);
      });
    } else {
      configure(patch);
    }
  }

  function prefs() {
    if (prefsEntry) { prefsEntry.close(); return; }
    var s = sheet('Hot corners', 'hc-prefs');
    prefsEntry = s;
    var body = s.body;
    body.appendChild(make('p', 'hc-dim',
      'Swipe in from a corner toward the centre of the screen.'));

    var masterRow = make('label', 'hc-row hc-master');
    var master = make('input', '');
    master.type = 'checkbox';
    masterRow.appendChild(master);
    masterRow.appendChild(make('span', '', 'Corner swipes on'));
    body.appendChild(masterRow);
    master.addEventListener('change', function () { set({enabled: master.checked}); });

    prefsControls = {master: master};
    for (var i = 0; i < CORNERS.length; i += 1) {
      (function (corner) {
        var row = make('label', 'hc-row');
        row.appendChild(make('span', 'hc-corner', CORNER_WORDS[corner]));
        var pick = make('select', 'hc-pick');
        pick.setAttribute('aria-label', CORNER_WORDS[corner] + ' corner');
        for (var k = 0; k < ACTIONS.length; k += 1) {
          var opt = make('option', '', ACTION_WORDS[ACTIONS[k]]);
          opt.value = ACTIONS[k];
          pick.appendChild(opt);
        }
        pick.addEventListener('change', function () {
          var patch = {};
          patch[corner] = pick.value;
          set(patch);
        });
        row.appendChild(pick);
        body.appendChild(row);
        prefsControls[corner] = pick;
      })(CORNERS[i]);
    }
    /* Read the native side's truth once, where there is one. */
    if (has('hotCorners')) {
      Promise.resolve(bridge().hotCorners()).then(function (got) {
        if (got && typeof got === 'object') configure(got);
      }, function () { /* the store stands */ });
    }
    paintPrefs();
    s.onClose = function () { prefsEntry = null; prefsControls = null; };
  }

  /* The rail's handle for the sheet. rail.js calls this when it builds
   * the rail and finds this global; if this file is evaluated AFTER the
   * rail (the kiosk's injection order is its own), it adds itself. Both
   * check the id, so there is never a second one. */
  function railTab() {
    if (!doc) return;
    var rail = doc.getElementById('pineViewRail');
    if (!rail || doc.getElementById('pineViewTab-corners')) return;
    var tab = make('button', 'pine-view-tab');
    tab.id = 'pineViewTab-corners';
    tab.textContent = 'CORNERS';
    tab.title = 'Hot corners: what a swipe in from each corner does';
    tab.addEventListener('click', function () { try { prefs(); } catch (e) { /* not fatal */ } });
    rail.appendChild(tab);
  }

  /* ------------------------------------------------------------ dispose */

  function dispose() {
    unwire();
    closeSheets();
    stopAudio();
    abandon();
    if (glow && glow.parentNode) glow.parentNode.removeChild(glow);
    glow = null;
    if (toastEl && toastEl.parentNode) toastEl.parentNode.removeChild(toastEl);
    toastEl = null;
  }

  /* --------------------------------------------------------------- go */

  if (doc) {
    wire();
    try { railTab(); } catch (e) { /* the rail may not be up yet */ }
  }

  var api = {
    configure: configure,
    config: config,
    act: act,
    dispose: dispose,
    prefs: prefs,
    railTab: railTab,
    /* #1140: the red-ink annotator, for any picture - see annotate(). */
    annotate: annotate,
    /* #1181: the rail keeps clear of the corner squares, and it can only
     * do that if it knows how big they are. One number, one owner. */
    CORNER_PX: CORNER_PX,
    ACTIONS: ACTIONS.slice(),
    ACTION_WORDS: merge({}, ACTION_WORDS),
    STEPS: STEPS.slice(),
    /* The pure parts, for a harness. */
    _cornerAt: cornerAt,
    _judge: judge,
    /* #1166: whose press is this? Exported so the rail exemption can be
     * checked against the real page rather than argued about. */
    _overControl: overControl,
    _stepTable: stepTable,
    _heardRow: heardRow,
    _lastSfx: lastSfx,
    _stationUrl: stationUrl,
    _editorPath: editorPath,
    _editorMessage: editorMessage
  };
  root.PineHotCorners = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
