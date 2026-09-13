/* THE TABLET'S CAMERA, WATCHED FROM HERE.
 *
 * The tablet is NOT showing the camera - it is still drawing the station.
 * The frames come off an ImageReader with no preview and no activity, and
 * arrive as the same multipart the screen mirror uses, which a bare <img>
 * renders with nothing running per frame.
 */
'use strict';

const api = window.pineDesktop || {};
const live = document.getElementById('live');
const veil = document.getElementById('veil');
const howEl = document.getElementById('how');
const saidEl = document.getElementById('said');

let facing = 'rear';

function cover(words, bad) {
  veil.textContent = words || '';
  veil.classList.toggle('bad', !!bad);
  veil.classList.toggle('gone', !words);
}

function say(words, bad) {
  saidEl.textContent = words || '';
  saidEl.classList.toggle('bad', !!bad);
}

function paintLens() {
  document.getElementById('rear').classList.toggle('on', facing === 'rear');
  document.getElementById('front').classList.toggle('on', facing === 'front');
}

async function begin() {
  let where = null;
  try {
    where = await api.cameraWhere();
  } catch (error) {
    return cover('the camera could not be reached: ' + error.message, true);
  }
  if (!where || !where.ok) {
    return cover((where && where.why) || 'the camera is not open', true);
  }
  facing = where.facing || 'rear';
  paintLens();
  /* The first frame clears the veil: "running" is not "there are pictures",
   * and a black rectangle over a dead stream looks like a covered lens. */
  live.addEventListener('load', function () { cover(''); }, { once: true });
  live.addEventListener('error', function () {
    cover('the picture stopped coming', true);
  });
  live.src = where.url;
  paintLive();
  askRange();
  watch();
}

async function lens(want) {
  if (want === facing) return;
  say('Switching lens\u2026');
  try {
    const said = await api.cameraFace(want);
    if (!said || !said.ok) {
      return say((said && said.why) || 'the lens would not switch', true);
    }
    facing = want;
    paintLens();
    say('Looking through the ' + want + ' camera.');
  } catch (error) {
    say(error.message, true);
  }
}

document.getElementById('rear').addEventListener('click', function () { lens('rear'); });
document.getElementById('front').addEventListener('click', function () { lens('front'); });

/* ------------------------------------------------------- look and dials */

/* THE PICTURE'S OWN CONTROLS, kept on this side on purpose.
 *
 * Gamma, lift and the look are decisions about how the collected light is
 * SHOWN. Doing them on the tablet would bake them into every frame and there
 * would be no way back; here they sit over a picture that is still the
 * camera's. The sensor's dials - shutter, ISO, EV - do go to the tablet,
 * because only the camera can decide how much light to collect. */
let look = 'none';
let gamma = 1;
let stops = 0;
let range = null;          /* what this sensor says it can do */

function paintLive() {
  /* AN APPROXIMATION, FOR FREE. A CSS filter is not in the picture - a canvas
   * drawn from this <img> gets the ORIGINAL - so this is only for the eye,
   * and the real table is applied to the pixels at the moment of capture. */
  const bits = [];
  if (gamma !== 1) bits.push('brightness(' + (1 / gamma).toFixed(3) + ')');
  if (stops) bits.push('brightness(' + Math.pow(2, stops).toFixed(3) + ')');
  if (look.indexOf('filmic') === 0) bits.push('contrast(1.06) saturate(0.96)');
  else if (look === 'flat') bits.push('contrast(0.86) brightness(1.06)');
  else if (look === 'raw') bits.push('brightness(0.6) contrast(1.2)');
  live.style.filter = bits.join(' ');
}

/* The graded pixels, at the camera's own size. Everything that leaves this
 * window goes through here, so what is copied is what was seen. */
function gradedCanvas() {
  if (!live.naturalWidth) return null;
  const plate = document.createElement('canvas');
  plate.width = live.naturalWidth;
  plate.height = live.naturalHeight;
  const paint = plate.getContext('2d');
  paint.drawImage(live, 0, 0);
  if (window.pineLooks && (look !== 'none' || gamma !== 1 || stops)) {
    const pixels = paint.getImageData(0, 0, plate.width, plate.height);
    window.pineLooks.apply(pixels, look, gamma, stops);
    paint.putImageData(pixels, 0, 0);
  }
  return plate;
}

