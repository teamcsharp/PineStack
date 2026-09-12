/* window.pineSampler — the sampler's audio engine, Web Audio backend.
 *
 * THIS FILE IS A SEAM, NOT A FEATURE. The sampler UI talks to nothing but
 * the surface declared at the bottom of this file. The Android terminal
 * ships a native Oboe/AAudio implementation of that same surface and loads
 * it instead of this one; the UI does not know which is underneath.
 *
 * Why the tablet cannot use this file: a WebView audio path will not hold
 * "tap the pad and it plays with no delay" on a mid-range MediaTek. On the
 * desktop it is comfortably good enough, so Electron gets Web Audio and the
 * tablet gets native, and neither of them gets a second UI.
 *
 * The rules that shape the code below:
 *   - Every sample is decoded ONCE, on load, and held resident. Nothing is
 *     decoded on the press - that is the whole point of downloading.
 *   - Every start and every stop rides a short envelope. A raw start() or
 *     stop() on a buffer that isn't at a zero crossing is an audible click,
 *     and a sampler that clicks is a toy.
 *   - A voice is never left dangling: onended always reaps it, so a long
 *     one-shot that finishes on its own frees its slot the same way a
 *     released gate does.
 */
(function (root) {
  "use strict";

  /* Long enough to hide a discontinuity, short enough that a stab still
   * reads as a stab. Measured by ear against the station's own stings. */
  const ATTACK = 0.003;
  const RELEASE = 0.012;

  /* A tap that fires the same pad again lands on top of the previous voice
   * rather than cutting it dead, unless polyphony is off or the pad is in a
   * choke group. */
  let polyphonic = true;

  let ctx = null;
  let master = null;
  let voiceSeq = 0;

  const pads = new Map();    /* padId -> pad record                     */
  const voices = new Map();  /* voiceId -> {source, gain, padId, group}  */

  function context() {
    if (!ctx) {
      const Ctor = root.AudioContext || root.webkitAudioContext;
      if (!Ctor) throw new Error("This build has no Web Audio.");
      /* interactive = the smallest buffer the platform will give us. */
      ctx = new Ctor({ latencyHint: "interactive" });
      master = ctx.createGain();
      master.gain.value = 1;
      master.connect(ctx.destination);
    }
    /* Autoplay policy parks the context until a gesture. Every fire()
     * follows a real tap, so resuming here is always legitimate. */
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    return ctx;
  }

  function reversedCopy(buffer) {
    const out = context().createBuffer(
      buffer.numberOfChannels, buffer.length, buffer.sampleRate);
    for (let c = 0; c < buffer.numberOfChannels; c += 1) {
      const from = buffer.getChannelData(c);
      const to = out.getChannelData(c);
      for (let i = 0, j = from.length - 1; i < from.length; i += 1, j -= 1) {
        to[i] = from[j];
      }
    }
    return out;
  }

  function padRecord(padId) {
    const key = String(padId);
    let pad = pads.get(key);
    if (!pad) {
      pad = {
        id: key, buffer: null, reversed: null,
        gain: 1, pitch: 1, loop: false, reverse: false,
        trim: null,          /* {start, end} in seconds, or null for whole  */
        choke: ""            /* pads sharing a non-empty group cut each other */
      };
      pads.set(key, pad);
    }
    return pad;
  }

  /* The window actually played, expressed against the buffer that will be
   * handed to the source. A trim is stored against the FORWARD sample, so
   * playing it backwards means mirroring the window, not reusing it. */
  function window_(pad, buffer) {
    const total = buffer.duration;
    const trim = pad.trim;
    let start = trim ? Math.max(0, Math.min(total, Number(trim.start) || 0)) : 0;
    let end = trim ? Math.max(start, Math.min(total, Number(trim.end) || total)) : total;
    if (!(end > start)) { start = 0; end = total; }
    if (pad.reverse) return { offset: total - end, duration: end - start };
    return { offset: start, duration: end - start };
  }

  function reap(voiceId) {
    const voice = voices.get(voiceId);
    if (!voice) return;
    voices.delete(voiceId);
    try { voice.source.disconnect(); } catch (err) { /* already gone */ }
    try { voice.gain.disconnect(); } catch (err) { /* already gone */ }
  }

  /* Stop with a ramp rather than a cut. Used by release(), by choke, by a
   * retrigger when polyphony is off, and by stopAll(). */
  function fade(voiceId) {
    const voice = voices.get(voiceId);
    if (!voice) return;
    const now = context().currentTime;
    const gain = voice.gain.gain;
    try {
      gain.cancelScheduledValues(now);
      gain.setValueAtTime(gain.value, now);
      gain.linearRampToValueAtTime(0, now + RELEASE);
    } catch (err) { /* a context that went away mid-release */ }
    try { voice.source.stop(now + RELEASE); } catch (err) { /* already stopped */ }
    /* onended reaps it; this only guarantees it if the source never fired. */
    setTimeout(() => reap(voiceId), (RELEASE * 1000) + 40);
  }

  function cutSiblings(pad, exceptId) {
    for (const [voiceId, voice] of [...voices.entries()]) {
      if (voiceId === exceptId) continue;
      const samePad = voice.padId === pad.id;
      const sameGroup = pad.choke && voice.group === pad.choke;
      if (sameGroup || (samePad && !polyphonic)) fade(voiceId);
    }
  }

  const engine = {
    /* ---- lifecycle ------------------------------------------------- */

    /* Called from a real gesture so the context is live before the first
     * pad is pressed - otherwise press #1 pays for the resume. */
    warm() {
      try { context(); return true; } catch (err) { return false; }
    },

    ready() { return !!ctx && ctx.state === "running"; },

    setPolyphonic(on) { polyphonic = !!on; },
    isPolyphonic() { return polyphonic; },

    /* ---- loading ---------------------------------------------------- */

    /* bytes may be an ArrayBuffer (what a fetch of /api/booth/clip gives)
     * or a URL string. Decoding happens here and only here. */
    async load(padId, bytesOrUrl) {
      const pad = padRecord(padId);
      let bytes = bytesOrUrl;
      if (typeof bytesOrUrl === "string") {
        const response = await fetch(bytesOrUrl);
        if (!response.ok) throw new Error("Could not fetch that sample (HTTP " + response.status + ").");
        bytes = await response.arrayBuffer();
      }
      if (bytes instanceof Uint8Array) bytes = bytes.buffer;
      if (!(bytes instanceof ArrayBuffer)) throw new Error("A pad needs bytes or a URL.");
      if (!bytes.byteLength) throw new Error("That sample was empty.");
      /* decodeAudioData detaches the buffer it is given, so a caller that
       * wants to keep the bytes (to write them to disk) keeps its own copy. */
      const buffer = await context().decodeAudioData(bytes.slice(0));
      pad.buffer = buffer;
      pad.reversed = null;      /* rebuilt lazily if the pad is reversed */
      if (!pad.trim) pad.trim = null;
      return { seconds: buffer.duration, rate: buffer.sampleRate,
               channels: buffer.numberOfChannels };
    },

    /* Share one decoded buffer with another pad. Chop needs the same
     * thirty seconds of air on all sixteen pads with different windows;
     * decoding it sixteen times would be sixteen times the memory and the
     * wait, for identical samples. The buffer is immutable once decoded,
     * so sharing the reference is safe - only the per-pad trim differs. */
    copy(fromPadId, toPadId) {
      const from = pads.get(String(fromPadId));
      if (!from || !from.buffer) return false;
      const to = padRecord(toPadId);
      to.buffer = from.buffer;
      to.reversed = from.reverse === to.reverse ? from.reversed : null;
      return true;
    },

    unload(padId) {
      const pad = pads.get(String(padId));
      if (!pad) return false;
      engine.stopPad(padId);
      pad.buffer = null;
      pad.reversed = null;
      return true;
    },

    /* Drop every pad. Wiping the banks, or handing the instrument to a
     * different set of templates, should not leave a quarter of a gigabyte
     * of decoded audio resident behind the new layout. */
    clear() {
      engine.stopAll();
      pads.clear();
      return true;
    },

    loaded(padId) { return !!(pads.get(String(padId)) || {}).buffer; },

    seconds(padId) {
      const pad = pads.get(String(padId));
      return pad && pad.buffer ? pad.buffer.duration : 0;
    },

    /* The decoded samples, for the trim editor's waveform. Mono mixdown at
     * whatever resolution the caller asks for, so the UI never touches an
     * AudioBuffer directly. */
    peaks(padId, buckets = 512) {
      const pad = pads.get(String(padId));
      if (!pad || !pad.buffer) return [];
      const buffer = pad.buffer;
      const count = Math.max(1, Math.min(4096, buckets | 0));
      const per = Math.max(1, Math.floor(buffer.length / count));
      const out = new Array(count).fill(0);
      for (let c = 0; c < buffer.numberOfChannels; c += 1) {
        const data = buffer.getChannelData(c);
        for (let i = 0; i < count; i += 1) {
          let peak = 0;
          const from = i * per;
          const to = Math.min(data.length, from + per);
          for (let j = from; j < to; j += 1) {
            const v = data[j] < 0 ? -data[j] : data[j];
            if (v > peak) peak = v;
          }
          if (peak > out[i]) out[i] = peak;
        }
      }
      return out;
    },

    /* The nearest point to `seconds` where the waveform crosses zero.
     * Trimming anywhere else leaves a step in the signal, and a step is a
     * click. The search is bounded so a pad of solid tone (which may have
     * no crossing nearby) simply keeps the handle where it was put. */
    zeroCross(padId, seconds, withinMs = 30) {
      const pad = pads.get(String(padId));
      if (!pad || !pad.buffer) return seconds;
      const buffer = pad.buffer;
      const data = buffer.getChannelData(0);
      const rate = buffer.sampleRate;
      const target = Math.max(0, Math.min(buffer.length - 1,
        Math.round(Number(seconds) * rate)));
      const span = Math.max(1, Math.round((withinMs / 1000) * rate));
      for (let step = 0; step <= span; step += 1) {
        for (const index of (step === 0 ? [target] : [target - step, target + step])) {
          if (index <= 0 || index >= data.length) continue;
          const before = data[index - 1];
          const here = data[index];
          if ((before <= 0 && here >= 0) || (before >= 0 && here <= 0)) {
            return index / rate;
          }
        }
      }
      return seconds;
    },

    /* ---- per-pad settings ------------------------------------------- */

    set(padId, patch = {}) {
      const pad = padRecord(padId);
      if ("gain" in patch) pad.gain = Math.max(0, Math.min(4, Number(patch.gain) || 0));
      if ("pitch" in patch) pad.pitch = Math.max(0.03125, Math.min(32, Number(patch.pitch) || 1));
      if ("loop" in patch) pad.loop = !!patch.loop;
      if ("choke" in patch) pad.choke = String(patch.choke || "");
      if ("reverse" in patch) {
        const want = !!patch.reverse;
        if (want !== pad.reverse) pad.reversed = null;
        pad.reverse = want;
      }
      if ("trim" in patch) {
        pad.trim = patch.trim
          ? { start: Number(patch.trim.start) || 0, end: Number(patch.trim.end) || 0 }
          : null;
      }
      return { ...pad, buffer: undefined, reversed: undefined };
    },

    get(padId) {
      const pad = pads.get(String(padId));
      if (!pad) return null;
      return { id: pad.id, gain: pad.gain, pitch: pad.pitch, loop: pad.loop,
               reverse: pad.reverse, trim: pad.trim, choke: pad.choke,
               seconds: pad.buffer ? pad.buffer.duration : 0 };
    },

    /* ---- playing ----------------------------------------------------- */

    /* Returns a voice id, or "" if the pad is empty. `gate` holds the note
     * until release(); `loop` overrides the pad's own loop flag for one hit
     * (16 Level and Note Repeat both need that). */
    fire(padId, options = {}) {
      const pad = pads.get(String(padId));
      if (!pad || !pad.buffer) return "";
      const audio = context();

      if (pad.reverse && !pad.reversed) pad.reversed = reversedCopy(pad.buffer);
      const buffer = pad.reverse ? pad.reversed : pad.buffer;

      const velocity = Math.max(0, Math.min(1,
        "velocity" in options ? Number(options.velocity) : 1));
      const loop = "loop" in options ? !!options.loop : pad.loop;
      const gate = !!options.gate;
      const pitch = Math.max(0.03125, Math.min(32,
        "pitch" in options ? Number(options.pitch) || 1 : pad.pitch));

      const source = audio.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = pitch;

      const gain = audio.createGain();
      const peak = pad.gain * velocity;
      const now = audio.currentTime;
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(peak, now + ATTACK);

      source.connect(gain);
      gain.connect(master);

      const { offset, duration } = window_(pad, buffer);
      if (loop) {
        source.loop = true;
        source.loopStart = offset;
        source.loopEnd = offset + duration;
      }

      const voiceId = "v" + (voiceSeq += 1);
      /* WHEN IT STARTED AND HOW LONG IT RUNS, so the view can draw a
       * playhead. The clock is the AudioContext's, not the wall's: that is
       * the clock the sound is actually scheduled against, so a bar drawn
       * from it cannot drift away from what is being heard.
       *
       * `duration` is the window in the BUFFER, so it is divided by the
       * playback rate to get the time it will really take - a pad played an
       * octave up finishes in half the time, and a timeline that ignored
       * that would be wrong by a factor of two exactly when 16 LEVEL is on.
       * A looping or gated voice has no end, and says so with `until: 0`. */
      const realLength = duration / pitch;
      voices.set(voiceId, {
        source, gain, padId: pad.id, group: pad.choke,
        from: now,
        until: (loop || gate) ? 0 : now + realLength,
        length: realLength,
        label: pad.label || ""
      });
      cutSiblings(pad, voiceId);

      source.onended = () => reap(voiceId);
      /* A looping or gated voice runs until it is released; a one-shot is
       * given its exact window so it stops itself. */
      if (loop || gate) source.start(now, offset);
      else source.start(now, offset, duration);

      return voiceId;
    },

    release(voiceId) { fade(String(voiceId)); },

    stopPad(padId) {
      const key = String(padId);
      for (const [voiceId, voice] of [...voices.entries()]) {
        if (voice.padId === key) fade(voiceId);
      }
    },

    stopAll() {
      for (const voiceId of [...voices.keys()]) fade(voiceId);
    },

    /* ---- metering ---------------------------------------------------- */

    /* What the loaded pads actually cost in memory.
     *
     * MEASURED, not assumed: a booth "line" off this station ran 62.97s,
     * and decodeAudioData resamples the box's mono 24 kHz up to the
     * context rate, so one pad like that is ~12 MB of float32 - not the
     * fraction of a megabyte its 596 KB mp3 suggests. Sixteen of them is
     * a quarter of a gigabyte. The caller decides what to do about it;
     * this only refuses to let it happen invisibly.
     *
     * Buffers shared by chop are counted once. */
    footprint() {
      const seen = new Set();
      let bytes = 0;
      let loadedPads = 0;
      for (const pad of pads.values()) {
        if (!pad.buffer) continue;
        loadedPads += 1;
        if (seen.has(pad.buffer)) continue;
        seen.add(pad.buffer);
        bytes += pad.buffer.length * pad.buffer.numberOfChannels * 4;
        if (pad.reversed && !seen.has(pad.reversed)) {
          seen.add(pad.reversed);
          bytes += pad.reversed.length * pad.reversed.numberOfChannels * 4;
        }
      }
      return { bytes, pads: loadedPads, buffers: seen.size };
    },

    levels() {
      const perPad = {};
      for (const voice of voices.values()) {
        perPad[voice.padId] = (perPad[voice.padId] || 0) + 1;
      }
      return {
        voices: voices.size,
        pads: perPad,
        state: ctx ? ctx.state : "closed",
        /* What the platform admits to. The real number is measured with a
         * recorder against a physical tap - never reported from here as if
         * it were the tap-to-sound figure. */
        baseLatency: ctx && ctx.baseLatency ? ctx.baseLatency : 0,
        outputLatency: ctx && ctx.outputLatency ? ctx.outputLatency : 0
      };
    },

    /* LENT, so the air tap and the pads share one clock and one output
     * stream. A second AudioContext is a second stream for the platform to
     * schedule, and on this MediaTek that is audible. Web Audio only - the
     * native terminal engine has no context to lend and says so by not
     * defining this. */
    context() { return context(); },

    /* HOW MANY VOICES ARE STILL SOUNDING. The broadcast is ducked while a pad
     * plays and has to come back when the LAST one finishes, not when the
     * finger lifts - a one-shot outlives the press that started it, and
     * reference-counting presses would unduck over the top of it. */
    playing() { return voices.size; },

    /**
     * EVERY VOICE STILL SOUNDING, AND HOW FAR THROUGH IT IS.
     *
     * For the timeline across the sampler. `at` is 0..1 for a one-shot and
     * -1 for a voice with no end - a loop or a held gate - because a
     * progress bar for something that does not end is a lie, and the view
     * draws those as a running stripe instead.
     */
    active() {
      const audio = ctx;
      if (!audio) return [];
      const now = audio.currentTime;
      const out = [];
      voices.forEach((voice, id) => {
        const open = !voice.until;
        out.push({
          id,
          padId: voice.padId,
          at: open ? -1 : Math.max(0, Math.min(1,
            (now - voice.from) / Math.max(0.001, voice.until - voice.from))),
          seconds: open ? (now - voice.from) : voice.length,
          done: open ? 0 : now - voice.from,
          open
        });
      });
      return out;
    },

    backend: "webaudio"
  };

  if (typeof module !== "undefined" && module.exports) module.exports = engine;
  /* The native terminal defines window.pineSampler before this file loads;
   * when it has, we leave it alone. */
  if (!root.pineSampler) root.pineSampler = engine;
  /* Published under its own name as well: `pineSampler` may be the NATIVE
   * engine on the terminal, and the air tap needs the Web Audio one
   * specifically - it wants the context, which the native engine has not
   * got. Asking for the right thing by name beats feature-sniffing. */
  root.PineSamplerEngine = engine;
})(typeof window !== "undefined" ? window : globalThis);
