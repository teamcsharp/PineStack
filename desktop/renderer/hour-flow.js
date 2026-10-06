/* [hour-flow] THE HOUR'S ENTRY AS A VERTICAL FLOWCHART EDITOR.
 *
 * "convert 'the hour' view for a segment into a vertical flowchart ... back
 * button ... same style as the script view flowchart ... add, remove, insert,
 * adjust, extend nodes ... select a node to give more inner conversational
 * depth ... micro exchanges."                      - the operator, 2026-10-06
 * Edit scope, the operator's choice: "Both, with a toggle" - an edit applies
 * to THIS entry only, or to every entry of this kind.
 *
 * One node per leg of the entry's System 3 structure, top to bottom, in the
 * script view flowchart's look (flow-chart.css): the label, the seat, the act,
 * the family chips; the connectors between. Per node: insert after, remove,
 * move up / down, extend (a continuation), and select to open its
 * micro-exchanges - the inner rows planned right after that leg.
 *
 *   PineHourFlow.open({road, kind, slot_id, label, hour, onBack, scope})  a full-glass sheet
 *   PineHourFlow.mount(host, {road, kind, slot_id, label, get, put, del, onBack})  the tablet
 *   PineHourFlow.close()
 *
 * Reads   GET    /api/system3/structures/{road}?slot_id=
 * Writes  PUT    /api/system3/structures/{road}   {scope:"entry", slot_id, structure}  (this entry)
 *                                                 the structure itself              (every entry)
 *         DELETE /api/system3/structures/{road}?scope=entry&slot_id=   back to the road's own
 *
 * The reader is never moved: a repaint keeps the scroll where it was and
 * nothing here ever scrolls on its own. ASCII only; no emoji.
 */
