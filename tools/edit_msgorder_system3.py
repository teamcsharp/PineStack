#!/usr/bin/env python3
"""[msgorder] The Messenger is a correspondence in AIR ORDER. frontend/system3.js only.

"I still don't know why messages and messenger view do not transition to
message to message to message like they would in an instant messenger ...
they need to be sequential messages in a feed representing that they're going
through the R and G roulette system as designed. These messages are inserted
chaotically and don't make sense and don't work like an instant message
correspondence that I'm able to accurately scrub through and accurately
understand." (operator, 2026-09-28)

What the debugger recorded (msgorder/HANDOFF.md): the thread gave a turn with
no spoken line in the script a made-up place - right after its round's LAST
line, which is history. Interject rounds plan 4-7 turns but only the SFX
board's first sting is ever written, so every one left 3-6 roulette cards
("The SFX board End · turn 7") inside the history above the round on air
(91 at once in 12 minutes), frozen there by the linear rule; their SFX plans
(+-0.3 on turns 1/1000 apart) scattered before turn 1 and after the last; a
turn the board speaks (its line is a board row) never placed at all; and
trim() could never drop such a round.

The rule now: an item is in the correspondence only when the script ledger
gives it a place (block, ord) - a spoken turn at its first line, a run or a
sting at its own row, what hangs off a turn beside it (a plan the turn's
placement says before it, before it; the rest after it; a board turn's at its
sting, which is its message). The ledger only grows at the end, so a new
message is appended; one filed late goes under the air (the linear rule, as
before). A turn planned but not written yet waits out of sight and joins at
the bottom when the station writes it; a round with nothing written waits the
same way (at most UNPLACED_MAX of them, the oldest let go first) and is not
counted against FEED_MAX. Every message that appears calls ONE hook, in air
order: v.arrived(key, node) ([msgview] builds the animation on it).

Edits (marker [msgorder]):
  O1 placesOf/turnPlace/placeOf/cmpPlace: places from the ledger only,
     [block, ord, sub]; null = no place yet.
  O2 collect(): an item with no place is kept out of the thread and out of
     sight (data-unplaced), never removed; it comes back when it has one.
  O3 layoutThread(): a round with nothing in the thread is out of sight.
  O4 addRound(): a round is built in front of the operator (pump) only when
     every turn has its place; otherwise it is drawn out of sight.
  O5 trim(): rounds waiting unwritten are not counted, and are capped.
  O6 enterPast/enterLive: the arrival hook, once per message, in order.
  O7 liveEdge(): the linear rule's edge is also the last message on show
     that aired (the air is often on a record no round owns): a sting whose
     round is fetched after it aired lands under it, never inside history.
     Not during the first fill (seed), which is drawn in the ledger's order.
  O8 shownIndex(): once the air has been seen, the message on air is the next
     to appear. The receipt says 'published' before a line is heard; read as
     "already shown" it kept release() from ever running (replay: 0 arrivals
     in 13 minutes) - the feed was drawn written, never message by message.

  python edit_msgorder_system3.py --check <frontend/system3.js>   0 ready / 2 applied / 1 missing
  python edit_msgorder_system3.py --apply <frontend/system3.js>   idempotent, atomic, keeps endings
"""
import os
import sys
import tempfile

O1_OLD = r'''  /* The ledger's place of each item of a round: [tier, a, b] - tier 0 in the
     script ([block, ord]), tier 1 not yet ([planned at, turn]). */
  const PLACES = new WeakMap();
  function placesOf(conv) {
    if (PLACES.has(conv)) return PLACES.get(conv);
    const lines = (conv.lines || []).filter(l => Number(l.block) > 0).sort(byLedger);
    const first = new Map(), rows = new Map();
    for (const l of lines) {
      const at = [0, Number(l.block), Number(l.ord) || 0];
      if (isSpoken(l)) { if (!first.has(l.turn_id)) first.set(l.turn_id, at); }
      else if (l.line_id) rows.set('sfx:' + l.line_id, at);
    }
    /* [s3-imsg] a later run of a turn stands at its own first line */
    for (const t of conv.turns || []) {
      for (const part of (v.partsOf(conv, t) || []).slice(1)) {
        const l = part.lines[0];
        rows.set(part.key, [0, Number(l.block), Number(l.ord) || 0]);
      }
    }
    const end = lines[lines.length - 1];
    const out = {first, rows, last: end ? [0, Number(end.block), Number(end.ord) || 0] : null, created: convTime(conv),
      turns: new Map((conv.turns || []).map(t => [t.turn_id, t]))};
    PLACES.set(conv, out);
    return out;
  }
  function turnPlace(conv, turnId) {
    const p = placesOf(conv);
    if (p.first.has(turnId)) return p.first.get(turnId);
    const i = Number((p.turns.get(turnId) || {}).index) || 0;
    return p.last ? [0, p.last[1], p.last[2] + 0.5 + i / 1000] : [1, p.created, i];
  }
  function placeOf(entry, key, n) {
    const conv = entry.conv, p = placesOf(conv), turnId = n.dataset.turn || '';
    if ((key.startsWith('sfx:') || key.startsWith('part:')) && p.rows.has(key)) return p.rows.get(key);
    if (p.turns.has(key)) return turnPlace(conv, key);
    const host = turnPlace(conv, turnId), t = p.turns.get(turnId);
    const before = key.startsWith('plan:') && t && t.sfx && t.sfx.placement === 'before';
    return [host[0], host[1], host[2] + (key.startsWith('sfx:') ? 0.6 : before ? -0.3 : 0.3)];
  }
  const cmpPlace = (x, y) => (x[0] - y[0]) || (x[1] - y[1]) || (x[2] - y[2]);
'''

