'use strict';
/* THE ROLLING RECORD OF THIS WINDOW (2026-09-15, #1182).
 *
 * The operator: "Make sure that the Pine Box app also supports the ability
 * to record and export screen recordings of the application that are being
 * cached in real time as the application is running." And then, about the
 * app as a whole: "Basically the Pine Box app needs the same feature set as
 * what we have going on with the Pine Box tab. So it needs feature parity,
 * so there's nothing left out."
 *
 * He had the export sheet open when he said it, and the sheet was telling
 * him the truth: "the ring cannot be read on this surface (no replayState)"
 * and "no screen recording road on this surface". The renderer has had the
 * whole hot-corner export flow for a week; only the tablet had anything
 * behind it. The note this file closes was already written, at glass:clip
 * in main.js:
 *
 *     "Only the tablet has a rolling recorder; this window does not, so a
 *      local capture still films forwards."
 *
 * Which is why "save the last minute" on the desk could only ever mean
 * "wait a minute". It reaches backwards now.
 *
 * WHAT IS CACHED, AND WHY IT IS SHAPED LIKE THIS.
 *
 * The renderer records the window with MediaRecorder and hands finished
 * pieces down here; this module keeps them on DISK, oldest thrown away, and
 * cuts what is asked for out of the pieces that survive.
 *
 * The pieces are SELF-CONTAINED files - the recorder is stopped and started
 * again every SEGMENT_MS - rather than one long recording chopped into
 * timeslices. That costs a few milliseconds at each seam and buys the only
 * property that matters here: every file on disk is a file. A WebM
 * timeslice that is not the first carries no EBML header, so a ring made of
 * them is a ring of bytes that no decoder will open, and the failure only
 * shows up when somebody finally asks for a cut - which is the worst moment
 * to discover it.
 *
 * Disk rather than memory because the ask goes to twenty minutes. At the
 * bitrate the renderer asks for, twenty minutes is on the order of two
 * hundred megabytes; that is nothing on a disk and is not a thing to hold
 * in an Electron main process. HOLD_MAX_BYTES bounds it a second way, so a
 * screen that suddenly encodes badly cannot fill the drive while the
 * seconds count still looks reasonable.
 *
 * THE ERA. The concat demuxer refuses pieces whose codec parameters
 * disagree, and the window is resizable, so a ring that spans a resize
 * cannot be concatenated. Each piece records the size it was made at, and
 * pieces of the current size are an "era": a cut uses the newest era and
 * says so when it had to stop early. The renderer asks for a fixed capture
 * size to make this rare, not impossible.
 *
 * ---------------------------------------------------------------------------
 * THE BROADCAST IS IN THE RING NOW (2026-09-15, #1205).
 *
 * The operator, with the editor open on a thirty-second cut that said "No
 * audio was captured in this recording":
 *
 *   "Similar to the tablet, I always want to capture the broadcast audio of
 *    the recording. So any time that I go into the video editor, I need the
 *    audio of the broadcast."
 *
 * "Any time" is the requirement, not a preference, so the sound has to be
 * PART of the recording rather than something fetched afterwards - which is
 * exactly how the tablet does it: ScreenReplay captures the Android playback
 * mix alongside the picture and muxes the two together.
 *
 * WHAT #1182 DID INSTEAD, AND WHY IT WAS ALWAYS SILENT. Every piece was
 * filmed with `-an` and the sound was pulled after the fact out of PineAir's
 * ring by executeJavaScript. Measured tonight, that road cannot work on this
 * desk, for two independent reasons:
 *
 *   1. PineAir.start() has exactly ONE caller in the whole renderer
 *      (sampler.js:3247, inside the sampler's own mount). On a desk where the
 *      sampler is never opened there is no ring at all, and the question came
 *      back "the air tap is not running on this terminal".
 *   2. Even started it would tap the WRONG DOCUMENT. PineAir hooks media
 *      elements that play in the document it runs in, and it runs in the
 *      SHELL; the broadcast plays in the panel - `<webview id="controlFrame">`
 *      (index.html:542) - a separate document in a separate renderer process.
 *      sampler-air.js's own header says the rest: on the desk the shell is
 *      file:// and the panel is http://, so the tap is cross-origin, and
 *      tapping a tainted element would MUTE the broadcast - so it refuses,
 *      "honestly rather than recording silence".
 *
 * So the pieces now arrive WITH an audio track. Electron's display-media
 * handler answers `audio: 'loopback'`, which is this machine's playback mix -
 * the panel's sound included, because a loopback tap sits below every
 * document boundary - and this module's remaining job is to carry that track
 * through the concat and to say, piece by piece, whether it was really there.
 *
 * EVERY PIECE RECORDS WHETHER IT HAD SOUND (`a` in the meta), because a
 * recording that CLAIMS audio it does not have is the one outcome worse than
 * silence. A cut therefore reports coverage across the window it actually
 * used, how many gaps there were, and a plain reason when there is nothing -
 * the tablet's provenance shape, which video-edit-model.js audioNotice()
 * already reads (state / complete / coverage_ratio / video_only_explicit).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const clipMux = require('./clip-mux.cjs');

/* THE OPERATOR'S OWN NUMBERS (#1182): "I want the rolling replay to be at
 * default 30 seconds with a max able to be set to up to five or ten minutes
 * and a minimum set to five seconds." Ten minutes is taken as the ceiling,
 * being the generous end of what he said.
 *
 * A piece must be shorter than the SHORTEST hold or the ring cannot hold a
 * whole one: at a five-second hold, two-second pieces leave three in hand
 * and a cut that can actually land inside the window. Ten minutes of them
 * is three hundred files, which is nothing for a directory and is the price
 * of every piece being a file a decoder will open. */
