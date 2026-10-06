'use strict';
/* 2026-10-03: Native 60fps capture, one absolute audio/video interval,
 * pixel-preserving resize runs, GPU encode with audio-preserving CPU fallback,
 * and a shared 4GiB audio+video rolling cache. The historical notes below
 * describe earlier measurements; the current paths supersede 12/25fps eras. */
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

/* ---------------------------------------------------------------------------
 * TWO RINGS, ONE CUT (2026-09-15, #1207).
 *
 *   "Similar to the tablet, I always want to capture the broadcast audio of
 *    the recording. So any time that I go into the video editor, I need the
 *    audio of the broadcast."
 *
 * #1205 above says the pieces "now arrive WITH an audio track". They never
 * did. Every pairing that would have put the sound in the same capture as the
 * picture was measured and refused by this Electron (37.10.3):
 *
 *   { video: win, audio: 'loopback' }     -> "Error starting capture".
 *   { video: win, audio: <panel frame> }  -> the same, with the frame found
 *                                            and correct in the log.
 *   { video: <panel frame>, audio: same } -> ACCEPTED, and the piece did
 *       carry 48 kHz opus - but the picture became the panel's own control
 *       page: no rail, no menu, not the Listen view he was watching. A
 *       recording of the wrong screen is worse than a silent one.
 *
 * What IS accepted is a SECOND capture, audio-only: the renderer asks
 * getDisplayMedia({ video: false, audio: true }) and main.js answers
 * { audio: <panel frame>, enableLocalEcho: true }. Measured: one audio track
 * labelled "Tab audio", no video track, and two such captures of the same
 * frame may be live at once - which is what makes this possible at all,
 * because the window capture is already running beside it.
 *
 * So there are two rings. The picture ring is untouched. The sound ring holds
 * its own pieces, and the cut lays them under the picture.
 *
 * -------------------------------------------------------------------------
 * ALIGNMENT, WHICH IS THE WHOLE DIFFICULTY, AND WHAT WAS MEASURED.
 *
 * The naive scheme - concatenate each ring and shift the sound by the gap
 * between the two first stamps - is wrong, and wrong by SECONDS. Measured
 * over a real 70-second two-lane recording (35 pieces in each ring):
 *
 *     wall clock spanned            70.014 s
 *     sound concat                  68.880 s   (-1.1 s)
 *     picture concat                43.260 s   (-26.8 s)
 *
 * Desktop capture is CHANGE-DRIVEN. A screen that is not moving emits no
 * frames, so a two-second piece of a still screen ends at its last frame and
 * carries perhaps 1.2 s of timeline. The concat demuxer lays pieces end to
 * end by their container durations, so every still moment pulls everything
 * after it earlier - against a sound ring that is locked to real time. Over
 * a ten-minute cut that is minutes of divergence, not milliseconds.
 *
 * THE CURE IS TO STOP LETTING THE CONTAINER DECIDE. Each list now carries an
 * explicit `duration` directive per piece, and the duration is the interval
 * to the NEXT piece's stamp - not the piece's own measured length, because
 * that would leave the stop-and-start seam (about 32 ms on the sound ring,
 * more on the picture ring) to accumulate. So piece k begins at exactly
 * (at_k - at_0) in its ring's timeline: every piece re-anchors to the wall
 * clock it was stamped with, and error cannot accumulate across a cut of any
 * length. `-r 25` on the output fills a still stretch by holding the frame,
 * which is the truthful picture of a screen that was not moving.
 *
 * Measured again with the directives in place, same recording:
 *
 *     picture concat 69.750 s, sound concat 69.940 s
 *
 * and, with a time code - the panel flashing white and clicking at 3 kHz in
 * the same task, so the mark is in both media with no cross-process skew -
 * read back out of a finished 20-second cut taken with a non-zero seek:
 *
 *     first mark +60 ms, last mark +60 ms  ->  drift across the cut +1 ms
 *
 * The residual is the sound landing 60-120 ms after the picture, and it does
 * not grow. Most of that is where it has to be: a piece is stamped with
 * Date.now() immediately before MediaRecorder.start(), and the picture's
 * first frame arrives up to one capture interval later (83 ms at 12 fps)
 * while the sound's first samples arrive within about 20 ms. Sound LATE
 * against picture is the forgiving direction, and 60-120 ms is inside what
 * broadcast practice allows (ITU-R BT.1359-1: up to 125 ms behind). A
 * measured correction, if one is ever wanted, goes in ALIGN_NUDGE_MS.
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
/* #1211: the ring keeps this much MORE than it offers, so the oldest piece of
 * a full-length window is not standing on the edge of its own eviction while
 * an export reads it. Two segments. */
const HOLD_GRACE_S = 4;
const HOLD_MAX_S = 3600;          /* One-hour requests; the existing byte cap still bounds disk use. */
const HOLD_MAX_BYTES = 4 * 1024 * 1024 * 1024;

