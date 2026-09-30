"""[onecard] Every roulette roll of one moment on ONE card - the line's.

Operator, 2026-09-30: "I need all of the RNG roulette roll results to happen
all on the same card instead of it being split across multiple cards. It's
taking the ES and putting that on another card and then showing the
subsequent results on a different card." Chosen: the line's card (the first
card of the turn, the one with ES) keeps every roll; later rolls for the same
turn are added to it and roll THERE; a later card with no words of its own is
not made at all; a clip card keeps its picture without a second roulette.

The Message view made one card per aired item and each asked System 3 for its
own rows, so the SFX Guy's reaction to a line - linked to the same turn - got
a card of its own with SFX/SFXGUY while the line's card held ES/IRS. And a
line carrying an sfx_roll returned ONLY its SFX row, dropping the line's own
decisions. Usage: onecard_patch.py <script-page.js>   (idempotent)"""
import sys
from pathlib import Path

p = Path(sys.argv[1])
raw = p.read_bytes()
crlf = b"\r\n" in raw
t = raw.decode("utf-8").replace("\r\n", "\n")
if "[onecard]" in t:
    print("already patched:", p)
    sys.exit(0)


def sub(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times in {p}")
    return text.replace(old, new)


t = sub(t, '''    answers: Object.create(null), answerOrder: [], convs: Object.create(null)''',
        '''    answers: Object.create(null), answerOrder: [], convs: Object.create(null),
    turnCards: Object.create(null), turnOrder: []   /* [onecard] tid -> the moment's card */''',
        "state")

t = sub(t, '''      rows.push(mvCounted('SFX', String(sfx.road || 'SFX'), sfx.category, sfx.clip));
      return rows;
    }''', '''      rows.push(mvCounted('SFX', String(sfx.road || 'SFX'), sfx.category, sfx.clip));
      /* [onecard] and the line's own decisions after it - the moment's rolls
         are all on its card, not the sting's alone */
    }''', "sfx-early-return")

t = sub(t, '''      mvAsk(item).then(function (data) { if (mv.cur === cur) mvPlan(cur, data || {rows: [], sources: {main: '', others: []}}); });''',
        '''      mvAsk(item).then(function (data) {
        data = data || {rows: [], sources: {main: '', others: []}};
        var host = mvTurnHost(cur, data);      /* [onecard] */
        if (host) { mvTurnJoin(host, cur, data); return; }
        if (mv.cur === cur) mvPlan(cur, data);
      });''', "ask")

t = sub(t, '''  function mvRetire(cur) {''', '''  /* [onecard] THE MOMENT'S CARD. The first card of a System 3 turn is where
     every roll of that turn lands: a later item of the same turn (the SFX
     Guy's reaction, a line that followed it) hands its rolls to that card
     instead of rolling them on one of its own. Null = this card IS the
     moment's card (registered here) or has no turn to join. */
  function mvTurnHost(cur, data) {
    var tid = String((data && data.tid) || '');
    if (!tid) return null;
    var host = mv.turnCards[tid];
    if (host && host !== cur && host.node && host.node.isConnected) return host;
    mv.turnCards[tid] = cur;
    mv.turnOrder.push(tid);
    while (mv.turnOrder.length > 40) delete mv.turnCards[mv.turnOrder.shift()];
    return null;
  }
  function mvRowKey(r) {
    return String(r.event || '') || [r.fam, r.table, r.main && r.main.dice,
      r.main && r.main.label, r.sub && r.sub.dice].join('|');
  }
  function mvTurnJoin(host, cur, data) {
    var had = Object.create(null);
    ((host.data && host.data.rows) || []).forEach(function (r) { had[mvRowKey(r)] = 1; });
    var fresh = (data.rows || []).filter(function (r) { return !had[mvRowKey(r)]; });
    var bare = cur.item.kind === 'speech' && !String(cur.item.text || '').trim();
    if (bare && cur.node) cur.node.style.display = 'none';   /* a roll-only card: not made */
    cur.joined = host;
    /* this card keeps its words or its picture - never a second roulette */
    var own = {rows: [], sources: data.sources || {main: '', others: []}, cid: data.cid,
      tid: data.tid, stores: data.stores, origin: data.origin};
    if (mv.cur === cur) mvPlan(cur, own);
    if (cur.all) {
      cur.all.textContent = '';
      cur.all.appendChild(make('p', 'sp-mv-note', 'this moment\\'s rolls are on '
        + (host.item.name || 'the line') + '\\'s card'));
    }
    if (!fresh.length) return;
    if (host.data) host.data.rows = (host.data.rows || []).concat(fresh);
    fresh.forEach(function (r) {              /* the Result tab's list, too */
      var line = mvStatic(r);
      if (r.event && data.cid && !r.failed) {
        line.addEventListener('click', function (ev) {
          ev.stopPropagation();
          feedDiceOpen({conversation_id: data.cid, turn_id: data.tid}, {event_id: r.event}, host.item.lid);
        });
      }
      if (host.all) host.all.appendChild(line);
    });
    /* the new tables ROLL on the moment's card, after what it already rolled */
    var sheet = mvRrSheet(host, fresh, 3000);
    sheet.keep = true;
    host.rolls.appendChild(sheet.box);
    host.node.classList.add('sp-mv-joined');
    if (cur.still) { mvRrAt(sheet, 0, true); mvRrResults(sheet); return; }
    var t0 = Date.now();
    (function step() {
      if (!host.node.isConnected) return;
      if (mvRrAt(sheet, Date.now() - t0, false) === 'results') return;
      root.requestAnimationFrame(step);
    })();
  }
  function mvRetire(cur) {''', "helpers")

out = t.replace("\n", "\r\n") if crlf else t
p.write_bytes(out.encode("utf-8"))
print("patched", p)