const picker = document.getElementById('look');
if (picker && window.pineLooks) {
  for (const one of window.pineLooks.LOOKS) {
    const choice = document.createElement('option');
    choice.value = one.id;
    choice.textContent = one.name;
    if (one.note) choice.title = one.note;
    picker.appendChild(choice);
  }
  picker.value = look;
  picker.addEventListener('change', function () {
    look = picker.value;
    paintLive();
    say('Look: ' + picker.options[picker.selectedIndex].textContent);
  });
}

const tray = document.getElementById('tray');
document.getElementById('dials').addEventListener('click', function () {
  tray.hidden = !tray.hidden;
  document.getElementById('dials').classList.toggle('on', !tray.hidden);
  if (!tray.hidden) askRange();
});

async function askRange() {
  try {
    const said = await api.cameraTune({});
    range = (said && said.range) || null;
    paintDials();
  } catch (error) { /* the sliders still work in their own units */ }
}

function paintDials() {
  const evSaid = document.getElementById('evSaid');
  if (evSaid) evSaid.textContent = String(document.getElementById('ev').value);
  const g = Number(document.getElementById('gamma').value) / 100;
  document.getElementById('gammaSaid').textContent = g.toFixed(2);
  const st = Number(document.getElementById('stops').value) / 10;
  document.getElementById('stopsSaid').textContent = st.toFixed(1) + ' EV';

  /* THE SENSOR'S OWN LIMITS, not invented ones. The sliders are 0..100 and
   * are mapped onto whatever this camera reports, so "halfway" means halfway
   * between what it can actually do. */
  const sPos = Number(document.getElementById('shutter').value);
  const iPos = Number(document.getElementById('iso').value);
  const sSaid = document.getElementById('shutterSaid');
  const iSaid = document.getElementById('isoSaid');
  if (!sPos) sSaid.textContent = 'auto';
  else if (range && range.shutterMinNs) {
    sSaid.textContent = '1/' + Math.round(1e9 / shutterFor(sPos));
  } else sSaid.textContent = sPos + '%';
  if (!iPos) iSaid.textContent = 'auto';
  else if (range && range.isoMin) iSaid.textContent = String(isoFor(iPos));
  else iSaid.textContent = iPos + '%';
}

function shutterFor(pos) {
  if (!range || !range.shutterMinNs) return 0;
  /* Logarithmic, because shutter speeds are: a linear slider over
   * 1/100000 to 1/2 spends nine tenths of its travel below 1/1000. */
  const lo = Math.log(range.shutterMinNs);
  const hi = Math.log(range.shutterMaxNs);
  return Math.round(Math.exp(lo + (hi - lo) * (pos / 100)));
}

function isoFor(pos) {
  if (!range || !range.isoMin) return 0;
  return Math.round(range.isoMin + (range.isoMax - range.isoMin) * (pos / 100));
}

async function sendDials() {
  const sPos = Number(document.getElementById('shutter').value);
  const iPos = Number(document.getElementById('iso').value);
  const manual = sPos > 0 || iPos > 0;
  try {
    const said = await api.cameraTune({
      auto: !manual,
      shutterNs: manual ? shutterFor(sPos) : 0,
      iso: manual ? isoFor(iPos) : 0,
      ev: Number(document.getElementById('ev').value),
      slowShutter: document.getElementById('slow').checked
    });
    if (said && said.range) range = said.range;
    document.getElementById('autoBtn').classList.toggle('on', !manual);
    paintDials();
  } catch (error) { say(error.message, true); }
}

for (const id of ['ev', 'shutter', 'iso']) {
  document.getElementById(id).addEventListener('input', paintDials);
  document.getElementById(id).addEventListener('change', sendDials);
}
document.getElementById('slow').addEventListener('change', sendDials);

for (const id of ['gamma', 'stops']) {
  document.getElementById(id).addEventListener('input', function () {
    gamma = Number(document.getElementById('gamma').value) / 100;
    stops = Number(document.getElementById('stops').value) / 10;
    paintDials();
    paintLive();
  });
}

document.getElementById('autoBtn').addEventListener('click', function () {
  document.getElementById('shutter').value = '0';
  document.getElementById('iso').value = '0';
  document.getElementById('ev').value = '0';
  sendDials();
});

/* ---------------------------------------------------------- the grabs */

/* THE FRAME ON THE CLIPBOARD, graded and optionally enlarged.
 *
 * The enlargement is the same lanczos-then-unsharp the screenshots use - see
 * shot-enhance.cjs - so a camera frame and a screen capture come out of the
 * same mill and look like each other. */
