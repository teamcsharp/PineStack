"""[onecard] ONE MOMENT, ONE CARD - the road that decides which card owns a roll.

Operator, 2026-09-30, after the first [onecard] install: "when building these
cards. I dont want the info being moved to another card. I need a single card
to show the entire roulette rolodex result. One card."

What still split one moment across cards after 4447544:
  1. the moment was keyed by System 3 turn id ONLY. A sting off the board
     inside a line ("<line>-punct-1", the "#049af8d7-p1" card) has no turn of
     its own, so its roll (book: sfx_ads 2 of 85 / PineBox-H3_00200_) stayed
     on the clip's card while the line's card said "SFX 60 no clip";
  2. a join onto the moment's card appended a SECOND roll sheet to a card that
     had already cleared its rolls (digital, after air) or gone to the past
     (".sp-mv-past .sp-mv-rolls" hidden) - the joined rolls were never seen;
  3. the Result pin (and every history card) asked for the tapped card's OWN
     rows only - pinning the SFX Guy's reaction replayed its rolls on its card,
     pinning the line replayed the line's alone;
  4. a live card whose line came back on air got a second card with the same
     id (only history twins were removed);
  5. while it rolled, a card folded away every table but the last two ("only
     the last folded one stays in view") - ES1 vanished off the line's card as
     RS1 and SFX rolled, and a card landed late (skip) never showed it again;
     and mvPlan capped the tables at 6.

The road now: a moment is its System 3 turn AND the line it is part of
('t:<turn>' / 'l:<line without -punct-N>'), with its members and every row
they rolled. The moment's card is the earliest card of it still in the list;
a later member's rolls land there in ONE sheet (landed tables kept, new ones
rolling after them) and the card keeps that tally in view; a pin of any member
pins the moment's card with every row of the moment (asking the cards beside
it and the line's stings the history leaves out); a card for a key already in
the list replaces the earlier one; the tables stay on the card as the next one
rolls, all of them. Usage: onecard_moment_patch.py <script-page.js|.css>...
(idempotent)"""
import sys
from pathlib import Path

MARK = "[onecard-moment]"


def sub(text, old, new, name, p):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times in {p}")
    return text.replace(old, new)


