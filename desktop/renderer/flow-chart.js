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
            mode: 'technical', follow: true, cache: {}, lastFlow: null, autoAt: 0, modeBtn: null, followBtn: null};
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
    (n.codes || []).forEach(function (c) { top.appendChild(codeChip(c, n)); });
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
    flow.__ordered = out.map(function (x) { return x.n; });
    flow.__orderedOf = nodes;
    return flow.__ordered;
  }
  function revealUpTo(flow) {
    /* live: up to the turn going out now (and what comes straight after it); otherwise all */
    var nodes = ordered(flow);
    if (!ui.live || !flow.now_turn) return nodes.length;
    var at = -1;
    for (var i = 0; i < nodes.length; i += 1) if (nodes[i].type === 'turn' && nodes[i].now) at = i;
    if (at < 0) return nodes.length;
    for (var j = at + 1; j < nodes.length && (nodes[j].type === 'gate' || nodes[j].type === 'step'); j += 1) at = j;
    return at + 1;
  }
  /* [fc-oneway] what the chart follows: the turn on air, else the last turn that
     aired - never the "planned - not aired yet" end, which is where it kept jumping */
  function followTarget() {
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
    say('#' + flow.key + ' · ' + (flow.road || '') + ' · ' + (c.decisions || 0) + ' draws · ' + (c.turns || 0)
      + ' turns (' + (c.aired || 0) + ' aired) · ' + (c.candidates_lost || 0) + ' candidates beaten'
      + (ui.follow ? '' : ' · not following - tap Follow'));
    if (ui.wantJump || (fresh && ui.follow)) {
      ui.wantJump = false;
      root.setTimeout(scrollNow, Math.min(fresh, ANIMATE_LAST) * STAGGER_MS + 40);
    }
  }
  /* [fc-design] "its blank atm": a conversation is hundreds of draws, and every new
     row waited 110 ms behind the one before - the last appeared a minute later, and
     the jump to the bottom landed on rows still invisible. Only the last few new
     rows animate now; the rest are there at once. */
  var ANIMATE_LAST = 8;
  function paintTech(flow) {
    if (flow.key !== ui.flowKey || ui.paintedMode !== 'technical') {
      ui.body.textContent = '';
      ui.shown = {};
      ui.flowKey = flow.key;
      ui.paintedMode = 'technical';
      ui.nowRow = null; ui.airedRow = null;
      ui.prevSig = ''; ui.prevRow = null;                                 /* [fc-inspect] */
    }
    var nodes = ordered(flow);                                           /* [fc-oneway] */
    var upto = revealUpTo(flow);
    var news = 0;
    nodes.forEach(function (n, i) { if (i < upto && !ui.shown[n.id]) news += 1; });
    var fresh = 0;
    nodes.forEach(function (n, i) {
      var had = ui.shown[n.id];
      if (i >= upto) { if (had) had.hidden = true; return; }
      if (had && n.type === 'turn' && n.now) ui.nowRow = had;            /* [air-jump-any] */
      if (had && n.type === 'turn' && (n.said || n.aired_at)) ui.airedRow = had;   /* [fc-oneway] */
      if (had) {
        had.hidden = false;
        if (n.type === 'turn') {
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
      row.__node = n;                                                     /* [fc-inspect] */
      ui.prevSig = sig; ui.prevRow = row;
      if (n.type === 'turn' && n.now) ui.nowRow = row;                    /* [air-jump-any] */
      if (n.type === 'turn' && (n.said || n.aired_at)) ui.airedRow = row;   /* [fc-oneway] */
      fresh += 1;
    });
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
    row.appendChild(make('span', 'fd-dia-label', (n.family || 'roll') + ': ' + cut(w, 80)));
    row.title = (n.path || []).join(' › ') + (n.of ? '  ·  ' + n.of + ' in the drum' : '')
      + ((n.losers || []).length ? '\nbeat: ' + n.losers.map(function (l) { return l.label + (l.p != null ? ' ' + pct(l.p) : ''); }).join(' | ') : '');
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
    return box;
  }
  function paintDesign(flow) {
    var nodes = ordered(flow);                                           /* [fc-oneway] */
    var upto = revealUpTo(flow);
    var turns = [], byTurn = {};
    nodes.forEach(function (n, i) {
      if (i >= upto) return;
      if (n.type === 'turn') turns.push(n);
      else if (n.type === 'decision' && DESIGN_DICE[n.family] && n.turn_index >= 0) {
        (byTurn[n.turn_index] = byTurn[n.turn_index] || []).push(n);
      }
    });
    var sig = flow.key + '|' + turns.map(function (t) { return t.index + (t.said ? 's' : '') + (t.now ? 'n' : ''); }).join(',');
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
    if (Date.now() - ui.autoAt < 900) return;
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
    ui.jumpLid = /^[0-9a-f]{6,32}$/i.test(String(lid || '')) ? String(lid).toLowerCase() : '';
    ui.fallbackFor = '';
    ui.wantJump = true;
    setFollow(true);
    scrollNow();
    tick();
    return true;
  }
  /* [air-jump-any] "its blank atm": what is on air has no System 3 conversation (a
     board clip, a record), so Live showed nothing. Live now shows, in order: the
     conversation of the line the strip was tapped on (by its line code, with that
     line's turn marked), the last conversation that aired live, the newest one. */
  /* [fc-stay] "Why does this collapse back instead of stay open and continue going to
     the next message?" (the operator, 2026-10-01). /api/flow/now knows only a line
     announced on its own; while a streamed round plays it says "nothing is on air",
     and every two seconds the chart fell back to the NEWEST conversation - a one-line
     board clip - dropping the one being heard. Live now follows the line the strip is
     playing (its conversation, its turn marked, tiles revealed as it advances); a
     strip line with no conversation (a clip) leaves the open conversation open. The
     newest conversation is only a first paint, never a replacement. */
  var NO_FLOW = {}, noFlowN = 0;
  function stripLine() {
    var lid = '';
    try { lid = ui.lineSource ? String(ui.lineSource() || '').toLowerCase() : ''; } catch (e) { lid = ''; }
    return /^[0-9a-f]{6,32}$/.test(lid) ? lid : '';
  }
  function fallbackShow(why) {
    var lid = ui.jumpLid || stripLine();
    if (lid && !NO_FLOW[lid]) {
      get('/api/flow/' + encodeURIComponent(lid)).then(function (f) {
        if (!ui.on || !ui.live) return;
        if (f && f.nodes) {
          ui.jumpLid = '';
          paint(f);
          say(why + ' - following the line in the strip (#' + f.key + ')');
        } else {
          markNoFlow(lid); keepShown(why);
        }
      }, function () { markNoFlow(lid); keepShown(why); });
      return;
    }
    keepShown(why);
  }
  function markNoFlow(lid) {
    if (noFlowN > 600) { NO_FLOW = {}; noFlowN = 0; }
    NO_FLOW[lid] = 1; noFlowN += 1;
    if (ui.jumpLid === lid) ui.jumpLid = '';
  }
  function keepShown(why) {
    if (ui.flowKey) {                                   /* stay: refresh what is open, now and then */
      if (Date.now() - (ui.keptAt || 0) < 6000) return;
      ui.keptAt = Date.now();
      var key = ui.flowKey;
      get('/api/flow/' + encodeURIComponent(key)).then(function (f) {
        if (ui.on && ui.live && f && f.nodes && f.key === ui.flowKey) paint(f);
      }, function () { /* the next pass tries again */ });
      return;
    }
    firstPaint(why);
  }
  function firstPaint(why) {
    var keys = [ui.lastLive, ui.recentFirst].filter(function (k, i, a) { return k && a.indexOf(k) === i; });
    var want = keys.join('|');
    if (ui.fallbackFor === want) return;
    ui.fallbackFor = want;
    (function tryNext(i) {
      if (i >= keys.length) { if (!ui.flowKey) say(why); return; }
      get('/api/flow/' + encodeURIComponent(keys[i])).then(function (f) {
        if (!ui.on || !ui.live) return;
        if (!(f && f.nodes)) { tryNext(i + 1); return; }
        if (ui.flowKey) return;                         /* the strip's line got there first */
        var which = keys[i] === ui.lastLive ? 'the last conversation that aired' : 'the newest conversation';
        paint(f);
        say(why + ' - showing ' + which + ' (#' + f.key + ')');
      }, function () { tryNext(i + 1); });
    }(0));
  }

  function tick() {
    if (!ui.on || ui.busy) return;
    ui.busy = true;
    var path = ui.live ? '/api/flow/now' : '/api/flow/' + encodeURIComponent(ui.key);
    get(path).then(function (d) {
      if (!ui.on) return;
      if (ui.live) {
        if (d && d.live && d.flow) { ui.lastLive = d.flow.key; ui.fallbackFor = ''; paint(d.flow); }
        else fallbackShow(d && d.why ? d.why : 'nothing is on air');
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
    wireHold(ui.body);                                                     /* [fc-inspect] */
    pane.appendChild(ui.body);
    ui.pane = pane;
    paintMode();
  }
  function paintMode() {
    if (!ui.modeBtn) return;
    ui.modeBtn.textContent = ui.mode === 'design' ? 'Design' : 'Tech';
    ui.modeBtn.title = ui.mode === 'design'
      ? 'Design flowchart: the chain as the NodePlan draws it - tap for the Technical flowchart (every draw)'
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
    ui.on = on;
    if (ui.timer) { root.clearInterval(ui.timer); ui.timer = 0; }
    if (on) {
      loadRecent();
      /* [fc-design] the moment the chart is opened: the latest conversation the
         background kept, at once, then the live read */
      if (ui.live && ui.bgFlow && ui.body && !ui.body.childElementCount) { ui.wantJump = true; paint(ui.bgFlow); }
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
  root.setInterval(background, BG_MS);
  root.setTimeout(background, 1500);

  root.PineFlowChart = {show: show, open: openKey, isOn: function () { return ui.on; }, jumpLive: jumpLive,
    lineSource: function (fn) { ui.lineSource = typeof fn === 'function' ? fn : null; },   /* [fc-stay] the strip's line */
    _paint: paint};
})(typeof window !== 'undefined' ? window : globalThis);
