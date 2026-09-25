/* OBEYING THE ROUTING TABLE, IN THE PAGE.
 *
 * terminal-audio.cjs decides WHICH device is the room and at what levels.
 * This is the half that carries it out inside a browser - the tablet's
 * WebView and the desktop's panel run the same file, so they cannot drift.
 *
 * It does not invent an audio path. The panel already has a desk: the
 * djGainMusic / djGainVoice / djDuck sliders, read by djLevels()
 * (app.py:149377) and applied by djApplyGain(), which routes music through
 * a GainNode where one exists and falls back to element volume where it
 * does not. Those sliders are per-browser, remembered in localStorage -
 * which is exactly the independence the operator asked for, and exactly
 * why the desktop could not reach them.
 *
 * So this does not replace the desk. It DRIVES it: the terminals table is
 * the source of truth, this moves the sliders to match, and the panel's own
 * machinery does the rest. Move a slider by hand and the change is written
 * back to your own row, so the desk still works the way it always did.
 *
 * THE CLAMP IS NOT COSMETIC. The voice slider defaults to 160%, and on the
 * tablet the DJs play through a plain <audio> element, whose volume setter
 * THROWS above 1.0:
 *
 *     IndexSizeError: The volume provided (1.6) is outside the range [0, 1]
 *
 * The throw aborted the routine that was setting it, so the DJs were silent
 * on the tablet while music played. The desktop never saw it because its
 * GainNode accepts boost. Clamping the setter fixes it for every element in
 * the page, including ones this file has never heard of.
 */