def patch_js(t, p):
    t = sub(t, '''    turnCards: Object.create(null), turnOrder: []   /* [onecard] tid -> the moment's card */''',
            '''    turnCards: Object.create(null), turnOrder: []   /* [onecard-moment] 't:<turn>' / 'l:<line>' -> the moment */''',
            "state", p)

    t = sub(t, '''    mv.cur = cur;
    cur.media = media;                         /* [msgmedia] */''',
            '''    mv.cur = cur;
    node.__mvCur = cur;                        /* [onecard-moment] the card, off its node: the moment finds its mates */
    cur.media = media;                         /* [msgmedia] */''',
            "node-cur", p)

    t = sub(t, '''      mvAsk(item).then(function (data) {
        data = data || {rows: [], sources: {main: '', others: []}};
        var host = mvTurnHost(cur, data);      /* [onecard] */
        if (host) { mvTurnJoin(host, cur, data); return; }
        if (mv.cur === cur) mvPlan(cur, data);
      });''',
            '''      mvAsk(item).then(function (data) {
        mvMomentLand(cur, data || {rows: [], sources: {main: '', others: []}});   /* [onecard-moment] */
      });''',
            "ask", p)

    old_road_start = t.index('''  /* [onecard] THE MOMENT'S CARD.''')
    old_road_end = t.index('''  function mvRetire(cur) {''')
    t = t[:old_road_start] + ROAD + t[old_road_end:]

    t = sub(t, '''    var rows = (data.rows || []).slice(0, 6);''',
            '''    var rows = (data.rows || []).slice();      /* [onecard-moment] every table the moment rolled - no cap */''',
            "cap", p)

    t = sub(t, '''    if (cur.sheet) cur.rolls.appendChild(cur.sheet.box);''',
            '''    if (cur.sheet) cur.rolls.appendChild(cur.sheet.box);
    /* [onecard-moment] every table stays on the card as the next one rolls:
       nothing folds away, not while it rolls, not when it lands late */
    if (cur.sheet) { cur.sheet.keep = true; cur.sheet.box.classList.add('sp-rr-keep'); }''',
            "keep", p)

    t = sub(t, '''    cur.node.classList.add('sp-mv-past', 'sp-mv-hist');''',
            '''    cur.node.classList.add('sp-mv-past', 'sp-mv-hist');
    cur.node.__mvCur = cur;                    /* [onecard-moment] */''',
            "hist-cur", p)

    t = sub(t, '''    var twin = stage.querySelectorAll('.sp-mv-hist[data-mv-key="' + String(item.key).replace(/"/g, '') + '"]');
    [].slice.call(twin).forEach(function (n) { if (!mv.pin || mv.pin.cur.node !== n) n.parentNode.removeChild(n); });''',
            '''    /* [onecard-moment] one card per id: an earlier card of this key - history
       or live (its line came back on air) - goes; the moment keeps its rows */
    var twin = stage.querySelectorAll('.sp-mv-item[data-mv-key="' + String(item.key).replace(/"/g, '') + '"]');
    [].slice.call(twin).forEach(function (n) {
      if (n === node || (mv.pin && mv.pin.cur.node === n)) return;
      if (mv.io) { try { mv.io.unobserve(n); } catch (e) { /* gone */ } }
      n.parentNode.removeChild(n);
    });''',
            "twins", p)

    t = sub(t, '''  function mvPinToggle(cur) {
    if (mv.pin && mv.pin.cur === cur) { mv.pin.why = 'the Result tapped again'; mvUnpin(); return; }
    mvPin(cur);
  }
  function mvPin(cur) {''',
            '''  function mvPinToggle(cur) {
    /* [onecard-moment] a card whose rolls are on the moment's card pins that card */
    var to = cur.joined && cur.joined.node && cur.joined.node.isConnected ? cur.joined : cur;
    if (mv.pin && (mv.pin.cur === cur || mv.pin.cur === to || mv.pin.from === cur)) { mv.pin.why = 'the Result tapped again'; mvUnpin(); return; }
    mvPin(to);
  }
  function mvPin(cur, hop) {''',
            "pin-toggle", p)

    t = sub(t, '''    var P = mv.pin = {cur: cur, cycles: 0,''', '''    var P = mv.pin = {cur: cur, from: hop || null, cycles: 0,''', "pin-from", p)

    t = sub(t, '''    (cur.data ? Promise.resolve(cur.data) : mvAsk(cur.item).then(null, function () { return null; })).then(function (data) {
      if (mv.pin !== P) return;
      cur.data = data || {rows: [], sources: {main: '', others: [], why: {}}};
      P.armed = true;                          /* the next frame starts the first cycle */''',
            '''    /* [onecard-moment] the roll replayed is the MOMENT's, on the moment's card */
    mvMomentGather(cur).then(function (got) {
      if (mv.pin !== P) return;
      if (!hop && got.card && got.card !== cur) { P.why = 'handed to the card of its moment'; mvPin(got.card, cur); mvPinReveal(got.card); return; }
      cur.data = got.data || {rows: [], sources: {main: '', others: [], why: {}}};
      P.armed = true;                          /* the next frame starts the first cycle */''',
            "pin-gather", p)

    t = sub(t, '''    if (cur.sheet) { cur.sheet.keep = false; cur.sheet.box.classList.remove('sp-rr-keep'); }
''', '''    /* [onecard-moment] the tables stay on the card (mvPlan keeps them) */
''', "unpin-keep", p)
    return t


