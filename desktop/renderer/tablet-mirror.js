/* THE TABLET, LIVE, AND THE TWO SIZES THAT ARE NOT THE SAME THING.
 *
 * "A picture in picture window... that allows me to see the screen of the
 *  tablet itself in real time and be able to dynamically adjust the scale of
 *  the window to have it be the size that I need it to be."
 * "Allow me to render the tablet in full size if I desire, but generally I
 *  would want to bring it up at a third resolution or half."
 * "And if I double click it, I want to go fullscreen with the display."
 *
 * DETAIL and WINDOW are kept apart deliberately:
 *
 *   Detail is how many pixels the TABLET sends. It costs the tablet encoder
 *     work and battery, and it is the only one of the two that can make the
 *     picture sharper.
 *   Window is how big this is on THIS desk. It costs nothing and can be
 *     changed by dragging the edge like any other window.
 *
 * Conflating them is how a mirror ends up either crisp and postage-stamp
 * sized or huge and soft, with no obvious way back.
 *
 * THE PICTURE IS AN <img> AND NOTHING RUNS PER FRAME. It is pointed at a
 * multipart stream; the browser decodes and scales it. Changing detail does
 * not change the URL, so the connection is never dropped - the frames simply
 * get bigger or smaller.
 */
'use strict';

const api = window.pineDesktop || {};

const live = document.getElementById('live');
const veil = document.getElementById('veil');
const glass = document.getElementById('glass');
const how = document.getElementById('how');

let shown = null;          /* the last answer from the main process */
let full = false;

function cover(words, bad) {
  veil.textContent = words || '';
  veil.classList.toggle('bad', !!bad);
  veil.classList.toggle('gone', !words);
}

/* ------------------------------------------------------------ the stream */

async function begin() {
  let open = null;
  try {
    open = await api.mirrorOpen({});
  } catch (error) {
    return cover('the tablet mirror would not start: ' + error.message, true);
  }
  if (!open || !open.ok) {
    return cover((open && open.why) || 'the tablet mirror would not start', true);
  }
  shown = open;
  paintButtons();
  /* The first frame clears the veil - "running" is not the same as "there
   * are pictures", and covering the gap with a black rectangle would make a
   * dead stream look like a sleeping tablet. */
  live.addEventListener('load', function () { cover(''); }, { once: true });
  live.addEventListener('error', function () {
    cover('the picture stopped coming', true);
  });
  live.src = open.url;
  watch();
}

function paintButtons() {
  for (const button of document.querySelectorAll('.res')) {
    button.classList.toggle('on', !!shown && button.dataset.size === shown.size);
  }
}

/* -------------------------------------------------------------- detail */

/* Changing what the tablet sends. Shared by the buttons and by the zoom, so
 * both roads behave identically - including the note that says why the
 * picture is about to stall for a moment. */
async function setDetail(want, why) {
  if (!shown || !want || want === shown.size) return false;
  try {
    const said = await api.mirrorSize(want);
    if (!said || !said.ok) return false;
    shown = said;
    paintButtons();
    /* THE ZOOM IS NOT RESET. The <img> is fitted to the glass by CSS, so
     * every detail lays out at the same size and only sharpness changes -
     * throwing the magnifier away here would discard the view the operator
     * zoomed in to reach, which is the entire point of the feature. */
    cover((why || 'Switching the tablet to ') + label(want) + '…');
    setTimeout(function () { cover(''); }, 1600);
    return true;
  } catch (error) {
    cover(error.message, true);
    return false;
  }
}

for (const button of document.querySelectorAll('.res')) {
  button.addEventListener('click', function () {
    /* A DELIBERATE CHOICE OUTRANKS THE GESTURE. Picking a detail by hand
     * turns off the automatic sharpening, or the next wheel notch would
     * quietly overrule what was just asked for. */
    auto = false;
    paintAuto();
    setDetail(button.dataset.size, 'Switching the tablet to ');
  });
}