O1_NEW = r'''  /* [msgorder] THE LEDGER'S PLACE OF EACH ITEM, AND ONLY THE LEDGER'S:
     [block, ord, sub] - sub orders what shares a line: -1 hangs before it
     (a plan the turn's placement puts before it), 0 is the line's own
     message, 1 hangs after it, 2 a sting drawn off it. A spoken turn stands
     at its first spoken line; a later run or a sting at its own row; a turn
     the SFX board speaks airs as a board row stamped with its turn - that
     sting IS its message, so the turn card itself has no place, and what
     hangs off it hangs off the sting. null = the ledger has no place for it
     yet (planned, not written - most of an interject round's turns never
     are): it is not in the correspondence. The made-up places that stood
     here (a planned turn "after its round's last line", which is history)
     are what put roulette cards in the middle of what already aired. */
  const PLACES = new WeakMap();
  function placesOf(conv) {
    if (PLACES.has(conv)) return PLACES.get(conv);
    const lines = (conv.lines || []).filter(l => Number(l.block) > 0).sort(byLedger);
    const first = new Map(), rows = new Map(), board = new Map();
    for (const l of lines) {
      const at = [Number(l.block), Number(l.ord) || 0, 0];
      if (isSpoken(l)) { if (!first.has(l.turn_id)) first.set(l.turn_id, at); }
      else if (l.line_id) {
        rows.set('sfx:' + l.line_id, at);
        if (isBoard(l) && l.turn_id && !board.has(l.turn_id)) board.set(l.turn_id, at);
      }
    }
    /* [s3-imsg] a later run of a turn stands at its own first line */
    for (const t of conv.turns || []) {
      for (const part of (v.partsOf(conv, t) || []).slice(1)) {
        const l = part.lines[0];
        rows.set(part.key, [Number(l.block), Number(l.ord) || 0, 0]);
      }
    }
    const out = {first, rows, board, turns: new Map((conv.turns || []).map(t => [t.turn_id, t]))};
    PLACES.set(conv, out);
    return out;
  }
  /* where a turn's message stands: its first spoken line, else (a board turn) its sting; null when unwritten */
  function turnPlace(conv, turnId) {
    const p = placesOf(conv);
    return p.first.get(turnId) || p.board.get(turnId) || null;
  }
  function placeOf(entry, key, n) {
    const conv = entry.conv, p = placesOf(conv), turnId = n.dataset.turn || '';
    if ((key.startsWith('sfx:') || key.startsWith('part:')) && p.rows.has(key)) return p.rows.get(key);
    if (p.turns.has(key)) return p.first.get(key) || null;                 /* a board turn: its sting is its message */
    const host = turnPlace(conv, turnId), t = p.turns.get(turnId);
    if (!host) return null;
    const before = key.startsWith('plan:') && t && t.sfx && t.sfx.placement === 'before';
    return [host[0], host[1], key.startsWith('sfx:') ? 2 : before ? -1 : 1];
  }
  const cmpPlace = (x, y) => (x[0] - y[0]) || (x[1] - y[1]) || (x[2] - y[2]);
  /* [msgorder] out of sight while it has no place - kept, never removed, so it comes back as it was */
  function unplaced(n, off) {
    if (off) { if (n.dataset.unplaced !== '1') { n.dataset.unplaced = '1'; n.style.display = 'none'; } }
    else if (n.dataset.unplaced) { delete n.dataset.unplaced; n.style.display = ''; }
  }
'''

