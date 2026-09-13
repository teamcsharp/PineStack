/* CHOOSING WHAT GETS EXPORTED.
 *
 * "Offer a popup where I choose what channels are used for the export and if
 *  the channels are mixed into mono and if I need to gain one of the
 *  channels."
 * "Also when extracting a video allow me to set the in and out points."
 *
 * THE PREVIEW IS THE POINT, not decoration. A gain control with no way to
 * hear it is a number you guess at, export, listen to, and come back to - so
 * the preview plays the video with EXACTLY the mix the export will have:
 * the same channels, the same gains, the same mono decision, the same in and
 * out points. What you hear is what ffmpeg is told to make.
 *
 * The video element is kept muted throughout and every sound comes from Web
 * Audio, because the recording has no audio track of its own and the two
 * WAVs have to be placed against the picture by hand anyway - the tablet's
 * ear starts before the camera does, on purpose.
 */
'use strict';

const api = window.pineDesktop || {};
const film = document.getElementById('film');
const track = document.getElementById('track');
const band = document.getElementById('band');
const inMark = document.getElementById('inMark');
const outMark = document.getElementById('outMark');
const head = document.getElementById('head');

let clip = null;            /* what the recorder brought back */
let duration = 0;
let inAt = 0;
let outAt = 0;
/* MONO BY DEFAULT.
 *
 * "Also automatically mix clips to mono."
 *
 * The two sources are a mono broadcast ring and a mono microphone, so
 * "stereo" here never meant a stereo image - it meant the two kept apart,
 * one in each ear, which is useful for pulling them back out later and
 * strange to listen to. Mono is what these clips are for: showing someone
 * what happened. The toggle is still there for when separation is wanted. */
let mono = true;
let busy = false;

/* One decoded buffer per channel, kept for the preview and the waveforms. */
const tracks = {
  broadcast: { buffer: null, offset: 0, db: 0, use: true, there: false },
  mic: { buffer: null, offset: 0, db: 0, use: true, there: false }
};

let context = null;
let voices = [];
let playing = false;
let raf = 0;

function say(text, kind) {
  const note = document.getElementById('note');
  note.textContent = text || '';
  note.classList.toggle('err', kind === 'bad');
  note.classList.toggle('good', kind === 'good');
}

function clock(seconds) {
  const whole = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(whole / 60);
  const s = whole - m * 60;
  return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
}

/* ------------------------------------------------------------------ trim */

function paintTrim() {
  if (!duration) return;
  const left = (inAt / duration) * 100;
  const right = (outAt / duration) * 100;
  band.style.left = left + '%';
  band.style.width = Math.max(0, right - left) + '%';
  inMark.style.left = left + '%';
  outMark.style.left = right + '%';
  document.getElementById('trimSaid').textContent =
    'in ' + clock(inAt) + '   out ' + clock(outAt)
    + '   — ' + (outAt - inAt).toFixed(2) + 's of ' + duration.toFixed(2) + 's';
}

function paintHead(at) {
  if (!duration) return;
  const when = at == null ? film.currentTime : at;
  head.style.left = ((when / duration) * 100) + '%';
  const said = document.getElementById('headSaid');
  if (said) said.textContent = clock(when);
}

/* SCRUBBING WITHOUT QUEUEING SEEKS.
 *
 * Assigning `currentTime` faster than the decoder can answer does not queue -
 * Chromium drops the positions in between - so during a drag the picture
 * lands on whichever seek happened to finish and then sits there, which reads
 * as the display not updating at all. The latest wanted position is kept and
 * re-applied when the outstanding seek lands, so the picture chases the
 * handle and always ends where the handle stopped. */
let wantAt = null;
let seeking = false;

function showAt(when) {
  if (!duration) return;
  wantAt = Math.min(Math.max(0, when), duration);
  paintHead(wantAt);
  if (seeking) return;
  seeking = true;
  film.currentTime = wantAt;
}

film.addEventListener('seeked', () => {
  seeking = false;
  if (wantAt != null && Math.abs(film.currentTime - wantAt) > 0.02) {
    seeking = true;
    film.currentTime = wantAt;
    return;
  }
  wantAt = null;
  paintHead();
});

