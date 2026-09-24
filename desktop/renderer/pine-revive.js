/* PINE REVIVE - CLICK THE WORDS "PINE BOX" AND GET THE SOUND BACK.
 *
 * The operator, after an hour of silence with every server reading green:
 *
 *   "I click the Pine box label in the Pine app, I want it doing whatever
 *    it takes to get the audio playing out of this application, to
 *    redirect or activate the audio in this application and to get it
 *    working properly. Basically I want to be able to click on Pine box
 *    and it does every level of troubleshooting that is required to
 *    basically get the audio to begin playing on my side short of
 *    restarting the server, which is what the icon is for. I just want to
 *    be able to click the Pine box text and it does everything on the
 *    backend as far as coordinating with the orchestrator to do whatever
 *    it takes to get the audio redirected to this application. So it's
 *    coming out of the default audio device that I needed to."
 *
 * The WORDS are this ladder. The MARK beside them is still #1044 - deploy
 * app.py and rebuild the app - and this file does not touch it.
 *
 * ------------------------------------------------------------------
 * WHAT WENT WRONG THE NIGHT THIS WAS ASKED FOR (#1178), because the
 * rungs are shaped by it and not by a general idea of "audio trouble".
 *
 * Lines were written, tinted, rendered, admitted and published the whole
 * time. /api/dj last_said was 26s old. What stopped was HEARING:
 *
 *   - one page holds the air exclusively (audio_owner) and every other
 *     page gags itself for the holder (pineSoloGate, app.py);
 *   - the holder was THE DESK SHELL, which acknowledges no clip at all,
 *     so the whole house was gagged for a page that plays nothing;
 *   - #1332 took the air off it on time, and the #1185 operator-table
 *     fallback handed it straight back one second later, four times in
 *     four and a half minutes, because the deaf-rest is keyed by
 *     listener id and a listener id is minted fresh on every page load;
 *   - and settings.json terminals.pinetab.play was FALSE while
 *     terminals.desktop.play was true, so the preferred device could
 *     never sound. (Measured again while this file was written: BOTH
 *     rows read play:false. That is silence by construction.)
 *
 * THREE THINGS FOLLOW, and they are why this ladder is not in the order
 * a reasonable person would first write it.
 *
 * 1. THIS APPLICATION IS TWO LISTENERS, NOT ONE. The Electron shell
 *    mints `desktop-<rand>` and polls /api/radio/clock with it; the
 *    station panel inside the controlFrame <webview> mints `pb<rand>`
 *    (pineListenerId, sessionStorage.pbfmListener) and is the one that
 *    actually takes clips, plays them and acknowledges them. The air
 *    belongs to the PANEL. Giving it to the shell is the #1178 fault
 *    performed deliberately, so this file never does it.
 *
 * 2. TAKING THE AIR IS RARELY THE CURE; LETTING GO OF IT USUALLY IS.
 *    The task sheet put "take the air" at rung 4. The evidence says the
 *    fault is a page HOLDING it. So rung 4 is split: RELEASE first
 *    ({"clear": true}, both rooms sound, #738 - heard in the wrong room
 *    beats not heard at all), and CLAIM only much later, when releasing
 *    has been tried and something keeps taking the air back.
 *
 * 3. THE SOLO GAG IS NOT OURS TO RIP OFF. #1147: the shell used to
 *    force-unmute the panel's elements and surfaced a second copy of the
 *    broadcast in half-second bursts. A gagged element (data-pine-gag=1)
 *    is left exactly as it is; the cure for a gag is the air rung, and
 *    the panel's own pineSoloGate lifts it on its next clock poll.
 *
 * ------------------------------------------------------------------
 * THE ONE FAULT NO SERVER READING CAN SEE, and the reason rung 2 exists.
 *
 * The panel routes the music player and both DJ voice elements through
 * ONE shared graph: audioScope() builds
 * source -> analyser -> gain -> window.pineAudioCtx.destination.
 * If window.pineAudioCtx is SUSPENDED, the element still plays, its
 * currentTime still advances, its `volume` and `muted` still read
 * perfectly healthy - and the acknowledgement the page posts carries
 * exactly those three numbers. So the station records "heard", the
 * console records audible_volume above zero, and not one sound leaves
 * the machine. Every meter in the house says green.
 *
 * That is why this ladder reads pineAudioCtx.state AND watches
 * pineAudioCtx.currentTime advance, and why the verdict at the end can
 * say "the element is playing and the graph is asleep" - a sentence no
 * server-side reading in this station is able to produce today.
 *
 * ------------------------------------------------------------------
 * EVERY RUNG SAYS WHAT IT DID, NOT THAT IT RAN, and a rung that cannot
 * prove sound says so. This house has been bitten repeatedly by meters
 * that can only print one answer; there is no code path in this file
 * that reports success without a measurement behind it.
 *
 * ES5, one IIFE, no dependencies beyond PineDuck. Exports
 * window.PineRevive = {run, open, close, RUNGS, ...}.
 */
