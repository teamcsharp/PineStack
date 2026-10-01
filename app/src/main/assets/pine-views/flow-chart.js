/* [flowchart] THE CONVERSATION AS A CONDITIONAL FLOWCHART, GROWING AS IT AIRS.
 *
 * "In script view I want a button that I can press that toggles between
 * showing the script view and showing the technical flowchart view. When
 * viewing the technical flow chart view, I want you to see each element flip
 * and rotate out as the conversation is taking place ... demonstrating the
 * roulette, the RNG and the systems of system three playing out, building the
 * conversation in the form of conditional flow charts expanding out."
 *                                                     - the operator, 2026-10-01
 *
 * script-page.js owns the toggle and hands a pane: PineFlowChart.show(pane, on).
 * Live, it follows the conversation on air (GET /api/flow/now) and reveals the
 * chart up to the turn being spoken; a hex key (a conversation's, or any line's
 * code) opens any conversation (GET /api/flow/{key}). Every diamond is a draw
 * System 3 recorded: the die shows its d100, the path down is the winner, the
 * boxes beside it the candidates it beat, with their odds. Nothing is invented.
 */
(function (root) {
  'use strict';

  var POLL_MS = 2000;
  var STAGGER_MS = 110;
  var ui = {pane: null, on: false, live: true, key: '', flowKey: '', timer: 0, busy: false,
            shown: {}, body: null, status: null, keyBox: null, liveBtn: null, recent: null, reveal: -1};

  /* ------------------------------------------------------------ roads */
  function bridge() { var b = root.pineDesktop; return b && typeof b.get === 'function' ? b : null; }
  function httpPage() { try { return /^https?:$/.test(String(root.location.protocol)); } catch (e) { return false; } }
  function stationUrl(u) {
    if (httpPage()) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (e) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }
  function stationKey() {
    try { if (typeof root.key === 'function') { var k = root.key(); if (typeof k === 'string' && k) return k; } } catch (e) { /* not the panel */ }
    try { /* eslint-disable-next-line no-undef */ if (typeof SERVER_KEY === 'string' && SERVER_KEY) return SERVER_KEY; } catch (e) { /* undeclared */ }
    try { return String(root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || ''); } catch (e) { return ''; }
  }
  function get(path) {
    var b = bridge();
    if (b) return Promise.resolve(b.get(path));
    var headers = {};
    var key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    return root.fetch(stationUrl(path), {headers: headers, cache: 'no-store'}).then(function (res) {
      return res.json().then(function (d) {
        if (!res.ok) throw new Error(String((d && d.detail) || res.status));
        return d;
      });
    });
  }

  /* ------------------------------------------------------------ helpers */
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function pct(p) { return p == null ? '' : Math.round(Number(p) * 100) + '%'; }
  function cut(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function copy(text) {
    try { if (root.navigator && root.navigator.clipboard) root.navigator.clipboard.writeText(text); } catch (e) { /* no clipboard */ }
    say('copied ' + text);
  }
  function say(t) { if (ui.status) ui.status.textContent = t; }

  /* ------------------------------------------------------------ nodes */
  function die(value, delay) {
    var d = make('span', 'fc-die', '?');
    var final = value == null ? '–' : String(value);
    root.setTimeout(function () {
      var t0 = Date.now();
      (function spin() {
        if (Date.now() - t0 >= 900) { d.textContent = final; d.classList.add('landed'); return; }
        d.textContent = String(1 + Math.floor(Math.random() * 100));
        root.setTimeout(spin, 55);
      }());
    }, delay || 0);
    d.title = value == null ? 'no random number: a pinned or single-choice draw' : 'd100 ' + final;
    return d;
  }
  function codeChip(code) {
    var c = make('button', 'fc-code', '#' + code.slice(0, 8));
    c.type = 'button';
    c.title = 'Copy this line\'s code - paste it to ask about this line';
    c.addEventListener('click', function (e) { e.stopPropagation(); copy(code.slice(0, 8)); });
    return c;
  }
  function startNode(n) {
    var box = make('div', 'fc-node fc-start');
    box.appendChild(make('b', '', n.label));
    var sub = [n.road, n.structure, n.topic].filter(Boolean).join(' · ');
    if (sub) box.appendChild(make('span', 'fc-sub', cut(sub, 140)));
    var key = make('button', 'fc-code', 'key ' + String(n.id).split(':')[1]);
    key.type = 'button';
    key.title = 'Copy this conversation\'s key';
    key.addEventListener('click', function () { copy(String(n.id).split(':')[1]); });
    box.appendChild(key);
    return box;
  }
  function decisionNode(n, delay) {
    var row = make('div', 'fc-decision');
    var dia = make('div', 'fc-node fc-diamond' + (n.fixed ? ' fixed' : ''));
    var inner = make('div', 'fc-dia-in');
    inner.appendChild(make('b', '', n.family || 'roll'));
    inner.appendChild(die(n.dice, delay + 200));
    if (n.odds != null) inner.appendChild(make('span', 'fc-sub', 'at ' + pct(n.odds)));
    dia.appendChild(inner);
    dia.title = (n.path || []).join(' › ') + (n.of ? '  ·  ' + n.of + ' in the drum' : '');
    row.appendChild(dia);
    var side = make('div', 'fc-branches');
    if (n.winner) {
      var w = make('div', 'fc-branch win', '▼ ' + cut(n.winner.label, 70) + (n.winner.p != null ? '  ' + pct(n.winner.p) : ''));
      if (n.winner.why && n.winner.why.length) w.title = n.winner.why.join('; ');
      side.appendChild(w);
    }
    (n.losers || []).forEach(function (l, i) {
      var b = make('div', 'fc-branch lose', cut(l.label, 60) + (l.p != null ? '  ' + pct(l.p) : ''));
      b.style.animationDelay = (delay + 260 + i * 90) + 'ms';
      side.appendChild(b);
    });
    if (n.more) side.appendChild(make('div', 'fc-branch more', '+' + n.more + ' more not taken'));
    if (n.excluded) side.appendChild(make('div', 'fc-branch more', n.excluded + ' could not come up'));
    if ((n.path || []).length > 1) side.appendChild(make('div', 'fc-path', n.path.join(' › ')));
    row.appendChild(side);
    return row;
  }
  function turnNode(n) {
    var box = make('div', 'fc-node fc-turn' + (n.now ? ' now' : '') + (n.aired_at ? ' aired' : ''));
    var top = make('div', 'fc-turn-top');
    top.appendChild(make('b', '', n.who || n.seat));
    top.appendChild(make('span', 'fc-sub', (n.index + 1) + ' · ' + (n.leg || n.place || '') + (n.feeling ? ' · ' + n.feeling : '')));
    (n.codes || []).forEach(function (c) { top.appendChild(codeChip(c)); });
    box.appendChild(top);
    box.appendChild(make('p', n.said ? 'fc-said' : 'fc-asked', n.said ? '“' + cut(n.said, 320) + '”' : cut(n.asked, 260)));
    return box;
  }
  function plainNode(n, cls, label, text) {
    var box = make('div', 'fc-node ' + cls);
    box.appendChild(make('b', '', label));
    if (text) box.appendChild(make('span', 'fc-sub', cut(text, 220)));
    return box;
  }
  function nodeFor(n, delay) {
    if (n.type === 'start') return startNode(n);
    if (n.type === 'decision') return decisionNode(n, delay);
    if (n.type === 'turn') return turnNode(n);
    if (n.type === 'gate') return plainNode(n, 'fc-gate', n.label, n.text);
    if (n.type === 'step') {
      var facts = n.facts ? Object.keys(n.facts).map(function (k) { return k + ' ' + n.facts[k]; }).join(' · ') : '';
      return plainNode(n, 'fc-step', n.label, facts || n.text);
    }
    return plainNode(n, 'fc-end', n.label, '');
  }

  /* ------------------------------------------------------------ painting */
  function edgeLabel(flow, id) {
    var e = (flow.edges || []).filter(function (x) { return x.to === id; })[0];
    return e ? e.label : '';
  }
  function revealUpTo(flow) {
    /* live: up to the turn going out now (and what comes straight after it); otherwise all */
    var nodes = flow.nodes || [];
    if (!ui.live || !flow.now_turn) return nodes.length;
    var at = -1;
    for (var i = 0; i < nodes.length; i += 1) if (nodes[i].type === 'turn' && nodes[i].now) at = i;
    if (at < 0) return nodes.length;
    for (var j = at + 1; j < nodes.length && nodes[j].type === 'gate'; j += 1) at = j;
    return at + 1;
  }
  function paint(flow) {
    if (!ui.body) return;
    if (flow.key !== ui.flowKey) {
      ui.body.textContent = '';
      ui.shown = {};
      ui.flowKey = flow.key;
    }
    var nodes = flow.nodes || [];
    var upto = revealUpTo(flow);
    var fresh = 0;
    nodes.forEach(function (n, i) {
      var had = ui.shown[n.id];
      if (i >= upto) { if (had) had.hidden = true; return; }
      if (had) {
        had.hidden = false;
        if (n.type === 'turn') {
          var repl = nodeFor(n, 0);
          had.replaceChild(repl, had.querySelector('.fc-node'));
        }
        return;
      }
      var delay = fresh * STAGGER_MS;
      var row = make('div', 'fc-row fc-row-' + n.type);
      var lab = i ? edgeLabel(flow, n.id) : '';
      if (i) row.appendChild(make('div', 'fc-edge', lab ? '▼ ' + lab : '▼'));
      var node = nodeFor(n, delay);
      row.appendChild(node);
      row.classList.add('fc-enter');
      row.style.animationDelay = delay + 'ms';
      ui.body.appendChild(row);
      ui.shown[n.id] = row;
      fresh += 1;
    });
    var c = flow.counts || {};
    say('#' + flow.key + ' · ' + (flow.road || '') + ' · ' + (c.decisions || 0) + ' draws · ' + (c.turns || 0)
      + ' turns (' + (c.aired || 0) + ' aired) · ' + (c.candidates_lost || 0) + ' candidates beaten');
    if (fresh && ui.live) {
      var last = ui.body.lastElementChild;
      if (last && last.scrollIntoView) root.setTimeout(function () { try { last.scrollIntoView({block: 'end', behavior: 'smooth'}); } catch (e) { /* old engine */ } }, fresh * STAGGER_MS);
    }
  }

  function tick() {
    if (!ui.on || ui.busy) return;
    ui.busy = true;
    var path = ui.live ? '/api/flow/now' : '/api/flow/' + encodeURIComponent(ui.key);
    get(path).then(function (d) {
      if (!ui.on) return;
      if (ui.live) {
        if (d && d.live && d.flow) paint(d.flow);
        else if (!ui.flowKey) say(d && d.why ? d.why : 'waiting for a System 3 line on air');
      } else if (d && d.nodes) {
        paint(d);
      }
    }, function (err) { say(String((err && err.message) || err)); })
      .then(function () { ui.busy = false; });
  }

  function loadRecent() {
    get('/api/flow/recent?limit=40').then(function (d) {
      if (!ui.recent) return;
      ui.recent.textContent = '';
      ui.recent.appendChild(make('option', '', 'recent conversations…'));
      ((d && d.conversations) || []).forEach(function (c) {
        var cid = String(c.conversation_id || c.id || '');
        if (!cid) return;
        var o = make('option', '', cid + ' · ' + (c.road || '') + (c.topic ? ' · ' + cut(c.topic, 40) : ''));
        o.value = cid;
        ui.recent.appendChild(o);
      });
    }, function () { /* the list is a convenience */ });
  }

  function openKey(key) {
    key = String(key || '').trim().replace(/^#/, '').toLowerCase();
    if (!/^[0-9a-f]{6,32}$/.test(key)) { say('a key is hex: a conversation\'s 16 or a line\'s code'); return; }
    ui.live = false;
    ui.key = key;
    ui.flowKey = '';
    if (ui.liveBtn) ui.liveBtn.setAttribute('aria-pressed', 'false');
    tick();
  }

  function build(pane) {
    pane.textContent = '';
    pane.classList.add('fc-pane');
    var bar = make('div', 'fc-bar');
    bar.appendChild(make('b', 'fc-title', 'FLOWCHART'));
    ui.liveBtn = make('button', 'fc-btn', 'Live');
    ui.liveBtn.type = 'button';
    ui.liveBtn.title = 'Follow the conversation on air';
    ui.liveBtn.setAttribute('aria-pressed', 'true');
    ui.liveBtn.addEventListener('click', function () {
      ui.live = true; ui.flowKey = ''; ui.liveBtn.setAttribute('aria-pressed', 'true'); tick();
    });
    bar.appendChild(ui.liveBtn);
    ui.keyBox = make('input', 'fc-key');
    ui.keyBox.placeholder = 'hex key or line code';
    ui.keyBox.spellcheck = false;
    ui.keyBox.addEventListener('keydown', function (e) { if (e.key === 'Enter') openKey(ui.keyBox.value); });
    bar.appendChild(ui.keyBox);
    var go = make('button', 'fc-btn', 'Open');
    go.type = 'button';
    go.addEventListener('click', function () { openKey(ui.keyBox.value); });
    bar.appendChild(go);
    ui.recent = make('select', 'fc-recent');
    ui.recent.setAttribute('aria-label', 'Recent conversations');
    ui.recent.addEventListener('change', function () { if (ui.recent.value) openKey(ui.recent.value); });
    bar.appendChild(ui.recent);
    var rep = make('button', 'fc-btn', 'Report');
    rep.type = 'button';
    rep.title = 'Copy this conversation\'s key and the report address, to hand over for a diagnosis';
    rep.addEventListener('click', function () { if (ui.flowKey) copy(ui.flowKey + '  /api/flow/' + ui.flowKey + '?text=1'); });
    bar.appendChild(rep);
    pane.appendChild(bar);
    ui.status = make('div', 'fc-status', 'reading…');
    pane.appendChild(ui.status);
    ui.body = make('div', 'fc-body');
    pane.appendChild(ui.body);
    ui.pane = pane;
  }

  function show(pane, on) {
    on = !!on;
    if (on && pane && ui.pane !== pane) build(pane);
    ui.on = on;
    if (ui.timer) { root.clearInterval(ui.timer); ui.timer = 0; }
    if (on) {
      loadRecent();
      tick();
      ui.timer = root.setInterval(tick, POLL_MS);
    }
  }

  root.PineFlowChart = {show: show, open: openKey, isOn: function () { return ui.on; },
    _paint: paint};
})(typeof window !== 'undefined' ? window : globalThis);