/* #1205: the name the provenance carries, said the way the tablet says
 * "android-playback-mix" - what it IS, not which API produced it.
 *
 * #1207 renamed it. It said 'desk-loopback-mix' through a fortnight in which
 * nothing was ever captured, and the name was doubly false once something
 * was: this is not the machine's loopback and it is not a mix. It is the
 * station panel's own audio - the broadcast, and only the broadcast, which is
 * better than a loopback would have been, because it cannot pick up a
 * notification or whatever else the desktop is doing. Nothing outside this
 * file reads the string. */
const AUDIO_SOURCE = 'desk-broadcast-frame';

/* #1207: A SHIFT THIS LARGE MEANS A STAMP IS NOT BELIEVABLE.
 *
 * NOT a tolerance on how far out of step the sound may be. The shift is
 * measured from the two rings' own stamps and compensated EXACTLY, whatever
 * its size, so a large one is usually not an error at all: a sound ring that
 * only came up twenty seconds into a thirty-second window is twenty seconds
 * "out", and delaying it by twenty seconds puts it exactly where it belongs.
 * Refusing that would throw away ten seconds of real broadcast to avoid a
 * problem that does not exist. An earlier draft of this did precisely that.
 *
 * What cannot happen is a shift larger than the ring can hold. Both rings are
 * asked for the same absolute window and pruned to the same wall clock, so
 * the gap between their first pieces is bounded by the hold. Anything past
 * that means a stamp is wrong - the system clock moved under the recorder -
 * and then the operator's own rule applies: an audio track a second out of
 * step is more distracting than none. The cut goes out silent and says why.
 *
 * The floor keeps it sane for very short holds; the real ceiling is the hold
 * itself, computed at the cut. */
const ALIGN_MAX_MS = 10000;

/* A measured correction to put the sound ahead of where its stamps say, in
 * milliseconds. Zero, deliberately: the time-code run put the sound 60-120 ms
 * after the picture, but part of that is the probe's own paint-against-
 * schedule skew and the rest is inside broadcast tolerance, so nothing is
 * applied on a model rather than a measurement. This is where a correction
 * goes if the operator ever actually hears one. */
const ALIGN_NUDGE_MS = 0;

/* A hole in the sound shorter than this is the recorder's stop-and-start
 * seam, not a stretch of missing broadcast. Measured at about 32 ms per seam
 * on the sound ring; a quarter second is a wide margin around that. Without
 * it a thirty-second cut would report fifteen "gaps" and frighten somebody
 * about a recording that is whole. */
const GAP_MIN_MS = 250;

function nowMs() { return Date.now(); }

class ScreenRing {
  constructor() {
    this.dir = null;
    this.pieces = [];             /* {file, at, ms, bytes, w, h, a} oldest first */
    /* #1207: THE SECOND RING. The same shape, from the second recorder - the
     * audio-only capture of the panel frame. Kept apart from the picture
     * rather than merged, because the two recorders stop and start on their
     * own clocks and a merged list could not say which ring a hole was in. */
    this.sound = [];
    this.holdSeconds = HOLD_DEFAULT_S;
    /* #1211: A CUT PINS WHAT IT IS READING.
     * pins: file -> how many exports are currently reading it. doomed: files
     * the ring has already let go of but which an export still needs. */
    this.pins = new Map();
    this.doomed = new Set();
    this.doomedBytes = new Map();
    this.running = false;
    this.detail = 'not started';
    this.startedAt = 0;
    this.dropped = 0;             /* pieces aged out, for the record */
    this.soundDropped = 0;
    /* #1182d: bumped on every piece that lands, so a cut can wait for the
     * one it just asked for rather than sleeping a guessed interval. */
    this.taken = 0;
    this.fileSequence = 0;
    this.retiredDirs = new Set();
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
    this.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pinebox-screen-ring-' + process.pid + '-'));
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
        if (!/^pinebox-screen-ring-(\d+)(?:-.+)?$/.test(name)) continue;
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
      complete: given.complete !== false,
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
    /* #1207: which ring this piece belongs to. Absent means the picture, so
     * a renderer that has not been updated still fills the ring it always
     * filled rather than dropping its pieces on the floor. */
    const isSound = String(m.kind || '') === 'a';
    this.ensureDir();
    const file = path.join(this.dir,
      (isSound ? 'a' : 'p') + String(at) + '-' + (++this.fileSequence) + '.webm');
    try {
      fs.writeFileSync(file, Buffer.from(buffer));
    } catch (error) {
      this.lastError = error.message;
      return { ok: false, why: error.message };
    }
    this.taken += 1;
    /* #1205: `a` is the renderer's answer to "did THIS piece carry a live
     * audio track", asked of the stream at the moment the piece closed. A
     * piece from a recorder that lost its capture halfway through says false,
     * and the cut's coverage says so rather than the file quietly going quiet
     * in the middle. On a picture piece it is always false now (#1207): the
     * picture ring carries no sound and never claims to. */
    const piece = { file, at, ms, bytes: buffer.length,
      w: Math.round(Number(m.w) || 0), h: Math.round(Number(m.h) || 0),
      fps: Math.max(1, Math.min(240, Number(m.fps) || 60)),
      requested_fps: Math.max(1, Math.min(240, Number(m.requested_fps) || 60)),
      mime: String(m.mime || ''),
      audio_complete: m.audio_complete === undefined ? this.audioSaid.complete !== false : m.audio_complete !== false,
      a: !!m.a, view: m.view === 'pip' ? 'pip' : m.view === 'transition' ? 'transition' : 'app' };
    if (isSound) {
      this.sound.push(piece);
      this.sound.sort((a, b) => a.at - b.at);
    } else {
      this.pieces.push(piece);
      this.pieces.sort((a, b) => a.at - b.at);
      /* Only the picture decides that the ring is running and when it began.
       * A sound ring that outlived the picture must not hold the recorder
       * open on its own - there would be nothing to cut. */
      this.running = true;
      this.detail = 'recording';
      this.startedAt = this.startedAt || at;
    }
    this.prune();
    return { ok: true, held: this.heldSeconds(),
      pieces: this.pieces.length, sound: this.sound.length };
  }

