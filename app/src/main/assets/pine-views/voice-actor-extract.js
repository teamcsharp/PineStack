/* VOICE ACTOR - EXTRACTION: THE SIGNATURE-MAKING PANE.
 *
 * "I also want to be able to put youtube links in the window and drag in and
 *  out points and set the specifics of video for the audio to be extracted as
 *  a sample for an audio XTTS / F5 cloned template ... load mp3s, mp4s from
 *  the SFX library ... search and scroll through folders and preview mp4s and
 *  mp3s and put those in a bin cart so they can be used in conjunction for a
 *  voice signature ... multiple SFX clips to generate one signature if the
 *  single clip is too short ... extract an 'actor signature' (XTTS / F5 voice
 *  clone) from video ... from the sfx/user directory of user submitted video
 *  to make videos and ads from the submitted content." (the operator)
 *
 * WHERE IT LIVES. The voice actor subpanel's "New actor" layer
 * (voice-actor.js, SHELL_CONTRACT.md): this file registers with
 * PineVoiceActor.registerExtraction({mount, tile, unmount}) and builds into
 * #vaExtractionMount. Desk and tablet (1154x690 touch) run the same file.
 *
 * FOUR PAGES, ONE PIPELINE (the Voice Studio's own):
 *   Link       a link -> POST /api/samples/fetch (the sample extractor's
 *              preview road: the station's sample cache, whole media first)
 *              -> a picture strip with DRAGGABLE in/out handles (mouse and
 *              touch) + numeric fields -> POST /api/voice-actor/extract/link
 *              (the studio's _voicelab_start with that range, the name, who
 *              this is, notes, and the engine the reference is cut for).
 *   Library    the clip book: /api/sfx/folders for the folder tree, a page
 *              of one folder or a search through GET /api/voice-actor/
 *              extract/sfx (off the loop, the house's one postings list),
 *              muted preview (poster + video for mp4, spectrogram + a short
 *              play for mp3 - this screen's element only, never the
 *              broadcast), and a BIN CART across folders.
 *   Uploads    the same browser on samples_grabbed/user, where the listener
 *              courier delivers; an actor made from these is marked
 *              user-submitted with a credit so ads can name the source.
 *   Jobs       every submission, polled until the harvest lands it in the
 *              library (the harvest rides the poll - SHELL_CONTRACT.md 4).
 *
 * A CART IS ONE JOB. POST /api/voice-actor/extract/clips joins the clips on
 * the station (each to its own in/out) and hands the lab ONE file; the join
 * is reported as its own stage, "join (station)", before the lab's nine.
 *
 * BOTH ENGINES = TWO CAPTURES. There is one reference per voice, cut for one
 * engine (#1476: XTTS listens to 30 s, F5 hard-clips at 12 s so the lab cuts
 * 10.5). Ticking both sends two jobs, linked as twins; the preferred engine
 * is recorded with POST /api/voice-actor/prefs once each lands. The station
 * always speaks through the ONE active engine - this pane shows which and
 * never switches it (the shell's engine strip owns that).
 *
 * EVENTS for the 3JS tile rail (SHELL_CONTRACT.md 9): on window,
 *   pine-voice-actor:extract-jobs  {jobs:[job...]}   on mount and on any add/forget
 *   pine-voice-actor:extract-job   job               on every change of one job
 *   pine-voice-actor:job           {job_id, status, name}  every raw poll answer
 * and window.PineVoiceActorExtract.jobs() for a late reader. A job carries
 * only the lab's real fields (stage, progress, stages_done, note, title,
 * diarize_note, speakers, speaker_used, extra_speakers, error, error_kind)
 * plus the station's own join facts. Nothing here invents a pipeline fact.
 *
 * NO SCROLL IS EVER TAKEN: nothing calls scrollTo/scrollIntoView; the job
 * console appends at the bottom and repaints its rows in place.
 * NO AUDIO PLAYS UNASKED: every element is muted + playsInline + preload
 * metadata until the operator presses a play button; sound is a per-screen
 * element toggle, never a station level.
 */