function label(size) {
  return size === 'quarter' ? 'a quarter'
    : size === 'third' ? 'a third'
    : size === 'full' ? 'full detail' : 'half';
}

/* -------------------------------------------------------------- window */

for (const button of document.querySelectorAll('.zoom')) {
  button.addEventListener('click', function () {
    if (!shown) return;
    /* Sized against the TABLET's real screen, not against the capture: at a
     * third detail, "100%" should still mean one tablet pixel per screen
     * pixel, or the button would mean something different at each setting. */
    const real = shown.real || { width: shown.width, height: shown.height };
    const part = Number(button.dataset.zoom) || 1;
    api.mirrorWindow({
      width: Math.round(real.width * part),
      height: Math.round(real.height * part)
    });
  });
}

/* ------------------------------------------------------- zoom and pan */

/* A THIRD KIND OF SIZE - and unlike the other two it decides the first one.
 *
 * Detail is pixels the tablet sends. Window is how big this is on the desk.
 * ZOOM is a magnifier over what has arrived - and because a magnifier over a
 * third-detail stream only enlarges blur, zooming in asks the tablet for
 * more pixels. See sharpenSoon(). */
const MOST = 8;
const ORDER = ['quarter', 'third', 'half', 'full'];
const PART = { quarter: 1 / 4, third: 1 / 3, half: 1 / 2, full: 1 };

let zoom = 1;
let ox = 0;                 /* pan, in displayed pixels from the centre */
let oy = 0;
let panning = null;
let auto = true;
let sharpenAt = 0;

function frame() {
  /* The picture's laid-out size at zoom 1 - the browser has already fitted
   * it inside the glass, so this is what everything scales from. */
  return { wide: live.clientWidth, tall: live.clientHeight,
    boxWide: glass.clientWidth, boxTall: glass.clientHeight };
}

/* KEEP THE PICTURE ON SCREEN. Panned far enough, an unclamped viewer loses
 * the picture entirely and there is no obvious way back. */
function rein() {
  const it = frame();
  const slackX = Math.max(0, (it.wide * zoom - it.boxWide) / 2);
  const slackY = Math.max(0, (it.tall * zoom - it.boxTall) / 2);
  ox = Math.max(-slackX, Math.min(slackX, ox));
  oy = Math.max(-slackY, Math.min(slackY, oy));
}

function place() {
  rein();
  live.style.transform = zoom === 1 && !ox && !oy
    ? '' : 'translate(' + ox.toFixed(1) + 'px,' + oy.toFixed(1) + 'px) scale('
      + zoom.toFixed(4) + ')';
  glass.classList.toggle('zoomed', zoom > 1);
  const at = document.getElementById('zoomAt');
  if (at) at.textContent = zoom > 1 ? '×' + zoom.toFixed(1) : '';
}

function reset() { zoom = 1; ox = 0; oy = 0; place(); sharpenSoon(); }

/* WHICH DETAIL THIS ZOOM DESERVES: the smallest one whose frames do not have
 * to be upscaled to fill the picture as it is currently displayed. */
function deserved() {
  if (!shown || !shown.real) return null;
  const acrossNow = frame().wide * zoom;
  for (const name of ORDER) {
    if (Math.round(shown.real.width * PART[name]) >= acrossNow * 0.98) return name;
  }
  return 'full';
}

/* Every change rebuilds the capture pipe and costs about two seconds of
 * picture, so this waits for the wheel to stop, and is deliberately reluctant
 * to step back DOWN: a zoom sitting on a boundary would otherwise rebuild the
 * pipe back and forth for as long as it sat there. */
