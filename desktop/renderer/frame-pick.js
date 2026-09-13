/* FINDING THE MOMENT, THEN TAKING IT.
 *
 * "When I control click the image icon, allow me to scrub the timeline to
 *  scrub back and find the exact moment in time in which I want to draw on
 *  the screenshot."
 *
 * The picture this window produces is a FRAME OF THE RECORDING, not a fresh
 * screenshot - the whole point is that the moment has already passed. It is
 * drawn out of the <video> at its natural size through a canvas, so what
 * reaches the clipboard and the mark-up window is exactly the pixels the
 * tablet's encoder wrote, at the recording's resolution.
 *
 * TIME IS SHOWN AS "AGO", NOT AS A POSITION. The recording ends at the
 * instant the button was pressed, so 0.0 s is now and the far left is the
 * oldest thing still held. "12.4 s ago" is a thing an operator can reason
 * about; "00:17 of 00:30" is arithmetic they have to do themselves.
 */
'use strict';

const api = window.pineDesktop || {};

const film = document.getElementById('film');
const waiting = document.getElementById('waiting');
const track = document.getElementById('track');
const done = document.getElementById('done');
const head = document.getElementById('head');
const ticks = document.getElementById('ticks');
const agoAt = document.getElementById('ago');
const ofWhat = document.getElementById('ofWhat');
const playPause = document.getElementById('playPause');
const said = document.getElementById('said');

/* The recording's own length, from the file rather than from what was asked
 * for - the ring holds what it holds, and a scrub bar scaled to a length
 * that is not there puts every moment in the wrong place. */
let span = 0;
let playing = false;
let taking = false;
let scrubbing = false;

/* A STEP IS A THIRTIETH, NOT A TWELFTH. The encoder is asked for 12 fps but
 * a mirrored display posts frames whenever the screen changes, and the
 * recordings measure nearer 35 fps. Stepping by 1/12 would skip two frames
 * out of three - which is exactly the frame you were looking for. */
const STEP = 1 / 30;

function say(words, bad) {
  said.textContent = words || '';
  said.classList.toggle('bad', !!bad);
}

/* ----------------------------------------------------------- the picture */

async function begin() {
  let held = null;
  try {
    held = await api.framePending();
  } catch (error) {
    return say('the recording could not be reached: ' + error.message, true);
  }
  if (!held || !held.ok) {
    return say((held && held.why) || 'there is no recording waiting', true);
  }
  (held.notes || []).length ? say(held.notes.join('; ')) : say('');

  film.addEventListener('loadedmetadata', function () {
    /* The file's own duration, unless it is one of the NaN/Infinity answers
     * a fragmented mp4 gives, in which case fall back to what the recorder
     * said it wrote. */
    span = isFinite(film.duration) && film.duration > 0
      ? film.duration : (Number(held.seconds) || 0);
    waiting.classList.add('gone');
    /* THE END, NOT THE BEGINNING. The last frame is the closest thing to
     * "what I was just looking at", so it is the one to open on - scrubbing
     * back from there is the gesture that was asked for. */
    film.currentTime = Math.max(0, span - 0.05);
    layTicks();
    paint();
  }, { once: true });

  film.addEventListener('error', function () {
    say('the recording would not play in this window', true);
  });

  film.src = held.videoUrl;
  film.load();
}

/* ---------------------------------------------------------- the timeline */

function paint() {
  const at = Number(film.currentTime) || 0;
  const part = span > 0 ? Math.max(0, Math.min(1, at / span)) : 0;
  head.style.left = (part * 100).toFixed(3) + '%';
  done.style.width = (part * 100).toFixed(3) + '%';
  const back = Math.max(0, span - at);
  agoAt.textContent = back < 0.05 ? 'now' : back.toFixed(2) + ' s ago';
  ofWhat.textContent = span > 0
    ? '— ' + span.toFixed(1) + ' s held' : '';
  track.setAttribute('aria-valuenow', back.toFixed(1));
}

/* A mark every five seconds, counted BACKWARDS from the end for the same
 * reason the readout is: the operator is looking for "about ten seconds
 * ago", not for "at twenty seconds in". */
function layTicks() {
  ticks.textContent = '';
  if (!(span > 0)) return;
  for (let back = 0; back <= span; back += 5) {
    const mark = document.createElement('span');
    mark.textContent = back === 0 ? 'now' : '-' + back + 's';
    mark.style.left = (((span - back) / span) * 100).toFixed(3) + '%';
    ticks.appendChild(mark);
  }
}

function goTo(at) {
  if (!(span > 0)) return;
  film.currentTime = Math.max(0, Math.min(span - 0.01, at));
  paint();
}