const SEGMENT_MS = 2000;
const HOLD_DEFAULT_S = 30;
const HOLD_MIN_S = 5;
const HOLD_MAX_S = 600;           /* ten minutes */
const HOLD_MAX_BYTES = 900 * 1024 * 1024;

/* #1205: the name the provenance carries, said the way the tablet says
 * "android-playback-mix" - what it IS, not which API produced it. */
const AUDIO_SOURCE = 'desk-loopback-mix';

function nowMs() { return Date.now(); }

class ScreenRing {
  constructor() {
    this.dir = null;
    this.pieces = [];             /* {file, at, ms, bytes, w, h, a} oldest first */
    this.holdSeconds = HOLD_DEFAULT_S;
    this.running = false;
    this.detail = 'not started';
    this.startedAt = 0;
    this.dropped = 0;             /* pieces aged out, for the record */
    /* #1182d: bumped on every piece that lands, so a cut can wait for the
     * one it just asked for rather than sleeping a guessed interval. */
    this.taken = 0;
    this.lastError = '';
    /* #1205: WHAT THE RECORDER SAYS ABOUT ITS OWN SOUND, before any cut is
     * asked for. The renderer is the only side that can know whether the
     * capture came back with an audio track, so it says so at begin() and
     * again whenever that changes, and the export sheet reads it off
     * replayState() - hot-corners.js:1553 prints `audio.state` and
     * `audio.detail` word for word. */
    this.audioSaid = { source: AUDIO_SOURCE, present: false,
      state: 'unknown', detail: 'the recorder has not said yet',
      supported: null };
  }

  /* --------------------------------------------------------------- disk */

  ensureDir() {
    if (this.dir && fs.existsSync(this.dir)) return this.dir;
    this.dir = path.join(os.tmpdir(), 'pinebox-screen-ring-' + process.pid);
    fs.mkdirSync(this.dir, { recursive: true });
    return this.dir;
  }

  /* A ring left behind by a process that died. Nothing else cleans these
   * up, and a crashed session must not cost the disk a quarter gigabyte
   * until the machine is rebooted. */
  sweepOld() {
    let swept = 0;
    try {
      const tmp = os.tmpdir();
      for (const name of fs.readdirSync(tmp)) {
        if (!/^pinebox-screen-ring-(\d+)$/.test(name)) continue;
        const pid = Number(RegExp.$1);
        if (pid === process.pid) continue;
        let alive = false;
        try { process.kill(pid, 0); alive = true; } catch (e) { alive = false; }
        if (alive) continue;
        try { fs.rmSync(path.join(tmp, name), { recursive: true, force: true }); swept += 1; }
        catch (e) { /* someone else's, or in use */ }
      }
    } catch (e) { /* a tmpdir that cannot be listed is not fatal */ }
    return swept;
  }

  /* --------------------------------------------------------------- feed */