function sharpenSoon() {
  if (!auto || !shown) return;
  clearTimeout(sharpenAt);
  sharpenAt = setTimeout(function () {
    const want = deserved();
    if (!want || want === shown.size) return;
    const climbing = ORDER.indexOf(want) > ORDER.indexOf(shown.size);
    if (!climbing) {
      /* A fifth of slack before letting the tablet off again. */
      const acrossNow = frame().wide * zoom;
      if (Math.round(shown.real.width * PART[want]) < acrossNow * 1.2) return;
    }
    setDetail(want, climbing ? 'Sharpening to ' : 'Easing back to ');
  }, 500);
}

glass.addEventListener('wheel', function (event) {
  event.preventDefault();
  const was = zoom;
  /* A fixed ratio per notch, so zooming in and straight back out lands
   * exactly where it started rather than drifting. */
  const step = event.deltaY < 0 ? 1.25 : 1 / 1.25;
  zoom = Math.max(1, Math.min(MOST, zoom * step));
  if (zoom === was) return;

  /* ABOUT THE POINTER. The point under the cursor must not move: with
   * transform-origin at the centre a screen point p maps from picture
   * point q as p = o + q*s, so holding p fixed across a scale change
   * gives o1 = p - (p - o0) * s1/s0. */
  const box = glass.getBoundingClientRect();
  const px = event.clientX - box.left - box.width / 2;
  const py = event.clientY - box.top - box.height / 2;
  ox = px - (px - ox) * (zoom / was);
  oy = py - (py - oy) * (zoom / was);
  if (zoom === 1) { ox = 0; oy = 0; }
  place();
  sharpenSoon();
}, { passive: false });

/* HOLD SPACE TO PAN, the same as the mark-up window - "Photoshop level
 * controls for basic functionality whenever I'm using any of the editors".
 *
 * While TOUCH is on, space belongs to the tablet: it is a character being
 * typed into whatever is on the terminal's screen, and stealing it would
 * make a space impossible to send. */
let spaceHeld = false;

document.addEventListener('keydown', function (event) {
  if (event.code !== 'Space' || touching) return;
  /* Auto-repeat fires for as long as it is held: arm once, but suppress the
   * default every time or the window scrolls under the pan. */
  event.preventDefault();
  if (spaceHeld) return;
  spaceHeld = true;
  glass.classList.add('handy');
});

document.addEventListener('keyup', function (event) {
  if (event.code !== 'Space') return;
  spaceHeld = false;
  glass.classList.remove('handy');
});

/* Alt-tab away with space down and the keyup never arrives, leaving the
 * window armed in a mode with nothing on screen to explain it. */
window.addEventListener('blur', function () {
  spaceHeld = false;
  glass.classList.remove('handy');
});

/* THE MIDDLE BUTTON PANS, and so does the left one while space is held.
 * auxclick is swallowed as well, because Windows otherwise starts its own
 * autoscroll on the middle button and the picture fights it. */