function timeAt(event) {
  const box = track.getBoundingClientRect();
  const across = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
  return across * duration;
}

let dragging = null;

for (const mark of [inMark, outMark]) {
  mark.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
    dragging = mark.dataset.edge;
    try { mark.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
  });
  mark.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    moveEdge(dragging, timeAt(event));
  });
  const done = () => { dragging = null; };
  mark.addEventListener('pointerup', done);
  mark.addEventListener('pointercancel', done);
}

function moveEdge(edge, when) {
  /* A tenth of a second of daylight between them: an out point at or before
   * the in point is not a short clip, it is a broken command line. */
  if (edge === 'in') inAt = Math.min(Math.max(0, when), outAt - 0.1);
  else outAt = Math.max(Math.min(duration, when), inAt + 0.1);
  paintTrim();
  if (playing) stop();
  /* THE FRAME THE HANDLE IS ON, both handles. The out point used to show
   * `outAt - 0.4` - meant as "the last bit you keep" and in practice a
   * picture of somewhere other than the cut being made. */
  showAt(edge === 'in' ? inAt : outAt);
}

/* Clicking the strip scrubs; it does not move a handle. Handles are dragged,
 * which is the only way to have both on one strip without every scrub
 * nudging whichever edge was nearest. */
track.addEventListener('pointerdown', (event) => {
  if (dragging) return;
  const when = timeAt(event);
  if (playing) stop('scrubbed');
  showAt(when);
});

/* Dragging across the strip scrubs too - pointer capture keeps it coming
 * once the finger has left the track. */
track.addEventListener('pointermove', (event) => {
  if (dragging || !(event.buttons & 1)) return;
  showAt(timeAt(event));
});
track.addEventListener('pointerdown', (event) => {
  try { track.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
});

document.getElementById('setIn').addEventListener('click',
  () => moveEdge('in', film.currentTime));
document.getElementById('setOut').addEventListener('click',
  () => moveEdge('out', film.currentTime));
document.getElementById('resetTrim').addEventListener('click', () => {
  inAt = 0;
  outAt = duration;
  paintTrim();
});

/* --------------------------------------------------------------- channels */

function row(name) { return document.querySelector('.trk[data-track="' + name + '"]'); }

function paintTrack(name) {
  const node = row(name);
  const state = tracks[name];
  node.classList.toggle('off', !state.use);
  node.classList.toggle('missing', !state.there);
  node.querySelector('.use').checked = state.use && state.there;
  node.querySelector('.use').disabled = !state.there;
  node.querySelector('.db').value = String(state.db);
  node.querySelector('.dbSaid').textContent =
    (state.db > 0 ? '+' : '') + state.db + ' dB';
}

for (const name of ['broadcast', 'mic']) {
  const node = row(name);
  node.querySelector('.use').addEventListener('change', (event) => {
    tracks[name].use = !!event.target.checked;
    paintTrack(name);
    paintMono();
    if (playing) restart();
  });
  node.querySelector('.db').addEventListener('input', (event) => {
    tracks[name].db = Number(event.target.value) || 0;
    paintTrack(name);
    /* Live, while it plays - the whole reason the preview exists. */
    if (playing) applyGains();
  });
}

document.getElementById('monoBtn').addEventListener('click', () => {
  mono = !mono;
  paintMono();
  if (playing) restart();
});

function paintMono() {
  const button = document.getElementById('monoBtn');
  const both = tracks.broadcast.use && tracks.broadcast.there
    && tracks.mic.use && tracks.mic.there;
  button.classList.toggle('on', mono);
  /* With one channel there is nothing to mix, and a live toggle that does
   * nothing is a question about whether it is broken. */
  button.disabled = !both;
  button.title = both
    ? 'Sum both channels into one. Off keeps them apart — broadcast left, '
      + 'microphone right — so they can be separated again later.'
    : 'Only meaningful with both channels in';
}

/* The shape of the sound, so a silent take is visible before it is exported
 * rather than discovered afterwards. */
function paintWave(name) {
  const node = row(name);
  const canvas = node.querySelector('.wave');
  const ctx = canvas.getContext('2d');
  const width = canvas.width, height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  const buffer = tracks[name].buffer;
  if (!buffer) {
    ctx.fillStyle = '#4a5b68';
    ctx.font = '11px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('nothing captured', 8, height / 2 + 4);
    return;
  }
  const data = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / width));
  ctx.fillStyle = name === 'mic' ? '#e3b341' : '#65c7da';
  for (let x = 0; x < width; x += 1) {
    let peak = 0;
    const from = x * step;
    for (let i = from; i < from + step && i < data.length; i += 1) {
      const v = Math.abs(data[i]);
      if (v > peak) peak = v;
    }
    const tall = Math.max(1, peak * (height - 2));
    ctx.fillRect(x, (height - tall) / 2, 1, tall);
  }
}