async function grab(times) {
  const plate = gradedCanvas();
  if (!plate) return say('there is no frame yet', true);
  say(times > 1 ? 'Enlarging \u00d7' + times + '\u2026' : 'Copying\u2026');
  try {
    const said = await api.cameraGrab({ dataUrl: plate.toDataURL('image/png'),
      times: times });
    say(said && said.ok
      ? 'Copied ' + said.width + '\u00d7' + said.height
        + (times > 1 ? ' (\u00d7' + times + ', sharpened)' : '')
        + ' to the clipboard.'
      : ((said && said.why) || 'it would not copy'), !(said && said.ok));
  } catch (error) { say(error.message, true); }
}

document.getElementById('grab1').addEventListener('click', function () { grab(1); });
document.getElementById('grab2').addEventListener('click', function () { grab(2); });
document.getElementById('grab3').addEventListener('click', function () { grab(3); });

/* FIVE TO GET READY, THEN RECORD, THEN SAVE IT WHERE YOU SAY.
 *
 * The countdown is the reason this is not the film button with a timer bolted
 * on: the operator is IN the shot, so after pressing record they have to walk
 * back to where they will be. Five seconds is that walk, and the number is
 * large and over the picture because somebody looking at the lens cannot read
 * a status line. */
const LENGTHS = [5, 10, 15, 20, 30];
let filming = false;

/* THE WAY OUT OF A TAKE.
 *
 * Set by the record button pressed a second time, or by Escape. Both the
 * countdown and the frame loop read it on their next tick, so a cancel lands
 * within a tenth of a second rather than at the end of the take. */
let dropFilm = false;
let filmFor = 10;
try {
  const kept = Number(localStorage.getItem('pine-camera-seconds'));
  if (LENGTHS.indexOf(kept) >= 0) filmFor = kept;
} catch (error) { /* the default is fine */ }

const countEl = document.getElementById('count');
const filmMenu = document.getElementById('filmMenu');

function paintFor() {
  document.getElementById('filmSaid').textContent = filmFor + 's';
}
paintFor();

document.getElementById('filmFor').addEventListener('click', function (event) {
  event.stopPropagation();
  filmMenu.textContent = '';
  for (const many of LENGTHS) {
    const one = document.createElement('button');
    one.type = 'button';
    one.textContent = many + ' seconds';
    if (many === filmFor) one.className = 'on';
    one.addEventListener('click', function () {
      filmFor = many;
      try { localStorage.setItem('pine-camera-seconds', String(many)); }
      catch (err) { /* fine */ }
      paintFor();
      filmMenu.hidden = true;
      say('Record will run for ' + many + ' seconds after the countdown.');
    });
    filmMenu.appendChild(one);
  }
  filmMenu.hidden = false;
  const box = document.getElementById('filmFor').getBoundingClientRect();
  const room = filmMenu.getBoundingClientRect();
  filmMenu.style.left = Math.max(6, box.left) + 'px';
  filmMenu.style.top = Math.max(6, box.top - room.height - 6) + 'px';
});

document.addEventListener('click', function (event) {
  if (!filmMenu.hidden && !filmMenu.contains(event.target)) filmMenu.hidden = true;
});

function countdown(from) {
  return new Promise(function (done) {
    let left = from;
    countEl.hidden = false;
    countEl.classList.remove('rolling');
    countEl.textContent = String(left);
    const tick = setInterval(function () {
      /* Checked before the count, because the five seconds before a take are
       * exactly when somebody realises they do not want it. */
      if (dropFilm) {
        clearInterval(tick);
        countEl.textContent = '';
        done();
        return;
      }
      left -= 1;
      if (left <= 0) {
        clearInterval(tick);
        countEl.textContent = '';
        done();
        return;
      }
      countEl.textContent = String(left);
    }, 1000);
  });
}