ROAD = r'''  /* [onecard-moment] ONE MOMENT, ONE CARD. "I dont want the info being moved
     to another card. I need a single card to show the entire roulette
     rolodex result. One card." (the operator, 2026-09-30)
     A moment is its System 3 turn AND the line it is part of: a sting off
     the board inside a line ("<line>-punct-1") has no turn of its own and is
     that line's moment all the same. mv.turnCards maps 't:<turn>' and
     'l:<line>' to one record - its member items, the rows each rolled, the
     card that shows them. The moment's card is the earliest card of it still
     in the list; every roll of every member lands THERE, and nowhere else. */
  var MV_MATES = 3;
  function mvBaseLid(lid) { return String(lid || '').replace(/-(?:punct-|p)\d+$/, ''); }
  function mvMomentKeys(item, data) {
    var keys = [];
    var tid = String((data && data.tid) || '');
    if (tid) keys.push('t:' + tid);
    var base = mvBaseLid(item && item.lid);
    if (base) keys.push('l:' + base);
    return keys;
  }
  function mvMomentLink(m, keys) {
    keys.forEach(function (k) {
      if (mv.turnCards[k] === m) return;
      mv.turnCards[k] = m;
      mv.turnOrder.push(k);
    });
    while (mv.turnOrder.length > 80) {
      var old = mv.turnOrder.shift();
      if (mv.turnOrder.indexOf(old) < 0) delete mv.turnCards[old];
    }
    return m;
  }
  function mvMomentOf(item, data) {
    var keys = mvMomentKeys(item, data), m = null;
    for (var i = 0; i < keys.length && !m; i += 1) m = mv.turnCards[keys[i]] || null;
    return mvMomentLink(m || {host: null, members: [], rows: [], n: 0}, keys);
  }
  /* a member: its item, the card that shows it (none for a sting the history
     leaves out), the rows IT rolled */
  function mvMomentMember(m, item, cur, rows) {
    var lid = String((item && item.lid) || '');
    for (var i = 0; i < m.members.length; i += 1) {
      var x = m.members[i];
      if (x.lid !== lid) continue;
      if (cur) x.cur = cur;                   /* the same line's newer card */
      x.rows = rows || [];
      return x;
    }
    var y = {lid: lid, base: mvBaseLid(lid), cur: cur || null, rows: rows || [], n: m.n};
    m.n += 1;
    m.members.push(y);
    return y;
  }
  function mvMomentList() { return mv.stage ? [].slice.call(mv.stage.querySelectorAll('.sp-mv-item')) : []; }
  function mvMomentShown(cur) {
    return !!(cur && cur.node && cur.node.isConnected && cur.node.style.display !== 'none');
  }
  /* the moment's card: the earliest of its cards still in the list */
  function mvMomentCard(m) {
    var list = mvMomentList(), best = null, at = Infinity;
    m.members.forEach(function (x) {
      if (!mvMomentShown(x.cur)) return;
      var i = list.indexOf(x.cur.node);
      if (i >= 0 && i < at) { at = i; best = x.cur; }
    });
    return best;
  }
  /* every row of the moment, once each, in the order its members aired: a
     card gone from the list first, a line's stings right after the line */
  function mvMomentRows(m) {
    var list = mvMomentList();
    var pos = function (x) {
      if (x.cur && x.cur.node && x.cur.node.isConnected) return list.indexOf(x.cur.node) * 2;
      for (var i = 0; i < m.members.length; i += 1) {
        var b = m.members[i];
        if (b !== x && b.lid === x.base && b.cur && b.cur.node && b.cur.node.isConnected) return list.indexOf(b.cur.node) * 2 + 1;
      }
      return -1;
    };
    var ord = m.members.map(function (x) { return {x: x, p: pos(x)}; });
    ord.sort(function (a, b) { return (a.p - b.p) || (a.x.n - b.x.n); });
    var had = Object.create(null), rows = [];
    ord.forEach(function (o) {
      (o.x.rows || []).forEach(function (r) {
        var k = mvRowKey(r);
        if (had[k]) return;
        had[k] = 1;
        rows.push(r);
      });
    });
    return rows;
  }
  function mvRowKey(r) {
    return String(r.event || '') || [r.fam, r.table, r.main && r.main.dice,
      r.main && r.main.label, r.sub && r.sub.dice, r.sub && r.sub.label].join('|');
  }
  /* a live card's answer: it joins its moment - onto the moment's card when
     one is in the list, or as that card, with every roll the moment made */
  function mvMomentLand(cur, data) {
    var m = mvMomentOf(cur.item, data);
    mvMomentMember(m, cur.item, cur, data.rows || []);
    var host = m.host;
    if (host && host !== cur && mvMomentShown(host)) { mvTurnJoin(host, cur, data, m); return; }
    m.host = cur;
    var plan = mvMerge(data, {});
    plan.rows = mvMomentRows(m);
    m.rows = plan.rows;
    cur.data = plan;
    if (mv.cur === cur) mvPlan(cur, plan);
  }
  function mvTurnJoin(host, cur, data, m) {
    var had = Object.create(null);
    m.rows.forEach(function (r) { had[mvRowKey(r)] = 1; });
    var fresh = (data.rows || []).filter(function (r) {
      var k = mvRowKey(r);
      if (had[k]) return false;
      had[k] = 1;
      return true;
    });
    var bare = cur.item.kind === 'speech' && !String(cur.item.text || '').trim();
    if (bare && cur.node) cur.node.style.display = 'none';   /* a roll-only card: not made */
    cur.joined = host;
    /* this card keeps its words or its picture - never a roulette of its own */
    var own = {rows: [], sources: data.sources || {main: '', others: []}, cid: data.cid,
      tid: data.tid, stores: data.stores, origin: data.origin};
    if (mv.cur === cur) mvPlan(cur, own); else cur.data = own;
    if (cur.all) {
      cur.all.textContent = '';
      cur.all.appendChild(make('p', 'sp-mv-note', 'this moment\'s rolls are on '
        + (host.item.name || 'the line') + '\'s card'));
    }
    if (!fresh.length) return;
    var from = m.rows.length;
    m.rows.push.apply(m.rows, fresh);
    if (host.data) host.data.rows = m.rows;
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
    /* ONE sheet on the moment's card: what it rolled, landed and kept, then
       the new tables rolling after them; the tally stays in view after */
    var sheet = mvRrSheet(host, m.rows, Math.max(1100, 3000 / fresh.length) * m.rows.length);
    sheet.keep = true;
    sheet.box.classList.add('sp-rr-keep');
    host.rolls.textContent = '';
    host.rolls.style.display = '';
    host.rolls.appendChild(sheet.box);
    host.sheet = sheet;
    host.waitDie = null;
    host.node.classList.add('sp-mv-joined');
    var at0 = sheet.tables[from] ? sheet.tables[from].at : 0;
    if (cur.still || host.still) { mvRrAt(sheet, 0, true); mvRrResults(sheet); return; }
    var t0 = Date.now();
    (function step() {
      if (!host.node.isConnected || host.sheet !== sheet) return;
      if (mvRrAt(sheet, at0 + Date.now() - t0, false) === 'results') return;
      root.requestAnimationFrame(step);
    })();
  }
  /* the cards beside it that may share its moment (nearest first, up to a
     record), and the stings of those lines the history leaves out */
  function mvMomentMates(cur) {
    var out = [], seen = Object.create(null), bases = Object.create(null);
    seen[cur.item.lid] = 1;
    bases[mvBaseLid(cur.item.lid)] = 1;
    ['previousElementSibling', 'nextElementSibling'].forEach(function (dir) {
      var n = cur.node, k = 0;
      while (k < MV_MATES && n && (n = n[dir])) {
        var c = n.__mvCur;
        if (!c || !c.item || !c.item.lid) break;   /* a record, a live set: another moment */
        k += 1;
        if (seen[c.item.lid]) continue;
        seen[c.item.lid] = 1;
        bases[mvBaseLid(c.item.lid)] = 1;
        out.push({item: c.item, cur: c});
      }
    });
    var rows = [];
    try { rows = (root.PineStationFeed && root.PineStationFeed.rows && root.PineStationFeed.rows()) || []; } catch (e) { rows = []; }
    rows.forEach(function (r) {
      var id = String((r && r.id) || '');
      var b = /^(.*)-punct-\d+$/.exec(id);
      if (!b || !bases[b[1]] || seen[id]) return;
      seen[id] = 1;
      out.push({item: mvHistItem(r), cur: null});
    });
    return out;
  }
  /* the whole moment of a card: {card: the moment's card, data: its answer
     with every row of the moment} */
  function mvMomentGather(cur) {
    var none = function () { return null; };
    var empty = {rows: [], sources: {main: '', others: [], why: {}}};
    if (!cur.item.lid) return Promise.resolve({card: cur, data: cur.data || empty});
    return mvAsk(cur.item).then(null, none).then(function (data) {
      data = data || empty;
      var m = mvMomentOf(cur.item, data);
      mvMomentMember(m, cur.item, cur, data.rows || []);
      var said = Object.create(null);
      said[cur.item.lid] = data;
      var mates = mvMomentMates(cur);
      return Promise.all(mates.map(function (x) {
        return mvAsk(x.item).then(function (d) { return d ? {x: x, d: d} : null; }, none);
      })).then(function (got) {
        got.forEach(function (g) {     /* nearest first, the stings last: a sting joins through its line */
          var keys = g ? mvMomentKeys(g.x.item, g.d) : [];
          if (!keys.some(function (k) { return mv.turnCards[k] === m; })) return;
          mvMomentLink(m, keys);
          mvMomentMember(m, g.x.item, g.x.cur, g.d.rows || []);
          said[g.x.item.lid] = g.d;
        });
        var card = mvMomentCard(m) || cur;
        if (!mvMomentShown(m.host)) m.host = card;
        var plan = mvMerge(said[card.item.lid] || data, {});
        plan.rows = mvMomentRows(m);
        if (m.host === card) m.rows = plan.rows;
        return {card: card, data: plan};
      });
    });
  }
  /* a pin handed to the moment's card brings it into the list's view */
  function mvPinReveal(cur) {
    var s = mv.stage;
    if (!s || !cur || !cur.node || !cur.node.isConnected) return;
    var sr = s.getBoundingClientRect(), nr = cur.node.getBoundingClientRect();
    if (nr.bottom < sr.top || nr.top > sr.bottom) s.scrollTop += nr.top - sr.top - 8;
  }
'''

CSS_OLD = '''.sp-mv-stage.sp-mv-pinlist { overflow-anchor: none; }'''
CSS_NEW = '''.sp-mv-stage.sp-mv-pinlist { overflow-anchor: none; }
/* [onecard-moment] the moment's card keeps the moment's tally in view once a
   later member's rolls have landed on it - in the past and in the history */
.sp-mv-past.sp-mv-joined .sp-mv-rolls { display: flex !important; }'''


def main():
    for arg in sys.argv[1:]:
        p = Path(arg)
        raw = p.read_bytes()
        crlf = b"\r\n" in raw
        t = raw.decode("utf-8").replace("\r\n", "\n")
        if MARK in t:
            print("already patched:", p)
            continue
        if p.suffix == ".css":
            t = sub(t, CSS_OLD, CSS_NEW, "css", p)
        else:
            t = patch_js(t, p)
        out = t.replace("\n", "\r\n") if crlf else t
        p.write_bytes(out.encode("utf-8"))
        print("patched", p)


if __name__ == "__main__":
    main()