/* ---------------------------------------------------------------- preview */

function ensureContext() {
  if (!context) context = new (window.AudioContext || window.webkitAudioContext)();
  if (context.state === 'suspended') context.resume();
  return context;
}

function gainOf(name) {
  const db = tracks[name].db;
  return db === 0 ? 1 : Math.pow(10, db / 20);
}

function applyGains() {
  for (const voice of voices) {
    if (voice.gain) voice.gain.gain.value = gainOf(voice.name);
  }
}

function start() {
  const audio = ensureContext();
  stopVoices();
  for (const name of ['broadcast', 'mic']) {
    const state = tracks[name];
    if (!state.there || !state.use || !state.buffer) continue;
    const source = audio.createBufferSource();
    source.buffer = state.buffer;
    const gain = audio.createGain();
    gain.gain.value = gainOf(name);
    /* Placed exactly as ffmpeg will place it: the track's own offset plus
     * the in point. A negative offset means it started before the camera,
     * so that much of its head is skipped. */
    const lead = state.offset < 0 ? -state.offset : 0;
    const late = state.offset > 0 ? state.offset : 0;
    const from = lead + inAt - late;
    if (mono || !bothIn()) {
      source.connect(gain).connect(audio.destination);
    } else {
      /* Not mono: broadcast left, ear right, the same split the file gets. */
      const side = audio.createStereoPanner();
      side.pan.value = name === 'mic' ? 1 : -1;
      source.connect(gain).connect(side).connect(audio.destination);
    }
    const at = Math.max(0, from);
    source.start(audio.currentTime + Math.max(0, -from), at, outAt - inAt);
    voices.push({ name, source, gain });
  }
}

function bothIn() {
  return tracks.broadcast.use && tracks.broadcast.there
    && tracks.mic.use && tracks.mic.there;
}

function stopVoices() {
  for (const voice of voices) {
    try { voice.source.stop(); } catch (error) { /* already done */ }
  }
  voices = [];
}

function follow() {
  paintHead();
  if (playing && film.currentTime >= outAt - 0.02) { stop('reached the out point'); return; }
  raf = requestAnimationFrame(follow);
}

function play() {
  if (!duration) return;
  /* Any scrub still in flight is abandoned: its `seeked` handler would
   * otherwise re-seek back to where the finger left off and yank the
   * playhead out of playback. */
  wantAt = null;
  seeking = false;
  film.currentTime = inAt;
  film.muted = true;
  playing = true;
  document.getElementById('playBtn').innerHTML = '&#9632; Stop';
  film.play().catch(() => {});
  start();
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(follow);
}

function stop(why) {
  /* WHY IT STOPPED, said out loud.
   *
   * The preview pausing itself has cost two rounds of guessing - once when a
   * NaN from a mis-bound event listener froze the playhead, and once when the
   * video itself turned out to be paused with no error and a full buffer.
   * Every caller now names itself, so the next time this happens the answer
   * is one line in the console rather than an afternoon. */
  try {
    console.info('[clip] stop(' + (why || 'unsaid') + ') at '
      + Number(film.currentTime).toFixed(2) + ' of ' + outAt.toFixed(2));
  } catch (error) { /* a console is not always there */ }
  playing = false;
  document.getElementById('playBtn').innerHTML = '&#9654; Preview';
  try { film.pause(); } catch (error) { /* fine */ }
  stopVoices();
  cancelAnimationFrame(raf);
  paintHead();
}

