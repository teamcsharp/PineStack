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
const HOLD_MAX_S = 600;           /* ten minutes */
const HOLD_MAX_BYTES = 900 * 1024 * 1024;

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
    this.running = false;
    this.detail = 'not started';
    this.startedAt = 0;
    this.dropped = 0;             /* pieces aged out, for the record */
    this.soundDropped = 0;
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
    /* #1207: which ring this piece belongs to. Absent means the picture, so
     * a renderer that has not been updated still fills the ring it always
     * filled rather than dropping its pieces on the floor. */
    const isSound = String(m.kind || '') === 'a';
    this.ensureDir();
    const file = path.join(this.dir,
      (isSound ? 'a' : 'p') + String(at) + '.webm');
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
      a: !!m.a };
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
    const keepFrom = nowMs()
      - ((this.holdSeconds + HOLD_GRACE_S) * 1000);          /* #1211 */
    while (this.pieces.length > 1) {
      const first = this.pieces[0];
      if (first.at + first.ms >= keepFrom) break;
      this.drop(first);
    }
    while (this.pieces.length > 1 && this.bytes() > HOLD_MAX_BYTES) {
      this.drop(this.pieces[0]);
    }
    /* #1207: the sound ring is pruned to the same wall clock, on its own, so
     * neither ring can hold the other's pieces alive. It is not weighed: a
     * second of opus is about 16 kB against a second of picture at 200 kB,
     * so the byte ceiling that matters is the picture's. */
    while (this.sound.length > 1) {
      const first = this.sound[0];
      if (first.at + first.ms >= keepFrom) break;
      this.dropSound(first);
    }
  }

  drop(piece) {
    this.pieces.shift();
    this.dropped += 1;
    this.erase(piece.file);
  }

  dropSound(piece) {
    this.sound.shift();
    this.soundDropped += 1;
    this.erase(piece.file);
  }

  /* #1211: the one road that removes bytes. A file an export is reading is
   * recorded as doomed and unlinked when that export lets go - the piece
   * still leaves the ring at the right moment, it is only the bytes that
   * outlive it, and only for as long as somebody is actually reading them. */
  erase(file) {
    if (this.pins.has(file)) { this.doomed.add(file); return; }
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
      try { fs.unlinkSync(file); } catch (e) { /* already gone */ }
    }
  }

  forget() {
    this.running = false;
    for (const p of this.pieces) { try { fs.unlinkSync(p.file); } catch (e) {} }
    for (const p of this.sound) { try { fs.unlinkSync(p.file); } catch (e) {} }
    this.pieces = [];
    this.sound = [];
    this.pins.clear();                                          /* #1211 */
    this.doomed.clear();
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
  window(seconds, back, which) {
    const want = Math.max(0.2, Number(seconds) || 0);
    const behind = Math.max(0, Number(back) || 0);
    const sound = which === 'sound';
    const list = sound ? this.sound : this.pieces;
    const held = this.heldSeconds();
    if (!list.length) {
      return { ok: false, held: sound ? held : 0, start: 0, end: 0,
        detail: sound ? 'the sound ring is empty' : 'the ring is empty' };
    }
    const end = nowMs() - (behind * 1000);
    const start = end - (want * 1000);
    /* The era is the picture's problem alone: it exists because the concat
     * demuxer refuses pieces whose codec parameters disagree and the window
     * is resizable. Opus at 48 kHz does not change shape when a window is
     * dragged, so the sound ring has no eras to keep apart. */
    const era = sound ? { w: 0, h: 0 } : this.era();
    const used = [];
    let clamped = false;
    for (const p of list) {
      if (p.at + p.ms <= start) continue;
      if (p.at >= end) continue;
      if (era.w && p.w && (p.w !== era.w || p.h !== era.h)) { clamped = true; continue; }
      used.push(p);
    }
    if (!used.length) {
      return { ok: false, held, clamped, start, end,
        detail: sound ? 'nothing in the sound ring covers that window'
          : 'nothing in the ring covers that window' };
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
    return { ok: true, pieces: used, held, clamped, start, end,
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
    const audio = { source: AUDIO_SOURCE, present: false, complete: false,
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
    audio.align_bound_ms = Math.round(1000 / 12);
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
    audio.complete = !gaps;
    audio.state = gaps ? 'partial' : 'captured';
    audio.detail = gaps
      ? ('the broadcast, with ' + gaps + (gaps === 1 ? ' gap' : ' gaps')
         + ' totalling ' + audio.gap_seconds.toFixed(1) + 's')
      : 'the broadcast, from the panel, laid under the picture';
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
  listFile(dir, pieces, name) {
    /* #1211: NEVER NAME A FILE THAT IS NOT THERE. One stale name fails the
     * whole concat, which costs the operator the entire recording instead of
     * the single moment that went missing. The durations are worked out AFTER
     * this filter, so every surviving piece still begins at exactly
     * (at_k - at_0) and the piece before a hole holds its last frame across
     * it - a freeze over the gap, rather than everything after it sliding
     * early. */
    const here = [];
    let missing = 0;
    for (const piece of pieces) {
      let there = false;
      try { there = fs.existsSync(piece.file); } catch (e) { there = false; }
      if (there) here.push(piece); else missing += 1;
    }
    const lines = [];
    for (let i = 0; i < here.length; i += 1) {
      const p = here[i];
      lines.push("file '" + p.file.replace(/\\/g, '/').replace(/'/g, "'\\''") + "'");
      const next = (i + 1 < here.length) ? (here[i + 1].at - p.at) : p.ms;
      lines.push('duration ' + (Math.max(1, next) / 1000).toFixed(3));
    }
    const list = path.join(dir, name || 'pieces.txt');
    fs.writeFileSync(list, lines.join('\n') + '\n', 'utf8');
    return { path: list, missing, count: here.length };
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
  /* #1207: HOW THE SOUND IS PUT ON THE PICTURE'S TIMELINE.
   *
   * Both lists are already anchored to the wall clock by their `duration`
   * directives, so input 0 at time t is absolute (vfirst.at + t) and input 1
   * at time t is absolute (afirst.at + t). One shift puts them together:
   *
   *   shift = vfirst.at - afirst.at
   *
   *   shift > 0  the sound ring began first, so drop `shift` off its front.
   *              atrim leaves the original timestamps behind it, which is why
   *              asetpts follows and not the other way round.
   *   shift < 0  the sound ring began later, so hold it back by that much.
   *              Here asetpts must come FIRST: asetpts=PTS-STARTPTS after an
   *              adelay would reset the delay it had just applied, silently,
   *              and the sound would be early by exactly the amount it was
   *              supposed to be late.
   *
   * aresample=async=1:first_pts=0 closes the arithmetic: it pads the front
   * with real silence so the stream begins at zero, and it fills the seams
   * between pieces rather than pulling everything after a seam earlier. */
  soundFilter(shift) {
    const bits = [];
    const ms = Math.round(shift) - ALIGN_NUDGE_MS;
    if (ms > 0) {
      bits.push('atrim=start=' + (ms / 1000).toFixed(3));
      bits.push('asetpts=PTS-STARTPTS');
    } else if (ms < 0) {
      bits.push('asetpts=PTS-STARTPTS');
      bits.push('adelay=' + Math.abs(ms) + ':all=1');
    } else {
      bits.push('asetpts=PTS-STARTPTS');
    }
    bits.push('aresample=async=1:first_pts=0');
    return '[1:a]' + bits.join(',') + '[pinesound]';
  }

  async cut(want, options) {
    const opts = options || {};
    const got = this.window(want.seconds, want.back);
    /* THE PICTURE DECIDES WHETHER THERE IS A CUT AT ALL. A sound ring with no
     * picture behind it produces nothing - a black rectangle with a broadcast
     * on it is not a screen recording, and nobody asked for one. */
    if (!got.ok) return { ok: false, detail: got.detail, held: got.held };
    /* And the sound is entirely optional: every road below this line still
     * lands a silent recording if the second ring is empty, dead, or was
     * never started. */
    const heard = want.video_only ? null : this.window(want.seconds, want.back, 'sound');
    const shift = (heard && heard.ok && heard.pieces.length && got.pieces.length)
      ? (got.pieces[0].at - heard.pieces[0].at) : null;
    const dir = clipMux.stash();
    const audio = this.soundFor(got, want.video_only, heard, shift);
    /* #1211: hold the bytes for as long as ffmpeg is reading them. This is
     * the cure for the operator's "Impossible to open ... No such file or
     * directory": the ring goes on recording throughout the encode, and
     * without this the oldest piece in the list is unlinked mid-read. */
    const held = this.pinPieces(got.pieces)
      .concat(audio.present && heard ? this.pinPieces(heard.pieces) : []);
    try {
      const shown = this.listFile(dir, got.pieces);
      const list = shown.path;
      if (!shown.count) {
        throw new Error('every piece of that window had already been swept');
      }
      if (shown.missing) {
        audio.pieces_missing = shown.missing;
      }
      const soundCut = (audio.present && heard)
        ? this.listFile(dir, heard.pieces, 'sound.txt') : null;
      const soundList = soundCut ? soundCut.path : '';
      if (soundCut && !soundCut.count) {
        audio.present = false;
        audio.state = 'unavailable';
        audio.detail = 'the sound for that window had already been swept';
      }
      const out = want.out || path.join(dir, 'screen.mp4');
      const build = (withSound) => ['-hide_banner', '-nostdin', '-y',
        '-f', 'concat', '-safe', '0', '-i', list,
        ...(withSound ? ['-f', 'concat', '-safe', '0', '-i', soundList] : []),
        ...(withSound
          ? ['-filter_complex', this.soundFilter(audio.align_shift_ms),
             '-map', '0:v:0', '-map', '[pinesound]']
          : []),
        '-ss', got.offset.toFixed(3), '-t', got.seconds.toFixed(3),
        ...(withSound
          ? ['-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2']
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
    } finally {
      this.releasePieces(held);                                 /* #1211 */
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
      const shown = this.listFile(dir, got.pieces);
      const list = shown.path;
      if (!shown.count) {
        throw new Error('every piece of that window had already been swept');
      }
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
        /* #1205: said out loud so no decoder time is spent on a track that
         * cannot reach a JPEG. #1207: the picture ring has no audio track at
         * all now - the sound is a second ring and this never opens it - so
         * this is belt and braces rather than the thing that strips it. */
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
      this.releasePieces(held);                                  /* #1214 */
      clipMux.forget(dir);
    }
  }
}

module.exports = { ScreenRing, SEGMENT_MS, HOLD_DEFAULT_S, HOLD_MIN_S, HOLD_MAX_S,
  HOLD_MAX_BYTES, AUDIO_SOURCE, ALIGN_MAX_MS, ALIGN_NUDGE_MS, GAP_MIN_MS };
