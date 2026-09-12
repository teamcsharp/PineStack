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
let mono = false;
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

function paintHead() {
  if (!duration) return;
  head.style.left = ((film.currentTime / duration) * 100) + '%';
}

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
  film.currentTime = edge === 'in' ? inAt : Math.max(inAt, outAt - 0.4);
  paintHead();
}

/* Clicking the strip scrubs; it does not move a handle. Handles are dragged,
 * which is the only way to have both on one strip without every scrub
 * nudging whichever edge was nearest. */
track.addEventListener('pointerdown', (event) => {
  if (dragging) return;
  const when = timeAt(event);
  if (playing) stop();
  film.currentTime = Math.min(Math.max(when, 0), duration);
  paintHead();
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
  if (playing && film.currentTime >= outAt - 0.02) { stop(); return; }
  raf = requestAnimationFrame(follow);
}

function play() {
  if (!duration) return;
  film.currentTime = inAt;
  film.muted = true;
  playing = true;
  document.getElementById('playBtn').innerHTML = '&#9632; Stop';
  film.play().catch(() => {});
  start();
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(follow);
}

function stop() {
  playing = false;
  document.getElementById('playBtn').innerHTML = '&#9654; Preview';
  try { film.pause(); } catch (error) { /* fine */ }
  stopVoices();
  cancelAnimationFrame(raf);
  paintHead();
}

function restart() { if (playing) { stop(); play(); } }

document.getElementById('playBtn').addEventListener('click',
  () => (playing ? stop() : play()));

window.addEventListener('keydown', (event) => {
  if (event.target && /input|textarea/i.test(event.target.tagName)) return;
  if (event.key === ' ') { event.preventDefault(); playing ? stop() : play(); }
  else if (event.key.toLowerCase() === 'i') moveEdge('in', film.currentTime);
  else if (event.key.toLowerCase() === 'o') moveEdge('out', film.currentTime);
  else if (event.key === 'Escape') { if (playing) stop(); else close(); }
});

/* ----------------------------------------------------------------- export */

document.getElementById('cancelBtn').addEventListener('click', () => close());

document.getElementById('exportBtn').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  stop();
  const button = document.getElementById('exportBtn');
  button.disabled = true;
  say('Laying the sound under the picture…');
  try {
    const done = await api.clipExport({
      inPoint: inAt,
      outPoint: outAt,
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
    film.addEventListener('timeupdate', paintHead);

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
