/* [works-portable] THE WORKS, PORTABLE - the rooms and the blocked book, anywhere.
 *
 * "Make 'the works' able to be used as a popup in PineApp and able to be used
 * by the pineTab."                                       - the operator, 2026-10-06
 *
 * The desk's Works (renderer.js initWorksPopup) is a thousand lines of drawers
 * wired to the desk's own helpers. This is the same account in a portable
 * shape: GET /api/cupboard (the writers, what is being prepared, every round on
 * the shelves with its state, audio and grade, and the rooms' feed) and GET
 * /api/dj (the dialogue flow), painted in place every few seconds, with the
 * blocked book (blocked-book.js over GET /api/blocked) as the second tab.
 * mount(host, {get}) takes any fetcher; open() makes its own popup with a
 * close X; the PiP's popup catalog lists it because it has open(); the tablet
 * mounts it in the TOOLS view. The reader is never moved: a repaint keeps every
 * open round open and never scrolls.
 */
(function (root) {
  'use strict';
  if (root.PineTheWorks) return;
  var doc = root.document;

  function request(method, path, body) {
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge[method.toLowerCase()] === 'function') return Promise.resolve(bridge[method.toLowerCase()](path, body));
    var headers = {}, key = root.PINE_KEY || root.__PINE_VIDEO_EDITOR_KEY || '';
    if (key) headers.Authorization = 'Bearer ' + key;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    var base = root.PINE_BASE || (/^https?:/.test(root.location.protocol) ? '' : 'http://10.89.1.246:8096');
    return root.fetch(base + path, {method: method, headers: headers, cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (got) { if (!r.ok) throw new Error(typeof got.detail === 'string' ? got.detail : got.why || 'The station refused this request.'); return got; }); });
  }
  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function setText(node, text) { if (node && node.textContent !== text) node.textContent = text; }
  function ago(ts) {
    if (!ts) return '';
    var s = Math.max(0, (Date.now() - Number(ts) * (Number(ts) > 1e12 ? 1 : 1000)) / 1000);
    return s < 60 ? Math.round(s) + ' s ago' : s < 3600 ? Math.round(s / 60) + ' min ago' : (s / 3600).toFixed(1) + ' h ago';
  }
  function clock(ts) {
    if (!ts) return '';
    var d = new Date(Number(ts) * (Number(ts) > 1e12 ? 1 : 1000));
    return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  }
  var STATE_ORDER = ['writing', 'written', 'tinting', 'recording', 'ready', 'waiting', 'withheld', 'blocked', 'withdrawn'];

  /* ---- the rooms tab: one column of stages, painted in place */
  function roomsTab(host, api) {
    var ui = {open: {}, rounds: {}};
    var col = el('div', 'tw-rooms'); host.appendChild(col);
    function stage(key, title) {
      var box = el('section', 'tw-stage'); box.dataset.stage = key;
      var head = el('div', 'tw-stage-head'); head.append(el('b', '', title), el('span', 'tw-stage-sub', ''));
      var body = el('div', 'tw-stage-body');
      box.append(head, body); col.appendChild(box);
      return {box: box, sub: head.lastChild, body: body};
    }
    var desk = stage('desk', 'the writing desk');
    var room = stage('room', 'the recording room');
    var shelves = stage('shelves', 'the shelves');
    var feed = stage('feed', 'the rooms\' feed');
    var status = el('p', 'tw-status', 'reading the rooms...'); col.appendChild(status);

    function paintDesk(dj, cup) {
      var f = (dj && dj.dialogue_flow) || {}, w = (cup && cup.writers) || {};
      setText(desk.sub, (f.writing ? 'writing a round now' : 'idle - the reserve is at its target') + (dj && dj.model ? ' - ' + dj.model : ''));
      var rows = [['active', w.active], ['waiting', w.waiting], ['deferred', w.deferred]];
      if (!desk.body.firstChild) rows.forEach(function (r) { var line = el('div', 'tw-line'); line.dataset.key = r[0]; line.append(el('span', 'tw-k', r[0]), el('span', 'tw-v', '')); desk.body.appendChild(line); });
      rows.forEach(function (r) {
        var v = r[1], line = desk.body.querySelector('[data-key="' + r[0] + '"]');
        var text = Array.isArray(v) ? (v.length ? v.map(function (x) { return typeof x === 'string' ? x : (x.kind || x.name || x.id || JSON.stringify(x)).toString().slice(0, 40); }).join(', ') : 'none') : (v == null ? '-' : typeof v === 'object' ? JSON.stringify(v).slice(0, 120) : String(v));
        setText(line.lastChild, text);
      });
      var rec = (cup && cup.recovery) || {};
      var recLine = desk.body.querySelector('[data-key="recovery"]');
      if (!recLine) { recLine = el('div', 'tw-line'); recLine.dataset.key = 'recovery'; recLine.append(el('span', 'tw-k', 'recovery'), el('span', 'tw-v', '')); desk.body.appendChild(recLine); }
      setText(recLine.lastChild, (rec.running ? 'running - ' : '') + (rec.why || 'quiet'));
    }
    function paintRoom(cup) {
      var p = (cup && cup.preparing) || {};
      var head = p.kind ? [String(p.kind), String(p.stage || ''), String(p.who || ''), (p.made != null ? String(p.made) + '/' + String(p.lines || '?') + ' lines' : ''), (p.at ? ago(p.at) : '')].filter(Boolean).join(' - ') : 'nothing on the floor';
      setText(room.sub, head);
      var t = (cup && cup.tint) || {};
      if (!room.body.firstChild) { var line = el('div', 'tw-line'); line.dataset.key = 'tint'; line.append(el('span', 'tw-k', 'tint'), el('span', 'tw-v', '')); room.body.appendChild(line); }
      setText(room.body.firstChild.lastChild, typeof t === 'object' ? (t.say || t.state || JSON.stringify(t).slice(0, 120)) : String(t));
    }
    function roundKey(r, i) { return String(r.id || r.sid || (r.kind + '|' + r.label + '|' + i)); }
    function paintShelves(cup) {
      var rounds = (cup && cup.rounds) || [];
      var byState = {};
      rounds.forEach(function (r) { var s = String(r.state || 'written'); (byState[s] = byState[s] || []).push(r); });
      var states = Object.keys(byState).sort(function (a, b) { return (STATE_ORDER.indexOf(a) + 1 || 99) - (STATE_ORDER.indexOf(b) + 1 || 99); });
      setText(shelves.sub, rounds.length + ' round(s): ' + states.map(function (s) { return byState[s].length + ' ' + s; }).join(', '));
      var seen = {};
      rounds.forEach(function (r, i) {
        var key = roundKey(r, i); seen[key] = true;
        var row = ui.rounds[key];
        if (!row) {
          row = el('details', 'tw-round'); row.dataset.key = key;
          var sum = el('summary', 'tw-round-sum');
          sum.append(el('span', 'tw-kind', ''), el('span', 'tw-label', ''), el('span', 'tw-state', ''), el('span', 'tw-audio', ''), el('span', 'tw-grade', ''));
          var lines = el('div', 'tw-lines');
          row.append(sum, lines); row.open = !!ui.open[key];
          row.addEventListener('toggle', function () { ui.open[key] = row.open; });
          ui.rounds[key] = row;
        }
        var sum2 = row.firstChild;
        setText(sum2.children[0], String(r.kind || ''));
        setText(sum2.children[1], String(r.label || r.title || ''));
        setText(sum2.children[2], String(r.state || ''));
        setText(sum2.children[3], r.audio != null ? String(r.audio) + (r.cut ? ' cut ' + r.cut : '') : '');
        setText(sum2.children[4], String(r.grade || ''));
        row.dataset.state = String(r.state || '');
        var lines2 = row.lastChild, want = (r.lines || []);
        if (row.open || lines2.childElementCount !== want.length) {
          while (lines2.childElementCount > want.length) lines2.removeChild(lines2.lastChild);
          want.forEach(function (l, j) {
            var line = lines2.children[j];
            if (!line) { line = el('div', 'tw-l'); line.append(el('b', '', ''), el('span', '', '')); lines2.appendChild(line); }
            setText(line.firstChild, String(l.who || '') + ':'); setText(line.lastChild, ' ' + String(l.text || ''));
            line.dataset.mark = String(l.mark || '');
          });
        }
      });
      /* order: by state, in place; rows that left the shelves leave */
      var order = [];
      states.forEach(function (s) { byState[s].forEach(function (r, i) { order.push(roundKey(r, rounds.indexOf(r))); }); });
      Object.keys(ui.rounds).forEach(function (key) { if (!seen[key]) { ui.rounds[key].remove(); delete ui.rounds[key]; } });
      var cursor = null;
      order.forEach(function (key) {
        var row = ui.rounds[key]; if (!row) return;
        if (row.parentNode !== shelves.body) shelves.body.appendChild(row);
        if (cursor ? row.previousSibling !== cursor : row !== shelves.body.firstChild) shelves.body.insertBefore(row, cursor ? cursor.nextSibling : shelves.body.firstChild);
        cursor = row;
      });
      if (!rounds.length && !shelves.body.querySelector('.tw-empty')) shelves.body.appendChild(el('p', 'tw-empty', 'nothing on the shelves yet'));
      if (rounds.length) { var e = shelves.body.querySelector('.tw-empty'); if (e) e.remove(); }
    }
    function paintFeed(cup) {
      var rows = ((cup && cup.feed) || []).slice(-14).reverse();
      setText(feed.sub, rows.length ? 'the last ' + rows.length + ' things the rooms said' : 'quiet');
      rows.forEach(function (r, i) {
        var line = feed.body.children[i];
        if (!line) { line = el('div', 'tw-feed'); line.append(el('span', 'tw-when', ''), el('span', 'tw-fkind', ''), el('span', 'tw-ftext', '')); feed.body.appendChild(line); }
        setText(line.children[0], clock(r.at)); setText(line.children[1], String(r.kind || '')); setText(line.children[2], String(r.text || ''));
      });
      while (feed.body.childElementCount > rows.length) feed.body.removeChild(feed.body.lastChild);
    }
    function paint(dj, cup) {
      try { paintDesk(dj, cup); paintRoom(cup); paintShelves(cup); paintFeed(cup); setText(status, 'read ' + clock(Date.now() / 1000) + (cup && cup.paused ? ' - the station is paused, the rooms bank behind it' : '')); }
      catch (e) { setText(status, 'the rooms could not be drawn: ' + (e.message || e)); }
    }
    return {
      load: function () {
        return Promise.all([api('/api/cupboard'), api('/api/dj').catch(function () { return null; })]).then(function (got) { paint(got[1], got[0]); })
          .catch(function (e) { setText(status, 'the station did not answer: ' + (e.message || e)); });
      }
    };
  }

  /* ---- the whole: two tabs, a badge, a poll */
  function mount(host, opts) {
    opts = opts || {};
    var api = typeof opts.get === 'function' ? opts.get : function (p) { return request('GET', p); };
    var dead = false, timer = 0, badgeTimer = 0, book = null;
    var panel = el('div', 'tw-panel'); host.appendChild(panel);
    var tabs = el('div', 'tw-tabs');
    var tabRooms = el('button', 'tw-tab on', 'the rooms'); tabRooms.type = 'button';
    var tabBlocked = el('button', 'tw-tab', 'blocked'); tabBlocked.type = 'button';
    var badge = el('span', 'tw-badge', ''); tabBlocked.appendChild(badge);
    tabs.append(tabRooms, tabBlocked); panel.appendChild(tabs);
    panel.appendChild(el('p', 'tw-sub', 'Every round is written, banked, recorded and stacked before it goes out. This is where each one is right now.'));
    var roomsHost = el('div', 'tw-pane'), bookHost = el('div', 'tw-pane tw-book'); bookHost.style.display = 'none';
    panel.append(roomsHost, bookHost);
    var rooms = roomsTab(roomsHost, api);
    function show(which) {
      var r = which !== 'blocked';
      tabRooms.classList.toggle('on', r); tabBlocked.classList.toggle('on', !r);
      roomsHost.style.display = r ? '' : 'none'; bookHost.style.display = r ? 'none' : '';
      if (!r && !book && root.PineBlockedBook) book = root.PineBlockedBook.mount(bookHost, {get: api, always: true, openRound: opts.openRound});
      if (!r && !root.PineBlockedBook && !bookHost.firstChild) bookHost.appendChild(el('p', 'tw-status', 'The blocked book is not loaded on this screen.'));
      try { root.localStorage.setItem('twTab', r ? 'rooms' : 'blocked'); } catch (e) { /* no storage */ }
    }
    tabRooms.addEventListener('click', function () { show('rooms'); });
    tabBlocked.addEventListener('click', function () { show('blocked'); });
    function badgeTick() {
      api('/api/blocked?limit=1&standing=1&history=1').then(function (b) {
        if (dead) return;
        var sys = (b && b.counts && b.counts.system) || {};
        var n = Object.keys(sys).reduce(function (a, k) { return a + (Number(sys[k]) || 0); }, 0);
        setText(badge, n ? String(n) : ''); tabBlocked.title = b && b.say ? b.say : 'every blocked case the ledgers hold';
      }).catch(function () {});
    }
    function tick() { if (dead) return; if (roomsHost.style.display !== 'none') rooms.load(); }
    tick(); badgeTick();
    timer = root.setInterval(tick, Number(opts.pollMs) || 4000);
    badgeTimer = root.setInterval(badgeTick, 15000);
    try { if (root.localStorage.getItem('twTab') === 'blocked') show('blocked'); } catch (e) { /* no storage */ }
    return {
      close: function () { dead = true; root.clearInterval(timer); root.clearInterval(badgeTimer); if (book && book.close) book.close(); panel.remove(); },
      refresh: function () { tick(); badgeTick(); },
      show: show
    };
  }

  var popup = null;
  function open(opts) {
    if (popup) { close(); return; }
    var shade = el('div', 'tw-pop'); shade.id = 'pineTheWorksPop'; shade.setAttribute('role', 'dialog'); shade.setAttribute('aria-label', 'The Works');
    var box = el('div', 'tw-box');
    var head = el('div', 'tw-head'); head.append(el('b', '', 'The Works'), el('span', 'tw-head-sub', 'how the dialogue gets made'));
    var x = el('button', 'tw-x', 'X'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close The Works');
    x.addEventListener('click', close); head.appendChild(x);
    box.appendChild(head); shade.appendChild(box); doc.body.appendChild(shade);
    popup = {shade: shade, mounted: mount(box, opts || {})};
    return popup.mounted;
  }
  function close() { if (!popup) return; try { popup.mounted.close(); } catch (e) { /* gone */ } popup.shade.remove(); popup = null; }

  root.PineTheWorks = {mount: mount, open: open, close: close, isOpen: function () { return !!popup; }};
})(typeof window !== 'undefined' ? window : this);