(function (root) {
  'use strict';
  if (root.PineHourFlow) return;
  var doc = root.document;

  var FAMILIES = ['ES', 'RS', 'IRS', 'FL', 'CTS', 'REACT'];
  var FAMILY_WORDS = {
    ES: 'the feeling it is said in (Emotion Set)', RS: 'how it answers the line before (Response Style)',
    IRS: 'how it takes the line before, inside (Inner Response)', FL: 'where the talk goes next (Flow)',
    CTS: 'the subject (topic)', REACT: 'the stance taken (reaction)'
  };
  var SEATS = [['A', 'A - host'], ['B', 'B - co-host'], ['D', 'D - third seat'], ['C', 'C - caller'],
               ['E', 'E - second caller'], ['alternate', 'alternate - the next voice']];
  var PLACES = [['open', 'opening'], ['middle', 'middle - repeats to the turn budget'], ['close', 'closing']];
  var PLACE_WORD = {open: 'opening', middle: 'middle', close: 'closing'};
  var KIND_ROAD = {banter_caller: 'caller'};
  var NO_LEGS = {
    banter: 'Banter runs the cycle, not legs: its shape is edited in the System 3 window.',
    record: 'A record is not a conversation - the needle just drops.',
    deep: 'The deep stretch is written from the show itself; it has no legs to shape.'
  };
  var ui = {overlay: null, ctl: null, onKey: null};

  /* ------------------------------------------------------------ helpers */
  function make(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function svgX() {
    var ns = 'http://www.w3.org/2000/svg';
    var s = doc.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 16 16'); s.setAttribute('width', '16'); s.setAttribute('height', '16');
    s.setAttribute('aria-hidden', 'true');
    [['3', '3', '13', '13'], ['13', '3', '3', '13']].forEach(function (p) {
      var l = doc.createElementNS(ns, 'line');
      l.setAttribute('x1', p[0]); l.setAttribute('y1', p[1]); l.setAttribute('x2', p[2]); l.setAttribute('y2', p[3]);
      l.setAttribute('stroke', 'currentColor'); l.setAttribute('stroke-width', '2'); l.setAttribute('stroke-linecap', 'round');
      s.appendChild(l);
    });
    return s;
  }
  /* a label is cut at a word, never inside one */
  function cutWords(s, n) {
    s = String(s == null ? '' : s);
    if (s.length <= n) return s;
    var head = s.slice(0, n), at = head.lastIndexOf(' ');
    return (at > n * 0.5 ? head.slice(0, at) : head) + '...';
  }
  function clone(v) { return v == null ? v : JSON.parse(JSON.stringify(v)); }
  function stationKey() {
    try { if (typeof root.key === 'function') { var k = root.key(); if (typeof k === 'string' && k) return k; } } catch (e) { /* not the panel */ }
    try { /* eslint-disable-next-line no-undef */ if (typeof SERVER_KEY === 'string' && SERVER_KEY) return SERVER_KEY; } catch (e) { /* undeclared */ }
    try { return String(root.PINE_KEY || root.__PINE_VIDEO_EDITOR_KEY || ''); } catch (e) { return ''; }
  }
  function stationBase() {
    if (root.PINE_BASE) return String(root.PINE_BASE).replace(/\/$/, '');
    try { if (/^https?:$/.test(String(root.location.protocol))) return ''; } catch (e) { /* no location */ }
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (e) { b = ''; }
    return (b || 'http://10.89.1.246:8096').replace(/\/$/, '');
  }
  /* the desk's bridge (pineDesktop.get/post/put/del), else the station over HTTP with the key:
     the same door on the desk, the PiP tools page and the tablet */
  function request(method, path, body) {
    var verb = method === 'DELETE' ? 'del' : String(method).toLowerCase();
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge[verb] === 'function') {
      return Promise.resolve(body === undefined ? bridge[verb](path) : bridge[verb](path, body)).then(function (got) {
        if (got && got.ok === false && got.detail) throw new Error(String(got.detail));
        if (got && typeof got.detail === 'string' && !got.structure && !got.road) throw new Error(got.detail);
        return got;
      });
    }
    var headers = {}, key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return root.fetch(stationBase() + path, {method: method, headers: headers, cache: 'no-store',
                                             body: body === undefined ? undefined : JSON.stringify(body)})
      .then(function (r) {
        return r.json().then(function (got) {
          if (!r.ok) throw new Error(typeof got.detail === 'string' ? got.detail : (got.why || 'The station refused this.'));
          return got;
        });
      });
  }
  function roadOf(opts) {
    var k = String(opts.road || opts.kind || '');
    return KIND_ROAD[k] || k;
  }
  function familiesOf(leg) {
    var out = [];
    (leg.draws || []).forEach(function (d) { if (d && d.family && out.indexOf(d.family) < 0) out.push(d.family); });
    return out;
  }
  function toggleFamily(leg, fam) {
    var draws = (leg.draws || []).filter(function (d) { return d && d.family; });
    var has = draws.some(function (d) { return d.family === fam; });
    if (has) draws = draws.filter(function (d) { return d.family !== fam; });
    else draws.push(fam === 'FL' ? (leg.place === 'close' ? {family: 'FL', tables: ['FL2'], closes: true} : {family: 'FL', tables: ['FL2']}) : {family: fam});
    if (!draws.length) draws.push({family: 'ES'});
    leg.draws = draws;
  }
  function freshId(legs, base) {
    base = String(base || 'leg').replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || 'leg';
    var taken = {};
    legs.forEach(function (l) { taken[String(l.id)] = true; });
    if (!taken[base]) return base;
    for (var i = 2; i < 1000; i += 1) if (!taken[base + '_' + i]) return base + '_' + i;
    return base + '_' + Date.now();
  }
  function newLeg(legs, like) {
    like = like || {};
    return {id: freshId(legs, (like.id ? like.id + '_next' : 'leg')), label: 'New turn',
            place: like.place || 'middle', seat: 'alternate',
            act: 'answers the line before, and says one thing of its own.',
            draws: [{family: 'ES'}, {family: 'RS'}]};
  }
  function extendLeg(legs, leg) {
    var on = clone(leg);
    on.id = freshId(legs, String(leg.id) + '_on');
    on.label = String(leg.label || leg.id) + ' (continued)';
    on.seat = 'alternate';
    on.act = 'Carries straight on from the turn before: ' + String(leg.act || '');
    delete on.inner;
    return on;
  }
  function turnsPlanned(st) {
    var legs = st.legs || [];
    var fixed = legs.filter(function (l) { return l.place !== 'middle'; }).length;
    var inner = 0;
    legs.forEach(function (l) { inner += (l.inner || []).filter(function (r) { return r && String(r.act || '').trim(); }).length; });
    var lo = Number(st.min_turns) || fixed, hi = Number(st.max_turns) || (fixed + inner);
    return {legs: legs.length, fixed: fixed, inner: inner, lo: lo, hi: hi,
            floor: Math.max(fixed, lo) + inner, over: Math.max(fixed, lo) + inner > hi};
  }

  /* ------------------------------------------------------------ the editor */
  function mount(host, opts) {
    opts = opts || {};
    var get = typeof opts.get === 'function' ? opts.get : function (p) { return request('GET', p); };
    var put = typeof opts.put === 'function' ? opts.put : function (p, b) { return request('PUT', p, b); };
    var del = typeof opts.del === 'function' ? opts.del : function (p) { return request('DELETE', p); };
    var state = {road: roadOf(opts), kind: String(opts.kind || opts.road || ''), slot: String(opts.slot_id || ''),
                 label: String(opts.label || opts.kind || opts.road || ''), hour: String(opts.hour || ''),
                 scope: opts.scope === 'road' || opts.scope === 'entry' ? opts.scope : null,
                 server: null, drafts: {entry: null, road: null}, dirty: {entry: false, road: false},
                 selected: null, busy: false, dead: false};
    var path = '/api/system3/structures/' + encodeURIComponent(state.road);
    var entryQuery = '?slot_id=' + encodeURIComponent(state.slot);

    host.textContent = '';
    host.classList.add('hf-host');

    /* the bar: Back, the title, the X */
    var bar = make('div', 'hf-bar');
    var back = make('button', 'hf-btn hf-back', 'Back');
    back.type = 'button'; back.title = 'Back to the hour';
    back.setAttribute('aria-label', 'Back to the hour');
    back.addEventListener('click', function () { leave(false); });
    if (opts.back === false) back.hidden = true;
    bar.appendChild(back);
    var title = make('div', 'hf-title');
    title.appendChild(make('b', '', 'THE HOUR'));
    title.appendChild(make('span', 'hf-title-sub', cutWords(state.label, 60) + (state.slot ? '  -  entry ' + state.slot : '')
      + (state.hour ? '  -  ' + state.hour : '')));
    bar.appendChild(title);
    var status = make('span', 'hf-status', 'reading...');
    status.setAttribute('role', 'status');
    bar.appendChild(status);
    var x = make('button', 'hf-x');
    x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close');
    x.appendChild(svgX());
    x.addEventListener('click', function () { leave(true); });
    if (opts.close === false) x.hidden = true;
    bar.appendChild(x);
    host.appendChild(bar);

    /* the scope toggle: this entry only / every entry of the kind */
    var scopeRow = make('div', 'hf-scope');
    scopeRow.setAttribute('role', 'group'); scopeRow.setAttribute('aria-label', 'Edit scope');
    var scopeEntry = make('button', 'hf-scope-btn', 'this entry only');
    scopeEntry.type = 'button';
    scopeEntry.title = 'Edits apply to this running-order entry alone (' + (state.slot || 'no entry named') + '); every other ' + state.kind + ' entry keeps the road\'s shape';
    var scopeRoad = make('button', 'hf-scope-btn', 'every ' + (state.kind || 'such') + ' entry');
    scopeRoad.type = 'button';
    scopeRoad.title = 'Edits apply to the road itself: every ' + state.kind + ' entry without a shape of its own';
    scopeEntry.addEventListener('click', function () { setScope('entry'); });
    scopeRoad.addEventListener('click', function () { setScope('road'); });
    scopeRow.appendChild(make('span', 'hf-scope-label', 'edit'));
    scopeRow.appendChild(scopeEntry);
    scopeRow.appendChild(scopeRoad);
    var scopeNote = make('span', 'hf-scope-note', '');
    scopeRow.appendChild(scopeNote);
    host.appendChild(scopeRow);

    /* the chart and, under it, the inspector of the selected node */
    var body = make('div', 'hf-body');
    var chart = make('div', 'hf-chart');
    chart.setAttribute('role', 'list');
    body.appendChild(chart);
    var inspect = make('section', 'hf-inspect');
    inspect.setAttribute('aria-label', 'The selected turn');
    inspect.hidden = true;
    body.appendChild(inspect);
    host.appendChild(body);

    /* the foot: the turn bounds, Save, back to the default, Reload */
    var foot = make('div', 'hf-foot');
    var bounds = make('label', 'hf-bounds');
    bounds.appendChild(make('span', '', 'turns'));
    var minIn = make('input', 'hf-num'); minIn.type = 'number'; minIn.min = '1'; minIn.max = '60'; minIn.setAttribute('aria-label', 'Fewest turns');
    var maxIn = make('input', 'hf-num'); maxIn.type = 'number'; maxIn.min = '1'; maxIn.max = '60'; maxIn.setAttribute('aria-label', 'Most turns');
    bounds.appendChild(minIn); bounds.appendChild(make('span', '', 'to')); bounds.appendChild(maxIn);
    minIn.addEventListener('change', function () { var st = current(); if (st) { st.min_turns = clampTurns(minIn.value, st.min_turns); touched(); paint(); } });
    maxIn.addEventListener('change', function () { var st = current(); if (st) { st.max_turns = clampTurns(maxIn.value, st.max_turns); touched(); paint(); } });
    foot.appendChild(bounds);
    var save = make('button', 'hf-btn hf-save', 'Save');
    save.type = 'button';
    save.addEventListener('click', function () { doSave(); });
    foot.appendChild(save);
    var reset = make('button', 'hf-btn hf-reset', "Back to the road's default");
    reset.type = 'button';
    reset.addEventListener('click', function () { doReset(); });
    foot.appendChild(reset);
    var reload = make('button', 'hf-btn', 'Reload');
    reload.type = 'button'; reload.title = 'Read the station again (drops unsaved edits)';
    reload.addEventListener('click', function () { load(); });
    foot.appendChild(reload);
    var say = make('span', 'hf-say', '');
    foot.appendChild(say);
    host.appendChild(foot);

    function clampTurns(v, was) { var n = Math.round(Number(v)); return n >= 1 && n <= 60 ? n : was; }
    function tell(text) { if (!state.dead) status.textContent = String(text || ''); }
    function note(text) { if (!state.dead) say.textContent = String(text || ''); }
    function current() { return state.scope ? state.drafts[state.scope] : null; }
    function touched() { if (state.scope) state.dirty[state.scope] = true; }
    function leave(closing) {
      if (state.dead) return;
      if (typeof opts.onBack === 'function' && !closing) { try { opts.onBack(); } catch (e) { /* the host's door */ } return; }
      if (typeof opts.onClose === 'function') { try { opts.onClose(); } catch (e) { /* the host's door */ } return; }
      if (typeof opts.onBack === 'function') { try { opts.onBack(); } catch (e) { /* the host's door */ } }
    }

    function load() {
      state.busy = true;
      tell('reading...');
      return get(path + entryQuery).then(function (d) {
        if (state.dead) return;
        state.busy = false;
        if (!d || !d.structure) { tell('no structure came back'); return; }
        state.server = d;
        state.drafts.road = clone(d.road_structure || d.structure);
        state.drafts.entry = clone(d.scope === 'entry' ? d.structure : (d.road_structure || d.structure));
        if (d.scope !== 'entry') {
          /* a fresh entry draft starts as the road's shape; saved, it becomes this entry's own */
          delete state.drafts.entry.graph; delete state.drafts.entry.weight; delete state.drafts.entry.variant_of;
          state.drafts.entry.label = d.structure.label;
        }
        state.dirty = {entry: false, road: false};
        if (!state.scope) state.scope = state.slot && d.scope === 'entry' ? 'entry' : (state.slot ? 'entry' : 'road');
        if (!state.slot) state.scope = 'road';
        state.selected = null;
        tell((d.line_road ? 'a single-voice road - one leg, one seat' : (d.structure.legs || []).length + ' legs')
          + (d.scope === 'entry' ? ' - this entry runs a shape of its own' : ' - this entry runs the road\'s shape'));
        paint();
      }).catch(function (e) {
        if (state.dead) return;
        state.busy = false;
        var why = String(e && e.message || e);
        chart.textContent = '';
        chart.appendChild(make('div', 'hf-empty', NO_LEGS[state.kind] || NO_LEGS[state.road] || ('The station could not hand over this road\'s structure: ' + why)));
        tell('nothing to shape here');
        save.disabled = true; reset.disabled = true;
      });
    }

    function setScope(scope) {
      if (!state.drafts[scope]) return;
      if (scope === 'entry' && !state.slot) { note('this sheet was opened without an entry; the road is all there is to edit'); return; }
      state.scope = scope;
      state.selected = null;
      paint();
    }

    function doSave() {
      var st = current();
      if (!st || state.busy) return;
      var problems = check(st);
      if (problems.length) { note(problems[0]); return; }
      state.busy = true; save.disabled = true;
      note('saving...');
      var body = {legs: st.legs, label: st.label, head: st.head, tail: st.tail, min_turns: st.min_turns, max_turns: st.max_turns};
      if (st.alternate_seats) body.alternate_seats = st.alternate_seats;
      if (typeof st.topics === 'boolean') body.topics = st.topics;
      var payload = state.scope === 'entry' ? {scope: 'entry', slot_id: state.slot, structure: body} : body;
      put(path, payload).then(function (got) {
        if (state.dead) return;
        state.busy = false;
        var v = got && got.structure && got.structure.version;
        note(state.scope === 'entry' ? 'saved: this entry runs its own shape' + (v ? ' (v' + v + ')' : '')
                                     : 'saved: every ' + state.kind + ' entry without a shape of its own runs this' + (v ? ' (v' + v + ')' : ''));
        return load();
      }).catch(function (e) { if (state.dead) return; state.busy = false; save.disabled = false; note('not saved: ' + String(e && e.message || e)); });
    }

    function doReset() {
      if (!state.server || state.busy) return;
      if (state.scope === 'entry') {
        if (state.server.scope !== 'entry' && !state.server.entry_held) { note('this entry already runs the road\'s shape'); return; }
        state.busy = true; reset.disabled = true;
        note('dropping this entry\'s own shape...');
        del(path + '?scope=entry&slot_id=' + encodeURIComponent(state.slot)).then(function () {
          if (state.dead) return;
          state.busy = false;
          note('this entry is back on the road\'s shape');
          return load();
        }).catch(function (e) { if (state.dead) return; state.busy = false; reset.disabled = false; note('not dropped: ' + String(e && e.message || e)); });
        return;
      }
      var dflt = state.server.default;
      if (!dflt) { note('this road has no default to go back to'); return; }
      var st = state.drafts.road;
      st.legs = clone(dflt.legs); st.head = dflt.head; st.tail = dflt.tail; st.label = dflt.label;
      st.min_turns = dflt.min_turns; st.max_turns = dflt.max_turns;
      state.dirty.road = true; state.selected = null;
      note('the default legs are in the draft - Save to make every ' + state.kind + ' entry run them');
      paint();
    }

    function check(st) {
      var out = [];
      var legs = st.legs || [];
      if (!legs.length) out.push('a shape needs at least one turn');
      if (!legs.some(function (l) { return l.place === 'close'; })) out.push('a shape needs a closing turn');
      var ids = {};
      legs.forEach(function (l) {
        if (!l.id) out.push('every turn needs an id');
        if (ids[l.id]) out.push('turn ' + l.id + ' appears twice');
        ids[l.id] = true;
        if (!String(l.act || '').trim()) out.push('turn ' + (l.label || l.id) + ' needs its act (what it does)');
        (l.inner || []).forEach(function (r, i) { if (!String(r.act || '').trim()) out.push('exchange ' + (i + 1) + ' inside ' + (l.label || l.id) + ' needs its act'); });
      });
      return out;
    }

    /* --- the chart -------------------------------------------------------- */
    function paint() {
      if (state.dead) return;
      var st = current();
      var keep = body.scrollTop;                 /* the reader is never moved */
      scopeEntry.setAttribute('aria-pressed', String(state.scope === 'entry'));
      scopeRoad.setAttribute('aria-pressed', String(state.scope === 'road'));
      scopeEntry.classList.toggle('on', state.scope === 'entry');
      scopeRoad.classList.toggle('on', state.scope === 'road');
      scopeEntry.disabled = !state.slot;
      var sv = state.server || {};
      scopeNote.textContent = state.scope === 'entry'
        ? (sv.scope === 'entry' ? 'this entry has a shape of its own' + (state.dirty.entry ? ' - edited, not saved' : '')
                                : 'this entry runs the road\'s shape; Save gives it one of its own' + (state.dirty.entry ? ' (edited)' : ''))
        : ('the road\'s shape: every ' + state.kind + ' entry without one of its own' + (state.dirty.road ? ' - edited, not saved' : ''));
      chart.textContent = '';
      inspect.hidden = true;
      if (!st) { body.scrollTop = keep; return; }
      minIn.value = st.min_turns || ''; maxIn.value = st.max_turns || '';
      save.disabled = state.busy;
      reset.textContent = state.scope === 'entry' ? "Back to the road's default" : "Use the road's default legs";
      reset.title = state.scope === 'entry' ? 'Drop this entry\'s own shape: it runs the road\'s again'
                                            : 'Put the road\'s default legs in the draft (Save to keep them)';
      reset.disabled = state.busy || (state.scope === 'entry' && sv.scope !== 'entry' && !sv.entry_held);

      var legs = st.legs || [];
      var counts = turnsPlanned(st);
      var start = make('div', 'hf-node hf-start');
      start.setAttribute('role', 'listitem');
      start.appendChild(make('b', '', String(st.label || state.road)));
      start.appendChild(make('span', 'hf-sub', state.road + (state.scope === 'entry' ? ' - entry ' + state.slot : ' - the road')
        + ' - ' + counts.lo + ' to ' + counts.hi + ' turns' + (counts.inner ? ' - ' + counts.inner + ' inner exchange' + (counts.inner === 1 ? '' : 's') : '')));
      if (counts.over) start.appendChild(make('span', 'hf-warn', 'the legs and exchanges at the floor make ' + counts.floor + ' turns; most turns is ' + counts.hi + ' - the last exchanges would be left out'));
      chart.appendChild(start);

      legs.forEach(function (leg, i) {
        var row = make('div', 'hf-row hf-row-' + (leg.place || 'middle'));
        row.setAttribute('role', 'listitem');
        row.appendChild(make('div', 'hf-edge', (i === 0 ? 'opens with' : leg.place === 'middle' && legs[i - 1] && legs[i - 1].place === 'middle' ? 'then, to the budget' : 'then') + ''));
        row.appendChild(nodeFor(leg, i, legs));
        var inner = (leg.inner || []);
        inner.forEach(function (r, k) {
          var sub = make('div', 'hf-inner-row');
          sub.appendChild(make('div', 'hf-edge hf-edge-inner', 'inside, exchange ' + (k + 1)));
          var n = make('div', 'hf-node hf-inner' + (state.selected === leg.id ? ' selected' : ''));
          var top = make('div', 'hf-node-top');
          top.appendChild(make('b', '', cutWords(r.label || ('Exchange ' + (k + 1)), 50)));
          top.appendChild(make('span', 'hf-seat', 'seat ' + (r.seat || 'alternate')));
          n.appendChild(top);
          n.appendChild(make('p', 'hf-act', cutWords(r.act || '(no act yet)', 160)));
          var chips = make('div', 'hf-chips');
          ['ES'].concat((r.families || []).filter(function (f) { return f !== 'ES'; })).forEach(function (f) { chips.appendChild(chip(f, true)); });
          n.appendChild(chips);
          n.addEventListener('click', function (ev) { ev.stopPropagation(); select(leg.id); });
          sub.appendChild(n);
          row.appendChild(sub);
        });
        chart.appendChild(row);
      });
      var end = make('div', 'hf-node hf-end');
      end.setAttribute('role', 'listitem');
      end.appendChild(make('b', '', 'hands back to the show'));
      chart.appendChild(end);

      if (state.selected) {
        var sel = legs.filter(function (l) { return l.id === state.selected; })[0];
        if (sel) paintInspect(sel, legs);
      }
      body.scrollTop = keep;
    }

    function chip(fam, on, onToggle) {
      var c = make(onToggle ? 'button' : 'span', 'hf-chip hf-chip-' + fam + (on ? ' on' : ''), fam);
      if (onToggle) { c.type = 'button'; c.setAttribute('aria-pressed', String(!!on)); c.addEventListener('click', function (ev) { ev.stopPropagation(); onToggle(); }); }
      c.title = (FAMILY_WORDS[fam] || fam) + (onToggle ? (on ? ' - drawn; tap to drop' : ' - not drawn; tap to add') : '');
      return c;
    }

    function nodeFor(leg, i, legs) {
      var n = make('div', 'hf-node hf-leg hf-' + (leg.place || 'middle') + (state.selected === leg.id ? ' selected' : ''));
      n.dataset.legId = String(leg.id);
      var top = make('div', 'hf-node-top');
      top.appendChild(make('b', '', cutWords(leg.label || leg.id, 60)));
      top.appendChild(make('span', 'hf-seat', 'seat ' + (leg.seat || 'alternate')));
      top.appendChild(make('span', 'hf-place', PLACE_WORD[leg.place] || leg.place || ''));
      if (leg.splits) top.appendChild(make('span', 'hf-place', 'splits'));
      n.appendChild(top);
      n.appendChild(make('p', 'hf-act', cutWords(leg.act || '(no act yet)', 220)));
      var chips = make('div', 'hf-chips');
      familiesOf(leg).forEach(function (f) { chips.appendChild(chip(f, true)); });
      n.appendChild(chips);
      var inner = (leg.inner || []).length;
      var tools = make('div', 'hf-tools');
      tool(tools, inner ? 'exchanges (' + inner + ')' : 'deepen', 'Select this turn: edit it and give it inner exchanges (micro-exchanges planned right after it)', function () { select(leg.id); }, 'hf-tool-deepen');
      tool(tools, 'insert after', 'Insert a new turn right after this one', function () { legs.splice(i + 1, 0, newLeg(legs, leg)); touched(); state.selected = legs[i + 1].id; paint(); });
      tool(tools, 'extend', 'Extend this turn: a continuation of it follows as the next turn', function () { legs.splice(i + 1, 0, extendLeg(legs, leg)); touched(); paint(); });
      tool(tools, 'up', 'Move this turn up', function () { if (i > 0) { legs.splice(i - 1, 0, legs.splice(i, 1)[0]); touched(); paint(); } }).disabled = i === 0;
      tool(tools, 'down', 'Move this turn down', function () { if (i < legs.length - 1) { legs.splice(i + 1, 0, legs.splice(i, 1)[0]); touched(); paint(); } }).disabled = i === legs.length - 1;
      tool(tools, 'remove', 'Remove this turn' + (legs.length <= 1 ? ' (the last one stays)' : ''), function () {
        if (legs.length <= 1) { note('a shape keeps at least one turn'); return; }
        legs.splice(i, 1); if (state.selected === leg.id) state.selected = null; touched(); paint();
      }, 'hf-tool-remove').disabled = legs.length <= 1;
      n.appendChild(tools);
      n.addEventListener('click', function () { select(state.selected === leg.id ? null : leg.id); });
      return n;
    }
    function tool(host, label, title, fn, cls) {
      var b = make('button', 'hf-tool' + (cls ? ' ' + cls : ''), label);
      b.type = 'button'; b.title = title;
      b.addEventListener('click', function (ev) { ev.stopPropagation(); fn(); });
      host.appendChild(b);
      return b;
    }
    function select(id) { state.selected = id; paint(); }

    /* --- the inspector: the selected turn and its micro-exchanges ------------ */
    function paintInspect(leg, legs) {
      inspect.textContent = '';
      inspect.hidden = false;
      var head = make('div', 'hf-inspect-head');
      head.appendChild(make('b', '', 'Turn: ' + cutWords(leg.label || leg.id, 60)));
      var done = make('button', 'hf-btn hf-small', 'done');
      done.type = 'button'; done.title = 'Close this panel (the edits stay in the draft)';
      done.addEventListener('click', function () { select(null); });
      head.appendChild(done);
      inspect.appendChild(head);

      var grid = make('div', 'hf-fields');
      var label = field(grid, 'label', 'input'); label.value = leg.label || '';
      label.addEventListener('input', function () { leg.label = label.value; touched(); });
      label.addEventListener('change', function () { paint(); });
      var place = field(grid, 'place', 'select');
      PLACES.forEach(function (p) { var o = make('option', '', p[1]); o.value = p[0]; place.appendChild(o); });
      place.value = leg.place || 'middle';
      place.addEventListener('change', function () { leg.place = place.value; touched(); paint(); });
      var seat = field(grid, 'seat', 'select');
      SEATS.forEach(function (s) { var o = make('option', '', s[1]); o.value = s[0]; seat.appendChild(o); });
      seat.value = leg.seat || 'alternate';
      seat.addEventListener('change', function () { leg.seat = seat.value; touched(); paint(); });
      var act = field(grid, 'act - what this turn does', 'textarea'); act.rows = 3; act.value = leg.act || '';
      act.addEventListener('input', function () { leg.act = act.value; touched(); });
      act.addEventListener('change', function () { paint(); });
      inspect.appendChild(grid);

      var fams = make('div', 'hf-fam-row');
      fams.appendChild(make('span', 'hf-label', 'draws'));
      FAMILIES.forEach(function (f) {
        fams.appendChild(chip(f, familiesOf(leg).indexOf(f) >= 0, function () { toggleFamily(leg, f); touched(); paint(); }));
      });
      inspect.appendChild(fams);

      var ex = make('section', 'hf-exchanges');
      ex.setAttribute('aria-label', 'Micro-exchanges');
      var exHead = make('div', 'hf-inspect-head');
      exHead.appendChild(make('b', '', 'Micro-exchanges inside this turn'));
      exHead.appendChild(make('span', 'hf-sub', 'each one is a turn planned right after it, in this order'));
      ex.appendChild(exHead);
      var rows = leg.inner = Array.isArray(leg.inner) ? leg.inner : [];
      if (!rows.length) ex.appendChild(make('div', 'hf-empty', 'no exchanges yet - add one to give this turn more inner conversational depth'));
      rows.forEach(function (r, k) {
        var line = make('div', 'hf-exchange');
        line.appendChild(make('span', 'hf-ex-n', String(k + 1)));
        var s = make('select', 'hf-select'); s.setAttribute('aria-label', 'Seat of exchange ' + (k + 1));
        SEATS.forEach(function (st) { var o = make('option', '', st[0]); o.value = st[0]; o.title = st[1]; s.appendChild(o); });
        s.value = r.seat || 'alternate';
        s.addEventListener('change', function () { r.seat = s.value; touched(); paint(); });
        line.appendChild(s);
        var a = make('input', 'hf-input'); a.type = 'text'; a.value = r.act || ''; a.placeholder = 'what this exchange does';
        a.setAttribute('aria-label', 'Act of exchange ' + (k + 1));
        a.addEventListener('input', function () { r.act = a.value; touched(); });
        a.addEventListener('change', function () { paint(); });
        line.appendChild(a);
        var fr = make('span', 'hf-chips');
        FAMILIES.forEach(function (f) {
          var on = f === 'ES' || (r.families || []).indexOf(f) >= 0;
          fr.appendChild(chip(f, on, f === 'ES' ? function () { note('ES rides every exchange - a turn always has a feeling'); } : function () {
            var list = (r.families || []).filter(function (g) { return g !== f; });
            if (!on) list.push(f);
            r.families = list; touched(); paint();
          }));
        });
        line.appendChild(fr);
        var rm = make('button', 'hf-tool hf-tool-remove', 'remove');
        rm.type = 'button'; rm.title = 'Remove this exchange';
        rm.addEventListener('click', function () { rows.splice(k, 1); touched(); paint(); });
        line.appendChild(rm);
        ex.appendChild(line);
      });
      var add = make('button', 'hf-btn hf-small', 'add an exchange');
      add.type = 'button'; add.title = 'One more turn planned right after this one';
      add.addEventListener('click', function () {
        rows.push({seat: 'alternate', act: rows.length ? 'answers the exchange before, in one breath.' : 'asks one thing about what was just said.', families: ['ES', 'RS']});
        touched(); paint();
      });
      ex.appendChild(add);
      inspect.appendChild(ex);
    }
    function field(grid, label, kind) {
      var lab = make('label', 'hf-field');
      lab.appendChild(make('span', '', label));
      var input = make(kind, kind === 'select' ? 'hf-select' : kind === 'textarea' ? 'hf-textarea' : 'hf-input');
      input.setAttribute('aria-label', label);
      lab.appendChild(input);
      grid.appendChild(lab);
      return input;
    }

    load();
    return {
      reload: load,
      close: function () { state.dead = true; },
      state: function () { return state; },
      setScope: setScope,
      deselect: function () { select(null); },
      host: host
    };
  }

  /* ------------------------------------------------------------ the sheet */
  function entryPicker(panel, opts) {
    /* opened with no entry (the PiP tools page): the hour on air, one button per entry */
    panel.textContent = '';
    panel.classList.add('hf-host');
    var bar = make('div', 'hf-bar');
    var title = make('div', 'hf-title'); title.appendChild(make('b', '', 'THE HOUR')); title.appendChild(make('span', 'hf-title-sub', 'pick an entry to shape'));
    bar.appendChild(title);
    var status = make('span', 'hf-status', 'reading the hour...'); bar.appendChild(status);
    var x = make('button', 'hf-x'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close'); x.appendChild(svgX());
    x.addEventListener('click', close); bar.appendChild(x);
    panel.appendChild(bar);
    var list = make('div', 'hf-body hf-pick'); panel.appendChild(list);
    var get = typeof opts.get === 'function' ? opts.get : function (p) { return request('GET', p); };
    get('/api/schedule/hours?count=1').then(function (d) {
      var hour = ((d && d.hours) || [])[0];
      if (!hour) { status.textContent = 'no hour came back'; return; }
      status.textContent = String(hour.label || hour.key || '');
      (hour.slots || []).forEach(function (s) {
        var b = make('button', 'hf-pick-btn');
        b.type = 'button';
        b.appendChild(make('b', '', String(s.label || s.kind)));
        b.appendChild(make('span', 'hf-sub', String(s.starts_at || '') + '  ' + String(s.kind || '') + '  ' + String(s.minutes || '') + 'm'));
        b.addEventListener('click', function () {
          open({road: s.kind, kind: s.kind, slot_id: s.id, label: s.label || s.kind, hour: hour.key, get: opts.get, put: opts.put, del: opts.del,
                onBack: function () { open(opts); }});
        });
        list.appendChild(b);
      });
    }).catch(function (e) { status.textContent = 'the hour could not be read: ' + String(e && e.message || e); });
  }

  function open(opts) {
    opts = opts || {};
    close();
    var overlay = make('section', 'hf-overlay');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', 'The hour, as a flowchart');
    var panel = make('div', 'hf-panel');
    overlay.appendChild(panel);
    (opts.host || doc.body).appendChild(overlay);
    ui.overlay = overlay;
    if (!opts.road && !opts.kind) {
      entryPicker(panel, opts);
    } else {
      ui.ctl = mount(panel, Object.assign({}, opts, {
        onBack: function () { close(); if (typeof opts.onBack === 'function') opts.onBack(); },
        onClose: function () { close(); if (typeof opts.onClose === 'function') opts.onClose(); else if (typeof opts.onBack === 'function') opts.onBack(); }
      }));
    }
    /* Escape closes the selected turn's panel first (the draft stays), then the sheet */
    ui.onKey = function (ev) {
      if (ev.key !== 'Escape') return;
      if (ui.ctl && ui.ctl.state().selected) { ui.ctl.deselect(); return; }
      var leave = opts.onBack;
      close();
      if (typeof leave === 'function') { try { leave(); } catch (e) { /* the host's door */ } }
    };
    doc.addEventListener('keydown', ui.onKey);
    return ui.ctl;
  }
  function close() {
    if (ui.ctl) { try { ui.ctl.close(); } catch (e) { /* already gone */ } ui.ctl = null; }
    if (ui.overlay) { ui.overlay.remove(); ui.overlay = null; }
    if (ui.onKey) { doc.removeEventListener('keydown', ui.onKey); ui.onKey = null; }
  }

  root.PineHourFlow = {open: open, close: close, mount: mount, request: request, FAMILIES: FAMILIES.slice(),
    isOpen: function () { return !!ui.overlay; }, VERSION: '2026-10-06'};
})(typeof window !== 'undefined' ? window : globalThis);