  begin(opts) {
    const want = Number((opts || {}).holdSeconds || 0);
    if (want > 0) this.setHold(want);
    if (opts && opts.audio) this.noteAudio(opts.audio);
    this.ensureDir();
    this.sweepOld();
    this.running = true;
    this.startedAt = this.startedAt || nowMs();
    this.detail = 'recording';
    return this.state();
  }

  stop(why) {
    this.running = false;
    this.detail = String(why || 'stopped');
    return this.state();
  }

  /* #1205: the recorder, saying what its capture actually carries. Taken
   * whole rather than merged, so a recorder that LOSES its audio track
   * cannot leave a stale "capturing" behind it. `supported` is null until
   * the renderer has been told; false means this platform has no loopback
   * road at all, and the detail is what the sheet and the editor print. */
  noteAudio(said) {
    const given = said || {};
    this.audioSaid = {
      source: String(given.source || AUDIO_SOURCE),
      present: !!given.present,
      state: String(given.state || (given.present ? 'capturing' : 'unavailable')),
      detail: String(given.detail || ''),
      supported: given.supported === null || given.supported === undefined
        ? null : !!given.supported
    };
    return this.audioSaid;
  }

  setHold(seconds) {
    const n = Math.round(Number(seconds) || 0);
    this.holdSeconds = Math.max(HOLD_MIN_S, Math.min(HOLD_MAX_S, n || HOLD_DEFAULT_S));
    this.prune();
    return this.holdSeconds;
  }

  /* One finished piece from the renderer. `at` is when the piece STARTED,
   * in epoch ms, taken in the renderer rather than here: the trip through
   * IPC is short but it is not zero, and every cut is arithmetic on these
   * timestamps. */
  take(buffer, meta) {
    if (!buffer || !buffer.length) return { ok: false, why: 'empty piece' };
    const m = meta || {};
    const ms = Math.max(1, Math.round(Number(m.ms) || SEGMENT_MS));
    const at = Math.round(Number(m.at) || (nowMs() - ms));
    this.ensureDir();
    const file = path.join(this.dir, 'p' + String(at) + '.webm');
    try {
      fs.writeFileSync(file, Buffer.from(buffer));
    } catch (error) {
      this.lastError = error.message;
      return { ok: false, why: error.message };
    }
    this.taken += 1;
    /* #1205: `a` is the renderer's answer to "did THIS piece carry a live
     * audio track", asked of the stream at the moment the piece closed. A
     * piece from a recorder that lost its loopback halfway through says
     * false, and the cut's coverage says so rather than the file quietly
     * going quiet in the middle. */
    this.pieces.push({ file, at, ms, bytes: buffer.length,
      w: Math.round(Number(m.w) || 0), h: Math.round(Number(m.h) || 0),
      a: !!m.a });
    this.pieces.sort((a, b) => a.at - b.at);
    this.running = true;
    this.detail = 'recording';
    this.startedAt = this.startedAt || at;
    this.prune();
    return { ok: true, held: this.heldSeconds(), pieces: this.pieces.length };
  }

  /* Old pieces go, by time first and by weight second. */
  prune() {
    const keepFrom = nowMs() - (this.holdSeconds * 1000);
    while (this.pieces.length > 1) {
      const first = this.pieces[0];
      if (first.at + first.ms >= keepFrom) break;
      this.drop(first);
    }
    while (this.pieces.length > 1 && this.bytes() > HOLD_MAX_BYTES) {
      this.drop(this.pieces[0]);
    }
  }

  drop(piece) {
    this.pieces.shift();
    this.dropped += 1;
    try { fs.unlinkSync(piece.file); } catch (e) { /* already gone */ }
  }

  forget() {
    this.running = false;
    for (const p of this.pieces) { try { fs.unlinkSync(p.file); } catch (e) {} }
    this.pieces = [];
    if (this.dir) { try { fs.rmSync(this.dir, { recursive: true, force: true }); } catch (e) {} }
    this.dir = null;
  }

  /* -------------------------------------------------------------- reads */

  bytes() {
    let n = 0;
    for (const p of this.pieces) n += p.bytes;
    return n;
  }

  heldSeconds() {
    if (!this.pieces.length) return 0;
    const first = this.pieces[0];
    const last = this.pieces[this.pieces.length - 1];
    return Math.max(0, ((last.at + last.ms) - first.at) / 1000);
  }

