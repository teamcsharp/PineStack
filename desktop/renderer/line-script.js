/* THE SCRIPT BESIDE THE LINE, IN CONVERSATIONAL CONTEXT.
 *
 * "In this window i want to see the response. And what came before what was
 *  next and even be able to review the entire script in a sidebar of the line
 *  in conversational context with the ability to right click lines and be
 *  able to export them to mp3 or the conversation chain in full or the entire
 *  segment from the script view."
 *
 * TWO READINGS OF "CONTEXT", AND THEY ARE NOT THE SAME THING.
 *
 *   THE ROUND     the rows sharing this line's sid, in turn order. This is
 *                 the conversation as WRITTEN - one exchange, start to
 *                 finish, the thing the writer actually composed.
 *   THE AIR       the rows either side in broadcast order, whatever round
 *                 they came from. This is what a listener HEARD, which is
 *                 not the same and is frequently the more interesting one -
 *                 a round can be interrupted by a caller, a sting, a record.
 *
 * Both are offered because correcting "the flow of conversations" needs both:
 * the round tells you what the writer intended, the air tells you what
 * actually happened to it.
 *
 * EXPORT IS THREE SIZES OF THE SAME RECORDING, named apart because an
 * operator who asked for one and got another would only find out on playback:
 * this line, the whole round welded together, or the run of air around it.
 */
'use strict';

/* WRAPPED, BECAUSE THIS SHARES A GLOBAL SCOPE WITH script-flow.js.
 *
 * Classic scripts in one document all declare into the SAME top-level scope,
 * so a second `const api = ...` here is not shadowing - it is a SyntaxError
 * that kills whichever file loads second. Measured: script-flow.js stopped
 * executing entirely, the chart never drew, and window.onerror reported only
 * "Script error." because the file was cross-origin. Nothing about the
 * symptom pointed at this line.
 *
 * line-reach.js is wrapped for the same reason. */
(function () {

const api = window.pineDesktop || {};

/* Filled by the inspector when it opens. */
let chain = [];
let around = [];
let thisId = '';
let onPick = null;

function say(words, bad) {
  const el = document.getElementById('scriptSaid');
  if (!el) return;
  el.textContent = words || '';
  el.className = bad ? 'scriptSaid bad' : 'scriptSaid';
}

/* ------------------------------------------------------------ the menu */

const menu = document.getElementById('scriptMenu');

function item(label, can, go) {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = label;
  b.disabled = !can;
  if (can) {
    b.addEventListener('click', () => { shut(); go(); });
  }
  return b;
}

function shut() { if (menu) menu.hidden = true; }

document.addEventListener('click', (event) => {
  if (menu && !menu.hidden && !menu.contains(event.target)) shut();
});

/**
 * The three sizes, plus the ways into the rest of the window.
 *
 * `row` is the line right-clicked, which is NOT necessarily the line the
 * window is about - the whole point of the sidebar is that you can reach the
 * ones around it.
 */
function openMenu(atX, atY, row) {
  if (!menu) return;
  menu.textContent = '';
  const playable = !!(row.id);

  menu.appendChild(item('Play this line', playable, () => play(row)));
  menu.appendChild(document.createElement('hr'));
  menu.appendChild(item('Export this line to mp3', playable,
    () => save(row, 'line')));
  /* THE WHOLE ROUND, welded. &whole=1 hands back the surrounding burst
   * rather than the one row - a different length of the same recording. */
  menu.appendChild(item('Export the conversation in full',
    playable && !!row.sid, () => save(row, 'round')));
  menu.appendChild(item('Export this whole segment', playable,
    () => save(row, 'segment')));
  menu.appendChild(document.createElement('hr'));
  menu.appendChild(item('Inspect this line instead', playable,
    () => { if (onPick) onPick(row); }));
  menu.appendChild(item('Copy its text', !!row.text, () => {
    if (api.copyText) api.copyText(String(row.text || ''));
    say('Copied.');
  }));
  menu.appendChild(item('Copy its id', !!row.id, () => {
    if (api.copyText) api.copyText(String(row.id || ''));
    say('Copied ' + row.id);
  }));

  menu.hidden = false;
  const room = document.body.getBoundingClientRect();
  const box = menu.getBoundingClientRect();
  menu.style.left = Math.min(atX, room.width - box.width - 6) + 'px';
  menu.style.top = Math.min(atY, room.height - box.height - 6) + 'px';
}

/* ----------------------------------------------------------- the doing */

async function play(row) {
  try {
    say('Playing…');
    /* THE WHOLE ROW, not just its id: regionAudio in main.js can use a
     * clip_media path or a music track directly when the row carries
     * one, rather than asking the booth to cut what it already has. */
    const done = await api.inspectPlay(row);
    say(done && done.ok ? '' : ((done && done.why) || 'it would not play'),
      !(done && done.ok));
  } catch (error) { say(error.message, true); }
}

async function save(row, how) {
  const named = { line: 'this line', round: 'the conversation',
    segment: 'the segment' }[how] || how;
  try {
    say('Fetching ' + named + '…');
    const done = await api.inspectExport({
      id: row.id, sid: row.sid || '', how,
      /* The air run is assembled from what the sidebar is already showing,
       * so the export matches what was on screen rather than a second,
       * possibly different, read of the feed. */
      ids: how === 'segment' ? around.map((r) => r.id) : null
    });
    if (!done || !done.ok) {
      return say((done && done.why) || 'it did not come back', true);
    }
    say(done.canceled ? 'Not saved.'
      : 'Saved ' + Math.round((done.bytes || 0) / 1024) + ' kB — '
        + (done.path || ''));
  } catch (error) { say(error.message, true); }
}

/* ---------------------------------------------------------- the drawing */

function line(row, where) {
  const el = document.createElement('div');
  el.className = 'sline' + (row.id === thisId ? ' here' : '');
  el.dataset.lineId = row.id || '';

  const who = document.createElement('b');
  who.textContent = row.name || row.who || '?';
  el.appendChild(who);

  /* WHICH TURN OF THE ROUND, because "what came before" inside one written
   * exchange is a different question from what aired before it. */
  if (where === 'round' && row.turn !== null && row.turn !== undefined) {
    const turn = document.createElement('em');
    turn.textContent = (Number(row.turn) + 1) + '/' + (row.turns || '?');
    el.appendChild(turn);
  }
  if (where === 'air' && row.kind) {
    const kind = document.createElement('em');
    kind.textContent = row.kind;
    el.appendChild(kind);
  }

  const what = document.createElement('i');
  what.textContent = String(row.text || '');
  el.appendChild(what);

  el.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    event.stopPropagation();
    openMenu(event.clientX, event.clientY, row);
  });
  el.addEventListener('dblclick', () => { if (onPick) onPick(row); });
  return el;
}

