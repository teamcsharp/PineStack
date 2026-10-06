/* [blocked-book] THE BLOCKED BOOK - every blocked case, one list, five sorts.
 *
 * "At the top of The Works put a 2nd tab that shows each and every blocked
 * listing. I want to see each and every blocked case listed with an
 * expandable tri that tells me what system did it, why was it blocked, the
 * rule causing the block, what section got it blocked, where the gate that
 * blocked it is located, the System 3 roulette roll that caused the
 * rejection. Offer a button to sort by rule, time/date, segment, roulette
 * roll, node."                                        - the operator, 2026-10-06
 *
 * Reads GET /api/blocked (blocked_book.py). Portable: mount(host, {get}) takes
 * any fetcher that returns parsed JSON, so The Works on the desk, the PiP's
 * popup and the tablet's view all paint the same book. The reader is never
 * moved: a repaint keeps every open row open and never scrolls; new rows are
 * added in place of the old list only when the set actually changed.
 */
(function (root) {
  'use strict';
  if (root.PineBlockedBook) return;

  var SORTS = [
    ['time', 'time / date', function (r) { return -(Number(r.at) || 0); }],
    ['rule', 'rule', function (r) { return String(r.rule || '').toLowerCase(); }],
    ['section', 'segment', function (r) { return String(r.section || '~').toLowerCase(); }],
    ['roll', 'roulette roll', function (r) {
      var k = r.roll || {};
      return (k.conversation_id ? '' : '~') + String(k.family || '~') + '|' + String(k.d100 == null ? '~' : k.d100) + '|' + String(k.conversation_id || '');
    }],
    ['node', 'node', function (r) { return String(r.node || (r.roll && r.roll.turn_id) || '~').toLowerCase(); }],
  ];

  function el(tag, cls, text) {
    var n = root.document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function when(ts) {
    if (!ts) return '-';
    var d = new Date(Number(ts) * 1000);
    var p = function (x) { return (x < 10 ? '0' : '') + x; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function ago(ts) {
    if (!ts) return '';
    var s = Math.max(0, Date.now() / 1000 - Number(ts));
    if (s < 90) return Math.round(s) + ' s ago';
    if (s < 5400) return Math.round(s / 60) + ' min ago';
    if (s < 172800) return (s / 3600).toFixed(1) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }
  function cut(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function rollWords(roll) {
    roll = roll || {};
    if (!roll.conversation_id && roll.d100 == null && !roll.family) return 'no roll on record';
    var bits = [];
    if (roll.family) bits.push(roll.family);
    if (roll.item) bits.push('→ ' + roll.item);
    if (roll.d100 != null) bits.push('d100 ' + (Number(roll.d100) <= 1 ? Math.round(Number(roll.d100) * 100) : roll.d100));
    if (roll.turn_id) bits.push('turn ' + roll.turn_id);
    if (roll.conversation_id) bits.push('round ' + roll.conversation_id);
    if (roll.decisions != null) bits.push(roll.decisions + ' decisions');
    return bits.join(' · ');
  }
  function gateWords(gate) {
    gate = gate || {};
    var where = (gate.file || '') + (gate.line ? ':' + gate.line : '');
    var fn = gate.fn ? gate.fn + '()' : '';
    var out = [fn, where].filter(Boolean).join('  in  ');
    if (gate.note) out += '  — ' + gate.note;
    return out || 'not located';
  }

  function mount(host, opts) {
    opts = opts || {};
    var get = opts.get;
    var state = {sort: 'time', dir: 1, standing: true, history: true, q: '', rows: [], sig: '', open: {}, timer: 0, busy: false, counts: {}};
    try { var saved = JSON.parse(root.localStorage.getItem('pine.blockedbook') || '{}'); if (saved.sort) state.sort = saved.sort; if (saved.dir) state.dir = saved.dir; if (typeof saved.standing === 'boolean') state.standing = saved.standing; if (typeof saved.history === 'boolean') state.history = saved.history; } catch (e) { /* first run */ }
    host.textContent = '';
    host.classList.add('bb-host');

    var bar = el('div', 'bb-bar');
    var sortLabel = el('span', 'bb-label', 'sort by');
    bar.appendChild(sortLabel);
    var sortBtns = {};
    SORTS.forEach(function (s) {
      var b = el('button', 'bb-sort', s[1]);
      b.type = 'button';
      b.title = 'Sort the book by ' + s[1] + ' (press again to reverse)';
      b.onclick = function () {
        if (state.sort === s[0]) state.dir = -state.dir; else { state.sort = s[0]; state.dir = 1; }
        remember(); paint(true);
      };
      sortBtns[s[0]] = b;
      bar.appendChild(b);
    });
    var standing = el('button', 'bb-flag', 'standing');
    standing.type = 'button';
    standing.title = 'Cases that block right now (the cupboard, the dynamic segments)';
    standing.onclick = function () { state.standing = !state.standing; remember(); load(true); };
    var history = el('button', 'bb-flag', 'history');
    history.type = 'button';
    history.title = 'Cases the ledgers recorded as they happened (the flow ledger, no-repeat, hand-overs, the pen, System 3)';
    history.onclick = function () { state.history = !state.history; remember(); load(true); };
    bar.appendChild(standing);
    bar.appendChild(history);
    var search = el('input', 'bb-search');
    search.type = 'search';
    search.placeholder = 'filter: rule, segment, words…';
    search.oninput = function () { state.q = String(search.value || '').toLowerCase(); paint(true); };
    bar.appendChild(search);
    var status = el('span', 'bb-status', '');
    bar.appendChild(status);
    host.appendChild(bar);

    var counts = el('div', 'bb-counts');
    host.appendChild(counts);
    var list = el('div', 'bb-list');
    host.appendChild(list);

    function remember() {
      try { root.localStorage.setItem('pine.blockedbook', JSON.stringify({sort: state.sort, dir: state.dir, standing: state.standing, history: state.history})); } catch (e) { /* no storage */ }
    }

    function fetchRows() {
      var path = '/api/blocked?limit=600&standing=' + (state.standing ? 1 : 0) + '&history=' + (state.history ? 1 : 0);
      if (typeof get === 'function') return Promise.resolve(get(path));
      var base = '';
      try { base = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (e) { base = ''; }
      var headers = {};
      try { var k = typeof root.key === 'function' ? root.key() : (root.PINE_KEY || ''); if (k) headers.Authorization = 'Bearer ' + k; } catch (e) { /* no key */ }
      return root.fetch(base.replace(/\/$/, '') + path, {headers: headers}).then(function (r) { return r.json(); });
    }

    function load(force) {
      if (state.busy) return;
      state.busy = true;
      fetchRows().then(function (got) {
        state.busy = false;
        if (!got || !Array.isArray(got.rows)) { status.textContent = 'the book could not be read'; return; }
        var sig = got.rows.map(function (r) { return r.key; }).join('|');
        state.counts = got.counts || {};
        status.textContent = got.say || (got.rows.length + ' case(s)');
        if (sig === state.sig && !force) return;
        state.rows = got.rows;
        state.sig = sig;
        paint(false);
      }).catch(function (e) { state.busy = false; status.textContent = 'the book could not be read: ' + (e && e.message || e); });
    }

    function visible() {
      var q = state.q;
      var rows = state.rows.filter(function (r) {
        if (!q) return true;
        var hay = [r.system, r.rule, r.why, r.section, r.node, r.ref, r.text, (r.gate || {}).fn].join(' ').toLowerCase();
        return hay.indexOf(q) >= 0;
      });
      var spec = SORTS.filter(function (s) { return s[0] === state.sort; })[0] || SORTS[0];
      var keyOf = spec[2];
      rows.sort(function (a, b) {
        var ka = keyOf(a), kb = keyOf(b);
        var c = (ka < kb ? -1 : ka > kb ? 1 : 0);
        if (c === 0) c = (Number(b.at) || 0) - (Number(a.at) || 0);
        return c * state.dir;
      });
      return rows;
    }

    function row(r) {
      var d = el('details', 'bb-row bb-' + String(r.system || '').replace(/[^a-z0-9]+/g, '-'));
      d.dataset.key = r.key;
      if (state.open[r.key]) d.open = true;
      d.ontoggle = function () { state.open[r.key] = d.open; };
      var s = el('summary', 'bb-sum');
      s.appendChild(el('span', 'bb-when', ago(r.at)));
      s.appendChild(el('span', 'bb-sys', r.system || ''));
      s.appendChild(el('span', 'bb-rule', cut(r.rule || '', 44)));
      s.appendChild(el('span', 'bb-seg', r.section || '-'));
      s.appendChild(el('span', 'bb-why', cut(r.why || '', 120)));
      if (r.standing) s.appendChild(el('span', 'bb-standing', 'standing'));
      d.appendChild(s);
      var body = el('dl', 'bb-body');
      function kv(k, v, cls) {
        var dt = el('dt', '', k); var dd = el('dd', cls || '', v == null || v === '' ? '-' : String(v));
        body.appendChild(dt); body.appendChild(dd);
        return dd;
      }
      kv('what system did it', r.system);
      kv('why it was blocked', r.why);
      if (r.fix) kv('what would free it', r.fix);
      kv('the rule causing the block', r.rule);
      kv('what section got it blocked', (r.section || '-') + (r.node ? '  · node ' + r.node : ''));
      var g = kv('where the gate is located', gateWords(r.gate), 'bb-gate');
      g.title = 'file:line and the function that holds the gate';
      kv('System 3 roulette roll', rollWords(r.roll), 'bb-roll');
      kv('when', when(r.at) + (r.at ? '  (' + ago(r.at) + ')' : ''));
      if (r.ref) {
        var dd = kv('reference', r.ref);
        var ref = String(r.ref);
        if (/^[a-f0-9]{16}$/i.test(ref) || (r.roll && r.roll.conversation_id)) {
          var b = el('button', 'bb-open', 'open the round');
          b.type = 'button';
          b.onclick = function (ev) {
            ev.preventDefault();
            var cid = (r.roll && r.roll.conversation_id) || ref;
            try { if (typeof root.system3Open === 'function') { root.system3Open('audit'); } } catch (e) { /* no window here */ }
            try { if (root.PineFlowChart && typeof root.PineFlowChart.openKey === 'function') root.PineFlowChart.openKey(cid); } catch (e) { /* no chart here */ }
            try { if (typeof opts.openRound === 'function') opts.openRound(cid, r); } catch (e) { /* the host's own door */ }
          };
          dd.appendChild(root.document.createTextNode('  '));
          dd.appendChild(b);
        }
      }
      if (r.text) kv('the words', cut(r.text, 400), 'bb-text');
      d.appendChild(body);
      return d;
    }

    function paint(keepScroll) {
      var top = list.scrollTop;
      Object.keys(sortBtns).forEach(function (k) {
        sortBtns[k].classList.toggle('on', k === state.sort);
        sortBtns[k].textContent = (SORTS.filter(function (s) { return s[0] === k; })[0] || [])[1] + (k === state.sort ? (state.dir > 0 ? ' ▾' : ' ▴') : '');
      });
      standing.classList.toggle('on', state.standing);
      history.classList.toggle('on', state.history);
      counts.textContent = '';
      var bySys = (state.counts && state.counts.system) || {};
      Object.keys(bySys).sort(function (a, b) { return bySys[b] - bySys[a]; }).forEach(function (k) {
        var chip = el('span', 'bb-chip', k + ' ' + bySys[k]);
        chip.onclick = function () { search.value = k; state.q = k.toLowerCase(); paint(true); };
        counts.appendChild(chip);
      });
      var rows = visible();
      var frag = root.document.createDocumentFragment();
      if (!rows.length) frag.appendChild(el('div', 'bb-empty', state.rows.length ? 'nothing matches the filter' : 'nothing is blocked'));
      rows.slice(0, 600).forEach(function (r) { frag.appendChild(row(r)); });
      list.textContent = '';
      list.appendChild(frag);
      if (keepScroll) list.scrollTop = top;
    }

    load(true);
    state.timer = root.setInterval(function () {
      if (!host.isConnected) { root.clearInterval(state.timer); return; }
      if (host.offsetParent === null && !opts.always) return;   /* hidden: do not fetch */
      load(false);
    }, Number(opts.pollMs) || 6000);
    return {
      refresh: function () { load(true); },
      close: function () { root.clearInterval(state.timer); },
      count: function () { return state.rows.length; },
    };
  }

  root.PineBlockedBook = {mount: mount, SORTS: SORTS.map(function (s) { return s[0]; })};
})(typeof window !== 'undefined' ? window : this);