  /* Old pieces go, by time first and by weight second. */
  prune() {
    const keepFrom = nowMs() - ((this.holdSeconds + HOLD_GRACE_S) * 1000);
    for (const lane of ['pieces', 'sound']) {
      while (this[lane].length > 1 && this[lane][0].at + this[lane][0].ms < keepFrom) {
        if (lane === 'pieces') this.drop(this.pieces[0]); else this.dropSound(this.sound[0]);
      }
    }
    // Audio and video share one disk budget and are evicted by oldest timestamp.
    while (this.bytes() > HOLD_MAX_BYTES && (this.pieces.length > 1 || this.sound.length > 1)) {
      const picture = this.pieces.length > 1 ? this.pieces[0] : null;
      const sound = this.sound.length > 1 ? this.sound[0] : null;
      if (picture && (!sound || picture.at <= sound.at)) this.drop(picture);
      else this.dropSound(sound);
    }
  }

  drop(piece) {
    this.pieces.shift();
    this.dropped += 1;
    this.erase(piece.file, piece.bytes);
  }

  dropSound(piece) {
    this.sound.shift();
    this.soundDropped += 1;
    this.erase(piece.file, piece.bytes);
  }

  /* #1211: the one road that removes bytes. A file an export is reading is
   * recorded as doomed and unlinked when that export lets go - the piece
   * still leaves the ring at the right moment, it is only the bytes that
   * outlive it, and only for as long as somebody is actually reading them. */
  erase(file, bytes) {
    if (this.pins.has(file)) {
      this.doomed.add(file); this.doomedBytes.set(file, Math.max(0, Number(bytes) || 0)); return;
    }
    try { fs.unlinkSync(file); } catch (e) { /* already gone */ }
  }

  /* Refcounted, not a flag: two exports may want the same piece, and the
   * second one letting go must not delete what the first is still reading. */
  pinPieces(pieces) {
    const held = [];
    for (const piece of pieces || []) {
      this.pins.set(piece.file, (this.pins.get(piece.file) || 0) + 1);
      held.push(piece.file);
    }
    return held;
  }

  releasePieces(files) {
    for (const file of files || []) {
      const left = (this.pins.get(file) || 0) - 1;
      if (left > 0) { this.pins.set(file, left); continue; }
      this.pins.delete(file);
      if (!this.doomed.has(file)) continue;
      this.doomed.delete(file);
      this.doomedBytes.delete(file);
      try { fs.unlinkSync(file); } catch (e) { /* already gone */ }
    }
    this.cleanRetiredDirs();
  }

  forget() {
    this.running = false;
    for (const p of [...this.pieces, ...this.sound]) this.erase(p.file, p.bytes);
    this.pieces = [];
    this.sound = [];
    if (this.dir) this.retiredDirs.add(this.dir);
    this.dir = null;
    this.cleanRetiredDirs();
  }

  cleanRetiredDirs() {
    for (const dir of this.retiredDirs) {
      if ([...this.pins.keys()].some(file => path.dirname(file) === dir)) continue;
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { continue; }
      this.retiredDirs.delete(dir);
    }
  }