O2_OLD = r'''          if (seen.has(k)) { n.remove(); continue; }  /* one node per item */
          seen.add(k);
          rows.push({key: k, entry, node: n, place: placeOf(entry, k, n), i: rows.length});
'''
O2_NEW = r'''          if (seen.has(k)) { n.remove(); continue; }  /* one node per item */
          seen.add(k);
          const place = placeOf(entry, k, n);
          unplaced(n, !place);                         /* [msgorder] no place in the ledger: not in the thread */
          if (place) rows.push({key: k, entry, node: n, place, i: rows.length});
'''

O3_OLD = r'''    for (const e of feed.values()) {
      const n = used.get(e) || 0;
      while (e.runs.length > Math.max(0, n - 1)) e.runs.pop().section.remove();
'''
O3_NEW = r'''    for (const e of feed.values()) {
      const n = used.get(e) || 0;
      unplaced(e.section, !n && !e.building);      /* [msgorder] nothing of it written yet: out of sight */
      while (e.runs.length > Math.max(0, n - 1)) e.runs.pop().section.remove();
'''

O4_OLD = r'''    if (animate && !reduced()) { queue.push({conv}); pump(); return; }
'''
O4_NEW = r'''    /* [msgorder] built in front of the operator only when every turn has its place in the air's order */
    if (animate && !reduced() && (conv.turns || []).every(t => turnPlace(conv, t.turn_id))) { queue.push({conv}); pump(); return; }
'''

O5_OLD = r'''  function trim() {
    while (feed.size > FEED_MAX) {
'''
O5_NEW = r'''  const UNPLACED_MAX = 12;         /* [msgorder] rounds with nothing written yet, kept out of sight */
  function trim() {
    /* [msgorder] a round with nothing in the thread waits out of sight: not
       counted, and only the newest UNPLACED_MAX are kept (the oldest were
       planned and never written) */
    const placed = new Set(thread.map(k => ownerOf.get(k)));
    const waiting = [...feed.values()].filter(e => !e.building && !placed.has(e.conv.identity.conversation_id))
      .sort((a, b) => convTime(a.conv) - convTime(b.conv));
    while (waiting.length > UNPLACED_MAX) {
      const e = waiting.shift(), id = e.conv.identity.conversation_id;
      for (const s of [e.section, ...e.runs.map(r => r.section)]) s.remove();
      feed.delete(id);
      v.forget(id);
    }
    while (feed.size - waiting.length > FEED_MAX) {
'''

O6A_OLD = r'''    glide();
    if (rhythm()) await wait(ENTER_MS);
    announce(key, 'past', 'end', grace);
  }
'''
O6A_NEW = r'''    glide();
    const came = arrive(key);                      /* [msgorder] the one hook: a new message, in air order */
    if (rhythm()) await wait(ENTER_MS);
    if (came && rhythm() && dueIndex() <= shownIndex()) await Promise.race([came, wait(ARRIVE_CAP_MS)]);   /* nothing else due: it plays out before the next */
    announce(key, 'past', 'end', grace);
  }
  /* [msgorder] A NEW MESSAGE ARRIVED, IN AIR ORDER. Called once per message
     as release() lets it appear - the thread's order, one at a time - with
     its node where it stands. The builder of the arrival ([msgview]:
     v.arrived) decides how it comes together; the order is never its
     business. A promise (or nothing). */
  const ARRIVE_CAP_MS = 9000;
  function arrive(key) {
    const n = itemNode(key);
    if (!n || typeof v.arrived !== 'function') return null;
    try { return Promise.resolve(v.arrived(key, n)).catch(() => false); } catch (e) { return null; }
  }
'''

O6B_OLD = r'''    shownKey = key;
    announce(key, 'live', 'start', grace);
    await startReveal(key);
'''
O6B_NEW = r'''    shownKey = key;
    announce(key, 'live', 'start', grace);
    arrive(key);                                   /* [msgorder] the one hook; on air, the reveal is its arrival */
    await startReveal(key);
'''

O7A_OLD = r"""  function liveEdge() {
    let best = '', at = -1;
    for (const k of [airKey, shownKey, airHead]) { const i = k ? thread.indexOf(k) : -1; if (i > at) { at = i; best = k; } }
    return best;
  }
"""
O7A_NEW = r"""  function liveEdge() {
    let best = '', at = -1;
    for (const k of [airKey, shownKey, airHead]) { const i = k ? thread.indexOf(k) : -1; if (i > at) { at = i; best = k; } }
    /* [msgorder] and the last message on show that has aired, when that is
       further down: the air is often on a record or an ad no round owns, and
       a sting fetched after it aired must land under what is already there,
       never inside it (the feed filled at mount is drawn in the ledger's order) */
    if (!seeding) {
      for (let i = thread.length - 1; i > at; i -= 1) {
        const n = nodes.get(thread[i]);
        if (n && AIRED_STAGES.has(n.dataset.stage)) { at = i; best = thread[i]; break; }
      }
    }
    return best;
  }
  const AIRED_STAGES = new Set(['past', 'written', 'skipped', 'live']);
  let seeding = false;
"""