  /* The size the newest pieces are being made at. */
  era() {
    if (!this.pieces.length) return { w: 0, h: 0 };
    const last = this.pieces[this.pieces.length - 1];
    return { w: last.w, h: last.h };
  }

  /* The shape hot-corners.js reads: {ok, running, seconds, holds, bytes,
   * detail}. `seconds` is what is HELD - less than `holds` for the first
   * minutes and after the recorder has been interrupted - which is exactly
   * what the tablet's own replayState means by it. */
  state() {
    const held = this.heldSeconds();
    let detail = this.detail;
    if (this.running && held < this.holdSeconds) {
      detail = 'recording - holding ' + held.toFixed(0) + 's of '
        + this.holdSeconds + 's';
    } else if (this.running) {
      detail = 'recording - the ring is full';
    }
    if (this.lastError) detail += ' (last trouble: ' + this.lastError + ')';
    return { ok: true, running: !!this.running, seconds: Math.round(held * 10) / 10,
      holds: this.holdSeconds, bytes: this.bytes(), pieces: this.pieces.length,
      dropped: this.dropped, era: this.era(), where: this.dir || '',
      /* #1205: the sheet asks this BEFORE it cuts, so the checkbox about
       * allowing video without complete audio is a decision made with the
       * answer in hand rather than a guess. `held_ratio` is measured over
       * the pieces on disk, not claimed by the recorder. */
      audio: { ...this.audioSaid, held_ratio: this.heldAudioRatio() },
      detail };
  }

  /* How much of what is HELD carries sound, 0..1. 0 with nothing held, so a
   * fresh ring reads as "no sound yet" rather than "complete". */
  heldAudioRatio() {
    let heard = 0;
    let total = 0;
    for (const p of this.pieces) { total += p.ms; if (p.a) heard += p.ms; }
    if (!total) return 0;
    return Math.round((heard / total) * 1000) / 1000;
  }

  /* The pieces covering `seconds` of video ending `back` seconds ago, newest
   * era only. Returns what it could actually reach, never a promise it
   * cannot keep. */
  window(seconds, back) {
    const want = Math.max(0.2, Number(seconds) || 0);
    const behind = Math.max(0, Number(back) || 0);
    const held = this.heldSeconds();
    if (!this.pieces.length) {
      return { ok: false, held: 0, detail: 'the ring is empty' };
    }
    const end = nowMs() - (behind * 1000);
    const start = end - (want * 1000);
    const era = this.era();
    const used = [];
    let clamped = false;
    for (const p of this.pieces) {
      if (p.at + p.ms <= start) continue;
      if (p.at >= end) continue;
      if (era.w && p.w && (p.w !== era.w || p.h !== era.h)) { clamped = true; continue; }
      used.push(p);
    }
    if (!used.length) {
      return { ok: false, held, clamped,
        detail: 'nothing in the ring covers that window' };
    }
    const first = used[0];
    const last = used[used.length - 1];
    if (first.at > start + 250) clamped = true;
    /* Where the cut really lands, said the way the tablet says it: seconds
     * before now, oldest edge and newest edge. */
    const from = (nowMs() - first.at) / 1000;
    const to = Math.max(0, (nowMs() - (last.at + last.ms)) / 1000);
    /* How far into the first piece the wanted window begins. */
    const offset = Math.max(0, (start - first.at) / 1000);
    return { ok: true, pieces: used, held, clamped,
      from: Math.round(from * 10) / 10, to: Math.round(to * 10) / 10,
      offset, seconds: Math.min(want, ((last.at + last.ms) - Math.max(start, first.at)) / 1000),
      w: era.w, h: era.h };
  }

  /* ------------------------------------------------------------ the sound */