function timeAt(event) {
  const box = track.getBoundingClientRect();
  const part = box.width > 0
    ? Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) : 0;
  return part * span;
}

track.addEventListener('pointerdown', function (event) {
  if (!(span > 0)) return;
  scrubbing = true;
  pause();
  /* Guarded: a capture on an element that has already lost the pointer
   * throws, and an uncaught throw here leaves the scrub half-engaged. */
  try { track.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
  goTo(timeAt(event));
});

track.addEventListener('pointermove', function (event) {
  if (scrubbing) goTo(timeAt(event));
});

function letGo(event) {
  if (!scrubbing) return;
  scrubbing = false;
  try { track.releasePointerCapture(event.pointerId); } catch (error) { /* fine */ }
}

track.addEventListener('pointerup', letGo);
track.addEventListener('pointercancel', letGo);

/* The video's own clock drives the readout while it plays - painting from a
 * timer instead is how a playhead ends up describing a moment the picture
 * has already left. */
film.addEventListener('timeupdate', function () { paint(); });
film.addEventListener('seeked', function () { paint(); });

/* ---------------------------------------------------------- the transport */

function drawPlayGlyph() {
  const name = playing ? 'c:pause--filled' : 'c:caret--right';
  playPause.innerHTML = (window.pineIcon ? window.pineIcon(name) : '');
  playPause.setAttribute('aria-label', playing ? 'Pause' : 'Play');
}

function play() {
  if (!(span > 0)) return;
  if (film.currentTime >= span - 0.05) film.currentTime = 0;
  film.play().then(function () {
    playing = true;
    drawPlayGlyph();
  }).catch(function (error) {
    say('it would not play: ' + error.message, true);
  });
}

function pause() {
  if (!playing) return;
  film.pause();
  playing = false;
  drawPlayGlyph();
}

film.addEventListener('ended', function () { playing = false; drawPlayGlyph(); });

playPause.addEventListener('click', function () {
  playing ? pause() : play();
});

document.getElementById('backFrame').addEventListener('click', function () {
  pause();
  goTo(film.currentTime - STEP);
});

document.getElementById('onFrame').addEventListener('click', function () {
  pause();
  goTo(film.currentTime + STEP);
});

document.addEventListener('keydown', function (event) {
  if (event.target && /^(INPUT|TEXTAREA)$/.test(event.target.tagName)) return;
  const big = event.shiftKey;
  if (event.key === 'ArrowLeft') {
    event.preventDefault(); pause(); goTo(film.currentTime - (big ? 1 : STEP));
  } else if (event.key === 'ArrowRight') {
    event.preventDefault(); pause(); goTo(film.currentTime + (big ? 1 : STEP));
  } else if (event.key === ' ') {
    event.preventDefault(); playing ? pause() : play();
  } else if (event.key === 'Home') {
    event.preventDefault(); pause(); goTo(0);
  } else if (event.key === 'End') {
    event.preventDefault(); pause(); goTo(span);
  } else if (event.key === 'Enter') {
    event.preventDefault(); take(true);
  } else if (event.key === 'Escape') {
    event.preventDefault();
    if (api.frameDone) api.frameDone();
  }
});

/* ------------------------------------------------------------- the taking */

/* The frame as pixels. Drawn at the video's NATURAL size rather than the
 * size it happens to be displayed at, so a window dragged small does not
 * quietly produce a small screenshot. */
function frameNow() {
  const wide = film.videoWidth;
  const tall = film.videoHeight;
  if (!wide || !tall) return null;
  const plate = document.createElement('canvas');
  plate.width = wide;
  plate.height = tall;
  plate.getContext('2d').drawImage(film, 0, 0, wide, tall);
  return plate.toDataURL('image/png');
}

async function take(edit) {
  if (taking) return;
  if (!(span > 0)) return say('there is nothing to take yet', true);
  taking = true;
  pause();
  try {
    const png = frameNow();
    if (!png) {
      taking = false;
      return say('the frame could not be read off the video', true);
    }
    const back = Math.max(0, span - (Number(film.currentTime) || 0));
    const went = await api.framePick({ dataUrl: png, edit: !!edit, back });
    if (!went || !went.ok) {
      taking = false;
      return say((went && went.why) || 'the frame could not be taken', true);
    }
    /* On success the window is closed from the main process, so there is
     * nothing to say here that anyone would have time to read. */
  } catch (error) {
    taking = false;
    say(error.message, true);
  }
}

document.getElementById('take').addEventListener('click', function () { take(true); });
document.getElementById('copy').addEventListener('click', function () { take(false); });

/* ----------------------------------------------------------------- start */

if (window.pineIconUpgrade) window.pineIconUpgrade(document);
drawPlayGlyph();
begin();
