/* [va-strips] The voice actor panel's profile strips.
 *
 * "In the voice actors page, use the random SFX clips thumbs and comfy UI
 *  images to represent the last eight profiles ... tap ... assign ... tap and
 *  hold ... play a sample ... pop up with an audio meter" (2026-09-29).
 *
 * Under the Host, Co-host, third-chair and Scheduled-caller rows of the cast
 * card: the LAST EIGHT voice profiles (GET /api/voices, newest `created`
 * first), each wearing the face the station keeps for it - a random SFX video
 * clip's poster or a ComfyUI render (GET /api/voice-actor/faces, drawn once,
 * then the same on every screen).
 *
 *   TAP   assigns the profile to that seat through the panel's own roads:
 *         POST /api/voice-actor/seat (host / cohost / third - #820's cut) or,
 *         for the caller seat, PUT /api/dj/callers/{id} on the armed caller.
 *   HOLD  auditions a short sample (POST /api/voice-actor/sample) in a sheet
 *         with a radial peak-hold level meter. NOTHING IS AIRED. The station
 *         renders it on its ONE running engine with the profile's signature
 *         for that engine (#1476) and answers 409 rather than wake another.
 *         The meter plays the take's measured levels (peak + RMS every 20 ms,
 *         read from the file by the station) in step with the audio, so it
 *         reads the same on the desk's file: page and in the kiosk.
 *
 * Registers with the shell: PineVoiceActor.registerStrips({seat(el,row,ctx)})
 * (tools/edit_voice_actor_strips_shell.py). Carbon icons only, via ctx.icon.
 */
