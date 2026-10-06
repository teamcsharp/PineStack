/* [prod-feed] THE PAUSE, AS A FEED.
 *
 * "When the station is paused, I want a script scrolling a feed of the
 * generative production of banking on the backend. I want to see dice and
 * roulette animations and RNG results for the conversations and paths being
 * split showing dialogue winning over other dialogue."  - the operator, 2026-10-01
 *
 * Mounted above the script feed (#spFeed) while the station is paused.
 * script-page.js tells it when that changes: PineProductionFeed.paused(bool).
 * Everything drawn is a recorded fact from GET /api/production/feed: the
 * reel lands on the candidate System 3 actually picked, the die shows the
 * draw it actually made, and the losers are the candidates it actually beat.
 */
(function (root) {
  'use strict';

  var POLL_MS = 2000;
  var KEEP = 160;            /* rows kept in the panel */
  var SPIN_MS = 1400;
  var STAGE_NAMES = ['written', 'emoted', 'recorded', 'banked'];
  var ES_DIMS = ['tempo', 'pitch', 'range', 'energy', 'pause'];

  var ui = {box: null, list: null, head: null, on: false, timer: 0, busy: false,
            cursor: {s3: 0, n: 0, t: 0}, seen: 0, follow: true, rolls: 0, banked: 0};

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
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
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
  function clock(at) {
    try {
      var d = new Date(Number(at) * 1000);
      return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2) + ':' + ('0' + d.getSeconds()).slice(-2);
    } catch (e) { return ''; }
  }
  function roadName(r) {
    return {caller: 'CALL', manager: 'MEMO', banter: 'BANTER', ad: 'AD', station_id: 'STATION ID',
      gallery: 'GALLERY', news: 'NEWS', recap: 'RECAP'}[String(r || '')] || String(r || '').toUpperCase();
  }
  function head(text, n) {
    var lines = String(text || '').split('\n').filter(function (l) { return l.trim(); });
    return lines.slice(0, n || 4).join('\n') + (lines.length > (n || 4) ? '\n…' : '');
  }

  /* ------------------------------------------------------------ the die and the reel */
  function die(value) {
    var d = make('span', 'pf-die', '?');
    var final = value == null ? '–' : String(value);
    var t0 = Date.now();
    (function spin() {
      if (!d.isConnected && Date.now() - t0 > 100) { d.textContent = final; return; }
      if (Date.now() - t0 >= SPIN_MS) { d.textContent = final; d.classList.add('landed'); return; }
      d.textContent = String(1 + Math.floor(Math.random() * 100));
      root.setTimeout(spin, 60);
    }());
    d.title = value == null ? 'no random number - this draw was pinned or had one choice' : 'd100: ' + final;
    return d;
  }
  function reel(opts, hit) {
    var H = 26;
    var win = make('div', 'pf-reel');
    var strip = make('div', 'pf-strip');
    var list = opts.length > 1 ? opts.concat(opts) : opts.slice();
    var land = opts.length > 1 ? opts.length + hit : hit;
    list.forEach(function (o, i) { strip.appendChild(make('div', 'pf-card' + (i === land ? ' hit' : ''), o)); });
    win.appendChild(strip);
    root.setTimeout(function () {
      strip.style.transition = 'transform ' + SPIN_MS + 'ms cubic-bezier(.12,.7,.18,1)';
      strip.style.transform = 'translateY(' + (-land * H) + 'px)';
    }, 40);
    return win;
  }

  /* ------------------------------------------------------------ rows */
  function rollNode(it) {
    var n = make('div', 'pf-row pf-roll');
    var top = make('div', 'pf-top');
    top.appendChild(make('span', 'pf-time', clock(it.at)));
    if (it.road) top.appendChild(make('span', 'pf-road', roadName(it.road)));
    top.appendChild(make('b', 'pf-title', it.title || 'a roll'));
    if (it.speaker) top.appendChild(make('span', 'pf-dim', it.speaker));
    n.appendChild(top);
    (it.rows || []).forEach(function (r) {
      var m = r.main || {};
      var line = make('div', 'pf-rollline');
      line.appendChild(die(m.dice));
      var body = make('div', 'pf-rollbody');
      body.appendChild(make('span', 'pf-table', String(r.table || '') + (m.of ? '  ·  ' + m.of + ' in the drum' : '')));
      body.appendChild(reel((m.opts || [m.label || '?']).map(String), Math.max(0, Number(m.hit) || 0)));
      var won = r.winner;
      if (won || (r.losers && r.losers.length)) {
        var v = make('div', 'pf-verdict');
        if (won) v.appendChild(make('span', 'pf-win', '▲ ' + won.label + (won.p != null ? ' (' + pct(won.p) + ')' : '')));
        (r.losers || []).forEach(function (l) {
          v.appendChild(make('span', 'pf-lose', l.label + (l.p != null ? ' (' + pct(l.p) + ')' : '')));
        });
        if (won && won.why && won.why.length) v.title = won.why.join('; ');
        body.appendChild(v);
      }
      line.appendChild(body);
      n.appendChild(line);
    });
    if (it.why) n.appendChild(make('p', 'pf-dim', it.why));
    return n;
  }
  function stageNode(it) {
    var n = make('div', 'pf-row pf-stage pf-' + String(it.stage || ''));
    var top = make('div', 'pf-top');
    top.appendChild(make('span', 'pf-time', clock(it.at)));
    top.appendChild(make('span', 'pf-road', roadName(it.road)));
    var track = make('span', 'pf-track');
    var reached = STAGE_NAMES.indexOf(String(it.stage || ''));
    STAGE_NAMES.forEach(function (s, i) {
      track.appendChild(make('span', 'pf-step' + (i < reached ? ' done' : i === reached ? ' now' : ''), s));
    });
    top.appendChild(track);
    n.appendChild(top);
    var facts = [];
    if (it.caller) facts.push('caller: ' + it.caller);
    if (it.outcome) facts.push('it ends: ' + it.outcome);
    if (it.seconds) facts.push(it.seconds + 's');
    if (it.made != null && it.lines) facts.push(it.made + ' of ' + it.lines + ' lines voiced');
    if (it.shelf) facts.push(it.shelf + ' on the shelf');
    if (it.off_brief) facts.push('OFF BRIEF - it will not air');
    if (it.discarded) facts.push('DISCARDED');
    if (facts.length) n.appendChild(make('div', 'pf-facts', facts.join('  ·  ')));
    if (it.text) n.appendChild(make('pre', 'pf-script', head(it.text, it.stage === 'written' ? 8 : 3)));
    return n;
  }
  function emoteNode(it) {
    var n = make('div', 'pf-row pf-emote');
    var top = make('div', 'pf-top');
    top.appendChild(make('span', 'pf-time', clock(it.at)));
    top.appendChild(make('span', 'pf-road', 'EMOTED'));
    top.appendChild(make('b', 'pf-title', String(it.speaker || '')));
    top.appendChild(make('span', 'pf-dim', it.shaped ? 'shaped by the emotion engine' : 'no emotion on this line'));
    n.appendChild(top);
    if (it.text) n.appendChild(make('p', 'pf-said', '“' + it.text + '”'));
    var es = it.es || {};
    var bars = make('div', 'pf-es');
    ES_DIMS.forEach(function (k) {
      if (es[k] == null) return;
      var v = Number(es[k]);
      var cell = make('span', 'pf-esdim');
      cell.appendChild(make('i', '', k));
      var bar = make('span', 'pf-esbar');
      var fill = make('span', 'pf-esfill');
      fill.style.width = Math.max(4, Math.min(100, Math.round(v * 50))) + '%';
      bar.appendChild(fill);
      cell.appendChild(bar);
      cell.title = k + ' ' + v.toFixed(2);
      bars.appendChild(cell);
    });
    if (bars.childNodes.length) n.appendChild(bars);
    return n;
  }
  function plainNode(it) {
    var n = make('div', 'pf-row pf-' + (it.type === 'gate' ? 'gate' : 'note'));
    var top = make('div', 'pf-top');
    top.appendChild(make('span', 'pf-time', clock(it.at)));
    top.appendChild(make('span', 'pf-road', it.type === 'gate' ? String(it.title || it.family || 'gate').toUpperCase()
      : String(it.kind || 'note').toUpperCase()));
    top.appendChild(make('span', 'pf-text', String(it.text || '')));
    n.appendChild(top);
    return n;
  }
  function nodeFor(it) {
    if (it.type === 'roll') return rollNode(it);
    if (it.type === 'stage') return stageNode(it);
    if (it.type === 'emote') return emoteNode(it);
    return plainNode(it);
  }

  /* ------------------------------------------------------------ the header */
  function paintHead(h) {
    var box = ui.head;
    if (!box) return;
    box.textContent = '';
    var bank = (h && h.bank) || {};
    var title = make('div', 'pf-headline');
    title.appendChild(make('b', '', 'THE PAUSE IS BANKING'));
    title.appendChild(make('span', 'pf-dim', ui.rolls + ' roll(s) and ' + ui.banked + ' banked round(s) seen here'));
    box.appendChild(title);
    var needs = (h && h.needs) || {};
    var meters = make('div', 'pf-meters');
    Object.keys(needs).sort().forEach(function (k) {
      var r = needs[k] || {};
      var owed = Number(r.owed) || 0, held = Number(r.held) || 0;
      var m = make('div', 'pf-meter');
      m.appendChild(make('span', 'pf-road', roadName(k)));
      var bar = make('span', 'pf-bar');
      var fill = make('span', 'pf-fill');
      fill.style.width = (owed ? Math.min(100, Math.round(held / owed * 100)) : 100) + '%';
      bar.appendChild(fill);
      m.appendChild(bar);
      m.appendChild(make('span', 'pf-dim', Math.round(held / 60) + ' of ' + Math.round(owed / 60) + ' min'));
      meters.appendChild(m);
    });
    if (meters.childNodes.length) box.appendChild(meters);
    /* the operator's last sentence: "we dont make dialogue that is not being used" */
    var waste = make('div', 'pf-waste');
    waste.appendChild(make('span', '', (bank.unheard || 0) + ' banked round(s) never heard'));
    waste.appendChild(make('span', '', (bank.ready || 0) + ' ready to air'));
    waste.appendChild(make('span', bank.overdue ? 'pf-warn' : '', (bank.overdue || 0) + ' waiting past the dial'));
    waste.appendChild(make('span', '', (bank.aired_by_rescue || 0) + ' aired by the cupboard rescue'));
    box.appendChild(waste);
    var ends = bank.call_endings || {};
    if (ends.unheard_calls) {
      var e = make('div', 'pf-ends');
      e.appendChild(make('span', 'pf-dim', 'banked calls end: '));
      Object.keys(ends.endings || {}).slice(0, 8).forEach(function (k) {
        e.appendChild(make('span', 'pf-chip', k + ' × ' + ends.endings[k]));
      });
      box.appendChild(e);
    }
    var ref = bank.refusals || {};
    var refKeys = Object.keys(ref);
    if (refKeys.length) {
      var r2 = make('div', 'pf-refuse');
      r2.appendChild(make('span', 'pf-dim', 'refused: '));
      refKeys.slice(0, 4).forEach(function (k) { r2.appendChild(make('span', 'pf-chip warn', k + ' × ' + ref[k])); });
      box.appendChild(r2);
    }
  }

  /* ------------------------------------------------------------ the loop */
  function build() {
    if (ui.box) return ui.box;
    var feed = document.getElementById('spFeed');
    if (!feed || !feed.parentNode) return null;
    ui.box = make('section', 'pf-panel');
    ui.box.setAttribute('aria-label', 'What the pause is banking');
    ui.head = make('div', 'pf-head');
    ui.list = make('div', 'pf-list');
    ui.list.setAttribute('role', 'log');
    ui.list.setAttribute('aria-live', 'off');
    ui.list.addEventListener('scroll', function () {
      ui.follow = ui.list.scrollTop + ui.list.clientHeight >= ui.list.scrollHeight - 40;
    });
    ui.box.appendChild(ui.head);
    ui.box.appendChild(ui.list);
    feed.parentNode.insertBefore(ui.box, feed);
    return ui.box;
  }
  /* [feed-panel-home] the panel sits inside whichever pane is showing: first child of the
     Message view pane (a flex column, so the bubbles move down), else before the feed */
  function home() {
    if (!ui.box) return;
    var feed = document.getElementById('spFeed');
    var pane = document.getElementById('spMsgView');
    var paneUp = !!(pane && pane.style.display !== 'none' && pane.offsetParent !== null);
    if (paneUp) {
      if (ui.box.parentNode !== pane || pane.firstChild !== ui.box) pane.insertBefore(ui.box, pane.firstChild);
    } else if (feed && feed.parentNode && (ui.box.parentNode !== feed.parentNode || ui.box.nextSibling !== feed)) {
      feed.parentNode.insertBefore(ui.box, feed);
    }
  }
  function add(items) {
    if (!items || !items.length) return;
    var frag = document.createDocumentFragment();
    items.forEach(function (it) {
      if (it.type === 'roll') ui.rolls += 1;
      if (it.type === 'stage' && it.stage === 'banked') ui.banked += 1;
      try { frag.appendChild(nodeFor(it)); } catch (e) { /* one bad row never stops the feed */ }
    });
    ui.list.appendChild(frag);
    while (ui.list.childNodes.length > KEEP) ui.list.removeChild(ui.list.firstChild);
    if (ui.follow) ui.list.scrollTop = ui.list.scrollHeight;
  }
  function tick() {
    if (!ui.on || ui.busy) return;
    if (!build()) return;
    try { home(); } catch (e) { /* [feed-panel-home] a pane mid-rebuild */ }
    ui.busy = true;
    var c = ui.cursor;
    get('/api/production/feed?s3=' + (c.s3 || 0) + '&n=' + (c.n || 0) + '&t=' + (c.t || 0))
      .then(function (d) {
        if (!ui.on) return;
        if (d && d.cursor) ui.cursor = d.cursor;
        add((d && d.items) || []);
        paintHead((d && d.header) || {});
      }, function () { /* the next tick tries again */ })
      .then(function () { ui.busy = false; });
  }
  function paused(on) {
    on = !!on;
    if (on === ui.on) return;
    ui.on = on;
    if (on) {
      if (!build()) { ui.on = false; return; }
      ui.box.hidden = false;
      tick();
      ui.timer = root.setInterval(tick, POLL_MS);
    } else {
      if (ui.timer) root.clearInterval(ui.timer);
      ui.timer = 0;
      if (ui.box) ui.box.hidden = true;
    }
  }

  root.PineProductionFeed = {paused: paused, isOn: function () { return ui.on; }};
})(typeof window !== 'undefined' ? window : globalThis);