(function (global) {
  'use strict';

  const STREAMS = ['music', 'voice', 'reply'];
  const POLL_MS = 8000;      /* several looks inside the shared presence lease */

  function clamp(value, fallback) {
    const level = Number(value);
    if (!Number.isFinite(level)) return fallback === undefined ? 1 : fallback;
    return Math.max(0, Math.min(1, level));
  }

  /* ---- the clamp ---------------------------------------------------- */

  let clamped = false;
  function clampMediaVolume() {
    if (clamped) return false;
    const proto = global.HTMLMediaElement && global.HTMLMediaElement.prototype;
    const desc = proto && Object.getOwnPropertyDescriptor(proto, 'volume');
    if (!desc || !desc.set) return false;
    Object.defineProperty(proto, 'volume', {
      configurable: true,
      enumerable: desc.enumerable,
      get: function () { return desc.get.call(this); },
      /* Silently clamping is right here. The caller asked for "as loud as
       * possible and then some"; the element's ceiling IS as loud as
       * possible, and throwing takes the rest of their routine down. */
      set: function (value) { desc.set.call(this, clamp(value, 1)); }
    });
    clamped = true;
    return true;
  }

  /* ---- the desk ------------------------------------------------------ */

  /* The panel's sliders are percentages; the table stores 0..1. */
  const SLIDER = {music: 'djGainMusic', voice: 'djGainVoice'};

  /* Read RAW, not clamped. The voice slider's default is 160%, and clamping
   * on the way in would make 160 and 100 read as the same number - so the
   * table could never pull a boosted slider down, because the desk would
   * always already appear to agree with it. */
  function deskLevels(doc) {
    const out = {};
    for (const stream of STREAMS) {
      const input = doc.getElementById(SLIDER[stream] || '');
      const raw = input ? Number(input.value) / 100 : null;
      out[stream] = Number.isFinite(raw) ? raw : null;
    }
    return out;
  }

  /* Moving the slider is not enough - the panel only reacts to its own
   * input event, and djApplyGain is what actually ramps the GainNode. */
  function setDesk(doc, stream, level) {
    const input = doc.getElementById(SLIDER[stream] || '');
    if (!input) return false;
    const want = String(Math.round(clamp(level) * 100));
    if (input.value === want) return false;
    input.value = want;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }

  /* Silence is a separate lever from level. Setting the sliders to zero
   * would be written back as the operator's chosen levels the moment this
   * device takes the air again, so a quiet device keeps its numbers and is
   * muted at the elements instead. */
  function mute(doc, quiet) {
    let touched = 0;
    const all = doc.querySelectorAll('audio, video');
    for (const element of all) {
      /* The sampler is the operator's own hands on a pad, not the
       * broadcast, and it is never silenced by the routing table. */
      if (element.closest && element.closest('#sampler, .pb-sampler')) continue;
      element.dataset = element.dataset || {};
      if (quiet) {
        if (element.dataset.pineTerminalGag !== '1') {
          element.dataset.pineTerminalWasMuted = element.muted ? '1' : '0';
        }
        if (!element.muted) { element.muted = true; touched += 1; }
        element.dataset.pineTerminalGag = '1';
      } else if (element.dataset.pineTerminalGag === '1') {
        const muted = element.dataset.pineTerminalWasMuted === '1'
          || element.dataset.pineDecor === '1';
        if (element.muted !== muted) { element.muted = muted; touched += 1; }
        delete element.dataset.pineTerminalGag;
        delete element.dataset.pineTerminalWasMuted;
      }
    }
    return touched;
  }

  /* ---- the loop ------------------------------------------------------ */

  function Client(options) {
    const opts = options || {};
    this.id = String(opts.id || 'desktop');
    this.doc = opts.document || global.document;
    this.fetchJson = opts.fetchJson;
    this.decide = opts.decide;          /* terminal-audio.cjs decide() */
    this.update = opts.update;          /* terminal-audio.cjs update() */
    this.pollMs = opts.pollMs || POLL_MS;
    this.onState = opts.onState || function () {};
    this.state = null;
    this.timer = null;
    this.claimed = false;
  }

  /* Announce which row is ours, so a desktop three rooms away can name this
   * device and set its levels. Without a claim the table is a list of
   * strangers. */
  Client.prototype.claim = async function claim(extra) {
    const settings = await this.fetchJson('/api/settings');
    const patch = Object.assign({}, extra || {});
    const row = ((settings || {}).terminals || {})[this.id];
    /* A row that already names itself keeps its name - the operator may
     * have renamed it, and a client overwriting that every poll would make
     * the field unusable. */
    if (!row && !patch.name) patch.name = this.id;
    const out = this.update(settings, this.id, patch);
    if (!out.ok) return out;
    await this.fetchJson('/api/settings', {method: 'PUT', body: out.settings});
    this.claimed = true;
    return out;
  };

  Client.prototype.tick = async function tick() {
    let settings; let roster;
    try {
      settings = await this.fetchJson('/api/settings');
      roster = await this.fetchJson('/api/radio/listeners');
    } catch (error) {
      /* The station being unreachable must NOT silence a device that is
       * already playing - a dropped poll is not an instruction. */
      this.onState({error: error.message, mine: null});
      return null;
    }
    const decision = this.decide(settings, roster);
    const mine = decision.rows[this.id] || null;
    this.state = decision;

    if (mine) {
      const desk = deskLevels(this.doc);
      if (mine.play) {
        for (const stream of STREAMS) {
          if (desk[stream] === null) continue;
          const want = mine.levels[stream];
          /* A slider the operator has just moved by hand wins, and is
           * written back to the table so the desktop sees it. Anything
           * else follows the table. */
          if (Math.abs(desk[stream] - want) > 0.005) {
            if (this.dirty && this.dirty[stream]) {
              await this.push(stream, desk[stream]);
            } else {
              setDesk(this.doc, stream, want);
            }
          }
        }
      }
      mute(this.doc, !mine.play);
    }
    this.onState({decision, mine: mine ? Object.assign({}, mine) : null});
    return decision;
  };

  /* Write one of this device's levels back to the table. */
  Client.prototype.push = async function push(stream, level) {
    const settings = await this.fetchJson('/api/settings');
    const out = this.update(settings, this.id, {[stream]: clamp(level)});
    if (!out.ok) return out;
    await this.fetchJson('/api/settings', {method: 'PUT', body: out.settings});
    if (this.dirty) this.dirty[stream] = false;
    return out;
  };

  /* Watch the panel's own sliders, so a hand on the desk is not fought by
   * the next poll. */
  Client.prototype.watchDesk = function watchDesk() {
    this.dirty = {};
    for (const stream of STREAMS) {
      const input = this.doc.getElementById(SLIDER[stream] || '');
      if (!input) continue;
      input.addEventListener('change', () => {
        this.dirty[stream] = true;
        this.push(stream, Number(input.value) / 100).catch(() => {});
      });
    }
    return this;
  };

  Client.prototype.start = function start() {
    clampMediaVolume();
    this.watchDesk();
    const beat = () => { this.tick().catch(() => {}); };
    beat();
    this.timer = setInterval(beat, this.pollMs);
    return this;
  };

  Client.prototype.stop = function stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    return this;
  };

  const api = {
    Client, clamp, clampMediaVolume, deskLevels, setDesk, mute,
    STREAMS, POLL_MS, SLIDER
  };
  global.PineTerminalAudio = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
