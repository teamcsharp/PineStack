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

const glass = document.getElementById('glass');
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
  } else if (event.key === '0') {
    event.preventDefault(); resetZoom();
  } else if (event.key === 'Escape' && zoom > 1) {
    /* Escape gets out of the magnifier before it gets out of the window -
     * one press should not throw away the moment that was just found. */
    event.preventDefault(); resetZoom();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    if (api.frameDone) api.frameDone();
  }
});

/* -------------------------------------------------------- zoom and pan */

/* THE SAME GESTURE AS THE LIVE MIRROR, because it is the same gesture: the
 * picture is letterboxed into whatever room the window has, and finding the
 * exact moment often means reading something small.
 *
 * A VIEWING AID ONLY. frameNow() still draws the whole video at its natural
 * size, so zooming in to read a label cannot quietly hand over a cropped
 * screenshot of whatever happened to be on screen. */
const MOST = 8;
let zoom = 1;
let ox = 0;
let oy = 0;
let panning = null;

function place() {
  /* Clamped so the picture cannot be thrown off the edge and lost - an
   * unclamped viewer has a state with no obvious way out of it. */
  const wide = film.clientWidth;
  const tall = film.clientHeight;
  const room = glass.getBoundingClientRect();
  const slackX = Math.max(0, (wide * zoom - room.width) / 2);
  const slackY = Math.max(0, (tall * zoom - room.height) / 2);
  ox = Math.max(-slackX, Math.min(slackX, ox));
  oy = Math.max(-slackY, Math.min(slackY, oy));
  film.style.transform = zoom === 1 && !ox && !oy
    ? '' : 'translate(' + ox.toFixed(1) + 'px,' + oy.toFixed(1) + 'px) scale('
      + zoom.toFixed(4) + ')';
  glass.classList.toggle('zoomed', zoom > 1);
}

function resetZoom() { zoom = 1; ox = 0; oy = 0; place(); }

glass.addEventListener('wheel', function (event) {
  event.preventDefault();
  const was = zoom;
  /* A fixed ratio per notch, so in-and-straight-back-out lands exactly
   * where it started rather than drifting. */
  zoom = Math.max(1, Math.min(MOST, zoom * (event.deltaY < 0 ? 1.25 : 1 / 1.25)));
  if (zoom === was) return;
  /* ABOUT THE POINTER: with the origin at the centre a screen point maps
   * from a picture point as p = o + q*s, so holding p still across a scale
   * change gives o1 = p - (p - o0) * s1/s0. Zooming about the centre would
   * mean every zoom is followed by a pan to get back to what you were
   * looking at. */
  const room = glass.getBoundingClientRect();
  const px = event.clientX - room.left - room.width / 2;
  const py = event.clientY - room.top - room.height / 2;
  ox = px - (px - ox) * (zoom / was);
  oy = py - (py - oy) * (zoom / was);
  if (zoom === 1) { ox = 0; oy = 0; }
  place();
}, { passive: false });

glass.addEventListener('pointerdown', function (event) {
  if (event.button !== 1) return;
  event.preventDefault();
  panning = { x: event.clientX, y: event.clientY };
  glass.classList.add('panning');
  try { glass.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
});

glass.addEventListener('pointermove', function (event) {
  if (!panning) return;
  ox += event.clientX - panning.x;
  oy += event.clientY - panning.y;
  panning = { x: event.clientX, y: event.clientY };
  place();
});

function stopPan(event) {
  if (!panning) return;
  panning = null;
  glass.classList.remove('panning');
  try { glass.releasePointerCapture(event.pointerId); } catch (error) { /* fine */ }
}

glass.addEventListener('pointerup', stopPan);
glass.addEventListener('pointercancel', stopPan);
/* Windows starts its own autoscroll on the middle button and the picture
 * fights it. */
glass.addEventListener('auxclick', function (event) {
  if (event.button === 1) event.preventDefault();
});

/* The fit changes with the window, so the clamp has to be reapplied or a
 * zoomed picture ends up pinned off-centre. */
window.addEventListener('resize', place);

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