(function (root) {
  'use strict';

  var JOBS_KEY = 'pineVoiceActor.jobs.v1';          /* the key SHELL_CONTRACT.md suggests */
  var CART_KEY = 'pineVoiceActor.cart.v1';
  var TAB_KEY = 'pineVoiceActor.extractTab.v1';
  var LINK_KEY = 'pineVoiceActor.linkDraft.v1';
  var STAGES = ['download', 'extract_audio', 'transcribe', 'diarize', 'analyze_pitch',
    'analyze_cadence', 'build_signature', 'extract_reference', 'cleanup'];
  var STAGE_WORDS = {
    join: 'Join (station)', download: 'Download', extract_audio: 'Extract audio',
    transcribe: 'Transcribe', diarize: 'Diarize', analyze_pitch: 'Pitch',
    analyze_cadence: 'Cadence', build_signature: 'Signature', extract_reference: 'Reference',
    cleanup: 'Cleanup', handoff: 'Hand-off to the lab', queued: 'Queued', done: 'Done', error: 'Failed'
  };
  var REF_DEFAULT = {xtts: 30, f5: 10.5};           /* ENGINE_REGISTRY ref_s, until health answers */
  var REF_MIN_S = 10;                               /* voice-lab REF_MIN: under it a clone is rough */
  var LEAST_S = 3;                                  /* the join's own floor */
  var CART_MAX = 12;
  var GAP_S = 0.4;
  var POLL_MS = 2000;
  var FETCH_POLL_MS = 1500;
  var PAGE = 40;
  var SHORT_PLAY_S = 15;
  var LINK_GAP_S = 1;
  var CLIP_GAP_S = 0.2;
  var ENGINES = ['xtts', 'f5'];
  var ENGINE_WORDS = {xtts: 'XTTS', f5: 'F5'};

  /* ================================================== pure (and tested) */

  function r2(x) { return Math.round(Number(x) * 100) / 100; }

  /** Seconds as m:ss.s (h:mm:ss.s past the hour). */
  function fmtTime(s) {
    s = Number(s);
    if (!isFinite(s) || s < 0) s = 0;
    var tenths = Math.round(s * 10);
    var h = Math.floor(tenths / 36000);
    var m = Math.floor((tenths % 36000) / 600);
    var sec = (tenths % 600) / 10;
    var ss = (sec < 10 ? '0' : '') + sec.toFixed(1);
    return (h ? h + ':' + (m < 10 ? '0' : '') + m : String(m)) + ':' + ss;
  }

  /** "90", "1:30", "1:04:30.5" -> seconds (the lab's parse_ts); '' -> null;
   *  anything else -> NaN. */
  function parseTime(text) {
    var t = String(text === undefined || text === null ? '' : text).trim();
    if (!t) return null;
    if (!/^\d+(\.\d+)?(:\d+(\.\d+)?){0,2}$/.test(t)) return NaN;
    var parts = t.split(':').map(Number);
    while (parts.length < 3) parts.unshift(0);
    return r2(parts[0] * 3600 + parts[1] * 60 + parts[2]);
  }

  /** A legal range inside [0, dur]: ordered, at least `gap` long. */
  function clampRange(a, b, dur, gap) {
    gap = Number(gap) || 0;
    var d = isFinite(dur) && dur > 0 ? Number(dur) : Infinity;
    a = Math.max(0, Math.min(Number(a) || 0, d));
    b = Math.max(0, Math.min(isFinite(Number(b)) ? Number(b) : d, d));
    if (b < a) { var t = a; a = b; b = t; }
    if (b - a < gap) {
      if (a + gap <= d) b = a + gap;
      else { b = d; a = Math.max(0, d - gap); }
    }
    return {start: r2(a), end: r2(b)};
  }

  /** One handle dragged to `t`: it stops `gap` short of the other one. */
  function dragHandle(which, t, range, dur, gap) {
    var d = isFinite(dur) && dur > 0 ? dur : Infinity;
    t = Math.max(0, Math.min(Number(t) || 0, d));
    if (which === 'in') return {start: r2(Math.max(0, Math.min(t, range.end - gap))), end: range.end};
    return {start: range.start, end: r2(Math.min(d, Math.max(t, range.start + gap)))};
  }

  /** The time under a pointer at clientX over a strip box. */
  function timeAt(clientX, left, width, dur) {
    if (!(width > 0) || !(dur > 0)) return 0;
    return r2(Math.max(0, Math.min(1, (clientX - left) / width)) * dur);
  }

  /** What the lab is told: seconds, or nothing for the whole of it. */
  function rangeBody(range, dur) {
    if (!range) return {start: null, end: null};
    var whole = range.start <= 0.05 && (!isFinite(dur) || range.end >= dur - 0.05);
    if (whole) return {start: null, end: null};
    return {start: range.start > 0.05 ? r2(range.start) : null,
      end: (!isFinite(dur) || range.end < dur - 0.05) ? r2(range.end) : null};
  }

  /** Honest length advice against the engines the reference is cut for. */
  function lengthAdvice(seconds, engines, refs) {
    var out = [];
    refs = refs || REF_DEFAULT;
    seconds = Number(seconds) || 0;
    if (seconds < LEAST_S) {
      out.push({tone: 'bad', text: 'Under ' + LEAST_S + ' s - the lab has nothing to hear. Widen the range or add clips.'});
      return out;
    }
    if (seconds < REF_MIN_S) {
      out.push({tone: 'warn', text: fmtTime(seconds) + ' in all - under the lab\'s 10 s of clean speech, the clone will be rough.'});
    }
    (engines || []).forEach(function (e) {
      var need = Number((refs[e] && refs[e].ref_s !== undefined ? refs[e].ref_s : refs[e]) || REF_DEFAULT[e] || 0);
      var word = ENGINE_WORDS[e] || String(e).toUpperCase();
      if (!need) return;
      if (seconds < need) {
        out.push({tone: 'warn', text: word + ' listens to ' + need + ' s of reference; this is ' + fmtTime(seconds)
          + ' at most - the lab keeps only this speaker\'s clean speech.'});
      } else {
        out.push({tone: 'ok', text: word + ': room for its ' + need + ' s reference if most of it is this speaker'
          + (e === 'f5' ? ' (F5 hard-clips at 12 s, so the lab cuts 10.5).' : '.')});
      }
    });
    return out;
  }

  /** The seconds one cart item contributes. */
  function itemSeconds(item) {
    var end = item.end !== null && item.end !== undefined ? Number(item.end) : Number(item.seconds || 0);
    var start = Number(item.start || 0);
    return Math.max(0, r2(end - start));
  }

  function cartTotals(cart) {
    var clips = (cart || []).length;
    var speech = 0;
    (cart || []).forEach(function (it) { speech += itemSeconds(it); });
    return {clips: clips, speech: r2(speech), joined: r2(speech + (clips > 1 ? GAP_S * (clips - 1) : 0)),
      user: (cart || []).some(function (it) { return !!it.user; })};
  }

  /** Put a clip in the cart: {cart, added, why}. A clip may go in twice with
   *  two different ranges; the same range twice is refused. */
  function cartAdd(cart, item) {
    cart = (cart || []).slice();
    if (cart.length >= CART_MAX) return {cart: cart, added: false, why: 'The cart holds ' + CART_MAX + ' clips - the most one job takes.'};
    for (var i = 0; i < cart.length; i += 1) {
      if (cart[i].id === item.id && (cart[i].start || null) === (item.start || null) && (cart[i].end || null) === (item.end || null)) {
        return {cart: cart, added: false, why: 'That clip and range are in the cart already.'};
      }
    }
    cart.push(item);
    return {cart: cart, added: true, why: ''};
  }

  function isUserFolder(path) {
    return /(^|\/)samples_grabbed\/user\/?$/i.test(String(path || '').replace(/\\/g, '/'));
  }

  /** The stages one job walks: a cart starts with the station's join. */
  function jobChain(job) {
    /* a cart reaches the lab as an upload: the station joins it, the lab
     * never downloads anything */
    return job && job.kind === 'cart' ? ['join'].concat(STAGES.slice(1)) : STAGES.slice();
  }

  function jobPhase(job) {
    if (!job) return 'queued';
    if (job.stage === 'error' || job.error) return 'error';
    if (job.harvested) return 'done';
    if (job.stage === 'done') return 'harvesting';
    if (job.station || job.stage === 'join' || job.stage === 'handoff') return 'station';
    if (job.stage === 'queued' || !job.stage) return 'queued';
    return 'running';
  }

  /** done / now / todo for each stage of the chain, from the real fields. */
  function stageStates(job) {
    var chain = jobChain(job);
    var phase = jobPhase(job);
    var done = {};
    (job.stages_done || []).forEach(function (s) { done[s] = true; });
    if (job.joined) done.join = true;
    var at = chain.indexOf(phase === 'error' ? String(job.failedAt || '') : job.stage);
    return chain.map(function (s, i) {
      if (phase === 'done' || done[s] || (at >= 0 && i < at)) return {stage: s, state: 'done'};
      if (i === at) return {stage: s, state: phase === 'error' ? 'bad' : 'now'};
      return {stage: s, state: 'todo'};
    });
  }

  /** The event a tile rail is handed: the real fields, nothing more. */
  function eventOf(job) {
    job = job || {};
    return {
      id: job.id || '', lab_job: job.lab_job || '', kind: job.kind || 'link', legacy: !!job.legacy,
      name: job.name || '', engine: job.engine || '', twin: job.twin || '',
      label: job.label || '', clips: (job.clips || []).map(function (c) {
        return {id: c.id, name: c.name, video: !!c.video, user: !!c.user, seconds: c.seconds || null};
      }),
      user_submitted: !!job.user_submitted,
      phase: jobPhase(job), stage: job.stage || 'queued', progress: Number(job.progress || 0),
      stages: jobChain(job), stages_done: (job.stages_done || []).slice(),
      note: job.note || '', title: job.title || '', diarize_note: job.diarize_note || '',
      speakers: (job.speakers || []).slice(), speaker_used: job.speaker_used || '',
      extra_speakers: (job.extra_speakers || []).slice(),
      joined: job.joined || null, harvested: !!job.harvested, voice_id: job.voice_id || '',
      error: job.error || '', error_kind: job.error_kind || '', failed_at: job.failedAt || '',
      at: job.seen || 0
    };
  }

  /** Fold a poll answer into a job record (only the real fields). */
  function foldStatus(job, st) {
    var out = {};
    for (var k in job) if (Object.prototype.hasOwnProperty.call(job, k)) out[k] = job[k];
    if (st.stage === 'error' && job.stage && job.stage !== 'error') out.failedAt = job.stage;
    out.note = st.note || '';               /* each answer's own note - a station note never lingers into the lab */
    ['stage', 'progress', 'stages_done', 'title', 'diarize_note', 'speakers', 'speaker_used',
      'extra_speakers', 'harvested', 'voice_id', 'error', 'error_kind', 'harvest_error', 'signature_note',
      'joined', 'lab_job', 'station', 'user_submitted', 'credits', 'twin'].forEach(function (key) {
      if (st[key] !== undefined) out[key] = st[key];
    });
    if (st.stage !== 'error') { out.error = st.error || ''; out.error_kind = st.error_kind || ''; }
    if (st.stage === 'error' && !out.error) out.error = 'The job failed without a reason.';
    out.station = !!st.station;
    out.seen = Date.now();
    return out;
  }

  function readJobs(store) {
    try {
      var raw = store && store.getItem(JOBS_KEY);
      var got = raw ? JSON.parse(raw) : [];
      return Array.isArray(got) ? got.filter(function (j) { return j && j.id; }) : [];
    } catch (err) { return []; }
  }

  function writeJobs(store, jobs) {
    try { if (store) store.setItem(JOBS_KEY, JSON.stringify((jobs || []).slice(-30))); }
    catch (err) { /* a locked profile still keeps them for this visit */ }
  }

  function readJson(store, key, fallback) {
    try { var raw = store && store.getItem(key); return raw ? JSON.parse(raw) : fallback; }
    catch (err) { return fallback; }
  }

  function writeJson(store, key, value) {
    try { if (store) store.setItem(key, JSON.stringify(value)); } catch (err) { /* this visit only */ }
  }

  /* ================================================== small DOM helpers */

  var S = null;           /* the mounted state; null while the layer is closed */

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function ico(name) {
    var span = make('span', 'vx-ico');
    span.setAttribute('aria-hidden', 'true');
    var markup = '';
    try { markup = S && S.ctx && typeof S.ctx.icon === 'function' ? S.ctx.icon(name, '') : ''; } catch (err) { markup = ''; }
    if (!markup) {
      try { markup = typeof root.pineIcon === 'function' ? root.pineIcon(name, '') : ''; } catch (err) { markup = ''; }
    }
    if (markup) span.innerHTML = markup;
    return span;
  }

  function btn(cls, words, iconName, title) {
    var b = make('button', 'vx-btn' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    if (iconName) b.appendChild(ico(iconName));
    if (words) b.appendChild(make('span', 'vx-btn-words', words));
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    return b;
  }

  function setText(node, text) {
    text = text === undefined || text === null ? '' : String(text);
    if (node && node.textContent !== text) node.textContent = text;
  }

  function on(node, type, fn, opts) {
    node.addEventListener(type, fn, opts || false);
    if (S) S.offs.push(function () { node.removeEventListener(type, fn, opts || false); });
  }

  function later(fn, ms) {
    var id = root.setTimeout(function () {
      if (S) S.timers = S.timers.filter(function (t) { return t !== id; });
      fn();
    }, ms);
    if (S) S.timers.push(id);
    return id;
  }

  function say(text, kind) {
    try { if (S && S.ctx && typeof S.ctx.say === 'function') S.ctx.say(text, kind || ''); } catch (err) { /* the line is the shell's */ }
    if (S && S.note) { setText(S.note, text); S.note.className = 'vx-note' + (kind === 'bad' ? ' vx-bad' : ''); }
  }

  function request(method, path, body) {
    if (!S || !S.ctx || typeof S.ctx.request !== 'function') return Promise.reject(new Error('the panel is closed'));
    return S.ctx.request(method, path, body);
  }

  function url(u) {
    try { return S && S.ctx && typeof S.ctx.stationUrl === 'function' ? S.ctx.stationUrl(u) : u; } catch (err) { return u; }
  }

  function storage() {
    try { return root.localStorage || null; } catch (err) { return null; }
  }

  function emit(name, detail) {
    try { root.dispatchEvent(new root.CustomEvent('pine-voice-actor:' + name, {detail: detail || {}})); }
    catch (err) { /* no listeners on a WebView without CustomEvent */ }
  }

  function absent(err) { return !!(err && err.status === 404 && /not\s*found/i.test(String(err.message || ''))); }

  function field(labelText, input, hint) {
    var wrap = make('label', 'vx-field');
    wrap.appendChild(make('span', 'vx-field-label', labelText));
    wrap.appendChild(input);
    if (hint) wrap.appendChild(make('span', 'vx-field-hint', hint));
    return wrap;
  }

  function textInput(cls, placeholder, value) {
    var i = make('input', 'vx-input' + (cls ? ' ' + cls : ''));
    i.type = 'text';
    i.autocomplete = 'off';
    i.spellcheck = false;
    if (placeholder) i.placeholder = placeholder;
    if (value) i.value = value;
    return i;
  }

  function refs() { return (S && S.health && S.health.engines) || REF_DEFAULT; }

  function activeEngine() {
    var e = null;
    try { e = S && S.ctx && typeof S.ctx.engines === 'function' ? S.ctx.engines() : null; } catch (err) { e = null; }
    return e;
  }

  /* ================================================== the scrubber
   *
   * One media element with a picture strip under it and two DRAGGABLE
   * handles. Pointer events carry mouse and touch alike (touch-action: none
   * on the strip so a drag never scrolls the layer). Every element starts
   * muted; nothing plays until a play button is pressed. */

  function Scrubber(opts) {
    var self = this;
    this.opts = opts;
    this.gap = opts.gap || LINK_GAP_S;
    this.dur = NaN;
    this.range = {start: 0, end: 0};
    this.stopAt = 0;
    this.alive = true;
    this.raf = 0;
    this.frameJob = null;
    var el = this.el = make('div', 'vx-scrub' + (opts.compact ? ' vx-scrub-compact' : ''));

    var stage = this.stage = make('div', 'vx-scrub-stage');
    el.appendChild(stage);

    var bar = make('div', 'vx-scrub-bar');
    this.playBtn = btn('vx-scrub-play', 'Play range', 'c:caret--right', 'Play the chosen range on this screen');
    this.soundBtn = btn('vx-scrub-sound', 'Sound off', 'c:volume--mute--filled',
      'Sound on this screen only - the element\'s own mute, never a station level');
    this.clock = make('span', 'vx-scrub-clock', '0:00.0 / -');
    bar.appendChild(this.playBtn);
    bar.appendChild(this.soundBtn);
    bar.appendChild(this.clock);
    this.pictureNote = make('span', 'vx-scrub-pic-note', '');
    bar.appendChild(this.pictureNote);
    el.appendChild(bar);

    var strip = this.strip = make('div', 'vx-strip');
    strip.setAttribute('aria-label', 'Range strip - drag the IN and OUT handles');
    this.pic = make('canvas', 'vx-strip-pic');
    this.wave = make('canvas', 'vx-strip-wave');
    this.dimL = make('div', 'vx-strip-dim vx-strip-dim-l');
    this.dimR = make('div', 'vx-strip-dim vx-strip-dim-r');
    this.sel = make('div', 'vx-strip-sel');
    this.head = make('div', 'vx-strip-head');
    this.hIn = this.handle('in', 'IN');
    this.hOut = this.handle('out', 'OUT');
    [this.pic, this.wave, this.dimL, this.dimR, this.sel, this.head, this.hIn, this.hOut].forEach(function (n) { strip.appendChild(n); });
    this.empty = make('div', 'vx-strip-empty', opts.emptyText || 'Load a preview to drag the in and out points.');
    strip.appendChild(this.empty);
    el.appendChild(strip);

    var fields = make('div', 'vx-scrub-fields');
    this.inField = textInput('vx-in', '0:00.0');
    this.outField = textInput('vx-out', 'end');
    this.inField.setAttribute('inputmode', 'decimal');
    this.outField.setAttribute('inputmode', 'decimal');
    var setIn = btn('vx-set-in', 'In here', 'c:cut', 'Set the in point at the playhead');
    var setOut = btn('vx-set-out', 'Out here', 'c:cut', 'Set the out point at the playhead');
    this.len = make('span', 'vx-scrub-len', '');
    var fin = field('In', this.inField);
    fin.appendChild(setIn);
    var fout = field('Out', this.outField);
    fout.appendChild(setOut);
    fields.appendChild(fin);
    fields.appendChild(fout);
    fields.appendChild(this.len);
    el.appendChild(fields);

    on(this.playBtn, 'click', function (e) { e.stopPropagation(); self.togglePlay(); });
    on(this.soundBtn, 'click', function (e) { e.stopPropagation(); self.toggleSound(); });
    on(setIn, 'click', function (e) { e.stopPropagation(); self.setAtHead('in'); });
    on(setOut, 'click', function (e) { e.stopPropagation(); self.setAtHead('out'); });
    [this.inField, this.outField].forEach(function (input) {
      on(input, 'input', function () { input.__typing = true; });
      on(input, 'blur', function () { if (input.__typing) self.fromFields(); });
      on(input, 'change', function () { self.fromFields(); });
      on(input, 'keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); self.fromFields(); } });
    });
    on(strip, 'pointerdown', function (e) { self.stripDown(e); });
    this.paint();
  }

  Scrubber.prototype.handle = function (which, word) {
    var self = this;
    var h = make('div', 'vx-handle vx-handle-' + which);
    h.setAttribute('role', 'slider');
    h.setAttribute('tabindex', '0');
    h.setAttribute('aria-label', which === 'in' ? 'In point' : 'Out point');
    h.appendChild(make('span', 'vx-handle-grip'));
    h.appendChild(make('span', 'vx-handle-tag', word));
    on(h, 'pointerdown', function (e) { self.handleDown(which, e); });
    on(h, 'keydown', function (e) { self.handleKey(which, e); });
    return h;
  };

  Scrubber.prototype.ready = function () { return isFinite(this.dur) && this.dur > 0; };

  Scrubber.prototype.setMedia = function (kind, src, extra) {
    extra = extra || {};
    this.clearMedia();
    setText(this.empty, this.opts.emptyText || 'Reading the clip...');
    this.kind = kind;
    var m = make(kind === 'video' ? 'video' : 'audio', 'vx-scrub-media');
    m.muted = true;
    m.defaultMuted = true;
    m.playsInline = true;
    m.setAttribute('playsinline', '');
    m.setAttribute('muted', '');
    m.preload = 'metadata';
    if (extra.poster) m.poster = extra.poster;
    var self = this;
    on(m, 'loadedmetadata', function () {
      if (!self.alive || self.media !== m) return;
      self.stall(false);
      var d = Number(m.duration);
      if (!isFinite(d) || d <= 0) d = Number(extra.seconds) || NaN;
      self.dur = d;
      var want = extra.range || self.pending || {start: 0, end: d};
      self.pending = null;
      self.setRange(want.start, want.end === null || want.end === undefined ? d : want.end);
      self.drawPicture(extra);
      if (typeof self.opts.onReady === 'function') self.opts.onReady(self);
    });
    on(m, 'timeupdate', function () { self.tick(); });
    on(m, 'pause', function () { self.playing(false); });
    on(m, 'play', function () { self.playing(true); });
    on(m, 'error', function () {
      if (!self.alive) return;
      if (typeof self.opts.onError === 'function') self.opts.onError(self, kind);
    });
    if (kind === 'audio' && extra.spec) {
      var img = make('img', 'vx-scrub-spec');
      img.alt = 'Spectrogram of the clip';
      img.decoding = 'async';
      img.src = extra.spec;
      this.stage.appendChild(img);
    }
    this.stage.appendChild(m);
    this.stage.classList.toggle('vx-scrub-stage-audio', kind !== 'video');
    this.media = m;
    this.extra = extra;
    this.paintSound(false);
    m.src = src;
    this.stall(true);
    this.paint();
  };

  /* A media load that never answers (a WebView's socket pool is six deep,
   * and a slow share can sit on a request) is asked again once, then said. */
  Scrubber.prototype.stall = function (arm) {
    var self = this;
    root.clearTimeout(this.stallTimer);
    this.stallTimer = 0;
    if (!arm) return;
    var m = this.media;
    var tries = 0;
    var watch = function () {
      if (!self.alive || self.media !== m || self.ready()) return;
      tries += 1;
      if (tries === 1) {
        setText(self.empty, 'Still reading the clip - asked again.');
        try { m.load(); } catch (err) { /* the element is gone */ }
        self.stallTimer = root.setTimeout(watch, 9000);
      } else {
        setText(self.empty, 'The clip did not load on this screen.');
        if (typeof self.opts.onError === 'function') self.opts.onError(self, self.kind);
      }
    };
    this.stallTimer = root.setTimeout(watch, 7000);
  };

  Scrubber.prototype.clearMedia = function () {
    this.stall(false);
    this.stopFrames();
    if (this.raf) { try { root.cancelAnimationFrame(this.raf); } catch (err) { /* gone */ } this.raf = 0; }
    if (this.media) {
      try { this.media.pause(); } catch (err) { /* not started */ }
      try { this.media.removeAttribute('src'); this.media.load(); } catch (err) { /* released */ }
    }
    this.media = null;
    this.stage.replaceChildren();
    this.dur = NaN;
    this.wave.getContext && this.clearCanvas(this.wave);
    this.pic.getContext && this.clearCanvas(this.pic);
    setText(this.pictureNote, '');
  };

  Scrubber.prototype.clearCanvas = function (c) {
    try { var g = c.getContext('2d'); if (g) g.clearRect(0, 0, c.width, c.height); } catch (err) { /* no 2D here */ }
  };

  Scrubber.prototype.destroy = function () {
    this.alive = false;
    this.clearMedia();
  };

  Scrubber.prototype.setRange = function (a, b) {
    if (!this.ready()) {
      this.range = {start: r2(Math.max(0, a || 0)), end: r2(b || 0)};
      this.paint();
      return;
    }
    this.range = clampRange(a, b, this.dur, this.gap);
    this.paint();
    if (typeof this.opts.onRange === 'function') this.opts.onRange(this.range, this);
  };

  Scrubber.prototype.paint = function () {
    var ready = this.ready();
    this.el.classList.toggle('vx-scrub-ready', ready);
    this.empty.hidden = ready;
    this.hIn.hidden = !ready;
    this.hOut.hidden = !ready;
    this.sel.hidden = !ready;
    this.dimL.hidden = !ready;
    this.dimR.hidden = !ready;
    this.playBtn.disabled = !ready;
    if (ready) {
      var a = this.range.start / this.dur * 100;
      var b = this.range.end / this.dur * 100;
      this.hIn.style.left = a + '%';
      this.hOut.style.left = b + '%';
      this.sel.style.left = a + '%';
      this.sel.style.width = Math.max(0, b - a) + '%';
      this.dimL.style.width = a + '%';
      this.dimR.style.left = b + '%';
      this.dimR.style.width = Math.max(0, 100 - b) + '%';
      this.hIn.setAttribute('aria-valuemin', '0');
      this.hIn.setAttribute('aria-valuemax', String(this.dur));
      this.hIn.setAttribute('aria-valuenow', String(this.range.start));
      this.hIn.setAttribute('aria-valuetext', fmtTime(this.range.start));
      this.hOut.setAttribute('aria-valuemin', '0');
      this.hOut.setAttribute('aria-valuemax', String(this.dur));
      this.hOut.setAttribute('aria-valuenow', String(this.range.end));
      this.hOut.setAttribute('aria-valuetext', fmtTime(this.range.end));
    }
    if (!this.inField.__typing) this.inField.value = ready || this.range.start ? fmtTime(this.range.start) : '';
    if (!this.outField.__typing) this.outField.value = ready || this.range.end ? fmtTime(this.range.end) : '';
    var len = ready ? this.range.end - this.range.start : (this.range.end > this.range.start ? this.range.end - this.range.start : 0);
    setText(this.len, len > 0 ? 'Length ' + fmtTime(len) : (ready ? '' : 'No preview yet - the fields still set the range.'));
    this.tick();
  };

  Scrubber.prototype.tick = function () {
    var m = this.media;
    var t = m ? Number(m.currentTime) || 0 : 0;
    setText(this.clock, fmtTime(t) + ' / ' + (this.ready() ? fmtTime(this.dur) : '-'));
    if (this.ready()) this.head.style.left = (Math.min(this.dur, t) / this.dur * 100) + '%';
    this.head.hidden = !this.ready();
    if (m && this.stopAt && !m.paused && t >= this.stopAt - 0.03) {
      try { m.pause(); } catch (err) { /* stopped */ }
      this.stopAt = 0;
    }
  };

  Scrubber.prototype.loop = function () {
    var self = this;
    if (!this.alive || !this.media || this.media.paused) { this.raf = 0; return; }
    this.tick();
    this.raf = root.requestAnimationFrame(function () { self.loop(); });
  };

  Scrubber.prototype.playing = function (yes) {
    var b = this.playBtn;
    b.replaceChildren(ico(yes ? 'c:pause--filled' : 'c:caret--right'), make('span', 'vx-btn-words', yes ? 'Pause' : 'Play range'));
    b.classList.toggle('on', !!yes);
    if (yes && !this.raf) this.loop();
  };

  Scrubber.prototype.togglePlay = function () {
    var m = this.media;
    if (!m || !this.ready()) return;
    if (!m.paused) { try { m.pause(); } catch (err) { /* stopped */ } return; }
    var start = this.range.start;
    var end = this.range.end;
    if (this.opts.shortPlay) end = Math.min(end, start + SHORT_PLAY_S);
    this.stopAt = end;
    try { m.currentTime = start; } catch (err) { /* seek when it can */ }
    var p = null;
    try { p = m.play(); } catch (err) { p = null; }
    if (p && typeof p.catch === 'function') p.catch(function () { say('This screen would not start the preview.', 'bad'); });
  };

  Scrubber.prototype.toggleSound = function () {
    var m = this.media;
    var nowOn = m ? !!m.muted : !this.soundOn;
    if (m) m.muted = !nowOn;
    this.paintSound(nowOn);
  };

  Scrubber.prototype.paintSound = function (nowOn) {
    this.soundOn = !!nowOn;
    this.soundBtn.replaceChildren(ico(nowOn ? 'c:volume--up--filled' : 'c:volume--mute--filled'),
      make('span', 'vx-btn-words', nowOn ? 'Sound on' : 'Sound off'));
    this.soundBtn.classList.toggle('on', !!nowOn);
  };

  Scrubber.prototype.setAtHead = function (which) {
    if (!this.media || !this.ready()) return;
    var t = Number(this.media.currentTime) || 0;
    var next = dragHandle(which, t, this.range, this.dur, this.gap);
    this.setRange(next.start, next.end);
  };

  Scrubber.prototype.fromFields = function () {
    this.inField.__typing = false;
    this.outField.__typing = false;
    var a = parseTime(this.inField.value);
    var b = parseTime(this.outField.value);
    if ((a !== null && isNaN(a)) || (b !== null && isNaN(b))) {
      say('A time reads 90, 1:30 or 1:04:30.5.', 'bad');
      this.paint();
      return;
    }
    if (!this.ready()) {
      this.range = {start: a || 0, end: b === null ? 0 : b};
      this.pending = {start: a || 0, end: b};
      this.paint();
      if (typeof this.opts.onRange === 'function') this.opts.onRange(this.range, this);
      return;
    }
    this.setRange(a === null ? 0 : a, b === null ? this.dur : b);
  };

  Scrubber.prototype.box = function () {
    var r = this.strip.getBoundingClientRect();
    return {left: r.left, width: r.width};
  };

  Scrubber.prototype.handleDown = function (which, e) {
    if (!this.ready()) return;
    e.preventDefault();
    e.stopPropagation();
    var self = this;
    var h = which === 'in' ? this.hIn : this.hOut;
    h.classList.add('vx-dragging');
    var move = function (ev) {
      var b = self.box();
      var next = dragHandle(which, timeAt(ev.clientX, b.left, b.width, self.dur), self.range, self.dur, self.gap);
      self.range = next;
      self.paint();
    };
    var up = function (ev) {
      move(ev);
      h.classList.remove('vx-dragging');
      if (self.media) { try { self.media.currentTime = which === 'in' ? self.range.start : self.range.end; } catch (err2) { /* later */ } }
      self.setRange(self.range.start, self.range.end);
    };
    this.follow(e, h, move, up);
  };

  /* Follow one pointer to its release. The moves are read on the document
   * (capture), so a drag keeps going when the finger or the mouse leaves the
   * handle - with or without pointer capture, which not every engine grants. */
  Scrubber.prototype.follow = function (e, node, move, up) {
    var doc = root.document;
    var id = e.pointerId;
    try { node.setPointerCapture(id); } catch (err) { /* the document still hears it */ }
    var onMove = function (ev) { if (ev.pointerId === id) { ev.preventDefault(); move(ev); } };
    var onUp = function (ev) {
      if (ev.pointerId !== id) return;
      doc.removeEventListener('pointermove', onMove, true);
      doc.removeEventListener('pointerup', onUp, true);
      doc.removeEventListener('pointercancel', onUp, true);
      try { node.releasePointerCapture(id); } catch (err) { /* released */ }
      up(ev);
    };
    doc.addEventListener('pointermove', onMove, true);
    doc.addEventListener('pointerup', onUp, true);
    doc.addEventListener('pointercancel', onUp, true);
  };

  Scrubber.prototype.handleKey = function (which, e) {
    if (!this.ready()) return;
    var step = e.shiftKey ? 1 : 0.1;
    var cur = which === 'in' ? this.range.start : this.range.end;
    var t = null;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') t = cur - step;
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') t = cur + step;
    else if (e.key === 'Home') t = 0;
    else if (e.key === 'End') t = this.dur;
    if (t === null) return;
    e.preventDefault();
    var next = dragHandle(which, t, this.range, this.dur, this.gap);
    this.setRange(next.start, next.end);
  };

  /* A tap (or drag) on the strip itself moves the playhead - it never moves
   * a handle, so a stray touch cannot undo a careful cut. */
  Scrubber.prototype.stripDown = function (e) {
    if (!this.ready() || !this.media) return;
    if (e.target === this.hIn || e.target === this.hOut || this.hIn.contains(e.target) || this.hOut.contains(e.target)) return;
    e.preventDefault();
    var self = this;
    var seek = function (ev) {
      var b = self.box();
      var t = timeAt(ev.clientX, b.left, b.width, self.dur);
      try { self.media.currentTime = t; } catch (err) { /* later */ }
      self.head.style.left = (t / self.dur * 100) + '%';
      setText(self.clock, fmtTime(t) + ' / ' + fmtTime(self.dur));
    };
    seek(e);
    this.follow(e, this.strip, seek, seek);
  };

  /* ---- the picture under the handles: film frames, a spectrogram, a waveform */

  Scrubber.prototype.sizeCanvas = function (c) {
    var r = this.strip.getBoundingClientRect();
    var w = Math.max(60, Math.round(r.width || 600));
    var h = Math.max(30, Math.round(r.height || 64));
    if (c.width !== w) c.width = w;
    if (c.height !== h) c.height = h;
    return {w: w, h: h};
  };

  Scrubber.prototype.drawPicture = function (extra) {
    var self = this;
    try {
      if (extra.spec) {
        var img = new root.Image();
        img.decoding = 'async';
        img.onload = function () {
          if (!self.alive) return;
          try {
            var s = self.sizeCanvas(self.pic);
            self.pic.getContext('2d').drawImage(img, 0, 0, s.w, s.h);
            setText(self.pictureNote, 'picture: the clip\'s spectrogram');
          } catch (err) { /* the strip stays plain */ }
        };
        img.src = extra.spec;
      } else if (this.kind === 'video' && (extra.frames || 0) > 0) {
        this.frames(extra.frames);
      }
      if (extra.waveSrc) this.waveform(extra.waveSrc, extra.waveMostBytes || 0);
    } catch (err) { /* a plain strip still drags */ }
  };

  /* Film frames from a second, never-played, muted element on the same
   * (cached) file: seek, draw, next. One at a time, each bounded. */
  Scrubber.prototype.frames = function (n) {
    var self = this;
    var src = this.media && this.media.currentSrc;
    if (!src || !(this.dur > 0)) return;
    var v = document.createElement('video');
    v.muted = true;
    v.playsInline = true;
    v.preload = 'auto';
    var job = this.frameJob = {v: v, stop: false, timer: 0};
    var s = this.sizeCanvas(this.pic);
    var g = null;
    try { g = this.pic.getContext('2d'); } catch (err) { g = null; }
    if (!g) return;
    var i = 0;
    var slot = s.w / n;
    var next = function () {
      if (job.stop || !self.alive || i >= n) { self.stopFrames(); return; }
      var t = Math.min(self.dur - 0.05, (i + 0.5) / n * self.dur);
      root.clearTimeout(job.timer);
      job.timer = root.setTimeout(function () { i += 1; next(); }, 4000);
      try { v.currentTime = t; } catch (err) { i += 1; next(); }
    };
    v.addEventListener('seeked', function () {
      if (job.stop) return;
      try {
        var vw = v.videoWidth || 16, vh = v.videoHeight || 9;
        var dh = s.h, dw = Math.min(slot, dh * vw / vh);
        g.drawImage(v, i * slot + (slot - dw) / 2, 0, dw, dh);
      } catch (err) { /* a tainted or empty frame: leave the slot dark */ }
      i += 1;
      next();
    });
    v.addEventListener('loadedmetadata', function () { setText(self.pictureNote, 'picture: ' + n + ' frames of the preview'); next(); }, {once: true});
    v.addEventListener('error', function () { self.stopFrames(); }, {once: true});
    v.src = src;
  };

  Scrubber.prototype.stopFrames = function () {
    var job = this.frameJob;
    if (!job) return;
    job.stop = true;
    root.clearTimeout(job.timer);
    try { job.v.removeAttribute('src'); job.v.load(); } catch (err) { /* released */ }
    this.frameJob = null;
  };

  /* The waveform of the cached preview audio, decoded offline (no output, no
   * level, nothing heard). A screen that cannot fetch it keeps the frames. */
  Scrubber.prototype.waveform = function (src, mostBytes) {
    var self = this;
    var Off = root.OfflineAudioContext || root.webkitOfflineAudioContext;
    if (!Off || typeof root.fetch !== 'function') return;
    root.fetch(src, {cache: 'force-cache'}).then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      var size = Number(res.headers.get('content-length') || 0);
      if (mostBytes && size > mostBytes) throw new Error('too large to draw here');
      return res.arrayBuffer();
    }).then(function (buf) {
      if (!self.alive) return null;
      var ctx = new Off(1, 2, 22050);
      return new Promise(function (resolve, reject) {
        var p = ctx.decodeAudioData(buf, resolve, reject);
        if (p && typeof p.then === 'function') p.then(resolve, reject);
      });
    }).then(function (audio) {
      if (!audio || !self.alive) return;
      var data = audio.getChannelData(0);
      var s = self.sizeCanvas(self.wave);
      var g = self.wave.getContext('2d');
      g.clearRect(0, 0, s.w, s.h);
      g.fillStyle = 'rgba(101, 199, 218, .85)';
      var per = Math.max(1, Math.floor(data.length / s.w));
      for (var x = 0; x < s.w; x += 1) {
        var peak = 0;
        var from = x * per;
        for (var k = 0; k < per; k += 8) { var v = Math.abs(data[from + k] || 0); if (v > peak) peak = v; }
        var hh = Math.max(1, peak * s.h * 0.9);
        g.fillRect(x, (s.h - hh) / 2, 1, hh);
      }
      setText(self.pictureNote, (self.pictureNote.textContent ? self.pictureNote.textContent + ' + ' : 'picture: ') + 'waveform');
    }).catch(function () { /* frames only on this screen */ });
  };

  /* ================================================== the specifics form */

  function specifics(prefix, opts) {
    opts = opts || {};
    var wrap = make('div', 'vx-spec vx-spec-' + prefix);
    var name = textInput('vx-name', opts.namePlaceholder || 'Name for the actor');
    name.maxLength = 80;
    var who = textInput('vx-who', 'Who is this? (the person, the show, the role)');
    who.maxLength = 200;
    var notes = make('textarea', 'vx-input vx-notes');
    notes.rows = 2;
    notes.maxLength = 600;
    notes.placeholder = 'Notes - how they talk, what to use them for, what to avoid';
    var row1 = make('div', 'vx-spec-row');
    row1.appendChild(field('Name', name));
    row1.appendChild(field('Who is this', who));
    wrap.appendChild(row1);
    wrap.appendChild(field('Notes', notes));

    var engRow = make('div', 'vx-spec-row vx-engines');
    var engBox = make('div', 'vx-engine-pick');
    engBox.appendChild(make('span', 'vx-field-label', 'Cut the reference for'));
    var checks = {};
    var prefRadios = {};
    var prefBox = make('div', 'vx-pref-pick');
    prefBox.appendChild(make('span', 'vx-field-label', 'Preferred engine'));
    ENGINES.forEach(function (e) {
      var l = make('label', 'vx-check');
      var c = make('input');
      c.type = 'checkbox';
      c.value = e;
      c.className = 'vx-engine-' + e;
      l.appendChild(c);
      var ref = refs()[e];
      var refS = ref && ref.ref_s !== undefined ? ref.ref_s : REF_DEFAULT[e];
      l.appendChild(make('span', '', ENGINE_WORDS[e] + ' (' + refS + ' s reference)'));
      engBox.appendChild(l);
      checks[e] = c;
      var pl = make('label', 'vx-check');
      var r = make('input');
      r.type = 'radio';
      r.name = 'vx-pref-' + prefix;
      r.value = e;
      r.className = 'vx-pref-' + e;
      pl.appendChild(r);
      pl.appendChild(make('span', '', ENGINE_WORDS[e]));
      prefBox.appendChild(pl);
      prefRadios[e] = r;
    });
    engRow.appendChild(engBox);
    engRow.appendChild(prefBox);
    var spk = make('select', 'vx-input vx-speaker');
    [['', 'Auto - whoever talks most'], ['Speaker 1', 'Speaker 1'], ['Speaker 2', 'Speaker 2'],
      ['Speaker 3', 'Speaker 3'], ['Speaker 4', 'Speaker 4']].forEach(function (o) {
      var opt = make('option', '', o[1]);
      opt.value = o[0];
      spk.appendChild(opt);
    });
    engRow.appendChild(field('Speaker', spk, 'the lab names speakers by talk time after it diarizes'));
    wrap.appendChild(engRow);
    var engineNote = make('div', 'vx-engine-note');
    wrap.appendChild(engineNote);

    var act = activeEngine();
    var start = (act && act.engine && checks[act.engine]) ? act.engine : 'xtts';
    checks[start].checked = true;
    prefRadios[start].checked = true;

    function paintEngineNote() {
      var e = activeEngine();
      var chosen = ENGINES.filter(function (k) { return checks[k].checked; });
      var bits = [];
      if (e && e.engine) {
        bits.push('The station speaks through ' + (ENGINE_WORDS[e.engine] || String(e.engine).toUpperCase())
          + ' now' + (e.ready === false ? ' (not ready)' : '') + ' - every actor speaks through that one engine; the switch is the engine strip\'s.');
        ENGINES.forEach(function (k) {
          var row = e.engines && e.engines[k];
          if (row && row.ready === false && checks[k].checked) {
            bits.push(ENGINE_WORDS[k] + ' is down (' + String(row.detail || 'not ready') + '); a reference cut for it still lands in the library.');
          }
        });
      }
      if (chosen.length === 2) bits.push('Both ticked = two captures: the lab runs twice, one reference per engine, linked as twins.');
      setText(engineNote, bits.join(' '));
      ENGINES.forEach(function (k) {
        prefRadios[k].disabled = !checks[k].checked;
        if (!checks[k].checked && prefRadios[k].checked) {
          var other = chosen[0];
          if (other) prefRadios[other].checked = true;
        }
      });
    }
    ENGINES.forEach(function (k) { on(checks[k], 'change', paintEngineNote); });
    paintEngineNote();

    return {
      el: wrap, name: name, who: who, notes: notes, checks: checks, prefs: prefRadios, speaker: spk,
      engines: function () { return ENGINES.filter(function (k) { return checks[k].checked; }); },
      preferred: function () {
        for (var i = 0; i < ENGINES.length; i += 1) if (prefRadios[ENGINES[i]].checked && checks[ENGINES[i]].checked) return ENGINES[i];
        return '';
      },
      read: function () {
        return {name: name.value.trim(), who: who.value.trim(), notes: notes.value.trim(),
          engines: this.engines(), preferred: this.preferred(), speaker: spk.value};
      },
      repaint: paintEngineNote
    };
  }

  function adviceList(node, items) {
    node.replaceChildren();
    items.forEach(function (a) {
      var li = make('div', 'vx-advice vx-advice-' + a.tone);
      li.appendChild(ico(a.tone === 'ok' ? 'c:checkmark--filled' : 'c:warning--alt'));
      li.appendChild(make('span', '', a.text));
      node.appendChild(li);
    });
  }

  /* ================================================== jobs: store, poll, events */

  function jobs() { return S ? S.jobs : readJobs(storage()); }

  function saveJobs() { if (S) writeJobs(storage(), S.jobs); }

  function addJob(job) {
    if (!S) return;
    S.jobs.push(job);
    saveJobs();
    emit('extract-jobs', {jobs: S.jobs.map(eventOf)});
    emit('extract-job', eventOf(job));
    paintJobs();
    paintTabs();
  }

  function jobPath(job) {
    return job.legacy ? '/api/voicelab/jobs/' + encodeURIComponent(job.id)
      : '/api/voice-actor/extract/jobs/' + encodeURIComponent(job.id);
  }

  function activeJobs() {
    return (S ? S.jobs : []).filter(function (j) { var p = jobPhase(j); return p !== 'done' && p !== 'error'; });
  }

  function pollOnce() {
    if (!S) return Promise.resolve();
    var list = activeJobs();
    if (!list.length) return Promise.resolve();
    S.pollAt = (S.pollAt || 0) % list.length;
    var pick = list.slice(S.pollAt, S.pollAt + 3);
    if (pick.length < 3) pick = pick.concat(list.slice(0, Math.min(list.length, 3) - pick.length));
    S.pollAt += 3;
    return Promise.all(pick.map(function (job) {
      return request('GET', jobPath(job)).then(function (st) {
        /* the raw answer too (partial transcript + signature included), for
         * the tile rail's richer readout - the lab's own fields, verbatim */
        emit('job', {job_id: job.id, status: st || {}, name: job.name || ''});
        updateJob(job.id, st || {});
      }, function (err) {
        if (err && err.status === 404) {
          updateJob(job.id, {stage: 'error', error: job.legacy ? 'The lab no longer knows this job.' : 'The station no longer knows this job.',
            error_kind: 'GONE'});
        } else {
          var j = findJob(job.id);
          if (j) { j.pollFail = String((err && err.message) || err); paintJob(j); }
        }
      });
    }));
  }

  function findJob(id) {
    if (!S) return null;
    for (var i = 0; i < S.jobs.length; i += 1) if (S.jobs[i].id === id) return S.jobs[i];
    return null;
  }

  function updateJob(id, st) {
    if (!S) return;
    for (var i = 0; i < S.jobs.length; i += 1) {
      if (S.jobs[i].id !== id) continue;
      var before = JSON.stringify(eventOf(S.jobs[i]));
      var was = jobPhase(S.jobs[i]);
      var next = foldStatus(S.jobs[i], st);
      next.pollFail = '';
      S.jobs[i] = next;
      var after = eventOf(next);
      var changed = JSON.stringify(after) !== before;
      if (changed) {
        saveJobs();
        emit('extract-job', after);
      }
      if (was !== 'done' && jobPhase(next) === 'done') landed(next);
      paintJob(next);
      paintTabs();
      return;
    }
  }

  /** A voice is in the library: tell the shell once, and record the
   *  preferred engine on it (the shell's store; absent -> said once). */
  function landed(job) {
    if (!S || job.announced) return;
    job.announced = true;
    saveJobs();
    say('"' + (job.name || 'The new actor') + '" is in the voice library' + (job.user_submitted ? ' (user-submitted - credited)' : '') + '.');
    try {
      if (typeof S.ctx.actorCreated === 'function') {
        Promise.resolve(S.ctx.actorCreated({id: job.voice_id, name: job.name, engine: job.engine})).catch(function () { /* the shell repaints on its own clock */ });
      }
    } catch (err) { /* the shell's own business */ }
    if (job.preferred && job.voice_id && !job.prefSent) {
      var mark = function (how) {
        var j = findJob(job.id);
        if (!j) return;
        j.prefSent = how;
        saveJobs();
        paintJob(j);
      };
      request('POST', '/api/voice-actor/prefs', {voice_id: job.voice_id, preferred: job.preferred}).then(function () {
        mark(true);
      }, function (err) { mark(absent(err) ? 'absent' : 'failed'); });
    }
  }

  function startPolling() {
    if (!S) return;
    var tick = function () {
      if (!S) return;
      pollOnce().then(function () { if (S) S.pollTimer = later(tick, POLL_MS); },
        function () { if (S) S.pollTimer = later(tick, POLL_MS); });
    };
    S.pollTimer = later(tick, 200);
  }

  /* Jobs a second glass started, from the station's own list. */
  function mergeServerJobs() {
    return request('GET', '/api/voice-actor/extract/jobs').then(function (got) {
      if (!S) return;
      var added = 0;
      var dayAgo = Date.now() / 1000 - 86400;
      (got.jobs || []).slice().reverse().forEach(function (row) {
        if (!row.vx || findJob(row.vx) || Number(row.created || 0) < dayAgo) return;
        S.jobs.push({id: row.vx, kind: row.kind === 'cart' ? 'cart' : 'link', name: row.name, engine: row.engine,
          twin: row.twin, label: row.kind === 'cart' ? (row.clips || []).length + ' clip(s)' : row.url,
          clips: row.clips || [], user_submitted: !!row.user_submitted, stage: row.stage,
          voice_id: row.voice_id || '', harvested: row.state === 'done', announced: row.state === 'done',
          error: row.error || '', created: row.created, fromStation: true});
        added += 1;
      });
      if (added) { saveJobs(); emit('extract-jobs', {jobs: S.jobs.map(eventOf)}); paintJobs(); paintTabs(); }
    }, function () { /* an older station: the local list is the list */ });
  }

  /* ================================================== the pages */

  var TABS = [
    {id: 'link', word: 'Link', icon: 'c:link'},
    {id: 'library', word: 'SFX library', icon: 'c:folders'},
    {id: 'uploads', word: 'Listener uploads', icon: 'c:user'},
    {id: 'jobs', word: 'Jobs', icon: 'c:hourglass'}
  ];

  function build(el) {
    var rootEl = make('div', 'vx-root' + (S.ctx.isTablet ? ' vx-tablet' : ''));
    var tabs = make('div', 'vx-tabs');
    tabs.setAttribute('role', 'tablist');
    S.tabBtns = {};
    TABS.forEach(function (t) {
      var b = btn('vx-tab vx-tab-' + t.id, t.word, t.icon);
      b.setAttribute('role', 'tab');
      b.appendChild(make('span', 'vx-tab-count', ''));
      on(b, 'click', function (e) { e.stopPropagation(); showTab(t.id); });
      tabs.appendChild(b);
      S.tabBtns[t.id] = b;
    });
    rootEl.appendChild(tabs);
    S.note = make('div', 'vx-note', '');
    S.note.setAttribute('role', 'status');
    rootEl.appendChild(S.note);
    S.pages = {};
    var pages = make('div', 'vx-pages');
    S.pages.link = buildLink();
    S.pages.library = buildLibrary();
    S.pages.jobs = buildJobs();
    pages.appendChild(S.pages.link);
    pages.appendChild(S.pages.library);
    pages.appendChild(S.pages.jobs);
    rootEl.appendChild(pages);
    el.appendChild(rootEl);
    S.rootEl = rootEl;
  }

  function showTab(id) {
    if (!S) return;
    S.tab = id;
    writeJson(storage(), TAB_KEY, id);
    S.pages.link.hidden = id !== 'link';
    S.pages.library.hidden = !(id === 'library' || id === 'uploads');
    S.pages.jobs.hidden = id !== 'jobs';
    TABS.forEach(function (t) {
      var b = S.tabBtns[t.id];
      b.classList.toggle('on', t.id === id);
      b.setAttribute('aria-selected', t.id === id ? 'true' : 'false');
    });
    if (id === 'uploads') openFolder(userRoot(), 'Listener uploads');
    else if (id === 'library' && S.lib && S.lib.mode === 'user') openFolder(S.lib.lastFolder || '', S.lib.lastFolderName || '');
    if (id === 'library' || id === 'uploads') loadFolders();
  }

  function paintTabs() {
    if (!S || !S.tabBtns) return;
    var running = activeJobs().length;
    setText(S.tabBtns.jobs.querySelector('.vx-tab-count'), running ? String(running) : (S.jobs.length ? String(S.jobs.length) : ''));
    S.tabBtns.jobs.classList.toggle('vx-busy', running > 0);
    var n = S.cart.length;
    setText(S.tabBtns.library.querySelector('.vx-tab-count'), n ? String(n) : '');
  }

  /* -------------------------------------------------- Link */

  function buildLink() {
    var page = make('section', 'vx-page vx-page-link');
    var draft = readJson(storage(), LINK_KEY, {}) || {};
    var row = make('div', 'vx-link-row');
    var input = S.linkInput = textInput('vx-url', 'Paste a YouTube link (or any video / audio address)', draft.url || '');
    input.setAttribute('inputmode', 'url');
    var load = btn('vx-primary vx-load', 'Load preview', 'c:view', 'Fetch the media for the in/out strip');
    row.appendChild(input);
    row.appendChild(load);
    page.appendChild(row);
    page.appendChild(make('div', 'vx-hint',
      'The preview is the sample extractor\'s road: the station fetches the whole media into its sample cache first '
      + '(the range is cut afterwards, never asked of the site). The signature job downloads it again and deletes its copy after extraction - the lab\'s rule.'));
    var fetchLine = S.fetchLine = make('div', 'vx-fetch-line', '');
    page.appendChild(fetchLine);

    S.linkScrub = new Scrubber({gap: LINK_GAP_S, frames: S.ctx.isTablet ? 5 : 10,
      emptyText: 'Load a preview to see the picture and drag the IN and OUT handles. The fields below set the range either way.',
      onRange: function () { paintLinkAdvice(); saveLinkDraft(); },
      onError: function (sc, kind) {
        if (kind === 'video' && S && S.preview && S.preview.audio) {
          setText(S.fetchLine, 'No picture for this one - the audio alone.');
          sc.setMedia('audio', url(S.preview.audio), {waveSrc: url(S.preview.audio), waveMostBytes: S.ctx.isTablet ? 15e6 : 60e6,
            range: sc.range.end > sc.range.start ? sc.range : null});
        } else {
          say('This screen could not play the preview.', 'bad');
        }
      }});
    page.appendChild(S.linkScrub.el);
    if (draft.start !== undefined || draft.end !== undefined) {
      S.linkScrub.range = {start: Number(draft.start) || 0, end: Number(draft.end) || 0};
      S.linkScrub.pending = {start: Number(draft.start) || 0, end: draft.end ? Number(draft.end) : null};
      S.linkScrub.paint();
    }
    S.linkAdvice = make('div', 'vx-advice-list');
    page.appendChild(S.linkAdvice);

    S.linkSpec = specifics('link', {namePlaceholder: 'Name for the actor (the video title if left empty)'});
    if (draft.name) S.linkSpec.name.value = draft.name;
    if (draft.who) S.linkSpec.who.value = draft.who;
    if (draft.notes) S.linkSpec.notes.value = draft.notes;
    page.appendChild(S.linkSpec.el);
    ENGINES.forEach(function (k) { on(S.linkSpec.checks[k], 'change', paintLinkAdvice); });
    [S.linkSpec.name, S.linkSpec.who, S.linkSpec.notes, input].forEach(function (n) { on(n, 'input', saveLinkDraft); });

    var go = btn('vx-primary vx-extract-link', 'Extract signature', 'c:chemistry', 'Send the link and range to the voice lab');
    var foot = make('div', 'vx-foot');
    foot.appendChild(go);
    page.appendChild(foot);

    on(load, 'click', function (e) { e.stopPropagation(); loadPreview(); });
    on(input, 'keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); loadPreview(); } });
    on(go, 'click', function (e) { e.stopPropagation(); submitLink(go); });
    paintLinkAdvice();
    return page;
  }

  function saveLinkDraft() {
    if (!S || !S.linkSpec) return;
    var r = S.linkScrub.range;
    writeJson(storage(), LINK_KEY, {url: S.linkInput.value, start: r.start, end: r.end,
      name: S.linkSpec.name.value, who: S.linkSpec.who.value, notes: S.linkSpec.notes.value});
  }

  function linkSeconds() {
    var sc = S.linkScrub;
    if (sc.ready()) return sc.range.end - sc.range.start;
    if (sc.range.end > sc.range.start) return sc.range.end - sc.range.start;
    return NaN;
  }

  function paintLinkAdvice() {
    if (!S || !S.linkAdvice || !S.linkSpec) return;
    var secs = linkSeconds();
    if (!isFinite(secs)) {
      adviceList(S.linkAdvice, [{tone: 'warn', text: 'No range yet - the whole media goes to the lab (a long video is a long job).'}]);
      return;
    }
    adviceList(S.linkAdvice, lengthAdvice(secs, S.linkSpec.engines(), refs()));
  }

  function loadPreview() {
    if (!S) return;
    var u = S.linkInput.value.trim();
    if (!u) { say('Paste a link first.', 'bad'); return; }
    if (S.preview && S.preview.url === u && S.preview.state === 'fetching') return;
    S.preview = {url: u, state: 'fetching', job: ''};
    S.linkScrub.clearMedia();
    S.linkScrub.paint();
    setText(S.fetchLine, 'Asking the station to fetch it...');
    var mine = S.preview;
    request('POST', '/api/samples/fetch', {url: u, video: true}).then(function (got) {
      if (!S || S.preview !== mine) return;
      mine.job = String((got && got.job_id) || '');
      if (!mine.job) throw new Error('the station answered without a job');
      pollPreview(mine);
    }).catch(function (err) {
      if (!S || S.preview !== mine) return;
      mine.state = 'error';
      setText(S.fetchLine, 'The preview fetch failed: ' + String((err && err.message) || err));
      say('The preview fetch failed - the fields still set a range.', 'bad');
    });
  }

  function pollPreview(mine) {
    if (!S || S.preview !== mine) return;
    request('GET', '/api/samples/job/' + encodeURIComponent(mine.job)).then(function (st) {
      if (!S || S.preview !== mine) return;
      st = st || {};
      if (st.stage === 'done') {
        mine.state = 'done';
        mine.audio = st.audio || '';
        mine.video = st.video || '';
        setText(S.fetchLine, 'Fetched' + (st.title ? ': ' + st.title : '') + '. Drag IN and OUT on the strip.');
        if (st.title && !S.linkSpec.name.value) S.linkSpec.name.placeholder = st.title;
        var keep = S.linkScrub.pending || (S.linkScrub.range.end > S.linkScrub.range.start ? S.linkScrub.range : null);
        S.linkScrub.setMedia(mine.video ? 'video' : 'audio', url(mine.video || mine.audio), {
          frames: S.ctx.isTablet ? 5 : 10, range: keep,
          waveSrc: mine.audio ? url(mine.audio) : '', waveMostBytes: S.ctx.isTablet ? 15e6 : 60e6});
        return;
      }
      if (st.stage === 'error') {
        mine.state = 'error';
        setText(S.fetchLine, 'The preview fetch failed: ' + String(st.error || 'the lab gave no reason'));
        return;
      }
      var stage = String(st.stage || 'queued');
      var pct = Math.round(Number(st.progress || 0) * 100);
      setText(S.fetchLine, 'Fetching the preview - ' + (STAGE_WORDS[stage] || stage) + (pct ? ' ' + pct + '%' : '')
        + (st.note ? ' - ' + st.note : ''));
      later(function () { pollPreview(mine); }, FETCH_POLL_MS);
    }, function (err) {
      if (!S || S.preview !== mine) return;
      setText(S.fetchLine, 'The preview job could not be read: ' + String((err && err.message) || err));
      later(function () { pollPreview(mine); }, FETCH_POLL_MS * 2);
    });
  }

  function submitLink(button) {
    if (!S) return;
    var u = S.linkInput.value.trim();
    if (!u) { say('Paste a link first.', 'bad'); return; }
    var spec = S.linkSpec.read();
    if (!spec.engines.length) { say('Tick the engine the reference is cut for (XTTS, F5 or both).', 'bad'); return; }
    var sc = S.linkScrub;
    if (!sc.ready()) sc.fromFields();
    var body = sc.ready() ? rangeBody(sc.range, sc.dur)
      : {start: sc.range.start > 0 ? sc.range.start : null, end: sc.range.end > sc.range.start ? sc.range.end : null};
    var secs = linkSeconds();
    if (isFinite(secs) && secs > 0 && secs < LEAST_S) { say('The range is under ' + LEAST_S + ' s - widen it.', 'bad'); return; }
    button.disabled = true;
    var name = spec.name;
    var twin = '';
    var both = spec.engines.length === 2;
    var chain = Promise.resolve();
    spec.engines.forEach(function (engine) {
      chain = chain.then(function () {
        var jobName = both && name ? name + ' (' + ENGINE_WORDS[engine] + ')' : name;
        var payload = {url: u, start: body.start, end: body.end, name: jobName, who: spec.who, notes: spec.notes,
          engine: engine, speaker: spec.speaker, twin: twin};
        return request('POST', '/api/voice-actor/extract/link', payload).then(function (got) {
          twin = got.vx;
          addJob({id: got.vx, kind: 'link', name: got.name || jobName || u, engine: engine, twin: got.twin || '',
            label: u, range: got.range || '', stage: 'queued', station: true, preferred: spec.preferred,
            created: Date.now() / 1000});
        }, function (err) {
          if (!absent(err)) throw err;
          /* an older station: the studio's own road, without the specifics */
          return request('POST', '/api/voicelab/ingest', {url: u, start: body.start, end: body.end, mode: 'both',
            name: jobName, engine: engine, speaker: spec.speaker}).then(function (got) {
            addJob({id: got.job_id, kind: 'link', legacy: true, name: jobName || u, engine: engine, label: u,
              stage: 'queued', preferred: spec.preferred, created: Date.now() / 1000,
              note: 'sent through /api/voicelab/ingest - who / notes are not kept on this station yet'});
          });
        });
      });
    });
    chain.then(function () {
      say('Sent to the voice lab' + (both ? ' twice - one reference per engine' : '') + '. The Jobs page follows it.');
      showTab('jobs');
    }, function (err) {
      say('The lab did not take it: ' + String((err && err.message) || err), 'bad');
    }).then(function () { button.disabled = false; });
  }

  /* -------------------------------------------------- Library + Uploads */

  function userRoot() {
    return (S && S.health && S.health.user_root) || '/samples/samples_grabbed/user';
  }

  function buildLibrary() {
    var page = make('section', 'vx-page vx-page-lib');
    S.lib = {folders: null, folder: '', folderName: '', q: '', video: '', offset: 0, rows: [], mode: 'folder',
      previewItem: null, posterQueue: [], posterBusy: 0};
    var grid = make('div', 'vx-lib');

    /* folders */
    var fcol = make('div', 'vx-col vx-col-folders');
    var fhead = make('div', 'vx-col-head');
    fhead.appendChild(ico('c:folders'));
    fhead.appendChild(make('b', '', 'Folders'));
    fcol.appendChild(fhead);
    S.lib.folderFilter = textInput('vx-folder-filter', 'Filter folders');
    fcol.appendChild(S.lib.folderFilter);
    S.lib.folderList = make('div', 'vx-folder-list');
    S.lib.folderList.setAttribute('role', 'listbox');
    fcol.appendChild(S.lib.folderList);
    on(S.lib.folderFilter, 'input', paintFolders);
    grid.appendChild(fcol);

    /* clips */
    var ccol = make('div', 'vx-col vx-col-clips');
    var search = make('div', 'vx-search');
    S.lib.searchInput = textInput('vx-search-input', 'Search the clip book - names, what is said, what is seen');
    S.lib.searchInput.setAttribute('inputmode', 'search');
    var sbtn = btn('vx-search-go', 'Search', 'c:search', 'Search the clip book');
    search.appendChild(S.lib.searchInput);
    search.appendChild(sbtn);
    ccol.appendChild(search);
    var filters = make('div', 'vx-filters');
    S.lib.filterBtns = {};
    [['', 'All'], ['1', 'Video'], ['0', 'Audio']].forEach(function (f) {
      var b = btn('vx-filter', f[1], '', 'Show ' + f[1].toLowerCase());
      b.dataset.video = f[0];
      on(b, 'click', function (e) { e.stopPropagation(); S.lib.video = f[0]; paintFilters(); reloadClips(); });
      filters.appendChild(b);
      S.lib.filterBtns[f[0]] = b;
    });
    S.lib.where = make('span', 'vx-where', '');
    filters.appendChild(S.lib.where);
    ccol.appendChild(filters);
    S.lib.clipList = make('div', 'vx-clip-list');
    S.lib.more = btn('vx-more', 'Show more', 'c:add', 'Load the next page of clips');
    S.lib.more.hidden = true;
    S.lib.clipWrap = make('div', 'vx-clip-wrap');
    S.lib.clipWrap.appendChild(S.lib.clipList);
    S.lib.clipWrap.appendChild(S.lib.more);
    ccol.appendChild(S.lib.clipWrap);
    S.lib.previewBox = make('div', 'vx-preview');
    S.lib.previewBox.hidden = true;
    ccol.appendChild(S.lib.previewBox);
    on(sbtn, 'click', function (e) { e.stopPropagation(); runSearch(); });
    on(S.lib.searchInput, 'keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); runSearch(); } });
    on(S.lib.more, 'click', function (e) { e.stopPropagation(); loadClips(true); });
    grid.appendChild(ccol);

    /* the cart */
    grid.appendChild(buildCart());
    page.appendChild(grid);
    paintFilters();
    return page;
  }

  function paintFilters() {
    if (!S || !S.lib) return;
    Object.keys(S.lib.filterBtns).forEach(function (k) {
      S.lib.filterBtns[k].classList.toggle('on', k === S.lib.video);
      S.lib.filterBtns[k].setAttribute('aria-pressed', k === S.lib.video ? 'true' : 'false');
    });
  }

  function loadFolders() {
    if (!S || S.lib.folders || S.lib.foldersLoading) return;
    S.lib.foldersLoading = true;
    setText(S.lib.folderList, 'Reading the clip book...');
    request('GET', '/api/sfx/folders').then(function (got) {
      if (!S) return;
      S.lib.folders = (got && got.folders) || [];
      paintFolders();
    }, function (err) {
      if (!S) return;
      S.lib.foldersLoading = false;
      setText(S.lib.folderList, 'The folders could not be read: ' + String((err && err.message) || err));
    });
  }

  function paintFolders() {
    if (!S || !S.lib.folders) return;
    var list = S.lib.folderList;
    var q = S.lib.folderFilter.value.trim().toLowerCase();
    list.replaceChildren();
    var user = {path: userRoot(), name: 'Listener uploads', audio: 0, video: 0, pinned: true};
    S.lib.folders.forEach(function (f) { if (isUserFolder(f.path)) { user.audio = f.audio; user.video = f.video; } });
    var rows = [user].concat(S.lib.folders.filter(function (f) { return !isUserFolder(f.path); }));
    rows.forEach(function (f) {
      if (!f.pinned && q && String(f.name).toLowerCase().indexOf(q) < 0 && String(f.path).toLowerCase().indexOf(q) < 0) return;   /* the uploads stay pinned */
      var b = make('button', 'vx-folder' + (f.pinned ? ' vx-folder-user' : '') + (S.lib.folder === f.path ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('role', 'option');
      b.dataset.path = f.path;
      b.appendChild(ico(f.pinned ? 'c:user' : 'c:folder'));
      var words = make('span', 'vx-folder-words');
      words.appendChild(make('b', '', f.name));
      var counts = [];
      if (f.video) counts.push(f.video + ' video');
      if (f.audio) counts.push(f.audio + ' audio');
      words.appendChild(make('span', 'vx-folder-counts', counts.join(' / ') || (f.pinned ? 'samples_grabbed/user' : 'empty')));
      b.appendChild(words);
      on(b, 'click', function (e) { e.stopPropagation(); openFolder(f.path, f.name); });
      list.appendChild(b);
    });
  }

  function openFolder(path, name) {
    if (!S) return;
    closePreview();
    S.lib.mode = isUserFolder(path) ? 'user' : 'folder';
    if (S.lib.mode === 'folder') { S.lib.lastFolder = path; S.lib.lastFolderName = name; }
    S.lib.folder = path;
    S.lib.folderName = name || path.split('/').pop();
    S.lib.q = '';
    S.lib.searchInput.value = '';
    reloadClips();
    if (S.lib.folders) {
      var btns = S.lib.folderList.querySelectorAll('.vx-folder');
      for (var i = 0; i < btns.length; i += 1) btns[i].classList.toggle('on', btns[i].dataset.path === path);
    }
  }

  function runSearch() {
    if (!S) return;
    var q = S.lib.searchInput.value.trim();
    if (!q) { say('Type something to search for.', 'bad'); return; }
    closePreview();
    S.lib.q = q;
    S.lib.mode = 'search';
    reloadClips();
  }

  function reloadClips() {
    if (!S) return;
    S.lib.offset = 0;
    S.lib.rows = [];
    S.lib.clipList.replaceChildren();
    S.lib.posterQueue = [];
    loadClips(false);
  }

  function inlineSamples(folder) {
    var out = [];
    (S.lib.folders || []).forEach(function (f) {
      if (f.path !== folder && folder) return;
      (f.samples || []).forEach(function (smp) {
        out.push({id: smp.id, name: smp.name, video: !!smp.video, seconds: smp.seconds, url: smp.url,
          poster_url: '', spec_url: '', folder: f.path, user: isUserFolder(f.path)});
      });
    });
    return out;
  }

  function loadClips(more) {
    if (!S || S.lib.loading) return;
    if (!S.lib.q && !S.lib.folder) {
      setText(S.lib.where, 'Pick a folder, or search.');
      return;
    }
    S.lib.loading = true;
    var q = S.lib.q;
    var folder = q ? '' : S.lib.folder;
    var params = ['limit=' + PAGE, 'offset=' + S.lib.offset];
    if (folder) params.push('folder=' + encodeURIComponent(folder));
    if (q) params.push('q=' + encodeURIComponent(q));
    if (S.lib.video) params.push('video=' + S.lib.video);
    setText(S.lib.where, more ? 'Reading more...' : 'Reading the clip book...');
    var ask = S.lib.ask = {};
    request('GET', '/api/voice-actor/extract/sfx?' + params.join('&')).then(function (got) {
      if (!S || S.lib.ask !== ask) return;
      S.lib.loading = false;
      var rows = (got && got.clips) || [];
      S.lib.offset += rows.length;
      S.lib.rows = S.lib.rows.concat(rows);
      rows.forEach(function (c) { S.lib.clipList.appendChild(clipRow(c)); });
      S.lib.more.hidden = !got.more;
      var head = q ? 'Search "' + q + '" - ' + S.lib.rows.length + (got.more ? '+' : '') + ' match(es)' + (got.how === 'index' ? '' : ' by name')
        : S.lib.folderName + ' - ' + (got.total >= 0 ? got.total + ' clip(s)' : S.lib.rows.length + ' shown');
      setText(S.lib.where, head);
      if (got.say && (!rows.length || got.how === 'names')) say(got.say);
      if (!S.lib.rows.length) {
        var empty = make('div', 'vx-empty', got.say || (q ? 'Nothing matches.' : 'This folder has no playable clips in the clip book.'));
        S.lib.clipList.appendChild(empty);
      }
    }, function (err) {
      if (!S || S.lib.ask !== ask) return;
      S.lib.loading = false;
      if (absent(err)) {
        /* an older station: what /api/sfx/folders carries inline (three a kind) */
        var rows = inlineSamples(folder).filter(function (c) {
          return (!q || String(c.name).toLowerCase().indexOf(q.toLowerCase()) >= 0)
            && (!S.lib.video || String(c.video ? 1 : 0) === S.lib.video);
        });
        if (!more) rows.forEach(function (c) { S.lib.clipList.appendChild(clipRow(c)); });
        S.lib.rows = rows;
        S.lib.more.hidden = true;
        setText(S.lib.where, 'Only the samples /api/sfx/folders carries - the full listing needs tools/voice_actor_extract_patch.py on the station.');
        return;
      }
      setText(S.lib.where, 'The clip book could not be read: ' + String((err && err.message) || err));
    });
  }

  function clipRow(c) {
    var row = make('div', 'vx-clip' + (c.user ? ' vx-clip-user' : ''));
    row.dataset.id = c.id;
    var thumb = make('div', 'vx-thumb' + (c.video ? ' vx-thumb-video' : ' vx-thumb-audio'));
    thumb.appendChild(ico(c.video ? 'c:screen' : 'c:music'));
    if (c.video && c.poster_url) queuePoster(thumb, c.poster_url);
    row.appendChild(thumb);
    var words = make('div', 'vx-clip-words');
    words.appendChild(make('b', 'vx-clip-name', c.name));
    var meta = make('span', 'vx-clip-meta');
    meta.appendChild(make('span', 'vx-tag ' + (c.video ? 'vx-tag-video' : 'vx-tag-audio'), c.video ? 'MP4' : 'AUDIO'));
    if (c.user) meta.appendChild(make('span', 'vx-tag vx-tag-user', 'USER'));
    meta.appendChild(make('span', '', fmtTime(c.seconds || 0)));
    if (S.lib.mode === 'search' && c.folder) meta.appendChild(make('span', 'vx-clip-folder', c.folder.split('/').pop()));
    words.appendChild(meta);
    if (c.said) words.appendChild(make('span', 'vx-clip-said', '"' + c.said + '"'));
    row.appendChild(words);
    var pv = btn('vx-clip-preview', 'Preview', 'c:view', 'Preview ' + c.name + ' (muted until you ask)');
    var add = btn('vx-clip-add', 'Cart', 'c:add', 'Put the whole clip in the bin cart');
    on(pv, 'click', function (e) { e.stopPropagation(); openPreview(c, null); });
    on(add, 'click', function (e) { e.stopPropagation(); addToCart(c, null); });
    row.appendChild(pv);
    row.appendChild(add);
    return row;
  }

  /* Posters are rendered by the station on first ask (an ffmpeg each, two at
   * a time there) - so the pane asks lazily, two at a time too. */
  function queuePoster(thumb, posterUrl) {
    S.lib.posterQueue.push({thumb: thumb, src: posterUrl});
    later(pumpPosters, 0);                 /* after the row is on the page */
  }

  function pumpPosters() {
    if (!S) return;
    while (S.lib.posterBusy < 2 && S.lib.posterQueue.length) {
      var job = S.lib.posterQueue.shift();
      if (!job.thumb.isConnected) continue;
      S.lib.posterBusy += 1;
      (function (job) {
        var img = make('img', 'vx-poster');
        img.alt = '';
        img.decoding = 'async';
        var done = function () { if (S) { S.lib.posterBusy = Math.max(0, S.lib.posterBusy - 1); pumpPosters(); } };
        img.onload = function () { job.thumb.replaceChildren(img); done(); };
        img.onerror = done;
        img.src = url(job.src);
      })(job);
    }
  }

  /* ---- the preview: an inline sheet with its own ways out (BACK, Escape) */

  function openPreview(c, cartIndex) {
    if (!S) return;
    closePreview();
    var box = S.lib.previewBox;
    box.replaceChildren();
    var head = make('div', 'vx-preview-head');
    var back = btn('vx-preview-back', 'Back', 'c:caret--left', 'Back to the list');
    head.appendChild(back);
    var title = make('div', 'vx-preview-title');
    title.appendChild(make('b', '', c.name));
    title.appendChild(make('span', '', (c.video ? 'MP4' : 'Audio') + ' - ' + fmtTime(c.seconds || 0)
      + (c.user ? ' - a listener upload' : '') + (c.folder ? ' - ' + c.folder.split('/').pop() : '')));
    head.appendChild(title);
    box.appendChild(head);
    var start = c.start !== undefined && c.start !== null ? c.start : 0;
    var end = c.end !== undefined && c.end !== null ? c.end : null;
    var sc = new Scrubber({gap: CLIP_GAP_S, compact: true, shortPlay: !c.video,
      emptyText: 'Reading the clip...',
      onError: function () { say('This screen could not play that clip.', 'bad'); }});
    box.appendChild(sc.el);
    sc.setMedia(c.video ? 'video' : 'audio', url(c.url), {poster: c.poster_url ? url(c.poster_url) : '',
      spec: c.spec_url ? url(c.spec_url) : '', seconds: c.seconds, range: {start: start, end: end}});
    var acts = make('div', 'vx-preview-acts');
    var addRange = btn('vx-primary vx-add-range', cartIndex === null ? 'Put this range in the cart' : 'Keep this range',
      'c:add', 'The clip between IN and OUT goes in the bin cart');
    var addWhole = btn('vx-add-whole', 'Whole clip', 'c:box', 'The whole clip goes in the bin cart');
    acts.appendChild(addRange);
    if (cartIndex === null) acts.appendChild(addWhole);
    acts.appendChild(make('span', 'vx-hint', c.video ? 'Muted until you press Sound. Play runs the range on this screen only.'
      : 'Play runs up to ' + SHORT_PLAY_S + ' s of the range on this screen only.'));
    box.appendChild(acts);
    on(back, 'click', function (e) { e.stopPropagation(); closePreview(); });
    on(addRange, 'click', function (e) {
      e.stopPropagation();
      var r = sc.ready() ? rangeBody(sc.range, sc.dur) : {start: null, end: null};
      if (cartIndex === null) addToCart(c, r);
      else {
        S.cart[cartIndex] = Object.assign({}, S.cart[cartIndex], {start: r.start, end: r.end});
        saveCart();
        paintCart();
        say('Range kept for "' + c.name + '".');
      }
      closePreview();
    });
    on(addWhole, 'click', function (e) { e.stopPropagation(); addToCart(c, null); closePreview(); });
    S.lib.clipWrap.hidden = true;
    box.hidden = false;
    var close = function () { closePreview(); };
    var D = root.PineDismiss;
    S.lib.previewOff = [];
    if (D && typeof D.watch === 'function') {
      /* Escape closes the newest watched panel - this one; a tap inside the
       * pane (the cart, the folders) is spared, only a tap off it closes. */
      S.lib.previewOff.push(D.watch(box, close, [function () { return S && S.mount; }],
        function () { return !box.hidden; }));
    }
    if (D && typeof D.onBack === 'function') {
      /* registered after the shell's probe, so it wins the z tie: BACK closes
       * this sheet, then the extraction layer, then the popup */
      S.lib.previewOff.push(D.onBack(function () { return box.hidden ? null : {node: box, close: close}; }));
    }
    S.lib.previewItem = c;
    S.lib.scrub = sc;
  }

  function closePreview() {
    if (!S || !S.lib || !S.lib.previewItem) return;
    (S.lib.previewOff || []).forEach(function (off) { try { off(); } catch (err) { /* gone */ } });
    S.lib.previewOff = [];
    if (S.lib.scrub) S.lib.scrub.destroy();
    S.lib.scrub = null;
    S.lib.previewItem = null;
    S.lib.previewBox.hidden = true;
    S.lib.previewBox.replaceChildren();
    S.lib.clipWrap.hidden = false;
  }

  /* ---- the bin cart */

  function buildCart() {
    var col = make('div', 'vx-col vx-col-cart');
    var head = make('div', 'vx-col-head');
    head.appendChild(ico('c:box'));
    S.cartTitle = make('b', '', 'Bin cart');
    head.appendChild(S.cartTitle);
    var clear = btn('vx-cart-clear', 'Empty', 'c:trash-can', 'Take every clip out of the cart');
    head.appendChild(clear);
    col.appendChild(head);
    S.cartList = make('div', 'vx-cart-list');
    col.appendChild(S.cartList);
    S.cartTotals = make('div', 'vx-cart-totals');
    col.appendChild(S.cartTotals);
    S.cartAdvice = make('div', 'vx-advice-list');
    col.appendChild(S.cartAdvice);
    S.cartSpec = specifics('cart', {namePlaceholder: 'Name (the first clip\'s if empty)'});
    col.appendChild(S.cartSpec.el);
    ENGINES.forEach(function (k) { on(S.cartSpec.checks[k], 'change', paintCart); });
    S.cartGo = btn('vx-primary vx-cart-go', 'Make one signature', 'c:chemistry', 'Join the cart on the station and send it to the lab as one job');
    col.appendChild(S.cartGo);
    on(clear, 'click', function (e) { e.stopPropagation(); S.cart = []; saveCart(); paintCart(); });
    on(S.cartGo, 'click', function (e) { e.stopPropagation(); submitCart(); });
    return col;
  }

  function saveCart() { if (S) writeJson(storage(), CART_KEY, S.cart); paintTabs(); }

  function addToCart(c, range) {
    if (!S) return;
    var item = {id: c.id, name: c.name, video: !!c.video, user: !!c.user, seconds: Number(c.seconds || 0),
      url: c.url, poster_url: c.poster_url || '', spec_url: c.spec_url || '', folder: c.folder || '',
      start: range ? range.start : null, end: range ? range.end : null};
    var got = cartAdd(S.cart, item);
    if (!got.added) { say(got.why, 'bad'); return; }
    S.cart = got.cart;
    saveCart();
    paintCart();
    say('"' + c.name + '" is in the cart (' + S.cart.length + ').');
  }

  function paintCart() {
    if (!S || !S.cartList) return;
    var list = S.cartList;
    list.replaceChildren();
    setText(S.cartTitle, 'Bin cart (' + S.cart.length + '/' + CART_MAX + ')');
    if (!S.cart.length) {
      list.appendChild(make('div', 'vx-empty', 'Put clips here from any folder - several short ones make one signature.'));
    }
    S.cart.forEach(function (it, i) {
      var row = make('div', 'vx-cart-item' + (it.user ? ' vx-clip-user' : ''));
      var words = make('div', 'vx-cart-words');
      words.appendChild(make('b', '', it.name));
      var meta = make('span', 'vx-clip-meta');
      meta.appendChild(make('span', 'vx-tag ' + (it.video ? 'vx-tag-video' : 'vx-tag-audio'), it.video ? 'MP4' : 'AUDIO'));
      if (it.user) meta.appendChild(make('span', 'vx-tag vx-tag-user', 'USER'));
      var cut = it.start !== null || it.end !== null;
      meta.appendChild(make('span', '', cut ? fmtTime(it.start || 0) + '-' + fmtTime(it.end !== null ? it.end : it.seconds)
        + ' (' + fmtTime(itemSeconds(it)) + ')' : 'whole ' + fmtTime(it.seconds)));
      words.appendChild(meta);
      row.appendChild(words);
      var edit = btn('vx-cart-edit', '', 'c:cut', 'Set the in and out of "' + it.name + '"');
      var drop = btn('vx-cart-drop', '', 'c:trash-can', 'Take "' + it.name + '" out of the cart');
      on(edit, 'click', function (e) {
        e.stopPropagation();
        if (S.tab !== 'library' && S.tab !== 'uploads') showTab('library');
        openPreview(it, i);
      });
      on(drop, 'click', function (e) { e.stopPropagation(); S.cart.splice(i, 1); saveCart(); paintCart(); });
      row.appendChild(edit);
      row.appendChild(drop);
      list.appendChild(row);
    });
    var t = cartTotals(S.cart);
    setText(S.cartTotals, t.clips ? t.clips + ' clip(s) - ' + fmtTime(t.speech) + ' of audio, joins to ' + fmtTime(t.joined)
      + (t.clips > 1 ? ' with ' + GAP_S + ' s between' : '') + (t.user ? ' - includes listener uploads (credited)' : '') : '');
    adviceList(S.cartAdvice, t.clips ? lengthAdvice(t.speech, S.cartSpec.engines(), refs()) : []);
    S.cartGo.disabled = !t.clips || t.speech < LEAST_S;
  }

  function submitCart() {
    if (!S || !S.cart.length) return;
    var spec = S.cartSpec.read();
    if (!spec.engines.length) { say('Tick the engine the reference is cut for (XTTS, F5 or both).', 'bad'); return; }
    var t = cartTotals(S.cart);
    if (t.speech < LEAST_S) { say('The cart holds ' + fmtTime(t.speech) + ' - add clips or widen their ranges.', 'bad'); return; }
    var clips = S.cart.map(function (it) {
      return {id: it.id, start: it.start, end: it.end, seconds: it.seconds};
    });
    var cartCopy = S.cart.slice();
    var both = spec.engines.length === 2;
    var twin = '';
    S.cartGo.disabled = true;
    var chain = Promise.resolve();
    spec.engines.forEach(function (engine) {
      chain = chain.then(function () {
        var jobName = both && spec.name ? spec.name + ' (' + ENGINE_WORDS[engine] + ')' : spec.name;
        return request('POST', '/api/voice-actor/extract/clips', {clips: clips, name: jobName, who: spec.who,
          notes: spec.notes, engine: engine, speaker: spec.speaker, twin: twin}).then(function (got) {
          twin = got.vx;
          addJob({id: got.vx, kind: 'cart', name: got.name || jobName, engine: engine, twin: got.twin || '',
            label: cartCopy.length + ' clip(s)', clips: cartCopy.map(function (it) {
              return {id: it.id, name: it.name, video: it.video, user: it.user, seconds: itemSeconds(it)};
            }), user_submitted: !!got.user_submitted, credits: got.credits || [], stage: 'queued', station: true,
            preferred: spec.preferred, created: Date.now() / 1000});
        });
      });
    });
    chain.then(function () {
      say('The cart went as one job' + (both ? ' per engine' : '') + ' - joined on the station, then the lab.');
      S.cart = [];
      saveCart();
      paintCart();
      showTab('jobs');
    }, function (err) {
      if (absent(err)) say('The cart road is not on this station yet (tools/voice_actor_extract_patch.py) - nothing was sent.', 'bad');
      else say('The cart did not go: ' + String((err && err.message) || err), 'bad');
    }).then(function () { if (S) paintCart(); });
  }

  /* -------------------------------------------------- Jobs */

  function buildJobs() {
    var page = make('section', 'vx-page vx-page-jobs');
    var head = make('div', 'vx-jobs-head');
    head.appendChild(make('b', '', 'Signature jobs'));
    head.appendChild(make('span', 'vx-hint', 'Oldest first; new ones join at the bottom. A job lands in the library while this page is open - '
      + 'the harvest rides this poll - and picks up again whenever it is reopened.'));
    page.appendChild(head);
    S.jobList = make('div', 'vx-job-list');
    page.appendChild(S.jobList);
    return page;
  }

  function paintJobs() {
    if (!S || !S.jobList) return;
    var list = S.jobList;
    var have = {};
    var kids = list.querySelectorAll('.vx-job');
    for (var i = 0; i < kids.length; i += 1) have[kids[i].dataset.id] = kids[i];
    var ids = {};
    S.jobs.forEach(function (j) {
      ids[j.id] = true;
      if (!have[j.id]) list.appendChild(jobCard(j));
      paintJob(j);
    });
    Object.keys(have).forEach(function (id) { if (!ids[id]) have[id].remove(); });
    var empty = list.querySelector('.vx-empty');
    if (!S.jobs.length && !empty) list.appendChild(make('div', 'vx-empty', 'No signature jobs yet - a link or a cart starts one.'));
    if (S.jobs.length && empty) empty.remove();
  }

  function jobCard(j) {
    var card = make('div', 'vx-job');
    card.dataset.id = j.id;
    var top = make('div', 'vx-job-top');
    top.appendChild(ico(j.kind === 'cart' ? 'c:box' : 'c:link'));
    top.appendChild(make('b', 'vx-job-name', ''));
    top.appendChild(make('span', 'vx-tag vx-job-engine', ''));
    top.appendChild(make('span', 'vx-tag vx-tag-user vx-job-user', 'USER-SUBMITTED'));
    top.appendChild(make('span', 'vx-job-phase', ''));
    var retry = btn('vx-job-retry', 'Retry', 'c:renew', 'Run it again from the kept link or clips');
    var forget = btn('vx-job-forget', '', 'c:close--filled', 'Forget this job on this screen (the voice stays)');
    top.appendChild(retry);
    top.appendChild(forget);
    card.appendChild(top);
    card.appendChild(make('div', 'vx-job-label', ''));
    card.appendChild(make('div', 'vx-chain'));
    var bar = make('div', 'vx-progress');
    bar.appendChild(make('span', 'vx-progress-fill'));
    card.appendChild(bar);
    card.appendChild(make('div', 'vx-job-lines'));
    on(retry, 'click', function (e) { e.stopPropagation(); retryJob(j.id); });
    on(forget, 'click', function (e) {
      e.stopPropagation();
      S.jobs = S.jobs.filter(function (x) { return x.id !== j.id; });
      saveJobs();
      emit('extract-jobs', {jobs: S.jobs.map(eventOf)});
      paintJobs();
      paintTabs();
    });
    return card;
  }

  function paintJob(j) {
    if (!S || !S.jobList) return;
    var card = S.jobList.querySelector('.vx-job[data-id="' + String(j.id).replace(/"/g, '') + '"]');
    if (!card) return;
    var phase = jobPhase(j);
    card.className = 'vx-job vx-job-' + phase;
    setText(card.querySelector('.vx-job-name'), j.name || '(unnamed)');
    setText(card.querySelector('.vx-job-engine'), (ENGINE_WORDS[j.engine] || String(j.engine || '').toUpperCase()) + ' cut');
    card.querySelector('.vx-job-user').hidden = !j.user_submitted;
    var phaseWord = {queued: 'queued', station: 'on the station', running: 'in the lab', harvesting: 'landing in the library',
      done: 'in the library', error: 'failed'}[phase];
    setText(card.querySelector('.vx-job-phase'), phaseWord);
    card.querySelector('.vx-job-retry').hidden = !(phase === 'error' && !j.legacy);
    setText(card.querySelector('.vx-job-label'), (j.kind === 'cart' ? 'Cart: ' + (j.clips || []).map(function (c) { return c.name; }).join(', ')
      : j.label || '') + (j.range ? ' [' + j.range + ']' : ''));
    var chain = card.querySelector('.vx-chain');
    var states = stageStates(j);
    if (chain.children.length !== states.length) {
      chain.replaceChildren();
      states.forEach(function (s) {
        var pill = make('span', 'vx-stage', STAGE_WORDS[s.stage] || s.stage);
        pill.dataset.stage = s.stage;
        chain.appendChild(pill);
      });
    }
    states.forEach(function (s, i) {
      var pill = chain.children[i];
      var cls = 'vx-stage vx-stage-' + s.state;
      if (pill.className !== cls) pill.className = cls;
    });
    var pct = phase === 'done' ? 100 : Math.round(Number(j.progress || 0) * 100);
    card.querySelector('.vx-progress-fill').style.width = pct + '%';
    card.querySelector('.vx-progress').hidden = phase === 'done' || phase === 'error';
    var lines = [];
    if (phase === 'station' || phase === 'queued') lines.push(j.note || (j.stage === 'join' ? 'joining the cart on the station' : 'waiting for the lab'));
    else if (j.note) lines.push(j.note);
    if (j.joined) lines.push('Joined on the station: ' + j.joined.clips + ' clip(s), ' + fmtTime(j.joined.seconds) + ' in one file.');
    if (j.title) lines.push('Title: ' + j.title);
    if (j.diarize_note) lines.push('Diarize: ' + j.diarize_note);
    if (j.speakers && j.speakers.length) lines.push('Speakers: ' + j.speakers.join(', ') + (j.speaker_used ? ' - the reference is ' + j.speaker_used : ''));
    if (j.extra_speakers && j.extra_speakers.length) {
      lines.push('Also cloned (#457): ' + j.extra_speakers.map(function (x) { return x.speaker + ' (' + x.seconds + ' s)'; }).join(', '));
    }
    if (j.signature_note) lines.push(j.signature_note);
    if (j.harvest_error) lines.push('Harvest: ' + j.harvest_error);
    if (phase === 'done') {
      lines.push('In the library' + (j.voice_id ? ' as ' + j.voice_id : '') + (j.user_submitted ? ' - marked user-submitted, the sender credited' : '') + '.');
      if (j.prefSent === true) lines.push('Preferred engine recorded: ' + (ENGINE_WORDS[j.preferred] || j.preferred) + '.');
      else if (j.prefSent === 'absent') lines.push('The preferred engine could not be recorded - the actor store is not on this station.');
      else if (j.prefSent === 'failed') lines.push('The preferred engine was not recorded.');
    }
    if (phase === 'error') lines.push((j.error_kind ? j.error_kind + ': ' : '') + (j.error || 'failed'));
    if (j.pollFail) lines.push('The last poll failed: ' + j.pollFail);
    var box = card.querySelector('.vx-job-lines');
    var want = lines.join('\n');
    if (box.__text !== want) {
      box.__text = want;
      box.replaceChildren();
      lines.forEach(function (l) { box.appendChild(make('div', 'vx-job-line', l)); });
    }
  }

  function retryJob(id) {
    var j = findJob(id);
    if (!j) return;
    request('POST', '/api/voice-actor/extract/jobs/' + encodeURIComponent(id) + '/retry', {}).then(function () {
      updateJob(id, {stage: 'queued', station: true, error: '', error_kind: '', progress: 0, stages_done: [], joined: null});
      say('Running "' + (j.name || id) + '" again.');
    }, function (err) {
      say('Retry refused: ' + String((err && err.message) || err), 'bad');
    });
  }

  /* ================================================== mount / unmount */

  function mount(el, ctx) {
    if (S) unmount();
    S = {ctx: ctx, mount: el, offs: [], timers: [], jobs: readJobs(storage()),
      cart: readJson(storage(), CART_KEY, []) || [], health: null, tab: 'link'};
    if (!Array.isArray(S.cart)) S.cart = [];
    el.replaceChildren();
    build(el);
    paintCart();
    paintJobs();
    var tab = readJson(storage(), TAB_KEY, 'link');
    showTab(TABS.some(function (t) { return t.id === tab; }) ? tab : 'link');
    paintTabs();
    emit('extract-jobs', {jobs: S.jobs.map(eventOf)});
    var mine = S;
    request('GET', '/api/voice-actor/extract/health').then(function (h) {
      if (S !== mine) return;
      S.health = h || null;
      if (S.linkSpec) S.linkSpec.repaint();
      paintLinkAdvice();
      paintCart();
    }, function (err) {
      if (S !== mine) return;
      if (absent(err)) say('This station has the studio\'s link road but not the cart or the full clip browser yet (tools/voice_actor_extract_patch.py).');
    });
    mergeServerJobs();
    startPolling();
  }

  function unmount() {
    if (!S) return;
    var s = S;
    try { closePreview(); } catch (err) { /* going anyway */ }
    try { if (s.linkScrub) s.linkScrub.destroy(); } catch (err) { /* going anyway */ }
    s.timers.forEach(function (t) { root.clearTimeout(t); });
    s.offs.forEach(function (off) { try { off(); } catch (err) { /* gone */ } });
    try { tilesUnmount(); } catch (err) { /* the tiles' own mess */ }
    S = null;
  }

  /* The 3JS tile rail is a sibling's (SHELL_CONTRACT.md 9): handed the rail
   * when it has registered, left empty (and hidden by the shell) when not. */
  var tilesMounted = false;
  function tile(rail, ctx) {
    var T = root.PineVoiceActorTiles;
    if (!T || typeof T.mount !== 'function') return;
    try { T.mount(rail, ctx, api); tilesMounted = true; } catch (err) {
      if (root.console) root.console.error('[voice-actor-extract] tile rail failed:', err);
    }
  }

  function tilesUnmount() {
    var T = root.PineVoiceActorTiles;
    if (tilesMounted && T && typeof T.unmount === 'function') T.unmount();
    tilesMounted = false;
  }

  var api = {
    STAGES: STAGES.slice(), STAGE_WORDS: STAGE_WORDS, JOBS_KEY: JOBS_KEY, CART_KEY: CART_KEY,
    jobs: function () { return jobs().map(eventOf); },
    isMounted: function () { return !!S; },
    /* pure helpers, for the tests */
    fmtTime: fmtTime, parseTime: parseTime, clampRange: clampRange, dragHandle: dragHandle, timeAt: timeAt,
    rangeBody: rangeBody, lengthAdvice: lengthAdvice, itemSeconds: itemSeconds, cartTotals: cartTotals,
    cartAdd: cartAdd, isUserFolder: isUserFolder, jobChain: jobChain, jobPhase: jobPhase,
    stageStates: stageStates, eventOf: eventOf, foldStatus: foldStatus, readJobs: readJobs, writeJobs: writeJobs,
    CART_MAX: CART_MAX, GAP_S: GAP_S, REF_DEFAULT: REF_DEFAULT
  };
  root.PineVoiceActorExtract = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  /* One registration with the shell; if the shell loads later, wait for it. */
  var def = {mount: mount, unmount: unmount, tile: tile};
  function register() {
    var shell = root.PineVoiceActor;
    if (shell && typeof shell.registerExtraction === 'function') { shell.registerExtraction(def); return true; }
    return false;
  }
  if (typeof document !== 'undefined' && document && typeof document.createElement === 'function') {
    if (!register()) {
      var tries = 0;
      var wait = root.setInterval(function () {
        tries += 1;
        if (register() || tries > 40) root.clearInterval(wait);
      }, 250);
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