(function (root) {
  'use strict';

  var LAST_N = 8;
  var HOLD_MS = 450;
  var MOVE_PX = 10;
  var SAMPLE_MS = 90000;           /* a real render on the one engine */
  var PEAK_HOLD_MS = 1200;
  var PEAK_FALL_DB_S = 20;
  var FLOOR_DB = -60;
  var SEATS = {
    host: {kind: 'seat', seat: 'host', word: 'Host'},
    cohost: {kind: 'seat', seat: 'cohost', word: 'Co-host'},
    guest: {kind: 'seat', seat: 'third', word: 'Third chair'},
    scheduled: {kind: 'caller', word: 'Scheduled caller'}
  };

  /* ================================================== pure (and tested) */

  /** The last `n` profiles, newest `created` first (the list's own order breaks ties). */
  function lastProfiles(voices, n) {
    var rows = (voices || []).map(function (v, i) { return {v: v, i: i}; })
      .filter(function (r) { return r.v && r.v.id; });
    rows.sort(function (a, b) {
      var d = (Number(b.v.created) || 0) - (Number(a.v.created) || 0);
      return d || a.i - b.i;
    });
    return rows.slice(0, n || LAST_N).map(function (r) { return r.v; });
  }

  /** What a tap on this seat's strip changes, from the cast row model. */
  function seatTarget(row, callers) {
    var def = row && SEATS[row.seat];
    if (!def) return null;
    if (def.kind === 'seat') {
      return {kind: 'seat', seat: def.seat, word: def.word, current: String(row.voiceId || '')};
    }
    var cid = String(row.callerId || '');
    if (!cid) {
      return {kind: 'none', word: def.word, current: '',
        why: 'Arm a scheduled caller first - a caller\'s voice is pinned on that caller.'};
    }
    var c = null;
    (callers || []).forEach(function (x) { if (x && x.id === cid) c = x; });
    return {kind: 'caller', word: def.word, callerId: cid,
      callerName: String((c && c.name) || row.callerName || cid),
      current: String((c && c.voice_id) || '')};
  }

  function monogram(name) {
    var words = String(name || '?').replace(/[^A-Za-z0-9 ]+/g, ' ').trim().split(/\s+/);
    var m = words.length > 1 ? words[0].charAt(0) + words[1].charAt(0) : String(words[0] || '?').slice(0, 2);
    return (m || '?').toUpperCase();
  }

  function toDb(x) { return x > 0 ? 20 * Math.log10(x) : -Infinity; }

  /** 0..1 along the dial for a dBFS value (FLOOR_DB .. 0). */
  function dialFrac(db) {
    if (!(db > FLOOR_DB)) return 0;
    return Math.max(0, Math.min(1, (db - FLOOR_DB) / -FLOOR_DB));
  }

  /** The take's level at t seconds: {peak, rms} (0..1), or null with no reading. */
  function levelAt(env, t) {
    if (!env || !env.peak || !env.peak.length || !(env.step_s > 0)) return null;
    var i = Math.floor(Math.max(0, t) / env.step_s);
    if (i >= env.peak.length) return {peak: 0, rms: 0};
    return {peak: Number(env.peak[i]) || 0, rms: Number((env.rms || [])[i]) || 0};
  }

  /** Peak-hold: a new high is held PEAK_HOLD_MS, then falls PEAK_FALL_DB_S. */
  function holdStep(st, peakDb, nowMs) {
    st = st || {db: -Infinity, at: 0, t: nowMs};
    var dt = Math.max(0, nowMs - (st.t || nowMs)) / 1000;
    var db = st.db;
    if (peakDb >= db) return {db: peakDb, at: nowMs, t: nowMs};
    if (nowMs - st.at > PEAK_HOLD_MS) db = Math.max(peakDb, db - PEAK_FALL_DB_S * dt);
    return {db: db, at: st.at, t: nowMs};
  }

  function engineWord(e) {
    e = String(e || '').toLowerCase();
    return e === 'xtts' ? 'XTTS' : e === 'f5' ? 'F5' : e ? e.toUpperCase() : '';
  }

  /* ================================================== state */

  var st = {
    ctx: null,
    strips: {},                    /* seat key -> {node, sig, tiles:{vid: tile}} */
    faces: {},                     /* vid -> {kind, url, label} | null */
    facesAsked: {},
    facesAbsent: false,
    audio: null,
    unlocked: false,
    sheet: null,
    token: 0
  };

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function iconSpan(name, label) {
    var s = make('span', 'vas-ico');
    var markup = st.ctx && st.ctx.icon ? st.ctx.icon(name, label || '') : '';
    if (markup) s.innerHTML = markup;
    return s;
  }

  function say(text, kind) { try { if (st.ctx) st.ctx.say(text, kind || ''); } catch (err) { /* no line */ } }

  /* ------------------------------------------------------------- faces */

  function askFaces(ids) {
    if (st.facesAbsent || !st.ctx) return;
    var want = ids.filter(function (id) { return !st.facesAsked[id]; });
    if (!want.length) return;
    want.forEach(function (id) { st.facesAsked[id] = true; });
    st.ctx.request('GET', '/api/voice-actor/faces?ids=' + encodeURIComponent(want.join(','))).then(function (ans) {
      var got = (ans && ans.faces) || {};
      Object.keys(got).forEach(function (id) { st.faces[id] = got[id] || null; paintFace(id); });
    }, function (err) {
      if (err && err.status === 404) { st.facesAbsent = true; return; }
      want.forEach(function (id) { delete st.facesAsked[id]; });   /* a later paint asks again */
    });
  }

  function faceInto(box, vid, name) {
    box.replaceChildren();
    var face = st.faces[vid];
    if (face && face.url && !face.broken) {
      var img = make('img', 'vas-img');
      img.alt = '';
      img.decoding = 'async';
      img.loading = 'lazy';
      img.draggable = false;
      img.addEventListener('error', function () {
        face.broken = true;
        faceInto(box, vid, name);
      });
      img.src = st.ctx.stationUrl(face.url);
      box.appendChild(img);
      box.setAttribute('data-face', face.kind || '');
      box.title = (face.kind === 'sfx' ? 'SFX clip: ' : 'ComfyUI render: ') + (face.label || '');
    } else {
      box.appendChild(make('span', 'vas-mono', monogram(name)));
      box.setAttribute('data-face', 'none');
    }
  }

  function paintFace(vid) {
    Object.keys(st.strips).forEach(function (k) {
      var t = st.strips[k].tiles[vid];
      if (t) faceInto(t.face, vid, t.name);
    });
  }

  /* ------------------------------------------------------------- the strip */

  function buildStrip(key, target, profiles, active) {
    var strip = make('div', 'vas-strip');
    strip.setAttribute('data-vas-seat', key);
    var tiles = {};
    var head = make('div', 'vas-strip-head');
    head.appendChild(make('b', '', 'Last ' + profiles.length + ' profiles'));
    head.appendChild(make('small', '', target.kind === 'caller'
      ? 'tap to pin on ' + target.callerName + ' - hold to hear'
      : target.kind === 'none' ? target.why : 'tap to seat - hold to hear'));
    strip.appendChild(head);
    var rail = make('div', 'vas-rail');
    rail.setAttribute('role', 'list');
    profiles.forEach(function (v) {
      var name = String(v.name || v.id);
      var tile = make('div', 'vas-tile');
      tile.setAttribute('role', 'listitem');
      tile.tabIndex = 0;
      tile.setAttribute('data-vid', v.id);
      if (v.id === target.current) tile.classList.add('vas-current');
      if (target.kind === 'none') tile.classList.add('vas-off');
      tile.setAttribute('aria-label', name + (v.id === target.current ? ' (in this seat)' : '')
        + ' - tap to assign, hold to hear a sample');
      var face = make('div', 'vas-face');
      faceInto(face, v.id, name);
      tile.appendChild(face);
      var eng = engineWord(v.engine);
      if (eng) {
        var tag = make('span', 'vas-eng' + (active && String(v.engine).toLowerCase() !== active ? ' vas-eng-other' : ''), eng);
        tag.title = 'Reference cut for ' + eng + (active ? '; the station speaks on ' + engineWord(active) : '');
        tile.appendChild(tag);
      }
      if (v.id === target.current) tile.appendChild(iconSpan('c:checkmark--filled', 'in this seat'));
      tile.appendChild(make('span', 'vas-name', name));
      wireTile(tile, v, key);
      tiles[v.id] = {node: tile, face: face, name: name};
      rail.appendChild(tile);
    });
    if (!profiles.length) rail.appendChild(make('span', 'vas-none', 'No voice profiles in the library yet.'));
    strip.appendChild(rail);
    return {node: strip, tiles: tiles};
  }

  function wireTile(tile, v, key) {
    var press = null;
    var cancel = function () {
      if (press && press.timer) root.clearTimeout(press.timer);
      press = null;
      tile.classList.remove('vas-pressing');
      if (st.endPress === endMine) st.endPress = null;
      if (st.pressing) { st.pressing = false; flushPending(); }
    };
    /* the release that never reached the tile (its capture was lost to a
     * repaint that re-parented it) still ends the press - see start() */
    var endMine = function () {
      var held = press && press.held;
      cancel();
      if (held) swallowClicks();
    };
    tile.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button > 0) return;
      e.stopPropagation();
      unlockAudio();
      cancel();
      /* captured, so the release comes back here even once the sheet has
       * opened under the finger */
      try { tile.setPointerCapture(e.pointerId); } catch (err) { /* old engine */ }
      press = {x: e.clientX, y: e.clientY, held: false, t0: Date.now()};
      st.pressing = true;
      st.endPress = endMine;
      tile.classList.add('vas-pressing');
      press.timer = root.setTimeout(function () {
        if (!press) return;
        press.held = true;
        tile.classList.remove('vas-pressing');
        audition(v, key);
      }, HOLD_MS);
    });
    tile.addEventListener('pointermove', function (e) {
      if (press && !press.held && (Math.abs(e.clientX - press.x) > MOVE_PX || Math.abs(e.clientY - press.y) > MOVE_PX)) cancel();
    });
    tile.addEventListener('pointerup', function (e) {
      e.stopPropagation();
      if (!press) return;
      /* judged by the clock at release, not only by the timer: a busy page
       * can run the timer late, and a long press must never become an
       * assignment that changes who is on the air */
      var held = press.held;
      var long = held || Date.now() - press.t0 >= HOLD_MS;
      cancel();
      if (!long) { assign(v, key); return; }
      if (!held) audition(v, key);
      swallowClicks();
    });
    tile.addEventListener('pointercancel', cancel);
    tile.addEventListener('pointerleave', function () { if (press && !press.held) cancel(); });
    tile.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    tile.addEventListener('click', function (e) { e.stopPropagation(); });
    tile.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); assign(v, key); }
      else if (e.key === ' ') { e.preventDefault(); unlockAudio(); audition(v, key); }
    });
  }

  /* A finger lifted after a hold still sends the compatibility mouse events
   * and a click - onto the sheet that opened under it, whose backdrop would
   * close it (measured in the tablet drive). They are swallowed for a moment. */
  function swallowClicks() {
    st.swallowUntil = Date.now() + 700;
    if (st.swallowing) return;
    st.swallowing = true;
    ['mousedown', 'mouseup', 'click'].forEach(function (n) {
      document.addEventListener(n, function (e) {
        if (Date.now() > (st.swallowUntil || 0)) return;
        e.stopPropagation();
        e.preventDefault();
        if (n === 'click') st.swallowUntil = 0;
      }, true);
    });
  }

  /** The shell's hook: called for every cast row it paints. */
  function seatHook(el, row, ctx) {
    st.ctx = ctx;
    var key = row && row.seat;
    if (!SEATS[key]) return;
    var target = seatTarget(row, ctx.callers());
    var profiles = lastProfiles(ctx.actors(), LAST_N);
    var engines = ctx.engines();
    var active = String((engines && engines.engine) || '').toLowerCase();
    var sig = JSON.stringify([target, active, profiles.map(function (v) { return [v.id, v.name, v.engine]; })]);
    var have = st.strips[key];
    if (have && have.sig !== sig && st.pressing) {
      /* never rebuild the tiles under a finger: a poll that moves this strip
       * mid-press is kept and applied the moment the press ends */
      have.pending = {el: el, key: key, target: target, profiles: profiles, active: active, sig: sig};
    } else if (!have || have.sig !== sig) {
      var built = buildStrip(key, target, profiles, active);
      have = st.strips[key] = {node: built.node, tiles: built.tiles, sig: sig, target: target};
    }
    have.target = target;
    el.classList.add('vas-has-strip');
    el.appendChild(have.node);
    askFaces(profiles.map(function (v) { return v.id; }));
  }

  function flushPending() {
    Object.keys(st.strips).forEach(function (k) {
      var have = st.strips[k];
      var p = have.pending;
      if (!p) return;
      have.pending = null;
      var built = buildStrip(p.key, p.target, p.profiles, p.active);
      if (have.node.parentNode === p.el) p.el.replaceChild(built.node, have.node);
      st.strips[k] = {node: built.node, tiles: built.tiles, sig: p.sig, target: p.target};
    });
  }

  /* ------------------------------------------------------------- tap: assign */

  function assign(v, key) {
    var ctx = st.ctx;
    var have = st.strips[key];
    var target = have && have.target;
    if (!ctx || !target) return Promise.resolve(null);
    var name = String(v.name || v.id);
    if (target.kind === 'none') { say(target.why, 'bad'); return Promise.resolve(null); }
    if (v.id === target.current) {
      say(name + ' is already ' + (target.kind === 'caller' ? target.callerName + '\'s voice.' : 'in the ' + target.word + ' seat.'), '');
      return Promise.resolve(null);
    }
    var tile = have.tiles[v.id] && have.tiles[v.id].node;
    if (tile) tile.classList.add('vas-busy');
    var road = target.kind === 'caller'
      ? ctx.setCallerVoice(target.callerId, v.id).then(function () {
        say('Pinned ' + name + ' on ' + target.callerName + ' (the scheduled caller).', '');
      })
      : ctx.setSeat(target.seat, v.id);
    return Promise.resolve(road).then(function (ans) {
      if (tile) tile.classList.remove('vas-busy');
      return ans;
    }, function (err) {
      if (tile) tile.classList.remove('vas-busy');
      say('The station refused that: ' + String((err && err.message) || err), 'bad');
    });
  }

  /* ------------------------------------------------------------- hold: audition */

  /* One element for every sample. The first touch of any tile plays a silent
   * blip on it inside the gesture, so the WebView lets the same element play
   * the sample once the render lands (setMediaPlaybackRequiresUserGesture). */
  function silence() {                /* 50 ms of 8 kHz 16-bit silence */
    var le = function (v, n) { var s = ''; for (var i = 0; i < n; i += 1) { s += String.fromCharCode(v & 255); v >>>= 8; } return s; };
    var n = 800;
    var b = 'RIFF' + le(36 + n, 4) + 'WAVEfmt ' + le(16, 4) + le(1, 2) + le(1, 2) + le(8000, 4) + le(16000, 4)
      + le(2, 2) + le(16, 2) + 'data' + le(n, 4) + new Array(n + 1).join('\u0000');
    return 'data:audio/wav;base64,' + root.btoa(b);
  }

  function player() {
    if (!st.audio) {
      st.audio = new root.Audio();
      st.audio.preload = 'auto';
    }
    return st.audio;
  }

  function unlockAudio() {
    if (st.unlocked) return;
    try {
      var a = player();
      a.muted = true;
      a.src = silence();
      a.removeAttribute('data-src');
      var p = a.play();
      st.unlocked = true;
      if (p && p.then) p.then(function () { a.pause(); a.muted = false; }, function () { a.muted = false; st.unlocked = false; });
      else a.muted = false;
    } catch (err) { st.unlocked = false; }
  }

  function stopAudio() {
    if (!st.audio) return;
    try { st.audio.pause(); } catch (err) { /* stopped */ }
  }

  function buildSheet() {
    var sh = {};
    var node = make('div', 'vas-sheet');
    /* role=group, never dialog, no z-index (SHELL_CONTRACT section 3) */
    node.setAttribute('role', 'group');
    node.setAttribute('aria-label', 'Sample of a voice profile - never aired');
    node.hidden = true;
    var card = make('div', 'vas-card');
    var head = make('div', 'vas-card-head');
    sh.face = make('div', 'vas-face vas-face-lg');
    head.appendChild(sh.face);
    var words = make('div', 'vas-card-words');
    sh.name = make('b', '', '');
    words.appendChild(sh.name);
    sh.sub = make('small', '', '');
    words.appendChild(sh.sub);
    head.appendChild(words);
    var close = make('button', 'vas-x');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close the sample');
    close.appendChild(iconSpan('c:close--filled'));
    close.addEventListener('click', function (e) { e.stopPropagation(); closeSheet(); });
    head.appendChild(close);
    card.appendChild(head);

    var dial = make('div', 'vas-dial');
    sh.canvas = make('canvas', 'vas-meter');
    sh.canvas.width = 220;
    sh.canvas.height = 220;
    sh.canvas.setAttribute('role', 'img');
    sh.canvas.setAttribute('aria-label', 'Level meter');
    dial.appendChild(sh.canvas);
    sh.read = make('div', 'vas-read', '');
    dial.appendChild(sh.read);
    card.appendChild(dial);

    sh.status = make('div', 'vas-status', '');
    sh.status.setAttribute('role', 'status');
    card.appendChild(sh.status);

    var row = make('div', 'vas-actions');
    sh.replay = make('button', 'va-mini vas-btn');
    sh.replay.type = 'button';
    sh.replay.appendChild(iconSpan('c:volume--up--filled'));
    sh.replay.appendChild(make('span', '', 'Play again'));
    sh.replay.addEventListener('click', function (e) { e.stopPropagation(); playSample(true); });
    row.appendChild(sh.replay);
    sh.assign = make('button', 'va-mini vas-btn vas-btn-go');
    sh.assign.type = 'button';
    sh.assign.appendChild(iconSpan('c:checkmark'));
    sh.assignWords = make('span', '', 'Assign');
    sh.assign.appendChild(sh.assignWords);
    sh.assign.addEventListener('click', function (e) {
      e.stopPropagation();
      if (sh.voice) assign(sh.voice, sh.key).then(function () { closeSheet(); });
    });
    row.appendChild(sh.assign);
    card.appendChild(row);
    node.appendChild(card);
    node.addEventListener('click', function (e) { e.stopPropagation(); if (e.target === node) closeSheet(); });
    node.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
    sh.node = node;
    return sh;
  }

  function sheetStatus(text, kind) {
    var sh = st.sheet;
    if (!sh) return;
    sh.status.textContent = text;
    sh.status.className = 'vas-status' + (kind ? ' vas-' + kind : '');
  }

  function audition(v, key) {
    var ctx = st.ctx;
    var pop = ctx && ctx.pop && ctx.pop();
    if (!pop) return;
    if (!st.sheet) st.sheet = buildSheet();
    var sh = st.sheet;
    if (sh.node.parentNode !== pop) pop.appendChild(sh.node);
    stopAudio();
    var token = st.token += 1;
    var name = String(v.name || v.id);
    var have = st.strips[key];
    var target = have && have.target;
    sh.voice = v;
    sh.key = key;
    sh.answer = null;
    sh.env = null;
    sh.hold = null;
    sh.name.textContent = name;
    sh.sub.textContent = 'A sample - never aired' + (target ? ' - for the ' + target.word + ' seat' : '');
    faceInto(sh.face, v.id, name);
    sh.assign.disabled = !target || target.kind === 'none' || v.id === target.current;
    sh.assignWords.textContent = target && target.kind === 'caller' ? 'Pin on ' + target.callerName
      : 'Assign to ' + ((target && target.word) || 'seat');
    sh.replay.disabled = true;
    sh.read.textContent = '';
    var engines = ctx.engines();
    var active = engineWord(engines && engines.engine);
    sheetStatus('Rendering on ' + (active || 'the station\'s engine') + ' - the one engine that is running.', 'wait');
    if (!sh.node.hidden) { /* already open: a new profile replaces the take */ } else openSheet();
    drawMeter();
    ctx.request('POST', '/api/voice-actor/sample', {voice_id: v.id}, SAMPLE_MS).then(function (ans) {
      if (token !== st.token || sh.node.hidden) return;
      sh.answer = ans || {};
      sh.env = sh.answer.envelope || null;
      var bits = [engineWord(sh.answer.engine) + (sh.answer.cached ? ' (replayed, engine untouched)' : ' - ' + Math.round((sh.answer.ms || 0) / 100) / 10 + ' s to render')];
      if (sh.answer.twin_used) bits.push('its ' + engineWord(sh.answer.active) + ' capture');
      if (sh.answer.reference) bits.push(sh.answer.reference);
      sh.sub.textContent = 'A sample - never aired - ' + bits.join(' - ');
      sh.replay.disabled = false;
      playSample(false);
    }, function (err) {
      if (token !== st.token || sh.node.hidden) return;
      if (err && err.status === 404 && /voice-actor\/sample|Not Found/i.test(String(err.message))) {
        sheetStatus('Samples need the strips backend (tools/voice_actor_strips_patch.py).', 'bad');
      } else {
        sheetStatus(String((err && err.message) || err), 'bad');
      }
      drawMeter();
    });
  }

  function playSample(again) {
    var sh = st.sheet;
    if (!sh || !sh.answer || !sh.answer.url) return;
    var a = player();
    a.muted = false;
    var src = st.ctx.stationUrl(sh.answer.url);
    if (a.getAttribute('data-src') !== src) { a.src = src; a.setAttribute('data-src', src); }
    try { a.currentTime = 0; } catch (err) { /* not loaded yet */ }
    sh.hold = null;
    var p;
    try { p = a.play(); } catch (err) { p = Promise.reject(err); }
    sheetStatus(sh.env ? 'Playing - the meter reads the take\'s own levels.' : 'Playing - this take has no level reading.', '');
    if (p && p.then) {
      p.then(function () { runMeter(); }, function (err) {
        if (!sh.node.hidden) sheetStatus(err && err.name === 'NotAllowedError'
          ? 'This screen wants a tap to play sound - tap Play again.' : 'The sample would not play: ' + String((err && err.message) || err), 'bad');
      });
    } else runMeter();
    if (again) runMeter();
  }

  function runMeter() {
    var sh = st.sheet;
    if (!sh || sh.raf) return;
    var step = function () {
      sh.raf = 0;
      if (sh.node.hidden) return;
      drawMeter();
      var a = st.audio;
      var live = a && !a.paused && !a.ended;
      if (live || (sh.hold && sh.hold.db > FLOOR_DB)) sh.raf = root.requestAnimationFrame(step);
      else if (a && a.ended) sheetStatus('Done. Hold another profile, or play this one again.', '');
    };
    sh.raf = root.requestAnimationFrame(step);
  }

  function drawMeter() {
    var sh = st.sheet;
    if (!sh) return;
    var cv = sh.canvas;
    var g = cv.getContext && cv.getContext('2d');
    if (!g) return;
    var a = st.audio;
    var playing = a && !a.paused && !a.ended && sh.answer;
    var lv = playing ? levelAt(sh.env, a.currentTime) : null;
    var pk = lv ? toDb(lv.peak) : -Infinity;
    var rm = lv ? toDb(lv.rms) : -Infinity;
    var now = Date.now();
    sh.hold = holdStep(sh.hold, pk, now);
    sh.last = {peakDb: pk, rmsDb: rm, holdDb: sh.hold.db};
    var W = cv.width, H = cv.height, cx = W / 2, cy = H / 2 + 8, R = W * 0.4;
    var A0 = Math.PI * 0.75, SW = Math.PI * 1.5;           /* 270 degrees, open at the bottom */
    g.clearRect(0, 0, W, H);
    g.lineCap = 'butt';
    g.lineWidth = 16;
    g.strokeStyle = '#1d2b33';
    g.beginPath(); g.arc(cx, cy, R, A0, A0 + SW); g.stroke();
    /* the scale: green to -12, gold to -3, red above */
    var bands = [[FLOOR_DB, -12, '#54d18b'], [-12, -3, '#e3be63'], [-3, 0, '#ef6f5e']];
    var fill = dialFrac(rm);
    bands.forEach(function (b) {
      var f0 = dialFrac(b[0] + 0.0001), f1 = Math.min(fill, dialFrac(b[1]));
      if (b[0] === FLOOR_DB) f0 = 0;
      if (f1 <= f0) return;
      g.strokeStyle = b[2];
      g.beginPath(); g.arc(cx, cy, R, A0 + SW * f0, A0 + SW * f1); g.stroke();
    });
    /* the instant peak, a thin outer arc */
    g.lineWidth = 4;
    g.strokeStyle = '#65c7da';
    var pf = dialFrac(pk);
    if (pf > 0) { g.beginPath(); g.arc(cx, cy, R + 13, A0, A0 + SW * pf); g.stroke(); }
    /* ticks every 6 dB */
    g.lineWidth = 1.5;
    g.strokeStyle = '#35414c';
    for (var d = FLOOR_DB; d <= 0; d += 6) {
      var ta = A0 + SW * dialFrac(d === FLOOR_DB ? FLOOR_DB + 0.0001 : d);
      g.beginPath();
      g.moveTo(cx + Math.cos(ta) * (R - 12), cy + Math.sin(ta) * (R - 12));
      g.lineTo(cx + Math.cos(ta) * (R - 20), cy + Math.sin(ta) * (R - 20));
      g.stroke();
    }
    /* the held peak: a needle mark that waits, then falls */
    var hf = dialFrac(sh.hold.db);
    if (hf > 0) {
      var ha = A0 + SW * hf;
      g.lineWidth = 4;
      g.strokeStyle = sh.hold.db > -3 ? '#ef6f5e' : '#e3be63';
      g.beginPath();
      g.moveTo(cx + Math.cos(ha) * (R - 11), cy + Math.sin(ha) * (R - 11));
      g.lineTo(cx + Math.cos(ha) * (R + 17), cy + Math.sin(ha) * (R + 17));
      g.stroke();
    }
    g.fillStyle = '#dbe7eb';
    g.textAlign = 'center';
    g.font = '600 26px system-ui, sans-serif';
    var big = sh.hold.db > FLOOR_DB ? sh.hold.db.toFixed(1) : '--';
    g.fillText(big, cx, cy + 4);
    g.fillStyle = '#8fa0ad';
    g.font = '11px system-ui, sans-serif';
    g.fillText(sh.answer && !sh.env ? 'no level reading' : 'dBFS peak hold', cx, cy + 22);
    g.fillText('-60', cx + Math.cos(A0) * (R + 2) + 6, cy + Math.sin(A0) * (R + 2) + 22);
    g.fillText('0', cx + Math.cos(A0 + SW) * (R + 2) - 4, cy + Math.sin(A0 + SW) * (R + 2) + 22);
    sh.read.textContent = lv ? 'RMS ' + (rm > FLOOR_DB ? rm.toFixed(1) : '--') + ' dB - peak '
      + (pk > FLOOR_DB ? pk.toFixed(1) : '--') + ' dB' : '';
  }

  function openSheet() {
    var sh = st.sheet;
    sh.node.hidden = false;
    var dismiss = root.PineDismiss;
    if (!sh.unback && dismiss && typeof dismiss.onBack === 'function') {
      /* registered after the shell's probe, so it wins the z tie: BACK closes
       * the sample first, then the popup (SHELL_CONTRACT section 3) */
      sh.unback = dismiss.onBack(function () {
        return sh.node.hidden ? null : {node: sh.node.parentNode || sh.node, close: closeSheet};
      });
    }
  }

  function closeSheet() {
    var sh = st.sheet;
    if (!sh) return;
    st.token += 1;
    stopAudio();
    if (sh.raf) { root.cancelAnimationFrame(sh.raf); sh.raf = 0; }
    sh.node.hidden = true;
    if (typeof sh.unback === 'function') { try { sh.unback(); } catch (err) { /* gone */ } }
    sh.unback = null;
  }

  /* ================================================== start */

  var api = {
    seat: seatHook,
    /* for the drive and the tests */
    lastProfiles: lastProfiles, seatTarget: seatTarget, monogram: monogram, levelAt: levelAt,
    holdStep: holdStep, dialFrac: dialFrac, toDb: toDb,
    isOpen: function () { return !!(st.sheet && !st.sheet.node.hidden); },
    close: closeSheet,
    meter: function () { return st.sheet ? st.sheet.last || null : null; },
    faces: function () { return JSON.parse(JSON.stringify(st.faces)); },
    LAST_N: LAST_N, HOLD_MS: HOLD_MS
  };
  root.PineVoiceActorStrips = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document || typeof document.createElement !== 'function') return;

  root.addEventListener('pine-voice-actor:close', function () { closeSheet(); });
  ['pointerup', 'pointercancel'].forEach(function (n) {
    document.addEventListener(n, function () { if (st.endPress) st.endPress(); });
  });
  var tries = 0;
  (function register() {
    var shell = root.PineVoiceActor;
    if (shell && typeof shell.registerStrips === 'function') { shell.registerStrips(api); return; }
    if ((tries += 1) < 100) root.setTimeout(register, 100);
    else if (root.console) root.console.warn('[voice-actor-strips] the shell has no registerStrips door (tools/edit_voice_actor_strips_shell.py)');
  })();
})(typeof window !== 'undefined' ? window : globalThis);
