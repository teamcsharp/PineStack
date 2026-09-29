/* VOICE ACTOR - THE ASSIMILATION TILES ON THE EXTRACTION STUDIO'S RAIL.
 *
 * "I want it to show a 3JS simulation of a Icosphere that is being
 *  disintegrated and assimilated into a tile off on the side... that shows
 *  the process of what's happening in the background on a technical level
 *  with the assimilation of the audio and turning it into the clip. So I
 *  want it to show a four-line output during the process that's scrolling
 *  through showing automatically everything that's happening. And then I
 *  want it to also be able to visually show the intricacies of the process
 *  in the form of a visual icon sphere being disintegrated and broken down
 *  and reassembled into a folder icon that becomes the file of the person
 *  who becomes an audio signature."
 *
 * ONE TILE PER SIGNATURE JOB on #vaTileRail (voice-actor.js's extraction
 * layer, SHELL_CONTRACT.md section 1). Each tile is a small three.js scene -
 * an icosphere on the left, a folder on the right - over a FOUR-LINE
 * technical readout that scrolls itself up as the job's lines arrive.
 *
 * DRIVEN BY THE REAL JOB, NEVER A CANNED LOOP. The scene's position is a
 * function of the job's own poll answer (GET /api/voicelab/jobs/{id}, the
 * voice-lab's STAGES at voice-lab/app.py:58):
 *   queued              the seed: a dim point
 *   download            the wireframe forms (edges drawn = download progress)
 *   extract_audio       the faces fill in and detach from the sphere
 *   transcribe, diarize the faces are consumed and stream to the folder
 *   analyze_pitch/cadence, build_signature   the last of the stream lands
 *   extract_reference, cleanup   the folder assembles out of the stream
 *   done                the folder closes and becomes the actor's card,
 *                       named, with the signature's measured dimensions
 *   error               everything freezes where it failed, in red
 * Inside a stage the lab either reports progress (download, transcribe,
 * diarize) and the scene follows it, or reports none (extract_audio, the
 * analyses, the reference cut); there the scene creeps toward at most half
 * of that stage's span and holds - motion that says "working", never a
 * claim that the next stage arrived. Only a real stage change moves past it.
 *
 * THE FOUR LINES are derived from what CHANGED between two poll answers:
 * the stage (with a gloss of what that stage runs, read from the voice-lab
 * source: yt-dlp, ffmpeg, faster-whisper, pyannote, the signature, the
 * loudnorm/afftdn reference cut), progress in tens, the lab's own notes,
 * each new whisper segment's words, the speakers, the signature's measured
 * numbers, the reference cut, the files, the harvest, the error. Nothing
 * is narrated that the answer does not carry.
 *
 * WHERE THE EVENTS COME FROM. The extraction pane (voice-actor-extract.js)
 * owns the polling and hands this file the rail:
 *   window.PineVoiceActorTiles.mount(rail, ctx, api) / .unmount()
 *     - called from its tile() / unmount() hooks; api.jobs() is the late read
 *   window 'pine-voice-actor:extract-job'   detail = one job (its eventOf())
 *   window 'pine-voice-actor:extract-jobs'  detail {jobs:[...]} (mount, add, forget)
 * A second door, for a raw poll answer (partial.transcript_segments and
 * partial.signature included - the richest readout):
 *   window 'pine-voice-actor:job'  detail {job_id, status, name}
 *   or PineVoiceActorViz.feed(job_id, status, {name})
 * Every road lands in the same feed(). As a fallback the tiles also mount
 * themselves on 'pine-voice-actor:extract-open' into #vaTileRail and stand
 * down on ':extract-close' - attach/detach are idempotent.
 *
 * CHEAP ON THE TABLET. ONE shared WebGLRenderer on a canvas of its own,
 * rendering each live tile's scene in turn and copying it into that tile's
 * 2D canvas; DPR 1 on the tablet (<= 2 on the desk), 30 fps on the tablet;
 * the loop stops whenever the rail is not on screen (IntersectionObserver),
 * the page is hidden, the layer closes, or nothing is moving. A finished
 * tile renders its last frame, keeps it as a picture and disposes its
 * scene. Closing the layer disposes the renderer. Every frame is guarded:
 * a tile whose scene throws falls back to a flat 2D card and the rail
 * never blanks (the kiosk swallows throws as "Script error.").
 *
 * THE FINISHED CARD persists (localStorage, try/catch) as the actor's card
 * until its dismiss button is pressed. Carbon icons via pineIcon only; no
 * emoji. No scroll is ever taken: the readout's four-line window is a
 * clipped, non-scrollable ticker, and new tiles are appended so the rail
 * the operator scrolled never moves.
 */