  /* #1205: THE PROVENANCE OF ONE CUT, in the tablet's shape.
   *
   * The tablet reports `source: "android-playback-mix"` with present,
   * complete, state, coverage and gap counts; this is the same object for
   * the desk's own mix, measured over the pieces the cut actually used
   * rather than over the recorder's intention. video-edit-model.js
   * audioNotice() reads state, complete and coverage_ratio, and the station
   * carries the whole object through as `audio_capture`.
   *
   * THE STATES, AND WHAT EACH ONE MEANS TO SOMEBODY READING THE EDITOR:
   *
   *   captured     every piece in the window had sound. complete.
   *   partial      some did. The editor prints "Audio has gaps (73%
   *                captured). Missing sound cannot be restored in this
   *                editor." - which is true, and better than a silent
   *                stretch nobody was warned about.
   *   unavailable  none did, and `detail` says why in plain words.
   *
   * There is deliberately no state that means "probably". */
  soundFor(window, videoOnly) {
    const pieces = (window && window.pieces) || [];
    const said = this.audioSaid || {};
    const audio = { source: AUDIO_SOURCE, present: false, complete: false,
      state: 'unavailable', detail: '', coverage_ratio: 0,
      covered_seconds: 0, window_seconds: 0, gaps: 0, gap_seconds: 0,
      pieces: pieces.length, pieces_with_audio: 0,
      video_only_explicit: !!videoOnly, platform: process.platform,
      supported: said.supported === undefined ? null : said.supported };
    if (videoOnly) {
      audio.detail = 'video only, as asked';
      return audio;
    }
    let heard = 0;
    let missed = 0;
    let gaps = 0;
    let inGap = false;
    for (const p of pieces) {
      if (p.a) { heard += p.ms; inGap = false; audio.pieces_with_audio += 1; }
      else { missed += p.ms; if (!inGap) { gaps += 1; inGap = true; } }
    }
    const total = heard + missed;
    audio.window_seconds = Math.round((total / 1000) * 10) / 10;
    audio.covered_seconds = Math.round((heard / 1000) * 10) / 10;
    audio.gap_seconds = Math.round((missed / 1000) * 10) / 10;
    audio.gaps = gaps;
    audio.coverage_ratio = total ? Math.round((heard / total) * 1000) / 1000 : 0;
    if (!heard) {
      audio.detail = said.detail
        || (said.supported === false
          ? 'this platform has no loopback capture, so the recording is silent'
          : 'the recorder captured no audio track');
      return audio;
    }
    audio.present = true;
    audio.complete = !missed;
    audio.state = missed ? 'partial' : 'captured';
    audio.detail = missed
      ? ('the desk mix, with ' + gaps + (gaps === 1 ? ' gap' : ' gaps')
         + ' totalling ' + audio.gap_seconds.toFixed(1) + 's')
      : 'the desk mix, captured with the picture';
    return audio;
  }

  /* --------------------------------------------------------------- cuts */