O7B_OLD = r"""  async function seed() {
    await Promise.race([readSegs(true), sleep(2500)]);"""
O7B_NEW = r"""  async function seed() {
    seeding = true;                                /* [msgorder] the first fill: the ledger's order, whole */
    await Promise.race([readSegs(true), sleep(2500)]);"""

O7C_OLD = r"""    if (cid && !feed.has(cid)) { try { await addRound(cid); } catch (e) { /* keep going */ } }
    paintHead();
    if (follow) toAnchor(false);"""
O7C_NEW = r"""    if (cid && !feed.has(cid)) { try { await addRound(cid); } catch (e) { /* keep going */ } }
    seeding = false;                               /* [msgorder] from here on, what arrives lands under what is there */
    paintHead();
    if (follow) toAnchor(false);"""

O8_OLD = r"""    if (shownKey && pos.has(shownKey)) return pos.get(shownKey);
"""
O8_NEW = r"""    if (shownKey && pos.has(shownKey)) return pos.get(shownKey);
    /* [msgorder] once the air has been seen, the air decides: the station's
       receipt says 'published' before a line is heard, and read as "shown"
       it left nothing ever due - no message ever appeared, the feed was
       drawn written in one go. The one on air comes in next; what follows it
       is still to come. */
    if (airKey && pos.has(airKey)) return pos.get(airKey) - 1;
"""

EDITS = [
    ('O1', O1_OLD, O1_NEW, "[msgorder] THE LEDGER'S PLACE OF EACH ITEM"),
    ('O2', O2_OLD, O2_NEW, 'unplaced(n, !place);'),
    ('O3', O3_OLD, O3_NEW, 'unplaced(e.section, !n && !e.building);'),
    ('O4', O4_OLD, O4_NEW, '[msgorder] built in front of the operator only'),
    ('O5', O5_OLD, O5_NEW, 'const UNPLACED_MAX = 12;'),
    ('O6a', O6A_OLD, O6A_NEW, 'A NEW MESSAGE ARRIVED, IN AIR ORDER'),
    ('O6b', O6B_OLD, O6B_NEW, '[msgorder] the one hook; on air'),
    ('O7a', O7A_OLD, O7A_NEW, 'const AIRED_STAGES = new Set('),
    ('O7b', O7B_OLD, O7B_NEW, '[msgorder] the first fill'),
    ('O7c', O7C_OLD, O7C_NEW, '[msgorder] from here on, what arrives'),
    ('O8', O8_OLD, O8_NEW, '[msgorder] once the air has been seen, the air decides'),
]


def load(path):
    with open(path, 'rb') as f:
        raw = f.read().decode('utf-8')
    crlf = '\r\n' in raw
    return raw.replace('\r\n', '\n'), crlf


def status(text):
    applied, ready, missing = [], [], []
    for name, old, new, mark in EDITS:
        if mark in text:
            applied.append(name)
        elif text.count(old) == 1:
            ready.append(name)
        else:
            missing.append('%s (anchor x%d)' % (name, text.count(old)))
    return applied, ready, missing


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('--check', '--apply'):
        print(__doc__.strip().splitlines()[-2])
        print(__doc__.strip().splitlines()[-1])
        return 2
    path = sys.argv[2]
    text, crlf = load(path)
    applied, ready, missing = status(text)
    print('applied: %s | ready: %s | missing: %s' % (applied, ready, missing))
    if missing:
        return 1
    if sys.argv[1] == '--check':
        return 2 if applied and not ready else 0
    if not ready:
        print('nothing to do')
        return 0
    for name, old, new, mark in EDITS:
        if name in applied:
            continue
        assert text.count(old) == 1, name
        text = text.replace(old, new)
    for name, old, new, mark in EDITS:
        assert mark in text, name
    out = text.replace('\n', '\r\n') if crlf else text
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.msgorder-')
    with os.fdopen(fd, 'wb') as f:
        f.write(out.encode('utf-8'))
    os.replace(tmp, path)
    print('written', path, '(CRLF kept)' if crlf else '')
    return 0


if __name__ == '__main__':
    sys.exit(main())