  /* Live cache bytes. Pinned retired files temporarily outlive the budget
   * until their export finishes; they are never removed beneath a reader. */
  bytes(which) {
    let n = 0;
    const pieces = which === 'video' ? this.pieces : which === 'audio' ? this.sound : [...this.pieces, ...this.sound];
    for (const p of pieces) n += p.bytes;
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
      holds: this.holdSeconds, bytes: this.bytes(), byte_limit: HOLD_MAX_BYTES,
      // Exports may temporarily pin evicted files beyond the live-cache cap.
      pinned_retired_bytes: [...this.doomedBytes.values()].reduce((n, bytes) => n + bytes, 0),
      disk_bytes: this.bytes() + [...this.doomedBytes.values()].reduce((n, bytes) => n + bytes, 0),
      video_bytes: this.bytes('video'), audio_bytes: this.bytes('audio'),
      fps: this.pieces.at(-1)?.fps || 60, pieces: this.pieces.length,
      dropped: this.dropped, era: this.era(), where: this.dir || '',
      /* #1207: HOW MANY RINGS THIS BUILD KEEPS, and it is a handshake, not a
       * statistic.
       *
       * The renderer is reloaded whenever a file on the share changes; the
       * main process is not, and only comes up again when Pine Box is
       * restarted. So a new renderer routinely runs against an old main
       * process, and this is the pairing that goes wrong: a renderer that
       * sends sound pieces tagged `kind: 'a'` to a ring that has never heard
       * of `kind` gets every one of them filed in with the picture. That
       * happened on the live desk while this was being written - opus pieces
       * sitting in the picture list, where a cut would concat them together
       * with the video and ffmpeg would refuse the lot.
       *
       * So the renderer asks before it opens the second capture, and a build
       * that cannot answer (older main.js: `rings` is undefined) is told no.
       * The desk then films the window silently, exactly as it did before,
       * until it is restarted - which is the honest outcome and not a broken
       * ring. */
      rings: 2,
      /* #1205: the sheet asks this BEFORE it cuts, so the checkbox about
       * allowing video without complete audio is a decision made with the
       * answer in hand rather than a guess. `held_ratio` is measured over
       * the pieces on disk, not claimed by the recorder. */
      audio: { ...this.audioSaid, held_ratio: this.heldAudioRatio(),
        /* #1207: the sound ring's own count, so the sheet can tell a ring
         * that never started from one that started and went quiet. */
        pieces: this.sound.length, dropped: this.soundDropped },
      detail };
  }

  /* How much of what is HELD carries sound, 0..1. 0 with nothing held, so a
   * fresh ring reads as "no sound yet" rather than "complete".
   *
   * #1207: measured by laying the SOUND ring over the span the PICTURE ring
   * holds, because that span is what a cut can be taken out of. A sound ring
   * running beside no picture is 0, not 1: there is nothing to put it under. */
  heldAudioRatio() {
    if (!this.pieces.length) return 0;
    const last = this.pieces[this.pieces.length - 1];
    const from = this.pieces[0].at;
    const to = last.at + last.ms;
    const total = to - from;
    if (total <= 0) return 0;
    let heard = 0;
    for (const p of this.sound) {
      if (!p.a) continue;
      const start = Math.max(p.at, from);
      const end = Math.min(p.at + p.ms, to);
      if (end > start) heard += (end - start);
    }
    return Math.round(Math.min(1, heard / total) * 1000) / 1000;
  }

  /* The pieces covering `seconds` of video ending `back` seconds ago, newest
   * era only. Returns what it could actually reach, never a promise it
   * cannot keep. */
  /* #1207: `which` picks the ring - 'sound' for the second recorder's
   * pieces, anything else for the picture. Both are asked for the SAME
   * absolute window, which is what lets the cut put them on one timeline:
   * `start` and `end` come back so the caller can do that arithmetic without
   * recomputing nowMs() and getting a different answer a millisecond later. */
  window(seconds, back, which, view, interval) {
    const want = Math.max(0.2, Number(seconds) || 0);
    const behind = Math.max(0, Number(back) || 0);
    const sound = which === 'sound';
    let list = sound ? this.sound : this.pieces;
    if (!sound && view === 'pip') {
      const newest = list.findLastIndex(p => p.view === 'pip');
      if (newest < 0) return { ok: false, held: 0, detail: 'No PinePiP display is buffered yet. Open PinePiP and let the recorder fill.' };
      let oldest = newest;
      // A resize stays in the same run. A different display or capture outage does not.
      while (oldest > 0 && list[oldest - 1].view === 'pip'
          && list[oldest].at - (list[oldest - 1].at + list[oldest - 1].ms) < 1000) oldest--;
      list = list.slice(oldest, newest + 1);
    }
    const held = this.heldSeconds();
    if (!list.length) return { ok: false, held: sound ? held : 0, start: 0, end: 0,
      detail: sound ? 'the sound ring is empty' : 'the ring is empty' };
    const clock = interval?.clock ?? nowMs();
    // Freeze the selected window before flush/encoding. A missing tail shortens
    // the cut rather than moving its start into an earlier part of the mix.
    const requestedEnd = clock - behind * 1000;
    const end = interval?.end ?? (interval?.clock != null ? requestedEnd
      : Math.min(requestedEnd, list.at(-1).at + list.at(-1).ms));
    const start = interval?.start ?? end - want * 1000;
    const used = list.filter(p => p.at + p.ms > start && p.at < end);
    if (!used.length) return { ok: false, held, clamped: false, start, end, clock,
      detail: sound ? 'nothing in the sound ring covers that window' : 'nothing in the ring covers that window' };
    const actualStart = Math.max(start, used[0].at);
    const actualEnd = Math.min(end, used.at(-1).at + used.at(-1).ms);
    return { ok: true, pieces: used, held, clock, start: actualStart, end: actualEnd,
      clamped: actualStart > start + 1 || actualEnd < end - 1,
      from: Math.round((clock - actualStart) / 100) / 10,
      to: Math.round(Math.max(0, clock - actualEnd) / 100) / 10,
      offset: Math.max(0, (actualStart - used[0].at) / 1000),
      seconds: Math.max(0, (actualEnd - actualStart) / 1000),
      w: Math.max(...used.map(p => p.w)), h: Math.max(...used.map(p => p.h)),
      fps: Math.max(...used.map(p => p.fps || 60)) };
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
  /* #1207: MEASURED OVER THE SOUND RING, AGAINST THE PICTURE'S OWN WINDOW.
   *
   * `shot` is the picture window the cut is really using and `heard` is the
   * sound window for the same absolute seconds. Coverage is the fraction of
   * the picture's span that the sound ring actually holds - overlap by the
   * clock, not a count of pieces, because the two rings' pieces do not share
   * boundaries and never will.
   *
   * `shift` is how far the sound has to be moved to sit under the picture,
   * and it is REPORTED rather than hidden: an operator who hears something
   * odd should be able to read what was done to the sound. */
  soundFor(shot, videoOnly, heard, shift) {
    const said = this.audioSaid || {};
    const holds = (heard && heard.ok && heard.pieces) ? heard.pieces : [];
    const audio = { source: said.source || AUDIO_SOURCE, present: false, complete: false,
      state: 'unavailable', detail: '', coverage_ratio: 0,
      covered_seconds: 0, window_seconds: 0, gaps: 0, gap_seconds: 0,
      pieces: holds.length, pieces_with_audio: 0,
      video_only_explicit: !!videoOnly, platform: process.platform,
      supported: said.supported === undefined ? null : said.supported,
      align_shift_ms: null, align_bound_ms: null };
    if (videoOnly) {
      audio.detail = 'video only, as asked';
      return audio;
    }
    /* The span the cut will really cover, in absolute ms: where the picture
     * begins and how long of it there is. */
    const shotPieces = (shot && shot.pieces) || [];
    if (!shotPieces.length) {
      audio.detail = 'there is no picture to put sound under';
      return audio;
    }
    const from = Math.max(shot.start, shotPieces[0].at);
    const to = from + (shot.seconds * 1000);
    audio.window_seconds = Math.round(((to - from) / 1000) * 10) / 10;
    if (!holds.length) {
      audio.detail = said.detail || (said.supported === false
        ? 'the panel has no sound to capture on this surface, so the '
          + 'recording is silent'
        : 'the sound ring held nothing for that window');
      return audio;
    }
    /* #1207: a shift larger than the ring can hold is not a late start, it is
     * a broken stamp. Better a silent cut that says so than a track laid down
     * on a timeline that cannot be true. Anything short of that is
     * compensated exactly, however large it looks. */
    const ceiling = Math.max(ALIGN_MAX_MS, (this.holdSeconds * 1000) + SEGMENT_MS);
    if (shift === null || !Number.isFinite(shift) || Math.abs(shift) > ceiling) {
      audio.detail = 'the two rings are ' + Math.round(Math.abs(Number(shift) || 0))
        + ' ms apart, which is further than the ring can hold, so a stamp is '
        + 'wrong and the sound was left out rather than laid down out of step';
      return audio;
    }
    audio.align_shift_ms = Math.round(shift);
    /* What is left after the shift: the two recorders are stamped on the same
     * clock in the same thread, so what remains is the difference between how
     * long each one takes to produce its first sample - bounded by one
     * capture interval of the picture. */
    audio.align_bound_ms = Math.round(1000 / (shot.fps || 60));
    /* Overlap by the clock. Only pieces the recorder said carried a live
     * track count; one that was recorded off a dead capture is a hole. */
    const spans = [];
    for (const p of holds) {
      if (!p.a) continue;
      const start = Math.max(p.at, from);
      const end = Math.min(p.at + p.ms, to);
      if (end > start) { spans.push([start, end]); audio.pieces_with_audio += 1; }
    }
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const span of spans) {
      const last = merged[merged.length - 1];
      if (last && span[0] <= last[1] + GAP_MIN_MS) {
        last[1] = Math.max(last[1], span[1]);
      } else { merged.push([span[0], span[1]]); }
    }
    let covered = 0;
    for (const span of merged) covered += (span[1] - span[0]);
    /* Holes worth naming: the head, the tail, and anything between the merged
     * runs. The merge above has already swallowed the recorder's own seams. */
    let gaps = 0;
    let missed = 0;
    let edge = from;
    for (const span of merged) {
      if (span[0] - edge >= GAP_MIN_MS) { gaps += 1; missed += (span[0] - edge); }
      edge = Math.max(edge, span[1]);
    }
    if (to - edge >= GAP_MIN_MS) { gaps += 1; missed += (to - edge); }
    const total = Math.max(1, to - from);
    audio.covered_seconds = Math.round((covered / 1000) * 10) / 10;
    audio.gap_seconds = Math.round((missed / 1000) * 10) / 10;
    audio.gaps = gaps;
    audio.coverage_ratio = Math.round(Math.min(1, covered / total) * 1000) / 1000;
    if (!covered) {
      audio.detail = said.detail || 'the sound ring held nothing for that window';
      return audio;
    }
    audio.present = true;
    const contentIncomplete = holds.some(p => p.a && p.audio_complete === false
      && p.at + p.ms > from && p.at < to);
    audio.complete = !gaps && !contentIncomplete;
    audio.state = audio.complete ? 'captured' : 'partial';
    audio.application_audio_complete = !contentIncomplete;
    audio.detail = gaps
      ? ('the broadcast, with ' + gaps + (gaps === 1 ? ' gap' : ' gaps')
         + ' totalling ' + audio.gap_seconds.toFixed(1) + 's')
      : contentIncomplete ? (said.detail || 'Only part of the application audio was captured; shell music and effects may be missing.')
        : 'the captured application audio, laid under the picture';
    return audio;
  }

  /* --------------------------------------------------------------- cuts */

  /* #1207: EVERY PIECE CARRIES THE WALL CLOCK IT WAS STAMPED WITH.
   *
   * Without the `duration` directives the concat demuxer lays pieces end to
   * end by their container lengths, and a picture piece of a still screen is
   * shorter than the time it covers - measured at 43.26 s of timeline for
   * 70.01 s of recording, because desktop capture emits no frames while
   * nothing moves. Sound cannot be laid under a timeline like that.
   *
   * The duration written is the interval to the NEXT piece's stamp, not the
   * piece's own measured length: that puts piece k at exactly (at_k - at_0)
   * and leaves the stop-and-start seam out of the arithmetic entirely, so it
   * cannot accumulate over a ten-minute cut. The last piece has no next, so
   * it declares what it measured. */
  listFile(dir, pieces, name, endAt) {
    const here = pieces.filter(piece => fs.existsSync(piece.file));
    const lines = [];
    for (let i = 0; i < here.length; i += 1) {
      const p = here[i];
      lines.push("file '" + p.file.replace(/\\/g, '/').replace(/'/g, "'\\''") + "'");
      // inpoint=0 preserves the file's first-sample offset. Without it concat
      // subtracts each WebM start_time and silently pulls the first sample early.
      lines.push('inpoint 0');
      const next = (i + 1 < here.length) ? here[i + 1].at : (endAt ?? p.at + p.ms);
      lines.push('duration ' + (Math.max(1, next - p.at) / 1000).toFixed(6));
    }
    const list = path.join(dir, name || 'pieces.txt');
    fs.writeFileSync(list, lines.join('\n') + '\n', 'utf8');
    return { path: list, missing: pieces.length - here.length, count: here.length,
      pieces: here, origin: here[0]?.at ?? null };
  }

  /* Preserve sample timestamps when shifting to the single absolute cut
   * start. PTS-STARTPTS here loses the first decoded sample's offset after
   * a nonzero seek, and repeats that error after every recorder seam. */
  soundFilter(shift, input = 1, seconds) {
    const ms = Number(shift) - ALIGN_NUDGE_MS;
    const bits = ['asetpts=PTS-(' + (ms / 1000).toFixed(6) + ')/TB',
      'aresample=48000:async=1:min_hard_comp=0.001:first_pts=0'];
    if (Number(seconds) > 0) bits.push('apad=whole_dur=' + seconds.toFixed(6), 'atrim=duration=' + seconds.toFixed(6));
    return '[' + input + ':a]' + bits.join(',') + '[pinesound]';
  }

  /* Separate geometry runs so a resize never reinitializes a running filter
   * and drops buffered frames. All runs share one native-sized padded canvas. */
  videoInputs(dir, got, prefix = 'pieces') {
    const runs = [];
    for (const piece of got.pieces) {
      let run = runs.at(-1);
      if (!run || piece.w !== run.w || piece.h !== run.h || piece.mime !== run.mime) {
        run = { pieces: [], w: piece.w, h: piece.h, mime: piece.mime }; runs.push(run);
      }
      run.pieces.push(piece);
    }
    const width = Math.ceil(Math.max(2, got.w) / 2) * 2;
    const height = Math.ceil(Math.max(2, got.h) / 2) * 2;
    const inputs = [], filters = [];
    for (let i = 0; i < runs.length; i++) {
      const run = runs[i];
      const start = Math.max(got.start, run.pieces[0].at);
      const end = i + 1 < runs.length ? Math.min(got.end, runs[i + 1].pieces[0].at) : got.end;
      const duration = Math.max(0.001, (end - start) / 1000);
      const listed = this.listFile(dir, run.pieces, prefix + (i ? '-' + i : '') + '.txt', end);
      if (!listed.count) throw new Error('The picture for this part of the window is no longer buffered.');
      const seek = Math.max(0, (start - listed.origin) / 1000);
      inputs.push('-f', 'concat', '-safe', '0', '-i', listed.path);
      filters.push('[' + i + ':v]trim=start=' + seek.toFixed(6)
        + ',setpts=PTS-(' + seek.toFixed(6) + ')/TB'
        + ',fps=' + got.fps + ':start_time=0:round=near'
        + ',pad=' + width + ':' + height + ':0:0:color=black,setsar=1'
        + ',tpad=stop_mode=clone:stop_duration=' + duration.toFixed(6)
        + ',trim=duration=' + duration.toFixed(6) + ',setpts=PTS-STARTPTS[v' + i + ']');
    }
    filters.push(runs.length > 1
      ? runs.map((_, i) => '[v' + i + ']').join('') + 'concat=n=' + runs.length + ':v=1:a=0[pinevideo]'
      : '[v0]null[pinevideo]');
    return { inputs, filters, count: runs.length, width, height };
  }

  async cutAudio(want, options) {
    const interval = Number.isFinite(want.end_at) && want.end_at > 0 ? { clock: want.end_at } : undefined;
    const got = this.window(want.seconds, want.back, 'sound', undefined, interval);
    if (!got.ok) return { ok: false, detail: got.detail, held: got.held };
    const audio = this.soundFor(got, false, got, 0);
    if (!audio.present || !audio.complete) return { ok: false, detail: audio.detail || 'The broadcast buffer has gaps.', audio, held: got.held };
    const held = this.pinPieces(got.pieces), dir = clipMux.stash();
    try {
      const listed = this.listFile(dir, got.pieces, 'sound.txt', got.end);
      if (!listed.count || listed.missing) throw new Error('Some broadcast audio is no longer in the buffer.');
      const out = path.join(dir, 'broadcast.wav');
      await clipMux.run(clipMux.findFfmpeg(options?.ffmpeg).path, ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', listed.path,
        '-filter_complex', this.soundFilter(got.start - listed.origin, 0, got.seconds), '-map', '[pinesound]',
        '-t', got.seconds.toFixed(6), '-vn', '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', out], 600000);
      return { ok: true, out, dir, bytes: fs.statSync(out).size, seconds: Math.round(got.seconds * 10) / 10,
        asked: want.seconds, held: got.held, clamped: got.clamped, audio };
    } catch (error) { clipMux.forget(dir); return { ok: false, detail: error.message, held: got.held }; }
    finally { this.releasePieces(held); }
  }

  async cut(want, options) {
    const opts = options || {};
    const interval = Number.isFinite(want.end_at) && want.end_at > 0 ? { clock: want.end_at } : undefined;
    let got = this.window(want.seconds, want.back, undefined, want.view, interval);
    if (!got.ok) return { ok: false, detail: got.detail, held: got.held };
    // Snapshot and pin synchronously before any probe/transcode awaits.
    const heard = want.video_only ? null : this.window(got.seconds, 0, 'sound', undefined, got);
    const held = this.pinPieces(got.pieces).concat(heard?.ok ? this.pinPieces(heard.pieces) : []);
    const dir = clipMux.stash();
    let audio;
    try {
      const surviving = got.pieces.filter(p => fs.existsSync(p.file));
      if (!surviving.length) throw new Error('Every picture piece of that window has already been swept.');
      if (surviving.length !== got.pieces.length) {
        got = { ...got, pieces: surviving, start: Math.max(got.start, surviving[0].at), clamped: true };
        got.seconds = Math.max(0, (got.end - got.start) / 1000);
        got.offset = (got.start - surviving[0].at) / 1000;
        got.from = Math.round((got.clock - got.start) / 100) / 10;
      }
      const soundCut = heard?.ok ? this.listFile(dir, heard.pieces.filter(p => p.a), 'sound.txt', got.end) : null;
      const availableSound = soundCut?.count ? { ...heard, pieces: soundCut.pieces } : null;
      const shift = availableSound ? surviving[0].at - soundCut.origin : null;
      audio = this.soundFor(got, want.video_only, availableSound, shift);
      if (soundCut?.missing) audio.pieces_missing = soundCut.missing;
      const video = this.videoInputs(dir, got);
      if (process.platform === 'win32' && video.inputs.reduce((n, arg) => n + arg.length + 3, 0) > 24000) {
        throw new Error('This window has too many resize or codec transitions for one Windows export. Choose a shorter window; the recording remains buffered.');
      }
      const out = want.out || path.join(dir, 'screen.mp4');
      const filterGraph = video.filters.concat(audio.present
        ? [this.soundFilter(got.start - soundCut.origin, video.count, got.seconds)] : []).join(';');
      let graphArgs = ['-filter_complex', filterGraph];
      if (filterGraph.length > 4000) {
        const graphFile = path.join(dir, 'filters.txt');
        fs.writeFileSync(graphFile, filterGraph, 'utf8');
        graphArgs = ['-filter_complex_script', graphFile];
      }
      const build = encoder => ['-hide_banner', '-nostdin', '-y', ...video.inputs,
        ...(audio.present ? ['-f', 'concat', '-safe', '0', '-i', soundCut.path] : []),
        ...graphArgs,
        '-map', '[pinevideo]', ...(audio.present ? ['-map', '[pinesound]'] : []),
        '-t', got.seconds.toFixed(6),
        ...(audio.present ? ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2'] : ['-an']),
        ...clipMux.encoderArgs(encoder), '-pix_fmt', 'yuv420p', '-r', String(got.fps),
        '-fps_mode', 'cfr', '-movflags', '+faststart', out];
      const total = Math.max(.1, Number(got.seconds) || 0);   /* [pip-export-bar] seconds written so far, as a share of this cut */
      const encoding = await clipMux.encodeVideo(clipMux.findFfmpeg(opts.ffmpeg).path, build,
        { ...opts, onProgress: typeof opts.onProgress === 'function' ? seconds => opts.onProgress(Math.min(1, Math.max(0, seconds) / total)) : undefined,
          timeoutMs: opts.timeoutMs || Math.max(600000, Math.ceil(got.seconds * 6000 + 120000)) });
      const bytes = fs.statSync(out).size;
      if (!bytes) throw new Error('The encoder finished without writing a playable recording.');
      return { ok: true, out, bytes, seconds: Math.round(got.seconds * 10) / 10,
        asked: Number(want.seconds) || 0, held: got.held, clamped: got.clamped,
        from: got.from, to: got.to, dir, audio, w: video.width, h: video.height, fps: got.fps,
        video: { fps: got.fps, width: video.width, height: video.height, ...encoding,
          source: 'native-window-capture', pixel_scale: 1 } };
    } catch (error) {
      clipMux.forget(dir);
      return { ok: false, detail: error.message, held: got.held, audio };
    } finally { this.releasePieces(held); }
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
    const interval = Number.isFinite(want.end_at) && want.end_at > 0 ? { clock: want.end_at } : undefined;
    const got = this.window(seconds, back, undefined, want.view, interval);
    if (!got.ok) return { ok: false, held: got.held, detail: got.detail };
    const dir = clipMux.stash();
    /* #1214: EVERY READER OF THE RING PINS WHAT IT IS READING.
     *
     * #1211 pinned the pieces a cut reads and left this road alone, and the
     * operator hit the identical "Impossible to open ... No such file or
     * directory" again from a desk running that fix. The strip is built the
     * moment the sheet opens, so this is the reader he meets FIRST - and it
     * ran its own ffmpeg over the same pieces while the ring went on dropping
     * one every two seconds underneath it. */
    const held = this.pinPieces(got.pieces);
    try {
      const video = this.videoInputs(dir, got);
      const span = Math.max(0.2, got.seconds);
      const fps = count / span;
      const sample = 0.5 / Math.max(fps, 0.01);
      const filters = video.filters.concat('[pinevideo]trim=start=' + sample.toFixed(6)
        + ',setpts=PTS-STARTPTS,fps=' + fps.toFixed(5)
        + ',scale=' + edge + ':-2:flags=bicubic[thumbs]');
      const args = ['-hide_banner', '-nostdin', '-y', ...video.inputs,
        '-filter_complex', filters.join(';'), '-map', '[thumbs]', '-t', span.toFixed(6),
        '-an', '-frames:v', String(count), '-q:v', '4', path.join(dir, 'f%03d.jpg')];
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
      this.releasePieces(held);                                  /* #1214 */
      clipMux.forget(dir);
    }
  }
}

module.exports = { ScreenRing, SEGMENT_MS, HOLD_DEFAULT_S, HOLD_MIN_S, HOLD_MAX_S,
  HOLD_MAX_BYTES, AUDIO_SOURCE, ALIGN_MAX_MS, ALIGN_NUDGE_MS, GAP_MIN_MS };
