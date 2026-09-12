/* The Sampler - the station played back as an instrument.
 *
 * The station makes audio the operator likes and then loses it to air.
 * This is the net: drag a moment out of the live feed onto a pad and it is
 * DOWNLOADED to this machine, decoded once, and held resident. From then on
 * the pad plays it locally with no round trip and no broadcast involvement -
 * which is also the only way it can still work in 48 hours, because the
 * station sweeps its own media after that (AIRLOG_KEEP_S) and a pad that
 * pointed at a line id rather than holding bytes would simply go dead.
 *
 * Audio never happens in here. Everything goes through window.pineSampler,
 * which is Web Audio on the desktop and native Oboe on the tablet.
 */
(function (root) {
  "use strict";

  const BANKS = 5;
  const PADS = 16;
  const DB_NAME = "pinebox-sampler";
  const DB_STORE = "pads";

  const api = () => root.pineDesktop;
  const engine = () => root.pineSampler;

  let config = null;
  let bank = 0;
  let selected = 0;
  let layout = [];              /* layout[bank][pad] = meta | null */
  let unsubscribe = null;
  let mounted = false;
  let feedRows = [];
  let grabWhole = false;        /* the line, or the whole welded round */

  const modes = {
    poly: false, gate: false, full: false,
    sixteen: false, repeat: false, division: 4, bpm: 90,
    /* 16 LEVEL, beyond one chromatic run. "I want options to adjust the
     * octave, the chord, the progression."
     *   octave   shifts the whole grid in twelfths, -2..+2
     *   chord    the intervals the grid walks; "chromatic" is the original
     *            behaviour and stays the default
     *   progress a root movement applied every four pads, so the grid can
     *            walk a progression rather than one scale */
    octave: 0, chord: 'chromatic', progress: 'none'
  };

  /* WHAT THIS PAGE WAS LEFT SET TO.
   *
   * "Have POLY off by default. In fact, remember what settings I have on on
   *  this page and have them on by default when I go back to this page."
   *
   * POLY was on at boot because that was somebody's idea of a sensible
   * default, and a default is exactly the wrong shape for this: an
   * instrument should open the way you left it, not the way it shipped. So
   * every switch and dial is remembered, and the "default" is only what a
   * terminal that has never been touched starts with. POLY starts OFF there,
   * as asked. */
  const MODES_KEY = "pineSamplerModes";

  function rememberModes() {
    try {
      root.localStorage.setItem(MODES_KEY, JSON.stringify({
        poly: modes.poly, gate: modes.gate, full: modes.full,
        sixteen: modes.sixteen, repeat: modes.repeat,
        division: modes.division, bpm: modes.bpm,
        octave: modes.octave, chord: modes.chord, progress: modes.progress
      }));
    } catch (err) { /* a preference is not worth an exception */ }
  }

  function restoreModes() {
    let saved = null;
    try { saved = JSON.parse(root.localStorage.getItem(MODES_KEY) || "null"); }
    catch (err) { saved = null; }
    /* Never touched: POLY off, and everything else as declared above. */
    modes.poly = saved ? !!saved.poly : false;
    if (!saved) return;
    modes.gate = !!saved.gate;
    modes.full = !!saved.full;
    modes.sixteen = !!saved.sixteen;
    modes.repeat = !!saved.repeat;
    if (CHORDS[saved.chord]) modes.chord = saved.chord;
    if (PROGRESSIONS[saved.progress]) modes.progress = saved.progress;
    const octave = Number(saved.octave);
    if (isFinite(octave) && octave >= -2 && octave <= 2) modes.octave = octave;
    const division = Number(saved.division);
    if ([4, 6, 8, 12, 16, 24, 32].indexOf(division) >= 0) modes.division = division;
    const bpm = Number(saved.bpm);
    if (isFinite(bpm) && bpm >= 20 && bpm <= 300) modes.bpm = bpm;
  }

  /* THE SHAPES 16 LEVEL CAN TAKE.
   *
   * Semitones from the root, repeated up the octaves to fill sixteen pads.
   * Chromatic is what 16 LEVEL has always done and is still what it does
   * unless asked otherwise - this widens the control, it does not move it. */
  const CHORDS = {
    chromatic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    majorScale: [0, 2, 4, 5, 7, 9, 11],
    minorScale: [0, 2, 3, 5, 7, 8, 10],
    pentatonic: [0, 3, 5, 7, 10],
    major: [0, 4, 7],
    minor: [0, 3, 7],
    major7: [0, 4, 7, 11],
    minor7: [0, 3, 7, 10],
    dom7: [0, 4, 7, 10],
    sus4: [0, 5, 7],
    dim: [0, 3, 6],
    fourths: [0, 5],
    wholeTone: [0, 2, 4, 6, 8, 10]
  };

  /* Root movement per ROW of four pads, in semitones. */
  const PROGRESSIONS = {
    none: [0, 0, 0, 0],
    'I-IV-V-I': [0, 5, 7, 0],
    'I-V-vi-IV': [0, 7, 9, 5],
    'ii-V-I': [2, 7, 0, 0],
    'i-VI-III-VII': [0, 8, 3, 10],
    'rising4ths': [0, 5, 10, 15]
  };

  const held = new Map();       /* padIndex -> {voiceId, repeatTimer} */
  let tapTimes = [];

  const el = (id) => document.getElementById(id);
  const padKey = (b, p) => b + ":" + p;

  function blank() {
    return Array.from({ length: BANKS }, () => new Array(PADS).fill(null));
  }

  /* ---------------------------------------------------------------- store */
  /* Bytes live in IndexedDB rather than on the filesystem so the same code
   * runs unchanged in a plain browser tab; the tablet swaps this half for
   * Room + a PCM cache. The ORIGINAL compressed bytes are what we keep - a
   * spoken line is mono 24 kHz, so a typical one is 25-70 KB. */

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(DB_STORE)) db.createObjectStore(DB_STORE);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function dbPut(key, value) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, "readwrite");
      tx.objectStore(DB_STORE).put(value, key);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function dbGet(key) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, "readonly");
      const request = tx.objectStore(DB_STORE).get(key);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  }

  async function dbDelete(key) {
    const db = await openDb();
    return new Promise((resolve) => {
      const tx = db.transaction(DB_STORE, "readwrite");
      tx.objectStore(DB_STORE).delete(key);
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => resolve(false);
    });
  }

  function saveLayout() {
    try { localStorage.setItem("pineSamplerLayout", JSON.stringify(layout)); }
    catch (err) { /* a full quota must not stop the pad from sounding */ }
  }

  function loadLayout() {
    try {
      const raw = localStorage.getItem("pineSamplerLayout");
      const parsed = raw ? JSON.parse(raw) : null;
      if (Array.isArray(parsed) && parsed.length === BANKS) return parsed;
    } catch (err) { /* fall through to a clean set of banks */ }
    return blank();
  }

  /* ------------------------------------------------------------- fetching */

  function absolute(url) {
    const path = String(url || "");
    if (/^https?:/i.test(path)) return path;
    return String(config.baseUrl).replace(/\/+$/, "") + path;
  }

  /* Reads are open on this station today (SPARK_AGENT_LOCK_READS is unset),
   * so these URLs answer with no header at all. The bearer goes on anyway:
   * the day someone locks reads, /api/booth/clip is the ONE audio route
   * with no ?t= signature fallback, so it would be the first thing to break. */
  /* MEASURED, and it shapes the whole feel of this screen: the same clip
   * came back in 1,099 ms once and 13,540 ms the next time. That is not a
   * cold cache - it is STATION LOAD. The box is a live radio station
   * writing and recording audio, and a cut queues behind that work.
   *
   * Nothing here can make it faster. What it can do is never look broken
   * while it waits, never block another grab, and give up with a sentence
   * rather than hanging forever. */
  const FETCH_CEILING = 90000;

  async function fetchBytes(url) {
    const headers = config.apiKey ? { Authorization: "Bearer " + config.apiKey } : {};
    const response = await fetch(absolute(url), {
      headers,
      signal: AbortSignal.timeout ? AbortSignal.timeout(FETCH_CEILING) : undefined
    });
    if (!response.ok) {
      throw new Error("The station could not provide that sample (HTTP "
        + response.status + ").");
    }
    const type = response.headers.get("content-type") || "";
    if (!/^audio\//i.test(type) && !/^application\/octet-stream/i.test(type)) {
      throw new Error("That was not audio.");
    }
    return {
      bytes: await response.arrayBuffer(),
      type,
      /* X-Pine-Exact 0 means we were handed the surrounding moment or a near
       * miss rather than this row alone; X-Pine-Cut says so in prose. The pad
       * shows it, because "that is not the bit I wanted" should be visible
       * before it goes to air, not after. */
      exact: response.headers.get("x-pine-exact") === "1",
      cut: response.headers.get("x-pine-cut") || ""
    };
  }

  /* CAN THIS ROW BE TAKEN, AND FROM WHERE?
   *
   * The LCD asks a different question - "has this been on air?" - and the
   * sampler inherited its answer, which was badly wrong here. Measured
   * against the live station: of 240 rows in the ring, only SEVEN were
   * `aired`, but 212 carried `clip_media`/`clip_sig` (the welded round they
   * sit in) and 23 carried `media`/`sig` (their own recorded take). The
   * sampler was offering 7 of ~220 takeable moments.
   *
   * A line that is recorded and waiting has audio on disk. That it has not
   * reached the air yet is no reason the operator cannot have it - it is
   * arguably the most interesting time to grab one.
   *
   * Order matters: prefer the most exact cut available.
   *   1. a sting carries its own signed url - no round trip at all
   *   2. an advert is produced whole
   *   3. /api/booth/clip cuts THIS turn out of the welded round, which is
   *      better than the whole round, and the station caches the cut
   *   4. a row with only its own take is fetched directly
   */
  function sourceFor(row) {
    if (!row) return null;
    if (row.sfx && row.url) return { url: row.url, kind: "sfx", exactish: true };
    /* A RECORD IS TAKEN WHOLE FROM ITS OWN FILE, never cut out of the booth
     * ring - the clip route knows nothing about music. Marked by the feed
     * model (see lcd-dialogue.js) rather than guessed at from the shape of
     * the row, because `{url, text}` is also what an advert looks like.
     *
     * It is BIG, and the footprint line under the pads is where that shows:
     * four minutes decodes to roughly 45 MB. The operator asked for whole
     * records on pads, so it is offered - and counted honestly. */
    if (row.music && row.url) return { url: row.url, kind: "music", exactish: true };
    if (row.url && !row.text) return { url: row.url, kind: "media", exactish: true };

    const line = "/api/booth/clip?line=" + encodeURIComponent(row.id)
      + (grabWhole ? "&whole=1" : "");

    /* The clip route can cut it: either the turn's own span out of the
     * welded round, or the row's own media, or an advert. */
    if (row.clip_media && row.clip_sig) return { url: line, kind: "round" };
    if (row.ad_audio) return { url: line, kind: "advert" };
    if (row.media && row.sig) {
      /* When asked for the whole moment there is nothing wider than the
       * take itself, so go straight to the file and skip the cut. */
      return grabWhole
        ? { url: "/media/" + encodeURIComponent(row.media)
              + "?t=" + encodeURIComponent(row.sig), kind: "take", exactish: true }
        : { url: line, kind: "take" };
    }
    if (["box", "stream", "both", "airing"].indexOf(String(row.aired)) >= 0) {
      return { url: line, kind: "line" };
    }
    return null;
  }

  /* Shown greyed rather than hidden: "why is that not here" is a worse
   * question than "why is that greyed out". */
  function takeable(row) { return !!sourceFor(row); }

  /* Why the last import failed, in prose, for a caller that cannot see
   * #pbNote. Read immediately after the await that returned null; grab()
   * below is the only reader and it serialises itself so two grabs can
   * never interleave over this one slot. */
  let lastImportWhy = "";

  async function importRow(row, targetBank, targetPad) {
    lastImportWhy = "";
    const key = padKey(targetBank, targetPad);
    const cell = el("pad-" + targetPad);
    /* A pad that just sits there is indistinguishable from a pad that has
     * failed. Count up on its face so the wait is legibly a wait - and it
     * can be a long one, so this is not decoration. */
    let ticker = 0;
    if (cell) {
      cell.classList.add("loading");
      const label = cell.querySelector(".pb-pad-label");
      const sub = cell.querySelector(".pb-pad-sub");
      if (label) label.textContent = (row.text || row.name || "take").slice(0, 60);
      const began = Date.now();
      const tick = () => {
        if (sub) sub.textContent = "fetching… " + Math.round((Date.now() - began) / 1000) + "s";
      };
      tick();
      ticker = setInterval(tick, 1000);
    }
    try {
      const source = sourceFor(row);
      if (!source) throw new Error("There is no audio behind that line yet.");
      const got = await fetchBytes(source.url);
      await dbPut(key, { bytes: got.bytes, type: got.type });
      const meta = {
        label: (row.text || row.name || row.who || "take").slice(0, 90),
        who: row.name || row.who || "",
        kind: source.kind,
        srcId: row.id || "",
        exact: got.exact,
        cut: got.cut,
        at: Date.now(),
        gain: 1, pitch: 1, loop: false, reverse: false, trim: null, choke: ""
      };
      await engine().load(key, got.bytes);
      meta.seconds = engine().seconds(key);
      layout[targetBank][targetPad] = meta;
      saveLayout();
      paintPads();
      note(meta.exact
        ? "Pad " + (targetPad + 1) + " - " + meta.seconds.toFixed(2) + "s"
        : "Pad " + (targetPad + 1) + " - " + (meta.cut || "not an exact cut"));
      /* Handed back so a caller OUTSIDE this view can say what happened.
       * note() writes into #pbNote, which lives in the sampler host - and
       * the Listen view's one-tap grab fires while the sampler is not on
       * screen, so its operator would never see a word of it. */
      return meta;
    } catch (err) {
      const why = err && err.name === "TimeoutError"
        ? "The station did not answer in time - it is busy making the show. Try that one again."
        : (err.message || String(err));
      note("Pad " + (targetPad + 1) + " - " + why, true);
      lastImportWhy = why;
      /* Leave nothing half-written on the pad. */
      if (!layout[targetBank][targetPad]) {
        const label = cell && cell.querySelector(".pb-pad-label");
        const sub = cell && cell.querySelector(".pb-pad-sub");
        if (label) label.textContent = "";
        if (sub) sub.textContent = "";
      }
    } finally {
      if (ticker) clearInterval(ticker);
      if (cell) cell.classList.remove("loading");
    }
  }

  /* ONE-TAP GRAB, FOR A VIEW THAT HAS NO DRAG.
   *
   * The Listen view is lean-back: no feed list to drag from, no pad to
   * drop on, one button that means "keep that". It must not grow its own
   * copy of any of this - sourceFor() is the only place that knows where
   * a row's audio lives, and a second opinion about it would rot the
   * moment the station changes.
   *
   * Two things this has to do that a drag does not:
   *
   *   1. MOUNT. The sampler is built on first visit so an unopened view
   *      costs neither a decode nor a feed subscription - which means
   *      config is null and layout is [] until then, and importRow would
   *      throw on the first of those. A grab from elsewhere builds the
   *      view (into the hidden #sampler host) before it takes anything.
   *   2. SPEAK FOR ITSELF. Every message importRow writes goes to #pbNote
   *      inside a view the operator is not looking at, so the outcome
   *      comes back as a value instead.
   *
   * Serialised on purpose: a second tap while a clip is still coming down
   * is answered with "still fetching" rather than queued. The measured
   * fetch for one clip ranged from 1.1 s to 13.5 s against a busy
   * station, and two of them racing for "the next free pad" would both
   * pick the same one. */
  let grabbing = false;

  async function grab(row) {
    if (!row) return {ok: false, why: "there is nothing to take."};
    if (grabbing) return {ok: false, why: "still fetching the last one."};
    grabbing = true;
    try {
      if (!mounted) {
        const host = document.getElementById("sampler");
        if (!host) {
          return {ok: false, why: "the sampler is not on this page."};
        }
        await mount(host);
      }
      if (!sourceFor(row)) {
        return {ok: false, why: "there is no audio behind that line yet."};
      }
      const free = root.PineListenModel
        ? root.PineListenModel.firstFreePad(layout, bank)
        : null;
      if (!free) {
        return {ok: false,
          why: "every pad in every bank is full - clear one first."};
      }
      const meta = await importRow(row, free.bank, free.pad);
      if (!meta) {
        return {ok: false, why: lastImportWhy || "the station would not cut it."};
      }
      return {ok: true, bank: free.bank, pad: free.pad, meta,
        why: "bank " + (free.bank + 1) + ", pad " + (free.pad + 1)};
    } catch (err) {
      return {ok: false, why: (err && err.message) || String(err)};
    } finally {
      grabbing = false;
    }
  }

  /* Bring a bank's bytes back off disk and into the engine, so a pad is
   * instant the moment the app opens rather than on its first press. */
  async function preload(which) {
    const jobs = [];
    for (let p = 0; p < PADS; p += 1) {
      const meta = layout[which][p];
      if (!meta) continue;
      const key = padKey(which, p);
      if (engine().loaded(key)) { applySettings(key, meta); continue; }
      jobs.push(dbGet(key).then(async (record) => {
        if (!record || !record.bytes) return;
        try {
          await engine().load(key, record.bytes);
          applySettings(key, meta);
        } catch (err) { /* one bad pad never stops the bank */ }
      }));
    }
    await Promise.all(jobs);
    paintPads();
  }

  function applySettings(key, meta) {
    engine().set(key, {
      gain: meta.gain == null ? 1 : meta.gain,
      pitch: meta.pitch == null ? 1 : meta.pitch,
      loop: !!meta.loop, reverse: !!meta.reverse,
      trim: meta.trim || null, choke: meta.choke || ""
    });
  }

  /* -------------------------------------------------------------- playing */

  /* The M9 reports no usable pressure, and neither does a mouse. Vertical
   * position inside the pad is the honest stand-in: strike high for loud. */
  function velocityFrom(event, element) {
    if (modes.full) return 1;
    const box = element.getBoundingClientRect();
    const y = (event.clientY - box.top) / Math.max(1, box.height);
    return Math.max(0.25, Math.min(1, 1 - (y * 0.75)));
  }

  /* 16 LEVEL: one sample across the whole grid.
   *
   * Semitones are worked out FIRST and the playback rate comes from them,
   * not the other way round: chord and progression are both things you say
   * in semitones, and neither is expressible as a ratio.
   *
   * The grid reads BOTTOM-LEFT UP, the way a keyboard does and the way the
   * gradient draws it - pad 13, the bottom-left of a 4x4 laid out in
   * reading order, is the lowest. Numbering it in reading order would put
   * the lowest note at the top, backwards from every instrument and from
   * the illumination the operator asked for. */
  function sixteenSemitone(index) {
    const row = Math.floor(index / 4);          /* 0 at the top         */
    const column = index % 4;
    const step = (3 - row) * 4 + column;        /* 0 at the bottom-left */
    const shape = CHORDS[modes.chord] || CHORDS.chromatic;
    const degree = step % shape.length;
    /* TWO OCTAVES, THEN ROUND AGAIN - not a ladder that climbs forever.
     *
     * Stacking an octave on every cycle of the shape works for chromatic,
     * which has twelve notes and so only wraps once across sixteen pads. For
     * a triad it is a disaster: three notes per cycle means five octaves by
     * pad sixteen, and `octaves` ([0] - since removed) reached +168
     * semitones, a playback rate of 32768x. That is not a high note, it is a
     * click. Measured exactly that.
     *
     * Wrapping at two octaves gives every shape a repeating two-octave
     * layout, which is how pad grids are normally laid out anyway, and it
     * leaves CHROMATIC EXACTLY AS IT WAS - twelve notes then 12..15, unity at
     * the top-left, which is what 16 LEVEL has always done here. */
    const octaveUp = Math.floor(step / shape.length) % 2;
    const walk = PROGRESSIONS[modes.progress] || PROGRESSIONS.none;
    const root = walk[Math.floor(step / 4) % walk.length] || 0;
    /* CENTRED so the grid straddles the sample rather than climbing away
     * from it - twelve is where the chromatic run puts unity, and every
     * other shape inherits the same reference. */
    const want = shape[degree] + (octaveUp * 12) + root + (modes.octave * 12) - 12;
    /* AND BOUNDED. At -24 the clip runs four times as long, at +24 four
     * times as fast; past that there is nothing recognisable left of it. The
     * octave dial reaches +/-2 on its own, so this only ever bites when a
     * progression pushes it further. */
    return Math.max(-24, Math.min(24, want));
  }

  function sixteenPitch(index) {
    /* The semitone is already an interval FROM the sample, so this is the
     * whole of the conversion. */
    return Math.pow(2, sixteenSemitone(index) / 12);
  }

  /* The pad's stored tune, for the ledger. A pad can be tuned in the trim
   * editor and it changes how long it takes to play. */
  function padPitch(index) {
    const meta = layout[bank][index];
    const pitch = meta && Number(meta.pitch);
    return isFinite(pitch) && pitch > 0 ? pitch : 1;
  }

  function repeatInterval() {
    const beat = 60 / Math.max(20, Math.min(300, modes.bpm));
    return (beat * 4 / Math.max(1, modes.division)) * 1000;
  }

  function press(index, event) {
    const audio = engine();
    if (!audio) return;
    const element = el("pad-" + index);
    const sourceIndex = modes.sixteen ? selected : index;
    const key = padKey(bank, sourceIndex);
    if (!audio.loaded(key)) return;

    const options = {
      velocity: velocityFrom(event, element),
      gate: modes.gate,
      pitch: modes.sixteen ? sixteenPitch(index) : undefined
    };

    /* "Whenever I tap on a sample pad, the broadcast is muted while it is
     * playing the sample pad, allowing me to play the sample pad without
     * audio interference." On by default - see sampler-air.js. */
    duckForPads();

    const pitch = modes.sixteen ? sixteenPitch(index) : undefined;
    const fire = () => audio.fire(key, options);
    const voiceId = fire();
    began(voiceId, sourceIndex, key,
      pitch === undefined ? padPitch(sourceIndex) : pitch,
      modes.gate || (layout[bank][sourceIndex] || {}).loop);
    const record = { voiceId, repeatTimer: null };
    if (modes.repeat) {
      record.repeatTimer = setInterval(() => {
        const previous = held.get(index);
        if (previous && previous.voiceId && modes.gate) audio.release(previous.voiceId);
        if (previous) ended(previous.voiceId);
        const next = fire();
        began(next, sourceIndex, key,
          pitch === undefined ? padPitch(sourceIndex) : pitch,
          modes.gate || (layout[bank][sourceIndex] || {}).loop);
        if (previous) previous.voiceId = next;
      }, repeatInterval());
    }
    held.set(index, record);
    if (element) element.classList.add("lit");
    if (!modes.sixteen) select(index);
  }

  /* THE BROADCAST COMES BACK WHEN THE LAST VOICE DIES, not when the finger
   * lifts: a one-shot outlives the press that started it, so counting
   * presses would unduck over the top of a pad still sounding. The engine
   * is asked how many voices are live instead. */
  let unduckTimer = 0;
  function duckForPads() {
    const air = root.PineAir;
    if (!air) return;
    air.duck('pad');
    if (unduckTimer) return;
    unduckTimer = setInterval(() => {
      if (stillSounding().length > 0 || held.size > 0) return;
      clearInterval(unduckTimer);
      unduckTimer = 0;
      air.release('pad');
    }, 120);
  }

  function lift(index) {
    const record = held.get(index);
    held.delete(index);
    const element = el("pad-" + index);
    if (element) element.classList.remove("lit");
    if (!record) return;
    if (record.repeatTimer) clearInterval(record.repeatTimer);
    if (modes.gate && record.voiceId) {
      engine().release(record.voiceId);
      ended(record.voiceId);
    }
  }

  /* WHO WANTS TO KNOW WHEN THE PAD OR THE BANK CHANGES.
   *
   * The face - the knob row and the edit sheet - has to follow the selection,
   * and polling for it would be a timer running all day to catch something
   * that happens when a finger moves. */
  const watchers = [];
  function told() {
    for (const fn of watchers) {
      try { fn(bank, selected); } catch (err) { /* one bad watcher, not all */ }
    }
  }

  function select(index) {
    selected = index;
    document.querySelectorAll(".pb-pad").forEach((element) => {
      element.classList.toggle("selected", Number(element.dataset.pad) === index);
    });
    told();
  }

  /* ---------------------------------------------------------------- chop */

  /* CHOP IS NOT A MODE, AND THAT WAS THE BUG.
   *
   * "On the sampler, I am stuck in chop mode. I need the ability to exit
   * chop mode and go back to general sampler mode."
   *
   * There never was a chop mode to be in. CHOP is one destructive action:
   * it takes the selected pad and writes sixteen slices of it across the
   * whole bank, over whatever was there. But it sat in the row of toggles
   * wearing the same button as POLY and GATE, so it READ as a mode - and
   * once every pad said "[3/16]" there was no way back, which is exactly
   * what being stuck in a mode feels like.
   *
   * Two things fix it, and both are needed:
   *
   *   1. The bank is snapshotted first, so a second press puts it back.
   *      A destructive action with no undo does not belong under a thumb.
   *   2. The button says what it will do next - CHOP, then UNCHOP - and is
   *      drawn as an action rather than a toggle, so it never again looks
   *      like a state the sampler is sitting in.
   *
   * The snapshot holds the bytes, not just the labels: the chop overwrites
   * the other pads' records in the store, so a layout-only undo would
   * restore fifteen names in front of the wrong audio. */
  let chopUndo = null;

  /* Is this bank chopped RIGHT NOW?
   *
   * Read off the layout rather than remembered, because a remembered answer
   * is gone after a reload and the operator is still looking at sixteen
   * slices. Two or more pads carrying choke "chop" is the signature the
   * chop itself writes, and nothing else writes it. */
  function choppedBank(which) {
    const rows = layout[which] || [];
    const slices = [];
    for (let p = 0; p < PADS; p += 1) {
      const meta = rows[p];
      if (meta && meta.choke === "chop") slices.push(p);
    }
    return slices.length > 1 ? slices : null;
  }

  function chopping() {
    if (chopUndo && chopUndo.bank === bank) return true;
    return !!choppedBank(bank);
  }

  async function snapshotBank(which) {
    const shot = {bank: which, layout: JSON.parse(JSON.stringify(layout[which])),
      records: []};
    for (let p = 0; p < PADS; p += 1) {
      const key = padKey(which, p);
      /* An empty pad is recorded as a null, not skipped: putting the bank
       * back means emptying what the chop filled, too. */
      shot.records.push({pad: p, record: layout[which][p] ? await dbGet(key) : null});
    }
    return shot;
  }

  /* Collapse a chopped bank back to the one piece of audio it was made of.
   *
   * Used when there is no snapshot - after a reload, or for a chop made
   * before the snapshot existed. Every slice shares the same bytes, so the
   * whole recording is still there: keep the first pad, give it back the
   * full trim, and clear the other fifteen. The pads that the chop
   * OVERWROTE cannot come back this way - that is what the snapshot is for -
   * and the note says so rather than implying a full undo. */
  async function unchopByShape(slices) {
    const keep = slices[0];
    const meta = layout[bank][keep] || {};
    const whole = Object.assign({}, meta, {
      label: String(meta.label || "chop").replace(/\s*\[\d+\/\d+\]\s*$/, ""),
      trim: null,
      seconds: 0,
      choke: ""
    });
    for (const p of slices) {
      if (p === keep) continue;
      const key = padKey(bank, p);
      engine().clear(key);
      await dbDelete(key);
      layout[bank][p] = null;
    }
    layout[bank][keep] = whole;
    saveLayout();
    await preload(bank);
    applySettings(padKey(bank, keep), whole);
    paintPads();
    paintControls();
    note("Out of chop. Pad " + (keep + 1) + " holds the whole recording again; "
      + "the other slices are cleared.");
  }

  async function unchop() {
    const shot = chopUndo;
    if (!shot) {
      /* No snapshot - but the bank still says it is chopped, and the
       * operator still needs a way out. */
      const slices = choppedBank(bank);
      if (slices) await unchopByShape(slices);
      return;
    }
    chopUndo = null;
    for (const {pad, record} of shot.records) {
      const key = padKey(shot.bank, pad);
      engine().clear(key);
      if (record && record.bytes) {
        await dbPut(key, record);
      } else {
        await dbDelete(key);
      }
    }
    layout[shot.bank] = shot.layout;
    saveLayout();
    /* preload re-decodes from the restored records and repaints. */
    await preload(shot.bank);
    paintControls();
    note("Put the bank back the way it was before the chop.");
  }

  /* Slice the selected pad across the whole grid. This is how thirty
   * seconds of air becomes sixteen playable pieces. */
  async function chop() {
    if (chopping()) { await unchop(); return; }
    const from = padKey(bank, selected);
    const meta = layout[bank][selected];
    if (!meta || !engine().loaded(from)) {
      note("Select a loaded pad to chop.", true);
      return;
    }
    const record = await dbGet(from);
    if (!record) { note("That pad's bytes are missing.", true); return; }
    const undo = await snapshotBank(bank);
    const total = engine().seconds(from);
    const segment = total / PADS;
    for (let p = 0; p < PADS; p += 1) {
      const key = padKey(bank, p);
      if (p !== selected) {
        engine().copy(from, key);
        await dbPut(key, record);
      }
      const slice = Object.assign({}, meta, {
        label: (meta.label || "chop") + " [" + (p + 1) + "/" + PADS + "]",
        trim: { start: p * segment, end: (p + 1) * segment },
        seconds: segment,
        choke: "chop"
      });
      layout[bank][p] = slice;
      applySettings(key, slice);
    }
    chopUndo = undo;
    saveLayout();
    paintPads();
    paintControls();
    note("Chopped " + total.toFixed(2) + "s across " + PADS
      + " pads. Press UNCHOP to put the bank back.");
  }


  /* ---------------------------------------------------------------- carry
   *
   * DRAGGING A CLIP ONTO A PAD, WITH A FINGER.
   *
   * The first version used HTML5 drag-and-drop - draggable="true",
   * dragstart, dragover, drop. That works with a mouse and is COMPLETELY
   * INERT under touch: those events are mouse-only, so on the tablet - the
   * one device this is for - not a single clip could be moved.
   *
   * Pointer events cover both, so there is one path here and the mouse gets
   * the same code the finger does.
   *
   * The awkward part is that the feed is a scrolling list, and a finger
   * dragging across a row is ambiguous: scroll, or carry? Resolved by
   * DIRECTION, decided once, on the first few pixels of movement:
   *
   *   mostly vertical  -> it is a scroll. Let go of it entirely; the list
   *                       scrolls natively, which is smoother than anything
   *                       re-implemented here.
   *   mostly horizontal -> it is a carry. The pads are to the right of the
   *                       feed, so this is the direction the operator is
   *                       already moving in.
   *
   * `touch-action: pan-y` on a row tells the browser the same thing, so the
   * vertical case never waits on JavaScript.
   */

  const CARRY_SLOP = 8;          /* px before a gesture commits either way */
  let carry = null;

  function carryGhost(row) {
    /* A TILE, NOT A STRIP OF TEXT.
     *
     * "When I drag it I want it converted into a sampler tile so I can drag
     *  it over to the sampler instead of it being a strip of text."
     *
     * It is built to the same shape as a pad - square, numbered corner,
     * label at the foot - so what the hand is carrying looks like the thing
     * it is about to become. */
    const ghost = document.createElement("div");
    ghost.className = "pb-ghost";
    const who = document.createElement("i");
    who.textContent = row.name || row.who || row.kind || "take";
    const said = document.createElement("span");
    said.textContent = (row.text || row.name || "take").slice(0, 70);
    ghost.appendChild(who);
    ghost.appendChild(said);
    document.body.appendChild(ghost);
    return ghost;
  }

  function padUnder(x, y) {
    /* The ghost follows the finger, so it is what elementFromPoint would
     * find. Hide it for the hit test rather than offsetting guesses. */
    if (carry && carry.ghost) carry.ghost.style.display = "none";
    const under = document.elementFromPoint(x, y);
    if (carry && carry.ghost) carry.ghost.style.display = "";
    return under ? under.closest(".pb-pad") : null;
  }

  function carryMove(event) {
    if (!carry) return;
    const dx = event.clientX - carry.x0;
    const dy = event.clientY - carry.y0;

    if (!carry.committed) {
      if (Math.abs(dx) < CARRY_SLOP && Math.abs(dy) < CARRY_SLOP) return;
      if (Math.abs(dy) > Math.abs(dx)) { carry.scrolling = true; }
      else {
        carry.committed = true;
        carry.ghost = carryGhost(carry.row);
        carry.item.classList.add("lifting");
      }
    }

    /* MEASURED, and the reason the rows own their gesture outright.
     *
     * With `touch-action: pan-y` the browser may pan, and once it decides
     * to it TAKES THE WHOLE GESTURE: a real finger drag across a row
     * delivered 14 touchmove events but only ONE pointermove and no
     * pointerup at all - Chromium had fired pointercancel and gone
     * scrolling. Nothing could ever be carried.
     *
     * So the rows are `touch-action: none` and the vertical case is done
     * here by hand. It is a few lines, and it is the difference between a
     * list you can drag from and one you cannot. */
    if (carry.scrolling) {
      const list = el("pbFeed");
      if (list) {
        list.scrollTop = carry.scroll0 - dy;
        carry.item.classList.remove("lifting");
      }
      return;
    }

    event.preventDefault();
    carry.ghost.style.transform =
      "translate(" + (event.clientX + 12) + "px," + (event.clientY - 18) + "px)";

    const pad = padUnder(event.clientX, event.clientY);
    if (pad !== carry.over) {
      if (carry.over) carry.over.classList.remove("over");
      if (pad) pad.classList.add("over");
      carry.over = pad;
    }
  }

  function carryEnd(event) {
    if (!carry) return;
    const held = carry;
    carry = null;
    if (held.ghost) held.ghost.remove();
    held.item.classList.remove("lifting");
    if (held.over) held.over.classList.remove("over");
    try { held.item.releasePointerCapture(held.pointerId); } catch (err) { /* gone */ }
    if (!held.committed || !event) return;
    const pad = padUnder(event.clientX, event.clientY);
    if (pad) importRow(held.row, bank, Number(pad.dataset.pad));
  }

  function carryStart(event, item, row) {
    if (!sourceFor(row)) return;            /* nothing behind it to carry */
    if (event.button !== undefined && event.button !== 0) return;
    const list = el("pbFeed");
    carry = {
      row, item, over: null, ghost: null, committed: false, scrolling: false,
      x0: event.clientX, y0: event.clientY, pointerId: event.pointerId,
      scroll0: list ? list.scrollTop : 0
    };
    /* Capture so the gesture survives leaving the row - which it must, or
     * the carry dies the moment the finger crosses into the pad grid. */
    try { item.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
  }

  /* --------------------------------------------------------------- paint */

  function note(text, bad) {
    const element = el("pbNote");
    if (!element) return;
    element.textContent = text;
    element.classList.toggle("bad", !!bad);
  }

  /* The footprint is on screen because it is genuinely surprising: a
   * single booth turn off this station measured 62.97s, which decodes to
   * roughly 12 MB. Sixteen of those is a quarter of a gigabyte, and the
   * operator should be able to see that coming rather than meet it as a
   * stall. Trimming a pad does not shrink it - the decode is full length -
   * so the honest answer to a heavy bank is to clear pads, not to trim. */
  function footprintLine() {
    const shape = engine().footprint();
    if (!shape.pads) return "";
    const mb = shape.bytes / (1024 * 1024);
    return shape.pads + " pad" + (shape.pads === 1 ? "" : "s")
      + " resident · " + mb.toFixed(0) + " MB";
  }

  function paintBanks() {
    for (let b = 0; b < BANKS; b += 1) {
      const element = el("pbBank-" + b);
      if (!element) continue;
      element.classList.toggle("active", b === bank);
      const filled = layout[b].filter(Boolean).length;
      element.title = filled ? filled + " of " + PADS + " pads loaded" : "empty bank";
    }
  }

  /* The controls that change what they will do next. Only CHOP does, so
   * far - but it is called from the chop, the undo and every bank change,
   * because a bank is chopped or not INDEPENDENTLY of the one on screen. */
  function paintControls() {
    const button = document.getElementById("pbChop");
    if (!button) return;
    const undoable = chopping();
    button.textContent = undoable ? "UNCHOP" : "CHOP";
    button.title = undoable
      ? "Put this bank back the way it was before the chop"
      : "Slice the selected pad across all sixteen pads";
    button.classList.toggle("armed", undoable);
  }

  function paintPads() {
    for (let p = 0; p < PADS; p += 1) {
      const element = el("pad-" + p);
      if (!element) continue;
      const meta = layout[bank][p];
      const loaded = !!meta && engine().loaded(padKey(bank, p));
      element.classList.toggle("filled", !!meta);
      element.classList.toggle("cold", !!meta && !loaded);
      element.classList.toggle("inexact", !!meta && meta.exact === false);
      const label = element.querySelector(".pb-pad-label");
      const sub = element.querySelector(".pb-pad-sub");
      if (label) label.textContent = meta ? meta.label : "";
      if (sub) {
        sub.textContent = meta
          ? [meta.who, meta.seconds ? meta.seconds.toFixed(1) + "s" : "",
             meta.loop ? "loop" : "", meta.reverse ? "rev" : ""]
            .filter(Boolean).join(" · ")
          : "";
      }
      element.title = meta
        ? (meta.label + (meta.cut ? "\n\n" + meta.cut : ""))
        : "Tap to grab what just played, or hold to take the air right now";
    }
    paintSixteen();
    const foot = el("pbFoot");
    if (foot) foot.textContent = footprintLine();

    paintBanks();
    told();
  }

  /* ------------------------------------------------------------- kits */

  /* PRESETS AND FILES ARE THE SAME OBJECT, deliberately. A preset is a kit
   * kept in the browser; an export is the same kit written out. So a preset
   * can be exported, and an imported file can be kept as a preset, without
   * any conversion step for the operator to think about. */
  let kitSheet = null;
  /* PineDismiss.watch hands back an unwatch and it must be used: every open
   * would otherwise leave a live entry behind holding this sheet and its
   * close. They are inert (showing() checks isConnected) but they accumulate
   * for the life of the page, and a list of dead watchers is walked on every
   * pointerdown in the app. */
  let unwatchKits = null;

  function closeKits() {
    if (unwatchKits) { unwatchKits(); unwatchKits = null; }
    if (kitSheet) { kitSheet.remove(); kitSheet = null; }
  }

  async function openKits() {
    closeKits();
    const kits = root.PineSamplerKits;
    if (!kits) { note("Presets are not loaded on this terminal."); return; }

    kitSheet = document.createElement("div");
    kitSheet.className = "pb-kits";

    const head = document.createElement("div");
    head.className = "pb-kits-head";
    const title = document.createElement("b");
    title.textContent = "Presets";
    const shut = document.createElement("button");
    shut.className = "pb-kits-x";
    shut.textContent = "\u00d7";
    shut.addEventListener("click", closeKits);
    head.appendChild(title);
    head.appendChild(shut);
    kitSheet.appendChild(head);

    const said = document.createElement("p");
    said.className = "pb-kits-say";
    said.textContent = "A preset carries the AUDIO, not links to it - so it "
      + "still plays when the station is off, and after the 48-hour sweep.";
    kitSheet.appendChild(said);

    const saved = document.createElement("div");
    saved.className = "pb-kits-list";
    kitSheet.appendChild(saved);

    const acts = document.createElement("div");
    acts.className = "pb-kits-acts";
    acts.appendChild(kitAct("Save this bank", async () => {
      const name = prompt("Name this preset", kits.defaultName(bank));
      if (!name) return;
      await kits.save(name, bank);
      note("Preset saved: " + name);
      await fillKits(saved);
    }));
    acts.appendChild(kitAct("Save all five banks", async () => {
      const name = prompt("Name this preset", kits.defaultName(null));
      if (!name) return;
      await kits.save(name, null);
      note("Preset saved: " + name);
      await fillKits(saved);
    }));
    acts.appendChild(kitAct("Export this bank to a file", async () => {
      const got = await kits.exportKit(bank, kits.defaultName(bank));
      note(got.ok ? "Exported to " + got.where : "It would not export.");
    }));
    acts.appendChild(kitAct("Export all five to a file", async () => {
      const got = await kits.exportKit(null, kits.defaultName(null));
      note(got.ok ? "Exported to " + got.where : "It would not export.");
    }));
    /* THE HARDWARE DOOR. A folder of WAVs beside an .xpm program, which is
     * what an MPC reads - see sampler-kits.js for what is certain about it
     * and what is not. Seventeen files and tens of megabytes, so it reports
     * as it goes rather than appearing to hang. */
    acts.appendChild(kitAct("Export as an MPC kit", async () => {
      const name = prompt("Name this kit (it becomes the MPC program name)",
        "Pine Box bank " + (bank + 1));
      if (!name) return;
      note("Building the MPC kit…");
      const got = await root.PineSamplerKits.exportMpc(bank, name, (where) => {
        note("MPC kit: " + where);
      });
      note(got.ok
        ? "MPC kit written: " + got.pads + " pads in Downloads/" + got.folder
          + " - copy the whole folder to the MPC and open " + got.program
        : "The MPC kit could not be written.");
    }));
    /* STRAIGHT ONTO THE MPC. It exports first and then copies: the kit is
     * built and verified on local storage either way, and a card that is
     * unplugged halfway through leaves the good copy behind. */
    acts.appendChild(kitAct("Send this bank to the MPC over USB", async () => {
      const bridge = root.pineDesktop;
      if (!bridge || typeof bridge.usbState !== "function") {
        note("This terminal cannot reach a USB disk.");
        return;
      }
      let state = await bridge.usbState();
      if (!state.chosen) {
        if (!state.anyRemovable) {
          note("No USB disk is attached. Put the MPC in USB mode and connect "
            + "it with an OTG or USB-C cable, then try again.");
          return;
        }
        note("Point at the MPC’s disk…");
        const picked = await bridge.usbPick();
        if (!picked.ok) { note("No disk was chosen."); return; }
        state = await bridge.usbState();
      }
      const name = prompt("Name this kit (it becomes the MPC program name)",
        "Pine Box bank " + (bank + 1));
      if (!name) return;
      note("Building the kit…");
      const built = await root.PineSamplerKits.exportMpc(bank, name, (where) => {
        note("MPC kit: " + where);
      });
      if (!built.ok) {
        note("The kit could not be built: " + (built.detail || "unknown"));
        return;
      }
      note("Copying to " + (state.name || "the disk") + "…");
      const sent = await bridge.usbSend({folder: built.folder});
      note(sent.ok
        ? "Sent " + sent.files + " files to " + sent.where
          + " - open " + built.program + " on the MPC"
        : "The copy failed: " + (sent.detail || "unknown"));
    }));
    /* THE DISK ITSELF. Browsing it is the other half of "have it viewed as a
     * mass media drive" - writing to it was never enough on its own, because
     * the kits worth loading are the ones already on the card. */
    acts.appendChild(kitAct("Open the MPC disk", async () => {
      await openMpcDisk();
    }));
    acts.appendChild(kitAct("Import a kit file", async () => {
      try {
        const kit = await kits.importFile();
        const only = Object.keys(kit.banks || {}).length === 1;
        const got = await kits.apply(kit, only ? bank : null, false);
        note("Loaded " + got.pads + " pads"
          + (got.missing ? " - " + got.missing + " had no audio in the file" : ""));
        await preload(bank);
        closeKits();
      } catch (err) {
        note("Import failed: " + ((err && err.message) || err));
      }
    }));
    kitSheet.appendChild(acts);

    document.body.appendChild(kitSheet);
    if (root.PineDismiss) unwatchKits = root.PineDismiss.watch(kitSheet, closeKits, []);
    await fillKits(saved);
  }

  /* ------------------------------------------------- browsing the MPC disk */

  let diskSheet = null;
  let unwatchDisk = null;

  function closeDisk() {
    if (unwatchDisk) { unwatchDisk(); unwatchDisk = null; }
    if (diskSheet) { diskSheet.remove(); diskSheet = null; }
  }

  async function openMpcDisk() {
    const api = root.pineDesktop;
    if (!api || typeof api.usbList !== "function") {
      note("This terminal cannot read a USB disk.");
      return;
    }
    const state = await api.usbState();

    /* THREE DIFFERENT "NOTHING HAPPENED"s, each with its own cure. Guessing
     * between them is what makes a USB feature feel broken. */
    if (!state.canHost) {
      note("This tablet cannot act as a USB host, so it cannot read the MPC.");
      return;
    }
    if (!state.chosen) {
      if (!state.anyRemovable) {
        note("No disk is mounted. Put the MPC in USB mode, connect it with an "
          + "OTG or USB-C cable, and give it a moment to appear.");
        return;
      }
      note("Point at the MPC\u2019s disk\u2026");
      const picked = await api.usbPick();
      if (!picked.ok) { note("No disk was chosen."); return; }
    }
    closeKits();
    showDisk("");
  }

  async function showDisk(path) {
    closeDisk();
    diskSheet = document.createElement("div");
    diskSheet.className = "pb-kits pb-disk";

    const head = document.createElement("div");
    head.className = "pb-kits-head";
    const title = document.createElement("b");
    title.textContent = path ? path : "the MPC disk";
    const shut = document.createElement("button");
    shut.className = "pb-kits-x";
    shut.textContent = "\u00d7";
    shut.addEventListener("click", closeDisk);
    head.appendChild(title);
    head.appendChild(shut);
    diskSheet.appendChild(head);

    const say = document.createElement("p");
    say.className = "pb-kits-say";
    say.textContent = "reading\u2026";
    diskSheet.appendChild(say);

    const list = document.createElement("div");
    list.className = "pb-kits-list";
    diskSheet.appendChild(list);

    document.body.appendChild(diskSheet);
    if (root.PineDismiss) unwatchDisk = root.PineDismiss.watch(diskSheet, closeDisk, []);

    let got;
    try { got = await root.PineSamplerKits.browse(path); }
    catch (err) { got = {ok: false, detail: (err && err.message) || err}; }
    if (!got || !got.ok) {
      say.textContent = (got && got.detail) || "that folder would not open";
      return;
    }

    const folders = got.folders || [];
    const files = got.files || [];
    const kits = folders.filter((row) => row.program);
    say.textContent = kits.length
      ? kits.length + " kit" + (kits.length === 1 ? "" : "s") + " here"
      : folders.length + " folders, " + files.length + " files";

    /* Up one, unless we are already at the top of the disk. */
    if (path) {
      const up = document.createElement("button");
      up.className = "pb-kits-load";
      up.textContent = "\u2191 up";
      up.addEventListener("click", () => showDisk(path.split("/").slice(0, -1).join("/")));
      list.appendChild(up);
    }

    for (const row of folders) {
      const here = path ? path + "/" + row.name : row.name;
      const line = document.createElement("div");
      line.className = "pb-kits-row";
      const open = document.createElement("button");
      open.className = "pb-kits-load";
      /* A FOLDER THAT HOLDS A PROGRAM IS LABELLED AS A KIT, so the operator
       * is not opening folders one at a time to find out which are kits -
       * the listing already answered that question. */
      open.textContent = (row.program ? "\u25a0 " : "\u25b8 ") + row.name
        + (row.program ? "  \u00b7 " + row.program : "");
      open.addEventListener("click", () => showDisk(here));
      line.appendChild(open);
      if (row.program) {
        const load = document.createElement("button");
        load.className = "pb-kits-drop";
        load.style.width = "68px";
        load.textContent = "load";
        load.title = "Load this kit onto bank " + (bank + 1);
        load.addEventListener("click", async (event) => {
          event.stopPropagation();
          await loadFromDisk(here, load);
        });
        line.appendChild(load);
      }
      list.appendChild(line);
    }

    if (!folders.length && !files.length) {
      const none = document.createElement("p");
      none.className = "pb-kits-none";
      none.textContent = "Nothing here.";
      list.appendChild(none);
    }
  }

  async function loadFromDisk(folder, button) {
    const held = layout[bank].filter(Boolean).length;
    if (held && !root.confirm(
      "Load this kit onto bank " + (bank + 1) + "?\n\n"
      + "It has " + held + " pad" + (held === 1 ? "" : "s") + " on it, and any "
      + "pad the kit fills will be replaced.")) return;
    button.disabled = true;
    const bar = root.PineBusy ? root.PineBusy.attach(button, "loading") : null;
    try {
      const got = await root.PineSamplerKits.importMpc(folder, bank, (where) => {
        note("MPC: " + where);
      });
      if (bar) bar.finish(got.ok);
      await preload(bank);
      note(got.ok
        ? "Loaded " + got.pads + " pads from " + got.name
          + (got.missing.length
            ? " \u00b7 " + got.missing.length + " sample"
              + (got.missing.length === 1 ? "" : "s") + " were not on the disk"
            : "")
        : "Nothing in that kit could be loaded.", !got.ok);
      if (got.ok) closeDisk();
    } catch (err) {
      if (bar) bar.finish(false);
      note("That kit would not load: " + ((err && err.message) || err), true);
    } finally {
      button.disabled = false;
    }
  }

  function kitAct(words, run) {
    const button = document.createElement("button");
    button.className = "pb-kits-act";
    button.textContent = words;
    button.addEventListener("click", async () => {
      button.disabled = true;
      const bar = root.PineBusy ? root.PineBusy.attach(button, "working") : null;
      try { await run(); if (bar) bar.finish(true); }
      catch (err) {
        if (bar) bar.finish(false);
        note(((err && err.message) || err));
      } finally { button.disabled = false; }
    });
    return button;
  }

  async function fillKits(into) {
    const kits = root.PineSamplerKits;
    into.innerHTML = "";
    let saved = [];
    try { saved = await kits.list(); } catch (err) { saved = []; }
    if (!saved.length) {
      const none = document.createElement("p");
      none.className = "pb-kits-none";
      none.textContent = "No presets kept yet.";
      into.appendChild(none);
      return;
    }
    for (const name of saved) {
      const row = document.createElement("div");
      row.className = "pb-kits-row";
      const load = document.createElement("button");
      load.className = "pb-kits-load";
      load.textContent = String(name);
      load.addEventListener("click", async () => {
        const bar = root.PineBusy ? root.PineBusy.attach(load, "loading") : null;
        try {
          const kit = await kits.load(name);
          const only = Object.keys(kit.banks || {}).length === 1;
          const got = await kits.apply(kit, only ? bank : null, false);
          if (bar) bar.finish(true);
          note("Loaded " + got.pads + " pads from " + name
            + (got.missing ? " - " + got.missing + " had no audio" : ""));
          await preload(bank);
          closeKits();
        } catch (err) {
          if (bar) bar.finish(false);
          note("That preset would not load: " + ((err && err.message) || err));
        }
      });
      const kill = document.createElement("button");
      kill.className = "pb-kits-drop";
      kill.textContent = "\u00d7";
      kill.title = "Forget this preset";
      kill.addEventListener("click", async () => {
        await kits.forget(name);
        await fillKits(into);
      });
      row.appendChild(load);
      row.appendChild(kill);
      into.appendChild(row);
    }
  }

  /* ------------------------------------------------------- what is sounding
   *
   * THE VIEW KEEPS ITS OWN LIST OF VOICES, and it has to, because there are
   * TWO engines behind this seam and only one of them can answer.
   *
   *   web audio   sampler-engine.js, used on the desktop. Knows everything.
   *   oboe        the native terminal engine, which is what the TABLET runs
   *               (measured: window.pineSampler.backend === "oboe"). Its
   *               bridge publishes 24 methods and none of them is `active`
   *               or `playing` - levels() reports a voice COUNT and nothing
   *               per voice.
   *
   * So the timeline and the pad-solo duck were both written against methods
   * that do not exist on the device they were written for. Rather than push
   * a per-voice report down through the JNI and the C++ core for a progress
   * bar, the view records what it started: it knows the pad, the length, the
   * pitch and the moment, which is everything a playhead needs.
   *
   * THE CLOCK IS performance.now(), not the audio clock. A few milliseconds
   * of drift over an eight-second bar is invisible; reaching for the audio
   * clock would mean having one, and the native engine does not lend one. */
  const sounding = new Map();   /* voiceId -> {padId, at, length, open} */

  /* How long this pad will actually take at this pitch. `seconds()` is the
   * whole recording; a trimmed pad plays only its window, and a pad played
   * an octave up finishes in half the time - a bar that ignored either would
   * be wrong exactly when 16 LEVEL or the trim editor is in use. */
  function willTake(key, index, pitch) {
    const audio = engine();
    let length = 0;
    try { length = Number(audio.seconds(key)) || 0; } catch (err) { length = 0; }
    const meta = layout[bank][index];
    if (meta && meta.trim) {
      const from = Math.max(0, Number(meta.trim.start) || 0);
      const to = Math.min(length || Infinity, Number(meta.trim.end) || length);
      if (to > from) length = to - from;
    }
    const rate = isFinite(pitch) && pitch > 0 ? pitch : 1;
    return length / rate;
  }

  function began(voiceId, index, key, pitch, open) {
    if (!voiceId) return;
    sounding.set(voiceId, {
      padId: index,
      at: performance.now(),
      length: willTake(key, index, pitch),
      open: !!open
    });
    startTimeline();
  }

  function ended(voiceId) {
    if (voiceId) sounding.delete(voiceId);
  }

  /* Everything still sounding, in the shape the timeline draws. A one-shot
   * retires itself when its length is up: nothing tells the view that a
   * voice finished, and a lane that never cleared would say a pad was
   * playing long after the room went quiet. */
  function stillSounding() {
    const now = performance.now();
    const out = [];
    sounding.forEach((voice, id) => {
      const done = (now - voice.at) / 1000;
      if (!voice.open && done >= voice.length + 0.08) {
        sounding.delete(id);
        return;
      }
      out.push({
        id: id,
        padId: voice.padId,
        open: voice.open,
        done: done,
        seconds: voice.open ? done : voice.length,
        at: voice.open ? -1 : Math.max(0, Math.min(1, done / Math.max(0.001, voice.length)))
      });
    });
    return out;
  }

  /* ----------------------------------------------------------- timeline */

  /* ONE rAF LOOP, AND ONLY WHILE SOMETHING IS SOUNDING.
   *
   * This panel already keeps about eleven WebGL canvases running, which is
   * the whole of its remaining input delay - measured at 40-210 ms per
   * touch. A twelfth animation that ran all day for a grid that is silent
   * most of the time would be a straight subtraction from that. So the loop
   * starts on the first press and stops itself the moment the engine reports
   * no voices.
   *
   * The clock is the ENGINE's, read through active(): the AudioContext clock
   * is what the sound is actually scheduled against, so a bar driven by it
   * cannot drift away from what is being heard - which a Date.now() bar
   * would, and worst on a busy main thread, exactly when it is most visible. */
  let timeTimer = 0;

  function startTimeline() {
    if (timeTimer) return;
    const strip = el("pbTime");
    if (!strip) return;
    const step = () => {
      const live = stillSounding();
      paintTimeline(strip, live);
      if (!live.length) {
        timeTimer = 0;
        strip.hidden = true;
        strip.innerHTML = "";
        return;
      }
      timeTimer = requestAnimationFrame(step);
    };
    timeTimer = requestAnimationFrame(step);
  }

  function paintTimeline(strip, live) {
    if (!live.length) return;
    strip.hidden = false;
    /* A LANE PER SOUNDING PAD. Pads layer - that is what POLY is for - and
     * one bar showing only the newest would hide the fact. Lanes are keyed
     * by voice id so a retrigger does not make the bar jump backwards
     * through a lane that belongs to a voice still running. */
    const want = Object.create(null);
    for (const voice of live) want[voice.id] = voice;

    for (const node of [].slice.call(strip.children)) {
      if (!want[node.dataset.voice]) node.remove();
    }
    for (const voice of live) {
      let lane = strip.querySelector('[data-voice="' + voice.id + '"]');
      if (!lane) {
        lane = document.createElement("div");
        lane.className = "pb-time-lane";
        lane.dataset.voice = voice.id;
        lane.innerHTML = '<span class="pb-time-name"></span>'
          + '<i class="pb-time-rail"><b class="pb-time-fill"></b></i>'
          + '<span class="pb-time-clock"></span>';
        strip.appendChild(lane);
      }
      const pad = Number(voice.padId);
      const meta = isFinite(pad) ? layout[bank][pad] : null;
      lane.querySelector(".pb-time-name").textContent =
        (isFinite(pad) ? (pad + 1) + " " : "") + (meta ? meta.label : "").slice(0, 38);
      /* A voice with no end - a loop, or a gate still held - gets a running
       * stripe rather than a percentage. A progress bar for something that
       * does not end is a lie, and this sampler has had enough of those. */
      lane.classList.toggle("open", voice.open);
      const fill = lane.querySelector(".pb-time-fill");
      fill.style.width = voice.open ? "100%" : (voice.at * 100).toFixed(2) + "%";
      lane.querySelector(".pb-time-clock").textContent = voice.open
        ? voice.seconds.toFixed(1) + "s"
        : voice.done.toFixed(1) + " / " + voice.seconds.toFixed(1) + "s";
    }
  }

  /* ------------------------------------------------------- pad gestures */

  const HOLD_MS = 600;    /* the same hold line-actions.js uses */
  const SLOP = 12;        /* pixels that still count as standing still */
  let gesture = null;
  let bin = null;

  /* HAS SOMETHING ON IT - which is NOT the same as "ready to sound".
   *
   * A pad can carry a recording that is not decoded yet: the bank is
   * preloaded from IndexedDB at mount, a bank switch reloads in the
   * background, and a pad whose decode failed once stays cold until it is
   * pressed. paintPads has always drawn those with `.cold`.
   *
   * The gesture must key on CONTENT, not on readiness. Keying it on
   * `engine().loaded` - which is what this did at first - meant tapping a
   * pad that visibly holds a line opened the "put something on this pad"
   * window, and dragging it produced no bin. Measured exactly that on the
   * tablet: pad 1 held a line and answered loaded=false. */
  function hasContent(index) {
    return !!layout[bank][index];
  }

  function loadedAt(index) {
    return hasContent(index) && engine().loaded(padKey(bank, index));
  }

  /* WARM A COLD PAD AND PLAY IT, so a press is never silently ignored.
   * The bytes are on disk; the only thing missing is the decode. */
  async function warmAndFire(index, event) {
    const key = padKey(bank, index);
    const cell = el("pad-" + index);
    const bar = root.PineBusy ? root.PineBusy.attach(cell, "warming") : null;
    try {
      const record = await dbGet(key);
      if (!record || !record.bytes) {
        if (bar) bar.finish(false);
        note("Pad " + (index + 1) + " has lost its audio - clear it and take it again.");
        return;
      }
      await engine().load(key, record.bytes);
      applySettings(key, layout[bank][index]);
      if (bar) bar.finish(true);
      paintPads();
      press(index, event);
    } catch (err) {
      if (bar) bar.finish(false);
      note("Pad " + (index + 1) + " would not load: " + ((err && err.message) || err));
    }
  }

  /* THE BIN.
   *
   * "If I click and drag on a pad, show a trash can icon that I can drag the
   * pad onto in order to clear the pad."
   *
   * It exists only while something is being carried. A permanently visible
   * delete target on a grid you hit with your thumb is an accident waiting
   * for a busy moment. */
  function showBin(from) {
    if (bin) bin.remove();
    bin = document.createElement("div");
    bin.className = "pb-bin";
    const can = document.createElement("span");
    can.className = "pb-bin-can";
    can.textContent = String.fromCodePoint(0x1F5D1);
    const say = document.createElement("span");
    say.className = "pb-bin-say";
    say.textContent = "drop to clear pad " + (from + 1);
    bin.appendChild(can);
    bin.appendChild(say);
    document.body.appendChild(bin);
    requestAnimationFrame(() => { if (bin) bin.classList.add("up"); });
  }

  function overBin(event) {
    if (!bin || !event) return false;
    const box = bin.getBoundingClientRect();
    return event.clientX >= box.left && event.clientX <= box.right
      && event.clientY >= box.top && event.clientY <= box.bottom;
  }

  function moveBin(event) {
    if (bin) bin.classList.toggle("over", overBin(event));
  }

  async function dropOnBin(index, event) {
    const hit = overBin(event);
    if (bin) { bin.remove(); bin = null; }
    if (hit) {
      /* Silence the page before the pad goes - see clearBank. */
      try { engine().stopAll(); } catch (err) { /* nothing playing */ }
      sounding.clear();
      if (root.PineAir) root.PineAir.release("pad");
      await clearPad(index);
    }
  }

  /* Clearing is a real deletion - the bytes go too, or the bank keeps paying
   * for a pad nobody can hear. UNDO holds them until the next clear, because
   * a thumb over a bin is exactly the case this has to survive. */
  let binUndo = null;
  async function clearPad(index) {
    const key = padKey(bank, index);
    const meta = layout[bank][index];
    if (!meta) return;
    let record = null;
    try { record = await dbGet(key); } catch (err) { /* gone already */ }
    binUndo = { bank: bank, pad: index, meta: meta, record: record };
    try { await dbDelete(key); } catch (err) { /* it may never have landed */ }
    try { if (engine().unload) engine().unload(key); } catch (err) { /* older engine */ }
    layout[bank][index] = null;
    saveLayout();
    paintPads();
    note("Pad " + (index + 1) + " cleared.");
    showUndo();
  }

  function showUndo() {
    const foot = el("pbNote");
    if (!foot || !binUndo) return;
    const old = foot.querySelector(".pb-undo");
    if (old) old.remove();
    const button = document.createElement("button");
    button.className = "pb-undo";
    button.textContent = "UNDO";
    button.addEventListener("click", async () => {
      const back = binUndo;
      binUndo = null;
      button.remove();
      if (!back) return;
      if (back.record && back.record.bytes) {
        await dbPut(padKey(back.bank, back.pad), back.record);
        try { await engine().load(padKey(back.bank, back.pad), back.record.bytes); }
        catch (err) { /* it will load cold on the next press */ }
      }
      layout[back.bank][back.pad] = back.meta;
      saveLayout();
      paintPads();
      note("Pad " + (back.pad + 1) + " is back.");
    });
    foot.appendChild(button);
  }

  /* ------------------------------------------------------ clearing a bank */

  async function clearBank() {
    const held = layout[bank].filter(Boolean).length;
    if (!held) { note("This bank is already empty."); return; }

    /* SILENCE FIRST. "If I clear a pad, stop playback of pads on that page."
     * Clearing while a one-shot is still sounding leaves a voice playing
     * from a pad that no longer exists, which is a sound with nothing to
     * stop it. */
    try { engine().stopAll(); } catch (err) { /* nothing playing */ }
    sounding.clear();
    if (root.PineAir) root.PineAir.release("pad");

    const keep = root.confirm(
      "Clear all " + held + " pads on bank " + (bank + 1) + "?\n\n"
      + "The audio lives on this tablet - the station keeps references, not "
      + "recordings - so this cannot be undone.\n\n"
      + "OK to clear. Cancel to keep them.");
    if (!keep) { note("Nothing cleared."); return; }

    /* AND THE OFFER TO SAVE IT, at the only moment it can still be taken. */
    if (root.PineSamplerKits && root.confirm(
      "Save this bank out first, so it can be used on the MPC?\n\n"
      + "OK writes a kit - a folder of WAVs beside an .xpm program - to "
      + "Downloads. Cancel clears without saving.")) {
      const name = root.prompt("Name this kit",
        "Pine Box bank " + (bank + 1)) || ("Pine Box bank " + (bank + 1));
      note("Writing the kit\u2026");
      try {
        const got = await root.PineSamplerKits.exportMpc(bank, name, (where) => {
          note("kit: " + where);
        });
        if (!got.ok) {
          note("The kit could not be written, so nothing was cleared: "
            + (got.detail || "unknown"), true);
          return;                       /* refuse to clear what we could not keep */
        }
        note("Kit written to Downloads/" + got.folder);
      } catch (err) {
        note("The kit failed, so nothing was cleared: "
          + ((err && err.message) || err), true);
        return;
      }
    }

    for (let p = 0; p < PADS; p += 1) {
      if (!layout[bank][p]) continue;
      const key = padKey(bank, p);
      try { await dbDelete(key); } catch (err) { /* may never have landed */ }
      try { if (engine().unload) engine().unload(key); } catch (err) { /* older */ }
      layout[bank][p] = null;
    }
    binUndo = null;                     /* nothing here to put back any more */
    saveLayout();
    paintPads();
    note("Bank " + (bank + 1) + " cleared.");
  }

  /* ------------------------------------------------- sampling the air */

  /* HOLD AN EMPTY PAD: the broadcast, as it sounds right now.
   *
   * "Sample the current playing broadcast to the pad" - and "capture it at
   * the current levels and the current audio", which is why this comes out
   * of the tap in sampler-air.js rather than out of the station's files.
   *
   * It takes the seconds BEHIND the press, not after it: the operator hears
   * something good and then reaches for a pad, so the moment worth keeping
   * is already over by the time the finger lands. */
  const LIVE_TAKE_S = 8;

  async function sampleAirNow(index) {
    const air = root.PineAir;
    const cell = el("pad-" + index);
    if (!air || !air.ready()) {
      note("Cannot sample the air: " + (air ? air.why() : "the tap is not loaded"));
      return;
    }
    /* THE VOICES, NOT THE ROOM.
     *
     * "The samples I am capturing appear to overlap - it is recording
     *  multiple clips on top of each other."
     *
     * Nothing was being recorded twice; the MIX simply has several things in
     * it at once, and this station usually does. A pad grab wants what they
     * SAID, so it takes the voices ring where there is one and falls back to
     * the mix where there is not - a terminal whose panel never built an
     * analyser for a voice player would otherwise get silence. */
    const voicesOnly = typeof air.haveVoices === "function" && air.haveVoices();
    const take = Math.min(LIVE_TAKE_S,
      voicesOnly ? air.seconds(true) : air.seconds());
    if (take < 0.4) {
      note("There is not enough broadcast held yet - give it a few seconds.");
      return;
    }
    /* NOTHING TO HEAR IS NOT THE SAME AS A BROKEN FEATURE, and the operator
     * is owed the difference. The ring fills on the clock whether or not
     * anything is playing, so without this a hold during a quiet stretch put
     * eight seconds of digital silence on a pad and looked like a fault.
     * Measured that way once: peak 0.0037, rms 0.00118. */
    if (!voicesOnly && typeof air.quiet === "function" && air.quiet(take, 0)) {
      note("That stretch was silent - nothing is playing on this terminal "
        + "right now. Check the broadcast is coming here before holding a pad.");
      return;
    }
    if (cell) cell.classList.add("loading");
    const bar = root.PineBusy ? root.PineBusy.attach(cell, "taking the air") : null;
    try {
      const bytes = air.sliceWav(take, 0, voicesOnly);
      if (!bytes) throw new Error("the buffer would not give up that window");
      await putBytesOnPad(index, bytes, {
        label: "air " + take.toFixed(1) + "s",
        who: "broadcast", kind: "air",
        cut: "the last " + take.toFixed(1) + " seconds"
          + (voicesOnly ? " - voices only, without the record underneath"
                        : " as it played, mix and all"),
        voicesOnly: voicesOnly,
        /* WHERE IN THE RING THIS CAME FROM, so it can be widened afterwards.
         *
         * "In the event that I am tapping and holding it when audio is
         * already playing, I want to be able to retroactively go into that
         * sample and expand the play head forward and grab the full sentence
         * that was being said."
         *
         * A ring offset is only meaningful together with the moment it was
         * measured - "eight seconds ago" means something different a minute
         * later - so the wall clock is stamped beside it and the window is
         * re-derived from the two. */
        air: {from: take, to: 0, at: Date.now()}
      });
      if (bar) bar.finish(true);
      note("Pad " + (index + 1) + " - " + take.toFixed(1) + "s "
        + (voicesOnly ? "of voices" : "off the air")
        + ". Hold it again to widen, right-click to trim.");
    } catch (err) {
      if (bar) bar.finish(false);
      note("Could not take the air: " + ((err && err.message) || err));
    } finally {
      if (cell) cell.classList.remove("loading");
    }
  }

  /* THE ONE DOOR BYTES COME IN BY. importRow fetches from the station; this
   * takes bytes already in hand - off the air, out of the grab window, or
   * trimmed inside it - so all of them land identically and a pad cannot
   * tell which road it arrived on. */
  async function putBytesOnPad(index, bytes, extra) {
    const key = padKey(bank, index);
    await dbPut(key, { bytes: bytes, type: "audio/wav" });
    await engine().load(key, bytes);
    const meta = Object.assign({
      label: "take", who: "", kind: "air", srcId: "",
      exact: true, cut: "", at: Date.now(),
      gain: 1, pitch: 1, loop: false, reverse: false, trim: null, choke: ""
    }, extra || {});
    meta.seconds = engine().seconds(key);
    layout[bank][index] = meta;
    if (root.PineSamplerFace) root.PineSamplerFace.forgetPeaks(key);
    saveLayout();
    paintPads();
    return meta;
  }

  /* BYTES ONTO THE NEXT FREE PAD, WHEREVER IT IS.
   *
   * putBytesOnPad places into a pad you name on the bank you are looking at.
   * This is the other question - "just put it somewhere" - and it is the one
   * the Listen view asks: "if it is full, it increments over to the next
   * series of pads where it begins placing elements on the pads."
   *
   * firstFreePad already walks bank to bank, so the roll across banks is its
   * answer and not a second copy of the same logic. The bank in view FOLLOWS
   * the placement, because a pad you cannot see landing silently is how a
   * sampler starts feeling broken. */
  async function putBytesAnywhere(bytes, extra) {
    const free = root.PineListenModel
      ? root.PineListenModel.firstFreePad(layout, bank) : null;
    if (!free) {
      note("Every pad in every bank is full - clear one first.");
      return null;
    }
    if (free.bank !== bank) {
      bank = free.bank;
      paintBanks();
    }
    const meta = await putBytesOnPad(free.pad, bytes, extra);
    return {bank: free.bank, pad: free.pad, meta};
  }

  /* TAP AN EMPTY PAD: the grab window - scrub back through what just played,
   * or pick one of the clips listed beside it. Lives in sampler-grab.js. */
  function openGrab(index, widen) {
    if (!root.PineSamplerGrab) {
      note("The grab window is not loaded on this terminal.");
      return;
    }
    root.PineSamplerGrab.open({
      bank: bank,
      pad: index,
      /* The window this pad was cut from, when it came off the air, so the
       * selection opens on it instead of on the last few seconds. */
      widen: widen || null,
      put: (bytes, extra) => putBytesOnPad(index, bytes, extra),
      note: note
    });
  }

  /* A dial is shown only while the thing it dials is switched on. Three
   * menus and a slider permanently on screen would be four controls doing
   * nothing most of the time, on a nine-inch screen. */
  function paintDials() {
    const row = el("pbDials");
    if (!row) return;
    const rpt = el("pbRptDial");
    if (rpt) rpt.hidden = !modes.repeat;
    for (const id of ["pbOct", "pbChord", "pbProg"]) {
      const dial = el(id);
      if (dial) dial.hidden = !modes.sixteen;
    }
    row.hidden = !modes.repeat && !modes.sixteen;
  }

  /* SIXTEEN LEVELS, SHOWN AS SIXTEEN LEVELS.
   *
   * "Whenever I go into sixteen level, I want the pads to be illuminated in
   * a gradient going up the pads, showing the sixteen levels in action."
   *
   * The brightness is the PITCH, not the pad number, so a chord or a
   * progression reads as the shape it actually is rather than as a flat
   * ramp - a triad shows its steps, `octaves` shows four wide jumps. The
   * unity pad, the one that plays the sample untouched, is marked
   * separately; without it there is no way to see where the original sits. */
  function paintSixteen() {
    const grid = document.querySelector(".pb-grid");
    if (grid) grid.classList.toggle("sixteen", !!modes.sixteen);
    if (!modes.sixteen) {
      for (let p = 0; p < PADS; p += 1) {
        const element = el("pad-" + p);
        if (!element) continue;
        element.style.removeProperty("--lvl");
        element.classList.remove("unity");
        const tone = element.querySelector(".pb-pad-tone");
        if (tone) tone.remove();
      }
      return;
    }
    const notes = [];
    for (let p = 0; p < PADS; p += 1) notes.push(sixteenSemitone(p));
    const low = Math.min.apply(null, notes);
    const high = Math.max.apply(null, notes);
    const span = Math.max(1, high - low);
    for (let p = 0; p < PADS; p += 1) {
      const element = el("pad-" + p);
      if (!element) continue;
      element.style.setProperty("--lvl", ((notes[p] - low) / span).toFixed(3));
      element.classList.toggle("unity", notes[p] === 0);
      let tone = element.querySelector(".pb-pad-tone");
      if (!tone) {
        tone = document.createElement("span");
        tone.className = "pb-pad-tone";
        element.appendChild(tone);
      }
      tone.textContent = stepName(notes[p]);
    }
  }

  /* An interval from the SAMPLE'S OWN pitch, not a concert pitch: calling an
   * arbitrary clip "C" would be a lie about it. */
  function stepName(semitone) {
    if (semitone === 0) return "unity";
    return (semitone < 0 ? "-" : "+") + Math.abs(semitone);
  }

  let feedPrint = "";

  /* ONE rAF LOOP FOR THE SPECTRUM, and only while a canvas is on screen.
   *
   * The feed is rebuilt whenever it changes, so the canvas is a new element
   * each time; the loop follows whichever one is current and stops itself
   * the moment that canvas leaves the document. A loop per row would leak
   * one per repaint, which on a four-second feed is fifteen a minute. */
  let specCanvas = null;
  let specTimer = 0;

  function startSpectrum(canvas) {
    specCanvas = canvas;
    if (specTimer) return;
    const draw = () => {
      const target = specCanvas;
      if (!target || !target.isConnected) {
        specTimer = 0;
        return;
      }
      const air = root.PineAir;
      const bars = air && air.spectrum ? air.spectrum() : null;
      const pen = target.getContext("2d");
      pen.clearRect(0, 0, target.width, target.height);
      if (bars && bars.length) {
        /* The low half only: speech and stings live there, and the top of
         * the range is empty air that would make every clip look quiet. */
        const use = Math.max(8, Math.floor(bars.length / 2));
        const width = target.width / use;
        for (let i = 0; i < use; i += 1) {
          const height = Math.max(1, bars[i] * target.height);
          pen.fillStyle = "rgba(159, 224, 143, " + (0.35 + bars[i] * 0.65).toFixed(2) + ")";
          pen.fillRect(i * width, target.height - height, Math.max(1, width - 1), height);
        }
      }
      specTimer = requestAnimationFrame(draw);
    };
    specTimer = requestAnimationFrame(draw);
  }

  function paintFeed(rows) {
    const list = el("pbFeed");
    if (!list) return;
    feedRows = rows;

    /* The shared feed ticks at 250ms so the playhead can move between
     * polls. Rebuilding 120 rows four times a second is wasted work on a
     * tablet AND it throws away scroll position and any drag in progress -
     * you cannot drag a row that is replaced underneath your finger.
     * Repaint only when the feed actually changed. */
    /* NEVER rebuild mid-carry. `replaceChildren` destroys the very row the
     * finger is holding; the captured element is detached, the pointer
     * stream stops dead, and the carry dies silently a few pixels in.
     * Measured as 14 touchmoves reaching the row but only one pointermove -
     * which reads exactly like a browser gesture conflict and is not one. */
    if (carry) return;

    const print = rows.length + ":" + rows.map(
      (row) => row.id + (row.lcdStatus === "Playing" ? "*" : "")).join(",");
    if (print === feedPrint) return;
    feedPrint = print;

    const fragment = document.createDocumentFragment();
    /* Newest at the top: the thing worth grabbing almost always just
     * happened, and reaching for it should not mean scrolling.
     *
     * The whole ring is shown, not a slice of it. The station already caps
     * itself at 240 rows (app.py:25061), so this is bounded by something
     * that has thought about it - and halving that again only hid takeable
     * moments from the operator. The list grows as the broadcast runs and
     * rolls off the bottom when the station's own ring does. */
    const newestFirst = rows.slice().reverse();
    let drawnSpectrum = false;
    for (const row of newestFirst) {
      const source = sourceFor(row);
      const item = document.createElement("div");
      item.className = "pb-row" + (source ? " grabbable" : " quiet");
      item.dataset.rowId = row.id;
      /* And the hold, which reads data-line - see line-actions.js. A drag
       * puts this row on a pad; a HOLD offers the rest of what can be done
       * with it, and there is no reason the sampler's feed should be the one
       * list where that does not work. */
      if (row.id) item.dataset.line = String(row.id);
      if (row.lcdStatus === "Playing") item.classList.add("playing");
      const who = document.createElement("b");
      who.textContent = row.name || row.who || row.kind || "booth";
      const text = document.createElement("span");
      text.textContent = row.text || "";
      const tag = document.createElement("em");
      tag.textContent = row.lcdStatus || "";
      item.appendChild(who);
      /* WHICH CLIP IS ACTUALLY SOUNDING, drawn rather than asserted.
       *
       * "For the actively playing sound effect, put an audio spectrogram
       *  showing the actively playing sound effect playing so we know
       *  exactly which clip is currently being played."
       *
       * Only on the row that says Playing - a spectrum beside a row that is
       * not making a sound is decoration, and worse, it would make every row
       * look live. */
      /* ONLY THE NEWEST PLAYING ROW gets one. The feed can carry more than
       * one row marked Playing - the coalesced road marks the live turn and
       * a chat row of the same moment can arrive carrying the status too -
       * and two spectra means two canvases of which only the later is
       * driven, so the other sits there black and looks broken. Measured:
       * two canvases, 1305 lit pixels in one and 0 in the other. */
      if (row.lcdStatus === "Playing" && !drawnSpectrum) {
        drawnSpectrum = true;
        const bars = document.createElement("canvas");
        bars.className = "pb-spec";
        bars.width = 128;
        bars.height = 22;
        item.appendChild(bars);
        startSpectrum(bars);
      }
      item.appendChild(text);
      item.appendChild(tag);
      if (source) {
        item.title = "Drag onto a pad — " + source.kind;
        item.addEventListener("pointerdown", (event) => carryStart(event, item, row));
        item.addEventListener("pointermove", carryMove);
        item.addEventListener("pointerup", carryEnd);
        item.addEventListener("pointercancel", () => carryEnd(null));
      }
      fragment.appendChild(item);
    }
    list.replaceChildren(fragment);

    const tally = el("pbTally");
    if (tally) {
      const takeables = rows.filter(takeable).length;
      tally.textContent = rows.length
        ? takeables + " of " + rows.length + " takeable" : "";
    }
  }

  /* --------------------------------------------------------------- build */

  function build(host) {
    host.innerHTML = "";

    const left = document.createElement("div");
    left.className = "pb-left";
    left.innerHTML =
      '<div class="pb-feed-head">'
      + '<b>Feed</b>'
      + '<span id="pbTally" class="pb-tally"></span>'
      + '<button id="pbWhole" class="pb-toggle" title="Grab this line alone, '
      + 'or the whole welded round it aired in">line</button>'
      + '</div><div id="pbFeed" class="pb-feed"></div>'
      + '<div class="pb-note-bar"><span id="pbNote" class="pb-note"></span>'
      + '<span id="pbFoot" class="pb-foot" title="What the loaded pads cost '
      + 'in memory. A whole round decodes to far more than its download '
      + 'suggests; trimming does not shrink it, clearing does."></span></div>';

    const right = document.createElement("div");
    right.className = "pb-right";

    const banks = document.createElement("div");
    banks.className = "pb-banks";

    /* KITS, at the top, where the operator asked for them: "have that saved
     * as a preset that I can jump between with an icon at the top of the
     * screen". It sits beside the bank numbers because that is what it acts
     * on - one page, or all five. */
    const kitBtn = document.createElement("button");
    kitBtn.id = "pbKit";
    kitBtn.className = "pb-kit";
    kitBtn.title = "Presets - save, load and swap whole banks of pads";
    kitBtn.textContent = String.fromCodePoint(0x1F4BE);
    kitBtn.addEventListener("click", openKits);
    banks.appendChild(kitBtn);
    for (let b = 0; b < BANKS; b += 1) {
      const button = document.createElement("button");
      button.id = "pbBank-" + b;
      button.className = "pb-bank";
      button.textContent = String(b + 1);
      button.addEventListener("click", async () => {
        bank = b;
        paintPads();
        /* A chop can be undone only on the bank it happened to, so the
         * button follows the bank rather than the session. */
        paintControls();
        await preload(b);
      });
      banks.appendChild(button);
    }

    const grid = document.createElement("div");
    grid.className = "pb-grid";
    for (let p = 0; p < PADS; p += 1) {
      const pad = document.createElement("div");
      pad.id = "pad-" + p;
      pad.className = "pb-pad";
      pad.dataset.pad = String(p);
      pad.innerHTML = '<span class="pb-pad-num">' + (p + 1) + '</span>'
        + '<span class="pb-pad-label"></span><span class="pb-pad-sub"></span>';

      /* ONE POINTERDOWN, FOUR MEANINGS, and which it turns out to be is
       * decided by what the pad holds and what the finger then does:
       *
       *   loaded, tapped    play it              (what it always did)
       *   loaded, dragged   the bin appears, drop on it to clear the pad
       *   empty,  tapped    the grab window - the last two minutes of
       *                     broadcast, and the clips that just played
       *   empty,  held      take the air NOW, straight onto this pad
       *
       * The empty pair are the operator's: "tap and hold on a pad that is
       * idle or blank to sample the current playing broadcast to the pad",
       * and "if I tap on a pad and there is nothing there, then allow me to
       * open a pop up that allows me to grab from previous seconds".
       *
       * A HOLD IS NOT A DRAG AND A DRAG IS NOT A SCROLL: the hold dies on
       * movement past a few pixels, exactly as line-actions.js does it, or
       * the grid cannot be dragged at all. */
      pad.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        try { pad.setPointerCapture(event.pointerId); } catch (err) { /* mouse */ }
        gesture = {
          pad: p, x: event.clientX, y: event.clientY,
          moved: false, dragging: false, took: false, timer: 0
        };
        if (hasContent(p)) {
          if (loadedAt(p)) press(p, event);
          else warmAndFire(p, event);
          /* A HOLD ON A PAD THAT CAME OFF THE AIR REOPENS ITS WINDOW, so the
           * half-sentence that was caught can be widened into the whole one.
           * Only for air takes: a station clip has no ring behind it, and
           * holding it still means the trim editor. */
          const meta = layout[bank][p];
          if (meta && meta.air) {
            gesture.timer = setTimeout(() => {
              gesture.timer = 0;
              gesture.took = true;
              lift(p);
              openGrab(p, meta.air);
            }, HOLD_MS);
          }
        } else {
          gesture.timer = setTimeout(() => {
            gesture.timer = 0;
            gesture.took = true;
            sampleAirNow(p);
          }, HOLD_MS);
        }
      });

      pad.addEventListener("pointermove", (event) => {
        if (!gesture || gesture.pad !== p) return;
        const dx = Math.abs(event.clientX - gesture.x);
        const dy = Math.abs(event.clientY - gesture.y);
        if (dx <= SLOP && dy <= SLOP) return;
        gesture.moved = true;
        if (gesture.timer) { clearTimeout(gesture.timer); gesture.timer = 0; }
        if (hasContent(p) && !gesture.dragging) {
          gesture.dragging = true;
          /* IT IS BEING CARRIED, NOT PLAYED - so it stops making a noise.
           *
           * "Do not play the pad that I am deleting when I press delete to
           *  remove the pad."
           *
           * The hit still fires the instant the finger lands, because that
           * latency is the whole of what makes a sampler feel like one; what
           * changes is that the moment the gesture turns out to be a CARRY,
           * the sound it started is cut. lift() alone only released a gated
           * voice, so a one-shot carried on playing all the way to the bin. */
          lift(p);
          try { engine().stopPad(padKey(bank, p)); } catch (err) { /* older */ }
          for (const [id, voice] of sounding) {
            if (voice.padId === p) sounding.delete(id);
          }
          showBin(p);
        }
        if (gesture.dragging) moveBin(event);
      });

      const finish = (event) => {
        const g = gesture;
        gesture = null;
        if (!g || g.pad !== p) { lift(p); return; }
        if (g.timer) clearTimeout(g.timer);
        if (g.dragging) { dropOnBin(p, event); return; }
        if (hasContent(p)) { lift(p); return; }
        if (!g.took && !g.moved) openGrab(p);
      };
      pad.addEventListener("pointerup", finish);
      pad.addEventListener("pointercancel", finish);
      pad.addEventListener("pointerleave", () => { if (held.has(p)) lift(p); });


      /* Right-click / long-press opens the trim editor - but only on a pad
       * that HAS something to trim. On an empty pad the long press is the
       * operator's "sample the broadcast now", and the two would fight. */
      pad.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        if (!hasContent(p)) return;
        select(p);
        if (root.PineSamplerTrim) root.PineSamplerTrim.open(bank, p);
      });
      grid.appendChild(pad);
    }

    const controls = document.createElement("div");
    controls.className = "pb-controls";
    const toggles = [
      ["pbPoly", "POLY", "Let pads ring together. Off, a new hit cuts the last one.",
        () => modes.poly,
        () => { modes.poly = !modes.poly; engine().setPolyphonic(modes.poly); }],
      ["pbGate", "GATE", "Hold to play - the sound stops when you lift.",
        () => modes.gate, () => { modes.gate = !modes.gate; }],
      ["pbFull", "FULL", "Every hit at maximum, whatever the touch.",
        () => modes.full, () => { modes.full = !modes.full; }],
      ["pb16", "16 LVL", "The selected pad across all sixteen, played chromatically.",
        () => modes.sixteen, () => { modes.sixteen = !modes.sixteen; }],
      ["pbRpt", "NOTE RPT", "Hold a pad and it retriggers in time.",
        () => modes.repeat, () => { modes.repeat = !modes.repeat; }],
      /* ON AT BOOT, because the operator asked for it that way: "by default
       * I would have it on so that way whenever I tap on a sample pad, I am
       * hearing just the sound of that sample pad." */
      ["pbDuck", "SOLO PAD", "Mute the broadcast while a pad is playing.",
        () => (root.PineAir ? root.PineAir.duckEnabled() : false),
        () => {
          if (root.PineAir) root.PineAir.setDuckEnabled(!root.PineAir.duckEnabled());
        }]
    ];
    for (const spec of toggles) {
      const button = document.createElement("button");
      button.id = spec[0];
      button.className = "pb-mode";
      button.textContent = spec[1];
      button.title = spec[2];
      button.addEventListener("click", () => {
        spec[4]();
        button.classList.toggle("on", spec[3]());
        paintDials();
        paintSixteen();
        rememberModes();
      });
      controls.appendChild(button);
    }
    /* EVERY LIGHT FROM THE REMEMBERED STATE, none of them hardcoded. This
     * used to switch POLY's light on unconditionally, which was fine while
     * POLY was always on at boot and a lie the moment it was not. */
    for (const spec of toggles) {
      const light = controls.querySelector("#" + spec[0]);
      if (light) light.classList.toggle("on", !!spec[3]());
    }
    /* THE LIGHT MUST MATCH THE STATE, both ways.
     *
     * This only ever ADDED the class, so a terminal whose stored preference
     * was off still showed SOLO PAD lit - and then a press to "turn it on"
     * turned it off. Measured exactly that: duckEnabled false while the
     * button carried "pb-mode on". A toggle that lies about its own state is
     * worse than one that does nothing. */
    const duckBtn = controls.querySelector("#pbDuck");
    if (duckBtn) {
      duckBtn.classList.toggle("on",
        !!(root.PineAir && root.PineAir.duckEnabled()));
    }

    /* TAP, CHOP and STOP DO something; POLY, GATE, FULL, 16 LVL and NOTE
     * RPT ARE something. Wearing the same button made the first three read
     * as states the sampler was stuck in - which is how a one-press chop
     * became "chop mode". `.pb-act` draws them as the actions they are. */
    const tap = document.createElement("button");
    tap.className = "pb-mode pb-act";
    tap.textContent = "TAP";
    tap.title = "Tap the tempo Note Repeat runs at";
    tap.addEventListener("click", () => {
      const now = performance.now();
      tapTimes = tapTimes.filter((t) => now - t < 2500).concat(now);
      if (tapTimes.length >= 2) {
        const gaps = tapTimes.slice(1).map((t, i) => t - tapTimes[i]);
        const mean = gaps.reduce((a, b) => a + b, 0) / gaps.length;
        modes.bpm = Math.round(60000 / mean);
        rememberModes();
        note("Tempo " + modes.bpm + " bpm");
      }
    });
    controls.appendChild(tap);

    const chopBtn = document.createElement("button");
    chopBtn.id = "pbChop";
    chopBtn.className = "pb-mode pb-act";
    chopBtn.textContent = "CHOP";
    chopBtn.title = "Slice the selected pad across all sixteen pads";
    chopBtn.addEventListener("click", chop);
    controls.appendChild(chopBtn);

    /* CLEAR THE WHOLE PAGE, and ask first - and offer the way out.
     *
     * "Offer a button to clear all the pads on the page, and offer to confirm
     *  if I want to clear all the pads. Also ask me if I want to save it out
     *  under a preset that I can reuse on another device like the MPC."
     *
     * The offer to keep it is the point. Sixteen pads is real work and the
     * bytes live only on this device - the station holds references, not
     * audio - so a cleared bank that was never exported is gone for good.
     * Asking at the moment of deletion is the only moment the operator can
     * still act on it. */
    const wipe = document.createElement("button");
    wipe.id = "pbWipe";
    wipe.className = "pb-mode pb-act danger";
    wipe.textContent = "CLEAR";
    wipe.title = "Clear every pad on this bank";
    wipe.addEventListener("click", clearBank);
    controls.appendChild(wipe);

    const stop = document.createElement("button");
    stop.className = "pb-mode pb-act danger";
    stop.textContent = "STOP";
    stop.title = "Silence every pad at once";
    stop.addEventListener("click", () => {
      engine().stopAll();
      /* The ledger is the view's own record and nothing tells it the engine
       * went quiet, so STOP has to say so - otherwise the timeline keeps
       * drawing lanes for voices that were cut a moment ago. */
      sounding.clear();
      if (root.PineAir) root.PineAir.release('pad');
    });
    controls.appendChild(stop);

    /* ---- the second row: the dials the toggles above need ---------------
     *
     * Kept OFF the toggle row on purpose. POLY/GATE/FULL/16 LVL/NOTE RPT are
     * lights that are either on or off; a slider and three menus are neither,
     * and mixing the two kinds is how CHOP came to read as a mode. */
    const dials = document.createElement("div");
    dials.className = "pb-dials";
    dials.id = "pbDials";

    /* NOTE REPEAT: "there should be a slider for allowing the repeat
     * frequency to go from one fourth notes all the way up to one thirty
     * second notes." The slider STEPS through the divisions rather than
     * sweeping a number, because 1/5 and 1/9 are not things - the positions
     * are the musical values, and a continuous control that snaps is a
     * control lying about what it can do. Triplets are in because a repeat
     * row without them is missing the half of this that swings. */
    const DIVISIONS = [
      [4, "1/4"], [6, "1/4T"], [8, "1/8"], [12, "1/8T"],
      [16, "1/16"], [24, "1/16T"], [32, "1/32"]
    ];
    const rptWrap = document.createElement("label");
    rptWrap.className = "pb-dial";
    rptWrap.id = "pbRptDial";
    const rptName = document.createElement("span");
    rptName.className = "pb-dial-name";
    rptName.textContent = "REPEAT";
    const rptSlider = document.createElement("input");
    rptSlider.type = "range";
    rptSlider.min = "0";
    rptSlider.max = String(DIVISIONS.length - 1);
    rptSlider.step = "1";
    rptSlider.value = String(Math.max(0,
      DIVISIONS.findIndex((pair) => pair[0] === modes.division)));
    const rptSaid = document.createElement("b");
    rptSaid.className = "pb-dial-said";
    rptSaid.textContent = (DIVISIONS[Number(rptSlider.value)] || DIVISIONS[0])[1];
    rptSlider.addEventListener("input", () => {
      const pick = DIVISIONS[Number(rptSlider.value)] || DIVISIONS[0];
      modes.division = pick[0];
      rememberModes();
      rptSaid.textContent = pick[1];
      note("Repeat " + pick[1] + " at " + modes.bpm + " bpm");
    });
    rptWrap.appendChild(rptName);
    rptWrap.appendChild(rptSlider);
    rptWrap.appendChild(rptSaid);
    dials.appendChild(rptWrap);

    const menu = (id, name, options, get, set) => {
      const wrap = document.createElement("label");
      wrap.className = "pb-dial";
      wrap.id = id;
      const title = document.createElement("span");
      title.className = "pb-dial-name";
      title.textContent = name;
      const select = document.createElement("select");
      for (const pair of options) {
        const option = document.createElement("option");
        option.value = String(pair[0]);
        option.textContent = pair[1];
        select.appendChild(option);
      }
      select.value = String(get());
      select.addEventListener("change", () => {
        set(select.value);
        rememberModes();
        paintSixteen();
        note(name.toLowerCase() + ": " + select.options[select.selectedIndex].textContent);
      });
      wrap.appendChild(title);
      wrap.appendChild(select);
      dials.appendChild(wrap);
      return wrap;
    };

    menu("pbOct", "OCTAVE",
      [[-2, "-2"], [-1, "-1"], [0, "0"], [1, "+1"], [2, "+2"]],
      () => modes.octave, (v) => { modes.octave = Number(v); });
    menu("pbChord", "CHORD", [
      ["chromatic", "chromatic"], ["majorScale", "major scale"],
      ["minorScale", "minor scale"], ["pentatonic", "pentatonic"],
      ["major", "major"], ["minor", "minor"], ["major7", "major 7"],
      ["minor7", "minor 7"], ["dom7", "dominant 7"], ["sus4", "sus4"],
      ["dim", "diminished"], ["fourths", "fourths"], ["wholeTone", "whole tone"]
    ], () => modes.chord, (v) => { modes.chord = v; });
    menu("pbProg", "PROGRESSION", [
      ["none", "none"], ["I-IV-V-I", "I - IV - V - I"],
      ["I-V-vi-IV", "I - V - vi - IV"], ["ii-V-I", "ii - V - I"],
      ["i-VI-III-VII", "i - VI - III - VII"], ["rising4ths", "rising 4ths"]
    ], () => modes.progress, (v) => { modes.progress = v; });

    right.appendChild(banks);
    /* A PAD IS SQUARE. It is a thing you hit with a thumb, and a 4x4 of
     * rectangles is a spreadsheet. The grid stretches to whatever box it is
     * handed, which is square in neither orientation, so it is wrapped in
     * an element it can MEASURE: .pb-padwrap is a size container, and the
     * grid takes the smaller of that box's two sides. See sampler.css. */
    const padwrap = document.createElement("div");
    padwrap.className = "pb-padwrap";
    padwrap.appendChild(grid);
    /* THE TIMELINE, ACROSS THE SAMPLER.
     *
     * "When playing a song on a sampler pad show a timeline going across the
     * sampler as the clip is playing, illustrating that the clip is playing."
     *
     * Directly under the grid, so the eye travels from the pad it just hit
     * to the bar that pad started. It is empty and takes no height until
     * something sounds - a permanent empty strip under a 4x4 on a nine-inch
     * screen is height spent on nothing. */
    const timeline = document.createElement("div");
    timeline.className = "pb-time";
    timeline.id = "pbTime";
    timeline.hidden = true;

    right.appendChild(padwrap);
    right.appendChild(timeline);
    right.appendChild(controls);
    right.appendChild(dials);
    host.appendChild(left);
    host.appendChild(right);

    el("pbWhole").addEventListener("click", () => {
      grabWhole = !grabWhole;
      el("pbWhole").textContent = grabWhole ? "round" : "line";
      el("pbWhole").classList.toggle("on", grabWhole);
    });
  }

  /* --------------------------------------------------------------- mount */

  async function mount(host) {
    if (!host || mounted) return;
    layout = loadLayout();
    /* BEFORE build(), not after. The toggles draw their lights from `modes`,
     * so restoring the operator's settings afterwards left every light
     * showing the default while the behaviour was already the remembered
     * one - a control panel disagreeing with the instrument behind it. */
    restoreModes();
    config = await api().readConfig();
    build(host);
    engine().warm();
    /* The air tap has to be listening BEFORE the operator reaches for an
     * empty pad, or the first hold finds an empty buffer. It is idempotent
     * and cheap, so starting it on every mount is the safe shape. */
    if (root.PineAir) root.PineAir.start();
    /* The face - the wallpaper, the waveforms on the pads, the knob row and
     * the edit sheet. It hangs off the seams this file publishes rather than
     * reaching inside, so it can be absent without anything here noticing. */
    if (root.PineSamplerFace) root.PineSamplerFace.start();
    paintDials();
    engine().setPolyphonic(modes.poly);
    paintPads();
    /* SAY WHAT THE BUTTON WILL DO, FROM THE FIRST FRAME.
     *
     * This was the whole of "I am stuck in chop mode". The layout persists,
     * so the sampler opens onto whatever state it was left in - and it was
     * measured on the tablet opening onto bank 1 with 15 of 16 pads carrying
     * choke "chop" while the button still read CHOP. chopping() detected the
     * chopped bank perfectly well; paintControls simply was never called at
     * mount, only after a chop, an unchop or a bank change.
     *
     * So the one control that could undo it was labelled as the thing that
     * caused it, and pressing it chopped the bank AGAIN. Three presses, three
     * chops, no way out. */
    paintControls();
    /* A trim overlay left open by the previous session sits over the whole
     * grid, which is the other half of "stuck": measured on the tablet with
     * one .pb-trim still in the document at mount. The editor is per-pad and
     * transient - nothing is lost by starting closed. */
    document.querySelectorAll(".pb-trim").forEach((node) => node.remove());
    await preload(bank);
    if (!unsubscribe) {
      unsubscribe = root.PineStationFeed.subscribe((payload) => paintFeed(payload.rows));
    }
    mounted = true;
  }

  /* Mounted on first visit, not at boot. Decoding a bank costs real work
   * and the operator may never open this view in a given session; the
   * shared feed is likewise only subscribed to once the view exists, so an
   * unopened sampler adds nothing to what the station is being asked. */
  function bootstrap() {
    const tab = document.getElementById("samplerTabBtn");
    const host = document.getElementById("sampler");
    if (!tab || !host) return;
    tab.addEventListener("click", () => {
      mount(host).catch((err) => {
        const target = document.getElementById("pbNote");
        if (target) { target.textContent = String(err.message || err); target.classList.add("bad"); }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }

  root.PineSampler = {
    mount,
    isMounted: () => mounted,
    /* The trim editor and any future panel reach the same state through
     * here rather than keeping a second copy of it. */
    layout: () => layout,
    bankIndex: () => bank,
    selectedPad: () => selected,
    padKey,
    /* The seam the Listen view takes its one-tap grab through. sourceFor
     * and takeable are published so another view can GREY ITS OWN BUTTON
     * with the same answer this one uses, rather than guessing from
     * `aired` - which is the exact mistake that once offered 7 of ~220
     * takeable moments. */
    sourceFor,
    takeable,
    grab,
    applySettings,
    save: saveLayout,
    repaint: paintPads,
    bytes: dbGet,
    /* The kit loader writes whole banks back; it needs the same door the
     * sampler's own imports use rather than a second store of its own. */
    put: dbPut,
    /* Told on every selection and every repaint, so the face follows without
     * a timer of its own. */
    onPad: (fn) => { if (typeof fn === "function") watchers.push(fn); },
    select,
    padCount: PADS,
    bankCount: BANKS,
    /* "Put this somewhere" - used by the Listen view's grab pad, which has
     * no bank or pad in mind and wants the roll across banks for free. */
    putBytes: putBytesAnywhere,
    forget: async (b, p) => {
      await dbDelete(padKey(b, p));
      engine().unload(padKey(b, p));
      layout[b][p] = null;
      saveLayout();
      paintPads();
    }
  };
})(typeof window !== "undefined" ? window : globalThis);
