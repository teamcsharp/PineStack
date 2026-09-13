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

/* THE FRAME ON THE CLIPBOARD. Drawn from the <img> at its natural size, so
 * what is copied is the camera's own picture rather than the window's. */
document.getElementById('grab').addEventListener('click', function () {
  if (!live.naturalWidth) return say('there is no frame yet', true);
  const plate = document.createElement('canvas');
  plate.width = live.naturalWidth;
  plate.height = live.naturalHeight;
  plate.getContext('2d').drawImage(live, 0, 0);
  if (api.copyImage) {
    api.copyImage(plate.toDataURL('image/png'));
    say('Copied ' + plate.width + '\u00d7' + plate.height + ' to the clipboard.');
  } else {
    say('this window cannot reach the clipboard', true);
  }
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