(function (root) {
  'use strict';

  /* ================================================== the pipeline's words */

  var STAGES = ['download', 'extract_audio', 'transcribe', 'diarize', 'analyze_pitch',
    'analyze_cadence', 'build_signature', 'extract_reference', 'cleanup'];

  /* each stage's span of the scene's 0..1 (queued sits at 0, done at 1) */
  var SPAN = {
    queued: [0, 0.02],
    join: [0, 0.02],           /* the station joins a multi-clip cart first */
    handoff: [0, 0.02],        /* ... and hands it to the lab */
    download: [0.02, 0.18],
    extract_audio: [0.18, 0.32],
    transcribe: [0.32, 0.55],
    diarize: [0.55, 0.66],
    analyze_pitch: [0.66, 0.72],
    analyze_cadence: [0.72, 0.76],
    build_signature: [0.76, 0.82],
    extract_reference: [0.82, 0.93],
    cleanup: [0.93, 0.985]
  };
  /* stages whose progress the lab reports as it goes (voice-lab/app.py:583, 976, 1134) */
  var REPORTS = {download: true, transcribe: true, diarize: true};
  var CREEP_MAX = 0.5;       /* of a silent stage's span, at most */
  var CREEP_S = 14;          /* time constant of that creep, seconds */

  /* what each stage runs - read from voice-lab/app.py, not invented */
  var GLOSS = {
    queued: 'queued in the lab',
    join: 'the station joins the clips',
    handoff: 'hand-off to the lab',
    download: 'yt-dlp bestaudio -> source',
    extract_audio: 'ffmpeg -vn mono 24 kHz -> work.wav',
    transcribe: 'faster-whisper, word timestamps',
    diarize: 'pyannote speaker-diarization-3.1',
    analyze_pitch: 'f0 + intensity track',
    analyze_cadence: 'pace, pauses, phrase rhythm',
    build_signature: 'signature.json',
    extract_reference: 'loudnorm + afftdn -> reference.wav 24 kHz',
    cleanup: 'audio.mp3 kept, work.wav removed',
    done: 'job done'
  };
  /* the header's one word per stage (short enough for the tablet tile) */
  var HEAD_WORD = {
    queued: 'queued', join: 'joining', handoff: 'hand-off', download: 'download', extract_audio: 'extract', transcribe: 'transcribe',
    diarize: 'diarize', analyze_pitch: 'pitch', analyze_cadence: 'cadence', build_signature: 'measuring',
    extract_reference: 'reference', cleanup: 'cleanup'
  };
  var TAG = {
    queued: 'queue', join: 'join', handoff: 'handoff', download: 'dl', extract_audio: 'ffmpeg', transcribe: 'whisper', diarize: 'diarize',
    analyze_pitch: 'pitch', analyze_cadence: 'cadence', build_signature: 'sig', extract_reference: 'ref',
    cleanup: 'clean', done: 'done', error: 'error'
  };
  /* the signature dimensions a card draws (voice-lab/app.py _build_signature) */
  var SIG_DIMS = [
    ['pace', 'mean', 'pace'], ['pitch', 'center', 'pitch'], ['pitch', 'mobility', 'mobility'],
    ['rhythm', 'regularity', 'rhythm'], ['pauses', 'density', 'pauses'], ['energy', 'center', 'energy'],
    ['articulation', 'precision', 'artic.'], ['expressiveness', 'overall', 'express.']
  ];

  var CARDS_KEY = 'pineVoiceActor.vizCards.v1';
  var DISMISSED_KEY = 'pineVoiceActor.vizDismissed.v1';
  var MAX_CARDS = 12;
  var MAX_LINES = 200;
  var LINE_H = 14;           /* px - must match .vaz-line in the CSS */

  var PAL = {
    night: '#10191f', rule: '#35414c', text: '#dbe7eb', muted: '#8fa0ad',
    cyan: '#65c7da', gold: '#e3be63', green: '#54d18b', red: '#ef6f5e'
  };

  /* ================================================== pure (and tested) */

  function clamp01(x) { x = Number(x); return x > 1 ? 1 : (x > 0 ? x : 0); }
  function smooth(x) { x = clamp01(x); return x * x * (3 - 2 * x); }

  function hms(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function hostOf(url) {
    var m = /^[a-z]+:\/\/([^/?#]+)/i.exec(String(url || ''));
    return m ? m[1].replace(/^www\./, '') : '';
  }

  function short(text, n) {
    text = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
    return text.length > n ? text.slice(0, n - 1) + '…' : text;
  }

  function stageOf(status) {
    var s = String((status && status.stage) || 'queued');
    if (s === 'done' || s === 'error' || SPAN[s]) return s;
    return 'queued';
  }

  /** The scene position this answer is worth. stageAge (seconds in this
   * stage, by the tile's own clock) only creeps a SILENT stage, and never
   * past CREEP_MAX of its span. */
  function targetOf(status, stageAge) {
    var st = stageOf(status);
    if (st === 'done') return 1;
    if (st === 'error') return -1;                       /* frozen where it was */
    if (st === 'queued' || st === 'join' || st === 'handoff') return 0;   /* the lab has not started */
    var span = SPAN[st];
    var p = clamp01(status && status.progress);
    if (!REPORTS[st]) {
      var creep = CREEP_MAX * (1 - Math.exp(-Math.max(0, Number(stageAge) || 0) / CREEP_S));
      p = Math.max(Math.min(p, 1), creep);
    }
    return span[0] + (span[1] - span[0]) * clamp01(p);
  }

  /** The scene's four channels at position t (0..1). */
  function visualOf(t) {
    t = clamp01(t);
    return {
      wire: clamp01((t - SPAN.download[0]) / (SPAN.download[1] - SPAN.download[0])),
      detach: clamp01((t - SPAN.extract_audio[0]) / (SPAN.extract_audio[1] - SPAN.extract_audio[0])),
      stream: clamp01((t - SPAN.transcribe[0]) / (SPAN.build_signature[1] - SPAN.transcribe[0])),
      assemble: clamp01((t - SPAN.extract_reference[0]) / (1 - SPAN.extract_reference[0]))
    };
  }

  function phaseOf(stage) {
    if (stage === 'done' || stage === 'error' || stage === 'queued') return stage;
    if (stage === 'join' || stage === 'handoff') return 'queued';
    if (stage === 'download') return 'wire';
    if (stage === 'extract_audio') return 'detach';
    if (stage === 'extract_reference' || stage === 'cleanup') return 'assemble';
    return 'stream';
  }

  function sigOf(status) {
    var sig = status && status.partial && status.partial.signature;
    return sig && typeof sig === 'object' ? sig : null;
  }

  /** The measured dimensions a card draws, from a (partial) signature. */
  function sigBars(sig) {
    if (!sig) return [];
    var out = [];
    SIG_DIMS.forEach(function (d) {
      var g = sig[d[0]];
      var v = g && typeof g === 'object' ? g[d[1]] : null;
      if (typeof v === 'number' && isFinite(v)) out.push({key: d[0] + '.' + d[1], label: d[2], v: clamp01(v)});
    });
    return out;
  }

  function num(v, digits) {
    var n = Number(v);
    if (!isFinite(n)) return '';
    return digits === 0 ? String(Math.round(n)) : n.toFixed(digits == null ? 2 : digits).replace(/^0\./, '.');
  }

  /** The technical lines one poll answer adds to the readout: only what
   * changed between prev and next, only fields the answer carries. */
  function deriveLines(prev, next, jobId) {
    var out = [];
    var p = prev || {};
    var s = next || {};
    var add = function (tag, text) { if (text) out.push({tag: tag, text: String(text)}); };
    var st = stageOf(s);
    var pst = prev ? stageOf(p) : '';
    if (!prev) {
      add('job', [jobId || s.id || '', s.mode ? 'mode ' + s.mode : '', s.engine ? 'engine ' + s.engine : '']
        .filter(Boolean).join('  '));
    }
    if (s.url && s.url !== p.url && hostOf(s.url)) add('src', hostOf(s.url));
    var clips = s.clips || [];
    if (clips.length && clips.length !== (p.clips || []).length) {
      add('clips', clips.length + ': ' + clips.slice(0, 3).map(function (c) { return c.name || c.id; }).join(', ')
        + (clips.length > 3 ? ', …' : ''));
    }
    if (s.title && s.title !== p.title) add('title', short(s.title, 80));
    if (st !== pst && st !== 'error') {
      add(TAG[st] || st, st === 'done' && !s.harvested ? 'job done - waiting for the harvest'
        : st === 'done' ? 'job done' : (GLOSS[st] || st));
    }
    /* progress, in tens, for the stages that report it - whisper's own words win */
    var segs = (s.partial && s.partial.transcript_segments) || null;
    var psegs = (p.partial && p.partial.transcript_segments) || null;
    var newSeg = segs && segs.length && (!psegs || segs.length !== psegs.length
      || (segs[segs.length - 1] || {}).end !== (psegs[psegs.length - 1] || {}).end);
    if (st === 'transcribe' && newSeg) {
      var last = segs[segs.length - 1] || {};
      add('whisper', hms(last.start) + '  ' + short(last.text || '(no words)', 90));
    } else if (REPORTS[st] && st === pst) {
      var b = Math.floor(clamp01(s.progress) * 10), pb = Math.floor(clamp01(p.progress) * 10);
      if (b !== pb) add(TAG[st], Math.round(clamp01(s.progress) * 100) + '%');
    }
    if (s.duration && s.duration !== p.duration) add('wav', hms(s.duration) + ' of audio, mono 24 kHz');
    if (s.language && s.language !== p.language) {
      add('lang', s.language + (s.language_probability != null ? '  p ' + num(s.language_probability, 2) : ''));
    }
    ['note', 'transcribe_note', 'diarize_note', 'signature_note', 'reference_note'].forEach(function (k) {
      if (s[k] && s[k] !== p[k]) add(k === 'note' ? 'lab' : k.replace('_note', ''), short(s[k], 120));
    });
    var spk = s.speakers || [];
    if (spk.length && JSON.stringify(spk) !== JSON.stringify(p.speakers || [])) {
      add('speakers', spk.length + ': ' + spk.slice(0, 4).join(', ') + (spk.length > 4 ? ', …' : ''));
    }
    var sig = sigOf(s), psig = sigOf(p);
    if (sig && !psig) {
      add('sig', ['pace ' + num((sig.pace || {}).mean), 'pitch ' + num((sig.pitch || {}).center),
        'energy ' + num((sig.energy || {}).center), 'expr ' + num((sig.expressiveness || {}).overall)].join('  '));
      var raw = sig.raw || {};
      if (raw.wpm != null || raw.f0_median_hz != null) {
        add('raw', [raw.wpm != null ? num(raw.wpm, 0) + ' wpm' : '',
          raw.f0_median_hz != null ? 'f0 ' + num(raw.f0_median_hz, 0) + ' Hz' : '',
          raw.pause_per_min != null ? num(raw.pause_per_min, 1) + ' pauses/min' : '',
          raw.words != null ? raw.words + ' words' : ''].filter(Boolean).join('  '));
      }
    }
    if (s.reference_target_s && s.reference_target_s !== p.reference_target_s) {
      add('ref', 'target ' + num(s.reference_target_s, 1) + ' s of clean speech');
    }
    if (s.reference_range && JSON.stringify(s.reference_range) !== JSON.stringify(p.reference_range)) {
      add('ref', [s.reference_pieces ? s.reference_pieces + ' pieces' : '',
        s.reference_speech_s ? num(s.reference_speech_s, 1) + ' s speech' : '',
        hms(s.reference_range[0]) + '-' + hms(s.reference_range[1])].filter(Boolean).join('  '));
    }
    var ex = s.extra_speakers || [];
    if (ex.length && JSON.stringify(ex) !== JSON.stringify(p.extra_speakers || [])) {
      add('extra', ex.length + ' more voice' + (ex.length === 1 ? '' : 's') + ': '
        + ex.slice(0, 3).map(function (e) { return e.speaker + ' ' + num(e.seconds, 1) + ' s'; }).join(', '));
    }
    if (s.speaker_used && s.speaker_used !== p.speaker_used) add('target', s.speaker_used);
    if (s.files && s.files.length && JSON.stringify(s.files) !== JSON.stringify(p.files || [])) {
      add('files', s.files.length + ': ' + s.files.join(' '));
    }
    if (s.harvested && !p.harvested) add('harvest', 'into the voice library' + (s.voice_id ? ' as ' + s.voice_id : ''));
    if (s.harvest_error && s.harvest_error !== p.harvest_error) add('harvest', short(s.harvest_error, 120));
    if (st === 'error' && (pst !== 'error' || s.error !== p.error)) {
      add('error', (s.error_kind ? s.error_kind + '  ' : '') + (s.failed_at ? 'at ' + s.failed_at + '  ' : '')
        + short(s.error || 'the job failed', 140));
    }
    return out;
  }

  /** The name a tile wears: the library's own name for the harvested voice,
   * else the name the pane submitted, else the source's title, else the id. */
  function nameOf(tile, actors) {
    var vid = tile.status && tile.status.voice_id;
    if (vid && actors && actors.length) {
      for (var i = 0; i < actors.length; i += 1) {
        if (actors[i] && actors[i].id === vid && actors[i].name) return String(actors[i].name);
      }
    }
    if (tile.name) return String(tile.name);
    if (tile.title) return String(tile.title);
    return String(tile.id || 'voice');
  }

  /* ================================================== small DOM helpers */

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(name, label) {
    try { if (typeof root.pineIcon === 'function') return root.pineIcon(name, label) || ''; } catch (err) { /* text fallback */ }
    return '';
  }

  function iconInto(node, name, fallback) {
    var m = icon(name);
    if (m) { node.innerHTML = m; node.removeAttribute('data-fallback'); }
    else { node.textContent = fallback || ''; node.setAttribute('data-fallback', '1'); }
  }

  function storage() {
    try { return root.localStorage || null; } catch (err) { return null; }
  }

  function readJson(key, dflt) {
    try {
      var st = storage();
      var raw = st ? st.getItem(key) : null;
      var v = raw ? JSON.parse(raw) : null;
      return v == null ? dflt : v;
    } catch (err) { return dflt; }
  }

  function writeJson(key, value) {
    try { var st = storage(); if (st) st.setItem(key, JSON.stringify(value)); } catch (err) { /* private window */ }
  }

  function emit(name, detail) {
    try { root.dispatchEvent(new root.CustomEvent('pine-voice-actor:' + name, {detail: detail || {}})); }
    catch (err) { /* old WebView */ }
  }

  function isTablet() {
    try {
      if (root.__pineViewsBooted) return true;
      return !!(root.matchMedia && root.matchMedia('(pointer: coarse)').matches);
    } catch (err) { return false; }
  }

  function reducedMotion() {
    try { return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    catch (err) { return false; }
  }

  function actorsNow() {
    try {
      if (R.ctx && typeof R.ctx.actors === 'function') return R.ctx.actors() || [];
      if (root.PineVoiceActor && typeof root.PineVoiceActor.actors === 'function') return root.PineVoiceActor.actors() || [];
    } catch (err) { /* no store yet */ }
    return [];
  }

  function hashSeed(str) {
    var h = 2166136261;
    str = String(str || '');
    for (var i = 0; i < str.length; i += 1) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  function rng(seed) {
    var s = seed >>> 0 || 1;
    return function () {
      s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0;
      return (s >>> 0) / 4294967296;
    };
  }

  /* ================================================== the model */

  var tiles = {};             /* job id -> tile */
  var order = [];             /* job ids in arrival order */
  var dismissed = {};         /* job id -> true (loaded lazily) */
  var loaded = false;

  function loadStore() {
    if (loaded) return;
    loaded = true;
    var d = readJson(DISMISSED_KEY, []);
    if (Array.isArray(d)) d.forEach(function (id) { dismissed[id] = true; });
    var cards = readJson(CARDS_KEY, []);
    if (!Array.isArray(cards)) return;
    cards.forEach(function (c) {
      if (!c || !c.id || tiles[c.id] || dismissed[c.id]) return;
      var t = newTile(c.id);
      t.name = c.name || '';
      t.status = {stage: c.error ? 'error' : 'done', progress: 1, harvested: !!c.harvested, voice_id: c.voice_id || '',
        engine: c.engine || '', error: c.error || '', error_kind: c.error_kind || '',
        partial: c.sig ? {signature: c.sig} : {}};
      t.stage = t.status.stage;
      t.t = c.error ? clamp01(c.t) : 1;
      t.target = t.t;
      t.frozenT = t.t;
      t.restored = true;
      t.lines = (c.lines || []).slice(-4);
      t.finishedAt = c.at || 0;
    });
  }

  function saveCards() {
    var cards = [];
    order.forEach(function (id) {
      var t = tiles[id];
      if (!t || !(t.stage === 'done' || t.stage === 'error')) return;
      var s = t.status || {};
      cards.push({id: id, name: nameOf(t, actorsNow()), voice_id: s.voice_id || '', engine: s.engine || '',
        harvested: !!s.harvested, error: t.stage === 'error' ? String(s.error || 'failed') : '',
        error_kind: s.error_kind || '', t: t.t, sig: sigOf(s) ? stripSig(sigOf(s)) : null,
        lines: t.lines.slice(-4), at: t.finishedAt || Date.now()});
    });
    writeJson(CARDS_KEY, cards.slice(-MAX_CARDS));
  }

  function stripSig(sig) {
    var out = {};
    SIG_DIMS.forEach(function (d) {
      if (sig[d[0]] && typeof sig[d[0]] === 'object') {
        out[d[0]] = out[d[0]] || {};
        out[d[0]][d[1]] = sig[d[0]][d[1]];
      }
    });
    return out;
  }

  function newTile(id) {
    var t = {
      id: id, name: '', title: '', status: null, stage: 'queued', lines: [],
      clock: 0, stageClock: 0, t: 0, target: 0, frozenT: 0,
      doneClock: -1, finishedAt: 0, restored: false,
      dom: null, scene: null, snap: null, fallback: false, fallbackWhy: '',
      isStatic: false, sceneInfo: null, seed: hashSeed(id)
    };
    tiles[id] = t;
    order.push(id);
    return t;
  }

  /** THE ONE DOOR every real progress answer comes through. */
  function feed(jobId, status, meta) {
    jobId = String(jobId || (status && (status.id || status.job_id)) || '');
    if (!jobId || !status || typeof status !== 'object') return null;
    loadStore();
    if (dismissed[jobId]) return null;
    var t = tiles[jobId] || newTile(jobId);
    if (meta && meta.name) t.name = String(meta.name);
    if (status.title) t.title = String(status.title);
    var prev = t.status;
    /* the harvested answer is lean (the lab job is gone): keep what we knew */
    var merged = status;
    if (prev && status.harvested && !status.partial) {
      merged = {};
      Object.keys(prev).forEach(function (k) { merged[k] = prev[k]; });
      Object.keys(status).forEach(function (k) { merged[k] = status[k]; });
    }
    var lines = deriveLines(prev, merged, jobId);
    var st = stageOf(merged);
    if (st !== t.stage) {
      /* freeze where the job REPORTED it was, not where the easing lagged */
      if (t.stage !== 'error' && st === 'error') { t.frozenT = Math.max(t.t, t.target); t.t = t.frozenT; }
      t.stage = st;
      t.stageClock = t.clock;
      if (st === 'done' || st === 'error') t.finishedAt = Date.now();
      if (st === 'done') t.doneClock = t.clock;
    }
    t.status = merged;
    t.isStatic = false;          /* anything new re-renders the tile */
    t.snap = st === 'done' || st === 'error' ? t.snap : null;
    retarget(t);
    pushLines(t, lines);
    if (st === 'done' || st === 'error') saveCards();
    if (t.dom) paintTile(t);
    else if (R.rail) mountTile(t);
    wake('feed');
    return tileDebug(t);
  }

  function retarget(t) {
    var tg = targetOf(t.status || {}, t.clock - t.stageClock);
    if (tg < 0) tg = t.frozenT;                         /* error: hold still */
    t.target = Math.max(t.target, tg);                  /* the scene never walks back */
  }

  /** Advance one tile's model by dt seconds (the loop calls this; the tests
   * call it through advance() so no wall clock decides a check). */
  function step(t, dt) {
    t.clock += dt;
    if (t.stage === 'error') { t.t = t.frozenT; return; }
    retarget(t);
    var k = 1 - Math.exp(-dt * 2.2);
    t.t += (t.target - t.t) * k;
    if (t.target - t.t < 0.0005) t.t = t.target;
  }

  function settled(t) {
    if (t.stage === 'error') return true;
    if (t.stage !== 'done') return false;
    return t.t >= 0.9995 && t.doneClock >= 0 && (t.clock - t.doneClock) > 1.4;
  }

  function pushLines(t, lines) {
    if (!lines.length) return;
    var clock = new Date();
    var stamp = [clock.getHours(), clock.getMinutes(), clock.getSeconds()]
      .map(function (n) { return (n < 10 ? '0' : '') + n; }).join(':');
    lines.forEach(function (l) { t.lines.push({tag: l.tag, text: l.text, at: stamp}); });
    if (t.lines.length > MAX_LINES) t.lines.splice(0, t.lines.length - MAX_LINES);
    if (t.dom) paintReadout(t, lines.length);
  }

  /* ================================================== the tile's DOM */

  function mountTile(t) {
    if (!R.rail || t.dom) return;
    var el = make('div', 'vaz-tile');
    el.setAttribute('data-job', t.id);
    el.setAttribute('role', 'group');
    var head = make('div', 'vaz-head');
    var ico = make('span', 'vaz-ico');
    ico.setAttribute('aria-hidden', 'true');
    var name = make('b', 'vaz-name');
    var stage = make('span', 'vaz-stage');
    var dismiss = make('button', 'vaz-dismiss');
    dismiss.type = 'button';
    dismiss.title = 'Dismiss this card';
    dismiss.setAttribute('aria-label', 'Dismiss this card');
    iconInto(dismiss, 'c:close--filled', 'x');
    dismiss.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      dismissTile(t.id);
    });
    head.appendChild(ico);
    head.appendChild(name);
    head.appendChild(stage);
    head.appendChild(dismiss);
    var view = make('div', 'vaz-view');
    var canvas = make('canvas', 'vaz-canvas');
    canvas.setAttribute('aria-hidden', 'true');
    var meter = make('div', 'vaz-meter');
    var bar = make('i');
    meter.appendChild(bar);
    var card = make('div', 'vaz-card');
    card.hidden = true;
    view.appendChild(canvas);
    view.appendChild(card);
    view.appendChild(meter);
    var readout = make('div', 'vaz-readout');
    readout.setAttribute('role', 'log');
    readout.setAttribute('aria-live', 'off');
    readout.setAttribute('aria-label', 'What the job is doing');
    var win = make('div', 'vaz-window');
    var list = make('div', 'vaz-lines');
    win.appendChild(list);
    readout.appendChild(win);
    el.appendChild(head);
    el.appendChild(view);
    el.appendChild(readout);
    t.dom = {el: el, ico: ico, name: name, stage: stage, dismiss: dismiss, canvas: canvas,
      ctx2d: null, bar: bar, card: card, list: list, readout: readout, win: win, cardSig: ''};
    R.rail.appendChild(el);                 /* appended: a scrolled rail never moves */
    paintTile(t);
    paintReadout(t, 0);
    if (R.failed) toFallback(t, R.failed);
    else if (t.snap) blit(t, t.snap);
  }

  function unmountTile(t) {
    if (t.dom && t.dom.el.parentNode) t.dom.el.parentNode.removeChild(t.dom.el);
    t.dom = null;
  }

  function paintTile(t) {
    var d = t.dom;
    if (!d) return;
    var st = t.stage;
    var name = nameOf(t, actorsNow());
    d.el.setAttribute('data-phase', phaseOf(st));
    d.el.setAttribute('data-stage', st);
    d.el.setAttribute('aria-label', name + ' - ' + (st === 'done' ? 'signature ready' : st));
    if (d.name.textContent !== name) d.name.textContent = name;
    d.name.title = name;
    var word = st === 'done' ? (t.status && t.status.harvested ? 'signature' : 'harvesting')
      : st === 'error' ? 'failed' : (HEAD_WORD[st] || st);
    if (d.stage.textContent !== word) d.stage.textContent = word;
    var icoName = st === 'done' ? 'c:folder' : st === 'error' ? 'c:warning--alt' : 'c:waveform';
    if (d.ico.getAttribute('data-icon') !== icoName || d.ico.getAttribute('data-fallback')) {
      iconInto(d.ico, icoName, '');
      d.ico.setAttribute('data-icon', icoName);
    }
    d.dismiss.hidden = !(st === 'done' || st === 'error');
    d.bar.style.width = Math.round(clamp01(st === 'error' ? t.frozenT : t.target) * 100) + '%';
    paintCard(t);
    if (t.fallback) drawFallback(t);
  }

  function paintCard(t) {
    var d = t.dom;
    var done = t.stage === 'done';
    var bars = done ? sigBars(sigOf(t.status)) : [];
    var name = nameOf(t, actorsNow());
    var engine = String((t.status && t.status.engine) || '').toUpperCase();
    var key = [done, name, engine, JSON.stringify(bars), t.status && t.status.harvested].join('|');
    if (d.cardSig === key) return;
    d.cardSig = key;
    d.card.hidden = !done;
    d.card.replaceChildren();
    if (!done) return;
    var who = make('div', 'vaz-card-who');
    var ic = make('span', 'vaz-ico');
    iconInto(ic, 'c:user--avatar', '');
    who.appendChild(ic);
    who.appendChild(make('b', 'vaz-card-name', name));
    if (engine) who.appendChild(make('span', 'vaz-card-engine', engine));
    d.card.appendChild(who);
    if (bars.length) {
      var sig = make('div', 'vaz-sig');
      sig.setAttribute('aria-label', 'Audio signature: ' + bars.map(function (b) {
        return b.label + ' ' + b.v.toFixed(2); }).join(', '));
      bars.forEach(function (b) {
        var col = make('span', 'vaz-sig-bar');
        col.title = b.key + ' ' + b.v.toFixed(3);
        var fill = make('i');
        fill.style.height = Math.max(6, Math.round(b.v * 100)) + '%';
        col.appendChild(fill);
        sig.appendChild(col);
      });
      d.card.appendChild(sig);
    } else {
      /* no numbers reached this tile (the pane's event carries no partial):
       * say only what is known, never that none were measured */
      d.card.appendChild(make('span', 'vaz-card-note', t.status && t.status.harvested
        ? 'in the voice library' : 'waiting for the harvest'));
    }
  }

  /** The four-line window: the newest line at the bottom; a batch of new
   * lines slides the window up by that many lines. It is clipped and not
   * scrollable, so it can never take a scroll from anyone. */
  function paintReadout(t, added) {
    var d = t.dom;
    if (!d) return;
    var shown = t.lines.slice(-(4 + Math.min(4, added || 0)));
    d.list.replaceChildren();
    shown.forEach(function (l) {
      var row = make('div', 'vaz-line' + (l.tag === 'error' ? ' vaz-line-bad' : ''));
      row.title = l.at + '  ' + l.tag + '  ' + l.text;
      row.appendChild(make('span', 'vaz-line-tag', l.tag));
      row.appendChild(make('span', 'vaz-line-text', l.text));
      d.list.appendChild(row);
    });
    if (!added || reducedMotion()) { d.list.style.transition = 'none'; d.list.style.transform = 'translateY(0)'; return; }
    d.list.style.transition = 'none';
    d.list.style.transform = 'translateY(' + (Math.min(4, added) * LINE_H) + 'px)';
    void d.list.offsetHeight;                           /* commit the start position */
    d.list.style.transition = '';
    d.list.style.transform = 'translateY(0)';
  }

  function dismissTile(id) {
    var t = tiles[id];
    if (!t) return;
    disposeScene(t);
    unmountTile(t);
    delete tiles[id];
    order = order.filter(function (x) { return x !== id; });
    dismissed[id] = true;
    writeJson(DISMISSED_KEY, Object.keys(dismissed).slice(-80));
    saveCards();
    emit('viz-dismiss', {job_id: id});
  }

  /* ================================================== three.js, shared */

  var R = {
    rail: null, ctx: null, io: null, onScreen: true,
    THREE: null, loading: null, failed: '',
    canvas: null, renderer: null, w: 0, h: 0, dpr: 1,
    raf: 0, frames: 0, paused: true, reason: 'not attached', last: 0, acc: 0,
    tablet: false
  };

  function threeUrl() {
    try { if (typeof root.pineThreeUrl === 'function') return root.pineThreeUrl(); } catch (err) { /* fall through */ }
    try {
      if (R.ctx && typeof R.ctx.stationUrl === 'function') return R.ctx.stationUrl('/vendor/three.min.js');
      if (root.PineVoiceActor && typeof root.PineVoiceActor.stationUrl === 'function') {
        return root.PineVoiceActor.stationUrl('/vendor/three.min.js');
      }
    } catch (err) { /* fall through */ }
    return '/vendor/three.min.js';
  }

  function loadThree() {
    if (root.THREE && root.THREE.WebGLRenderer) { R.THREE = root.THREE; return Promise.resolve(R.THREE); }
    if (R.loading) return R.loading;
    var src = threeUrl();
    R.loading = new Promise(function (res, rej) {
      var sc = document.createElement('script');
      sc.src = src;
      sc.async = true;
      sc.onload = function () {
        if (root.THREE && root.THREE.WebGLRenderer) { R.THREE = root.THREE; res(R.THREE); }
        else { R.loading = null; rej(new Error('three.js loaded without THREE from ' + src)); }
      };
      sc.onerror = function () { R.loading = null; rej(new Error('three.js did not load from ' + src)); };
      document.head.appendChild(sc);
    });
    return R.loading;
  }

  function ensureRenderer(w, h) {
    if (R.failed) return null;
    var THREE = R.THREE;
    if (!THREE) return null;
    if (!R.renderer) {
      if (root.__pineVizNoWebGL) { R.failed = 'WebGL disabled for this page'; return null; }
      try {
        R.canvas = document.createElement('canvas');
        R.canvas.addEventListener('webglcontextlost', function (e) {
          e.preventDefault();
          /* our own dispose lets contexts go too (forceContextLoss): only a
           * loss on the canvas still in use is the GPU's doing */
          if (e.target !== R.canvas || !R.renderer) return;
          failAll('the GPU dropped the WebGL context');
        });
        R.renderer = new THREE.WebGLRenderer({canvas: R.canvas, antialias: !R.tablet, alpha: true,
          preserveDrawingBuffer: true, powerPreference: 'low-power'});
        R.dpr = R.tablet ? 1 : Math.min(2, root.devicePixelRatio || 1);
        R.renderer.setPixelRatio(R.dpr);
        R.renderer.setClearColor(0x000000, 0);
        R.w = 0; R.h = 0;
      } catch (err) {
        R.renderer = null;
        R.failed = 'no WebGL here - ' + (err && err.message ? err.message : err);
        return null;
      }
    }
    if (w !== R.w || h !== R.h) { R.renderer.setSize(w, h, false); R.w = w; R.h = h; }
    return R.renderer;
  }

  function disposeRenderer() {
    if (!R.renderer) return;
    var r = R.renderer;
    R.renderer = null;                  /* first: the loss event below is ours */
    R.canvas = null;
    R.w = 0; R.h = 0;
    try { r.dispose(); } catch (err) { /* already gone */ }
    try { if (r.forceContextLoss) r.forceContextLoss(); } catch (err) { /* fine */ }
  }

  function failAll(why) {
    R.failed = why;
    order.forEach(function (id) { var t = tiles[id]; if (t) toFallback(t, why); });
    disposeRenderer();
  }

  function toFallback(t, why) {
    disposeScene(t);
    t.fallback = true;
    t.fallbackWhy = String(why || '');
    if (t.dom) { t.dom.el.setAttribute('data-flat', '1'); drawFallback(t); }
  }

  /* ------------------------------------------------ one tile's scene */

  function buildScene(THREE, t) {
    var tablet = R.tablet;
    var rand = rng(t.seed);
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(36, 2.2, 0.1, 50);
    camera.position.set(0.25, 0.3, 5.4);
    camera.lookAt(0.25, 0, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 0.65));
    var sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(2, 3, 4);
    scene.add(sun);
    var disposables = [];
    var keep = function (x) { disposables.push(x); return x; };

    /* ---- the icosphere: wire, faces */
    var sphere = new THREE.Group();
    sphere.position.set(-1.15, 0.02, 0);
    scene.add(sphere);
    var R0 = 0.9;
    var ico = keep(new THREE.IcosahedronGeometry(R0, tablet ? 1 : 2));
    var src = ico.getAttribute('position').array;
    var nFaces = src.length / 9;
    var wireGeo = keep(new THREE.WireframeGeometry(ico));
    var wireMat = keep(new THREE.LineBasicMaterial({color: new THREE.Color(PAL.cyan), transparent: true, opacity: 0.9}));
    var wire = new THREE.LineSegments(wireGeo, wireMat);
    var wireCount = wireGeo.getAttribute('position').count;
    sphere.add(wire);

    var cen = new Float32Array(nFaces * 3);
    var loc = new Float32Array(nFaces * 9);          /* each vertex relative to its centroid */
    var nrm = new Float32Array(nFaces * 9);
    var order2 = [];
    for (var f = 0; f < nFaces; f += 1) {
      var cx = 0, cy = 0, cz = 0;
      for (var v = 0; v < 3; v += 1) { cx += src[f * 9 + v * 3]; cy += src[f * 9 + v * 3 + 1]; cz += src[f * 9 + v * 3 + 2]; }
      cx /= 3; cy /= 3; cz /= 3;
      cen[f * 3] = cx; cen[f * 3 + 1] = cy; cen[f * 3 + 2] = cz;
      var len = Math.sqrt(cx * cx + cy * cy + cz * cz) || 1;
      for (v = 0; v < 3; v += 1) {
        loc[f * 9 + v * 3] = src[f * 9 + v * 3] - cx;
        loc[f * 9 + v * 3 + 1] = src[f * 9 + v * 3 + 1] - cy;
        loc[f * 9 + v * 3 + 2] = src[f * 9 + v * 3 + 2] - cz;
        nrm[f * 9 + v * 3] = cx / len; nrm[f * 9 + v * 3 + 1] = cy / len; nrm[f * 9 + v * 3 + 2] = cz / len;
      }
      /* the side facing the folder goes first, with a seeded shuffle */
      order2.push({f: f, k: (cx / R0) * 0.7 + rand() * 0.6});
    }
    order2.sort(function (a, b) { return b.k - a.k; });
    var rank = new Float32Array(nFaces);
    order2.forEach(function (o, i) { rank[o.f] = i / Math.max(1, nFaces - 1); });
    var facePos = new Float32Array(nFaces * 9);
    var faceGeo = keep(new THREE.BufferGeometry());
    var posAttr = new THREE.BufferAttribute(facePos, 3);
    posAttr.setUsage(THREE.DynamicDrawUsage);
    faceGeo.setAttribute('position', posAttr);
    faceGeo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    var faceMat = keep(new THREE.MeshLambertMaterial({color: new THREE.Color('#3f97aa'), emissive: new THREE.Color('#0c2f38'),
      transparent: true, opacity: 0, side: THREE.DoubleSide, flatShading: true}));
    var faces = new THREE.Mesh(faceGeo, faceMat);
    faces.frustumCulled = false;
    sphere.add(faces);
    var seedDot = new THREE.Mesh(keep(new THREE.SphereGeometry(0.06, 8, 6)),
      keep(new THREE.MeshBasicMaterial({color: new THREE.Color(PAL.cyan), transparent: true, opacity: 0.9})));
    sphere.add(seedDot);

    /* ---- the folder, off to the side */
    var folder = new THREE.Group();
    folder.position.set(1.62, -0.12, 0);
    scene.add(folder);
    var FW = 1.2, FH = 0.84;
    var shape = new THREE.Shape();
    shape.moveTo(-FW / 2, -FH / 2);
    shape.lineTo(FW / 2, -FH / 2);
    shape.lineTo(FW / 2, FH / 2);
    shape.lineTo(-FW / 2 + 0.5, FH / 2);
    shape.lineTo(-FW / 2 + 0.42, FH / 2 + 0.13);
    shape.lineTo(-FW / 2, FH / 2 + 0.13);
    shape.lineTo(-FW / 2, -FH / 2);
    var outlinePts = shape.getPoints();
    var outlineGeo = keep(new THREE.BufferGeometry().setFromPoints(outlinePts));
    var outlineMat = keep(new THREE.LineDashedMaterial({color: new THREE.Color(PAL.gold), dashSize: 0.07, gapSize: 0.05,
      transparent: true, opacity: 0.55}));
    var outline = new THREE.Line(outlineGeo, outlineMat);
    outline.computeLineDistances();
    folder.add(outline);
    var backMat = keep(new THREE.MeshLambertMaterial({color: new THREE.Color('#9c7a2e'), emissive: new THREE.Color('#2a1f08'),
      transparent: true, opacity: 0, side: THREE.DoubleSide}));
    var back = new THREE.Mesh(keep(new THREE.ShapeGeometry(shape)), backMat);
    back.position.z = -0.02;
    folder.add(back);
    var fillMat = keep(new THREE.MeshBasicMaterial({color: new THREE.Color(PAL.cyan), transparent: true, opacity: 0.4}));
    var fillGeo = keep(new THREE.PlaneGeometry(FW - 0.14, FH - 0.12));
    fillGeo.translate(0, (FH - 0.12) / 2, 0);
    var fill = new THREE.Mesh(fillGeo, fillMat);
    fill.position.set(0, -FH / 2 + 0.06, 0.0);
    fill.scale.y = 0.0001;
    folder.add(fill);
    var frontPivot = new THREE.Group();
    frontPivot.position.set(0, -FH / 2, 0.03);
    folder.add(frontPivot);
    var frontGeo = keep(new THREE.PlaneGeometry(FW, FH - 0.1));
    frontGeo.translate(0, (FH - 0.1) / 2, 0);
    var frontMat = keep(new THREE.MeshLambertMaterial({color: new THREE.Color(PAL.gold), emissive: new THREE.Color('#3a2c0a'),
      transparent: true, opacity: 0, side: THREE.DoubleSide}));
    var front = new THREE.Mesh(frontGeo, frontMat);
    frontPivot.add(front);
    /* the name, on the folder's face once it has assembled */
    var labelCanvas = document.createElement('canvas');
    labelCanvas.width = 256; labelCanvas.height = 64;
    var labelTex = keep(new THREE.CanvasTexture(labelCanvas));
    var labelMat = keep(new THREE.MeshBasicMaterial({map: labelTex, transparent: true, opacity: 0, depthWrite: false}));
    var label = new THREE.Mesh(keep(new THREE.PlaneGeometry(FW * 0.9, FW * 0.9 / 4)), labelMat);
    label.position.set(0, (FH - 0.1) * 0.62, 0.004);
    front.add(label);
    var labelText = '';
    /* the signature trace across the folder's face */
    var TRACE_N = 24;
    var tracePos = new Float32Array(TRACE_N * 3);
    var traceGeo = keep(new THREE.BufferGeometry());
    traceGeo.setAttribute('position', new THREE.BufferAttribute(tracePos, 3));
    var traceMat = keep(new THREE.LineBasicMaterial({color: new THREE.Color('#1c2a30'), transparent: true, opacity: 0}));
    var trace = new THREE.Line(traceGeo, traceMat);
    trace.position.set(0, (FH - 0.1) * 0.22, 0.005);
    front.add(trace);
    var traceSig = '';
    /* where the pieces fly in from */
    var backFrom = new THREE.Vector3(-0.9 - rand() * 0.4, 0.6 + rand() * 0.4, 0.4);
    var frontFrom = new THREE.Vector3(-1.2 - rand() * 0.4, -0.5 - rand() * 0.3, 0.6);

    /* ---- the stream */
    var NP = tablet ? 140 : 320;
    var pPos = new Float32Array(NP * 3);
    var pCol = new Float32Array(NP * 3);
    var pFace = new Uint16Array(NP), pPhase = new Float32Array(NP), pSpeed = new Float32Array(NP),
      pLift = new Float32Array(NP), pEnd = new Float32Array(NP * 2);
    for (var i = 0; i < NP; i += 1) {
      pFace[i] = Math.floor(rand() * nFaces);
      pPhase[i] = rand();
      pSpeed[i] = 0.35 + rand() * 0.45;
      pLift[i] = 0.4 + rand() * 0.9;
      pEnd[i * 2] = (rand() - 0.5) * (FW - 0.3);
      pEnd[i * 2 + 1] = (rand() - 0.5) * (FH - 0.3);
    }
    var pGeo = keep(new THREE.BufferGeometry());
    var pPosAttr = new THREE.BufferAttribute(pPos, 3);
    pPosAttr.setUsage(THREE.DynamicDrawUsage);
    pGeo.setAttribute('position', pPosAttr);
    var pColAttr = new THREE.BufferAttribute(pCol, 3);
    pColAttr.setUsage(THREE.DynamicDrawUsage);
    pGeo.setAttribute('color', pColAttr);
    var pMat = keep(new THREE.PointsMaterial({size: tablet ? 0.065 : 0.05, vertexColors: true, transparent: true,
      opacity: 0.95, depthWrite: false}));
    var points = new THREE.Points(pGeo, pMat);
    points.frustumCulled = false;
    scene.add(points);
    var cA = new THREE.Color(PAL.cyan), cB = new THREE.Color(PAL.gold), cT = new THREE.Color();
    var red = new THREE.Color(PAL.red);
    var faceCol = new THREE.Color('#3f97aa'), wireCol = new THREE.Color(PAL.cyan);
    var sphereWorld = sphere.position, folderWorld = folder.position;
    var time = 0;

    function drawLabel(text) {
      var g = labelCanvas.getContext('2d');
      g.clearRect(0, 0, 256, 64);
      g.fillStyle = '#1b1406';
      g.font = '700 30px Inter, "Segoe UI", sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      var s = String(text || '');
      while (s.length > 3 && g.measureText(s).width > 236) s = s.slice(0, -2);
      if (s !== String(text || '')) s = s.replace(/.$/, '…');
      g.fillText(s, 128, 34);
      labelTex.needsUpdate = true;
    }

    function drawTrace(bars) {
      for (var j = 0; j < TRACE_N; j += 1) {
        var x = -FW * 0.4 + (FW * 0.8) * j / (TRACE_N - 1);
        var y = 0;
        if (bars.length) {
          var b = bars[j % bars.length].v;
          y = (b - 0.5) * 0.18 * (j % 2 ? 1 : -1);
        }
        tracePos[j * 3] = x; tracePos[j * 3 + 1] = y; tracePos[j * 3 + 2] = 0;
      }
      traceGeo.getAttribute('position').needsUpdate = true;
    }

    /** Pose everything for scene position tt (0..1) at this tile's state. */
    function update(dt, state) {
      time += dt;
      var vis = visualOf(state.t);
      var err = state.stage === 'error';
      var doneAge = state.doneAge;                          /* seconds since done, or -1 */
      var info = {faces: nFaces, detached: 0, consumed: 0, particles: 0, wireDrawn: 0,
        folderOpacity: 0, frontAngle: 0, label: labelText};
      if (!err) sphere.rotation.y += dt * 0.35;             /* ambient spin: alive, not progress */

      /* wire: drawn with download, fading as the faces take over */
      var wn = Math.floor(wireCount * vis.wire / 2) * 2;
      wireGeo.setDrawRange(0, wn);
      info.wireDrawn = wireCount ? wn / wireCount : 0;
      wireMat.opacity = err ? 0.9 : 0.9 * (1 - 0.8 * vis.stream) * (1 - smooth(vis.assemble * 3));
      wireMat.color.copy(err ? red : wireCol);
      seedDot.material.opacity = 0.9 * (1 - vis.wire);

      /* faces: fill in and detach with extract_audio, consumed by the stream */
      faceMat.opacity = 0.92 * smooth(vis.detach * 3);
      faceMat.color.copy(err ? red : faceCol);
      for (var fi = 0; fi < nFaces; fi += 1) {
        var h = rank[fi];
        var det = smooth((vis.detach - h * 0.75) / 0.25);
        var con = smooth((vis.stream - h * 0.88) / 0.12);
        if (det > 0.5) info.detached += 1;
        if (con > 0.98) info.consumed += 1;
        var push = 0.34 * det + 0.5 * con;
        var sc = det > 0 ? (1 - con) * (1 - 0.18 * det) : 1;
        var nx = nrm[fi * 9], ny = nrm[fi * 9 + 1], nz = nrm[fi * 9 + 2];
        var ox = cen[fi * 3] + nx * push, oy = cen[fi * 3 + 1] + ny * push, oz = cen[fi * 3 + 2] + nz * push;
        for (var vv = 0; vv < 3; vv += 1) {
          var o = fi * 9 + vv * 3;
          facePos[o] = ox + loc[o] * sc;
          facePos[o + 1] = oy + loc[o + 1] * sc;
          facePos[o + 2] = oz + loc[o + 2] * sc;
        }
      }
      posAttr.needsUpdate = true;

      /* particles: from each consumed face along an arc into the folder */
      var flowing = vis.stream > 0 && vis.assemble < 1 && !err;
      var land = smooth(vis.assemble * 1.5);
      var cosY = Math.cos(sphere.rotation.y), sinY = Math.sin(sphere.rotation.y);
      for (var pi = 0; pi < NP; pi += 1) {
        var f2 = pFace[pi];
        var hh = rank[f2];
        var released = vis.stream - hh * 0.88 > 0;
        var o3 = pi * 3;
        if (!flowing || !released || (vis.stream >= 1 && land >= 1)) {
          pPos[o3] = 0; pPos[o3 + 1] = -99; pPos[o3 + 2] = 0;
          continue;
        }
        info.particles += 1;
        var u = (time * pSpeed[pi] * 0.5 + pPhase[pi]) % 1;
        if (vis.stream >= 1) u = u + (1 - u) * land;          /* the last of it lands */
        var lx = cen[f2 * 3], ly = cen[f2 * 3 + 1], lz = cen[f2 * 3 + 2];
        var sx = sphereWorld.x + lx * cosY + lz * sinY, sy = sphereWorld.y + ly, sz = -lx * sinY + lz * cosY;
        var ex = folderWorld.x + pEnd[pi * 2], ey = folderWorld.y + pEnd[pi * 2 + 1] * 0.6, ez = 0.05;
        var mx = (sx + ex) / 2, my = Math.max(sy, ey) + pLift[pi], mz = (sz + ez) / 2 + 0.3;
        var a = (1 - u) * (1 - u), b2 = 2 * (1 - u) * u, c = u * u;
        pPos[o3] = a * sx + b2 * mx + c * ex;
        pPos[o3 + 1] = a * sy + b2 * my + c * ey;
        pPos[o3 + 2] = a * sz + b2 * mz + c * ez;
        cT.copy(cA).lerp(cB, u);
        pCol[o3] = cT.r; pCol[o3 + 1] = cT.g; pCol[o3 + 2] = cT.b;
      }
      pPosAttr.needsUpdate = true;
      pColAttr.needsUpdate = true;

      /* the folder: an outline waiting; filling with the stream; assembling */
      outlineMat.opacity = 0.55 * (1 - smooth(vis.assemble * 1.6));
      outlineMat.color.copy(err ? red : cB);
      fill.scale.y = Math.max(0.0001, vis.stream * (1 - smooth((vis.assemble - 0.5) * 2)));
      fillMat.opacity = 0.4;
      var ab = smooth(vis.assemble * 1.5);
      var af = smooth(vis.assemble * 1.5 - 0.45);
      back.position.set(backFrom.x * (1 - ab), backFrom.y * (1 - ab), -0.02 + backFrom.z * (1 - ab));
      back.scale.setScalar(Math.max(0.0001, ab));
      back.rotation.z = (1 - ab) * 1.4;
      backMat.opacity = ab;
      frontPivot.position.set(frontFrom.x * (1 - af), -FH / 2 + frontFrom.y * (1 - af), 0.03 + frontFrom.z * (1 - af));
      frontPivot.scale.setScalar(Math.max(0.0001, af));
      var close = doneAge >= 0 ? smooth(doneAge / 1.1) : 0;
      frontPivot.rotation.x = 0.62 * (1 - close) + (1 - af) * 0.9;
      frontMat.opacity = af;
      info.folderOpacity = Math.min(ab, af);
      info.frontAngle = frontPivot.rotation.x;
      if (err) { backMat.color.copy(red); frontMat.color.copy(red); }
      /* the finished file: the name and the signature on its face */
      if (state.stage === 'done') {
        if (state.name !== labelText) { labelText = state.name; drawLabel(labelText); }
        var ts = JSON.stringify(state.bars);
        if (ts !== traceSig) { traceSig = ts; drawTrace(state.bars); }
        labelMat.opacity = close;
        traceMat.opacity = state.bars.length ? 0.85 * close : 0;
        var pulse = close < 1 ? 1 : 1 + 0.035 * Math.max(0, 1 - (doneAge - 1.1) / 0.3);
        /* the file comes forward: bigger, so the name on its face reads */
        folder.scale.setScalar((1 + 0.32 * close) * pulse);
        folder.position.x = 1.62 - 0.12 * close;
      } else {
        labelMat.opacity = 0;
        traceMat.opacity = 0;
      }
      info.label = labelMat.opacity > 0.5 ? labelText : '';
      return info;
    }

    function dispose() {
      disposables.forEach(function (x) { try { x.dispose(); } catch (err) { /* fine */ } });
      disposables.length = 0;
    }

    return {scene: scene, camera: camera, update: update, dispose: dispose};
  }

  function disposeScene(t) {
    if (t.scene) { try { t.scene.dispose(); } catch (err) { /* fine */ } }
    t.scene = null;
  }

  /* ------------------------------------------------ the flat fallback */

  function canvasSize(t) {
    var c = t.dom && t.dom.canvas;
    if (!c) return null;
    var w = Math.max(1, Math.round(c.clientWidth || 0));
    var h = Math.max(1, Math.round(c.clientHeight || 0));
    if (w < 8 || h < 8) return null;
    return {w: w, h: h};
  }

  function ctx2d(t) {
    var d = t.dom;
    if (!d) return null;
    if (!d.ctx2d) { try { d.ctx2d = d.canvas.getContext('2d'); } catch (err) { d.ctx2d = null; } }
    return d.ctx2d;
  }

  function fitCanvas(t, dpr) {
    var sz = canvasSize(t);
    if (!sz) return null;
    var c = t.dom.canvas;
    var W = Math.round(sz.w * dpr), H = Math.round(sz.h * dpr);
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    return {w: sz.w, h: sz.h, W: W, H: H};
  }

  function blit(t, source) {
    var g = ctx2d(t);
    var sz = fitCanvas(t, R.dpr || 1);
    if (!g || !sz) return false;
    g.clearRect(0, 0, sz.W, sz.H);
    try { g.drawImage(source, 0, 0, sz.W, sz.H); } catch (err) { return false; }
    return true;
  }

  function drawFallback(t) {
    var g = ctx2d(t);
    var sz = fitCanvas(t, 1);
    if (!g || !sz) return;
    var W = sz.W, H = sz.H;
    var err = t.stage === 'error';
    var tt = err ? t.frozenT : t.target;
    var v = visualOf(tt);
    g.clearRect(0, 0, W, H);
    var cx = W * 0.27, cy = H * 0.52, r = Math.min(H * 0.34, W * 0.16);
    g.lineWidth = 2;
    g.strokeStyle = PAL.rule;
    g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke();
    g.strokeStyle = err ? PAL.red : PAL.cyan;
    g.beginPath(); g.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clamp01(tt)); g.stroke();
    g.fillStyle = err ? PAL.red : PAL.cyan;
    g.globalAlpha = 0.25 + 0.6 * (1 - v.stream);
    g.beginPath(); g.arc(cx, cy, r * 0.62 * (1 - 0.8 * v.stream), 0, Math.PI * 2); g.fill();
    g.globalAlpha = 1;
    var fx = W * 0.58, fy = H * 0.28, fw = W * 0.34, fh = H * 0.5;
    g.strokeStyle = err ? PAL.red : PAL.gold;
    g.setLineDash(v.assemble > 0.5 ? [] : [4, 3]);
    g.beginPath();
    g.moveTo(fx, fy + fh); g.lineTo(fx + fw, fy + fh); g.lineTo(fx + fw, fy);
    g.lineTo(fx + fw * 0.42, fy); g.lineTo(fx + fw * 0.35, fy - H * 0.07); g.lineTo(fx, fy - H * 0.07); g.closePath();
    g.stroke();
    g.setLineDash([]);
    if (v.assemble > 0) {
      g.globalAlpha = v.assemble;
      g.fillStyle = err ? PAL.red : PAL.gold;
      g.fillRect(fx + 2, fy + fh * 0.25, fw - 4, fh * 0.75 - 2);
      g.globalAlpha = 1;
    }
  }

  /* ------------------------------------------------ the loop */

  function needsFrames(t) {
    if (!t.dom || t.fallback) return false;
    if (t.isStatic) return false;
    return true;
  }

  function shouldRun() {
    if (!R.rail || !R.rail.isConnected) return 'not attached';
    if (document.hidden) return 'page hidden';
    if (!R.onScreen) return 'rail off screen';
    if (R.failed) return 'no WebGL';
    if (!R.THREE) return 'three.js loading';
    for (var i = 0; i < order.length; i += 1) { if (needsFrames(tiles[order[i]])) return ''; }
    return 'idle';
  }

  function wake(why) {
    if (R.raf) return;
    var no = shouldRun();
    if (no) { R.paused = true; R.reason = no; return; }
    R.paused = false;
    R.reason = why || 'running';
    R.last = 0;
    R.raf = root.requestAnimationFrame(frame);
  }

  function halt(why) {
    if (R.raf) { root.cancelAnimationFrame(R.raf); R.raf = 0; }
    R.paused = true;
    R.reason = why;
  }

  function frame(ts) {
    R.raf = 0;
    var no = shouldRun();
    if (no) { R.paused = true; R.reason = no; return; }
    var dt = R.last ? Math.min(0.1, (ts - R.last) / 1000) : 1 / 60;
    var minDt = R.tablet ? 1 / 31 : 1 / 61;              /* 30 fps on the tablet */
    R.acc += dt;
    R.last = ts;
    if (R.acc < minDt) { R.raf = root.requestAnimationFrame(frame); return; }
    dt = Math.min(0.1, R.acc);
    R.acc = 0;
    for (var i = 0; i < order.length; i += 1) {
      var t = tiles[order[i]];
      if (!needsFrames(t)) continue;
      try { renderTile(t, dt); }
      catch (err) {
        if (root.console) root.console.warn('[voice-actor-viz] tile fell back to 2D:', err);
        toFallback(t, err && err.message ? err.message : String(err));
      }
    }
    R.frames += 1;
    var again = shouldRun();
    if (again) { R.paused = true; R.reason = again; if (again === 'idle') disposeRenderer(); return; }
    R.raf = root.requestAnimationFrame(frame);
  }

  function renderTile(t, dt) {
    step(t, dt);
    var sz = canvasSize(t);
    if (!sz) return;
    var renderer = ensureRenderer(sz.w, sz.h);
    if (!renderer) { toFallback(t, R.failed || 'no renderer'); return; }
    if (!t.scene) t.scene = buildScene(R.THREE, t);
    var cam = t.scene.camera;
    var aspect = sz.w / sz.h;
    if (Math.abs(cam.aspect - aspect) > 0.001) { cam.aspect = aspect; cam.updateProjectionMatrix(); }
    t.sceneInfo = t.scene.update(dt, {t: t.t, stage: t.stage, name: nameOf(t, actorsNow()),
      bars: sigBars(sigOf(t.status)), doneAge: t.doneClock >= 0 ? t.clock - t.doneClock : (t.restored ? 9 : -1)});
    renderer.render(t.scene.scene, cam);
    blit(t, R.canvas);
    if (t.dom) t.dom.bar.style.width = Math.round(clamp01(t.stage === 'error' ? t.frozenT : t.t) * 100) + '%';
    if (t.restored && t.stage === 'done') { t.t = 1; }
    if (settled(t) || (t.restored && t.stage === 'done')) {
      /* the finished card: keep the last frame as a picture, free the scene */
      var keep = document.createElement('canvas');
      keep.width = t.dom.canvas.width; keep.height = t.dom.canvas.height;
      try { keep.getContext('2d').drawImage(t.dom.canvas, 0, 0); t.snap = keep; } catch (err) { t.snap = null; }
      t.isStatic = true;
      disposeScene(t);
    }
  }

  /* ================================================== attach / detach */

  function attach(rail, ctx) {
    if (!rail) return false;
    loadStore();
    if (ctx) R.ctx = ctx;
    R.tablet = ctx && typeof ctx.isTablet === 'boolean' ? ctx.isTablet : isTablet();
    if (R.rail === rail && rail.isConnected) { wake('attach'); return true; }
    if (R.rail) detach();
    R.rail = rail;
    order.forEach(function (id) { var t = tiles[id]; if (t) { t.dom = null; mountTile(t); } });
    try {
      if (root.IntersectionObserver) {
        R.io = new root.IntersectionObserver(function (entries) {
          var e = entries[entries.length - 1];
          R.onScreen = !!(e && e.isIntersecting);
          if (R.onScreen) wake('on screen'); else halt('rail off screen');
        });
        R.io.observe(rail);
      } else { R.onScreen = true; }
    } catch (err) { R.onScreen = true; }
    loadThree().then(function () { wake('three ready'); }, function (err) { failAll(err.message || String(err)); });
    wake('attach');
    return true;
  }

  function detach() {
    halt('not attached');
    if (R.io) { try { R.io.disconnect(); } catch (err) { /* fine */ } R.io = null; }
    order.forEach(function (id) {
      var t = tiles[id];
      if (!t) return;
      disposeScene(t);
      if (!t.isStatic) t.snap = null;
      unmountTile(t);
    });
    disposeRenderer();
    R.rail = null;
    R.onScreen = true;
  }

  /* ================================================== the debug hook */

  function tileDebug(t) {
    if (!t) return null;
    var visible = [];
    if (t.dom) {
      var box = t.dom.win.getBoundingClientRect();
      Array.prototype.forEach.call(t.dom.list.children, function (row) {
        var r = row.getBoundingClientRect();
        if (r.bottom > box.top + 1 && r.top < box.bottom - 1) visible.push(row.textContent);
      });
    }
    return {
      id: t.id, name: nameOf(t, actorsNow()), stage: t.stage, phase: phaseOf(t.stage),
      t: Math.round(t.t * 1000) / 1000, target: Math.round(t.target * 1000) / 1000,
      vis: visualOf(t.stage === 'error' ? t.frozenT : t.t), scene: t.sceneInfo,
      hasScene: !!t.scene, isStatic: t.isStatic, fallback: t.fallback, fallbackWhy: t.fallbackWhy,
      mounted: !!t.dom, lines: t.lines.slice(-4).map(function (l) { return l.tag + '  ' + l.text; }),
      lineCount: t.lines.length, visibleLines: visible, road: t.road || 'raw',
      card: t.dom && !t.dom.card.hidden ? t.dom.card.textContent : '',
      harvested: !!(t.status && t.status.harvested)
    };
  }

  function debug() {
    return {
      three: !!R.THREE, failed: R.failed, attached: !!R.rail, paneCtx: !!(R.ctx && R.ctx.request),
      renderer: {alive: !!R.renderer, frames: R.frames, running: !!R.raf, paused: R.paused, reason: R.reason,
        pixelRatio: R.dpr, size: [R.w, R.h], tablet: R.tablet},
      tiles: order.map(function (id) { return tileDebug(tiles[id]); })
    };
  }

  /** Tests: step every tile's model by sec seconds without the wall clock. */
  function advance(sec) {
    var n = Math.max(1, Math.round((Number(sec) || 0) / 0.05));
    for (var i = 0; i < n; i += 1) order.forEach(function (id) { step(tiles[id], 0.05); });
    order.forEach(function (id) {
      var t = tiles[id];
      if (!settled(t) && !(t.restored && t.stage === 'done')) t.isStatic = false;
      if (t.dom) paintTile(t);
    });
    wake('advance');
    return debug();
  }

  /* ================================================== wiring */

  function onJob(e) {
    var d = (e && e.detail) || {};
    feed(d.job_id || d.id || (d.status && d.status.id), d.status || d.job, {name: d.name});
  }

  /** The extraction pane's job (its eventOf()): the lab's real fields. */
  function onExtractJob(e) {
    var j = e && e.detail;
    if (!j || !j.id) return;
    var t = feed(j.id, j, {name: j.name});
    if (t && tiles[j.id]) tiles[j.id].road = 'extract';
  }

  /** The pane's whole list: a running tile the operator forgot goes too
   * (a finished card stays until its own dismiss). */
  function onExtractJobs(e) {
    var list = (e && e.detail && e.detail.jobs) || [];
    var keep = {};
    list.forEach(function (j) { if (j && j.id) { keep[j.id] = true; onExtractJob({detail: j}); } });
    order.slice().forEach(function (id) {
      var t = tiles[id];
      if (t && t.road === 'extract' && !keep[id] && t.stage !== 'done' && t.stage !== 'error') {
        disposeScene(t);
        unmountTile(t);
        delete tiles[id];
        order = order.filter(function (x) { return x !== id; });
      }
    });
  }

  function onVisibility() {
    if (document.hidden) halt('page hidden');
    else wake('page visible');
  }

  function start() {
    if (!root.addEventListener || R.started) return;
    R.started = true;
    root.addEventListener('pine-voice-actor:job', onJob);
    root.addEventListener('pine-voice-actor:extract-job', onExtractJob);
    root.addEventListener('pine-voice-actor:extract-jobs', onExtractJobs);
    root.addEventListener('pine-voice-actor:extract-open', function () {
      var rail = document.getElementById('vaTileRail');
      if (rail) attach(rail, R.ctx);
    });
    root.addEventListener('pine-voice-actor:extract-close', function () { detach(); });
    root.addEventListener('pine-voice-actor:actor-created', function (e) {
      var v = e && e.detail && e.detail.voice;
      if (!v || !v.id) return;
      order.forEach(function (id) {
        var t = tiles[id];
        if (t && t.status && t.status.voice_id === v.id) {
          if (v.name) t.name = String(v.name);
          t.isStatic = false; t.snap = null;
          if (t.dom) paintTile(t);
          saveCards();
        }
      });
      wake('actor named');
    });
    root.addEventListener('pine-voice-actor:actors', function () {
      order.forEach(function (id) { var t = tiles[id]; if (t && t.dom) paintTile(t); });
    });
    document.addEventListener('visibilitychange', onVisibility);
  }

  var api = {
    feed: feed, attach: attach, detach: detach, dismiss: dismissTile, debug: debug, advance: advance,
    /* pure helpers, for the tests */
    STAGES: STAGES, SPAN: SPAN, GLOSS: GLOSS, targetOf: targetOf, visualOf: visualOf, phaseOf: phaseOf,
    deriveLines: deriveLines, sigBars: sigBars, nameOf: nameOf, stageOf: stageOf, hms: hms,
    CARDS_KEY: CARDS_KEY, DISMISSED_KEY: DISMISSED_KEY
  };
  root.PineVoiceActorViz = api;
  /* the extraction pane's seam (voice-actor-extract.js tile() / unmount()) */
  root.PineVoiceActorTiles = {
    mount: function (rail, ctx, paneApi) {
      attach(rail, ctx);
      try {
        if (paneApi && typeof paneApi.jobs === 'function') onExtractJobs({detail: {jobs: paneApi.jobs() || []}});
      } catch (err) { /* the events still arrive */ }
    },
    unmount: function () { detach(); }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && document && typeof document.createElement === 'function') start();
})(typeof window !== 'undefined' ? window : globalThis);
