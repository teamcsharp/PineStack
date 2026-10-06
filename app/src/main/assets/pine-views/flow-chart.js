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
  var BG_MS = 10000;          /* [fc-design] off screen, the latest conversation is still fetched and kept */
  var ui = {pane: null, on: false, live: true, key: '', flowKey: '', timer: 0, busy: false,
            shown: {}, body: null, status: null, keyBox: null, liveBtn: null, recent: null, reveal: -1,
            mode: 'technical', follow: true, cache: {}, lastFlow: null, autoAt: 0, modeBtn: null, followBtn: null,
            playback: null, feedLeave: null, request: 0, liveLine: '', unfold: null, unfoldTimer: 0, actionRow: null};
  try { if (root.localStorage && root.localStorage.getItem('pine.fc.mode') === 'design') ui.mode = 'design'; } catch (e) { /* no storage */ }

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
    d.textContent = final; d.classList.add('landed');
    d.title = value == null ? 'no random number: a pinned or single-choice draw' : 'd100 ' + final;
    return d;
  }
  /* [fc-line] "On my tablet it brings up this" - a tap copied the code, and Android
     answers every copy with its clipboard preview. A tap now opens the line itself:
     who said it, its words, the rolls that made it, Open its conversation; copying is
     a button of its own. */
  function codeChip(code, turn) {
    var c = make('button', 'fc-code', '#' + code.slice(0, 8));
    c.type = 'button';
    c.title = 'This line: who said it, its words and the rolls behind it';
    c.addEventListener('click', function (e) { e.stopPropagation(); openLine(code, turn); });
    return c;
  }
  function openLine(code, turn) {
    closeInspect();
    var pop = make('section', 'fc-inspect');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'This line');
    var x = make('button', 'fc-inspect-x', '×');
    x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', closeInspect);
    pop.append(x, make('h3', '', 'Line #' + code.slice(0, 8)));
    var dl = make('dl', 'fc-inspect-dl');
    function row(k, v) { if (v) dl.append(make('dt', '', k), make('dd', '', String(v))); }
    if (turn) {
      row('speaker', (turn.who || '') + (turn.seat ? '  (seat ' + turn.seat + ')' : ''));
      row('turn', (turn.index + 1) + (turn.__role ? ' - ' + turn.__role : ''));
      row('feeling', turn.feeling);
      var of = (turn.codes || []).indexOf(code);
      if ((turn.codes || []).length > 1) row('part', (of + 1) + ' of ' + turn.codes.length
        + ' lines this turn went out as (a long turn is voiced and aired in pieces)');
    }
    pop.appendChild(dl);
    var said = make('p', 'fc-inspect-kind', 'reading the line…');
    pop.appendChild(said);
    var acts = make('div', 'fc-line-acts');
    var open = make('button', 'fc-btn', 'Open its conversation'); open.type = 'button';
    open.addEventListener('click', function () { closeInspect(); openKey(code); });
    var cp = make('button', 'fc-btn', 'Copy code'); cp.type = 'button';
    cp.addEventListener('click', function () { copy(code.slice(0, 8)); });
    acts.append(open, cp);
    pop.appendChild(acts);
    (ui.pane || document.body).appendChild(pop);
    seatPop(pop);                                                          /* [fc-seat] clear of the tabs */
    ui.inspect = pop;
    get('/api/system3/line?line_id=' + encodeURIComponent(code)).then(function (d) {
      if (ui.inspect !== pop) return;
      var ln = (d && d.line) || {};
      said.textContent = ln.text ? '“' + cut(ln.text, 600) + '”' : 'The station keeps no words for this line.';
      row('rolls behind it', (d && d.decisions ? d.decisions.length : 0) + ' recorded draws');
      row('aired', ln.at ? new Date(Number(ln.at) * 1000).toLocaleTimeString() : '');
    }, function () { if (ui.inspect === pop) said.textContent = turn && turn.said ? '“' + cut(turn.said, 600) + '”' : 'The line could not be read.'; });
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
    if (n.properties) box.appendChild(rouletteOptions(n));
    return box;
  }
  function rouletteOptions(n) {
    var panel = make('div', 'fc-roulette');
    if (n.previous_revision) panel.appendChild(make('b', 'fc-sub', 'Previous failed revision'));
    (n.stages || []).forEach(function (st) {
      var candidates = st.candidates || [];
      var group = make('section', 'fc-wheel');
      group.appendChild(make('b', 'fc-sub', (st.stage || 'options') + ' - ' + candidates.length + ' eligible'));
      var reel = make('div', 'fc-reel');
      reel.setAttribute('tabindex', '0'); reel.setAttribute('aria-label', 'Recorded ' + (n.family || '') + ' options');
      var selectedRow = null;
      candidates.forEach(function (c) {
        var selected = c.id === st.selected;
        var item = make('div', 'fc-option' + (selected ? ' selected' : ''));
        item.appendChild(make('b', '', (selected ? 'Selected: ' : '') + (c.label || c.id)));
        item.appendChild(make('span', 'fc-sub', 'weight ' + c.weight + (c.p != null ? ' | ' + pct(c.p) : '')));
        if (c.text) item.appendChild(make('p', '', c.text));
        if (c.why) item.appendChild(make('span', 'fc-sub', Array.isArray(c.why) ? c.why.join('; ') : String(c.why)));
        reel.appendChild(item); if (selected) selectedRow = item;
      });
      group.appendChild(reel);
      if (selectedRow) root.setTimeout(function () { reel.scrollTop = selectedRow.offsetTop - reel.firstElementChild.offsetTop; }, 0);
      if (candidates.length) {
        var replay = make('button', 'fc-btn', 'Scroll recorded options'); replay.type = 'button';
        replay.addEventListener('click', function (e) {
          e.stopPropagation();
          reel.scrollTop = 0;
          var i = 0; replay.disabled = true;
          function next() {
            if (!reel.isConnected) { replay.disabled = false; return; }
            if (i < reel.children.length) {
              reel.scrollTop = reel.children[i++].offsetTop - reel.firstElementChild.offsetTop;
              root.setTimeout(next, 220);
            } else {
              if (selectedRow) reel.scrollTop = selectedRow.offsetTop - reel.firstElementChild.offsetTop;
              replay.disabled = false;
            }
          }
          next();
        });
        group.appendChild(replay);
        if (candidates.length > 1 && !(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
          root.setTimeout(function () { if (replay.isConnected) replay.click(); }, 300);
        }
      }
      (st.excluded || []).forEach(function (c) {
        group.appendChild(make('div', 'fc-option excluded', 'Excluded: ' + (c.label || c.id) + ' | ' + (Array.isArray(c.why) ? c.why.join('; ') : c.why || '') + (c.text ? ' | ' + c.text : '')));
      });
      panel.appendChild(group);
    });
    if (n.selected && n.selected.text) panel.appendChild(make('p', 'fc-command', n.selected.text));
    if (n.properties && Object.keys(n.properties).length) {
      var details = make('details', 'fc-properties'); details.appendChild(make('summary', '', 'Node properties and changes'));
      details.appendChild(make('pre', '', JSON.stringify(n.properties, null, 2))); panel.appendChild(details);
    }
    return panel;
  }
  function decisionNode(n, delay) {
    var row = make('div', 'fc-decision');
    var dia = make('div', 'fc-node fc-diamond' + (n.fixed ? ' fixed' : ''));
    var inner = make('div', 'fc-dia-in');
    inner.appendChild(make('b', '', n.family === 'GRAPH' ? n.kind || 'GRAPH' : n.family || 'roll'));
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
    side.appendChild(rouletteOptions(n));
    if ((n.path || []).length > 1) side.appendChild(make('div', 'fc-path', n.path.join(' › ')));
    row.appendChild(side);
    return row;
  }
  function turnNode(n) {
    var box = make('div', 'fc-node fc-turn' + (n.now ? ' now' : '') + (n.aired_at ? ' aired' : ''));
    var top = make('div', 'fc-turn-top');
    top.appendChild(make('b', '', n.who || n.seat));
    top.appendChild(make('span', 'fc-sub', (n.index + 1) + ' · ' + (n.leg || n.place || '') + (n.feeling ? ' · ' + n.feeling : '')));
    (n.codes || []).forEach(function (c) { top.appendChild(codeChip(c, n)); });
    box.appendChild(top);
    box.appendChild(make('p', n.said ? 'fc-said' : 'fc-asked', n.said ? '“' + cut(n.said, 320) + '”' : cut(n.asked, 260)));
    replyTrail(box, n);
    if (n.properties) box.appendChild(rouletteOptions(n));
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
  /* [fc-oneway] "a flow chart should only flow one direction ... System 3 is
     intended to be one linear direction" (the operator, 2026-10-01). The station
     sends every roll of the whole plan first, then the turns, then the gates and
     steps as they were recorded - so the chart ran down through the rolls, back up
     to turn 1 and down again. Ordered here, one way: the round's own rolls, then
     each turn's rolls, the turn, and what the gates and steps did to it; the end. */
  function ordered(flow) {
    var nodes = flow.nodes || [];
    if (flow.__ordered && flow.__orderedOf === nodes) return flow.__ordered;
    var firstAt = {};                       /* turn index -> when its first roll was drawn */
    nodes.forEach(function (n) {
      if (n.type === 'decision' && n.turn_index >= 0 && n.at && (firstAt[n.turn_index] == null || n.at < firstAt[n.turn_index])) {
        firstAt[n.turn_index] = n.at;
      }
    });
    var turnsAt = Object.keys(firstAt).map(Number).sort(function (a, b) { return a - b; });
    function groupOf(n) {
      if (n.type === 'start') return -2;
      if (n.type === 'end') return 1e9;
      if (n.type === 'decision') return n.turn_index >= 0 ? n.turn_index : -1;
      if (n.type === 'turn') return n.index;
      var m = /\bturn (\d+)\b/i.exec(String(n.text || '') + ' ' + String(n.label || ''));
      if (m) return Math.max(0, Number(m[1]) - 1);
      var g = -1;
      turnsAt.forEach(function (t) { if (n.at && firstAt[t] <= n.at) g = t; });
      return g;
    }
    function rankOf(n) { return n.type === 'start' ? 0 : n.type === 'decision' ? 1 : n.type === 'turn' ? 2 : n.type === 'end' ? 4 : 3; }
    var out = nodes.map(function (n, i) { return {n: n, g: groupOf(n), r: rankOf(n), s: n.type === 'decision' ? (n.seq || 0) : (n.at || 0), i: i}; });
    out.sort(function (a, b) { return a.g - b.g || a.r - b.r || a.s - b.s || a.i - b.i; });
    flow.__nodeGroups = {};
    out.forEach(function (x) { flow.__nodeGroups[x.n.id] = x.g; });
    flow.__ordered = out.map(function (x) { return x.n; });
    flow.__orderedOf = nodes;
    return flow.__ordered;
  }
  /* The technical chart unfolds the actions of the clock-selected reply. Older
     turns remain landed; later replies stay hidden until they actually speak. */
  function stopUnfold() {
    if (ui.unfoldTimer) root.clearTimeout(ui.unfoldTimer);
    ui.unfoldTimer = 0;
  }
  function revealUpTo(flow) {
    var nodes = ordered(flow);
    if (!ui.live || !flow.now_turn) { stopUnfold(); ui.unfold = null; return nodes.length; }
    var at = nodes.findIndex(function (n) { return n.type === 'turn' && n.now; });
    if (at < 0) { stopUnfold(); ui.unfold = null; return nodes.length; }
    var last = at;
    while (last + 1 < nodes.length && (nodes[last + 1].type === 'gate' || nodes[last + 1].type === 'step')
      && flow.__nodeGroups[nodes[last + 1].id] === nodes[at].index) last += 1;
    if (ui.mode !== 'technical') { stopUnfold(); return last + 1; }
    var first = nodes.findIndex(function (n) { return flow.__nodeGroups[n.id] === nodes[at].index; });
    if (first < 0) first = at;
    // Round-wide planning belongs to the first reply; later replies retain it above.
    if (!nodes.slice(0, at).some(function (n) { return n.type === 'turn'; })) {
      var planning = nodes.findIndex(function (n) { return n.type !== 'start'; });
      if (planning >= 0) first = Math.min(first, planning);
    }
    var token = flow.key + '/' + (stripLine() || flow.now_turn);
    var now = Date.now(), value = ui.playback, stream = value && value.station && value.station.stream_now;
    var row = value && value.now, timed = stream && (stream.rows || []).find(function (r) { return String(r.id) === stripLine(); });
    timed = timed || row;
    var duration = timed && Number(timed.until) - Number(timed.from);
    var budget = duration > 0 ? Math.max(1000, Math.min(6000, duration * 350)) : 3000;
    var run = ui.unfold;
    if (!run || run.token !== token) run = ui.unfold = {token: token, elapsed: 0, stamp: now, count: 0};
    var paused = value && value.station && value.station.paused === true;
    if (!paused && !run.paused) run.elapsed += Math.max(0, now - run.stamp);
    run.stamp = now; run.paused = paused;
    if (stream && timed && stream.at != null && timed.from != null && value.at != null) {
      // Shared feed timestamps are milliseconds, including in the independent tools window.
      var playhead = Number(value.at) - Number(stream.at) * 1000 - Number(timed.from) * 1000;
      if (Number.isFinite(playhead) && !paused) run.elapsed = Math.max(run.elapsed, playhead);
    }
    var count = last - first + 1;
    run.count = Math.max(run.count, Math.min(count, 1 + Math.floor(Math.max(0, run.elapsed) / budget * count)));
    run.first = first; run.last = last; run.turn = nodes[at].index;
    stopUnfold();
    if (run.count < count && !paused && ui.on && !document.hidden) {
      ui.unfoldTimer = root.setTimeout(function () {
        ui.unfoldTimer = 0;
        if (ui.on && ui.live && ui.mode === 'technical' && ui.lastFlow) paint(ui.lastFlow);
      }, 160);
    }
    return Math.min(last + 1, first + run.count);
  }
  /* [fc-oneway] what the chart follows: the turn on air, else the last turn that
     aired - never the "planned - not aired yet" end, which is where it kept jumping */
  function followTarget() {
    if (ui.live && ui.mode === 'technical' && ui.actionRow && ui.actionRow.isConnected && !ui.actionRow.hidden) return ui.actionRow;
    if (ui.nowRow && ui.nowRow.isConnected && !ui.nowRow.hidden) return ui.nowRow;
    return ui.airedRow && ui.airedRow.isConnected && !ui.airedRow.hidden ? ui.airedRow : null;
  }
  /* [fc-design] one door for both styles; the last flow is kept to repaint a mode switch */
  function paint(flow) {
    if (!ui.body || !flow) return;
    ui.lastFlow = flow;
    if (flow.key) ui.cache[flow.key] = flow;
    var fresh = ui.mode === 'design' ? paintDesign(flow) : paintTech(flow);
    var c = flow.counts || {};
    var speaking = (flow.nodes || []).find(function (n) { return n.type === 'turn' && n.now; });
    say('#' + flow.key + ' · ' + (flow.road || '') + ' · ' + (c.decisions || 0) + ' draws · ' + (c.turns || 0)
      + ' turns (' + (c.aired || 0) + ' aired) · ' + (c.candidates_lost || 0) + ' candidates beaten'
      + (ui.live && speaking ? ' \u00b7 speaking: ' + (speaking.who || speaking.seat || '') + ' \u00b7 turn ' + (speaking.index + 1) : '')
      + (ui.follow ? '' : ' · not following - tap Follow'));
    if (ui.wantJump || (fresh && ui.follow)) {
      ui.wantJump = false;
      var body = ui.body;
      root.setTimeout(function () { if (ui.on && ui.body === body && ui.follow) scrollNow(); }, Math.min(fresh, ANIMATE_LAST) * STAGGER_MS + 40);
    }
  }
  /* [fc-design] "its blank atm": a conversation is hundreds of draws, and every new
     row waited 110 ms behind the one before - the last appeared a minute later, and
     the jump to the bottom landed on rows still invisible. Only the last few new
     rows animate now; the rest are there at once. */
  var ANIMATE_LAST = 8;
  function paintTech(flow) {
    if (flow.key !== ui.flowKey || ui.paintedMode !== 'technical' || ui.techRevision !== flow.revision) {
      ui.techRevision = flow.revision;
      ui.body.textContent = '';
      ui.shown = {};
      ui.flowKey = flow.key;
      ui.paintedMode = 'technical';
      ui.nowRow = null; ui.airedRow = null;
      ui.prevSig = ''; ui.prevRow = null;                                 /* [fc-inspect] */
    }
    var nodes = ordered(flow);                                           /* [fc-oneway] */
    var upto = revealUpTo(flow);
    ui.nowRow = null; ui.airedRow = null; ui.actionRow = null;
    var news = 0;
    nodes.forEach(function (n, i) { if (i < upto && !ui.shown[n.id]) news += 1; });
    var fresh = 0;
    var visibleRows = new Set(nodes.slice(0, upto).map(function (n) { return ui.shown[n.id]; }).filter(Boolean));
    nodes.forEach(function (n, i) {
      var had = ui.shown[n.id];
      if (i >= upto) { if (had && !visibleRows.has(had)) had.hidden = true; return; }
      if (had && n.type === 'turn' && n.now) ui.nowRow = had;            /* [air-jump-any] */
      if (had && n.type === 'turn' && (n.said || n.aired_at)) ui.airedRow = had;   /* [fc-oneway] */
      if (had) {
        had.hidden = false;
        if (n.type === 'decision' && JSON.stringify(had.__node) !== JSON.stringify(n)) {
          had.replaceChild(decisionNode(n, 0), had.querySelector('.fc-decision')); had.__node = n;
        }
        if (n.type === 'turn' && JSON.stringify(had.__node) !== JSON.stringify(n)) {
          had.__node = n;
          var repl = nodeFor(n, 0);
          had.replaceChild(repl, had.querySelector('.fc-node'));
        }
        return;
      }
      /* [fc-inspect] the same step or gate again and again ("speakerbox" x3) is
         one row with a count, not a wall of copies */
      var sig = (n.type === 'step' || n.type === 'gate') ? n.type + '|' + (n.label || '') + '|' + (n.text || '') : '';
      if (sig && sig === ui.prevSig && ui.prevRow && ui.prevRow.isConnected) {
        ui.shown[n.id] = ui.prevRow;
        ui.prevRow.__count = (ui.prevRow.__count || 1) + 1;
        var times = ui.prevRow.querySelector('.fc-times') || ui.prevRow.querySelector('.fc-node').appendChild(make('span', 'fc-times'));
        times.textContent = '×' + ui.prevRow.__count;
        (ui.prevRow.__nodes = ui.prevRow.__nodes || [ui.prevRow.__node]).push(n);
        return;
      }
      var k = fresh - (news - ANIMATE_LAST);
      var delay = k > 0 ? k * STAGGER_MS : 0;
      var row = make('div', 'fc-row fc-row-' + n.type);
      var lab = i ? edgeLabel(flow, n.id) : '';
      if (i) row.appendChild(make('div', 'fc-edge', lab ? '▼ ' + lab : '▼'));
      row.appendChild(nodeFor(n, delay));
      if (k >= 0) {
        row.classList.add('fc-enter');
        row.style.animationDelay = delay + 'ms';
      }
      ui.body.appendChild(row);
      ui.shown[n.id] = row;
      row.dataset.nodeId = n.id;
      row.__node = n;                                                     /* [fc-inspect] */
      ui.prevSig = sig; ui.prevRow = row;
      if (n.type === 'turn' && n.now) ui.nowRow = row;                    /* [air-jump-any] */
      if (n.type === 'turn' && (n.said || n.aired_at)) ui.airedRow = row;   /* [fc-oneway] */
      fresh += 1;
    });
    nodes.forEach(function (n, i) {
      var row = ui.shown[n.id]; if (!row) return;
      var active = ui.live && !!flow.now_turn && ui.unfold && i >= ui.unfold.first && i <= ui.unfold.last && i < upto;
      row.classList.toggle('fc-current-action', active);
      row.classList.remove('fc-active-step');
      if (active) ui.actionRow = row;
    });
    if (ui.actionRow) ui.actionRow.classList.add('fc-active-step');
    return fresh;
  }

  /* [fc-inspect] "I need to be able to tap and hold to bring up an inspection panel
     explaining the origin and details of each node" (the operator, 2026-10-01).
     Hold (or right-click) any node in either style: what kind of node it is, what
     made it, and every fact System 3 recorded on it. */
  var FAMILY = {
    GRAPH: 'a node of the segment\'s chain graph (the NodePlan): who speaks next, whether the reply chain goes on, how the speaker takes what was said',
    ES: 'the Emotion Set: the feeling this line is voiced in', SFX: 'the sound effect after the line: whether and which',
    SFXGUY: 'the SFX Guy: whether he punctuates this line with a clip', STATION: 'a station dice door: a pick the station made through System 3 (a document, a pool, an ad, a slot)',
    RS: 'the Response Style: how the speaker answers what was said', IRS: 'the Inner Response Style: how the speaker takes it inside',
    FL: 'the Flow: where the conversation moves next (stay, deepen, change, concede)', CUTIN: 'whether someone cuts in this round',
    SPEAKERBOX: 'whether a Speakerbox passage is dealt into the turn, and how', GOLD: 'whether a kept gold take is reused',
    TEMPER: 'the writer\'s temperature for the round', CTS: 'the current topic\'s subject', MEASURE: 'how the round is measured against its time',
    LENGTH: 'how long the round runs', TOPIC: 'the topic change: what the conversation turns to', REPAIR: 'whether a broken draft is repaired',
    ROOM: 'which room the round is made in', SHOCK: 'a shock: something outrageous dropped into the round', MEMORY: 'what the cast remembers from earlier',
    FAV: 'a cast favourite surfacing', MENTION: 'a mention of something the station knows', CALLARC: 'the arc of a phone call',
    CALLSHIFT: 'a detour in a phone call', EVENT: 'a live station event lending lines', WRAP: 'how the round wraps up', RESOLVE: 'how a planned turn is resolved'};
  var KIND = {
    start: 'Where this conversation began: the road that asked for it, the subject System 3 was handed, its running order and the seed every roll is drawn from.',
    decision: 'A roll System 3 made: a drum of candidates, each with its weight, and a d100 that picked one. The winner steered the conversation; the others are what it beat.',
    turn: 'A planned turn of the conversation: who was elected to speak, what the plan asked of them, how they feel, and - once written and aired - what they said.',
    gate: 'A gate: a check System 3 ran on the writing, and what it caught or changed here.',
    step: 'A step System 3 recorded while building the round (a prompt sent, a gate, a passage placed).',
    end: 'Where the conversation stands now.'};
  function inspectRows(n) {
    var out = [];
    function add(k, v) { if (v != null && v !== '' && !(Array.isArray(v) && !v.length)) out.push([k, v]); }
    add('node', n.id);
    add('properties and changes', n.properties);
    add('recorded stages, options and exclusions', n.stages);
    add('selected command', n.selected);
    add('state before', n.state_before); add('state after', n.state_after);
    if (n.type === 'decision') {
      add('family', (n.family || '') + (FAMILY[n.family] ? ' - ' + FAMILY[n.family] : ''));
      add('drawn from', (n.path || []).join(' › '));
      add('d100', n.dice == null ? 'no random number (pinned or a single choice)' : n.dice);
      add('odds', n.odds != null ? pct(n.odds) + ' to happen' : '');
      add('drum', n.of ? n.of + ' candidates' : '');
      if (n.winner) add('landed', n.winner.label + (n.winner.p != null ? '  (' + pct(n.winner.p) + ')' : '') + (n.winner.why && n.winner.why.length ? '  - ' + n.winner.why.join('; ') : ''));
      add('beat', (n.losers || []).map(function (l) { return l.label + (l.p != null ? ' ' + pct(l.p) : ''); }).join('  |  ') + (n.more ? '  |  +' + n.more + ' more' : ''));
      add('could not come up', n.excluded);
      add('for turn', n.turn_index >= 0 ? n.turn_index + 1 : 'the round as a whole');
      add('pinned', n.fixed ? 'yes - the roulette was off for this draw' : '');
    } else if (n.type === 'turn') {
      var rl = n.__role || roleOf(n);
      add('role', rl === 'initiator' ? 'Initiator' : rl === 'rebuttal' ? 'Rebuttal' : rl === 'topic' ? 'Topic Change' : 'Reply');
      add('speaker', (n.who || '') + (n.seat ? '  (seat ' + n.seat + ')' : ''));
      add('asked to', n.asked); add('said', n.said); add('feeling', n.feeling);
      add('answers', n.reply_to ? n.reply_to.name + ' · turn ' + (n.reply_to.index + 1) : '');
      add('turn credit', n.turn_credit ? '+1 · mainline turn restored' : '');
      add('exchange', n.cast_reaction ? 'Cast reaction' : n.returns_to_topic ? 'Topic instigator resumes' : n.inner_reply ? 'Inner reply chain' : 'Mainline');
      add('leg', [n.leg, n.place].filter(Boolean).join(' / '));
      add('line codes', (n.codes || []).join(', '));
      add('aired', n.aired_at ? new Date(n.aired_at * 1000).toLocaleTimeString() : 'not yet - planned');
      add('on air now', n.now ? 'yes' : '');
    } else if (n.type === 'start') {
      add('road', n.road); add('subject', n.topic); add('structure', n.structure); add('seed', n.seed);
      add('turns planned', n.turns); add('budget', n.budget);
    } else {
      add('what', n.label); add('detail', n.text);
      if (n.facts) Object.keys(n.facts).forEach(function (k) { add(k, n.facts[k]); });
    }
    if (n.at) add('recorded at', new Date(n.at * 1000).toLocaleTimeString());
    return out;
  }
  function openInspect(n, many) {
    closeInspect();
    var pop = make('section', 'fc-inspect');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Inspect this node');
    var x = make('button', 'fc-inspect-x', '×');
    x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', closeInspect);
    var title = n.type === 'decision' ? (n.family || 'roll') + ' roll' : n.type === 'turn' ? (n.who || n.seat || 'turn') + ' - turn ' + (n.index + 1)
      : n.type === 'start' ? 'Conversation #' + String(n.id).split(':')[1] : (n.label || n.type);
    pop.append(x, make('h3', '', title), make('p', 'fc-inspect-kind', KIND[n.type] || ''));
    if (many && many.length > 1) pop.appendChild(make('p', 'fc-inspect-kind', 'Recorded ' + many.length + ' times in a row here - shown once.'));
    var dl = make('dl', 'fc-inspect-dl');
    inspectRows(n).forEach(function (r) { dl.append(make('dt', '', r[0]), make('dd', '', typeof r[1] === 'object' ? JSON.stringify(r[1]) : String(r[1]))); });
    pop.appendChild(dl);
    (ui.pane || document.body).appendChild(pop);
    seatPop(pop);                                                          /* [fc-seat] clear of the tabs */
    ui.inspect = pop;
  }
  /* [fc-seat] "I can't close this pop-up because the X is under these tabs": the
     pane runs under the tablet's rail (#pineViewRail, painted over everything). A
     popup measures the rail and keeps its right edge - and its X - clear of it. */
  function seatPop(pop) {
    try {
      var rail = document.getElementById('pineViewRail');
      var host = pop.offsetParent || ui.pane;
      if (!rail || !host) return;
      var rr = rail.getBoundingClientRect(), hr = host.getBoundingClientRect();
      if (!rr.width || rr.left >= hr.right) return;
      pop.style.right = Math.max(12, Math.round(hr.right - rr.left) + 10) + 'px';
    } catch (e) { /* the default inset stands */ }
  }
  function closeInspect() { if (ui.inspect) { ui.inspect.remove(); ui.inspect = null; } }
  function nodeAt(el) {
    while (el && el !== ui.body) { if (el.__node) return el; el = el.parentNode; }
    return null;
  }
  function wireHold(body) {
    var timer = 0, sx = 0, sy = 0;
    function cancel() { if (timer) { root.clearTimeout(timer); timer = 0; } }
    body.addEventListener('pointerdown', function (ev) {
      if (ui.inspect) closeInspect();                  /* [fc-seat] a tap on the chart closes the popup */
      var host = nodeAt(ev.target);
      if (!host || (ev.button != null && ev.button > 0)) return;
      sx = ev.clientX; sy = ev.clientY;
      cancel();
      timer = root.setTimeout(function () { timer = 0; openInspect(host.__node, host.__nodes); }, 480);
    });
    body.addEventListener('pointermove', function (ev) { if (timer && Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 10) cancel(); });
    ['pointerup', 'pointercancel', 'pointerleave', 'scroll'].forEach(function (k) { body.addEventListener(k, cancel, {passive: true}); });
    body.addEventListener('contextmenu', function (ev) {
      var host = nodeAt(ev.target);
      if (!host) return;
      ev.preventDefault();
      openInspect(host.__node, host.__nodes);
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeInspect(); });
  }

  /* [fc-design] THE DESIGN FLOWCHART, the operator's NodePlan drawn from the record
     (docs/NodePlan/NODE_img.png, nodeplan.md): the chain's spine - Initiator, its
     Replies hanging off it, the Rebuttal back on the spine, the Topic Change that
     segues to the next chapter - with the dice that steered it as diamonds between
     the boxes (their odds as 1:N, the d100 they landed), the raffle's electee mark on
     every speaker, and planned turns not yet spoken as dashed boxes. */
  var DESIGN_DICE = {GRAPH: 1, CUTIN: 1, FL: 1, TOPIC: 1, LENGTH: 1, TEMPER: 1, SHOCK: 1};
  function roleOf(t) {
    var a = String(t.asked || t.leg || '').toLowerCase();
    if (/opens this chapter|opens the subject|initiat/.test(a)) return 'initiator';
    if (/answers the replies to their opening|^rebut/.test(a)) return 'rebuttal';
    if (/segues|next discussion point|topic change|new topic/.test(a)) return 'topic';
    return 'reply';
  }
  function odds(n) {
    if (n.odds != null && Number(n.odds) > 0) {
      var p = Number(n.odds);
      return p >= 0.95 ? 'sure' : (p <= 0.5 && Math.abs(1 / p - Math.round(1 / p)) < 0.08 ? '1:' + Math.round(1 / p) : Math.round(p * 100) + '%');
    }
    return n.of > 1 ? '1:' + n.of : '';
  }
  function designDiamond(n) {
    var row = make('div', 'fd-diarow');
    row.__node = n;                                                        /* [fc-inspect] */
    var dia = make('span', 'fd-dia');
    dia.appendChild(make('span', 'fd-dia-in', n.dice == null ? '–' : String(n.dice)));
    row.appendChild(dia);
    var o = odds(n);
    row.appendChild(make('span', 'fd-dia-odds', o ? '(' + o + ')' : ''));
    var w = n.winner ? n.winner.label : (n.path || []).slice(-1)[0] || n.label;
    row.appendChild(make('span', 'fd-dia-label', (n.family === 'GRAPH' ? n.kind || 'GRAPH' : n.family || 'roll') + ': ' + cut(w, 80)));
    row.title = (n.path || []).join(' › ') + (n.of ? '  ·  ' + n.of + ' in the drum' : '')
      + ((n.losers || []).length ? '\nbeat: ' + n.losers.map(function (l) { return l.label + (l.p != null ? ' ' + pct(l.p) : ''); }).join(' | ') : '');
    row.appendChild(rouletteOptions(n));
    return row;
  }
  function designBox(t, label, role) {
    var spoken = !!(t.said || t.aired_at);
    var box = make('div', 'fd-box fd-' + role + (spoken ? '' : ' planned') + (t.now ? ' now' : ''));
    box.__node = t;                                                        /* [fc-inspect] */
    var head = make('div', 'fd-box-head');
    head.appendChild(make('b', '', label));
    var elect = make('span', 'fd-elect');
    elect.title = (t.who || t.seat) + ' - elected from the cast for this place (the raffle)';
    elect.appendChild(make('i', 'fd-elect-dot'));
    elect.appendChild(make('i', 'fd-elect-dia'));
    head.appendChild(elect);
    head.appendChild(make('span', 'fd-who', (t.who || t.seat || '') + (t.feeling ? ' · ' + t.feeling : '')));
    (t.codes || []).forEach(function (c) { head.appendChild(codeChip(c, t)); });
    box.appendChild(head);
    box.appendChild(make('p', spoken && t.said ? 'fd-said' : 'fd-asked', spoken && t.said ? '“' + cut(t.said, 300) + '”' : cut(t.asked, 220)));
    replyTrail(box, t);
    if (t.properties) box.appendChild(rouletteOptions(t));
    return box;
  }
  function replyTrail(box, t) {
    box.dataset.turnId = t.turn_id || '';
    if (!t.reply_to) return;
    var line = make('p', 'fc-sub', (t.cast_reaction ? 'Cast reaction → ' : t.returns_to_topic ? 'Return to topic · answers ' : t.inner_reply ? 'Inner reply → ' : 'Answers ')
      + t.reply_to.name + ' · turn ' + (t.reply_to.index + 1) + (t.turn_credit ? ' · +1 turn restored' : ''));
    line.title = 'Response link: ' + t.reply_to.turn_id;
    var jump = make('button', 'fc-code', 'View answered turn');
    jump.type = 'button';
    jump.onclick = function (e) {
      e.stopPropagation();
      var target = Array.prototype.find.call(ui.body.querySelectorAll('[data-turn-id]'), function (n) {
        return n.dataset.turnId === t.reply_to.turn_id;
      });
      if (target) {
        ui.autoAt = Date.now(); target.scrollIntoView({block: 'center'});
        target.classList.add('fc-flash'); root.setTimeout(function () { target.classList.remove('fc-flash'); }, 1400);
      }
    };
    line.appendChild(document.createTextNode(' ')); line.appendChild(jump);
    box.appendChild(line);
  }
  function paintDesign(flow) {
    var nodes = ordered(flow);                                           /* [fc-oneway] */
    var upto = revealUpTo(flow);
    var turns = [], byTurn = {}, globalDecisions = [];
    nodes.forEach(function (n, i) {
      if (i >= upto) return;
      if (n.type === 'turn') turns.push(n);
      else if (n.type === 'decision' && n.turn_index >= 0) {
        (byTurn[n.turn_index] = byTurn[n.turn_index] || []).push(n);
      } else if (n.type === 'decision') globalDecisions.push(n);
    });
    var sig = JSON.stringify(nodes.slice(0, upto)) + '|' + flow.key + '|' + flow.revision + '|' + turns.map(function (t) { return t.index + (t.said ? 's' : '') + (t.now ? 'n' : ''); }).join(',');
    if (sig === ui.designSig && ui.paintedMode === 'design') return 0;
    var before = ui.designCount || 0;
    var sameFlow = ui.flowKey === flow.key && ui.paintedMode === 'design';
    ui.designSig = sig;
    ui.flowKey = flow.key;
    ui.paintedMode = 'design';
    ui.shown = {};
    ui.nowRow = null; ui.airedRow = null;
    var keep = ui.body.scrollTop;
    ui.body.textContent = '';
    var chart = make('div', 'fd-chart');
    var start = nodes[0] && nodes[0].type === 'start' ? nodes[0] : null;
    if (start) chart.appendChild(make('div', 'fd-title', cut([start.road, start.topic].filter(Boolean).join(' · '), 200)));
    globalDecisions.forEach(function (d) { chart.appendChild(designDiamond(d)); });
    if (start && start.properties) chart.appendChild(rouletteOptions(start));
    var chapter = 0, replyN = 0, chain = null;
    turns.forEach(function (t, k) {
      var role = k === 0 ? 'initiator' : roleOf(t);       /* a chain always opens on its Initiator */
      t.__role = role;                                     /* [fc-inspect] the panel names the same place */
      if (role === 'initiator' || !chain) {
        chapter += 1; replyN = 0;
        chain = make('section', 'fd-chain');
        chain.appendChild(make('div', 'fd-chapter', 'Chapter ' + chapter));
        chart.appendChild(chain);
      }
      (byTurn[t.index] || []).forEach(function (d) { chain.appendChild(designDiamond(d)); });
      var label = role === 'initiator' ? 'Initiator' : role === 'rebuttal' ? 'Rebuttal'
        : role === 'topic' ? 'Topic Change' : 'Reply ' + String.fromCharCode(65 + (replyN++ % 26));
      var box = designBox(t, label, role);
      if (sameFlow && k >= before) box.classList.add('fc-enter');
      chain.appendChild(box);
      if (t.now) ui.nowRow = box;
      if (t.said || t.aired_at) ui.airedRow = box;                       /* [fc-oneway] */
    });
    var end = nodes[nodes.length - 1];
    if (end && end.type === 'end') chart.appendChild(make('div', 'fd-end', end.label));
    ui.body.appendChild(chart);
    if (sameFlow) ui.body.scrollTop = keep;
    var fresh = sameFlow ? Math.max(0, turns.length - before) : turns.length;
    ui.designCount = turns.length;
    return fresh;
  }

  /* [air-jump-any] the strip's tap while the chart is up: back to Live, and to the
     turn going out now (the last shown node when the chart names none). */
  function lastRow() {
    if (!ui.body) return null;
    var all = ui.body.querySelectorAll('.fc-row:not([hidden]), .fd-box');
    return all.length ? all[all.length - 1] : ui.body.lastElementChild;
  }
  function scrollNow() {
    var r = followTarget() || (ui.body && ui.body.firstElementChild);   /* [fc-oneway] the latest aired turn; nothing aired: the top */
    if (!r || !r.scrollIntoView) return;
    ui.autoAt = Date.now();                                  /* our own scroll, not the operator's */
    try { r.scrollIntoView({block: 'center'}); } catch (e) { r.scrollIntoView(); }   /* instant: a smooth glide outlived the guard and read as the operator scrolling away */
    r.classList.add('fc-flash');
    root.setTimeout(function () { r.classList.remove('fc-flash'); }, 1400);
  }
  /* [fc-design] "If i am on the latest message, have it scroll to the next flowchart
     items and continue to follow it unless I scroll away from the active" (the
     operator, 2026-10-01). A hand scroll that leaves the active node and the end
     stops the following; scrolling back to either, Follow, Live or the strip's tap
     starts it again. Never a timed re-follow. */
  function onScroll() {
    if (Date.now() - ui.autoAt < 900 && Date.now() > (ui.handScrollUntil || 0)) return;
    var b = ui.body;
    var atEnd = b.scrollHeight - b.scrollTop - b.clientHeight < 140;
    var act = followTarget();                                  /* [fc-oneway] */
    var seeAct = false;
    if (act) {
      var br = b.getBoundingClientRect(), ar = act.getBoundingClientRect();
      seeAct = ar.bottom > br.top && ar.top < br.bottom;
    }
    setFollow(atEnd || seeAct);
  }
  function setFollow(on) {
    if (ui.follow === !!on) return;
    ui.follow = !!on;
    if (ui.followBtn) {
      ui.followBtn.hidden = ui.follow;
    }
  }
  function jumpLive(lid) {
    if (!ui.on) return false;
    if (!ui.live) {
      ui.live = true; ui.flowKey = ''; ui.nowRow = null;
      if (ui.liveBtn) ui.liveBtn.setAttribute('aria-pressed', 'true');
    }
    ui.request += 1; ui.busy = false;
    ui.jumpLid = /^[0-9a-f]{6,32}$/i.test(String(lid || '')) ? String(lid).toLowerCase() : '';
    ui.liveLine = stripLine();
    ui.fallbackFor = '';
    ui.wantJump = true;
    setFollow(true);
    scrollNow();
    tick();
    return true;
  }
  function stripLine() {
    var value = ui.playback || (root.PineStationFeed && root.PineStationFeed.latest && root.PineStationFeed.latest());
    var lid = '';
    if (value && Object.prototype.hasOwnProperty.call(value, 'now')) lid = String(value.now && value.now.id || '').toLowerCase();
    else try { lid = ui.lineSource ? String(ui.lineSource() || '').toLowerCase() : ''; } catch (e) { lid = ''; }
    return /^[0-9a-f]{6,32}$/.test(lid) ? lid : '';
  }
  function receivePlayback(value) {
    ui.playback = value;
    if (!ui.on || !ui.live) return;
    var lid = stripLine();
    if (lid !== ui.liveLine) {
      ui.liveLine = lid; ui.request += 1; ui.busy = false;
      stopUnfold(); ui.unfold = null; ui.actionRow = null; ui.nowRow = null;
      if (ui.body) ui.body.querySelectorAll('.fc-current-action,.fc-active-step,.fc-turn.now').forEach(function (n) { n.classList.remove('fc-current-action', 'fc-active-step', 'now'); });
      say(lid ? 'Reading recorded actions for #' + lid : 'Waiting for the next speaking reply');
      tick();
    } else if (ui.lastFlow && ui.unfold && ui.unfold.count <= ui.unfold.last - ui.unfold.first) paint(ui.lastFlow);
  }
  function tick() {
    if (!ui.on) return;
    var live = ui.live, key = ui.key, lid = live ? (stripLine() || ui.jumpLid || '') : '';
    if (live && !lid && ui.playback && Object.prototype.hasOwnProperty.call(ui.playback, 'now')) {
      say('Waiting for the next speaking reply'); return;
    }
    var path = live ? (lid ? '/api/flow/' + encodeURIComponent(lid) : '/api/flow/now') : '/api/flow/' + encodeURIComponent(key);
    if (ui.busy === path) return;
    ui.busy = path;
    var ticket = ++ui.request;
    get(path).then(function (d) {
      if (!ui.on || ticket !== ui.request || live !== ui.live || (!live && key !== ui.key) || (live && stripLine() && stripLine() !== lid)) return;
      var flow = live && !lid ? d && d.live && d.flow : d;
      if (flow && flow.nodes) {
        if (live) {
          var turns = flow.nodes.filter(function (n) { return n.type === 'turn'; });
          var turn = turns.find(function (n) { return (n.codes || []).indexOf(lid) >= 0; }) || turns.find(function (n) { return n.now; });
          if (lid && !turn) { say('Waiting for recorded actions for #' + lid); return; }
          if (lid && turn) {
            flow.now_turn = turn.turn_id || turn.id;
            turns.forEach(function (n) { n.now = n === turn; });
            var row = ui.playback && ui.playback.now;
            if (row && String(row.id) === lid && row.text) turn.said = String(row.text);
          }
          ui.lastLive = flow.key; ui.jumpLid = '';
        }
        paint(flow);
      } else say(d && d.why || 'Waiting for the speaking reply recorded flow');
    }, function (err) {
      if (ui.on && ticket === ui.request) say(live && lid ? 'Waiting for recorded actions for #' + lid : String(err && err.message || err));
    }).then(function () { if (ticket === ui.request) ui.busy = false; });
  }

  function loadRecent() {
    get('/api/flow/recent?limit=40').then(function (d) {
      if (!ui.recent) return;
      ui.recent.textContent = '';
      ui.recent.appendChild(make('option', '', 'recent conversations…'));
      ((d && d.conversations) || []).forEach(function (c) {
        var cid = String(c.conversation_id || c.id || '');
        if (!cid) return;
        if (!ui.recentFirst) ui.recentFirst = cid;                         /* [air-jump-any] Live's last resort */
        var o = make('option', '', cid + ' · ' + (c.road || '') + (c.topic ? ' · ' + cut(c.topic, 40) : ''));
        o.value = cid;
        ui.recent.appendChild(o);
      });
    }, function () { /* the list is a convenience */ });
  }

  function openKey(key) {
    key = String(key || '').trim().replace(/^#/, '').toLowerCase();
    if (!/^[0-9a-f]{6,32}$/.test(key)) { say('a key is hex: a conversation\'s 16 or a line\'s code'); return; }
    ui.live = false; ui.request += 1; ui.busy = false; stopUnfold(); ui.unfold = null; ui.actionRow = null;
    ui.key = key;
    ui.flowKey = '';
    if (ui.liveBtn) ui.liveBtn.setAttribute('aria-pressed', 'false');
    tick();
  }

  function build(pane) {
    ui.paintedMode = ''; ui.shown = {}; ui.nowRow = null; ui.actionRow = null;
    pane.textContent = '';
    pane.classList.add('fc-pane');
    var bar = make('div', 'fc-bar');
    bar.appendChild(make('b', 'fc-title', 'FLOWCHART'));
    ui.liveBtn = make('button', 'fc-btn', 'Live');
    ui.liveBtn.type = 'button';
    ui.liveBtn.title = 'Follow the conversation on air';
    ui.liveBtn.setAttribute('aria-pressed', 'true');
    ui.liveBtn.addEventListener('click', function () {
      jumpLive();
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
    /* [fc-design] "Technical and Design flowchart mode": the draws as they were made, or
       the NodePlan chain (Initiator, Replies, Rebuttal, Topic Change) */
    ui.modeBtn = make('button', 'fc-btn fc-mode', '');
    ui.modeBtn.type = 'button';
    ui.modeBtn.addEventListener('click', function () { setMode(ui.mode === 'design' ? 'technical' : 'design'); });
    bar.appendChild(ui.modeBtn);
    ui.followBtn = make('button', 'fc-btn fc-follow', 'Follow');
    ui.followBtn.type = 'button';
    ui.followBtn.title = 'Go back to the active node and follow it again';
    ui.followBtn.hidden = ui.follow;
    ui.followBtn.addEventListener('click', function () { setFollow(true); scrollNow(); });
    bar.appendChild(ui.followBtn);
    pane.appendChild(bar);
    ui.status = make('div', 'fc-status', 'reading…');
    pane.appendChild(ui.status);
    ui.body = make('div', 'fc-body');
    ui.body.addEventListener('scroll', onScroll, {passive: true});
    function handScroll() { ui.handScrollUntil = Date.now() + 1500; }
    ['wheel', 'touchmove', 'pointerdown'].forEach(function (name) { ui.body.addEventListener(name, handScroll, {passive: true}); });
    ui.body.addEventListener('keydown', function (e) { if (/^(ArrowUp|ArrowDown|PageUp|PageDown|Home|End)$/.test(e.key)) handScroll(); });
    wireHold(ui.body);                                                     /* [fc-inspect] */
    pane.appendChild(ui.body);
    ui.pane = pane;
    paintMode();
  }
  function paintMode() {
    if (!ui.modeBtn) return;
    ui.modeBtn.textContent = ui.mode === 'design' ? 'Design' : 'Tech';
    ui.modeBtn.title = ui.mode === 'design'
      ? 'Design flowchart: every recorded roulette and the conversation chain - tap for Technical view'
      : 'Technical flowchart: every draw as it was made - tap for the Design flowchart (the NodePlan chain)';
    ui.modeBtn.setAttribute('aria-pressed', String(ui.mode === 'design'));
    if (ui.pane) ui.pane.classList.toggle('fc-design', ui.mode === 'design');
  }
  function setMode(mode) {
    ui.mode = mode === 'design' ? 'design' : 'technical';
    try { if (root.localStorage) root.localStorage.setItem('pine.fc.mode', ui.mode); } catch (e) { /* no storage */ }
    paintMode();
    ui.paintedMode = '';
    ui.designSig = '';
    ui.wantJump = true;
    setFollow(true);
    if (ui.lastFlow) paint(ui.lastFlow);
  }

  function show(pane, on) {
    on = !!on;
    if (on && pane && ui.pane !== pane) build(pane);
    ui.on = on; ui.request += 1; ui.busy = false;
    if (ui.feedLeave) { ui.feedLeave(); ui.feedLeave = null; }
    stopUnfold();
    if (ui.timer) { root.clearInterval(ui.timer); ui.timer = 0; }
    if (on) {
      loadRecent();
      // Subscribe only while open; the shared feed supplies the exact playback line.
      if (root.PineStationFeed && root.PineStationFeed.subscribe) ui.feedLeave = root.PineStationFeed.subscribe(receivePlayback);
      tick();
      ui.timer = root.setInterval(tick, POLL_MS);
    }
  }
  /* [fc-design] "the flowchart system needs to be auto generating and perpetual": off
     screen, the live conversation is read every BG_MS and kept, so the chart opens on
     the latest one already built. */
  function background() {
    if (ui.on) return;
    try { if (root.document && root.document.hidden) return; } catch (e) { /* read anyway */ }
    get('/api/flow/now').then(function (d) {
      if (d && d.live && d.flow) { ui.bgFlow = d.flow; ui.lastLive = d.flow.key; ui.cache[d.flow.key] = d.flow; }
    }, function () { /* the next pass tries again */ });
  }
  if (!root.PINE_NATIVE_TOOLS) {
    root.setInterval(background, BG_MS);
    root.setTimeout(background, 1500);
  }

  root.PineFlowChart = {show: show, open: openKey, isOn: function () { return ui.on; }, jumpLive: jumpLive,
    lineSource: function (fn) { ui.lineSource = typeof fn === 'function' ? fn : null; },   /* [fc-stay] the strip's line */
    _paint: paint};
})(typeof window !== 'undefined' ? window : globalThis);
