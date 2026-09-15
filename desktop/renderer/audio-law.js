/* ONE PLACE THE AUDIO IS SET. THE DRAWER IS THE LAW.
 *
 * "I need all the audio settings unified across the app with these tabs. I
 * need to set the audio in the slide out and set it as law."
 *
 * There were FOUR desks, and that is why nothing agreed:
 *
 *   1. the native drawer      POST /api/dj/output {"music_level": 0.35}
 *                             - a STATION level, heard by every listener
 *   2. the Listen popover     moved djGainMusic / djGainVoice
 *                             - the PANEL's own gain, this browser only
 *   3. the panel's desk       the same two sliders, from the other side
 *   4. localStorage           pineMusicVolume / pineMusicMuted
 *                             - the element's own level, this browser only
 *
 * Two of those are station-wide and two are local, and nothing said which
 * was which - so setting a level in one place appeared to do nothing, or to
 * come undone a moment later. The drawer's values are the ones the operator
 * has been treating as real, so they are the law and this is the only door
 * to them.
 *
 * THE DIVISION, stated once so every view can stop guessing:
 *
 *   STREAM LEVELS (music / voice / reply)  -> the station, for everyone.
 *       Written as {"<stream>_level": 0..1} to /api/dj/output, which is
 *       exactly what the drawer sends (DjOutput.level).
 *
 *   STREAM ROUTES (app / box / both / off) -> the station, for everyone.
 *       {"<stream>": "here|box|both|off|nabu"} - DjOutput.stream.
 *
 *   THIS TERMINAL'S OWN VOLUME                -> local, this device only.
 *       The panel player's level, remembered in pineMusicVolume. The
 *       drawer calls it "Heard in this app" and says plainly that it lives
 *       in browser storage - that wording is kept here.
 *
 * READING BACK IS HONEST ABOUT ITS LIMITS. The station only publishes
 * levels on /api/dj when the broadcast device is the Nabu
 * (nabu_music_level and friends); for a Pine Box the equivalent lives in
 * settings and is not on /api/dj at all. So a level that cannot be read is
 * reported as the last value THIS terminal sent, marked as such, rather
 * than shown as though it had been confirmed.
 */