glass.addEventListener('pointerdown', function (event) {
  if (event.button !== 1 && !(event.button === 0 && spaceHeld)) return;
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
glass.addEventListener('auxclick', function (event) {
  if (event.button === 1) event.preventDefault();
});

/* The fit changes when the window does, so the clamp has to be reapplied or
 * a zoomed picture can end up pinned off-centre - and a bigger window is
 * also a reason to ask the tablet for more pixels. */
window.addEventListener('resize', function () { place(); sharpenSoon(); });

const autoBtn = document.getElementById('autoRes');

function paintAuto() {
  if (autoBtn) autoBtn.classList.toggle('on', auto);
}

if (autoBtn) {
  autoBtn.addEventListener('click', function () {
    auto = !auto;
    paintAuto();
    if (auto) sharpenSoon();
  });
}

/* ---------------------------------------------------------- fullscreen */

async function goFull(want) {
  try {
    const said = await api.mirrorFull(want);
    full = !!(said && said.full);
    document.body.classList.toggle('full', full);
    /* A fullscreen picture is a much bigger picture, and asking the tablet
     * for enough pixels to fill it is the same question the zoom asks. */
    setTimeout(function () { place(); sharpenSoon(); }, 250);
  } catch (error) { /* the window said no; nothing to do about it */ }
}

glass.addEventListener('dblclick', function () { goFull(!full); });
document.getElementById('big').addEventListener('click', function () { goFull(!full); });

document.addEventListener('keydown', function (event) {
  /* WHILE TOUCH IS ON, LETTERS BELONG TO THE TABLET. Otherwise there would
   * be no way to type an "f" into it. Escape still gets out. */
  if (touching && event.key !== 'Escape') return;
  if (event.key === 'f' || event.key === 'F') { event.preventDefault(); goFull(!full); }
  else if (event.key === '0') { event.preventDefault(); reset(); }
  else if (event.key === 'Escape' && zoom > 1) { event.preventDefault(); reset(); }
  else if (event.key === 'Escape' && full) { event.preventDefault(); goFull(false); }
});

/* --------------------------------------------------------- touching it */

/* OFF UNTIL IT IS TURNED ON. This window floats over everything and shows a
 * LIVE radio station: a stray click on a sampler pad puts a sound on the
 * air. The picture is inert until the operator says otherwise. */
let touching = false;
let press = null;
const touchBtn = document.getElementById('touch');
const spot = document.getElementById('spot');

/* WHERE ON THE TABLET a pointer is, undoing in order: the picture's place in
 * the glass, the magnifier over it, and the difference between its size here
 * and the tablet's real screen. Returns null when the pointer is on the
 * letterboxing rather than on the picture - clamping instead would put the
 * tap on the edge of the tablet's screen, which is a real place. */
function whereOnTablet(event) {
  if (!shown || !shown.real) return null;
  const it = frame();
  if (!(it.wide > 0 && it.tall > 0)) return null;
  const box = glass.getBoundingClientRect();
  const cx = event.clientX - box.left - box.width / 2;
  const cy = event.clientY - box.top - box.height / 2;
  /* Undo the magnifier: place() applies translate then scale about the
   * centre, so a screen point maps back as (c - offset) / zoom. */
  const qx = (cx - ox) / zoom;
  const qy = (cy - oy) / zoom;
  const fx = (qx + it.wide / 2) / it.wide;
  const fy = (qy + it.tall / 2) / it.tall;
  if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
  return { x: fx * shown.real.width, y: fy * shown.real.height };
}

function showSpot(event) {
  const box = glass.getBoundingClientRect();
  spot.style.left = (event.clientX - box.left) + 'px';
  spot.style.top = (event.clientY - box.top) + 'px';
  spot.classList.remove('hit');
  /* Forcing a reflow so the transition restarts on a repeated tap in the
   * same place - without it the second tap shows nothing. */
  void spot.offsetWidth;
  spot.classList.add('hit');
  setTimeout(function () { spot.classList.remove('hit'); }, 20);
}

function touchOn(want) {
  touching = want;
  glass.classList.toggle('touching', want);
  touchBtn.classList.toggle('on', want);
  try { localStorage.setItem('pine-mirror-touch', want ? '1' : '0'); }
  catch (error) { /* fine */ }
}

touchBtn.addEventListener('click', function () { touchOn(!touching); });

/* THE LEFT BUTTON REACHES THROUGH; the wheel and the middle button stay this
 * window's own, because zooming and panning are things you do to the VIEW
 * and the tablet has no business seeing them. */
glass.addEventListener('pointerdown', function (event) {
  if (!touching || event.button !== 0) return;
  const at = whereOnTablet(event);
  if (!at) return;
  event.preventDefault();
  press = { at: at, when: Date.now(), x: event.clientX, y: event.clientY };
  try { glass.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
});

glass.addEventListener('pointerup', async function (event) {
  if (!press || event.button !== 0) return;
  const from = press;
  press = null;
  try { glass.releasePointerCapture(event.pointerId); } catch (error) { /* fine */ }

  const to = whereOnTablet(event) || from.at;
  const held = Date.now() - from.when;
  /* Measured in SCREEN pixels, not tablet ones: what counts as "moved" is
   * what the hand did, and at 6x zoom a two-pixel wobble is a twelve-pixel
   * swipe on the tablet nobody intended. */
  const drift = Math.hypot(event.clientX - from.x, event.clientY - from.y);

  showSpot(event);
  let said = null;
  if (drift < 6 && held < 350) {
    said = await api.mirrorTouch({ do: 'tap', x: from.at.x, y: from.at.y });
  } else {
    /* Everything else is a swipe over the time it really took - which makes
     * a long press a swipe that did not move, and that is exactly how the
     * sampler's pads are edited. */
    said = await api.mirrorTouch({ do: 'swipe', x: from.at.x, y: from.at.y,
      x2: to.x, y2: to.y, ms: held });
  }
  if (said && !said.ok) cover(said.why || 'the touch did not land', true);
});

glass.addEventListener('pointercancel', function () { press = null; });

/* TYPING GOES THROUGH TOO, but only while touch is on and only when this
 * window is not being driven by its own shortcuts. */
document.addEventListener('keydown', function (event) {
  if (!touching) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const KEYS = { Backspace: 'DEL', Enter: 'ENTER', Tab: 'TAB',
    ArrowUp: 'DPAD_UP', ArrowDown: 'DPAD_DOWN', Home: 'HOME' };
  if (KEYS[event.key]) {
    event.preventDefault();
    api.mirrorTouch({ do: 'key', key: KEYS[event.key] });
    return;
  }
  /* One printable character at a time. The window's own keys - f, 0, Escape
   * - are only claimed when touch is OFF, or there would be no way to type
   * an "f" into the tablet. */
  if (event.key.length === 1) {
    event.preventDefault();
    api.mirrorTouch({ do: 'text', text: event.key });
  }
}, true);

/* ------------------------------------------------------- the vital signs */

/* WHAT WATCHING COSTS, over the thing being watched.
 *
 * The mirror's own frame rate is measured on THIS side of the wire and handed
 * to the shared block - there is no sense asking the tablet how fast its
 * pictures are arriving here. */
const over = document.getElementById('vitalsOver');
const statsBtn = document.getElementById('stats');
let showStats = true;
let stopVitals = null;
let lastFrames = 0;
let lastFramesAt = 0;

function mirrorCost() {
  return api.mirrorHow().then(function (said) {
    if (!said || !said.ok) return null;
    const now = Date.now();
    let fps = null;
    if (lastFramesAt && now > lastFramesAt) {
      fps = Math.round((said.frames - lastFrames) * 1000 / (now - lastFramesAt) * 10) / 10;
    }
    lastFrames = said.frames;
    lastFramesAt = now;
    return { mirror: Object.assign({}, said, { fps: fps }) };
  }).catch(function () { return null; });
}

function vitalsOn(want) {
  showStats = want;
  over.classList.toggle('gone', !want);
  statsBtn.classList.toggle('on', want);
  try { localStorage.setItem('pine-mirror-stats', want ? '1' : '0'); }
  catch (error) { /* fine */ }
  if (want && !stopVitals && window.pineVitals) {
    stopVitals = window.pineVitals.watch(over, { every: 4000,
      extra: function () { return mirrorCost(); } });
  } else if (!want && stopVitals) {
    stopVitals();
    stopVitals = null;
  }
}

statsBtn.addEventListener('click', function () { vitalsOn(!showStats); });

/* ------------------------------------------------------- capturing it */

/* THE SIDEBAR'S THREE BUTTONS, BROUGHT TO THE PICTURE.
 *
 * "Put an icon for copying the image on the screen to the clipboard... an
 *  icon for saving a video of what is on the screen... and a timeline where
 *  I'm able to adjust the in and out of the video range... the last 30
 *  seconds... and choose if I want to have the audio captured of the
 *  broadcast or my microphone."
 *
 * They call the same handlers the sidebar does, so there is ONE
 * implementation of each rather than two that drift apart. The still is
 * taken at the tablet's full resolution whatever the mirror is streaming:
 * the detail setting is about the cost of a live picture, not about the
 * quality of one that was asked for on purpose. */
let busy = false;

async function capture(saying, work) {
  if (busy) return;
  busy = true;
  cover(saying);
  try {
    const said = await work();
    if (!said || !said.ok) {
      cover((said && said.why) || 'it did not come back', true);
      setTimeout(function () { cover(''); }, 3000);
    } else {
      cover('');
    }
  } catch (error) {
    cover(error.message, true);
    setTimeout(function () { cover(''); }, 3000);
  } finally {
    busy = false;
  }
}

document.getElementById('grab').addEventListener('click', function () {
  capture('Taking the tablet\u2019s picture\u2026', function () {
    return api.glassStill({ edit: false, target: 'tablet' });
  });
});

document.getElementById('film').addEventListener('click', function () {
  capture('Recording 10s of the tablet\u2026', function () {
    return api.glassClip(10, { target: 'tablet' });
  });
});

/* EVERYTHING THE TABLET STILL HOLDS, already recorded.
 *
 * Not "the last thirty": the ring keeps whatever fits in its blob, which on
 * a mostly-static terminal is minutes rather than the design's sixty
 * seconds. Asking for a fixed thirty threw the rest away before the operator
 * could see it. The export window it opens carries the in and out points and
 * the crop, so the choosing happens there - against everything that exists,
 * rather than against a number guessed beforehand. */
document.getElementById('back30').addEventListener('click', function () {
  capture('Pulling everything the tablet still holds\u2026', function () {
    return api.glassClip(0, { target: 'tablet', replay: true });
  });
});

/* --------------------------------------------------------- the camera */

/* LOOKING THROUGH THE TABLET'S CAMERA. It goes on the TABLET's screen and
 * this window is already watching that screen - so there is no second video
 * road to keep alive. The buttons are here as well as on the tablet's own
 * bar because a control you can only press by aiming at a picture of it is a
 * control that fails the moment the picture stalls. */
let camFacing = '';

async function camera(want) {
  try {
    const said = await api.tabletCamera(want);
    if (!said || !said.ok) {
      cover((said && said.why) || 'the camera would not answer', true);
      setTimeout(function () { cover(''); }, 3000);
      return;
    }
    camFacing = want && want.off ? '' : (said.facing || '');
    paintCam();
    cover(want && want.off ? 'The terminal is back.'
      : 'Looking through the ' + camFacing + ' camera.');
    setTimeout(function () { cover(''); }, 2200);
  } catch (error) {
    cover(error.message, true);
  }
}

function paintCam() {
  const rear = document.getElementById('camRear');
  const front = document.getElementById('camFront');
  if (rear) rear.classList.toggle('on', camFacing === 'rear');
  if (front) front.classList.toggle('on', camFacing === 'front');
}

document.getElementById('camRear')?.addEventListener('click',
  function () { camera({ facing: 'rear' }); });
document.getElementById('camFront')?.addEventListener('click',
  function () { camera({ facing: 'front' }); });
document.getElementById('camOff')?.addEventListener('click',
  function () { camera({ off: true }); });

/* ----------------------------------------------------------- the sound */

/* MUTED UNTIL ASKED, and it does not reach into the panel and silence
 * something the operator had already chosen - "muted by default" means this
 * window adds no sound of its own.
 *
 * There is no player here: it drives the monitor the panel already has, for
 * the reasons in main.js. What comes back is what is AUDIBLE, so a route
 * that makes the monitor inert shows as off rather than as on-but-silent. */
const soundBtn = document.getElementById('sound');

/* TWO FACTS, AND THEY ARE NOT THE SAME ONE.
 *
 *   monitorOn - what the switch says, and the only thing a click can
 *               actually change. Tying the toggle to audibility instead
 *               made the button one-way: on a route where the monitor is
 *               inert, every click asked for ON again and it could never be
 *               turned back off. Measured, not imagined.
 *   audible   - whether that switch can do anything right now. */
let monitorOn = false;
let audible = false;

function paintSound(said) {
  monitorOn = !!(said && said.ok && said.monitor);
  audible = monitorOn && !!(said && said.effective);

  /* Lit by the SWITCH, so pressing it always visibly does something. */
  soundBtn.classList.toggle('on', monitorOn);
  /* The icon follows what can be HEARD, so "on but silent" is visible. */
  soundBtn.innerHTML = window.pineIcon
    ? window.pineIcon(audible ? 'c:volume--up--filled' : 'c:volume--mute--filled')
    : '';
  soundBtn.setAttribute('aria-label', monitorOn ? 'Mute the broadcast here'
    : 'Hear the broadcast here');

  if (monitorOn && !audible) {
    /* The state that needed explaining: the switch is on and nothing is
     * coming out, and without this the operator listens for a sound that
     * was never going to arrive. */
    soundBtn.title = 'On, but silent: the broadcast is already playing on the '
      + 'page feed' + (said && said.musicRoute
        ? ' (music is routed ' + said.musicRoute + ')' : '')
      + ', so this app stays quiet to avoid playing it twice.';
  } else {
    soundBtn.title = monitorOn
      ? 'Stop hearing the broadcast in this app'
      : 'Hear the broadcast in this app as well.\nOff by default - the tablet '
        + 'is usually already playing it.';
  }
}

soundBtn.addEventListener('click', async function () {
  try {
    paintSound(await api.mirrorSound(!monitorOn));
  } catch (error) {
    cover(error.message, true);
  }
});

/* ------------------------------------------------------------- on top */

const ontop = document.getElementById('ontop');
ontop.addEventListener('click', async function () {
  try {
    const said = await api.mirrorOnTop();
    ontop.classList.toggle('on', !!(said && said.onTop));
  } catch (error) { /* nothing to say */ }
});

/* --------------------------------------------------------- what it does */

/* THE STRIP TELLS THE TRUTH ABOUT THE STREAM, not about the processes. A
 * pipe whose children are both alive and which has produced no frame for two
 * seconds is stalled, and the operator needs to know that before they start
 * wondering why the tablet is frozen. */
async function watch() {
  for (;;) {
    try {
      const said = await api.mirrorHow();
      if (said && said.ok) {
        const shape = said.width + '×' + said.height;
        how.textContent = said.live
          ? shape + ' · ' + said.frames + ' frames'
            + (said.restarts ? ' · ' + said.restarts + ' restarts' : '')
          : (said.why || 'waiting for the tablet…');
        if (!said.live && said.frames > 0) {
          cover('The picture has stopped. ' + (said.why || 'Reconnecting…'), true);
        } else if (said.live) {
          cover('');
        }
      }
    } catch (error) { /* the window may be closing */ }
    await new Promise(function (go) { setTimeout(go, 1000); });
  }
}

if (window.pineIconUpgrade) window.pineIconUpgrade(document);
paintAuto();
/* Remembered, like every other panel in this app. */
let wantStats = true;
try { wantStats = localStorage.getItem('pine-mirror-stats') !== '0'; }
catch (error) { wantStats = true; }
vitalsOn(wantStats);
/* Touch is remembered too, but it starts OFF the very first time: the
 * picture floats over everything and a first click should not reach a live
 * station by surprise. */
let wantTouch = false;
try { wantTouch = localStorage.getItem('pine-mirror-touch') === '1'; }
catch (error) { wantTouch = false; }
touchOn(wantTouch);
/* ASK, DO NOT SET. Opening the mirror must not change what the operator is
 * already listening to in either direction. */
api.mirrorSound(null).then(paintSound).catch(function () { paintSound(null); });
place();
begin();
