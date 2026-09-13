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
      var saved = Number(localStorage.getItem('pineMusicVolume'));
      return Number.isFinite(saved) ? clamp(saved) : 1;
    } catch (err) { return 1; }
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

  root.PineAudioLaw = {
    localMix: localMix,
    setLocalMix: setLocalMix,
    localMixRange: localMixRange,
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