(function (root) {
  'use strict';

  var STREAMS = ['music', 'voice', 'reply'];
  var SENT_KEY = 'pineAudioLawSent';

  function api() {
    return root.pineDesktop || {
      get: function () { return Promise.reject(new Error('no bridge')); },
      post: function () { return Promise.reject(new Error('no bridge')); }
    };
  }

  function clamp(v) {
    var n = Number(v);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(1, n));
  }

  /* What this terminal last sent, so a level the station will not publish
   * can still be shown rather than snapping back to a default. */
  function sent() {
    try { return JSON.parse(localStorage.getItem(SENT_KEY) || '{}'); }
    catch (err) { return {}; }
  }
  function remember(stream, level) {
    var was = sent();
    was[stream] = level;
    try { localStorage.setItem(SENT_KEY, JSON.stringify(was)); }
    catch (err) { /* a locked store must not stop the desk */ }
  }

  /* ---- reading ------------------------------------------------------- */

  /* One stream's level, and where the number came from. */
  function levelOf(state, stream) {
    var s = state || {};
    /* The station's own, when it publishes one. */
    var keys = [stream + '_level', 'nabu_' + stream + '_level'];
    for (var i = 0; i < keys.length; i += 1) {
      var v = s[keys[i]];
      if (v === undefined || v === null) continue;
      var n = Number(v);
      if (!Number.isFinite(n)) continue;
      /* The station speaks in 0..1 on some keys and 0..100 on others. */
      return {level: clamp(n > 1 ? n / 100 : n), from: 'station'};
    }
    var mine = sent()[stream];
    if (mine !== undefined) return {level: clamp(mine), from: 'this terminal'};
    return {level: null, from: 'unset'};
  }

  function routeOf(state, stream) {
    return String((state || {})[stream + '_to'] || '');
  }

  /* ---- writing ------------------------------------------------------- */

  /* Set a stream's level for EVERYONE. The same body the drawer sends, to
   * two decimal places - a drag that posts 0.3499999 and then 0.35 is two
   * writes to a speaker for one thumb movement. */
  function setLevel(stream, level) {
    if (STREAMS.indexOf(stream) < 0) {
      return Promise.reject(new Error('no such stream: ' + stream));
    }
    var value = Math.round(clamp(level) * 100) / 100;
    var body = {};
    body[stream + '_level'] = value;
    remember(stream, value);
    return api().post('/api/dj/output', body).then(function (answer) {
      return {ok: true, stream: stream, level: value, state: answer};
    });
  }

  /* Send a stream somewhere. */
  function setRoute(stream, route) {
    if (STREAMS.indexOf(stream) < 0) {
      return Promise.reject(new Error('no such stream: ' + stream));
    }
    var body = {};
    body[stream] = String(route);
    return api().post('/api/dj/output', body).then(function (answer) {
      return {ok: true, stream: stream, route: route, state: answer};
    });
  }

  /* Talk only: the music stops being BROADCAST, rather than being muted
   * here. That is the difference the operator asked for - "I'm playing my
   * own music" means the station should not be sending any. */
  function talkOnly(on, state) {
    if (on) return setRoute('music', 'off');
    /* Back to wherever the DJs are going, not a guess at "here": if the
     * show is on the box, the music belongs on the box. */
    var back = routeOf(state, 'voice') || 'here';
    return setRoute('music', back);
  }

  function isTalkOnly(state) {
    return routeOf(state, 'music') === 'off'
      && routeOf(state, 'voice') !== 'off';
  }

  /* ---- this terminal only -------------------------------------------- */

  /* The panel player's own level. The drawer calls this "Heard in this
   * app" and says where it lives; the same words are used wherever this is
   * shown, so two screens never describe one control differently. */
  var LOCAL_WHY = 'This terminal only - it lives in this browser, not on '
    + 'the station.';

  function localVolume() {
    var el = document.getElementById('musicPlayer');
    if (el) return clamp(el.volume);
    try {
      /* #1194: A STORE WITH NOTHING IN IT IS NOT A LEVEL OF ZERO.
       *
       * getItem returns null when this terminal has never written the key,
       * Number(null) is 0, and Number.isFinite(0) is true - so the "or 1"
       * fallback below could never be reached and this returned 0. On the
       * desk nothing writes pineMusicVolume into the SHELL's store (the
       * injected appVolumeScript writes it inside the panel, which is a
       * different origin and a different store), so HERE read 0% on a
       * screen playing music at full level: unread, not silent. Measured
       * 2026-09-15 against the operator's screenshot, which showed
       * HERE 0% while the station was audible. */
      var raw = localStorage.getItem('pineMusicVolume');
      if (raw === null || raw === undefined || String(raw).trim() === '') return null;
      var saved = Number(raw);
      return Number.isFinite(saved) ? clamp(saved) : null;
    } catch (err) { return null; }
  }

  function setLocalVolume(level) {
    var want = clamp(level);
    var touched = 0;
    var nodes = document.querySelectorAll('audio, video');
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      /* A pad is the operator's own hands, never the broadcast. */
      if (node.closest && node.closest('#sampler, .pb-sampler')) continue;
      if (node.id === 'musicPlayer') { node.volume = want; touched += 1; }
    }
    try { localStorage.setItem('pineMusicVolume', String(want)); }
    catch (err) { /* locked */ }
    return touched;
  }

  /* ---------------------------------------------------------------------
     THIS TERMINAL'S OWN MIX - music against voices, in this room only.

     "I am trying to adjust the volume of just the music so that way I can
      hear the DJs better or hear the clips more and it is not letting me."

     There are TWO desks in this house and they are not the same desk:

       THE STATION'S   <stream>_level, written through /api/dj/output and
                       heard by every listener. That is a broadcast decision.
       THIS BROWSER'S  djGainMusic / djGainVoice / djDuck, read by djLevels()
                       and applied by djApplyGain(). A monitoring decision -
                       it changes what comes out of THIS device and nothing
                       else.

     "So I can hear the DJs better" is the second one. The Listen desk said
     so on its own face - "This terminal only" - and then called setLevel,
     which is the first one. Worse, the station only publishes per-stream
     levels when the broadcast device is the Nabu, so on this tablet the read
     came back null, every knob sat at 50 marked "not set", and moving one
     appeared to do nothing. Measured: the desk reading 50/50/50 while the
     real mix was music 100%, djs 160%.

     These are PERCENTAGES, not fractions, because that is what the panel's
     own sliders are and what its label shows. 100 is unity. */

  var LOCAL_GAIN = {
    music: {id: 'djGainMusic', fallback: 100},
    voice: {id: 'djGainVoice', fallback: 160},
    reply: {id: 'djGainVoice', fallback: 160},   /* replies ride the voice bus */
    duck: {id: 'djDuck', fallback: 70}
  };

  function gainNode(stream) {
    var spec = LOCAL_GAIN[stream];
    if (!spec || typeof document === 'undefined') return null;
    return document.getElementById(spec.id);
  }

  /** The panel's own gain for a stream, as a percentage, or null when this
   *  page has no panel behind it - the desktop renderer, which runs from
   *  file:// and has no djGain sliders of its own. */
  function localMix(stream) {
    var node = gainNode(stream);
    if (!node) return null;
    var value = Number(node.value);
    return isFinite(value) ? value : (LOCAL_GAIN[stream] || {}).fallback;
  }

  function localMixRange(stream) {
    var node = gainNode(stream);
    if (!node) return {min: 0, max: 200};
    return {min: Number(node.min) || 0, max: Number(node.max) || 200};
  }

  /**
   * Move this terminal's mix and make it audible NOW.
   *
   * The panel applies gain from these sliders through djApplyGain, so the
   * value is written AND the event fired - a value set without the event is
   * a slider that moved and a sound that did not.
   */
  function setLocalMix(stream, percent) {
    var node = gainNode(stream);
    if (!node) return false;
    var range = localMixRange(stream);
    var want = Math.max(range.min, Math.min(range.max, Math.round(Number(percent) || 0)));
    node.value = String(want);
    try { node.dispatchEvent(new Event('input', {bubbles: true})); } catch (err) { /* old */ }
    try { node.dispatchEvent(new Event('change', {bubbles: true})); } catch (err) { /* old */ }
    /* Belt and braces: the panel wires these, but if a build ever stops
     * listening the mix must still move. djApplyGain is idempotent. */
    if (typeof root.djApplyGain === 'function') {
      try { root.djApplyGain(); } catch (err) { /* not fatal */ }
    }
    return true;
  }

  /* ---------------------------------------------------------------------
     #1194: THE DESK IS TWO DOCUMENTS, AND THE MIX LIVES IN THE OTHER ONE.

     "Honor the sliders that I'm setting in the Pine box application, these
      are intended to be mixing the signal that I'm listening to."

     MEASURED, 2026-09-15, before a line of this was written:

       desktop/renderer/index.html  ...  djGainMusic / djGainVoice / djDuck
                                         occur ZERO times. No #musicPlayer
                                         either. The shell has one level of
                                         its own, #appVolume (index.html:324).
       app.py (the panel)           ...  djGainMusic (163451, 0-600, 100),
                                         djGainVoice (163458, 0-600, 160),
                                         djDuck (163467, 0-90, 70), and the
                                         one #musicPlayer on the station.

     The shell embeds the panel as <webview id="controlFrame">
     (index.html:542) and a webview is a SEPARATE DOCUMENT in a separate
     renderer process. So gainNode() above - document.getElementById in THIS
     document - returns null on the desk for all three, setLocalMix returns
     false, and the drawer printed "(no desk here)" on a screen that was
     plainly playing music. On the tablet the same file works because the
     kiosk injects these modules INTO the panel: there the sliders and the
     gain nodes share one window and the direct write is right.

     WHICH CONTROL EACH ROW ACTUALLY MOVES, read out of the panel rather
     than guessed (app.py djLevels:180200, djApplyGain:180265):

       MUSIC  djGainMusic -> djApplyGain puts it on a real GainNode over the
              panel's musicPlayer:
                 target = level.music * (speaking ? 1 - duck : 1) * mixer.music
              A gain STAGE, not an element volume - so it still works inside
              the desktop shell, which owns element volume but not the
              panel's audio graph. This is the road for MUSIC.

       DJS    djGainVoice -> djApplyGain writes djVoiceEls[i].volume, and
              app.py:180297 guards that write with
                 window.__pineDesktopVolume === undefined
              i.e. NOT INSIDE THE DESKTOP SHELL (#1147: one owner - the
              shell's injected appVolumeScript rewrites every live element's
              volume within a second, so the panel's slider only made the
              level flutter twice per clip). Writing djGainVoice from here
              on the desk would move a number and no sound. The shell's own
              per-listener voice level is window.pineMixer (renderer.js:199),
              which appVolumeScript multiplies into every element tagged
              data-pine-live="voice". That is the road for DJS on the desk.

       DUCK   djDuck -> how far the music dips while a DJ is talking, inside
              djApplyGain's music target. Settable, 0-90, and the panel is
              the only place it exists. NOT PineDuck: pine-duck.js is the
              10%-for-reports / 2%-for-dictation hold that ducks this
              terminal while a diagnostic or dictation is open, it is
              reference counted and transient, and nothing about it is a
              depth the operator dials.

     WHAT IT COSTS TO CROSS. executeJavaScript is one IPC round trip per
     frame per call and returns a Promise. A drag on `input` fires per pixel,
     so the writes are COALESCED: every move drops its value into a pending
     map and asks for one flush on the next animation frame, and while a
     flush is in the air further moves only update the map. Two sliders
     moved at once are therefore ONE crossing carrying both values, a
     50-pixel drag is one crossing per round trip rather than 50, and the
     value that lands last is always the one under the thumb. The label is
     written from the slider synchronously, so nothing lags behind the
     finger; only the sound waits on the round trip.

     WHICH WORLD AM I IN? Not a user-agent string and not a build flag: the
     test is the presence of the very element the direct write would move.
     document.getElementById('djGainMusic') is either here - in which case
     writing it IS the right answer, by construction - or it is not, and
     then we look for <webview> nodes carrying a src and a function called
     executeJavaScript, which is an Electron API that exists nowhere else.
     Both tests are about what is actually in the room. */

  var MIX_IDS = {music: 'djGainMusic', voice: 'djGainVoice', duck: 'djDuck'};
  var MIX_CEIL = {music: 200, voice: 200, duck: 90};

  var pendingMix = {};        /* stream -> percent, the thumb's latest */
  var mixInFlight = false;    /* a crossing is in the air */
  var mixScheduled = false;   /* a flush is booked for the next frame */
  var mixReach = {};          /* stream -> true/false, last PROVEN answer */
  var reachWatchers = [];
  var mixSeen = null;         /* the panel's own values, last time we read */
  var mixFrameId = '';        /* the webview that PROVED it has the desk */

  /* Every webview in this document that can be talked to. pine-revive.js
   * walks the same list for the same reason - it proves facts inside the
   * panel rather than guessing them from the shell. */
  function panelFrames() {
    var out = [];
    if (typeof document === 'undefined' || !document.querySelectorAll) return out;
    var all;
    try { all = document.querySelectorAll('webview'); } catch (err) { return out; }
    for (var i = 0; i < all.length; i += 1) {
      var f = all[i];
      if (!f || !f.src) continue;
      if (typeof f.executeJavaScript !== 'function') continue;
      out.push(f);
    }
    /* THE ONE THAT ANSWERED LAST GOES FIRST, THEN THE CONTROL FRAME.
     * This window has five webviews (control, radio, system2, guide,
     * slides) and only one of them is the station panel. Reading the wrong
     * one would report "no desk here" while the desk was two elements away,
     * and writing all five would spend four round trips on documents that
     * have never heard of djGainMusic. So the frame that last proved it has
     * the controls is tried first, and controlFrame - which is the one that
     * carries the broadcast on the Application route - before the rest. */
    out.sort(function (a, b) { return rank(a) - rank(b); });
    return out;
  }

  function rank(frame) {
    var id = String(frame.id || '');
    if (mixFrameId && id === mixFrameId) return 0;
    if (id === 'controlFrame') return 1;
    return 2;
  }

  /* The shell's own listener mixer, when this document is the shell. */
  function shellMixer() {
    var m = root.pineMixer;
    if (m && typeof m.set === 'function' && typeof m.get === 'function') return m;
    return null;
  }

  /* 'local'  - the gain slider is in this document; write it (the tablet).
   * 'panel'  - it is behind a webview; cross to it.
   * 'shell'  - the shell's own mixer is the only thing the ear obeys here.
   * ''       - no desk here, and the label must say so. */
  function mixRoad(stream) {
    if (!MIX_IDS[stream]) return '';
    if (gainNode(stream)) return 'local';
    var frames = panelFrames();
    if (!frames.length) return '';
    /* #1147 again: inside the shell the panel's voice slider is inert, so
     * DJS is the shell's mixer or it is nothing. Music and duck are the
     * panel's, because a gain stage and a duck depth are not element
     * volume and the shell never touches them. */
    if (stream === 'voice') return shellMixer() ? 'shell' : '';
    return 'panel';
  }

  function mixMax(stream) {
    var road = mixRoad(stream);
    /* pineMixer clamps a multiplier to 1.5 and the injected script caps a
     * live element at the master level, so a DJS knob past 150 would be a
     * knob with dead travel on it. Say 150 rather than pretend 200. */
    if (road === 'shell') return 150;
    if (road === 'local') return Math.min(localMixRange(stream).max, MIX_CEIL[stream]);
    return MIX_CEIL[stream];
  }

  function mixPercent(stream, value) {
    var n = Math.round(Number(value) || 0);
    if (n < 0) n = 0;
    var top = mixMax(stream);
    return n > top ? top : n;
  }

  function soon(fn) {
    if (typeof root.requestAnimationFrame === 'function') {
      try { root.requestAnimationFrame(fn); return; } catch (err) { /* below */ }
    }
    setTimeout(fn, 16);
  }

  function tellReach() {
    var snapshot = {};
    for (var k in mixReach) {
      if (Object.prototype.hasOwnProperty.call(mixReach, k)) snapshot[k] = mixReach[k];
    }
    for (var i = 0; i < reachWatchers.length; i += 1) {
      try { reachWatchers[i](snapshot); }
      catch (err) { /* a painter must not stop the sound */ }
    }
  }

  /* Stringified and evaluated INSIDE the panel; it closes over nothing in
   * this file. It moves the slider AND fires `input`, because the panel
   * wires its gains as oninput="djApplyGain()" - a value set without the
   * event is a slider that moved and a sound that did not - and then calls
   * djApplyGain once more, which is idempotent, in case a build ever stops
   * listening. */
  function panelMixSource(want) {
    /* Only the ids being written go over: a crossing that mentions
     * djGainVoice would read like the desk moves it, and on the desk it
     * does not (#1147). */
    var ids = {};
    for (var k in want) {
      if (Object.prototype.hasOwnProperty.call(want, k) && MIX_IDS[k]) ids[k] = MIX_IDS[k];
    }
    return '(function(){'
      + 'var w=' + JSON.stringify(want) + ';'
      + 'var ids=' + JSON.stringify(ids) + ';'
      + 'var hit={},shell=false;'
      + 'try{shell=(window.__pineDesktopVolume!==undefined);}catch(e0){}'
      + 'Object.keys(w).forEach(function(k){'
      + 'var el=document.getElementById(ids[k]);'
      + 'if(!el){hit[k]=false;return;}'
      + 'el.value=String(w[k]);hit[k]=true;'
      + 'try{el.dispatchEvent(new Event("input",{bubbles:true}));}catch(e1){}'
      + '});'
      + 'try{if(typeof djApplyGain==="function")djApplyGain();}catch(e2){}'
      + 'return {hit:hit,shell:shell};})()';
  }

  function panelReadSource() {
    return '(function(){'
      + 'var ids=' + JSON.stringify(MIX_IDS) + ';'
      + 'var out={shell:false,here:null};'
      + 'try{out.shell=(window.__pineDesktopVolume!==undefined);}catch(e0){}'
      + 'Object.keys(ids).forEach(function(k){'
      + 'var el=document.getElementById(ids[k]);'
      + 'out[k]=el?Number(el.value):null;});'
      + 'try{var p=document.getElementById("musicPlayer");'
      + 'if(p)out.here=Number(p.volume);}catch(e1){}'
      + 'return out;})()';
  }

  function runIn(frame, source) {
    var going;
    try { going = frame.executeJavaScript(source); }
    catch (err) { return Promise.resolve(null); }
    if (!going || typeof going.then !== 'function') return Promise.resolve(going || null);
    /* A panel that reloaded under the drawer rejects here. That is an
     * answer - "not reached" - not a crash. */
    return going.then(function (v) { return v; }, function () { return null; });
  }

  function flushMix() {
    mixScheduled = false;
    if (mixInFlight) return;                 /* it will re-flush on the way out */
    var want = pendingMix;
    pendingMix = {};
    var streams = Object.keys(want);
    if (!streams.length) return;

    var jobs = [];
    var toPanel = {};
    var panelStreams = 0;
    var stream;
    for (var i = 0; i < streams.length; i += 1) {
      stream = streams[i];
      var road = mixRoad(stream);
      if (road === 'local') {
        mixReach[stream] = setLocalMix(stream, want[stream]);
        continue;
      }
      if (road === 'shell') {
        var mixer = shellMixer();
        if (!mixer) { mixReach[stream] = false; continue; }
        var values = {};
        /* The shell speaks in multipliers where 1 is unity; the drawer
         * speaks in percent where 100 is unity. One conversion, here. */
        values[stream] = want[stream] / 100;
        try { mixer.set(values); mixReach[stream] = true; }
        catch (err) { mixReach[stream] = false; }
        continue;
      }
      if (road === 'panel') { toPanel[stream] = want[stream]; panelStreams += 1; continue; }
      mixReach[stream] = false;
    }

    var sent = [];
    if (panelStreams) {
      var frames = panelFrames();
      var source = panelMixSource(toPanel);
      /* Once one frame has proved it holds the desk, it is the only one
       * written to - a drag costs ONE crossing, not one per webview. If it
       * ever stops answering (the panel navigated, the operator opened a
       * different page in it) the next flush goes wide again. */
      if (mixFrameId && frames.length && String(frames[0].id || '') === mixFrameId) {
        frames = [frames[0]];
      }
      for (var f = 0; f < frames.length; f += 1) {
        sent.push(frames[f]);
        jobs.push(runIn(frames[f], source));
      }
    }

    if (!jobs.length) { tellReach(); return; }
    mixInFlight = true;
    Promise.all(jobs).then(function (answers) {
      var reached = {};
      var answered = '';
      for (var a = 0; a < answers.length; a += 1) {
        var got = answers[a];
        if (!got || !got.hit) continue;
        for (var k in got.hit) {
          if (!got.hit[k]) continue;
          reached[k] = true;
          if (!answered && sent[a]) answered = String(sent[a].id || '');
        }
      }
      mixFrameId = answered;
      for (var s in toPanel) {
        if (!Object.prototype.hasOwnProperty.call(toPanel, s)) continue;
        mixReach[s] = !!reached[s];
      }
      mixInFlight = false;
      tellReach();
      /* Whatever the thumb did while we were away goes now, and only the
       * last value goes - the drag never queues a tail of stale writes. */
      if (Object.keys(pendingMix).length) scheduleMix();
    });
  }

  function scheduleMix() {
    if (mixScheduled) return;
    mixScheduled = true;
    soon(flushMix);
  }

  /**
   * Move one row of the mixing drawer, wherever its desk happens to be.
   * Returns the road taken, synchronously, so the label can be honest in
   * the same frame: 'local', 'panel', 'shell', or '' for no desk here.
   */
  function setMix(stream, percent) {
    var road = mixRoad(stream);
    if (!road) { mixReach[stream] = false; return ''; }
    var want = mixPercent(stream, percent);
    if (road === 'local') {
      /* The tablet, and the panel in a plain browser: the gain nodes are in
       * this window, so this is a straight write with no crossing and no
       * coalescing to do. Unchanged from the day it worked. */
      mixReach[stream] = setLocalMix(stream, want);
      return mixReach[stream] ? 'local' : '';
    }
    pendingMix[stream] = want;
    scheduleMix();
    return road;
  }

  /** What the panel's own desk says right now. One crossing, and the
   *  answer is cached so a repaint that happens while the drawer is open
   *  has something true to draw before the round trip lands. */
  function readMix() {
    var frames = panelFrames();
    var mixer = shellMixer();
    if (!frames.length) {
      var here = {music: localMix('music'), voice: localMix('voice'),
                  duck: localMix('duck'),
                  road: gainNode('music') ? 'local' : '',
                  voiceRoad: gainNode('voice') ? 'local' : ''};
      mixSeen = here;
      return Promise.resolve(here);
    }
    return runIn(frames[0], panelReadSource()).then(function (got) {
      var out = {music: null, voice: null, duck: null, road: 'panel',
                 voiceRoad: 'panel', shell: !!(got && got.shell)};
      if (got) {
        out.music = (typeof got.music === 'number') ? got.music : null;
        out.duck = (typeof got.duck === 'number') ? got.duck : null;
        out.voice = (typeof got.voice === 'number') ? got.voice : null;
        if (!got.music && got.music !== 0) out.road = '';
      }
      if (!got) out.road = '';
      /* DJS on the desk is the shell's mixer, not that slider (#1147), so
       * the number shown has to come from where the ear's level comes
       * from or the drawer would lie in a new way. */
      if (mixer) {
        var levels = {};
        try { levels = mixer.get() || {}; } catch (err) { levels = {}; }
        var v = Number(levels.voice);
        out.voice = Number.isFinite(v) ? Math.round(v * 100) : null;
        out.voiceRoad = 'shell';
      } else if (out.shell) {
        out.voice = null;                    /* inert there, and say so */
        out.voiceRoad = '';
      }
      mixSeen = out;
      return out;
    });
  }

  /** The last answer, without crossing anything. */
  function mixNow() { return mixSeen; }

  function onMixReach(fn) {
    if (typeof fn !== 'function') return function () {};
    reachWatchers.push(fn);
    return function () {
      for (var i = 0; i < reachWatchers.length; i += 1) {
        if (reachWatchers[i] === fn) { reachWatchers.splice(i, 1); return; }
      }
    };
  }

  function mixReached(stream) {
    return Object.prototype.hasOwnProperty.call(mixReach, stream)
      ? !!mixReach[stream] : null;
  }

  root.PineAudioLaw = {
    localMix: localMix,
    setLocalMix: setLocalMix,
    localMixRange: localMixRange,
    /* #1194: the mix, wherever its desk is - see the long note above. */
    setMix: setMix,
    readMix: readMix,
    mixNow: mixNow,
    mixRoad: mixRoad,
    mixMax: mixMax,
    mixReached: mixReached,
    onMixReach: onMixReach,
    panelFrames: panelFrames,
    STREAMS: STREAMS,
    LOCAL_WHY: LOCAL_WHY,
    levelOf: levelOf, routeOf: routeOf,
    setLevel: setLevel, setRoute: setRoute,
    talkOnly: talkOnly, isTalkOnly: isTalkOnly,
    localVolume: localVolume, setLocalVolume: setLocalVolume,
    clamp: clamp
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineAudioLaw;
})(typeof window !== 'undefined' ? window : globalThis);
