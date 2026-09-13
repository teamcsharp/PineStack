/* CHANGING HOW A LINE IS PUT TOGETHER, AND PUT ON THE AIR.
 *
 * "From there I can make edits to how it's being synthesized and put together
 *  and brought together and put on the air."
 *
 * FIVE THINGS THE STATION WILL ACTUALLY ACCEPT, and they are different in
 * kind - which is why they are not one button:
 *
 *   REWRITE THIS TURN     you write the words. Sent with the text it is
 *                         REPLACING, so if the round moved underneath you
 *                         the station refuses rather than overwriting
 *                         somebody else's edit.
 *   BACK TO THE ROOM      you write a NOTE and the writer rewrites it. The
 *                         note does two jobs: it fixes this line now, and
 *                         kept as standing it is carried into every future
 *                         round of that road - which is the difference
 *                         between correcting a line and correcting a habit.
 *   TINT JUST THIS LINE   asks for a tinted version and applies NOTHING, so
 *                         the two can be read side by side first.
 *   RECORD IT AGAIN       sends the round back to the recording room.
 *                         `bypass` skips the tint pass for this round only.
 *   UP / DOWN             the editorial feedback the station already uses to
 *                         bound future writing. The smallest of the five and
 *                         the only one that is not a change to this line.
 *
 * EVERY ONE OF THEM NEEDS A sid, and 30% of the feed has none - measured:
 * every `interject` row, which is real dialogue written one line at a time
 * with no round behind it. Those are disabled here with the reason on them
 * rather than offered and then failing, because a control that fails after
 * you commit to it is worse than one that never offered.
 *
 * NOTHING HERE HAPPENS QUIETLY. Each one says what it did, and the two that
 * reach the air - recording and revising - ask first. This window is opened
 * to understand a line; changing what the station broadcasts should never be
 * one stray click away from reading.
 */
'use strict';