function restart() { if (playing) { stop('the mix changed'); play(); } }

document.getElementById('playBtn').addEventListener('click',
  () => (playing ? stop('pressed') : play()));

window.addEventListener('keydown', (event) => {
  if (event.target && /input|textarea/i.test(event.target.tagName)) return;
  if (event.key === ' ') { event.preventDefault(); playing ? stop('space') : play(); }
  else if (event.key.toLowerCase() === 'i') moveEdge('in', film.currentTime);
  else if (event.key.toLowerCase() === 'o') moveEdge('out', film.currentTime);
  else if (event.key === 'Escape') { if (playing) stop(); else close(); }
});

/* ----------------------------------------------------------------- export */

document.getElementById('cancelBtn').addEventListener('click', () => close());

document.getElementById('exportBtn').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  stop('exporting');
  const button = document.getElementById('exportBtn');
  button.disabled = true;
  say('Laying the sound under the picture…');
  try {
    const done = await api.clipExport({
      inPoint: inAt,
      outPoint: outAt,
      /* Null unless the box was actually moved: a crop at the full frame is
       * a filter that does nothing and can still fail. */
      crop: cropped && crop ? crop : null,
      mono: mono && bothIn(),
      use: {
        broadcast: tracks.broadcast.use && tracks.broadcast.there,
        mic: tracks.mic.use && tracks.mic.there
      },
      gains: { broadcast: tracks.broadcast.db, mic: tracks.mic.db }
    });
    if (done && done.canceled) say('Not saved.');
    else if (done && done.ok) {
      say('Saved — ' + Math.round(done.bytes / 1024) + ' kB. '
        + 'Opening the folder.', 'good');
      setTimeout(() => close(), 900);
    } else say((done && done.why) || 'It could not be written.', 'bad');
  } catch (error) {
    say(error.message, 'bad');
  } finally {
    busy = false;
    button.disabled = false;
  }
});

/* ============================================================== the crop ===
 *
 * "I want an editor where I can set the crop and adjust the timeline."
 *
 * HELD IN SOURCE PIXELS. The window is resizable and the video is fitted
 * into whatever room is left, so a box remembered as "where the mouse was"
 * would slide every time the window changed shape. One scale factor converts
 * in and out, and what the readout says - 640x480 - is exactly what ffmpeg is
 * told.
 *
 * OFF UNTIL IT IS TOUCHED. A box sitting at the full frame would still emit a
 * crop filter, and a filter that does nothing can still fail; `cropped` stays
 * false until the operator moves something. */
const cropLayer = document.getElementById('cropLayer');
const cropBox = document.getElementById('cropBox');
const cropSaid = document.getElementById('cropSaid');
const stage = document.getElementById('stage');

let cropping = false;       /* is the box being shown at all */
let cropped = false;        /* has it been moved off the full frame */
let crop = null;            /* {x, y, w, h} in SOURCE pixels */
let cropDrag = null;
const LEAST = 16;           /* the smallest crop worth allowing, in source px */

function sourceSize() {
  return { w: film.videoWidth || 0, h: film.videoHeight || 0 };
}

/* Where the VIDEO is on screen, which is not where the stage is: the picture
 * is letterboxed inside it, and a box draggable over the letterboxing would
 * describe pixels that do not exist. */
function filmRect() {
  const box = film.getBoundingClientRect();
  const room = stage.getBoundingClientRect();
  return { left: box.left - room.left, top: box.top - room.top,
    width: box.width, height: box.height };
}

function scale() {
  const src = sourceSize();
  const seen = filmRect();
  return src.w > 0 && seen.width > 0 ? src.w / seen.width : 1;
}