document.getElementById('film').addEventListener('click', async function () {
  /* THE SECOND PRESS IS STOP. This used to return, which made the only
   * control on screen dead for the whole take - and the whole take is
   * precisely when somebody wants out of it. */
  if (filming) {
    dropFilm = true;
    say('Stopping \u2014 this take is being thrown away.');
    return;
  }
  if (!gradedCanvas()) return say('there is no picture to record', true);
  filming = true;
  dropFilm = false;
  const seconds = filmFor;
  try {
    say('Get ready\u2026');
    await countdown(5);

    /* RECORDING, and saying so where it can be seen from the shot. */
    countEl.hidden = false;
    countEl.classList.add('rolling');
    const frames = [];
    const began = Date.now();
    await new Promise(function (done) {
      const tick = setInterval(function () {
        /* Before grabbing another frame, not after - there is no reason to
         * collect one more picture for something about to be discarded. */
        if (dropFilm) { clearInterval(tick); return done(); }
        const one = gradedCanvas();
        if (one) frames.push(one.toDataURL('image/jpeg', 0.92));
        const gone = (Date.now() - began) / 1000;
        const left = Math.max(0, seconds - gone);
        countEl.textContent = '\u25cf ' + left.toFixed(0) + 's';
        if (gone >= seconds) { clearInterval(tick); done(); }
      }, 100);
    });
    countEl.hidden = true;
    countEl.classList.remove('rolling');

    /* CANCELLED MEANS NOTHING IS WRITTEN. Not a shorter clip - that is a
     * different gesture, and treating an accidental press as "save what you
     * have" makes it expensive to take back. */
    if (dropFilm) {
      return say('Cancelled \u2014 nothing was saved.');
    }

    say('Writing ' + frames.length + ' frames\u2026');
    const made = await api.cameraRecord({ frames: frames,
      seconds: (Date.now() - began) / 1000 });
    if (made && made.canceled) say('Not saved.');
    else say(made && made.ok
      ? 'Saved ' + Math.round(made.bytes / 1024) + ' kB \u2014 '
        + made.frames + ' frames. Opening the folder.'
      : ((made && made.why) || 'it could not be written'), !(made && made.ok));
  } catch (error) {
    say(error.message, true);
  } finally {
    countEl.hidden = true;
    countEl.classList.remove('rolling');
    filming = false;
    dropFilm = false;
  }
});

/* ESCAPE IS THE SAME DECISION FROM THE KEYBOARD, and it comes first: an
 * operator standing in front of the lens with a countdown running is not
 * aiming a mouse at a small button. It closes the length menu otherwise, so
 * the key always does the nearest undoable thing. */
document.addEventListener('keydown', function (event) {
  if (event.key !== 'Escape') return;
  if (filming) {
    event.preventDefault();
    dropFilm = true;
    say('Stopping \u2014 this take is being thrown away.');
    return;
  }
  if (filmMenu && !filmMenu.hidden) {
    event.preventDefault();
    filmMenu.hidden = true;
  }
});

/* THE ADDRESS, FOR SOMETHING ELSE TO USE. The camera is plain MJPEG on a
 * fixed loopback port, which ComfyUI, OBS, ffmpeg and a browser all read - so
 * the useful thing this window can do for them is hand over the URL. */
document.getElementById('copyUrl')?.addEventListener('click', async function () {
  try {
    const where = await api.cameraWhere();
    if (!where || !where.ok) return say((where && where.why) || 'no address yet', true);
    const words = where.stream + '\n' + where.still;
    if (api.copyText) api.copyText(words);
    say('Copied: ' + where.stream + '  ·  single frame at ' + where.still
      + (where.known ? '' : ' (the usual port was taken, so this one is '
        + 'temporary)'), !where.known);
  } catch (error) { say(error.message, true); }
});

const ontop = document.getElementById('ontop');
ontop.addEventListener('click', async function () {
  try {
    const said = await api.mirrorOnTop();
    ontop.classList.toggle('on', !!(said && said.onTop));
  } catch (error) { /* nothing to say */ }
});

/* THE STRIP TELLS THE TRUTH ABOUT THE STREAM, not about the processes: a
 * connection that is alive and has produced no frame in two seconds is
 * stalled, and the operator should not have to work that out by staring. */
async function watch() {
  for (;;) {
    try {
      const said = await api.cameraWhere();
      if (said && said.ok) {
        howEl.textContent = said.live
          ? (live.naturalWidth || '?') + '\u00d7' + (live.naturalHeight || '?')
            + ' \u00b7 ' + said.frames + ' frames'
          : (said.why || 'waiting for the camera\u2026');
        if (said.live) cover('');
        else if (said.frames > 0) cover('The picture has stopped.', true);
      }
    } catch (error) { /* the window may be closing */ }
    await new Promise(function (go) { setTimeout(go, 1000); });
  }
}

if (window.pineIconUpgrade) window.pineIconUpgrade(document);
begin();