(function () {

const api = window.pineDesktop || {};

let line = null;          /* the row being inspected */
let sid = '';
let turn = null;

function el(id) { return document.getElementById(id); }

function say(words, bad) {
  const box = el('editSaid');
  if (!box) return;
  box.textContent = words || '';
  box.className = bad ? 'editSaid bad' : 'editSaid';
}

/* WHY SOMETHING CANNOT BE DONE, in the one place that decides it. */
function blocked() {
  if (!line || !line.id) return 'There is no line here to change.';
  if (!sid) {
    return 'The station kept no written round for this line, so there is '
      + 'nothing to edit. Lines that arrive as interjects are written one at '
      + 'a time and carry no round.';
  }
  return '';
}

/**
 * Do something, saying what happened.
 *
 * `needsRound` is false for the votes, which are about the line as HEARD and
 * not about the round behind it. Without that distinction the vote buttons
 * were drawn ENABLED for an interject and then refused when pressed - an
 * enabled control that says no is worse than a disabled one, because you
 * only find out after committing to it.
 */
async function ask(what, go, needsRound) {
  const why = needsRound === false
    ? (line && line.id ? '' : 'There is no line here.')
    : blocked();
  if (why) return say(why, true);
  try {
    say(what + '…');
    const done = await go();
    if (!done || done.ok === false) {
      return say((done && (done.why || done.detail)) || 'the station refused it',
        true);
    }
    return done;
  } catch (error) {
    say(error.message, true);
    return null;
  }
}

/* ------------------------------------------------------------ the doing */

async function rewrite() {
  const box = el('editText');
  const words = String(box.value || '').trim();
  if (!words) return say('Write the line first.', true);
  if (words === String(line.text || '').trim()) {
    return say('That is what it already says.', true);
  }
  if (turn === null || turn === undefined) {
    return say('The station did not record which turn of the round this was, '
      + 'so there is nothing to address the rewrite to.', true);
  }
  const done = await ask('Rewriting', () => api.lineEdit({
    sid, index: turn, text: words,
    /* WHAT IT IS REPLACING, so the station can refuse if the round moved
     * underneath us rather than overwriting somebody else's edit. */
    was: String(line.text || '')
  }));
  if (done) say('Rewritten. It will be recorded again before it airs.');
}

async function revise() {
  const note = String(el('editNote').value || '').trim();
  if (!note) {
    return say('A revision needs a note saying what to change.', true);
  }
  const standing = !!el('editStanding').checked;
  if (!window.confirm('Send this back to the writer room?\n\n' + note
    + (standing
      ? '\n\nKept as standing: every future round of this road will carry '
        + 'the note.'
      : '\n\nThis round only.'))) return;
  const done = await ask('Sending it back', () => api.lineRevise({
    sid, note, standing
  }));
  if (done) {
    say(standing
      ? 'Sent. The note is kept, so the next one of these is written '
        + 'knowing it.'
      : 'Sent back for this round.');
  }
}

async function tintOne() {
  const done = await ask('Asking for a tint', () => api.lineTint({
    sid, index: turn
  }));
  if (!done) return;
  /* NOTHING IS APPLIED - the route hands both back so they can be read
   * against each other first. */
  const was = String(done.plain || done.was || line.text || '');
  const now = String(done.tinted || done.text || '');
  const out = el('editTint');
  out.hidden = false;
  out.textContent = '';
  const a = document.createElement('div');
  a.className = 'tintWas';
  a.textContent = 'as written: ' + was;
  const b = document.createElement('div');
  b.className = 'tintNow';
  b.textContent = 'tinted: ' + (now || '(the tint came back empty)');
  out.appendChild(a);
  out.appendChild(b);
  say('Nothing has been applied — this is the tint offered, for reading.');
}

async function record() {
  const bypass = !!el('editBypass').checked;
  if (!window.confirm('Send this round back to the recording room?'
    + (bypass ? '\n\nSkipping the tint pass for this round.' : ''))) return;
  const done = await ask('Sending it to be recorded', () => api.lineRecord({
    sid, bypass
  }));
  if (done) say('Sent to the recording room.');
}

async function vote(up) {
  const done = await ask(up ? 'Marking it good' : 'Marking it poor',
    () => api.lineVote({ id: line.id, up }), false);
  if (done) {
    say(up ? 'Marked good. It bounds what gets written next.'
      : 'Marked poor. It bounds what gets written next.');
  }
}

/* ---------------------------------------------------------- the drawing */

function paint() {
  const why = blocked();
  const off = !!why;
  for (const id of ['editRewrite', 'editRevise', 'editTintBtn', 'editRecord']) {
    const b = el(id);
    if (!b) continue;
    b.disabled = off;
    b.title = why || '';
  }
  /* The votes are about the line as HEARD, not about its round, so they
   * survive a missing sid - the one thing an interject can still do. */
  for (const id of ['editUp', 'editDown']) {
    const b = el(id);
    if (b) b.disabled = !(line && line.id);
  }
  const note = el('editWhy');
  if (note) {
    note.textContent = why;
    note.hidden = !why;
  }
}

window.pineEdit = {
  fill(held) {
    const region = (held && held.region) || {};
    /* The chain is the authority on turn/sid: the region comes from whatever
     * view was right-clicked and may be a thinner copy. */
    const chain = (held && held.chain) || [];
    const mine = chain.find((r) => r && r.id === region.id);
    line = mine || region;
    sid = String(line.sid || region.sid || '');
    turn = (line.turn === undefined) ? null : line.turn;

    const box = el('editText');
    if (box) box.value = String(line.text || line.said || '');

    const where = el('editWhere');
    if (where) {
      where.textContent = sid
        ? 'round ' + sid + (turn === null ? '' : ', turn ' + (turn + 1))
        : 'no written round';
    }

    el('editRewrite')?.addEventListener('click', rewrite);
    el('editRevise')?.addEventListener('click', revise);
    el('editTintBtn')?.addEventListener('click', tintOne);
    el('editRecord')?.addEventListener('click', record);
    el('editUp')?.addEventListener('click', () => vote(true));
    el('editDown')?.addEventListener('click', () => vote(false));
    paint();
  }
};

})();