function wholeFrame() {
  const src = sourceSize();
  return { x: 0, y: 0, w: src.w, h: src.h };
}

/* EVEN IN ALL FOUR NUMBERS. libx264 with yuv420p refuses odd dimensions and
 * blames the frames when it does; odd x/y offsets are the same trap wearing a
 * different hat, putting the chroma planes half a pixel out. */
function tidy(box) {
  const src = sourceSize();
  let x = Math.max(0, Math.min(src.w - LEAST, Math.round(box.x)));
  let y = Math.max(0, Math.min(src.h - LEAST, Math.round(box.y)));
  let w = Math.max(LEAST, Math.min(src.w - x, Math.round(box.w)));
  let h = Math.max(LEAST, Math.min(src.h - y, Math.round(box.h)));
  x -= x % 2; y -= y % 2; w -= w % 2; h -= h % 2;
  if (x + w > src.w) w = src.w - x - ((src.w - x) % 2);
  if (y + h > src.h) h = src.h - y - ((src.h - y) % 2);
  return { x: x, y: y, w: Math.max(2, w), h: Math.max(2, h) };
}

function paintCrop() {
  const src = sourceSize();
  if (!crop || !src.w) {
    cropSaid.textContent = '';
    return;
  }
  const seen = filmRect();
  const by = seen.width / src.w;
  cropLayer.style.left = seen.left + 'px';
  cropLayer.style.top = seen.top + 'px';
  cropLayer.style.width = seen.width + 'px';
  cropLayer.style.height = seen.height + 'px';
  cropBox.style.left = (crop.x * by) + 'px';
  cropBox.style.top = (crop.y * by) + 'px';
  cropBox.style.width = (crop.w * by) + 'px';
  cropBox.style.height = (crop.h * by) + 'px';
  cropLayer.classList.toggle('hidden', !cropping);
  cropSaid.textContent = cropped
    ? src.w + '\u00d7' + src.h + ' \u2192 ' + crop.w + '\u00d7' + crop.h
    : src.w + '\u00d7' + src.h;
  const button = document.getElementById('cropBtn');
  if (button) button.classList.toggle('on', cropping);
}

function cropStart() {
  if (!crop) crop = wholeFrame();
  cropping = true;
  paintCrop();
}

function cropWhole() {
  crop = wholeFrame();
  cropped = false;
  paintCrop();
}

document.getElementById('cropBtn').addEventListener('click', function () {
  cropping ? (cropping = false, paintCrop()) : cropStart();
});

document.getElementById('cropAll').addEventListener('click', function () {
  cropWhole();
});

/* Dragging: the body of the box moves it, a grip resizes from that edge.
 * Both work in source pixels, so the arithmetic is the same either way. */