  listFile(dir, pieces) {
    const lines = pieces.map(
      (p) => "file '" + p.file.replace(/\\/g, '/').replace(/'/g, "'\\''") + "'");
    const list = path.join(dir, 'pieces.txt');
    fs.writeFileSync(list, lines.join('\n') + '\n', 'utf8');
    return list;
  }

  /* An mp4 of the window, written to `out`. Output-side -ss and -t, which
   * is the accurate seek - input-side seeking on a concat of WebM lands on
   * the nearest keyframe and a "last ten seconds" that is really the last
   * fourteen is not a cut, it is a guess.
   *
   * #1205: THE SOUND COMES OUT OF THE SAME PIECES AS THE PICTURE, which is
   * the whole point - no second file, no offset arithmetic, nothing to drift.
   * The audio is transcoded to AAC because the container is MP4 and Opus in
   * MP4 is a thing several players will not open; 160k stereo at 48k is the
   * broadcast's own shape.
   *
   * WHEN THE ENCODER REFUSES THE SOUND, THE PICTURE STILL LANDS. The concat
   * demuxer wants every piece to have the same streams, so a window that
   * spans the moment the loopback appeared or vanished can be refused whole.
   * That must cost the operator the audio, never the recording - so a refusal
   * is retried with `-an` and the provenance is DOWNGRADED to unavailable
   * with the encoder's own words in it. A cut that says "captured" must never
   * be a cut that is silent. */
  async cut(want, options) {
    const opts = options || {};
    const got = this.window(want.seconds, want.back);
    if (!got.ok) return { ok: false, detail: got.detail, held: got.held };
    const dir = clipMux.stash();
    const audio = this.soundFor(got, want.video_only);
    try {
      const list = this.listFile(dir, got.pieces);
      const out = want.out || path.join(dir, 'screen.mp4');
      const build = (withSound) => ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', list,
        '-ss', got.offset.toFixed(3), '-t', got.seconds.toFixed(3),
        ...(withSound
          ? ['-map', '0:v:0', '-map', '0:a:0',
             '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2']
          : ['-an']),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-pix_fmt', 'yuv420p', '-r', '25',
        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
        '-movflags', '+faststart', out];
      const ffmpeg = clipMux.findFfmpeg(opts.ffmpeg).path;
      try {
        await clipMux.run(ffmpeg, build(audio.present), 300000);
      } catch (error) {
        if (!audio.present) throw error;
        audio.present = false;
        audio.complete = false;
        audio.state = 'unavailable';
        audio.coverage_ratio = 0;
        audio.covered_seconds = 0;
        audio.detail = 'the ring held sound but the encoder refused it: '
          + error.message;
        await clipMux.run(ffmpeg, build(false), 300000);
      }
      const bytes = fs.statSync(out).size;
      return { ok: true, out, bytes, seconds: Math.round(got.seconds * 10) / 10,
        asked: Number(want.seconds) || 0, held: got.held, clamped: got.clamped,
        from: got.from, to: got.to, dir, audio,
        w: got.w, h: got.h };
    } catch (error) {
      clipMux.forget(dir);
      return { ok: false, detail: error.message, held: got.held, audio };
    }
  }

  /* Evenly spaced JPEGs out of the window, oldest first, for the scrub
   * strip. The mp4 behind them is temporary and is deleted before this
   * returns; nothing reaches the recordings folder. */
  async frames(want, options) {
    const opts = options || {};
    const seconds = Math.max(1, Math.min(30, Number(want.seconds) || 5));
    const count = Math.max(2, Math.min(24, Math.round(Number(want.count) || 10)));
    const edge = Math.max(120, Math.min(1280, Math.round(Number(want.edge) || 320)));
    const back = Math.max(0, Number(want.back) || 0);
    const got = this.window(seconds, back);
    if (!got.ok) return { ok: false, held: got.held, detail: got.detail };
    const dir = clipMux.stash();
    try {
      const list = this.listFile(dir, got.pieces);
      const span = Math.max(0.2, got.seconds);
      /* fps chosen so `count` frames land across the window. The half-frame
       * offset puts the first sample inside the window rather than exactly
       * on its opening edge, where a concat seam can leave a black field. */
      const fps = count / span;
      const args = ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', list,
        '-ss', (got.offset + (0.5 / Math.max(fps, 0.01))).toFixed(3),
        '-t', span.toFixed(3),
        '-vf', 'fps=' + fps.toFixed(5) + ',scale=' + edge + ':-2:flags=bicubic',
        /* #1205: the pieces carry sound now and the scrub strip is stills.
         * Said out loud so no decoder time is spent on a track that cannot
         * reach a JPEG. */
        '-an',
        '-frames:v', String(count), '-q:v', '4',
        path.join(dir, 'f%03d.jpg')];
      await clipMux.run(clipMux.findFfmpeg(opts.ffmpeg).path, args, 120000);
      const names = fs.readdirSync(dir).filter((n) => /^f\d+\.jpg$/.test(n)).sort();
      const frames = [];
      let bytes = 0;
      for (let i = 0; i < names.length; i += 1) {
        const b64 = fs.readFileSync(path.join(dir, names[i])).toString('base64');
        bytes += b64.length;
        /* `at` is how many seconds before NOW this frame sits, one decimal,
         * so the newest frame of a tail window is 0.0 and the strip can
         * label it "now" - the same meaning the tablet gives it. */
        const ago = got.to + ((names.length - 1 - i) * (span / Math.max(1, names.length - 1)));
        frames.push({ at: Math.round(ago * 10) / 10,
          image: 'data:image/jpeg;base64,' + b64 });
      }
      if (!frames.length) {
        return { ok: false, held: got.held, detail: 'the encoder produced no frames' };
      }
      return { ok: true, seconds: Math.round(span * 10) / 10, held: Math.round(got.held * 10) / 10,
        from: got.from, to: got.to, asked_back: back, clamped: got.clamped,
        frames, bytes, edge, detail: '' };
    } catch (error) {
      return { ok: false, held: got.held, detail: error.message };
    } finally {
      clipMux.forget(dir);
    }
  }
}

module.exports = { ScreenRing, SEGMENT_MS, HOLD_DEFAULT_S, HOLD_MIN_S, HOLD_MAX_S,
  HOLD_MAX_BYTES, AUDIO_SOURCE };