function draw() {
  const box = document.getElementById('scriptBody');
  if (!box) return;
  box.textContent = '';
  const which = document.querySelector('.scriptTab.on');
  const where = (which && which.dataset.where) || 'round';
  const rows = where === 'round' ? chain : around;

  if (!rows.length) {
    const none = document.createElement('div');
    none.className = 'none';
    none.textContent = where === 'round'
      /* SAID, NOT BLANK. A line with no sid genuinely has no written round
       * behind it - interjects are the big case - and an empty pane would
       * read as a fault in this window rather than a fact about the line. */
      ? 'The station kept no written round for this line, so there is no '
        + 'conversation to show. Lines that arrive as interjects are written '
        + 'one at a time and carry no round.'
      : 'Nothing of the surrounding air came through.';
    box.appendChild(none);
    return;
  }

  for (const row of rows) box.appendChild(line(row, where));

  /* Put the line itself on screen rather than making somebody find it. */
  const here = box.querySelector('.sline.here');
  if (here && here.scrollIntoView) {
    here.scrollIntoView({ block: 'center' });
  }
}

function tabs() {
  for (const tab of document.querySelectorAll('.scriptTab')) {
    tab.addEventListener('click', () => {
      for (const other of document.querySelectorAll('.scriptTab')) {
        other.classList.toggle('on', other === tab);
      }
      draw();
    });
  }
}

/** Called by the inspector once it has its hand-over. */
window.pineScript = {
  fill(held, pick) {
    chain = (held && held.chain) || [];
    around = (held && held.around) || [];
    thisId = String((held && held.region && held.region.id) || '');
    onPick = pick || null;
    const count = document.getElementById('scriptCount');
    if (count) {
      count.textContent = chain.length
        ? chain.length + ' in the round'
        : (around.length ? 'no written round' : '');
    }
    if (held && held.feedWhy) say(held.feedWhy, true);
    tabs();
    draw();
  },
  redraw: draw
};

})();