(function (root) {
  'use strict';

  /* ---------------------------------------------------------------
     THE WORLD, in one place, so the ladder can be driven by a stub.

     There is no debugging port on the machine this app runs on, so the
     only way to test the ordering and the stop-on-success rule is to
     hand the ladder a fake world and watch which rungs it enters. */

  var DEPS = null;

  function deps() {
    if (DEPS) return DEPS;
    return {
      api: root.pineDesktop || null,
      doc: root.document || null,
      win: root,
      now: function () { return Date.now(); },
      wait: function (ms) {
        return new Promise(function (go) { setTimeout(go, ms); });
      }
    };
  }

  function wait(ms) { return deps().wait(ms); }

  /* A station call that never throws. Every rung wants the ANSWER or the
     REASON there is no answer, and an exception halfway up a ladder is
     the one thing that would leave the operator with a half-written
     panel and no verdict. */
  function call(verb, route, body) {
    var api = deps().api;
    if (!api || typeof api[verb] !== 'function') {
      return Promise.resolve({ok: false, why: 'this app has no bridge to the station'});
    }
    var going;
    try {
      going = (verb === 'get') ? api.get(route) : api[verb](route, body || {});
    } catch (err) {
      return Promise.resolve({ok: false, why: String((err && err.message) || err)});
    }
    if (!going || typeof going.then !== 'function') {
      return Promise.resolve({ok: true, body: going});
    }
    return going.then(
      function (answer) { return {ok: true, body: answer || {}}; },
      function (err) {
        return {ok: false, why: String((err && err.message) || err || 'no answer')};
      });
  }

  function GET(route) { return call('get', route); }
  function POST(route, body) { return call('post', route, body); }
  function PUT(route, body) { return call('put', route, body); }

  function num(v, fallback) {
    var n = Number(v);
    return Number.isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
  }

  function round(v, places) {
    var f = Math.pow(10, places === undefined ? 2 : places);
    return Math.round(num(v) * f) / f;
  }

  function el(id) {
    var d = deps().doc;
    return (d && d.getElementById) ? d.getElementById(id) : null;
  }

  /* ---------------------------------------------------------------
     THE WEBVIEWS.

     The broadcast this application plays is NOT in this document. It is
     inside the controlFrame <webview>, which loads the station's own
     panel from the box - a different renderer process with its own
     document, its own listener id and its own audio graph. The only
     road into it is executeJavaScript, which is what renderer.js has
     always used to set volumes in there (appVolumeScript).

     So the three functions below are declared here and never called
     here: they are stringified and evaluated INSIDE the panel. They
     must close over nothing in this file. */

  function frames() {
    var d = deps().doc;
    var out = [];
    if (!d || !d.querySelectorAll) return out;
    var all;
    try { all = d.querySelectorAll('webview'); } catch (err) { return out; }
    for (var i = 0; i < all.length; i += 1) {
      var f = all[i];
      if (!f || !f.src) continue;
      if (typeof f.executeJavaScript !== 'function') continue;
      out.push(f);
    }
    return out;
  }

  function runIn(frame, source) {
    var going;
    try { going = frame.executeJavaScript(source); }
    catch (err) { return Promise.resolve(null); }
    if (!going || typeof going.then !== 'function') return Promise.resolve(going || null);
    return going.then(function (v) { return v; }, function () { return null; });
  }

  function named(frame, answer) {
    return {id: String(frame.id || ''), got: answer};
  }

  function inEvery(fn) {
    var list = frames();
    var jobs = [];
    var source = '(' + fn.toString() + ')()';
    var one = function (frame) {
      return runIn(frame, source).then(function (answer) {
        return named(frame, answer);
      });
    };
    for (var i = 0; i < list.length; i += 1) jobs.push(one(list[i]));
    return Promise.all(jobs);
  }

  /* --- evaluated inside the panel: what is true in there right now --- */
  function panelProbeFn() {
    var out = {href: '', gagged: false, listener: '', ctx: null, els: [],
               shellVolume: null, shellAudible: null};
    try { out.href = String(location.href); } catch (e1) { /* fine */ }
    try { out.gagged = !!window.__pineGagged; } catch (e2) { /* fine */ }
    try { out.shellVolume = window.__pineDesktopVolume; } catch (e3) { /* fine */ }
    try { out.shellAudible = window.__pineDesktopAudible; } catch (e4) { /* fine */ }
    try { out.listener = String(sessionStorage.pbfmListener || ''); } catch (e5) { /* locked */ }
    try {
      var c = window.pineAudioCtx;
      if (c) {
        out.ctx = {state: String(c.state), time: Number(c.currentTime),
                   sink: (typeof c.sinkId === 'string' ? c.sinkId : null)};
      }
    } catch (e6) { /* no graph yet, which is its own answer */ }
    try {
      var all = document.querySelectorAll('audio,video');
      for (var i = 0; i < all.length; i += 1) {
        var n = all[i];
        var d = n.dataset || {};
        out.els.push({
          id: String(n.id || ''), tag: String(n.tagName),
          live: String(d.pineLive || ''), gag: String(d.pineGag || ''),
          shellMuted: String(d.pineShellMuted || ''),
          muted: !!n.muted, volume: Number(n.volume), paused: !!n.paused,
          t: Number(n.currentTime), ready: Number(n.readyState),
          sink: (typeof n.sinkId === 'string' ? n.sinkId : null),
          err: (n.error ? Number(n.error.code) : 0)
        });
      }
    } catch (e7) { /* a navigating page */ }
    return out;
  }

  /* --- evaluated inside the panel: wake its audio up ---------------- */
  function panelReviveFn() {
    var did = [];
    try {
      var c = window.pineAudioCtx;
      if (c && String(c.state) !== 'running') {
        did.push('the panel audio graph was ' + c.state
                 + ' - every clip it plays was going nowhere; asked it to resume');
        try { c.resume(); } catch (e1) { /* the next probe will say */ }
      }
    } catch (e2) { /* no graph */ }
    try {
      var all = document.querySelectorAll('audio,video');
      for (var i = 0; i < all.length; i += 1) {
        var n = all[i];
        var d = n.dataset || {};
        /* #1147: A GAG IS THE STATION'S, NOT OURS. Force-unmuting a page
           the solo gate has gagged surfaced a second copy of the
           broadcast in half-second bursts. The cure for a gag is the air
           rung; pineSoloGate lifts it on its own next clock poll. */
        if (String(d.pineGag || '') === '1' || String(d.pineDecor || '') === '1') continue;
        if (n.muted && String(d.pineShellMuted || '') === '1') {
          n.muted = false;
          d.pineShellMuted = '';
          did.push('un-muted the ' + String(n.tagName).toLowerCase()
                   + ' this shell had silenced');
        }
      }
    } catch (e3) { /* fine */ }
    return did;
  }

  /* --- evaluated inside the panel: back onto the default output ----- */
  function panelSinkFn() {
    var did = [];
    try {
      var c = window.pineAudioCtx;
      if (c && typeof c.setSinkId === 'function'
          && typeof c.sinkId === 'string' && c.sinkId) {
        did.push('the panel audio graph was pinned to output "' + c.sinkId
                 + '" - put it back on the system default');
        try { c.setSinkId(''); } catch (e1) { /* older Chromium */ }
      }
    } catch (e2) { /* fine */ }
    try {
      var all = document.querySelectorAll('audio,video');
      for (var i = 0; i < all.length; i += 1) {
        var n = all[i];
        if (typeof n.setSinkId !== 'function') continue;
        if (typeof n.sinkId !== 'string' || !n.sinkId) continue;
        did.push('put ' + (n.id || String(n.tagName).toLowerCase())
                 + ' back on the system default output');
        try { n.setSinkId(''); } catch (e3) { /* it keeps the old sink */ }
      }
    } catch (e4) { /* fine */ }
    return did;
  }

  /* ---------------------------------------------------------------
     THE PROOF.

     "A rung that cannot prove sound must say so rather than claim
     success." So this is the only thing in the file allowed to say the
     word "sound", and it says it on THREE readings taken 1.2 seconds
     apart inside the page that is actually playing the show:

       1. a live element's currentTime ADVANCED. Not that play()
          resolved - play() resolves on a muted element into a dead
          device. Advanced.
       2. that element is unmuted and its volume is above zero.
       3. the panel's shared audio graph is RUNNING and its own clock
          advanced. Every live element in the panel is wired through
          window.pineAudioCtx, so a suspended graph is silence that
          every other reading in the house calls green.

     All three, or it is not sound. Two of three is a sentence, and the
     sentence is what the operator gets. */

  function elKey(row, i) {
    return (row.id || (row.tag + ':' + i)) + '|' + row.live;
  }

  function isLiveRow(row) {
    return !!row.live || row.id === 'musicPlayer' || row.id === 'desktopRadioPlayer';
  }

  function compareProbes(before, after) {
    var out = {sound: false, moving: [], silentMoving: [], graphs: [],
               asleep: [], why: ''};
    var index = {};
    var i;
    for (i = 0; i < before.length; i += 1) index[before[i].id] = before[i].got;
    for (i = 0; i < after.length; i += 1) {
      var frameId = after[i].id;
      var b = after[i].got;
      var a = index[frameId];
      if (!a || !b) continue;
      var was = {};
      var j;
      for (j = 0; j < (a.els || []).length; j += 1) {
        was[elKey(a.els[j], j)] = a.els[j];
      }
      var graph = null;
      if (b.ctx) {
        graph = {frame: frameId, state: b.ctx.state,
                 advanced: a.ctx ? round(b.ctx.time - a.ctx.time, 3) : null};
        out.graphs.push(graph);
        if (b.ctx.state !== 'running'
            || (graph.advanced !== null && graph.advanced <= 0.05)) {
          out.asleep.push(graph);
        }
      }
      for (j = 0; j < (b.els || []).length; j += 1) {
        var now = b.els[j];
        var then = was[elKey(now, j)];
        if (!then || !isLiveRow(now)) continue;
        var dt = round(now.t - then.t, 3);
        if (dt <= 0.15) continue;
        var row = {frame: frameId, id: (now.id || now.tag.toLowerCase()),
                   live: now.live, advanced: dt, muted: now.muted,
                   volume: round(now.volume, 3), gagged: now.gag === '1',
                   graph: graph};
        if (now.muted || now.volume <= 0.001) out.silentMoving.push(row);
        else out.moving.push(row);
      }
    }
    /* Sound is an audible element whose own graph is awake. */
    for (i = 0; i < out.moving.length; i += 1) {
      var m = out.moving[i];
      var asleep = !!m.graph
        && (m.graph.state !== 'running'
            || (m.graph.advanced !== null && m.graph.advanced <= 0.05));
      if (!asleep) { out.sound = true; break; }
    }
    if (out.sound) {
      out.why = 'a live element advanced with the graph running';
    } else if (out.moving.length) {
      out.why = 'a live element advanced but the panel audio graph is asleep';
    } else if (out.silentMoving.length) {
      out.why = 'a live element advanced with the sound turned off in it';
    } else {
      out.why = 'nothing in this application advanced a single frame of audio';
    }
    return out;
  }

  function proveSound(gapMs) {
    var gap = num(gapMs, 1200);
    return inEvery(panelProbeFn).then(function (before) {
      return wait(gap).then(function () {
        return inEvery(panelProbeFn).then(function (after) {
          return compareProbes(before, after);
        });
      });
    });
  }

  /* ---------------------------------------------------------------
     THE TONE, and exactly what it is worth.

     "Play a short known sound through the same path the show uses and
     confirm the element actually advanced."

     The show's path in this application is the panel's graph, and that
     is what proveSound() above watches. This is the OTHER half: a
     quarter of a second of 660 Hz, built here in the shell, run through
     an AnalyserNode and into the default output, at 7% so it is a pip
     and not an alarm.

     WHAT IT PROVES: this application can open an audio context, that
     context reached the state "running", its clock advanced, and a
     non-zero signal was measured going into the destination. That rules
     out a dead Web Audio stack, a context Chromium refused to start for
     want of a user gesture, and an output device the process could not
     open at all.

     WHAT IT CANNOT PROVE, and this is said on the panel too: that a
     speaker moved. The Windows per-application volume mixer, the master
     volume and the physical output are all invisible from inside a
     page. A zeroed app in the volume mixer measures exactly the same as
     a working one. So this reading is reported as a number with that
     sentence attached, never as "it works". */

  function toneTest(ms) {
    var W = deps().win;
    var hold = num(ms, 240);
    var Ctor = W.AudioContext || W.webkitAudioContext;
    if (!Ctor) {
      return Promise.resolve({ok: false, peak: null,
        why: 'this build has no Web Audio at all'});
    }
    var ctx;
    try { ctx = new Ctor(); }
    catch (err) {
      return Promise.resolve({ok: false, peak: null,
        why: 'could not open an audio context: ' + String((err && err.message) || err)});
    }
    var out = {ok: false, peak: 0, state: String(ctx.state), advanced: 0,
               sink: (typeof ctx.sinkId === 'string' ? ctx.sinkId : null), why: ''};
    var t0 = num(ctx.currentTime);
    var resume = ctx.resume ? ctx.resume() : Promise.resolve();
    if (!resume || typeof resume.then !== 'function') resume = Promise.resolve();
    return resume.then(function () { return null; }, function () { return null; })
      .then(function () {
        var osc, gain, scope, bins;
        try {
          osc = ctx.createOscillator();
          gain = ctx.createGain();
          scope = ctx.createAnalyser();
          scope.fftSize = 256;
          bins = new Uint8Array(scope.fftSize);
          osc.type = 'sine';
          osc.frequency.value = 660;
          gain.gain.value = 0.0001;
          osc.connect(gain);
          gain.connect(scope);
          scope.connect(ctx.destination);
          gain.gain.setValueAtTime(0.0001, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.07, ctx.currentTime + 0.03);
          osc.start();
        } catch (err) {
          out.why = 'the tone would not start: ' + String((err && err.message) || err);
          try { ctx.close(); } catch (e1) { /* fine */ }
          return out;
        }
        var reads = 0;
        var tick = function () {
          try {
            scope.getByteTimeDomainData(bins);
            var top = 0;
            for (var i = 0; i < bins.length; i += 1) {
              var away = Math.abs(bins[i] - 128);
              if (away > top) top = away;
            }
            if (top / 128 > out.peak) out.peak = round(top / 128, 4);
            reads += 1;
          } catch (err) { /* a closing context */ }
        };
        var every = setInterval(tick, 30);
        return wait(hold).then(function () {
          clearInterval(every);
          tick();
          out.state = String(ctx.state);
          out.advanced = round(num(ctx.currentTime) - t0, 3);
          out.reads = reads;
          try { gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.04); } catch (e2) { /* fine */ }
          try { osc.stop(ctx.currentTime + 0.06); } catch (e3) { /* fine */ }
          setTimeout(function () { try { ctx.close(); } catch (e4) { /* fine */ } }, 300);
          out.ok = out.state === 'running' && out.advanced > 0.02 && out.peak > 0.02;
          out.why = out.ok
            ? ('this application produced audio samples - the context ran, its '
               + 'clock advanced ' + out.advanced + 's and the signal peaked at '
               + Math.round(out.peak * 100) + '% of full scale. That is as far '
               + 'as a page can see: the Windows volume mixer and the speaker '
               + 'itself are invisible from in here.')
            : ('no audio left this application: the context is "' + out.state
               + '", its clock advanced ' + out.advanced + 's and the signal '
               + 'peaked at ' + Math.round(out.peak * 100) + '%.');
          return out;
        });
      });
  }

  /* Which outputs Windows is offering this application. */
  function outputs() {
    var W = deps().win;
    var media = W.navigator && W.navigator.mediaDevices;
    if (!media || typeof media.enumerateDevices !== 'function') {
      return Promise.resolve({ok: false, list: [],
        why: 'this build cannot list audio devices'});
    }
    return media.enumerateDevices().then(function (all) {
      var list = [];
      for (var i = 0; i < all.length; i += 1) {
        if (String(all[i].kind) !== 'audiooutput') continue;
        list.push({id: String(all[i].deviceId || ''),
                   label: String(all[i].label || '(unnamed)')});
      }
      return {ok: true, list: list, why: ''};
    }, function (err) {
      return {ok: false, list: [],
        why: 'Windows refused the device list: ' + String((err && err.message) || err)};
    });
  }

  /* ---------------------------------------------------------------
     RUNG 1 - IS ANYTHING WRONG?  Changes nothing.

     Five readings and one probe, and the probe is the one the station
     cannot take for itself: what is true inside the panel webview.

     The station already answers this in the operator's own terms
     (/api/broadcast/health: stuck, say, holding_the_air, solo_gagged,
     clips_waiting, fix_with) and /api/broadcast/console adds the per
     LISTENER acknowledgement census - acks, played, muted, vol=0,
     interrupted, stalled - which is how this rung can say "this
     application took three clips and started none of them" rather than
     "something is wrong somewhere".

     IT DOES NOT STOP ON A GREEN READING ALONE. The sheet said stop if
     the station is not stuck and this page acknowledged a clip
     recently. On the night of #1178 the station was not stuck and the
     acknowledgements were flowing, with audible_volume above zero, and
     the house was silent for an hour. So a green reading here buys a
     PROOF, not a verdict: if the sound is really there the ladder stops
     at rung 1 with nothing touched, and if it is not, the fact that the
     station thinks it is becomes the most useful thing on the panel. */

  function fire(node, kind) {
    try {
      node.dispatchEvent(new Event(kind, {bubbles: true}));
      return true;
    } catch (err) {
      try { node.dispatchEvent({type: kind}); return true; }
      catch (err2) { return false; }
    }
  }

  function pick(frameProbes, wanted) {
    var i;
    for (i = 0; i < frameProbes.length; i += 1) {
      if (frameProbes[i].id === wanted && frameProbes[i].got) return frameProbes[i];
    }
    for (i = 0; i < frameProbes.length; i += 1) {
      if (frameProbes[i].got && frameProbes[i].got.listener) return frameProbes[i];
    }
    return null;
  }

  function rowFor(settings, addr) {
    var table = (settings && settings.terminals) || {};
    var key;
    /* The app's own row first: APP_ROW is "desktop" in renderer.js and
       that is the row the operator sees as "This app". */
    if (table.desktop && (!addr || String(table.desktop.addr || '') === addr)) {
      return 'desktop';
    }
    for (key in table) {
      if (addr && String((table[key] || {}).addr || '') === addr) return key;
    }
    return table.desktop ? 'desktop' : '';
  }

  function rungLook(ctx) {
    return Promise.all([
      GET('/api/broadcast/health'),
      GET('/api/broadcast/console'),
      GET('/api/radio/listeners'),
      GET('/api/dj/state'),
      GET('/api/settings'),
      inEvery(panelProbeFn)
    ]).then(function (got) {
      var found = [];
      ctx.health = (got[0].ok && got[0].body) || {};
      ctx.console = (got[1].ok && got[1].body) || {};
      ctx.roster = (got[2].ok && got[2].body) || {};
      ctx.djState = (got[3].ok && got[3].body) || {};
      ctx.settings = (got[4].ok && got[4].body) || {};
      ctx.probes = got[5] || [];
      if (!got[0].ok) found.push('the station did not answer /api/broadcast/health: ' + got[0].why);

      var mine = pick(ctx.probes, 'controlFrame');
      ctx.panel = mine ? mine.got : null;
      ctx.panelFrame = mine ? mine.id : '';
      ctx.panelListener = ctx.panel ? String(ctx.panel.listener || '') : '';

      /* Which machine we are, taken from the roster row our panel's own
         listener id sits on - never assumed from the settings table,
         which is the thing #1178 found pointing at an address with
         nothing on it. */
      var rows = (ctx.roster.listeners) || [];
      var i;
      ctx.addr = '';
      for (i = 0; i < rows.length; i += 1) {
        if (String(rows[i].listener || '') === ctx.panelListener) {
          ctx.addr = String(rows[i].addr || '');
        }
      }
      ctx.row = rowFor(ctx.settings, ctx.addr);
      var table = (ctx.settings.terminals) || {};
      ctx.rowData = (ctx.row && table[ctx.row]) || null;

      ctx.owner = String(ctx.health.holding_the_air || ctx.roster.audio_owner || '');
      ctx.ownerIsPanel = !!ctx.owner && ctx.owner === ctx.panelListener;
      ctx.ownerIsThisMachine = false;
      for (i = 0; i < rows.length; i += 1) {
        if (String(rows[i].listener || '') === ctx.owner
            && ctx.addr && String(rows[i].addr || '') === ctx.addr) {
          ctx.ownerIsThisMachine = true;
        }
      }
      ctx.musicTo = String(ctx.djState.music_to || '');
      ctx.voiceTo = String(ctx.djState.voice_to || '');
      ctx.routeHere = (ctx.musicTo === 'here' || ctx.musicTo === 'both'
                       || ctx.voiceTo === 'here' || ctx.voiceTo === 'both');

      var triage = ctx.console.triage || {};
      var census = (triage.listeners) || {};
      ctx.baseline = census[ctx.panelListener] || null;
      ctx.found1 = found;
      return {changed: false, prove: true, found: sayLook(ctx, found, triage),
              did: ['read the station and probed inside this window; changed nothing']};
    });
  }

  /* What rung 1 found, in sentences rather than fields. */
  function sayLook(ctx, found, triage) {
    if (ctx.health.say) found.push('the station says: ' + ctx.health.say);
    if (ctx.health.paused) {
      found.push('THE STATION IS PAUSED - that is the FM switch in this rail, not this ladder');
    }
    found.push(ctx.panelListener
      ? ('this application listens as ' + ctx.panelListener
         + (ctx.addr ? (' from ' + ctx.addr) : '')
         + ' - that is the panel inside this window. The shell around it takes no '
         + 'clips at all and must never hold the air (#1178)')
      : 'the station panel in this window is not reporting a listener id - it may not have loaded');
    found.push(ctx.owner
      ? ('the air is held by ' + ctx.owner + ' - '
         + (ctx.ownerIsPanel ? 'which is this application'
            : ctx.ownerIsThisMachine
              ? 'THIS MACHINE but not the panel: the #1178 shape exactly, every '
                + 'other page in the house gagged for a page that plays nothing'
              : 'another device, so this application is gagging itself for it'))
      : 'nobody holds the air, so nothing is gagging this application');
    found.push(ctx.rowData
      ? ('the out-loud switch for "' + ctx.row + '" ('
         + String(ctx.rowData.name || ctx.row) + ' at '
         + String(ctx.rowData.addr || 'no address') + ') reads play='
         + (ctx.rowData.play ? 'true' : 'FALSE'))
      : 'there is no terminals row in settings.json for this machine');
    found.push('the show is routed music to ' + (ctx.musicTo || '?')
               + ', voices to ' + (ctx.voiceTo || '?')
               + (ctx.routeHere ? ' - a page, which is this application'
                  : ' - NOT a page, so this application only hears it with Monitor here on'));
    if (ctx.panel && ctx.panel.ctx) {
      found.push('the panel audio graph is ' + ctx.panel.ctx.state
                 + (ctx.panel.ctx.state === 'running' ? ''
                    : ' - every clip it plays is going nowhere, and no reading '
                      + 'on the station can see that'));
    } else if (ctx.panel) {
      found.push('the panel has built no audio graph yet - its clips play straight out');
    }
    if (ctx.panel && ctx.panel.gagged) {
      found.push('the panel has gagged itself for whoever holds the air');
    }
    found.push(ctx.baseline
      ? ('the station heard ' + num(ctx.baseline.acks) + ' acknowledgement(s) from this '
         + 'application recently: ' + num(ctx.baseline.played) + ' played, '
         + num(ctx.baseline.muted) + ' muted, ' + num(ctx.baseline.vol_zero)
         + ' at zero volume, ' + num(ctx.baseline.interrupted) + ' interrupted, '
         + num(ctx.baseline.stalled) + ' stalled')
      : 'the station has heard nothing at all from this application recently');
    if (triage && triage.why) found.push('the station names the fault: ' + triage.why);
    return found;
  }

  /* ---------------------------------------------------------------
     RUNG 2 - THIS APPLICATION'S OWN AUDIO.  Local; the station is not
     asked and nothing anyone else can hear is changed.

     "to redirect or activate the audio in this application"

     Four things, and it drives the controls this app ALREADY has rather
     than inventing a second set beside them - the #1063 lesson about
     four desks that do not agree:

       the App volume slider (#appVolume, renderer.js setAppVolume)
       the listener's mixer (window.pineMixer, #1419)
       the Monitor here switch (window.pineMonitorSay, #997/#979)
       and, inside the panel, window.pineAudioCtx.resume()

     THE RESUME IS THE IMPORTANT ONE. A suspended context after a
     relaunch plays every clip perfectly into nothing, with the element,
     the volume, the mute flag and the acknowledgement all reading
     healthy. It is the only fault in this ladder that the station is
     structurally unable to see.

     AND THIS RUNG RUNS INSIDE THE OPERATOR'S CLICK. Chromium will not
     start an audio context or a media element without a user gesture,
     and clicking the words "Pine Box" is one. That is not incidental -
     it is half the reason this belongs on a click and not on a timer. */

  function rungOwnAudio(ctx) {
    var did = [];
    var found = [];
    var W = deps().win;

    var slider = el('appVolume');
    if (slider) {
      var was = num(slider.value, -1);
      found.push('the App volume is at ' + was + '% (operator setting unchanged)');
    } else {
      found.push('this build has no App volume slider');
    }

    if (W.pineMixer && typeof W.pineMixer.get === 'function') {
      var mix = W.pineMixer.get() || {};
      found.push('the mixer reads voices ' + round(num(mix.voice, 1), 2)
                 + ', music ' + round(num(mix.music, 1), 2)
                 + ' (operator settings left unchanged)');
    }

    if (typeof W.pineMonitorSay === 'function') {
      var said = null;
      try { said = W.pineMonitorSay(); } catch (err) { said = null; }
      if (said && !ctx.routeHere && !said.monitor) {
        try { said = W.pineMonitorSay(true); } catch (err) { /* reported */ }
        did.push('the show is not routed to a page, so this app was silencing its '
                 + 'own copy - turned "Monitor here" on rather than moving the show '
                 + 'off the box behind your back');
      } else if (said) {
        found.push('Monitor here is ' + (said.monitor ? 'on' : 'off')
                   + ' and the music route is "' + String(said.musicRoute || '?') + '"');
      }
    }

    var player = el('desktopRadioPlayer');
    var musicLevel = W.pineMixer && typeof W.pineMixer.get === 'function'
      ? num((W.pineMixer.get() || {}).music, 1) : 1;
    if (player && player.paused && ctx.routeHere && musicLevel > 0) {
      try {
        var going = player.play();
        if (going && going.catch) going.catch(function () { /* said below */ });
        did.push('this app music element was paused - started it from your click, '
                 + 'which is the gesture Chromium wants before it will play anything');
      } catch (err) { found.push('this app music element refused to start: ' + err); }
    } else if (player && musicLevel <= 0) {
      found.push('the music slider is at zero; the record remains paused');
    }

    return inEvery(panelReviveFn).then(function (answers) {
      var i, j;
      for (i = 0; i < answers.length; i += 1) {
        var list = answers[i].got || [];
        for (j = 0; j < list.length; j += 1) did.push(answers[i].id + ': ' + list[j]);
      }
      if (!did.length) found.push('nothing in this application was muted, zeroed or asleep');
      return {changed: did.length > 0, did: did, found: found,
              cannot: 'this rung can only see the audio inside this window. It '
                      + 'cannot see the Windows volume mixer, where this '
                      + 'application can be muted on its own.'};
    });
  }

  /* ---------------------------------------------------------------
     RUNG 3 - THE OUT-LOUD SWITCH FOR THIS DEVICE.

     settings.json terminals.<row>.play. On the night of #1178 the
     pinetab row was false and the desktop row true; measured again
     while this was written, BOTH were false, which is silence by
     construction - and #1187 means a device whose row says play:false
     may not take the exclusive either, so this has to come before the
     air rung or the air rung is refused.

     PUT /api/settings REPLACES the whole document. So this is
     read-modify-write of the WHOLE object with ONE field changed, the
     same shape playersWrite uses in renderer.js. It never touches
     another device's row: turning the tablet off to make this app loud
     is not troubleshooting, it is taking the tablet away. */

  function rungOutLoud(ctx) {
    return GET('/api/settings').then(function (got) {
      if (!got.ok) {
        return {changed: false, did: [],
                found: ['could not read settings.json: ' + got.why],
                cannot: 'without settings.json this rung cannot tell whether this '
                        + 'device is allowed to play out loud at all'};
      }
      var settings = got.body || {};
      var table = settings.terminals || {};
      var row = ctx.row || rowFor(settings, ctx.addr);
      if (!row || !table[row]) {
        return {changed: false, did: [],
                found: ['there is no terminals row for this machine, so nothing '
                        + 'here is holding its out-loud switch down'],
                cannot: 'this ladder will not invent a device row; that is the '
                        + 'device table, and this ladder does not write rows into it'};
      }
      var current = table[row] || {};
      var did = [];
      var found = [];
      var next = {};
      var key;
      for (key in current) next[key] = current[key];
      if (!current.play) {
        next.play = true;
        did.push('the out-loud switch for "' + row + '" was FALSE - a device set '
                 + 'not to play out loud is silent whatever else is true, and '
                 + '#1187 will not let it hold the air either. Turned it on.');
      } else {
        found.push('the out-loud switch for "' + row + '" was already on');
      }
      if (ctx.addr && String(current.addr || '') !== ctx.addr) {
        next.addr = ctx.addr;
        did.push('the row said this machine was at "' + String(current.addr || 'nowhere')
                 + '" and it is at ' + ctx.addr + ' - corrected the address, which is '
                 + 'the field the station matches a listener on (#1178 found the '
                 + 'tablet row pointing at an address with nothing on it)');
      }
      if (!did.length) return {changed: false, did: [], found: found};
      table[row] = next;
      settings.terminals = table;
      return PUT('/api/settings', settings).then(function (put) {
        if (!put.ok) {
          return {changed: false, did: [],
                  found: found.concat(['the station refused the change: ' + put.why]),
                  cannot: 'the out-loud switch could not be written'};
        }
        ctx.row = row;
        ctx.rowData = next;
        return {changed: true, did: did, found: found,
                cannot: 'turning this device on does not turn any other device off, '
                        + 'and it does not decide which device wins - that is the air.'};
      });
    });
  }

  /* ---------------------------------------------------------------
     RUNG 4a - LET GO OF THE AIR.  POST /api/radio/solo {"clear": true}

     This is the rung the sheet called "take the air", turned around,
     because the evidence says so. #1008 hands ONE listener the exclusive
     and every other page gags itself. #1178 is what happens when the
     holder is a page that plays nothing: the whole house goes quiet for
     it, and the automatic hand-back puts it straight back.

     RELEASING is therefore the cure, not claiming: with no owner set,
     pineSoloGate gags nobody, which is #1008's own stated contract, and
     this application is free to sound. It is also the least destructive
     thing available - the tablet keeps its sound too. #738: heard in the
     wrong room beats not heard at all.

     CLAIMING the air for this application is rung 4b, far below, and it
     only happens if releasing was not enough. Said plainly on the panel
     either way, because the operator asked which it was doing. */

  function rungReleaseAir(ctx) {
    if (!ctx.owner) {
      return Promise.resolve({changed: false, did: [],
        found: ['nobody holds the air, so there is no gag to lift']});
    }
    if (ctx.ownerIsPanel) {
      return Promise.resolve({changed: false, did: [],
        found: ['this application already holds the air, so nothing is gagging it'],
        cannot: 'holding the air cannot make a silent page loud - #1178 is exactly '
                + 'a page that held it and played nothing'});
    }
    var who = ctx.ownerIsThisMachine
      ? 'a page on THIS machine that is not the panel - the #1178 shape'
      : 'another device';
    return POST('/api/radio/solo', {clear: true}).then(function (got) {
      if (!got.ok) {
        return {changed: false, did: [],
                found: ['the station refused to release the air: ' + got.why]};
      }
      ctx.owner = String((got.body && got.body.audio_owner) || '');
      return {changed: true,
        did: ['the air was held by ' + who + ', so every other page in the house '
              + 'was gagging itself for it. RELEASED it - every player may sound '
              + 'now, this one included. Nothing else was taken away from anybody.'],
        found: ['the station now reports the air held by "'
                + (ctx.owner || 'nobody') + '"'],
        cannot: 'releasing the air lets this application sound; it cannot make the '
                + 'station send it anything.'};
    });
  }

  /* ---------------------------------------------------------------
     RUNG 5 - UNSTICK THE DELIVERY.  POST /api/broadcast/unwedge

     The #1147 feed epoch: every page drops the clip it is holding and
     cannot start, orphans the play promises in flight and takes the next
     one. If the room is still quiet twelve seconds later the station
     releases the exclusive itself.

     IT COSTS A LINE. The clip being held is dropped, not replayed. And
     the route waits twelve seconds inside the station before answering,
     so this rung is slow on purpose and says so. */

  function rungUnwedge(ctx) {
    var waiting = num(ctx.health && ctx.health.clips_waiting, 0);
    return POST('/api/broadcast/unwedge', {}).then(function (got) {
      if (!got.ok) {
        return {changed: false, did: [],
                found: ['the station refused to unstick the broadcast: ' + got.why]};
      }
      var body = got.body || {};
      var did = body.did || [];
      var health = body.health || {};
      if (!body.ran) {
        return {changed: false, did: [],
                found: ['the station says there was nothing to unstick: '
                        + String(body.say || '')]};
      }
      return {changed: true,
        did: ['flushed the page feed at the station: ' + (did.join('; ') || String(body.say || ''))
              + (waiting ? (' (' + waiting + ' clip(s) were waiting)') : '')],
        found: ['the station now says: ' + String(health.say || '')],
        cannot: 'a flush drops the clip this page was stuck on - it is not replayed. '
                + 'It cannot fix a page that is not stuck.'};
    });
  }

  /* ---------------------------------------------------------------
     RUNG 6 - THE OUTPUT DEVICE.

     "So it's coming out of the default audio device that I needed to."

     WHAT THIS APPLICATION DOES TODAY, established before anything was
     changed: nothing. There is no output picker anywhere in the desk,
     no setSinkId call and no enumerateDevices call outside the talk
     dot, which lists INPUTS. Every element in the shell and in the panel
     plays to whatever Chromium picked, which is the system default.

     So this rung does not add a picker beside a picker that does not
     exist. It does one thing, which is the thing the operator asked
     for: if anything in this application has been pinned to a NAMED
     output - by a previous run, by a page, by a device that has since
     been unplugged - it is put back on the system default with
     setSinkId(''), which is the one sinkId value that needs no
     permission and always means "wherever Windows is sending sound".

     AND IT REPORTS THE LIST, because a list with nothing on it is a
     whole diagnosis: if Windows is offering this application no audio
     outputs at all, no rung above or below this one can produce a sound
     and the ladder should stop pretending otherwise.

     WHAT IT CANNOT DO, said on the panel: it cannot change which device
     Windows calls the default, it cannot see or move the per-application
     volume in the Windows volume mixer, and it cannot tell a working
     speaker from a muted one. Those are outside a page. */

  function rungOutputDevice(ctx) {
    return outputs().then(function (got) {
      var found = [];
      var i;
      if (!got.ok) {
        found.push(got.why);
      } else if (!got.list.length) {
        found.push('WINDOWS IS OFFERING THIS APPLICATION NO AUDIO OUTPUT AT ALL. '
                   + 'Nothing on this ladder can make a sound until that is true '
                   + 'again - check the output device in Windows sound settings.');
      } else {
        var names = [];
        for (i = 0; i < got.list.length && i < 6; i += 1) names.push(got.list[i].label);
        found.push('Windows is offering this application ' + got.list.length
                   + ' audio output(s): ' + names.join(', '));
      }
      /* An enumeration that FAILED is not an enumeration that found
         nothing, and the verdict below reads this: "Windows is offering
         this application no output" is a diagnosis, "I could not ask" is
         an excuse, and printing the first when the second is true is
         exactly the meter that can only print one answer. */
      ctx.outputs = got.ok ? (got.list || []) : null;
      var did = [];
      /* This document first - the shell music player and the SFX set. */
      var d = deps().doc;
      var here = [];
      try { here = d && d.querySelectorAll ? d.querySelectorAll('audio,video') : []; }
      catch (err) { here = []; }
      for (i = 0; i < here.length; i += 1) {
        var n = here[i];
        if (typeof n.setSinkId !== 'function') continue;
        if (typeof n.sinkId !== 'string' || !n.sinkId) continue;
        did.push('this window had ' + (n.id || 'an element') + ' pinned to output "'
                 + n.sinkId + '" - put it back on the system default');
        try { n.setSinkId(''); } catch (err) { /* it keeps the old sink */ }
      }
      return inEvery(panelSinkFn).then(function (answers) {
        var a, b;
        for (a = 0; a < answers.length; a += 1) {
          var list = answers[a].got || [];
          for (b = 0; b < list.length; b += 1) did.push(answers[a].id + ': ' + list[b]);
        }
        if (!did.length) {
          found.push('nothing in this application is pinned to a named output - it '
                     + 'is already playing to the system default');
        }
        return {changed: did.length > 0, did: did, found: found,
                cannot: 'a page cannot change which device Windows calls the default, '
                        + 'cannot see the per-application volume in the Windows volume '
                        + 'mixer, and cannot tell a working speaker from a muted one.'};
      });
    });
  }

  /* ---------------------------------------------------------------
     RUNG 4b - CLAIM THE AIR FOR THIS APPLICATION.
     POST /api/radio/solo {"listener": "<the panel's id>"}

     Only now, and only for the PANEL - never for the shell around it,
     which takes no clips and is the page that caused #1178 by holding
     the air and playing nothing.

     Why it is this far down: releasing (4a) already lets this
     application sound and costs nobody else their sound. Claiming takes
     the tablet's sound away. It is worth doing when something keeps
     re-taking the air - the #1185 fallback loop, four hand-backs in four
     and a half minutes - because then nobody is sounding anyway.

     #1187: the station refuses the exclusive to a device whose row says
     play:false, which is why rung 3 is above this one. When it refuses
     it says so in `why`, and that sentence is shown as it came. */

  function rungClaimAir(ctx) {
    if (!ctx.panelListener) {
      return Promise.resolve({changed: false, did: [],
        found: ['this window has no panel listener id to claim the air with'],
        cannot: 'the air can only be given to a page the station can see'});
    }
    if (ctx.owner === ctx.panelListener) {
      return Promise.resolve({changed: false, did: [],
        found: ['this application already holds the air']});
    }
    return POST('/api/radio/solo', {listener: ctx.panelListener}).then(function (got) {
      if (!got.ok) {
        return {changed: false, did: [],
                found: ['the station refused: ' + got.why]};
      }
      var body = got.body || {};
      if (body.refused) {
        return {changed: false, did: [],
                found: ['the station REFUSED to give this application the air: '
                        + String(body.why || '')],
                cannot: 'a refusal here is the station protecting the house - it is '
                        + 'not a failure of this rung.'};
      }
      ctx.owner = String(body.audio_owner || '');
      return {changed: true,
        did: ['TOOK the air for this application (' + ctx.panelListener + '). '
              + 'Every other page in the house is gagged while this holds it - '
              + 'the tablet included. Click PineTab under "Playing it" to hand it '
              + 'back, or press Pine Box again once the show is out here.'],
        found: ['the station now reports the air held by "' + ctx.owner + '"'],
        cannot: 'holding the air does not make this page play; it only stops the '
                + 'others. #1178 was a page that held it and played nothing.'};
    });
  }

  /* ---------------------------------------------------------------
     RUNG 7 - RELOAD THIS APPLICATION'S PANEL, and nobody else's.

     The station's own verdict for a page that takes clips and starts
     none of them is "only a reload clears that", and its cure key is
     reload_pages - which reloads EVERY page in the house, the tablet
     included, and did not cure this fault on the night of #1178.

     The same cure exists scoped to this application alone: reload the
     controlFrame webview. Same effect on this page, no effect on
     anybody else's. It costs the panel its listener id (a new one is
     minted on load, which is the #1178 trap for the station's deaf-rest
     but harmless here) and about six seconds of this window. */

  function rungReloadPanel(ctx) {
    var list = frames();
    var frame = null;
    var i;
    for (i = 0; i < list.length; i += 1) {
      if (list[i].id === 'controlFrame') frame = list[i];
    }
    if (!frame) frame = list.length ? list[0] : null;
    if (!frame || typeof frame.reload !== 'function') {
      return Promise.resolve({changed: false, did: [],
        found: ['there is no panel webview in this window to reload']});
    }
    try { frame.reload(); } catch (err) {
      return Promise.resolve({changed: false, did: [],
        found: ['the panel refused to reload: ' + String((err && err.message) || err)]});
    }
    return wait(6000).then(function () {
      return inEvery(panelProbeFn).then(function (probes) {
        var mine = pick(probes, 'controlFrame');
        ctx.panel = mine ? mine.got : null;
        ctx.panelListener = ctx.panel ? String(ctx.panel.listener || '') : '';
        return {changed: true,
          did: ['reloaded THIS application panel and nobody else - the station '
                + 'names a reload as the cure for a page that takes clips and '
                + 'never starts them, and this is that cure with the blast radius '
                + 'of one window'],
          found: [ctx.panelListener
            ? ('the panel came back as ' + ctx.panelListener)
            : 'the panel has not reported a listener id yet - give it a moment'],
          cannot: 'a reload cannot fix a station that is sending nothing.'};
      });
    });
  }

  /* ---------------------------------------------------------------
     RUNG 8 - RELOAD EVERY PAGE.  POST /api/broadcast/reload-pages

     Last, and only last. It reloads the tablet and every browser tab in
     the house as well as this one, and on the night of #1178 it did not
     cure the fault - the fault was the air, not the pages. It is here
     because it is occasionally right and because the alternative below
     it is the restart the operator explicitly put on the other button. */

  function rungReloadEverything() {
    return POST('/api/broadcast/reload-pages', {}).then(function (got) {
      if (!got.ok) {
        return {changed: false, did: [],
                found: ['the station refused: ' + got.why]};
      }
      return {changed: true,
        did: ['asked EVERY page in the house to reload itself - this window, the '
              + 'tablet and any browser tab. They come back within a few seconds.'],
        found: [String((got.body && got.body.say) || '')],
        cannot: 'this is the last rung. Anything past it is restarting the station, '
                + 'which is the mark beside these words, not this ladder.'};
    });
  }

  /* ---------------------------------------------------------------
     THE LADDER, in order. Local and free first, this device next, the
     house last - so the cheapest thing that can possibly be the fault
     is always tried before the most expensive, and nothing anybody else
     can hear is touched until everything in this window has been. */

  var RUNGS = [
    {key: 'look', label: 'Is anything wrong?', run: rungLook,
     why: 'reads the station and probes inside this window; changes nothing'},
    {key: 'own', label: 'This application own audio', run: rungOwnAudio,
     why: 'resumes the audio graph, lifts this app own mutes, puts the volume back'},
    {key: 'loud', label: 'The out-loud switch for this device', run: rungOutLoud,
     why: 'settings.json terminals.<row>.play - silence by construction when false'},
    {key: 'release', label: 'Let go of the air', run: rungReleaseAir,
     why: 'releases the exclusive so every page, this one included, may sound'},
    {key: 'unwedge', label: 'Unstick the delivery', run: rungUnwedge,
     why: 'flushes the page feed at the station - costs the clip being held'},
    {key: 'device', label: 'The output device', run: rungOutputDevice,
     why: 'puts anything pinned to a named output back on the system default'},
    {key: 'claim', label: 'Take the air for this application', run: rungClaimAir,
     why: 'gags every other page for this one - the tablet included'},
    {key: 'panel', label: 'Reload this application panel', run: rungReloadPanel,
     why: 'the station cure for a page that never starts a clip, scoped to this window'},
    {key: 'pages', label: 'Reload every page in the house', run: rungReloadEverything,
     why: 'the tablet and every browser tab too - last, and it did not cure #1178'}
  ];

  /* ---------------------------------------------------------------
     THE VERDICT.

     "a plain verdict at the end - sound is coming out of this
     application, or the most specific honest sentence available".

     Ordered most specific first, and every branch is reached by a
     MEASUREMENT. There is no branch here that can only print one
     answer. */

  function verdictOf(ctx) {
    var proof = ctx.proof || {moving: [], silentMoving: [], asleep: [], graphs: []};
    var tone = ctx.tone || {};
    var after = ((ctx.after || {}).triage || {}).listeners || {};
    var row = after[ctx.panelListener] || null;
    var playedNow = row ? num(row.played) : 0;
    var playedWas = ctx.baseline ? num(ctx.baseline.played) : 0;
    var station = String((ctx.after && ctx.after.say) || (ctx.health && ctx.health.say) || '');
    var i;

    if (proof.sound) {
      var m = proof.moving[0];
      return {good: true, say: 'Sound is coming out of this application.',
        because: 'the ' + m.live + ' element advanced ' + m.advanced
                 + 's at volume ' + Math.round(m.volume * 100) + '% with the panel '
                 + 'audio graph running'
                 + (playedNow > playedWas
                    ? ', and the station recorded ' + (playedNow - playedWas)
                      + ' clip(s) played by this application while the ladder ran'
                    : '')};
    }
    if (proof.moving.length && proof.asleep.length) {
      return {good: false,
        say: 'The show is playing in this application and its audio graph is asleep, '
             + 'so nothing is leaving the machine.',
        because: 'a live element advanced but window.pineAudioCtx is "'
                 + proof.asleep[0].state + '". The station cannot see this: the '
                 + 'acknowledgement carries the element volume and mute flag, and '
                 + 'both of those are healthy. Click inside the panel once, or press '
                 + 'Pine Box again - resuming a context needs a gesture in that page.'};
    }
    if (proof.silentMoving.length) {
      var s = proof.silentMoving[0];
      return {good: false,
        say: 'The station is sending, this application is playing it, and it is '
             + 'silenced in here.',
        because: 'the ' + (s.live || s.id) + ' element advanced ' + s.advanced
                 + 's while it was ' + (s.muted ? 'muted' : 'at zero volume')
                 + (s.gagged ? ' by the solo gate - another page holds the air' : '')};
    }
    if (ctx.outputs !== null && ctx.outputs !== undefined && !ctx.outputs.length) {
      return {good: false,
        say: 'Windows is offering this application no audio output device at all.',
        because: 'enumerateDevices returned no audiooutput. No rung on this ladder '
                 + 'can produce a sound until Windows has an output again.'};
    }
    if (tone.ok) {
      return {good: false,
        say: 'This application can make a sound, and the show is not playing in it.',
        because: tone.why + ' Nothing in this window advanced a frame of broadcast '
                 + 'audio while the ladder watched. ' + (station ? ('The station says: '
                 + station) : '')};
    }
    if (tone.why) {
      return {good: false,
        say: 'No audio is leaving this application at all.',
        because: tone.why + ' That is this application or this machine, not the '
                 + 'station: ' + (station || 'the station is answering normally') + '.'};
    }
    /* THE LAST BRANCH IS NOT A SHRUG. It is reached when the tone could
       not be taken at all, and it says which reading is missing rather
       than pretending to a verdict it has not earned. */
    var fault = String((((ctx.after || {}).triage) || {}).why || '');
    return {good: false,
            say: 'I could not prove sound from this application either way.',
            because: proof.why + ', and the test tone could not be taken. '
                     + (fault ? ('The station names the fault: ' + fault + '. ') : '')
                     + (station ? ('The station says: ' + station) : '')};
  }

  /* ---------------------------------------------------------------
     THE DRIVER.

     One rung at a time, in order, and it STOPS AT THE FIRST RUNG THAT
     PRODUCES PROVED SOUND. A rung that changed nothing is not worth a
     1.2 second proof, so the proof is taken after a rung that changed
     something - or after a rung that asks for one, which is rung 1,
     because rung 1 changing nothing is precisely when the answer might
     already be "there is nothing wrong". */

  var running = false;

  function blank(rung) {
    return {key: rung.key, label: rung.label, why: rung.why, state: 'running',
            did: [], found: [], cannot: '', proof: ''};
  }

  function finish(ctx, opts) {
    return proveSound(opts.gap).then(function (proof) {
      ctx.proof = proof;
      if (opts.tone === false) return null;
      return toneTest(opts.toneMs);
    }).then(function (tone) {
      ctx.tone = tone;
      return GET('/api/broadcast/console');
    }).then(function (got) {
      ctx.after = (got.ok && got.body) || {};
      ctx.verdict = verdictOf(ctx);
      ctx.done = true;
      ctx.ms = deps().now() - ctx.at;
      paint(ctx);
      return ctx;
    });
  }

  function run(options) {
    var opts = options || {};
    var ctx = {at: deps().now(), lines: [], done: false, stoppedAt: '',
               verdict: null, proof: null, tone: null};
    var i = 0;
    var only = opts.only || null;     /* for the harness: run these keys */

    var step = function () {
      if (i >= RUNGS.length) return finish(ctx, opts);
      var rung = RUNGS[i];
      i += 1;
      if (only && only.indexOf(rung.key) < 0) return step();
      var line = blank(rung);
      ctx.lines.push(line);
      paint(ctx);
      var going;
      try { going = Promise.resolve(rung.run(ctx, line)); }
      catch (err) { going = Promise.reject(err); }
      return going.then(function (got) {
        got = got || {};
        line.did = got.did || [];
        line.found = got.found || [];
        line.cannot = got.cannot || '';
        line.state = got.changed ? 'changed' : 'looked';
        paint(ctx);
        if (!got.changed && !got.prove) return step();
        return proveSound(opts.gap).then(function (proof) {
          ctx.proof = proof;
          line.proof = proof.why;
          line.state = proof.sound ? 'proved' : line.state;
          paint(ctx);
          if (!proof.sound) return step();
          ctx.stoppedAt = rung.key;
          return finish(ctx, opts);
        });
      }, function (err) {
        line.state = 'failed';
        line.cannot = 'this rung threw: ' + String((err && err.message) || err);
        paint(ctx);
        return step();
      });
    };

    if (running && !opts.force) {
      return Promise.resolve({busy: true,
        verdict: {good: false, say: 'the ladder is already running'}});
    }
    running = true;
    return step().then(function (done) {
      running = false;
      return done;
    }, function (err) {
      running = false;
      ctx.done = true;
      ctx.verdict = {good: false,
        say: 'the ladder itself failed: ' + String((err && err.message) || err),
        because: 'that is a fault in this file, not in the station'};
      paint(ctx);
      return ctx;
    });
  }

  /* ---------------------------------------------------------------
     THE PANEL the operator watches while it runs.

     One line per rung: what it FOUND, what it CHANGED, and what it
     cannot prove. The same dark glass as the clip doctor and the talk
     dot transcript, so it reads as the station explaining itself.

     Ducking: this is a diagnostic surface, so the broadcast steps back
     to 10% while it is open - PineDuck.hold(name, PineDuck.REPORT, el),
     tied to the box so a sheet torn out without closing still gives the
     sound back. */

  var box = null;
  var back = null;

  function node(tag, cls, text) {
    var d = deps().doc;
    var n = d.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function build() {
    var d = deps().doc;
    if (!d || !d.body || back) return back;
    back = node('div', 'pr-back');
    back.id = 'pineReviveBack';
    box = node('div', 'pr-box');
    var bar = node('div', 'pr-bar');
    bar.appendChild(node('b', '', 'Pine Box'));
    bar.appendChild(node('span', '', 'getting the sound back into this application'));
    var x = node('button', 'pr-x', '×');
    x.title = 'Close. The ladder keeps running if it has not finished.';
    x.onclick = close;
    bar.appendChild(x);
    box.appendChild(bar);
    box.appendChild(node('div', 'pr-verdict', 'working...'));
    box.appendChild(node('ol', 'pr-rungs'));
    var foot = node('div', 'pr-foot');
    var again = node('button', 'pr-again', 'Run it again');
    again.onclick = function () { run({force: true}); };
    foot.appendChild(again);
    foot.appendChild(node('span', 'pr-ms', ''));
    box.appendChild(foot);
    back.appendChild(box);
    d.body.appendChild(back);
    back.onclick = function (event) { if (event.target === back) close(); };
    return back;
  }

  function paint(ctx) {
    if (!back || !box) return;
    var list = box.querySelector('.pr-rungs');
    var verdict = box.querySelector('.pr-verdict');
    var ms = box.querySelector('.pr-ms');
    if (!list || !verdict) return;
    list.replaceChildren();
    var i, j;
    for (i = 0; i < ctx.lines.length; i += 1) {
      var line = ctx.lines[i];
      var item = node('li', 'pr-rung pr-' + line.state);
      item.appendChild(node('b', '', line.label));
      /* What the rung is FOR, in its own words, so the sheet explains the
         ladder as it climbs it rather than needing this file open. */
      if (line.why) item.appendChild(node('p', 'pr-why', line.why));
      for (j = 0; j < line.did.length; j += 1) {
        item.appendChild(node('p', 'pr-did', line.did[j]));
      }
      for (j = 0; j < line.found.length; j += 1) {
        item.appendChild(node('p', 'pr-found', line.found[j]));
      }
      if (line.proof) item.appendChild(node('p', 'pr-proof', 'proof: ' + line.proof));
      if (line.cannot) item.appendChild(node('p', 'pr-cannot', 'cannot prove: ' + line.cannot));
      list.appendChild(item);
    }
    if (ctx.verdict) {
      verdict.className = 'pr-verdict' + (ctx.verdict.good ? ' good' : '');
      verdict.replaceChildren();
      verdict.appendChild(node('div', 'pr-say', ctx.verdict.say));
      if (ctx.verdict.because) {
        verdict.appendChild(node('div', 'pr-because', ctx.verdict.because));
      }
    } else {
      verdict.className = 'pr-verdict';
      verdict.textContent = 'working through the ladder - it stops at the first '
        + 'rung that proves sound...';
    }
    if (ms) {
      ms.textContent = ctx.done
        ? ((ctx.stoppedAt ? ('stopped at "' + ctx.stoppedAt + '" - ') : 'ran every rung - ')
           + Math.round(num(ctx.ms) / 100) / 10 + 's')
        : '';
    }
  }

  function open() {
    var made = build();
    if (!made) return run({});
    made.classList.add('show');
    try {
      if (root.PineDuck) root.PineDuck.hold('pine-revive', root.PineDuck.REPORT, box);
    } catch (err) { /* the ladder matters more than the duck */ }
    return run({});
  }

  function close() {
    if (back) back.classList.remove('show');
    try { if (root.PineDuck) root.PineDuck.release('pine-revive'); }
    catch (err) { /* fine */ }
  }

  /* ---------------------------------------------------------------
     THE WIRING, and the one thing it must never do.

     The words "Pine Box" are this ladder. The MARK beside them is
     #1044 - deploy app.py to the box, collapse, rebuild and relaunch -
     and it keeps doing exactly that. The operator drew the line himself:
     "short of restarting the server, which is what the icon is for".

     So this attaches to #brandTitle and to nothing else. It does not
     touch #panicBtn, it does not touch renderer.js, and it stops the
     click from reaching anything behind it. */

  function wire() {
    var title = el('brandTitle');
    if (!title || title.dataset.pineRevive === '1') return false;
    title.dataset.pineRevive = '1';
    title.onclick = function (event) {
      try { event.preventDefault(); event.stopPropagation(); } catch (err) { /* fine */ }
      open();
    };
    title.onkeydown = function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      try { event.preventDefault(); } catch (err) { /* fine */ }
      open();
    };
    return true;
  }

  function start() {
    if (wire()) return;
    var d = deps().doc;
    if (!d) return;
    if (d.readyState === 'loading') {
      d.addEventListener('DOMContentLoaded', function () { wire(); });
    } else {
      setTimeout(wire, 250);
    }
  }

  root.PineRevive = {
    run: run,
    open: open,
    close: close,
    wire: wire,
    RUNGS: RUNGS,
    /* Everything below is for proving this file works without a debugging
       port on the machine it runs on: hand it a stub world and drive it. */
    _deps: function (world) { DEPS = world || null; return DEPS; },
    _rungKeys: function () {
      var out = [];
      for (var i = 0; i < RUNGS.length; i += 1) out.push(RUNGS[i].key);
      return out;
    },
    _compareProbes: compareProbes,
    _rowFor: rowFor,
    _verdictOf: verdictOf
  };

  try { start(); } catch (err) { /* a desk without a title still works */ }

  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineRevive;
})(typeof window !== 'undefined' ? window : globalThis);