cropBox.addEventListener('pointerdown', function (event) {
  if (!crop) return;
  event.preventDefault();
  event.stopPropagation();
  const grip = event.target && event.target.dataset
    ? event.target.dataset.grip : '';
  cropDrag = { grip: grip || '', x: event.clientX, y: event.clientY,
    from: { x: crop.x, y: crop.y, w: crop.w, h: crop.h } };
  try { cropBox.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
});

cropBox.addEventListener('pointermove', function (event) {
  if (!cropDrag) return;
  const by = scale();
  const dx = (event.clientX - cropDrag.x) * by;
  const dy = (event.clientY - cropDrag.y) * by;
  const was = cropDrag.from;
  const grip = cropDrag.grip;
  let next;
  if (!grip) {
    next = { x: was.x + dx, y: was.y + dy, w: was.w, h: was.h };
    /* Moving must not resize: clamp the ORIGIN against the frame rather
     * than letting tidy() shrink the box at the edge. */
    const src = sourceSize();
    next.x = Math.max(0, Math.min(src.w - was.w, next.x));
    next.y = Math.max(0, Math.min(src.h - was.h, next.y));
  } else {
    next = { x: was.x, y: was.y, w: was.w, h: was.h };
    if (grip.indexOf('w') >= 0) { next.x = was.x + dx; next.w = was.w - dx; }
    if (grip.indexOf('e') >= 0) { next.w = was.w + dx; }
    if (grip.indexOf('n') >= 0) { next.y = was.y + dy; next.h = was.h - dy; }
    if (grip.indexOf('s') >= 0) { next.h = was.h + dy; }
    /* Dragging an edge past its opposite would give a negative width, which
     * ffmpeg reports as an unhelpful filter error. */
    if (next.w < LEAST) { next.x = was.x + was.w - LEAST; next.w = LEAST; }
    if (next.h < LEAST) { next.y = was.y + was.h - LEAST; next.h = LEAST; }
  }
  crop = tidy(next);
  cropped = true;
  paintCrop();
});

function cropLetGo(event) {
  if (!cropDrag) return;
  cropDrag = null;
  try { cropBox.releasePointerCapture(event.pointerId); } catch (error) { /* fine */ }
}

cropBox.addEventListener('pointerup', cropLetGo);
cropBox.addEventListener('pointercancel', cropLetGo);

/* The picture moves when the window does, so the box has to be put back on
 * it - it is stored against the SOURCE, so nothing is lost, but the overlay
 * would be left behind. */
window.addEventListener('resize', paintCrop);

function close() {
  try { api.clipDone(); } catch (error) { window.close(); }
}

/* ------------------------------------------------------------------- open */

async function decode(name, dataUrl, offset) {
  const state = tracks[name];
  state.offset = Number(offset) || 0;
  if (!dataUrl) { state.there = false; state.use = false; paintWave(name); paintTrack(name); return; }
  try {
    const bytes = await (await fetch(dataUrl)).arrayBuffer();
    state.buffer = await ensureContext().decodeAudioData(bytes);
    state.there = true;
  } catch (error) {
    state.there = false;
    state.use = false;
    row(name).querySelector('.detail').textContent = 'would not decode';
  }
  paintWave(name);
  paintTrack(name);
}

(async function open() {
  try {
    clip = await api.clipPending();
    if (!clip || !clip.ok) {
      say((clip && clip.why) || 'There is no recording waiting.', 'bad');
      return;
    }
    film.src = clip.videoUrl;
    film.muted = true;
    await new Promise((resolve) => {
      film.addEventListener('loadedmetadata', resolve, { once: true });
      film.addEventListener('error', resolve, { once: true });
    });
    /* screenrecord's own header can say 0 on a short clip; the length the
     * recorder asked for is the honest fallback. */
    duration = isFinite(film.duration) && film.duration > 0
      ? film.duration : (clip.seconds || 0);
    inAt = 0;
    outAt = duration;
    paintTrim();
    paintHead();
    /* The crop box only exists once the source size is known - before
     * loadedmetadata videoWidth is 0 and every conversion through it would
     * be a division by zero. */
    cropWhole();
    /* WRAPPED, NOT PASSED DIRECTLY.
     *
     * paintHead takes an optional time, so binding it straight to the event
     * hands it the Event object as that argument - `(event / duration)` is
     * NaN, `left: NaN%` is ignored by CSS, and the playhead simply stops.
     * timeupdate fires about four times a second during playback, so it was
     * clobbering the correct positions the animation frame had just written.
     * Reported as "the playhead isn't moving whenever I play the timeline",
     * which is exactly what it does. */
    film.addEventListener('timeupdate', function () { paintHead(); });

    await decode('broadcast', clip.broadcastUrl, clip.broadcastOffset);
    await decode('mic', clip.micUrl, clip.micOffset);

    row('broadcast').querySelector('.detail').textContent = tracks.broadcast.there
      ? 'the mix as the tablet played it' : 'not captured';
    row('mic').querySelector('.detail').textContent = tracks.mic.there
      ? ('the tablet’s ear, echo-cancelled'
         + (clip.micQuiet ? ' — almost silent' : '')) : 'not captured';

    paintMono();
    const missing = (clip.notes || []).length
      ? ' · ' + clip.notes.join(' · ') : '';
    say(duration.toFixed(1) + 's recorded' + missing);
  } catch (error) {
    say(error.message, 'bad');
  }
})();
